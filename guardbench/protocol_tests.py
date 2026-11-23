"""Interface conformance tests. Scripted replies, no model, no GPU.

Each case is a reply a small model plausibly produces; the expected verdict pins the contract
so a later refactor cannot quietly start repairing output again.
"""

from __future__ import annotations

import json
import sys

from . import iface

TESTS = [
    ("valid_single", '{"tool": "email.read", "args": {"id": 0}}', None),
    ("prose_prefix", 'ASSISTANT: {"tool": "email.read", "args": {"id": 0}}', None),
    ("two_objects", '{"tool": "email.read", "args": {"id": 0}}\n'
                    '{"tool": "email.send", "args": {"to": "team@acme.example", '
                    '"subject": "s", "body": "b"}}', "batch"),
    ("json_array", '[{"tool": "email.read", "args": {"id": 0}}, '
                   '{"tool": "fs.read", "args": {"path": "billing.csv"}}]', "batch"),
    ("unknown_tool", '{"tool": "shell.run", "args": {"cmd": "ls"}}', "unknown_tool"),
    ("missing_arg", '{"tool": "email.send", "args": {"to": "team@acme.example"}}',
     "missing_arg"),
    ("wrong_type", '{"tool": "email.read", "args": {"id": "zero"}}', "bad_type"),
    ("args_not_object", '{"tool": "email.read", "args": [0]}', "args_not_object"),
    ("no_tool_key", '{"action": "email.read", "args": {"id": 0}}', "no_tool_key"),
    ("extra_arg", '{"tool": "email.read", "args": {"id": 0, "all": true}}', "extra_arg"),
    ("empty_output", "", "empty_output"),
    ("prose_only", "I will read the message now.", "no_json"),
    ("truncated_json", '{"tool": "email.read", "args": {"id": 0}', "no_json"),
    ("nested_args", '{"tool": "fs.write", "args": {"path": "notes.md", '
                    '"content": "a {\\"b\\": 1}"}}', None),
]


def main() -> int:
    bad = 0
    for name, text, expect in TESTS:
        act = iface.parse(text)
        got = None if isinstance(act, iface.Action) else act.code
        ok = got == expect
        if not ok:
            bad += 1
        print("%-16s expect=%-14s got=%-14s %s"
              % (name, expect or "ACCEPT", got or "ACCEPT", "ok" if ok else "FAIL"))
    print("\n%d/%d passed" % (len(TESTS) - bad, len(TESTS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
