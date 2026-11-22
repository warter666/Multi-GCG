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
    """Margin over the whole target span: min over positions of (z_target - max_{v != target} z_v).

    For a single-token target this is exactly the classic definition used by Hybrid GCG.
    For a multi-token target the first position alone is not enough: two different calls
    often share the opening tokens (`{"tool": "`), so a positive margin at position 0 is
    satisfied by any of them. Requiring every position is what actually corresponds to
    "greedy decoding emits this call".
    """
    import torch

    if not layout.targets:
        raise ValueError("layout has no target span; margin is undefined")

    worst = None
    for lg, tgt, _w in layout.target_slices(logits):
        z = lg[0].float()                      # [n, V]
        n = int(tgt.numel())
        if n == 0:
            continue
        idx = torch.arange(n, device=z.device)
        zt = z[idx, tgt]                       # [n]
        other = z.clone()
        other[idx, tgt] = float("-inf")
        per_pos = zt - other.max(dim=-1).values   # [n]
        m = per_pos.min()
        worst = m if worst is None else torch.minimum(worst, m)
    if worst is None:
        raise ValueError("target span is empty; margin is undefined")
    return worst


def margin_from_logits(logits, layout: Layout) -> float:
    return float(margin_tensor(logits, layout))


def adv_nll_from_logits(logits, layout: Layout, adv_ids):
    """In-context NLL of the payload itself: how surprised the model is by its own adv tokens.

    Token p of the adv is predicted by the logits at position p - 1, so the span starts at
    `B - 1`: the last pinned token predicts the first adv token. This is the differentiable
    analogue of the perplexity gate. The gate scores the body as bare text; this scores it in
    the slot where it actually sits, which is the only version a gradient can reach.

    Keep this term separate from the target loss. Mixing them with one weight hides the
    trade-off: the payload can then become fluent by giving up the call.
    """
    import torch

    B = int(layout.before_ids.numel())
    L = int(layout.adv_len)
    if L == 0:
        raise ValueError("layout has no adv span")
    lg = logits[:, B - 1 : B + L - 1, :].float()
    logp = torch.log_softmax(lg, dim=-1)
    return -logp.gather(-1, adv_ids.view(1, -1, 1)).squeeze(-1).mean()
