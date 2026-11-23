"""One verdict shape for every tool call."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Violation:
    rule: str      # which rule fired, for the audit line
    reason: str    # why, in one sentence a reviewer can read


@dataclass(frozen=True)
class Decision:
    allow: bool
    violations: tuple[Violation, ...] = field(default_factory=tuple)
    tool: str = ""
    normalized: dict = field(default_factory=dict)

    @property
    def reason(self) -> str:
        return "; ".join(v.reason for v in self.violations)

    @property
    def rules(self) -> tuple[str, ...]:
        return tuple(v.rule for v in self.violations)
