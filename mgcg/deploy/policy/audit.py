"""The audit trail. One line per decision, one line per executed call."""

from __future__ import annotations

import json
import os
import time


class Audit:
    def __init__(self, path: str | None = None):
        self.path = path
        self.lines: list[dict] = []
        if path:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def write(self, kind: str, **fields) -> None:
        rec = {"t": round(time.time(), 3), "kind": kind, **fields}
        self.lines.append(rec)
        if self.path:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")
