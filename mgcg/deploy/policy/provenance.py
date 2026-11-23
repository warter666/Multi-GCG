"""Provenance: which values are sensitive, where they were seen, and how they travel.

The layer keeps this state, not the model. Two facts are stored for every value that came out
of a sensitive path:

  origin   the path it was read from
  value    the literal text, and its normalised form, because a comparison may use either

Storage is a file when the policy is `full`, so a second process starts hot. A policy that
keeps this in memory reports zero after a restart, which is the hole the cross-session case
measures.
"""

from __future__ import annotations

import json
import os
import re

FLAT = re.compile(r"[^a-z0-9]")

# A partial match is trusted only at this length. Below it, a short shared prefix blocks text
# that has nothing to do with the value.
PARTIAL_MIN = 8


def flat(text: str) -> str:
    return FLAT.sub("", str(text).lower())


class Lineage:
    def __init__(self, path: str | None = None):
        self.path = path
        self.values: set[str] = set()   # normalised forms
        self.raw: set[str] = set()      # literal forms
        self.origins: dict[str, str] = {}
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                self.values = set(data.get("values", []))
                self.raw = set(data.get("raw", []))
                self.origins = dict(data.get("origins", {}))
            except Exception:
                self.values, self.raw, self.origins = set(), set(), {}

    def save(self) -> None:
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"values": sorted(self.values), "raw": sorted(self.raw),
                       "origins": self.origins}, fh)
        os.replace(tmp, self.path)

    def add(self, value: str, origin: str = "") -> None:
        f = flat(value)
        r = str(value).strip()
        if len(f) < 3 or f in self.values:
            return
        self.values.add(f)
        if r:
            self.raw.add(r)
        if origin:
            self.origins[f] = origin
        self.save()

    def holds(self, text: str, use_raw: bool) -> str | None:
        """The stored value this text carries, comparing only the forms the policy allows.

        `use_raw` is the literal comparison. Otherwise every candidate form is compared, and
        a candidate of at least PARTIAL_MIN characters may also sit inside a stored value, so
        a prefix of the value is still a leak.
        """
        if use_raw:
            for taint in self.raw:
                if taint and taint in text:
                    return taint
                if len(text) >= PARTIAL_MIN and text in taint:
                    return taint
            return None
        for taint in self.values:
            candidate = flat(text)
            if taint and taint in candidate:
                return taint
            if len(candidate) >= PARTIAL_MIN and candidate in taint:
                return taint
        return None
