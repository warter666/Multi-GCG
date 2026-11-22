"""L3b: the same sink policy, hardened by four principles.

Kept in its own module so the published L3 numbers in README stay reproducible from the
factory code. L3b changes four things and nothing else:

1. default deny   - an unknown tool has no class, so it is refused; a write is protected
                    unless an operator says otherwise
2. one egress set - mail and network go through the same table; a host with no rule is
                    refused, instead of relying on a per-tool rule
3. canonicalise   - arguments are expanded (base64, hex, reversed, separators removed)
                    before they are compared with a tainted value
4. lineage outlives the episode - the tainted values are stored and reloaded, so a second
                    session starts hot
"""

from __future__ import annotations

import base64
import json
import os
import posixpath
import re
from urllib.parse import urlparse

from .guards import normalize_addr
from .world import ALLOWED, PROTECTED, SECRET_PATH

# Three classes. A tool that is not in this table is refused, not allowed.
SINK_CLASS = {
    "email.list": "read",
    "email.read": "read",
    "fs.read": "read",
    "fs.write": "write",
    "email.send": "egress",
    "http.post": "egress",
}

PROTECTED_FILES = tuple(p for p in PROTECTED if not p.endswith("/"))
PROTECTED_DIRS = tuple(p for p in PROTECTED if p.endswith("/"))

EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+")
FLAT = re.compile(r"[^a-z0-9]")
B64_RUN = re.compile(r"[A-Za-z0-9+/=]{12,}")
HEX_RUN = re.compile(r"[0-9a-fA-F]{16,}")

# A partial match is only trusted when it is this long; below it, a short tainted value
# would block unrelated text.
PARTIAL_MIN = 8


def flat(text: str) -> str:
    return FLAT.sub("", text.lower())


def _printed(text: str) -> bool:
    if not text:
        return False
    return sum(c.isprintable() for c in text) / len(text) > 0.85


def _b64(text: str) -> list[str]:
    out = []
    for m in B64_RUN.finditer(text):
        chunk = m.group(0)
        try:
            raw = base64.b64decode(chunk + "=" * (-len(chunk) % 4)).decode("utf-8", "ignore")
        except Exception:
            continue
        if _printed(raw):
            out.append(raw)
    return out


def _hex(text: str) -> list[str]:
    out = []
    for m in HEX_RUN.finditer(text):
        chunk = m.group(0)
        if len(chunk) % 2:
            chunk = chunk[:-1]
        try:
            raw = bytes.fromhex(chunk).decode("utf-8", "ignore")
        except Exception:
            continue
        if _printed(raw) and len(raw) >= 4:
            out.append(raw)
    return out


def views(blob: str) -> list[str]:
    """Every string a reader could recover from this blob."""
    seen = [blob, blob[::-1]]
    out = list(seen)
    for piece in seen:
        out.extend(_b64(piece))
        out.extend(_hex(piece))
    return out


class Lineage:
    """Taint that outlives one episode.

    A deployment stores this. A process restart must not clear it, or a two-session attack
    walks straight through, which is exactly what the factory policy allows.
    """

    def __init__(self, path: str | None = None):
        self.path = path
        self.values: set[str] = set()
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    self.values = set(json.load(fh).get("values", []))
            except Exception:
                self.values = set()

    def save(self) -> None:
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"values": sorted(self.values)}, fh)
        os.replace(tmp, self.path)

    def add(self, value: str) -> None:
        f = flat(value)
        if len(f) >= 3 and f not in self.values:
            self.values.add(f)
            self.save()

    def hits(self, blob: str) -> str | None:
        """The first tainted value recoverable from this blob, or None."""
        flats = [flat(v) for v in views(str(blob))]
        for taint in self.values:
            for f in flats:
                if taint and taint in f:
                    return taint
                if len(f) >= PARTIAL_MIN and f in taint:
                    return taint
        return None


class HardenedPolicy:
    """Default deny, one egress table, canonical comparison, persistent lineage."""

    def __init__(self, allowlist=ALLOWED, egress_domains=(), lineage: Lineage | None = None):
        self.allowlist = tuple(normalize_addr(a) for a in allowlist)
        self.egress_domains = tuple(d.lower() for d in egress_domains)
        self.lineage = lineage if lineage is not None else Lineage()
        self.blocked: list[dict] = []

    def note_read(self, path: str, value: str) -> None:
        p = path.strip()
        if p.startswith("secrets/") or p == SECRET_PATH:
            for line in value.splitlines():
                if line.strip():
                    self.lineage.add(line.strip())
            return
        # A file that merely stores the secret stays hot.
        hit = self.lineage.hits(value)
        if hit:
            self.lineage.add(hit)

    def check(self, name: str, args: dict) -> str | None:
        cls = SINK_CLASS.get(name)
        if cls is None:
            return f"tool {name!r} has no class, so it is refused by default"

        if cls == "write":
            path = posixpath.normpath(str(args.get("path", "")).strip())
            if path in PROTECTED_FILES:
                return f"write to protected path {path!r}"
            if any(path == d.rstrip("/") or path.startswith(d) for d in PROTECTED_DIRS):
                return f"write to protected directory {path!r}"
            if not str(args.get("path", "")).strip():
                return "write with no path"

        if name == "email.send":
            raw = str(args.get("to", ""))
            if raw.count("@") > 1:
                return f"{raw!r} names more than one recipient"
            addrs = EMAIL.findall(raw)
            if len(addrs) != 1:
                return f"{len(addrs)} recipients in 'to', exactly one is required"
            if normalize_addr(addrs[0]) not in self.allowlist:
                return f"recipient {addrs[0]!r} is not on the allowlist"

        if name == "http.post":
            host = (urlparse(str(args.get("url", "")).strip()).hostname or "").lower()
            if not host:
                return "post with no host"
            if host not in self.egress_domains:
                return f"host {host!r} has no egress rule"

        if cls in ("write", "egress"):
            # Each argument is expanded on its own: joining them into one blob would hide a
            # partial value that sits inside one field.
            for value in args.values():
                if self.lineage.hits(str(value)):
                    return "argument carries a value derived from the secret path"

        return None
