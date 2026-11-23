"""L3 as one Policy Enforcement Layer.

Every tool call, without exception, goes through `PolicyEngine.evaluate()` before it runs
and through `record_result()` after it ran. There is one decision path, one place that holds
provenance, and one place that writes an audit line. The layer is named as a whole; the
mechanisms inside it are not exposed as switches.

Two named policies:

  ship   the rules L3 has always had: recipient allowlist, literal taint, taint in memory,
         writes unprotected, no destination rule for the network channel
  full   the same layer with the protections the layer is supposed to have: default deny,
         write protection, one destination table for both channels, structural
         normalisation, encoded-content detection, and lineage that outlives a process
"""

from .decision import Decision, Violation
from .engine import PolicyEngine, ToolRequest
from .provenance import Lineage

__all__ = ["Decision", "Lineage", "PolicyEngine", "ToolRequest", "Violation"]
