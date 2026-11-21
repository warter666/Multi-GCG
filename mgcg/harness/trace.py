"""Trace recording: one JSON object per tool event, plus the conversion into the shape a
predicate checker consumes.

Execution writes events; judgement reads them. Nothing in this module decides whether an
attack succeeded.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

# Frozen field set: do not add or rename fields without updating every consumer.
FIELDS = ("name", "args", "ok", "output", "side_effect", "scope", "source", "error")


@dataclass
class Event:
    name: str
    args: dict[str, Any]
    ok: bool
    output: str
    side_effect: str
    scope: str
    source: str
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return {k: d[k] for k in FIELDS}


@dataclass
class Trace:
    user_messages: list[str] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    assistant_messages: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add(self, event: Event) -> None:
        self.events.append(event)

    def add_note(self, text: str) -> None:
        self.notes.append(text)

    def tool_names(self) -> list[str]:
        return [e.name for e in self.events]

    def jsonl(self) -> str:
        return "\n".join(json.dumps(e.as_dict(), ensure_ascii=False) for e in self.events)

    def write_jsonl(self, path: str) -> None:
        body = self.jsonl()
        with open(path, "w", encoding="utf-8") as f:
            f.write(body + ("\n" if body else ""))

    def to_predicate_trace(self) -> dict[str, Any]:
        """The structure a predicate checker expects."""
        return {
            "user_messages": list(self.user_messages),
            "tool_events": [e.as_dict() for e in self.events],
            "assistant_messages": list(self.assistant_messages),
        }
