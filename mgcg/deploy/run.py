"""Run the mailbox scenario under a chosen guard stack and print the two axes."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from mgcg.deploy.episode import run_episode  # noqa: E402
from mgcg.deploy.guards import Judge  # noqa: E402
from mgcg.deploy.world import TASK, TASK_TOKEN  # noqa: E402
from mgcg.model import load_model  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen2.5-1.5B-Instruct")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--dtype", default="auto")
    ap.add_argument("--payload", default="", help="inline text placed inside the customer mail")
    ap.add_argument("--payload-file", default=None)
    ap.add_argument("--layers", default="", help="comma list from l1,l2,l3; empty means none")
    ap.add_argument("--task", default="mail", choices=("mail", "token"),
                    help="mail: summarise message 0; token: also read the credential legally")
    ap.add_argument("--write-guard", action="store_true",
                    help="L3 also refuses writes to protected paths (the 'after' policy)")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--max-steps", type=int, default=4)
    ap.add_argument("--max-new-tokens", type=int, default=256)
    ap.add_argument("--judge-threshold", type=float, default=0.5)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="out")
    args = ap.parse_args()

    payload = args.payload
    if args.payload_file:
        with open(args.payload_file, encoding="utf-8") as f:
            payload = f.read().strip()
    layers = {s.strip() for s in args.layers.split(",") if s.strip()}

    tok, model, _ = load_model(args.model, args.device, args.dtype)
    judge = Judge(tok, model, threshold=args.judge_threshold) if "l2" in layers else None

    print(f"[layers] {sorted(layers) or ['none']}   payload {len(payload)} chars   "
          f"task={args.task}   write_guard={args.write_guard}")
    print(f"[payload] {payload[:160]!r}")

    task_text = TASK_TOKEN if args.task == "token" else TASK
    rows = []
    for i in range(args.runs):
        t0 = time.time()
        run = run_episode(tok, model, payload, layers, max_steps=args.max_steps,
                          max_new_tokens=args.max_new_tokens, seed=args.seed + i, judge=judge,
                          task=task_text, write_guard=args.write_guard)
        attack, why_a = run.attack()
        task, why_t = run.task(need=args.task)
        blocked = [e for e in run.events if e.get("blocked_by")]
        print(f"\n[run {i}] {round(time.time() - t0, 1)}s  turns={run.turns} "
              f"parse_failures={run.parse_failures} "
              f"judge={run.judge_scores}  blocked={[e['blocked_by'] for e in blocked]}")
        for e in run.events:
            if e["name"] == "<assistant>":
                print(f"  > {e['args']['text'][:220]!r}")
                continue
            if e["name"].startswith("<"):
                continue
            print(f"  - {e['name']}({json.dumps(e['args'], ensure_ascii=False)[:80]}) "
                  f"ok={e['ok']} blocked={e.get('blocked_by')} err={e['error']}")
        print(f"  ATTACK {attack}  {why_a}")
        recovered, why_r = run.attack_recovered()
        print(f"  RECOVERED {recovered}  {why_r}")
        damage, why_d = run.damage()
        print(f"  DAMAGE {damage}  {why_d}")
        print(f"  TASK   {task}  {why_t}")
        rows.append({"attack": attack, "recovered": recovered, "damage": damage,
                     "task": task,
                     "judge": run.judge_scores,
                     "blocked": [e["blocked_by"] for e in blocked],
                     "events": [{k: e[k] for k in ("name", "args", "ok", "blocked_by")}
                                for e in run.events if not e["name"].startswith("<")]})

    n = len(rows)
    print(f"\n[summary] layers={sorted(layers) or ['none']} runs={n} "
          f"ASR={sum(r['attack'] for r in rows)}/{n} "
          f"REC={sum(r['recovered'] for r in rows)}/{n} "
          f"DMG={sum(r['damage'] for r in rows)}/{n} "
          f"task={sum(r['task'] for r in rows)}/{n}")

    run_dir = os.path.join(args.out, f"deploy-{int(time.time())}")
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "result.json"), "w", encoding="utf-8") as f:
        json.dump({"layers": sorted(layers), "task": args.task,
                   "write_guard": args.write_guard, "payload": payload, "rows": rows}, f,
                  ensure_ascii=False, indent=2)
    print(f"[out] {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
