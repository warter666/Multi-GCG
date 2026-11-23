"""Cell-by-cell comparison of two runs over the same cases, usually one changed harness argument.

    python scripts/bench_compare.py out/bench-qwen05 out/bench-qwen05-tok256 \
        out/bench-qwen05-tok256b out/bench-qwen05-tok256c --a 96 --b 256

The second and later directories are merged; a case and stack seen twice must agree on
(verdict, PF) or the pair is reported as a clash. Only cells present in both runs are compared.
"""

from __future__ import annotations

import argparse
import json
import os


def load(dirs: list[str]) -> tuple[dict, list[str]]:
    rows, clash = {}, []
    for d in dirs:
        with open(os.path.join(d, "results.jsonl"), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                key = (r["id"], r["stack"])
                if key in rows:
                    old = rows[key]
                    if (old["verdict"], old["PF"], old["A"], old["T"]) != \
                            (r["verdict"], r["PF"], r["A"], r["T"]):
                        clash.append("%s/%s" % key)
                    continue
                rows[key] = r
    return rows, clash


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b", nargs="+")
    ap.add_argument("--la", default="A")
    ap.add_argument("--lb", default="B")
    args = ap.parse_args()
    A, _ = load([args.a])
    B, clash = load(args.b)
    if clash:
        print("clashing duplicates: %s" % ", ".join(clash))

    keys = sorted(set(A) & set(B))
    lost = [k for k in keys if A[k]["PF"] and not B[k]["PF"]]
    kept = [k for k in keys if A[k]["PF"] and B[k]["PF"]]
    gained = [k for k in keys if not A[k]["PF"] and B[k]["PF"]]
    print("cells compared: %d of %d in %s and %d in %s"
          % (len(keys), len(A), args.la, len(B), args.lb))
    print("parse failure under %s: %d" % (args.la, sum(1 for k in keys if A[k]["PF"])))
    print("parse failure under %s: %d" % (args.lb, sum(1 for k in keys if B[k]["PF"])))
    print("resolved by %s: %d %s" % (args.lb, len(lost), lost))
    print("still failing under %s: %d %s" % (args.lb, len(kept), kept))
    print("new under %s: %d %s" % (args.lb, len(gained), gained))
    print("\nchanged verdicts:")
    for k in keys:
        if A[k]["verdict"] != B[k]["verdict"]:
            print("  %-5s %-6s %-22s -> %-22s (PF %d -> %d)"
                  % (k[0], k[1], A[k]["verdict"], B[k]["verdict"], A[k]["PF"], B[k]["PF"]))


if __name__ == "__main__":
    main()
