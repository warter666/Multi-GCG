"""The rules of the layer, evaluated on a normalised request.

A rule reads a `ToolRequest` and the provenance, and returns violations. It reads nothing
else: no raw argument strings, no detector output, no model scores. That is what makes the
decision explainable and what makes the same rule apply to every tool.

The two named policies differ in which rules they enable, not in the order they run:

  ship   allowlist, literal taint in one process, writes unprotected, no network destination
  full   the allowlist plus default deny, write protection, one destination table, structural
         comparison and encoded detection
"""

from __future__ import annotations

from dataclasses import dataclass

from ..world import ALLOWED, PROTECTED
from .decision import Violation
from .provenance import flat

PROTECTED_FILES = tuple(p for p in PROTECTED if not p.endswith("/"))
PROTECTED_DIRS = tuple(p for p in PROTECTED if p.endswith("/"))


@dataclass(frozen=True)
class Ruleset:
    name: str
    default_deny: bool
    protect_writes: bool
    destination_rule: bool
    detectors: tuple[str, ...]
    cross_file: bool
    persist: bool

    @property
    def use_raw(self) -> bool:
        return "literal" in self.detectors and "base64" not in self.detectors


SHIP = Ruleset(name="ship", default_deny=False, protect_writes=False, destination_rule=False,
               detectors=("literal",), cross_file=False, persist=False)
FULL = Ruleset(name="full", default_deny=True, protect_writes=True, destination_rule=True,
               detectors=("literal", "base64", "hex", "reversed"), cross_file=True, persist=True)

RULESETS = {"ship": SHIP, "full": FULL}


def unregistered(req, ctx) -> list[Violation]:
    if req.tool is None:
        return [Violation("default-deny",
                          f"tool {req.raw_tool!r} is not in the registry, so it is refused")]
    return []


def protected_write(req, ctx) -> list[Violation]:
    if req.tool != "fs.write":
        return []
    if not req.path:
        return [Violation("write-protection", "write with no path")]
    if req.path in PROTECTED_FILES:
        return [Violation("write-protection", f"write to protected path {req.path!r}")]
    for d in PROTECTED_DIRS:
        if req.path == d.rstrip("/") or req.path.startswith(d):
            return [Violation("write-protection", f"write to protected directory {d!r}")]
    return []


def destination(req, ctx) -> list[Violation]:
    """One rule, two channels. A mailbox address and a host are both destinations.

    The mail half is the layer's base: it runs under every policy, because a send needs a
    named recipient before anything else can be judged. The host half belongs to the full
    form, and is the half a deployment has to keep a table for.
    """
    if req.tool == "email.send":
        addrs, ats = req.recipients
        if ats > 1 or len(addrs) != 1:
            return [Violation("destination",
                              f"{len(addrs)} address(es) in 'to', exactly one is required")]
        if addrs[0] not in ctx["allowlist"]:
            return [Violation("destination", f"recipient {addrs[0]!r} is not on the allowlist")]
        return []
    if req.tool != "http.post" or not ctx["host_rule"]:
        return []
    if not req.host:
        return [Violation("destination", "post with no host")]
    if req.host not in ctx["hosts"]:
        return [Violation("destination", f"host {req.host!r} has no egress rule")]
    return []


def provenance_flow(req, ctx) -> list[Violation]:
    """No argument may carry a value the layer already knows is sensitive."""
    if req.tool not in ("fs.write", "email.send", "http.post"):
        return []
    lineage = ctx["lineage"]
    for name, value in req.args.items():
        for form, text in ctx["candidates"](str(value)):
            hit = lineage.holds(text, use_raw=ctx["use_raw"])
            if hit:
                origin = lineage.origins.get(flat(hit), "unrecorded")
                return [Violation("flow", f"argument {name!r} carries a sensitive value "
                                          f"recoverable as {form} (origin: {origin})")]
    return []
