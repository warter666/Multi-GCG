"""One table over several result directories, with the deltas that answer the margin questions.

    python scripts/bench_matrix.py out/bench-layer out/bench-matrix
    python scripts/bench_matrix.py out/bench-layer out/bench-matrix --md docs/stack_matrix.md

The directories may overlap; a (case, stack) pair seen twice must agree, and a disagreement is
reported instead of silently resolved. No model, no GPU: it only reads rows that were already
written.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from collections import Counter, defaultdict

ORDER = ["none", "l1", "l2", "l3", "full", "l1l2", "l1full", "l1l2l3"]
ATTACK = ("attack_succeeded", "safe_and_useful", "blocked_but_failed",
          "no_attempt_task_ok", "no_attempt_task_failed")


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (c - r) / d), min(1.0, (c + r) / d))


def ci(k: int, n: int) -> str:
    lo, hi = wilson(k, n)
    return "%.2f-%.2f" % (lo, hi)


def load(dirs: list[str]) -> tuple[dict, list[str]]:
    rows, clashes = {}, []
    for d in dirs:
        path = os.path.join(d, "results.jsonl")
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                key = (r["id"], r["stack"])
                if key in rows:
                    old = rows[key]
                    if (old["verdict"], old["A"], old["REC"], old["D"], old["T"]) != \
                            (r["verdict"], r["A"], r["REC"], r["D"], r["T"]):
                        clashes.append("%s/%s" % key)
                    continue
                rows[key] = r
    return rows, clashes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--md", default="")
    args = ap.parse_args()
    rows, clashes = load(args.dirs)

    stacks = defaultdict(list)
    for (cid, stack), r in rows.items():
        stacks[stack].append(r)
    out = []
    say = out.append

    say("# Stack matrix\n")
    say("Rows read: %d across %d stacks. Directories: %s.\n"
        % (len(rows), len(stacks), ", ".join(args.dirs)))
    if clashes:
        say("**Conflicting duplicates** (same case and stack, different verdict): %s\n"
            % ", ".join(clashes))
    else:
        say("No conflicting duplicates: every case and stack seen more than once agrees.\n")

    say("| stack | n_atk | attack_succeeded | safe_and_useful | blocked_but_failed | "
        "no_attempt_ok | no_attempt_failed | benign_success | benign_failure |")
    say("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    stat = {}
    for stack in [s for s in ORDER if s in stacks]:
        rs = stacks[stack]
        atk = [r for r in rs if r["kind"] == "attack"]
        ben = [r for r in rs if r["kind"] == "benign"]
        c = Counter(r["verdict"] for r in rs)
        stat[stack] = {"n_atk": len(atk), "n_ben": len(ben),
                       "asr": sum(1 for r in atk if r["verdict"] == "attack_succeeded"),
                       "ben": sum(1 for r in ben if r["verdict"] == "benign_success"),
                       **{v: c.get(v, 0) for v in ATTACK}}
        s = stat[stack]
        say("| %s | %d | %d | %d | %d | %d | %d | %d | %d |"
            % (stack, s["n_atk"], s["attack_succeeded"], s["safe_and_useful"],
               s["blocked_but_failed"], s["no_attempt_task_ok"],
               s["no_attempt_task_failed"], s["ben"], s["n_ben"] - s["ben"]))

    say("\n## Rates\n")
    say("| stack | ASR | benign success | never attempted |")
    say("| --- | --- | --- | --- |")
    for stack in [s for s in ORDER if s in stat]:
        s = stat[stack]
        na = s["no_attempt_task_ok"] + s["no_attempt_task_failed"]
        say("| %s | %d/%d (%s) | %d/%d (%s) | %d/%d |"
            % (stack, s["asr"], s["n_atk"], ci(s["asr"], s["n_atk"]),
               s["ben"], s["n_ben"], ci(s["ben"], s["n_ben"]), na, s["n_atk"]))

    say("\n## Margins\n")
    say("| comparison | dASR | dBenign | dStopped_and_useful |")
    say("| --- | --- | --- | --- |")
    pairs = [("l1", "none"), ("l2", "none"), ("l3", "none"), ("full", "none"),
             ("l1l2", "none"), ("l1l2l3", "l1l2"), ("l1full", "l1"), ("full", "l3")]
    for a, b in pairs:
        if a not in stat or b not in stat:
            continue
        say("| %s - %s | %+d | %+d | %+d |"
            % (a, b, stat[a]["asr"] - stat[b]["asr"], stat[a]["ben"] - stat[b]["ben"],
               stat[a]["safe_and_useful"] - stat[b]["safe_and_useful"]))

    text = "\n".join(out) + "\n"
    if args.md:
        os.makedirs(os.path.dirname(args.md) or ".", exist_ok=True)
        open(args.md, "w", encoding="utf-8").write(text)
        print("[written] %s" % args.md)
    else:
        print(text)


if __name__ == "__main__":
    main()
