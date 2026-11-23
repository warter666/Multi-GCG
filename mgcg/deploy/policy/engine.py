"""The single entry point. Every tool call is normalised, judged, then recorded.

    request -> normalise -> evaluate (before the call)  -> ALLOW / DENY
                          record_result (after the call) -> provenance and audit

`evaluate` has no side effect on the world and never takes one: it returns a Decision. The
caller runs the tool only when the Decision allows it. `record_result` is the only place that
writes provenance, so a read that was refused cannot taint anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..world import ALLOWED, SECRET_PATH
from . import canonical, encoded, rules
from .audit import Audit
from .decision import Decision
from .provenance import Lineage


@dataclass
class ToolRequest:
    raw_tool: str
    tool: str | None
    args: dict = field(default_factory=dict)
    path: str = ""
    host: str = ""
    recipients: tuple[list[str], int] = field(default_factory=lambda: ([], 0))
    normalized: dict = field(default_factory=dict)


class PolicyEngine:
    def __init__(self, policy: str = "ship", lineage: Lineage | None = None,
                 store: str | None = None, destinations: dict | None = None,
                 audit: str | None = None, ruleset=None):
        """`policy` names one of the two whole-layer configurations: ship, full.

        `ruleset` exists for internal ablation only, where one mechanism is removed from the
        complete layer to ask what that mechanism alone is worth. It is not a user-facing
        switch, and the command line does not expose it: a layer assembled from separate
        switches is not the layer being studied.
        """
        base = ruleset or rules.RULESETS.get(policy)
        if base is None:
            raise ValueError(f"unknown policy {policy!r}; choose from {sorted(rules.RULESETS)}")
        self.ruleset = base
        self.policy_name = base.name
        self.destinations = {"mail": ALLOWED, "host": ()}
        self.destinations.update(destinations or {})
        if lineage is not None:
            self.lineage = lineage
        elif base.persist and store:
            self.lineage = Lineage(store)
        else:
            self.lineage = Lineage(None)
        self.audit = Audit(audit)
        self.blocked: list[dict] = []

    # -- normalise -------------------------------------------------------------
    def normalize(self, tool: str, args: dict) -> ToolRequest:
        args = args if isinstance(args, dict) else {}
        name = canonical.tool_name(tool)
        req = ToolRequest(raw_tool=str(tool), tool=name, args=dict(args))
        if name == "http.post":
            u = canonical.url(args.get("url", ""))
            req.host = str(u["host"] or "")
            req.normalized = u
        if name == "fs.write" or name == "fs.read":
            req.path = canonical.path(args.get("path", ""))
            req.normalized = {"path": req.path}
        if name == "email.send":
            req.recipients = canonical.recipients(args.get("to", ""))
            req.normalized = {"to": req.recipients[0]}
        return req

    # -- before the call -------------------------------------------------------
    def evaluate(self, tool: str, args: dict) -> Decision:
        req = self.normalize(tool, args)
        ctx = {
            "allowlist": {a.lower() for a in self.destinations["mail"]},
            "hosts": {h.lower() for h in self.destinations["host"]},
            "host_rule": self.ruleset.destination_rule,
            "lineage": self.lineage,
            "use_raw": self.ruleset.use_raw,
            "candidates": self._candidates,
        }
        found = []
        if self.ruleset.default_deny:
            found += rules.unregistered(req, ctx)
        if self.ruleset.protect_writes:
            found += rules.protected_write(req, ctx)
        found += rules.destination(req, ctx)
        found += rules.provenance_flow(req, ctx)
        decision = Decision(allow=not found, violations=tuple(found), tool=str(tool),
                            normalized=req.normalized)
        if not decision.allow:
            self.blocked.append({"tool": str(tool), "rules": decision.rules,
                                 "reason": decision.reason})
            self.audit.write("decision", allow=False, tool=str(tool),
                             normalized=req.normalized, rules=decision.rules,
                             reason=decision.reason)
        return decision

    def check(self, tool: str, args: dict) -> str | None:
        """Convenience for probes and the dispatcher: the reason, or None for ALLOW."""
        decision = self.evaluate(tool, args)
        return None if decision.allow else decision.reason

    # -- after the call --------------------------------------------------------
    def record_result(self, tool: str, args: dict, decision: Decision, output: str = "",
                      executed: bool = True) -> None:
        if executed and decision.allow:
            req = self.normalize(tool, args)
            self.audit.write("result", tool=str(tool), normalized=req.normalized,
                             executed=True)
            if req.tool == "fs.read":
                self._observe(req.path, output)
        else:
            self.audit.write("result", tool=str(tool), executed=False)

    def _observe(self, path: str, value: str) -> None:
        if path == SECRET_PATH or path.startswith("secrets/"):
            for line in str(value).splitlines():
                if line.strip():
                    origin = path
                    self.lineage.add(line.strip(), origin=origin)
            return
        if not self.ruleset.cross_file:
            return
        # A file that merely stores the value stays hot: a copy is not a clean copy.
        for _form, text in self._candidates(str(value)):
            hit = self.lineage.holds(text, use_raw=self.ruleset.use_raw)
            if hit:
                self.lineage.add(hit, origin=path)
                return

    def observe_read(self, path: str, value: str) -> None:
        """Record a read that already happened outside the dispatcher (probes, replays)."""
        self._observe(canonical.path(path), str(value))

    # Kept as the old name for the probe scripts; it is the same method, not a second policy.
    note_read = observe_read

    def _candidates(self, text: str) -> list[tuple[str, str]]:
        if self.ruleset.use_raw:
            return [("literal", text)]
        return encoded.candidates(text, self.ruleset.detectors)
