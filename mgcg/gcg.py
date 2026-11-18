"""GCG search: radius-1 coordinate search with power-law rank sampling.

Three things differ from textbook GCG, all taken from the public Hybrid GCG approach:

1. **Selectable objective**: NLL or margin. Margin is closer to "would greedy decoding
   pick the wrong token".
2. **Power-law rank sampling**: rather than sampling uniformly from top-k, bias toward the
   head of the ranking with p(r) proportional to 1/r^alpha, keeping some exploration.
3. **The gradient only proposes**: whether an edit is accepted is decided separately
   (see gate.py and verify.py).

Note: the gradient is taken with respect to one-hot weights, not token ids. Token ids are
discrete and not differentiable, so the gradient has to pass through the embedding lookup.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch

from .layout import Layout, loss_from_logits, margin_tensor


@dataclass
class GCGConfig:
    steps: int = 40
    top_k: int = 256
    batch: int = 256
    chunk: int = 32          # forward-pass batch; lower this first when memory is tight
    seed_len: int = 16       # initial adv length
    seed: int = 0
    objective: str = "nll"   # nll | margin | both
    margin_weight: float = 1.0
    alpha: float = 1.0       # power-law exponent; larger biases harder toward the head
    power_law: bool = True


def objective(logits, layout: Layout, cfg: GCGConfig):
    """Return a differentiable scalar objective (lower is better)."""
    nll = loss_from_logits(logits, layout)
    if cfg.objective == "nll":
        return nll
    m = margin_tensor(logits, layout)
    if cfg.objective == "margin":
        return -m
    return nll - float(cfg.margin_weight) * m


def objective_from(nll: float, margin: float, cfg: GCGConfig) -> float:
    if cfg.objective == "nll":
        return nll
    if cfg.objective == "margin":
        return -margin
    return nll - float(cfg.margin_weight) * margin


def token_gradients(model, W: torch.Tensor, layout: Layout, adv_ids: torch.Tensor, cfg: GCGConfig):
    """Return (gradient per position [L, V], nll, margin)."""
    L = int(adv_ids.numel())
    V = int(W.size(0))

    one_hot = torch.zeros(L, V, device=adv_ids.device, dtype=W.dtype)
    one_hot[torch.arange(L, device=adv_ids.device), adv_ids] = 1.0
    one_hot.requires_grad_(True)

    emb = layout.assemble(one_hot @ W, W)              # [1, T, D]
    logits = model(inputs_embeds=emb, use_cache=False).logits
    loss = objective(logits, layout, cfg)
    loss.backward()

    with torch.no_grad():
        nll = float(loss_from_logits(logits, layout))
        marg = float(margin_tensor(logits, layout))

    return one_hot.grad.detach(), nll, marg


@torch.no_grad()
def batch_objective(
    model, W: torch.Tensor, layout: Layout, cands: torch.Tensor, chunk: int, cfg: GCGConfig
) -> list[float]:
    """Score a batch of candidate advs and return one objective value per candidate.

    cands: [N, L]. `chunk` is not a batch size in the usual sense: it is how many
    candidates' full logits are alive in GPU memory at once.
    """
    B = int(layout.before_ids.numel())
    before = W[layout.before_ids].unsqueeze(0)          # [1, Bb, D]
    after = W[layout.after_ids].unsqueeze(0)            # [1, Aa, D]

    out: list[float] = []
    for i in range(0, cands.size(0), chunk):
        c = cands[i : i + chunk]
        adv = W[c]                                      # [n, L, D]
        emb = torch.cat(
            [before.expand(c.size(0), -1, -1), adv, after.expand(c.size(0), -1, -1)],
            dim=1,
        )
        logits = model(inputs_embeds=emb, use_cache=False).logits
        for j in range(c.size(0)):
            out.append(float(objective(logits[j : j + 1], layout, cfg)))
    return out


def init_adv(tok, length: int, device, seed: int = 0) -> torch.Tensor:
    """Random initialization for the adv. For reproducibility across runs, warm-start
    from a previous run's adv_ids instead."""
    import random

    rng = random.Random(seed)
    ids = [rng.randrange(0, tok.vocab_size) for _ in range(length)]
    return torch.tensor(ids, device=device, dtype=torch.long)


def power_law_ranks(k: int, n: int, alpha: float, device, generator=None) -> torch.Tensor:
    """Sample ranks 1..k with p(r) proportional to 1/r^alpha; returns 0-based ranks."""
    ranks = torch.arange(1, k + 1, dtype=torch.float32, device=device)
    p = ranks.pow(-float(alpha))
    p = p / p.sum()
    return torch.multinomial(p, n, replacement=True, generator=generator)


def run_gcg(
    model,
    layout: Layout,
    adv_ids: torch.Tensor,
    cfg: GCGConfig,
    log=print,
    on_accept=None,
):
    """Run the search and return (best adv, best objective value, history)."""
    device = adv_ids.device
    W = model.get_input_embeddings().weight
    adv = adv_ids.clone()
    L = int(adv.numel())

    grad, nll, marg = token_gradients(model, W, layout, adv, cfg)
    cur = objective_from(nll, marg, cfg)
    history = [{"step": 0, "nll": nll, "margin": marg, "obj": cur, "accepted": False}]
    log(f"[gcg] start nll={nll:.4f} margin={marg:+.4f} obj={cur:.4f}")

    for step in range(1, cfg.steps + 1):
        K = min(cfg.top_k, grad.size(-1))
        topk = (-grad).topk(K, dim=-1).indices                       # [L, K]

        pos = torch.randint(0, L, (cfg.batch,), device=device)
        if cfg.power_law:
            pick = power_law_ranks(K, cfg.batch, cfg.alpha, device)
        else:
            pick = torch.randint(0, K, (cfg.batch,), device=device)
        chosen = topk[pos, pick]

        cands = adv.unsqueeze(0).repeat(cfg.batch, 1)
        cands[torch.arange(cfg.batch, device=device), pos] = chosen

        vals = batch_objective(model, W, layout, cands, cfg.chunk, cfg)
        best_i = int(min(range(len(vals)), key=lambda i: vals[i]))
        best_val = vals[best_i]

        accepted = best_val < cur
        if accepted:
            adv = cands[best_i].clone()
            cur = best_val

        # Recompute gradients after every acceptance (and read back nll / margin).
        grad, nll, marg = token_gradients(model, W, layout, adv, cfg)
        row = {"step": step, "nll": nll, "margin": marg, "obj": cur, "accepted": accepted}
        history.append(row)
        if on_accept and accepted:
            on_accept(row, adv)
        if step % 5 == 0 or accepted:
            log(
                f"[gcg] step={step:03d} nll={nll:.4f} margin={marg:+.4f} "
                f"obj={cur:.4f} {'accept' if accepted else 'no'}"
            )

    return adv, cur, history
