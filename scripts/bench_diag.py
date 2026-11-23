"""Diagnostics for one results directory: where the parse failures sit, and what they do to the verdicts.

    python scripts/bench_diag.py out/bench-qwen05
    python scripts/bench_diag.py out/bench-qwen05 --md out/qwen05-diag.md

Row-level only. It reads what bench_run.py already wrote and adds no runs. The point is to
separate three things that a single "14/36 parse failures" number merges:

  * episode-level: an episode whose execution column says parse_error
  * call-level: protocol refusals counted inside a turn (never a parse error by definition;
    an unparsable turn is retried once, and a refused call is a call that parsed)
  * which cases, which stacks, and whether the failing sets coincide
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict

VERDICTS = ("attack_succeeded", "safe_and_useful", "blocked_but_failed",
            "no_attempt_task_ok", "no_attempt_task_failed",
            "benign_success", "benign_failure")
STACKS = ("none", "l1", "l2", "l3", "full", "l1l2", "l1full", "l1l2l3")


def load(path: str) -> list[dict]:
    with open(os.path.join(path, "results.jsonl"), encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--label", default="")
    ap.add_argument("--md", default="")
    args = ap.parse_args()
    rows = load(args.dir)
    label = args.label or args.dir
    out = []
    say = out.append

    say("# Diagnostics: %s\n" % label)
    say("Rows: %d. Models in file: %s.\n"
        % (len(rows), ", ".join(sorted({str(r.get("model")) for r in rows}))))

    # 1. PF histogram per stack
    say("## Parse failures per stack\n")
    say("| stack | episodes | parse_error | PF=0 | PF=1 | PF>=2 | protocol refusals |")
    say("| --- | --- | --- | --- | --- | --- | --- |")
    pf_ids = {}
    for stack in STACKS:
        rs = [r for r in rows if r["stack"] == stack]
        if not rs:
            continue
        c = Counter(int(r["PF"] or 0) for r in rs)
        pf_ids[stack] = {r["id"] for r in rs if r["execution"] == "parse_error"}
        say("| %s | %d | %d | %d | %d | %d | %d |"
            % (stack, len(rs), sum(1 for r in rs if r["execution"] == "parse_error"),
               c.get(0, 0), c.get(1, 0), sum(v for k, v in c.items() if k >= 2),
               sum(int(r.get("protocol_refusals") or 0) for r in rs)))

    # 2. stack x kind x parse-error matrix
    say("\n## Verdicts by stack, kind and parse state\n")
    say("| stack | kind | parse_error | " + " | ".join(VERDICTS) + " | total |")
    say("| --- | --- | --- | " + " | ".join("---" for _ in VERDICTS) + " | --- |")
    for stack in STACKS:
        for kind in ("attack", "benign"):
            for pe in ("yes", "no"):
                rs = [r for r in rows if r["stack"] == stack and r["kind"] == kind
                      and (r["execution"] == "parse_error") == (pe == "yes")]
                if not rs:
                    continue
                c = Counter(r["verdict"] for r in rs)
                say("| %s | %s | %s | %s | %d |"
                    % (stack, kind, pe, " | ".join(str(c.get(v, 0)) for v in VERDICTS), len(rs)))

    # 3. intersections of parse-error sets
    say("\n## Parse-error case sets and their intersections\n")
    say("| stack | n | ids |")
    say("| --- | --- | --- |")
    for stack, ids in pf_ids.items():
        say("| %s | %d | %s |" % (stack, len(ids), ", ".join(sorted(ids)) or "-"))
    names = list(pf_ids)
    if len(names) > 1:
        say("\n| pair | shared | same set | shared ids |")
        say("| --- | --- | --- | --- |")
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                shared = pf_ids[a] & pf_ids[b]
                say("| %s & %s | %d | %s | %s |"
                    % (a, b, len(shared), "yes" if pf_ids[a] == pf_ids[b] else "no",
                       ", ".join(sorted(shared)) or "-"))
        inter = set.intersection(*pf_ids.values()) if pf_ids else set()
        union = set.union(*pf_ids.values()) if pf_ids else set()
        say("\nAll-stack intersection: %d (%s). Union: %d (%s).\n"
            % (len(inter), ", ".join(sorted(inter)) or "-", len(union),
               ", ".join(sorted(union)) or "-"))

    # 4. attack cases across stacks
    say("\n## Every attack case, stack by stack\n")
    say("| case | stack | verdict | security | PF | blocked_by | turns |")
    say("| --- | --- | --- | --- | --- | --- | --- |")
    for r in rows:
        if r["kind"] != "attack":
            continue
        say("| %s | %s | %s | %s | %d | %s | %s |"
            % (r["id"], r["stack"], r["verdict"], r["security"], int(r["PF"] or 0),
               ",".join(r.get("blocked") or []) or "-", r.get("turns")))

    # 5. blocked_by accounting
    say("\n## Guard blocks by name (attack cases only)\n")
    say("| stack | " + " | ".join(("sink", "judge", "protocol")) + " | episodes blocked |")
    say("| --- | --- | --- | --- | --- |")
    for stack in STACKS:
        rs = [r for r in rows if r["stack"] == stack and r["kind"] == "attack"]
        if not rs:
            continue
        c = Counter(b for r in rs for b in (r.get("blocked") or []))
        nb = sum(1 for r in rs if r.get("blocked"))
        say("| %s | %d | %d | %d | %d |"
            % (stack, c.get("sink", 0), c.get("judge", 0), c.get("protocol", 0), nb))

    text = "\n".join(out) + "\n"
    if args.md:
        os.makedirs(os.path.dirname(args.md) or ".", exist_ok=True)
        open(args.md, "w", encoding="utf-8").write(text)
        print("[written] %s" % args.md)
    else:
        print(text)


if __name__ == "__main__":
    main()
