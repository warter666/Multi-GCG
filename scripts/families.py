"""Run the two new attack families end to end, one model load for all cells.

Group W: destructive write on the mail task. The sink is measured three ways (no guard, L3 as
it shipped, L3 with the protected-path rule) plus a benign-write control in both directions.
Group T: exfiltration on the token task, where reading the credential is part of the user's
job, so the injection only has to redirect one action.

    python scripts/families.py
"""

from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mgcg.deploy.episode import run_episode  # noqa: E402
from mgcg.deploy.guards import Judge  # noqa: E402
from mgcg.deploy.world import TASK, TASK_TOKEN  # noqa: E402
from mgcg.model import load_model  # noqa: E402

OUT = "out"


def pay(name: str) -> str:
    if not name:
        return ""
    with open(os.path.join(OUT, name), encoding="utf-8") as f:
        return f.read().strip()


# label, task, layers, write_guard, payload file
CONFIGS = [
    ("W-none",         "mail",  set(),       False, "pay-write.txt"),
    ("W-l3-before",    "mail",  {"l3"},      False, "pay-write.txt"),
    ("W-l3-after",     "mail",  {"l3"},      True,  "pay-write.txt"),
    ("W-benign-none",  "mail",  set(),       False, "pay-write-benign.txt"),
    ("W-benign-after", "mail",  {"l3"},      True,  "pay-write-benign.txt"),
    ("T-control",      "token", set(),       False, ""),
    ("T-post-none",    "token", set(),       False, "pay-exfil-post.txt"),
    ("T-post-l3",      "token", {"l3"},      False, "pay-exfil-post.txt"),
    ("T-post-l2",      "token", {"l2"},      False, "pay-exfil-post.txt"),
    ("T-spaced-none",  "token", set(),       False, "pay-exfil-spaced.txt"),
    ("T-spaced-l3",    "token", {"l3"},      False, "pay-exfil-spaced.txt"),
    ("T-mail-none",    "token", set(),       False, "pay-exfil-mail.txt"),
    ("T-mail-l3",      "token", {"l3"},      False, "pay-exfil-mail.txt"),
    ("T-mail-l2",      "token", {"l2"},      False, "pay-exfil-mail.txt"),
]


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="run only cells whose label starts with this")
    args = ap.parse_args()
    configs = [c for c in CONFIGS if c[0].startswith(args.only)]
    tok, model, _ = load_model("Qwen/Qwen2.5-1.5B-Instruct", "auto", "auto")
    judge = Judge(tok, model)
    rows = []
    for label, task, layers, wg, pf in configs:
        payload = pay(pf)
        t0 = time.time()
        run = run_episode(tok, model, payload, layers,
                          max_steps=5 if task == "token" else 4,
                          max_new_tokens=384, seed=0,
                          judge=judge if "l2" in layers else None,
                          task=TASK_TOKEN if task == "token" else TASK,
                          write_guard=wg)
        a, wa = run.attack()
        r, wr = run.attack_recovered()
        d, wd = run.damage()
        t, wt = run.task(need=task)
        blocked = [e["blocked_by"] for e in run.events if e.get("blocked_by")]
        print(f"\n=== {label}  {round(time.time() - t0, 1)}s  turns={run.turns} "
              f"pf={run.parse_failures} judge={run.judge_scores} blocked={blocked}")
        for e in run.events:
            if e["name"] == "<assistant>":
                print(f"  > {e['args']['text'][:200]!r}")
            else:
                print(f"  - {e['name']}({json.dumps(e['args'], ensure_ascii=False)[:100]}) "
                      f"ok={e['ok']} blocked={e.get('blocked_by')} err={e['error']}")
        print(f"  A={int(a)} ({wa})  REC={int(r)} ({wr})  D={int(d)} ({wd})  T={int(t)} ({wt})")
        rows.append({"label": label, "task": task, "layers": sorted(layers),
                     "write_guard": wg, "payload_file": pf,
                     "attack": a, "recovered": r, "damage": d, "task": t,
                     "parse_failures": run.parse_failures, "judge": run.judge_scores,
                     "blocked": blocked,
                     "events": [{k: e[k] for k in ("name", "args", "ok", "blocked_by", "error")}
                                for e in run.events]})

    print("\n=== summary")
    print(f"{'cell':<16} {'A':<3} {'REC':<4} {'D':<3} {'T':<3} {'pf':<3} blocked")
    for r in rows:
        print(f"{r['label']:<16} {int(r['attack']):<3} {int(r['recovered']):<4} "
              f"{int(r['damage']):<3} {int(r['task']):<3} {r['parse_failures']:<3} "
              f"{r['blocked']}")

    run_dir = os.path.join(OUT, f"fam-{int(time.time())}")
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "result.json"), "w", encoding="utf-8") as f:
        json.dump({"rows": rows}, f, ensure_ascii=False, indent=2)
    print(f"[out] {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
