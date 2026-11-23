"""Compare bench runs that differ only by the model, one table per (model, stack).

    python scripts/bench_models.py --row qwen1.5=out/bench-layer --row qwen0.5=out/bench-qwen05

Each row is a directory written by scripts/bench_run.py. The models may have been run over
different stack subsets; the table shows what is there and leaves the rest blank. No model,
no GPU: it only reads rows that were already written.

Two extra columns matter for small models. `parse_error` counts episodes where no call
could be parsed at all (the corpus cannot be attempted by that model). `protocol_refusal`
counts calls the harness itself rejected for being malformed or off-schema. A low utility
number with high parse errors says the model failed the interface, not the defence.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from collections import Counter

ORDER = ["none", "l1", "l2", "l3", "full", "l1l2", "l1full", "l1l2l3"]
ATTACK = ("attack_succeeded", "safe_and_useful", "blocked_but_failed",
          "no_attempt_task_ok", "no_attempt_task_failed")
VERDICTS = ATTACK + ("benign_success", "benign_failure")


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


def load(path: str) -> list[dict]:
    with open(os.path.join(path, "results.jsonl"), encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def summarise(rows: list[dict]) -> dict[str, dict]:
    by_stack = {}
    for stack in ORDER:
        rs = [r for r in rows if r["stack"] == stack]
        if not rs:
            continue
        atk = [r for r in rs if r["kind"] == "attack"]
        ben = [r for r in rs if r["kind"] == "benign"]
        c = Counter(r["verdict"] for r in rs)
        by_stack[stack] = {
            "n_atk": len(atk), "n_ben": len(ben),
            "asr": sum(1 for r in atk if r["verdict"] == "attack_succeeded"),
            "ben": sum(1 for r in ben if r["verdict"] == "benign_success"),
            "pf": sum(1 for r in rs if r.get("PF")),
            "refusal": sum(int(r.get("protocol_refusals") or 0) for r in rs),
            **{v: c.get(v, 0) for v in VERDICTS},
        }
    return by_stack


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--row", action="append", default=[], metavar="NAME=DIR")
    ap.add_argument("--baseline", default="", help="row name the deltas are taken against")
    ap.add_argument("--md", default="")
    args = ap.parse_args()

    names, data = [], {}
    for spec in args.row:
        name, _, path = spec.partition("=")
        names.append(name)
        data[name] = summarise(load(path))

    out = []
    say = out.append
    say("# Cross-model table\n")
    say("Rows: %d. Directories: %s.\n"
        % (sum(len(v) for v in data.values()), ", ".join(s.partition("=")[2] for s in args.row)))

    say("| model | stack | ASR | benign | safe_and_useful | blocked_but_failed | "
        "no_attempt | parse_error | protocol_refusal |")
    say("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for name in names:
        for stack in [s for s in ORDER if s in data[name]]:
            s = data[name][stack]
            na = s["no_attempt_task_ok"] + s["no_attempt_task_failed"]
            say("| %s | %s | %d/%d (%s) | %d/%d (%s) | %d | %d | %d/%d | %d | %d |"
                % (name, stack, s["asr"], s["n_atk"], ci(s["asr"], s["n_atk"]),
                   s["ben"], s["n_ben"], ci(s["ben"], s["n_ben"]),
                   s["safe_and_useful"], s["blocked_but_failed"], na, s["n_atk"],
                   s["pf"], s["refusal"]))

    base = args.baseline or (names[0] if names else "")
    if base in data:
        say("\n## Margins against %s\n" % base)
        say("| model | stack | dASR | dBenign | dSafe_and_useful |")
        say("| --- | --- | --- | --- | --- |")
        for name in names:
            if name == base:
                continue
            for stack in [s for s in ORDER if s in data[name]]:
                if stack not in data[base]:
                    continue
                a, b = data[name][stack], data[base][stack]
                say("| %s | %s | %+d | %+d | %+d |"
                    % (name, stack, a["asr"] - b["asr"], a["ben"] - b["ben"],
                       a["safe_and_useful"] - b["safe_and_useful"]))

    text = "\n".join(out) + "\n"
    if args.md:
        os.makedirs(os.path.dirname(args.md) or ".", exist_ok=True)
        open(args.md, "w", encoding="utf-8").write(text)
        print("[written] %s" % args.md)
    else:
        print(text)


if __name__ == "__main__":
    main()
