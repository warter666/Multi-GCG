"""Print what the model actually emitted for one case, step by step.

    python scripts/gb_trace.py S12_benign off

Diagnostic only: it does not write results and it is not part of the suite. When a case
fails, this is the cheapest way to see whether the agent misread the task, mistyped the
call, or was stopped by the policy.
"""

from __future__ import annotations

import sys

from guardbench import cases, runner
from guardbench.policy import RefPolicy


def main() -> None:
    cid = sys.argv[1]
    cfg = sys.argv[2] if len(sys.argv) > 2 else "off"
    case = [c for c in cases.all_cases() if c["id"] == cid][0]
    tok, model = runner.load()
    policy = None if cfg == "off" else RefPolicy(hosts=tuple(case["hosts"]))
    run = runner.run_case(case, policy, tok, model)

    print("[task] %s" % case["task"])
    if case.get("task2"):
        print("[task2] %s" % case["task2"])
    for ev in run["events"]:
        if ev["kind"] == "protocol_error":
            print("s%d step%d PROTOCOL %s: %s" % (ev["session"], ev["step"], ev["code"],
                                                  (ev.get("text") or "").replace("\n", " ")))
            print("            detail: %s" % ev["detail"])
            continue
        print("s%d step%d %-10s %s  blocked=%s err=%s"
              % (ev["session"], ev["step"], ev["tool"],
                 str(ev["args"])[:100], ev["blocked_by"], ev["error"]))
        print("            text: %s" % (ev.get("text") or "").replace("\n", " ")[:160])
    print("[utility] %s missing=%s" % (run["protocol"]["valid"], run["state"]["attempts"]))


if __name__ == "__main__":
    main()
