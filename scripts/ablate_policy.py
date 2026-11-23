"""Policy-level ablation: remove one property at a time and watch the verdicts move.

No model. The corpus in bench/policy_cases.jsonl is a list of calls with the reads that
precede them. Each call is a decision the policy makes, so a change to the decision is
visible immediately and is reproducible.

Modes:
  full       all four properties on
  none       all four off (the control that says how much the four are worth together)
  -deny      an unclassified tool and a protected write are allowed
  -egress    a host with no rule is allowed
  -canonical the comparison sees only the literal argument
  -lineage   taint lives in memory only, and a stored copy does not stay hot
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

sys.path.insert(0, "/home/tbtb/projects/multi-gcg")

from mgcg.deploy.policy import ABLATIONS, Lineage, Policy

DOMAINS = ("api.acme.example",)


def load(path: str) -> list[dict]:
    out = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                out.append(json.loads(line))
    return out


def decide(case: dict, ablate: set[str]) -> tuple[str, str]:
    store = tempfile.mktemp(suffix=".json")
    try:
        lineage = None if "lineage" in ablate else Lineage(store)
        p = Policy(egress_domains=DOMAINS, lineage=lineage, ablate=ablate)
        for r in case.get("reads", []):
            p.note_read(r["path"], r["value"])
        if case.get("sessions", 1) > 1:
            # A new process. It reloads the lineage from disk, unless lineage is ablated.
            lineage2 = None if "lineage" in ablate else Lineage(store)
            p = Policy(egress_domains=DOMAINS, lineage=lineage2, ablate=ablate)
        reason = p.check(case["call"]["tool"], case["call"]["args"])
        return ("refuse", reason) if reason else ("allow", "")
    finally:
        if os.path.exists(store):
            os.remove(store)


MODES = {
    "full": set(),
    "none": set(ABLATIONS),
    "-deny": {"deny"},
    "-egress": {"egress"},
    "-canonical": {"canonical"},
    "-lineage": {"lineage"},
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="bench/policy_cases.jsonl")
    args = ap.parse_args()

    cases = load(args.cases)
    base = {c["id"]: decide(c, MODES["full"])[0] for c in cases}
    wrong = [c["id"] for c in cases if base[c["id"]] != c["expect"]]
    print(f"[cases] {len(cases)}  full-policy mismatches against expect: {wrong or 'none'}")

    order = list(MODES)
    print("\n  id     fires        " + "".join(f"{m:>12}" for m in order))
    flips = {m: [] for m in order}
    for case in cases:
        row = f"  {case['id']:<6} {case['fires']:<12}"
        for m in order:
            verdict = decide(case, MODES[m])[0]
            row += f"{verdict:>12}"
            if m != "full" and verdict != base[case["id"]]:
                flips[m].append(case["id"])
        print(row)

    print("\n[ablation] cases whose verdict changed against full")
    for m in order:
        if m == "full":
            continue
        changed = flips[m]
        print(f"  {m:<11} {len(changed):>2}/{len(cases)}  {','.join(changed) or '-'}")

    print("\n[interaction] canonical cases under -egress")
    print("  With no egress rule, the host rule no longer refuses first, so the encoded cases")
    print("  fall through to the taint comparison. A single-property table cannot show this.")
    for case in cases:
        if case["fires"] != "canonical":
            continue
        v_no_egress = decide(case, {"egress"})[0]
        v_canon = decide(case, {"canonical"})[0]
        print(f"  {case['id']:<6} -egress={v_no_egress:<7} -canonical={v_canon:<7}")


if __name__ == "__main__":
    main()
