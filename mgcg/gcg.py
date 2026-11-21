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

from dataclasses import dataclass, replace

import torch

from .layout import Layout, adv_nll_from_logits, loss_from_logits, margin_tensor


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
    # Fluency penalty. 0 disables it, which reproduces the unconstrained search. Positive
    # values push the payload toward text the model would write itself, which is the only
    # way it can pass a perplexity gate.
    ppl_weight: float = 0.0
    # Fraction of the budget that holds the penalty at full strength before it decays linearly
    # to zero. 0 keeps it constant. The point of the schedule is path dependence: a payload
    # that starts in the language manifold can move from there, while one that starts as noise
    # gets worse every step.
    ppl_warm_frac: float = 0.0
    # Bool mask [V] over the vocabulary: True where that id may be used. None = unrestricted.
    # This is how the search is confined to a carrier, e.g. the zero-width characters.
    mask: object | None = None


def ppl_weight_at(step: int, cfg: GCGConfig) -> float:
    """The penalty weight used at `step`. Constant unless a warm-up fraction is set."""
    w0 = float(cfg.ppl_weight)
    if w0 <= 0.0 or cfg.ppl_warm_frac <= 0.0 or cfg.steps <= 0:
        return w0
    hold = max(1, int(round(cfg.steps * float(cfg.ppl_warm_frac))))
    if step <= hold or hold >= cfg.steps:
        return w0
    frac = (cfg.steps - step) / float(cfg.steps - hold)
    return w0 * max(0.0, frac)


def objective(logits, layout: Layout, cfg: GCGConfig, adv_ids=None):
    """Return a differentiable scalar objective (lower is better)."""
    nll = loss_from_logits(logits, layout)
    if cfg.objective == "nll":
        obj = nll
    elif cfg.objective == "margin":
        obj = -margin_tensor(logits, layout)
    else:
        obj = nll - float(cfg.margin_weight) * margin_tensor(logits, layout)
    if cfg.ppl_weight:
        if adv_ids is None:
            raise ValueError("ppl_weight is set but no adv ids were passed")
        obj = obj + float(cfg.ppl_weight) * adv_nll_from_logits(logits, layout, adv_ids)
    return obj


def objective_from(nll: float, margin: float, cfg: GCGConfig, adv_nll: float = 0.0) -> float:
    if cfg.objective == "nll":
        obj = nll
    elif cfg.objective == "margin":
        obj = -margin
    else:
        obj = nll - float(cfg.margin_weight) * margin
    if cfg.ppl_weight:
        obj = obj + float(cfg.ppl_weight) * adv_nll
    return obj


def token_gradients(model, W: torch.Tensor, layout: Layout, adv_ids: torch.Tensor, cfg: GCGConfig):
    """Return (gradient per position [L, V], nll, margin, adv_nll)."""
    L = int(adv_ids.numel())
    V = int(W.size(0))

    one_hot = torch.zeros(L, V, device=adv_ids.device, dtype=W.dtype)
    one_hot[torch.arange(L, device=adv_ids.device), adv_ids] = 1.0
    one_hot.requires_grad_(True)

    emb = layout.assemble(one_hot @ W, W)              # [1, T, D]
    logits = model(inputs_embeds=emb, use_cache=False).logits
    loss = objective(logits, layout, cfg, adv_ids)
    loss.backward()

    with torch.no_grad():
        nll = float(loss_from_logits(logits, layout))
        marg = float(margin_tensor(logits, layout))
        adv_nll = float(adv_nll_from_logits(logits, layout, adv_ids))

    return one_hot.grad.detach(), nll, marg, adv_nll


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
            out.append(float(objective(logits[j : j + 1], layout, cfg, c[j])))
    return out


def init_adv(tok, length: int, device, seed: int = 0, allowed=None) -> torch.Tensor:
    """Random initialization for the adv. For reproducibility across runs, warm-start
    from a previous run's adv_ids instead.

    `allowed` restricts the pool, e.g. to ids that render as zero-width characters.
    """
    import random

    rng = random.Random(seed)
    if allowed is None:
        ids = [rng.randrange(0, tok.vocab_size) for _ in range(length)]
    else:
        pool = list(allowed)
        if not pool:
            raise ValueError("allowed pool is empty")
        ids = [pool[rng.randrange(0, len(pool))] for _ in range(length)]
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
    # Seed the torch RNG as well: position and rank sampling both draw from it, so without
    # this two runs with identical arguments diverge.
    torch.manual_seed(int(cfg.seed))
    W = model.get_input_embeddings().weight
    adv = adv_ids.clone()
    L = int(adv.numel())

    step_cfg = replace(cfg, ppl_weight=ppl_weight_at(0, cfg))
    grad, nll, marg, adv_nll = token_gradients(model, W, layout, adv, step_cfg)
    cur = objective_from(nll, marg, step_cfg, adv_nll)
    history = [{
        "step": 0, "nll": nll, "margin": marg, "adv_nll": adv_nll,
        "w": step_cfg.ppl_weight, "obj": cur, "accepted": False,
    }]
    log(f"[gcg] start nll={nll:.4f} margin={marg:+.4f} ppl={adv_nll:.4f} "
        f"w={step_cfg.ppl_weight:.2f} obj={cur:.4f}")

    for step in range(1, cfg.steps + 1):
        step_cfg = replace(cfg, ppl_weight=ppl_weight_at(step, cfg))
        if cfg.mask is not None:
            # Only ids inside the carrier can be proposed. Everything else is excluded, not
            # penalised: a soft penalty would still let an unusable id win late in the run.
            # The tokenizer's vocab size and the model's padded output size differ, so pad.
            m = cfg.mask
            if m.numel() < grad.size(-1):
                m = torch.nn.functional.pad(m, (0, grad.size(-1) - m.numel()))
            grad = grad.masked_fill(~m.unsqueeze(0), float("-inf"))
        K = min(cfg.top_k, grad.size(-1))
        if cfg.mask is not None:
            K = min(K, max(1, int(cfg.mask.sum())))
        topk = (-grad).topk(K, dim=-1).indices                       # [L, K]

        pos = torch.randint(0, L, (cfg.batch,), device=device)
        if cfg.power_law:
            pick = power_law_ranks(K, cfg.batch, cfg.alpha, device)
        else:
            pick = torch.randint(0, K, (cfg.batch,), device=device)
        chosen = topk[pos, pick]

        cands = adv.unsqueeze(0).repeat(cfg.batch, 1)
        cands[torch.arange(cfg.batch, device=device), pos] = chosen

        vals = batch_objective(model, W, layout, cands, cfg.chunk, step_cfg)
        best_i = int(min(range(len(vals)), key=lambda i: vals[i]))
        best_val = vals[best_i]

        accepted = best_val < cur
        if accepted:
            adv = cands[best_i].clone()
            cur = best_val

        # Recompute gradients after every acceptance (and read back nll / margin / ppl).
        grad, nll, marg, adv_nll = token_gradients(model, W, layout, adv, step_cfg)
        row = {
            "step": step, "nll": nll, "margin": marg, "adv_nll": adv_nll,
            "w": step_cfg.ppl_weight, "obj": cur, "accepted": accepted,
        }
        history.append(row)
        if on_accept and accepted:
            on_accept(row, adv)
        if step % 5 == 0 or accepted:
            log(
                f"[gcg] step={step:03d} nll={nll:.4f} margin={marg:+.4f} "
                f"ppl={adv_nll:.4f} w={step_cfg.ppl_weight:.2f} obj={cur:.4f} "
                f"{'accept' if accepted else 'no'}"
            )

    return adv, cur, history
