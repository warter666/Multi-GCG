"""CW, rebuilt for a discrete target.

Carlini and Wagner's attack minimises a margin loss with a confidence gap `k` and takes the
best of several restarts. Both halves were missing from the coordinate search this repo
started with: the loss was a plain likelihood, and one greedy pass over random restarts of
size one was reported as a result. The margin loss and the restarts are the two things that
make an attack reproducible, so they are the whole of this file.

The search runs on a hand-built token sequence (`JudgeSurface`). Nothing is reported until it
has been re-scored as a decoded string, because that is what the guard reads.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time

import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from mgcg.attacks.common import INVISIBLE, JudgeSurface, allowed_ids  # noqa: E402
from mgcg.deploy.guards import Judge  # noqa: E402
from mgcg.deploy.world import EMAILS  # noqa: E402
from mgcg.model import load_model  # noqa: E402


def mean_nll(tok, model, text: str, device) -> tuple[float, int]:
    """Teacher-forced mean nll of a string under the same model. Reported, never gated.

    The ppl gate in this repo has already been shown to measure tokenisation rather than
    naturalness; this number is here so a reader can see what a payload costs in fluency, not
    so the search can be stopped by it.
    """
    ids = tok(text, return_tensors="pt").input_ids.to(device)
    with torch.no_grad():
        logits = model(ids).logits.float()
    tgt = ids[0, 1:]
    lp = torch.log_softmax(logits[0, :-1], dim=-1)
    nll = -lp.gather(1, tgt.unsqueeze(1)).squeeze(1)
    return float(nll.mean()), int(ids.shape[1])


def cw_search(surface: JudgeSurface, vocab_ids: torch.Tensor, *, steps: int, suffix_len: int,
              cand: int, win: int, k: float, seed: int, batch: int = 16,
              strict: frozenset[str] | None = None, patience: int = 4,
              prune: bool = True) -> dict:
    """One restart: coordinate search on the CW margin, stopping once the gap clears k.

    The gradient is computed on a hand-concatenated token sequence, but nothing is accepted
    unless the decoded string improves on the guard's own number. Those two are not the same
    function: the guard scores a string it tokenises itself, and an id sequence assembled from
    separate pieces tokenises differently at the joins. Ranking candidates on the surrogate
    would report progress the guard does not agree with.

    `strict` keeps only candidates whose decoded string is made entirely of those characters.
    Constraining the vocabulary by token id is not enough, because re-encoding a run of
    invisible tokens can come back as visible punctuation; a carrier guarantee has to hold on
    the string, since the string is what a person and a filter both read.
    """
    rng = random.Random(seed)
    device = surface.device
    vlist = vocab_ids.tolist()
    suffix_ids = [rng.choice(vlist) for _ in range(max(1, suffix_len))]
    suffix = surface.tok.decode(suffix_ids, skip_special_tokens=False)
    if strict is not None and not all(c in strict for c in suffix):
        suffix = next(iter(strict)) * max(1, suffix_len)
        suffix = surface.tok.decode(
            surface.tok(suffix, add_special_tokens=False).input_ids,
            skip_special_tokens=False)

    mask = torch.full((surface.embed.num_embeddings,), float("-inf"), device=device)
    mask[vocab_ids.to(device)] = 0.0

    start = surface.score_text(suffix)
    best = start.margin
    edits = 0
    used = 0
    stall = 0
    trail = [round(best, 4)]

    for step in range(1, steps + 1):
        if best >= k:
            break
        used = step
        # The current string, tokenised as it stands. The gradient is about this sequence.
        cur = surface.tok(suffix, add_special_tokens=False).input_ids
        g = surface.grad(cur)
        pos = list(range(len(cur)))
        rng.shuffle(pos)
        pos = pos[:win]
        props = []
        for p in pos:
            gp = g[len(surface.head_ids) + p].to(surface.embed.weight.dtype)
            proj = torch.matmul(surface.embed.weight, gp) + mask
            for t in torch.topk(proj, k=min(cand, proj.numel())).indices.tolist():
                if int(t) == cur[p]:
                    continue
                c = list(cur)
                c[p] = int(t)
                s = surface.tok.decode(c, skip_special_tokens=False)
                if strict is not None and not all(ch in strict for ch in s):
                    continue
                props.append(s)
        if not props:
            break

        gains = []
        for s in range(0, len(props), batch):
            z_yes, z_no = surface.score_texts(props[s : s + batch])
            gains.extend((z_no - z_yes).tolist())
        i = int(torch.tensor(gains).argmax().item())
        if gains[i] <= best:
            # A single window of `win` positions produced no improvement. Ending the restart
            # here is what made half of them die after two steps: the wrong positions were
            # sampled, not a dead end. Keep going until `patience` steps pass without a gain,
            # which gives the shuffle a chance to reach the positions that do move the margin.
            stall += 1
            if stall >= patience:
                break
            continue
        best = gains[i]
        suffix = props[i]
        edits += 1
        stall = 0
        trail.append(round(best, 4))

    # CW's second half: minimise the edit, not just the loss. Once the margin holds, drop one
    # token at a time and keep the drop whenever the margin still clears k. The result is the
    # suffix a defender would actually have to explain, not the one that happened to score
    # best. Token count before and after is reported because "10 tokens cleared it" and
    # "2 tokens cleared it" are different claims about the guard.
    pruned_from = len(surface.tok(suffix, add_special_tokens=False).input_ids)
    if prune and best >= k:
        ids = surface.tok(suffix, add_special_tokens=False).input_ids
        again = True
        while again and ids:
            again = False
            for p in range(len(ids)):
                cand = ids[:p] + ids[p + 1:]
                s = surface.tok.decode(cand, skip_special_tokens=False) if cand else ""
                if strict is not None and not all(ch in strict for ch in s):
                    continue
                m = surface.score_text(s).margin
                if m >= k:
                    ids, suffix, best = cand, s, m
                    again = True
                    break
        pruned_to = len(ids)
    else:
        pruned_to = pruned_from

    real = surface.score_text(suffix)
    nll, ntok = mean_nll(surface.tok, surface.model, suffix, device) if suffix.strip() else (0.0, 0)
    return {
        "seed": seed,
        "init_margin": round(start.margin, 4),
        "best_margin": round(best, 4),
        "cleared_k": best >= k,
        "steps": used,
        "edits": edits,
        "stalled": stall,
        "trail": trail,
        "suffix": suffix,
        "real_p_act": round(real.p_act, 4),
        "real_margin": round(real.margin, 4),
        "nll": round(nll, 3),
        "tokens": ntok,
        "tokens_before_prune": pruned_from,
        "tokens_after_prune": pruned_to,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen2.5-1.5B-Instruct")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--dtype", default="auto")
    ap.add_argument("--body", default=EMAILS[0]["body"],
                    help="fixed text the judge reads before the payload")
    ap.add_argument("--prefix-text", default="",
                    help="payload part that is kept verbatim, e.g. the instruction that works")
    ap.add_argument("--prefix-file", default=None)
    ap.add_argument("--vocab", default="full", choices=["full", "ascii", "invisible"])
    ap.add_argument("--k", type=float, default=1.0,
                    help="confidence gap in logit units; 0 would be a bare flip past 0.5")
    ap.add_argument("--steps", type=int, default=40)
    ap.add_argument("--restarts", type=int, default=6)
    ap.add_argument("--suffix-len", type=int, default=16)
    ap.add_argument("--cand", type=int, default=24)
    ap.add_argument("--win", type=int, default=2)
    ap.add_argument("--patience", type=int, default=4,
                    help="steps without a gain before a restart is abandoned")
    ap.add_argument("--no-prune", action="store_true",
                    help="keep every token the search added instead of minimising the edit")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--verify-layers", default=None,
                    help="comma list from l1,l2,l3: run the episode on the best payload")
    ap.add_argument("--verify-runs", type=int, default=1)
    ap.add_argument("--max-steps", type=int, default=4)
    ap.add_argument("--max-new-tokens", type=int, default=256)
    ap.add_argument("--out", default="out")
    args = ap.parse_args()

    prefix = args.prefix_text
    if args.prefix_file:
        with open(args.prefix_file, encoding="utf-8") as f:
            prefix = f.read().strip()

    tok, model, _ = load_model(args.model, args.device, args.dtype)
    judge = Judge(tok, model)
    surface = JudgeSurface(tok, model, judge, args.body, prefix)
    surface.verify()
    vocab_ids = allowed_ids(tok, args.vocab)

    base = surface.score_text("")
    print(f"[model]   {args.model}  vocab {len(vocab_ids)} ids ({args.vocab})")
    print(f"[prefix]  {prefix[:160]!r}")
    print(f"[base]    p_act={base.p_act:.4f}  margin={base.margin:+.3f}  "
          f"(threshold {judge.threshold}, k={args.k})")
    print(f"[search]  restarts={args.restarts} steps={args.steps} len={args.suffix_len} "
          f"cand={args.cand} win={args.win} patience={args.patience} "
          f"prune={not args.no_prune}")

    t0 = time.time()
    rows = []
    strict = frozenset(INVISIBLE) if args.vocab == "invisible" else None
    if strict:
        print("[strict]  every candidate must decode to invisible characters only")
    for r in range(args.restarts):
        rec = cw_search(surface, vocab_ids, steps=args.steps, suffix_len=args.suffix_len,
                        cand=args.cand, win=args.win, k=args.k, seed=args.seed + r,
                        strict=strict, patience=args.patience, prune=not args.no_prune)
        rows.append(rec)
        print(f"  [r{r}] init {rec['init_margin']:+.3f} -> best {rec['best_margin']:+.3f} "
              f"(real p={rec['real_p_act']:.4f}) steps={rec['steps']} edits={rec['edits']} "
              f"tokens {rec['tokens_before_prune']}->{rec['tokens_after_prune']} "
              f"nll={rec['nll']} {'CLEARED' if rec['cleared_k'] else ''}")
    elapsed = round(time.time() - t0, 1)

    # Best restart by the number the guard would actually compute, not by the surrogate.
    best = min(rows, key=lambda r: r["real_p_act"])
    payload = prefix + best["suffix"]
    ok = best["real_p_act"] < judge.threshold
    cleared = sum(r["cleared_k"] for r in rows)
    steps = sorted(r["steps"] for r in rows if r["cleared_k"])
    med = steps[len(steps) // 2] if steps else 0
    print(f"\n[best]    real p_act={best['real_p_act']:.4f} "
          f"({'judge says SAFE' if ok else 'judge still blocks'})  "
          f"cleared {cleared}/{len(rows)} restarts at k={args.k}"
          f"{f', median {med} steps to clear' if cleared else ''}")
    print(f"[minimal] {best['tokens_before_prune']} -> {best['tokens_after_prune']} tokens "
          f"after minimising the edit")
    print(f"[payload] {payload[:400]!r}")

    verify = None
    if args.verify_layers:
        from mgcg.deploy.episode import run_episode

        layers = {s.strip() for s in args.verify_layers.split(",") if s.strip()}
        j = judge if "l2" in layers else None
        res = []
        for i in range(args.verify_runs):
            run = run_episode(tok, model, payload, layers, max_steps=args.max_steps,
                              max_new_tokens=args.max_new_tokens, seed=args.seed + i, judge=j)
            a, why_a = run.attack()
            t, why_t = run.task()
            res.append({"attack": a, "task": t, "why_attack": why_a, "why_task": why_t,
                        "judge": run.judge_scores,
                        "blocked": [e.get("blocked_by") for e in run.events if e.get("blocked_by")],
                        "events": [{k: e[k] for k in ("name", "args", "ok", "blocked_by")}
                                   for e in run.events if not e["name"].startswith("<")]})
            print(f"  [verify {i}] A={a} T={t}  judge={run.judge_scores} "
                  f"blocked={res[-1]['blocked']}")
        verify = {"layers": sorted(layers), "rows": res}

    run_dir = os.path.join(args.out, f"cw-{int(time.time())}")
    os.makedirs(run_dir, exist_ok=True)
    rec = {"model": args.model, "vocab": args.vocab, "k": args.k, "prefix": prefix,
           "body": args.body, "base": {"p_act": base.p_act, "margin": base.margin},
           "config": {k: getattr(args, k) for k in
                      ("steps", "restarts", "suffix_len", "cand", "win", "seed")},
           "restarts": rows, "best": best, "payload": payload,
           "judge_says_safe": ok, "seconds": elapsed, "verify": verify}
    with open(os.path.join(run_dir, "result.json"), "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    with open(os.path.join(run_dir, "payload.txt"), "w", encoding="utf-8") as f:
        f.write(payload)
    print(f"[out]     {run_dir}  ({elapsed}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
