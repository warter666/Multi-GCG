"""One assistant turn: generate, parse the call, retry once.

These three functions lived inside the competition-era harness, so the deployment stack pulled
in that whole package -- families, verification, the old filters -- just to read a JSON call.
They are pure here: a tokenizer, a model, a string in, a string out. No guards, no scoring, no
knowledge of what an episode is for. That is what lets `mgcg/deploy` stand on its own.
"""

from __future__ import annotations

import json
from typing import Any

import torch


def parse_calls(text: str) -> list[dict[str, Any]]:
    """Return every parsable call in one turn, in order.

    A real agent batches tool calls: one assistant turn can ask for two reads. Executing only
    the first one drops work the model did ask for, which then looks like a reasoning failure.
    Every balanced JSON object with a `tool` key counts.

    This is deliberately strict about the JSON itself: an object that stops mid-string is
    dropped, not repaired. A deployment would constrain decoding instead, so a malformed call
    is a property of this harness as much as of the model. That is why episodes count
    `parse_failures` and report them next to the two axes.
    """
    out: list[dict[str, Any]] = []
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        depth = 0
        for j in range(i, len(text)):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[i : j + 1])
                    except Exception:  # noqa: BLE001
                        break
                    if isinstance(obj, dict) and "tool" in obj:
                        args = obj.get("args")
                        out.append(
                            {"tool": str(obj["tool"]),
                             "args": args if isinstance(args, dict) else {}}
                        )
                    break
    return out


def parse_call(text: str) -> dict[str, Any] | None:
    calls = parse_calls(text)
    return calls[0] if calls else None


@torch.no_grad()
def generate(tok, model, ctx: str, max_new_tokens: int, device) -> str:
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


def step(tok, model, ctx: str, max_new_tokens: int, device):
    """One assistant turn. Returns (text, calls, updated_context).

    A parse failure is retried exactly once with an explicit instruction; the retry is counted
    and, if it also fails, the episode ends with a recorded event rather than a silently
    skipped step.
    """
    text = generate(tok, model, ctx, max_new_tokens, device)
    calls = parse_calls(text)
    if calls:
        return text, calls, ctx + "ASSISTANT: " + text.strip() + "\n"

    nudge = (
        ctx
        + "ASSISTANT: "
        + text.strip()
        + "\nUSER: Output exactly one line of JSON, nothing else.\n"
    )
    text2 = generate(tok, model, nudge, max_new_tokens, device)
    calls2 = parse_calls(text2)
    if calls2:
        return text2, calls2, nudge + "ASSISTANT: " + text2.strip() + "\n"
    return text2, [], nudge
