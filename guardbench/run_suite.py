"""Run the paired suite under both policy configurations and write the numbers.

    python -m guardbench.run_suite --configs off,full --limit 0 --out out/guardbench

Track A (agent capability) reads the same rows as track B; the difference is which columns
you report, not a different execution path. Protocol handling is identical under both
configurations, which is the property the review asked for.
"""

from __future__ import annotations

import argparse
import json
import os
import time

from . import cases as case_mod
from . import evaluate, metrics, runner
from .policy import RefPolicy
from .policy_engine import EnginePolicy


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", default="off,full")
    ap.add_argument("--only", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-steps", type=int, default=4)
    ap.add_argument("--max-new-tokens", type=int, default=96)
    ap.add_argument("--retries", type=int, default=1)
    ap.add_argument("--model", default="Qwen/Qwen2.5-1.5B-Instruct")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    suite = case_mod.all_cases()
    if args.only:
        want = {s.strip() for s in args.only.split(",") if s.strip()}
        suite = [c for c in suite if c["id"] in want]
    if args.limit:
        suite = suite[:args.limit]

    stamp = time.strftime("%Y%m%d-%H%M%S")
    outdir = args.out or os.path.join("out", "guardbench-" + stamp)
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, "results.jsonl")

    tok, model = runner.load(args.model)
    print("[guardbench] cases=%d configs=%s model=%s out=%s"
          % (len(suite), args.configs, args.model, outdir))

    rows: list[dict] = []
    with open(path, "w", encoding="utf-8") as fh:
        for cfg in [c.strip() for c in args.configs.split(",") if c.strip()]:
            for case in suite:

                def policy_for(session: int, cfg=cfg, case=case) -> object | None:
                    """One policy per session. For `engine`, the shipped implementation is
                    driven through this suite's own interface, so the two configurations
                    differ in implementation, not in protocol handling.

                    The lineage store is per case and per configuration. Sharing it across
                    cases of one pair, or across the two implementations, would let a case
                    inherit taint it never produced - the second attack variant would be
                    blocked by the first one's read, and `engine` by `full`'s residue.
                    """
                    if cfg == "off":
                        return None
                    lineage = os.path.join(outdir, "lineage-%s-%s.json" % (cfg, case["id"]))
                    if cfg == "full":
                        return RefPolicy(hosts=tuple(case["hosts"]), lineage_path=lineage)
                    if cfg == "engine":
                        return EnginePolicy(tuple(case["hosts"]), lineage)
                    raise SystemExit("unknown config %r" % cfg)

                run = runner.run_case(case, policy_for, tok, model, max_steps=args.max_steps,
                                      max_new_tokens=args.max_new_tokens,
                                      retries=args.retries, config=cfg)
                row = evaluate.score(case, run)
                row.update({"model": args.model,
                            "interface": "single-action",
                            "max_steps": args.max_steps,
                            "max_new_tokens": args.max_new_tokens,
                            "sessions": run["sessions"],
                            "seed": 0})
                rows.append(row)
                fh.write(json.dumps(row) + "\n")
                fh.flush()
                print("  %-11s %-6s s=%d u=%d att=%d exe=%d prot=%d/%d turns=%d %.1fs"
                      % (case["id"], cfg, run["sessions"], row["utility_ok"],
                         row["attack_attempted"], row["attack_executed"],
                         row["protocol"]["valid"], row["protocol"]["invalid"],
                         row["turns"], row["secs"]))

    per_cfg = {}
    for cfg in sorted({r["config"] for r in rows}):
        per_cfg[cfg] = metrics.aggregate([r for r in rows if r["config"] == cfg])

    print("\n[metrics]")
    head = "%-4s %-15s %-15s %-13s %-13s %-13s"
    print(head % ("cfg", "PCR (valid/turn)", "TSR (benign)", "attack-att", "ASR", "block-rate"))
    for cfg, m in per_cfg.items():
        def f(x):
            return "%.2f (%.2f-%.2f)" % (x["rate"], x["lo"], x["hi"]) if x["rate"] is not None else "n/a"
        print(head % (cfg, f(m["PCR_protocol_compliance"]), f(m["TSR_benign_success"]),
                      f(m["attack_attempt_rate"]), f(m["ASR_end_to_end"]),
                      f(m["policy_blocking_rate"])))
    print("\n%-4s %-15s %-15s %-8s"
          % ("cfg", "FPR", "utility|attack", "noise"))
    for cfg, m in per_cfg.items():
        print("%-4s %-15s %-15s %-8s"
              % (cfg, f(m["FPR_legit_denied"]), f(m["utility_in_attack_cases"]),
                 f(m["benign_unintended_rate"])))

    # Paired comparison: the point of running the same case under both configurations.
    paired = {}
    for r in rows:
        paired.setdefault(r["case"], {})[r["config"]] = r
    complete = {k: v for k, v in paired.items() if "off" in v and "full" in v}
    utility_lost = sorted(k for k, v in complete.items()
                          if v["off"]["utility_ok"] and not v["full"]["utility_ok"])
    utility_gained = sorted(k for k, v in complete.items()
                            if not v["off"]["utility_ok"] and v["full"]["utility_ok"])
    attack_stopped = sorted(k for k, v in complete.items()
                            if v["off"]["attack_executed"] and not v["full"]["attack_executed"])
    attack_newly_landed = sorted(k for k, v in complete.items()
                                 if not v["off"]["attack_executed"] and v["full"]["attack_executed"])

    print("\n[paired] off -> full, same case")
    print("  utility lost  : %s" % (", ".join(utility_lost) or "none"))
    print("  utility gained: %s" % (", ".join(utility_gained) or "none"))
    print("  attack stopped: %s" % (", ".join(attack_stopped) or "none"))
    print("  newly landed  : %s" % (", ".join(attack_newly_landed) or "none"))

    os.makedirs(outdir, exist_ok=True)
    json.dump({"model": args.model, "interface": "single-action",
               "max_steps": args.max_steps, "max_new_tokens": args.max_new_tokens,
               "seed": 0, "metrics": per_cfg,
               "paired": {"utility_lost": utility_lost, "utility_gained": utility_gained,
                          "attack_stopped": attack_stopped,
                          "newly_landed": attack_newly_landed}},
              open(os.path.join(outdir, "metrics.json"), "w", encoding="utf-8"), indent=1)
    print("\n[files] %s" % path)


if __name__ == "__main__":
    main()
