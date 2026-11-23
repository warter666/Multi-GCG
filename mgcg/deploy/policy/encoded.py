"""Content analysis: what a value would mean to a reader after a transform.

Separate from canonical.py on purpose. Canonicalisation makes equivalent requests comparable;
this module asks whether a piece of text can be read back as a value the layer already knows
is sensitive. Keeping them apart stops the layer from turning "a path with `..`" and "a
base64 blob" into the same kind of problem.

Each detector is named, has a limit, and returns candidates rather than a verdict. The caller
compares those candidates with the provenance. A detector that cannot parse the input returns
nothing: refusing on a guess is how a filter grows false positives.

Scope, stated rather than implied:
  literal   the value as given
  base64    runs of at least 12 characters that decode to printable text, decoded once
  hex       runs of at least 16 hex digits, decoded once
  reversed  the whole string read backwards

rot13, initials, paraphrases and split delivery are outside this list. Section 8 of the README
says so; nothing here claims a general decoder.
"""

from __future__ import annotations

import base64
import re

B64_RUN = re.compile(r"[A-Za-z0-9+/=]{12,}")
HEX_RUN = re.compile(r"[0-9a-fA-F]{16,}")
MAX_CHARS = 4096


def _printed(text: str) -> bool:
    if not text:
        return False
    return sum(c.isprintable() for c in text) / len(text) > 0.85


def literal(text: str) -> list[str]:
    return [text]


def base64_run(text: str) -> list[str]:
    out = []
    for m in B64_RUN.finditer(text[:MAX_CHARS]):
        chunk = m.group(0)
        try:
            raw = base64.b64decode(chunk + "=" * (-len(chunk) % 4)).decode("utf-8", "ignore")
        except Exception:
            continue
        if _printed(raw):
            out.append(raw)
    return out


def hex_run(text: str) -> list[str]:
    out = []
    for m in HEX_RUN.finditer(text[:MAX_CHARS]):
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


def reversed_text(text: str) -> list[str]:
    return [text[::-1]]


DETECTORS = {
    "literal": literal,
    "base64": base64_run,
    "hex": hex_run,
    "reversed": reversed_text,
}


def candidates(text: str, names: tuple[str, ...]) -> list[tuple[str, str]]:
    """Every (detector, candidate) pair for this text under the named detectors."""
    out = []
    for name in names:
        fn = DETECTORS.get(name)
        if fn is None:
            continue
        for value in fn(str(text)):
            out.append((name, value))
    return out
