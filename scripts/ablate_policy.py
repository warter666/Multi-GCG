"""Internal ablation of the complete layer: remove one mechanism, keep the rest.

The layer is studied as a whole (`ship` against `full`). This script exists for one secondary
question: if a mechanism inside the full layer is removed, does the verdict move? It is not a
feature matrix built from switches, and the command line does not offer these modes.

Each line of bench/policy_cases.jsonl is one decision: the reads that precede a call, then the
call. No model runs, so a decision is reproducible by construction.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import replace

sys.path.insert(0, "/home/tbtb/projects/multi-gcg")

from mgcg.deploy.policy import PolicyEngine  # noqa: E402
from mgcg.deploy.policy.rules import FULL, SHIP  # noqa: E402

DOMAINS = {"host": ("api.acme.example",)}

MODES = {
    "full": FULL,
    "-flow": replace(FULL, name="no-flow", detectors=("literal",)),
    "-session": replace(FULL, name="no-session", cross_file=False, persist=False),
    "-destination": replace(FULL, name="no-destination", destination_rule=False),
    "-write": replace(FULL, name="no-write", protect_writes=False),
    "-default-deny": replace(FULL, name="no-default-deny", default_deny=False),
    "ship": SHIP,
}


def load(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def decide(case: dict, ruleset) -> tuple[str, str]:
    store = tempfile.mktemp(suffix=".json") if ruleset.persist else None
    try:
        engine = PolicyEngine("full", ruleset=ruleset, store=store, destinations=DOMAINS)
        for r in case.get("reads", []):
            engine.observe_read(r["path"], r["value"])
        if case.get("sessions", 1) > 1:
            # A new process. It reloads from disk only when the layer keeps a store.
            engine = PolicyEngine("full", ruleset=ruleset, store=store, destinations=DOMAINS)
        reason = engine.check(case["call"]["tool"], case["call"]["args"])
        return ("refuse", reason) if reason else ("allow", "")
    finally:
        if store and os.path.exists(store):
            os.remove(store)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="bench/policy_cases.jsonl")
    args = ap.parse_args()

    cases = load(args.cases)
    base = {c["id"]: decide(c, FULL)[0] for c in cases}
    wrong = [c["id"] for c in cases if base[c["id"]] != c["expect"]]
    print(f"[cases] {len(cases)}   full-layer mismatches against expect: {wrong or 'none'}")

    order = [m for m in MODES if m not in ("full", "ship")]
    print("\n  id     fires          ship       " + "".join(f"{m:>14}" for m in order))
    flips = {m: [] for m in order}
    for case in cases:
        row = f"  {case['id']:<6} {case['fires']:<13} {decide(case, SHIP)[0]:>10}"
        for m in order:
            verdict = decide(case, MODES[m])[0]
            row += f"{verdict:>14}"
            if verdict != base[case["id"]]:
                flips[m].append(case["id"])
        print(row)

    print("\n[internal ablation] decisions that change when one mechanism is removed")
    for m in order:
        print(f"  {m:<14} {len(flips[m]):>2}/{len(cases)}  {','.join(flips[m]) or '-'}")

    print("\n[coupling] the cross-session case is encoded, so two mechanisms both hold it up")
    for case in cases:
        if case["fires"] != "session":
            continue
        print(f"  {case['id']}  -flow={decide(case, MODES['-flow'])[0]:<7} "
              f"-session={decide(case, MODES['-session'])[0]:<7} "
              f"full={base[case['id']]}")
    print("  Removing either one releases it. The mechanisms overlap on this case, which is")
    print("  why a table of single removals cannot price either of them separately.")


if __name__ == "__main__":
    main()
