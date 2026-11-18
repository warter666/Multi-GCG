"""Multi-GCG: multi-family, multi-objective GCG for targeted tool-call attacks on
tool-using agents.

Modules:
    layout    sequence layout (optimizable span + pinned context + target spans),
              NLL and margin objectives
    gcg       gradient-guided search (radius-1 coordinate search + power-law rank sampling)
    families  the four attack families and their pinned hops
    gate      hard checks performed before any edit is accepted
    verify    three-level verification
    model     target model loading

The gradient only *proposes*. Whether a proposal is really better is decided by a
separate full-context forward pass plus an external predicate checker — the same
separation of concerns the public Hybrid GCG implementation uses.
"""

__all__ = ["layout", "gcg", "families", "gate", "verify", "model"]
