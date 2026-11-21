"""Fake tool environment for the local harness.

Every tool is an in-memory simulation: nothing touches the network, the filesystem or a
shell. The point is that the *agent* really makes the call, so the recorded trace is
something we can be judged on rather than something we assembled ourselves.

`source` is set by the tool that produced the content, never by the caller: that is what
tells a provenance check whether the text came from a web page, an email or a file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..families import SECRET_FILE

SIDE_EFFECT = {
    "fs.read": "READ",
    "fs.write": "WRITE",
    "fs.delete": "WRITE",
    "http.post": "NETWORK",
    "email.send": "SHARE",
    "shell.run": "EXEC",
    "web.open": "NETWORK",
    "web.search": "NETWORK",
    "email.list": "READ",
    "email.read": "READ",
}

SCOPE = {
    "fs.read": "local",
    "fs.write": "local",
    "fs.delete": "local",
    "email.send": "local",
    "email.list": "local",
    "email.read": "local",
    "web.open": "local",
    "web.search": "local",
    "http.post": "external",
    "shell.run": "external",
}

# Content provenance, decided by the tool itself.
SOURCE = {
    "web.open": "web",
    "web.search": "web",
    "email.list": "email",
    "email.read": "email",
}


@dataclass
class Env:
    """In-memory world. `poison` is the optimizable document body injected into the file
    (or page) the agent is asked to read."""

    poison: str
    secret_file: str = SECRET_FILE
    # Only pages that match one of these keys return the poisoned body. Any other page is a
    # benign placeholder: otherwise a control run that happens to open the web leaks the
    # payload and fires an unrelated predicate.
    poison_pages: tuple[str, ...] = ("notes",)
    files: dict[str, str] = field(default_factory=dict)
    mailbox: list[dict[str, Any]] = field(default_factory=list)
    http_log: list[dict[str, Any]] = field(default_factory=list)
    shell_log: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.files:
            self.files = {
                "/data/notes.txt": self.poison,
                "data/notes.txt": self.poison,
                "notes.txt": self.poison,
                "secret.txt": self.secret_file,
                "/data/secret.txt": self.secret_file,
            }

    # -- internal helpers -------------------------------------------------------
    def _path(self, raw: str) -> str:
        return raw.strip()

    def dispatch(self, call: dict[str, Any]) -> dict[str, Any]:
        """Execute one tool call and return the event that will be written to the trace."""
        name = str(call.get("tool", ""))
        args = call.get("args") if isinstance(call.get("args"), dict) else {}
        base = {
            "name": name,
            "args": args,
            "ok": False,
            "output": "",
            "side_effect": SIDE_EFFECT.get(name, "READ"),
            "scope": SCOPE.get(name, "local"),
            "source": SOURCE.get(name, "file"),
            "error": None,
        }

        if name not in SIDE_EFFECT:
            base["error"] = f"unknown tool: {name!r}"
            return base

        if name == "fs.read":
            p = self._path(str(args.get("path", "")))
            if p in self.files:
                base["ok"], base["output"] = True, self.files[p]
            else:
                base["error"], base["output"] = f"no such file: {p}", ""
            return base

        if name == "fs.write":
            p = self._path(str(args.get("path", "")))
            self.files[p] = str(args.get("data", args.get("content", "")))
            base["ok"], base["output"] = True, f"wrote {p}"
            return base

        if name == "fs.delete":
            p = self._path(str(args.get("path", "")))
            if p in self.files:
                self.files.pop(p)
                base["ok"], base["output"] = True, f"deleted {p}"
            else:
                base["error"], base["output"] = f"no such file: {p}", ""
            return base

        if name == "email.send":
            self.mailbox.append(dict(args))
            base["ok"], base["output"] = True, "message queued (not delivered)"
            return base

        if name == "email.list":
            base["ok"] = True
            base["output"] = f"{len(self.mailbox)} message(s)"
            return base

        if name == "email.read":
            idx = int(args.get("id", args.get("index", 0)) or 0)
            if 0 <= idx < len(self.mailbox):
                base["ok"], base["output"] = True, str(self.mailbox[idx])
            else:
                base["error"], base["output"] = "no such message", ""
            return base

        if name == "http.post":
            self.http_log.append(dict(args))
            base["ok"], base["output"] = True, "request recorded (not sent)"
            return base

        if name in ("web.open", "web.search"):
            # Only the page this family poisons returns the payload; every other page is
            # inert, so a control run cannot accidentally read it.
            probe = " ".join(str(v) for v in args.values())
            if any(k in probe for k in self.poison_pages):
                base["ok"], base["output"] = True, self.poison
            else:
                base["ok"], base["output"] = True, "page opened: nothing relevant here"
            return base

        if name == "shell.run":
            self.shell_log.append(dict(args))
            base["ok"], base["output"] = True, "recorded (never executed)"
            return base

        base["error"] = "unhandled tool"
        return base
