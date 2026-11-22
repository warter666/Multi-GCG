"""Entry point: hard gates -> optimize one input span -> generate once -> three-level verify.

Usage (8 GB card, start with a 0.5B model to validate the pipeline):
    python run.py --family deputy --model Qwen/Qwen2.5-0.5B-Instruct --steps 20
    python run.py --family exfil  --model Qwen/Qwen2.5-1.5B-Instruct --objective margin
    python run.py --family deputy --dry-run          # layout and baseline only, no search
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import replace

import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from legacy.families import FAMILIES, SECRET, build_layout
from legacy.gate import gate
from legacy.gcg import GCGConfig, init_adv, objective_from, run_gcg
from legacy.harness import filters
from legacy import invisible
from legacy.layout import adv_nll_from_logits, loss_from_logits, margin_from_logits
from mgcg.model import load_model
from legacy.verify import failure_kind, verify


def generate(tok, model, ids, max_new_tokens: int) -> str:
    with torch.no_grad():
        out = model.generate(
            ids.unsqueeze(0),
            max_new_tokens=max_new_tokens,
            do_sample=False,
            temperature=None,
            top_p=None,
            pad_token_id=tok.pad_token_id,
        )
    return tok.decode(out[0, ids.numel() :], skip_special_tokens=True)


@torch.no_grad()
def probe(model, W, layout, adv):
    """Return (nll, margin, adv_nll) for the current adv."""
    emb = layout.assemble(W[adv], W)
    logits = model(inputs_embeds=emb, use_cache=False).logits
    return (
        float(loss_from_logits(logits, layout)),
        float(margin_from_logits(logits, layout)),
        float(adv_nll_from_logits(logits, layout, adv)),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", default="deputy", choices=list(FAMILIES))
    ap.add_argument("--model", default="Qwen/Qwen2.5-0.5B-Instruct")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--dtype", default="auto")
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--top-k", type=int, default=256)
    ap.add_argument("--batch", type=int, default=128)
    ap.add_argument("--chunk", type=int, default=16, help="lower to 8 when memory is tight")
    ap.add_argument("--adv-len", type=int, default=16)
    ap.add_argument("--max-new-tokens", type=int, default=64)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--objective", default="nll", choices=["nll", "margin", "both"])
    ap.add_argument("--margin-weight", type=float, default=1.0)
    ap.add_argument("--alpha", type=float, default=1.0, help="power-law exponent")
    ap.add_argument("--ppl-weight", type=float, default=0.0,
                    help="weight of the payload-fluency penalty; 0 = unconstrained search")
    ap.add_argument("--ppl-warm-frac", type=float, default=0.0,
                    help="fraction of steps that hold the penalty at full weight before it "
                         "decays linearly to zero; 0 keeps it constant")
    ap.add_argument("--invisible-only", action="store_true",
                    help="restrict the search to vocabulary ids that render as zero-width text")
    ap.add_argument("--no-power-law", action="store_true", help="fall back to uniform rank sampling")
    ap.add_argument(
        "--target-mode",
        default="auto",
        choices=["auto", "concrete", "structural"],
        help="concrete = bake the runtime value in (offline approximation); "
        "structural = optimize only up to the field opening",
    )
    ap.add_argument("--target-from", default=None,
                    help="file with the exact call text the model emitted (concrete targets only)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default="out")
    args = ap.parse_args()

    fam = FAMILIES[args.family]
    print(f"[family] {fam.key} — {fam.title}")

    tok, model, W = load_model(args.model, args.device, args.dtype)
    dev = W.device

    target_override = None
    if args.target_from:
        with open(args.target_from, encoding="utf-8") as f:
            target_override = f.read().strip()

    layout, head, target_text, structural = build_layout(
        fam, tok, args.adv_len, dev, mode=args.target_mode, target_override=target_override
    )
    print(f"[layout] before={layout.before_ids.numel()} adv={args.adv_len} after={layout.after_ids.numel()}")
    # Print the target actually being optimised, not the family default: --target-from can
    # replace it, and a stale line here makes the whole run look like it optimised something else.
    print(f"[target] {target_text}")
    if structural:
        print(f"[structural] target contains the runtime variable `{fam.runtime_arg}`: "
              f"optimize only up to the field opening")
        print("[structural] the remaining tokens are the value itself; we do not fit them")

    # Hard gates: do not continue if they fail, otherwise everything downstream optimizes a
    # different trajectory than the one being verified.
    g = gate(tok, layout, head, target_text, args.adv_len)
    for c in g["checks"]:
        print(f"[gate] {'OK  ' if c['ok'] else 'FAIL'} {c['why']}")
    if not g["ok"]:
        print("[gate] gate failed, stopping. Fix build_layout; do not bypass the check.")
        return 2

    pool = None
    mask = None
    if args.invisible_only:
        pool = invisible.invisible_ids(tok)
        print(f"[carrier] {len(pool)} invisible ids of {tok.vocab_size}")
        mask = invisible.as_mask(pool, tok.vocab_size, dev)

    adv = init_adv(tok, args.adv_len, dev, args.seed, allowed=pool)
    base_nll, base_m, base_p = probe(model, W, layout, adv)
    print(f"[baseline] nll={base_nll:.4f} margin={base_m:+.4f} ppl={base_p:.4f}")

    cfg = GCGConfig(
        steps=args.steps,
        top_k=args.top_k,
        batch=args.batch,
        chunk=args.chunk,
        seed_len=args.adv_len,
        seed=args.seed,
        objective=args.objective,
        margin_weight=args.margin_weight,
        alpha=args.alpha,
        power_law=not args.no_power_law,
        ppl_weight=args.ppl_weight,
        ppl_warm_frac=args.ppl_warm_frac,
        mask=mask,
    )
    if args.ppl_weight > 0 and args.ppl_warm_frac > 0:
        hold = max(1, round(args.steps * args.ppl_warm_frac))
        print(f"[schedule] w={args.ppl_weight:.2f} for {hold} step(s), "
              f"then linear decay to 0 over the remaining {max(0, args.steps - hold)}")

    run_dir = os.path.join(args.out, f"{fam.key}-{int(time.time())}")
    os.makedirs(run_dir, exist_ok=True)
    events_path = os.path.join(run_dir, "events.jsonl")

    def on_accept(row, adv_now):
        with open(events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({**row, "adv_ids": adv_now.tolist()}, ensure_ascii=False) + "\n")

    t0 = time.time()
    if args.dry_run:
        best, hist = adv, []
        print("[dry-run] search skipped")
    else:
        best, _, hist = run_gcg(model, layout, adv, cfg, on_accept=on_accept)
    if not hist:
        with open(events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"step": 0, "nll": base_nll, "margin": base_m,
                                "adv_nll": base_p, "adv_ids": adv.tolist()},
                               ensure_ascii=False) + "\n")

    fin_nll, fin_m, fin_p = probe(model, W, layout, best)
    adv_text = tok.decode(best)
    # The gate scores the payload as bare text; the loss scores it in the slot. Both are
    # reported, because they are not the same number and the gap is the interesting part.
    bare_ppl = float(filters.text_nll(tok, model, adv_text, dev))
    w_end = hist[-1]["w"] if hist else cfg.ppl_weight

    # Generate for real: context stops at the assistant header, the target text is not included.
    start = layout.targets[0].start
    gen_ids = torch.cat([layout.before_ids, best, layout.after_ids[:start]])
    text = generate(tok, model, gen_ids, args.max_new_tokens)

    # In structural mode the model produces half an object, so splice the prefix back on
    # before verifying.
    check_text = (target_text + text) if structural else text

    v = verify(check_text, fam, fam.target, fill=SECRET)
    kind = failure_kind(v)

    print("\n==== result ====")
    print(f"nll:    {base_nll:.4f} -> {fin_nll:.4f}")
    print(f"margin: {base_m:+.4f} -> {fin_m:+.4f}  "
          f"({'target is the greedy winner' if fin_m > 0 else 'still not the winner'})")
    print(f"ppl:    {base_p:.4f} -> {fin_p:.4f} in slot, {bare_ppl:.4f} as bare text "
          f"(gate ceiling 9.00)")
    print(f"obj:    {objective_from(base_nll, base_m, cfg, base_p):.4f} (w={cfg.ppl_weight:.2f})"
          f" -> {objective_from(fin_nll, fin_m, replace(cfg, ppl_weight=w_end), fin_p):.4f} "
          f"(w={w_end:.2f})  ({time.time() - t0:.1f}s)")
    print(f"L1 {v['l1']}  {v['l1_why']}")
    print(f"L2 {v['l2']}  {v['l2_why']}")
    print(f"L3 {v['l3']}  {v['l3_why']}")
    print(f"failure_kind: {kind}")
    print("\n---- generated ----")
    print(check_text.strip()[:800])
    print("\n---- adv span ----")
    print(repr(adv_text))

    rec = {
        "family": fam.key,
        "model": args.model,
        "config": {k: v for k, v in vars(args).items()},
        "gate": g,
        "baseline": {"nll": base_nll, "margin": base_m, "adv_nll": base_p},
        "final": {"nll": fin_nll, "margin": fin_m, "adv_nll": fin_p,
                  "bare_nll": bare_ppl, "ppl_weight_end": w_end},
        "adv_ids": best.tolist(),
        "adv_text": adv_text,
        "target_text": target_text,
        "structural": structural,
        "generated": text,
        "generated_full": check_text,
        "verify": v,
        "failure_kind": kind,
        "steps": len(hist),
        "seconds": round(time.time() - t0, 1),
    }
    with open(os.path.join(run_dir, "result.json"), "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    with open(os.path.join(run_dir, "adv.txt"), "w", encoding="utf-8") as f:
        f.write(adv_text)
    print(f"\n[run] {run_dir}")
    return 0 if v["breach"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
