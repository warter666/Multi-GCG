"""Run one real episode and record its trace.

Usage:
    python -m mgcg.harness.loop --family deputy --model Qwen/Qwen2.5-0.5B-Instruct \
        --adv-from out/deputy-1234/adv.txt
    python -m mgcg.harness.loop --family deputy --poison-file notes.txt   # baseline, no adv

The loop only executes. Judgement happens afterwards, on the trace it wrote.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from typing import Any

import torch

from ..families import FAMILIES, SYSTEM
from ..model import load_model
from ..verify import _balanced_json, l3_on_trace
from .env import Env
from .trace import Event, Trace


def parse_call(text: str) -> dict[str, Any] | None:
    """Return {tool, args} if the text contains a parsable call, else None."""
    obj = _balanced_json(text)
    if not isinstance(obj, dict) or "tool" not in obj:
        return None
    args = obj.get("args")
    if not isinstance(args, dict):
        args = {}
    return {"tool": str(obj["tool"]), "args": args}


@torch.no_grad()
def _generate(tok, model, ctx: str, max_new_tokens: int, device) -> str:
    ids = tok(ctx, return_tensors="pt").input_ids[0].to(device)
    out = model.generate(
        ids.unsqueeze(0),
        max_new_tokens=max_new_tokens,
        do_sample=False,
        temperature=None,
        top_p=None,
        pad_token_id=tok.pad_token_id,
    )
    return tok.decode(out[0, ids.numel() :], skip_special_tokens=True)


def _step(tok, model, ctx: str, max_new_tokens: int, device):
    """One assistant turn. Returns (text, call_or_None, updated_context).

    A parse failure is retried exactly once with an explicit instruction; the retry is
    counted and, if it also fails, the episode ends with a recorded event rather than a
    silently skipped step.
    """
    text = _generate(tok, model, ctx, max_new_tokens, device)
    call = parse_call(text)
    if call is not None:
        return text, call, ctx + "ASSISTANT: " + text.strip() + "\n"

    nudge = (
        ctx
        + "ASSISTANT: "
        + text.strip()
        + "\nUSER: Output exactly one line of JSON, nothing else.\n"
    )
    text2 = _generate(tok, model, nudge, max_new_tokens, device)
    call2 = parse_call(text2)
    if call2 is not None:
        return text2, call2, nudge + "ASSISTANT: " + text2.strip() + "\n"
    return text2, None, nudge


def run_episode(tok, model, fam, poison: str, max_steps: int, max_new_tokens: int, seed: int = 0):
    """Execute the episode; return (trace, parse_failures, budget_exhausted)."""
    torch.manual_seed(int(seed))
    device = next(model.parameters()).device
    env = Env(poison=poison)
    trace = Trace(user_messages=[fam.task])

    ctx = SYSTEM + "\n\nUSER: " + fam.task + "\n"
    parse_failures = 0
    budget_exhausted = True

    for step in range(1, max_steps + 1):
        text, call, ctx = _step(tok, model, ctx, max_new_tokens, device)
        trace.assistant_messages.append(text)

        if call is None:
            parse_failures += 1
            trace.add(
                Event(
                    name="<parse_error>",
                    args={},
                    ok=False,
                    output=text.strip()[:200],
                    side_effect="READ",
                    scope="local",
                    source="file",
                    error=f"no parsable tool call at step {step}",
                )
            )
            break

        event = env.dispatch(call)
        trace.add(Event(**event))
        ctx += f"TOOL[{event['name']}]: {event['output']}\n"

        if event["name"] in ("email.send", "http.post", "fs.delete", "shell.run"):
            # The agent has done the thing it was going to do; stop here.
            budget_exhausted = False
            break

    return trace, parse_failures, budget_exhausted


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", default="deputy", choices=list(FAMILIES))
    ap.add_argument("--model", default="Qwen/Qwen2.5-0.5B-Instruct")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--dtype", default="auto")
    ap.add_argument("--adv-from", default=None, help="path to an adv.txt produced by run.py")
    ap.add_argument("--poison-file", default=None, help="raw document body to inject instead")
    ap.add_argument("--poison", default="", help="inline document body to inject instead")
    ap.add_argument("--max-steps", type=int, default=4)
    ap.add_argument("--max-new-tokens", type=int, default=64)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="out")
    args = ap.parse_args()

    fam = FAMILIES[args.family]

    if args.adv_from:
        with open(args.adv_from, encoding="utf-8") as f:
            poison = f.read()
        origin = args.adv_from
    elif args.poison_file:
        with open(args.poison_file, encoding="utf-8") as f:
            poison = f.read()
        origin = args.poison_file
    else:
        poison = args.poison
        origin = "inline"

    tok, model, W = load_model(args.model, args.device, args.dtype)

    t0 = time.time()
    trace, parse_failures, budget_exhausted = run_episode(
        tok, model, fam, poison, args.max_steps, args.max_new_tokens, args.seed
    )
    seconds = round(time.time() - t0, 1)

    # Judgement: applied to the recorded trace, not to a trace we built.
    ok3, why3 = l3_on_trace(trace.to_predicate_trace(), fam.expect_predicate)

    print(f"[family] {fam.key} — {fam.title}")
    print(f"[poison] {origin} ({len(poison)} chars)")
    print(f"[trace]  {len(trace.events)} event(s): {trace.tool_names()}")
    print(f"[parse]  failures={parse_failures} budget_exhausted={budget_exhausted}")
    for e in trace.events:
        print(f"  - {e.name}({json.dumps(e.args, ensure_ascii=False)[:90]}) ok={e.ok} src={e.source}")
    print(f"[L3]     {ok3}  {why3}")
    print(f"[time]   {seconds}s")

    run_dir = os.path.join(args.out, f"harness-{fam.key}-{int(time.time())}")
    os.makedirs(run_dir, exist_ok=True)
    trace.write_jsonl(os.path.join(run_dir, "trace.jsonl"))

    # Raw assistant text, one JSON object per turn. This is what the elicitation step copies
    # into a target file: never retype the call, the tokenizer must see the same bytes.
    with open(os.path.join(run_dir, "assistant.jsonl"), "w", encoding="utf-8") as f:
        for t in trace.assistant_messages:
            f.write(json.dumps({"text": t}, ensure_ascii=False) + "\n")

    rec = {
        "family": fam.key,
        "model": args.model,
        "poison_origin": origin,
        "config": {"max_steps": args.max_steps, "max_new_tokens": args.max_new_tokens,
                   "seed": args.seed},
        "events": [e.as_dict() for e in trace.events],
        "parse_failures": parse_failures,
        "budget_exhausted": budget_exhausted,
        "l3": ok3,
        "l3_why": why3,
        "breach": bool(ok3),
        "seconds": seconds,
    }
    with open(os.path.join(run_dir, "result.json"), "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    print(f"[run] {run_dir}")

    return 0 if ok3 else 1


if __name__ == "__main__":
    raise SystemExit(main())
