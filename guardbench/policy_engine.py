"""Adapter: drive the shipped L3 layer through this suite's own policy interface.

The suite's reference policy (`policy.RefPolicy`) and the project's `PolicyEngine` are two
implementations of the same claim. Running both under the same cases, the same interface and
the same protocol handling is how a disagreement between them becomes visible: any case where
one blocks and the other allows is a bug in one of the two, not a result.

The adapter only translates; it adds no rules. `scene.py` deliberately does not import the
project, so the import happens here, at the boundary.
"""

from __future__ import annotations


class EnginePolicy:
    def __init__(self, hosts: tuple[str, ...], lineage_path: str | None = None):
        from mgcg.deploy.policy import PolicyEngine

        self._engine = PolicyEngine("full",
                                    store=lineage_path,
                                    destinations={"host": tuple(hosts)})

    def check(self, tool: str, args: dict) -> str | None:
        return self._engine.check(tool, args)

    def note_read(self, path: str, text: str) -> None:
        self._engine.observe_read(path, text)
