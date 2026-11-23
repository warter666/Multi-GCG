"""Read a finished suite directory and print the tables the write-up needs.

    python scripts/guardbench_report.py out/guardbench-v03
    python scripts/guardbench_report.py out/guardbench-v03 --md guardbench/results/v0.3/summary.md

Diagnostics only: no GPU, no model. It never rescored a trajectory; it reads the rows the
suite already wrote and adds the two comparisons a reader wants next - agreement between the
two implementations, and where the paired cases actually flipped.
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def load(path: str) -> tuple[list[dict], dict]:
    rows = []
    with open(os.path.join(path, "results.jsonl"), encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    meta_path = os.path.join(path, "metrics.json")
    meta = json.load(open(meta_path, encoding="utf-8")) if os.path.exists(meta_path) else {}
    return rows, meta


def fmt(x: dict) -> str:
    if not x or x.get("rate") is None:
        return "n/a"
    return "%.2f (%.2f-%.2f)" % (x["rate"], x["lo"], x["hi"])


def verdict(row: dict) -> tuple:
    return (row["utility_ok"], row["attack_attempted"], row["attack_executed"],
            len(row.get("forbidden_executed") or []))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--md", default="")
    args = ap.parse_args()
    rows, meta = load(args.path)
    out = []
    say = out.append

    cfgs = sorted({r["config"] for r in rows})
    say("# guardbench suite report\n")
    say("Rows: %d. Model: %s. Configs: %s.\n"
        % (len(rows), rows[0].get("model", "?"), ", ".join(cfgs)))

    say("## Six metrics by configuration\n")
    say("| config | PCR | TSR | attack attempt | ASR | blocking | FPR | noise |")
    say("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for cfg in cfgs:
        m = (meta.get("metrics") or {}).get(cfg)
        if not m:
            continue
        say("| %s | %s | %s | %s | %s | %s | %s | %s |"
            % (cfg, fmt(m["PCR_protocol_compliance"]), fmt(m["TSR_benign_success"]),
               fmt(m["attack_attempt_rate"]), fmt(m["ASR_end_to_end"]),
               fmt(m["policy_blocking_rate"]), fmt(m["FPR_legit_denied"]),
               fmt(m["benign_unintended_rate"])))

    say("\n## Agreement between `full` and `engine`\n")
    by_case = {}
    for r in rows:
        by_case.setdefault(r["case"], {})[r["config"]] = r
    diffs = []
    for cid, v in sorted(by_case.items()):
        if "full" in v and "engine" in v and verdict(v["full"]) != verdict(v["engine"]):
            diffs.append((cid, verdict(v["full"]), verdict(v["engine"])))
    if not diffs:
        say("Every case has the same (utility, attempted, executed, forbidden) verdict under "
            "both implementations.")
    else:
        for cid, a, b in diffs:
            say("- %s: full=%s engine=%s" % (cid, a, b))

    say("\n## Paired flips, `off` against each policy\n")
    for cfg in [c for c in cfgs if c != "off"]:
        lost = [c for c, v in by_case.items()
                if "off" in v and cfg in v and v["off"]["utility_ok"] and not v[cfg]["utility_ok"]]
        gained = [c for c, v in by_case.items()
                  if "off" in v and cfg in v and not v["off"]["utility_ok"] and v[cfg]["utility_ok"]]
        stopped = [c for c, v in by_case.items()
                   if "off" in v and cfg in v and v["off"]["attack_executed"]
                   and not v[cfg]["attack_executed"]]
        new = [c for c, v in by_case.items()
               if "off" in v and cfg in v and not v["off"]["attack_executed"]
               and v[cfg]["attack_executed"]]
        say("- off -> %s: utility lost %s; utility gained %s; attack stopped %s; newly landed %s"
            % (cfg, ", ".join(lost) or "none", ", ".join(gained) or "none",
               ", ".join(stopped) or "none", ", ".join(new) or "none"))

    say("\n## Attack cases by family\n")
    for cfg in cfgs:
        say("\n%s\n" % cfg)
        say("| family | attack cases | attempted | executed |")
        say("| --- | --- | --- | --- |")
        fam = {}
        for r in rows:
            if r["config"] == cfg and r["kind"] == "attack":
                fam.setdefault(r["family"], []).append(r)
        for name, rs in sorted(fam.items()):
            say("| %s | %d | %d | %d |"
                % (name, len(rs), sum(1 for r in rs if r["attack_attempted"]),
                   sum(1 for r in rs if r["attack_executed"])))

    text = "\n".join(out) + "\n"
    if args.md:
        os.makedirs(os.path.dirname(args.md) or ".", exist_ok=True)
        open(args.md, "w", encoding="utf-8").write(text)
        print("[written] %s" % args.md)
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
