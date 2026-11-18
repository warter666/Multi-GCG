"""Sequence layout: one optimizable span (the adv) plus pinned context and target spans.

Only the adv span is free; everything before and after is pinned.
`targets` are the tokens we *want* the model to produce, and the loss is computed only
on those positions.

Why the sequence is cut this way: an agent attack differs from plain prompt injection in
its success criterion. What is judged is one concrete tool call, so the optimization
target is a token sequence that is an executable call, not "text that reads as harmful".

torch is imported inside functions only, so the judgement logic can be tested without a GPU.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Span:
    """One span of `after_ids`, as [start, end), plus its weight in the total loss."""

    start: int
    end: int
    weight: float = 1.0


@dataclass
class Layout:
    before_ids: Any          # [B]  every pinned token before the adv
    after_ids: Any           # [A]  every pinned token after the adv (target spans included)
    targets: list[Span] = field(default_factory=list)
    adv_len: int = 0

    def assemble(self, adv_emb, W):
        """Splice an [L, D] adv in the middle and return [1, T, D]."""
        import torch

        before = W[self.before_ids]                    # [B, D]
        after = W[self.after_ids]                      # [A, D]
        return torch.cat([before, adv_emb, after], dim=0).unsqueeze(0)

    def target_slices(self, logits):
        """Return [(logit slice, target ids, weight)].

        Predicting token p uses the logits at position p - 1, so every span shifts left
        by one. Getting this wrong is the classic silent bug: the loss is then computed
        against the wrong tokens.
        """
        B = int(self.before_ids.numel())
        L = int(self.adv_len)
        out = []
        for s in self.targets:
            lo = B + L + s.start - 1
            hi = B + L + s.end - 1
            out.append((logits[:, lo:hi, :], self.after_ids[s.start : s.end], s.weight))
        return out


def loss_from_logits(logits, layout: Layout):
    """Weighted negative log-likelihood over the target spans."""
    import torch

    total = None
    for lg, tgt, w in layout.target_slices(logits):
        logp = torch.log_softmax(lg.float(), dim=-1)
        nll = -logp.gather(-1, tgt.view(1, -1, 1)).squeeze(-1).mean()
        term = float(w) * nll
        total = term if total is None else total + term
    if total is None:
        raise ValueError("layout has no target span; loss is undefined")
    return total


def margin_tensor(logits, layout: Layout):
    """Margin at the first target position: z_target - max_{v != target} z_v.

    This is the objective the public Hybrid GCG implementation uses by default. It is
    closer to "did it win" than NLL is: NLL can keep falling while the runner-up stays
    right behind, and greedy decoding can still emit the wrong token. A positive margin
    means the target token is the greedy winner.
    """
    import torch

    if not layout.targets:
        raise ValueError("layout has no target span; margin is undefined")
    first = layout.targets[0]
    B = int(layout.before_ids.numel())
    L = int(layout.adv_len)
    q = B + L + first.start - 1          # the position that predicts the first target token
    if q < 0:
        raise ValueError("target span starts at position 0; no predicting position available")

    z = logits[0, q, :].float()
    t = int(layout.after_ids[first.start])
    other = z.clone()
    other[t] = float("-inf")
    return z[t] - other.max()


def margin_from_logits(logits, layout: Layout) -> float:
    return float(margin_tensor(logits, layout))
