"""Structural normalisation. What a value means, not what it spells.

This module never looks for a secret. It answers one question: two requests that mean the
same thing must look the same before a rule compares them. A path with `..`, a URL with a
default port, an address inside a display name, and an aliased tool name are all the same
request as their plain form.

Encoded content is not here. Decoding base64 is a content analysis step, not a way to spell a
path, and it lives in encoded.py so that the two can be reasoned about separately.
"""

from __future__ import annotations

import posixpath
import re
from urllib.parse import urlparse

ADDR = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+")

# The registry: one canonical name per tool, and the aliases a model may emit for it.
TOOL_ALIASES = {
    "email.list": "email.list", "email_list": "email.list", "list_mail": "email.list",
    "email.read": "email.read", "email_read": "email.read", "read_mail": "email.read",
    "email.send": "email.send", "email_send": "email.send", "send_mail": "email.send",
    "fs.read": "fs.read", "fs_read": "fs.read", "read_file": "fs.read",
    "fs.write": "fs.write", "fs_write": "fs.write", "write_file": "fs.write",
    "http.post": "http.post", "http_post": "http.post", "post": "http.post",
}

DEFAULT_PORTS = {"http": 80, "https": 443}


def tool_name(name: str) -> str | None:
    """The registry name, or None when the tool is not registered."""
    return TOOL_ALIASES.get(str(name).strip().lower())


def path(value: str) -> str:
    """One path. `..` is resolved, `.` is dropped, a leading slash is dropped.

    `${root}/../secrets/x` and `secrets/./x` must not name different things, or a write rule
    protects a spelling instead of a file.
    """
    p = str(value).strip().replace("\\", "/")
    p = posixpath.normpath("/" + p).lstrip("/")
    return "" if p in ("", ".") else p


def url(value: str) -> dict[str, str | int | None]:
    """Scheme, host, port and path, in the form a rule can compare."""
    raw = str(value).strip()
    parts = urlparse(raw if "//" in raw else "//" + raw, scheme="https")
    scheme = (parts.scheme or "").lower()
    host = (parts.hostname or "").lower().rstrip(".")
    port = parts.port or DEFAULT_PORTS.get(scheme)
    return {"scheme": scheme, "host": host, "port": port,
            "path": posixpath.normpath(parts.path or "/")}


def recipients(value: str) -> tuple[list[str], int]:
    """The addresses in a recipient field, and how many `@` signs were seen.

    A field that names two people is not one recipient with a long name; the count of `@` is
    returned so a rule can refuse multi-recipient sends instead of silently reading the first.
    """
    raw = str(value)
    found = [a.lower().rstrip(".") for a in ADDR.findall(raw)]
    return found, raw.count("@")
