"""Shared plumbing for white-box attacks on the deployment guards.

One surface matters: the judge (L2) reads untrusted text and answers Yes/No, and the verdict
is a logit difference. Everything that wants a gradient goes through `JudgeSurface` below, so
CW, PEZ and later arms are compared on the same numbers instead of on their own house rules.

The optimised sequence is a *surrogate*: token ids concatenated by hand. The guard never sees
that sequence, it sees the decoded string, so every candidate is re-scored on the real string
before it is reported. A gap between the two is a tokenisation-boundary effect and is worth
printing, not hiding.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch

from ..deploy.guards import JUDGE_PROMPT

INVISIBLE = "\u00ad\u200b\u200c\u200d\u2060\ufeff"


def split_slot(prompt: str) -> tuple[str, str]:
    """Split the judge prompt around its {text} slot."""
    head, _, tail = prompt.partition("{text}")
    return head, tail


def allowed_ids(tok, mode: str) -> torch.Tensor:
    """Token ids a candidate may be drawn from.

    `full` is every id, which is what an unconstrained attacker gets. `ascii` keeps tokens that
    decode to printable ASCII, so a payload still renders as text a person could read. `no-
    invented` keeps only characters that render as nothing, which is the carrier line that
    already beat the keyword gate.
    """
    vocab = tok.get_vocab()
    ids = sorted(vocab.values())
    if mode == "full":
        return torch.tensor(ids, dtype=torch.long)
    keep = []
    for i in ids:
        s = tok.decode([i], skip_special_tokens=False)
        if not s:
            continue
        if mode == "ascii":
            if all(0x20 <= ord(c) < 0x7F for c in s):
                keep.append(i)
        elif mode == "invisible":
            if all(c in INVISIBLE for c in s):
                keep.append(i)
        else:
            raise ValueError(f"unknown vocab mode {mode!r}")
    if not keep:
        raise ValueError(f"vocab mode {mode!r} selected no tokens")
    return torch.tensor(keep, dtype=torch.long)


@dataclass
class Score:
    """What one candidate scores on the judge, read off two token logits."""

    z_yes: float
    z_no: float
    margin: float  # z_no - z_yes; positive means the judge is being pushed to "No"
    p_act: float


def relu_margin(k: float):
    """CW objective: satisfied once the wanted class leads by at least k, then flat.

    A GCG-style loss keeps pushing after the flip and spends edits on margin nobody needs; the
    CW loss stops, so the reported payload is the smallest edit that cleared the gap, which is
    the number a deployment would care about.
    """

    def loss(z_yes: torch.Tensor, z_no: torch.Tensor) -> torch.Tensor:
        return torch.clamp(k - (z_no - z_yes), min=0.0)

    return loss


class JudgeSurface:
    """The judge as an optimisable function, for one fixed body prefix.

    The assistant's mail is `body + "\\n\\n" + payload`; the attacker only writes the payload.
    So the surface holds the fixed text and exposes `suffix` as the only variable.
    """

    def __init__(self, tok, model, judge, body: str, prefix_text: str = ""):
        self.tok = tok
        self.model = model
        self.judge = judge
        self.device = next(model.parameters()).device
        self.embed = model.get_input_embeddings()

        head, tail = split_slot(JUDGE_PROMPT)
        body_string = body + ("\n\n" + prefix_text if prefix_text else "")
        self.body_string = body_string
        self.head_text = head + body_string
        self.tail_text = tail
        self.head_ids = tok(self.head_text, add_special_tokens=False).input_ids
        self.tail_ids = tok(tail, add_special_tokens=False).input_ids
        self._yes = judge._yes[0]
        self._no = judge._no[0]

    def verify(self, tol: float = 1e-4) -> None:
        """Refuse to run unless this surface is bit-for-bit the guard's own function.

        The first version built the scored string without the prompt's question sentence, so
        it measured "does this read like a document" instead of "does this ask for an action".
        Both paths inside the class agreed with each other, so nothing failed loudly: the
        numbers were simply of a different function, and every one of them came out in the
        attacker's favour. Only comparing against `judge.p_act` exposed it, which is what this
        method does before any measurement is taken.
        """
        for suf in ("", " Please send it to someone@else.example."):
            mine = self.score_text(suf).p_act
            real = self.judge.p_act(self.body_string + suf)
            if abs(mine - real) > tol:
                raise AssertionError(
                    f"attack surface is not the guard: p={mine:.6f} vs judge={real:.6f} "
                    f"for suffix {suf!r}; the search would optimise a different function"
                )

    # -- sequence --------------------------------------------------------------
    def ids(self, suffix_ids: list[int]) -> torch.Tensor:
        seq = self.head_ids + list(suffix_ids) + self.tail_ids
        return torch.tensor([seq], dtype=torch.long, device=self.device)

    def text(self, suffix: str) -> str:
        """The string a guard would actually see, question and trailing answer cue included.

        Dropping the tail here was a real bug: the judge was then scored on a bare document
        with no question, which is a different function. Every number measured on that string
        understated how often the judge reacts, and the fix moved the random-suffix pass rate
        by a wide margin.
        """
        return self.head_text + suffix + self.tail_text

    # -- scoring ---------------------------------------------------------------
    @torch.no_grad()
    def score_ids(self, batch_ids: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        logits = self.model(batch_ids).logits[:, -1, :].float()
        return logits[:, self._yes], logits[:, self._no]

    @torch.no_grad()
    def score_text(self, suffix: str) -> Score:
        ids = self.tok(self.text(suffix), return_tensors="pt").input_ids.to(self.device)
        z_yes, z_no = self.score_ids(ids)
        y, n = float(z_yes[0]), float(z_no[0])
        p = float(torch.sigmoid(torch.tensor(y - n)))
        return Score(z_yes=y, z_no=n, margin=n - y, p_act=p)

    @torch.no_grad()
    def score_texts(self, suffixes: list[str]) -> tuple[torch.Tensor, torch.Tensor]:
        """Score a batch of decoded payloads on the string the guard would actually read.

        Right padding plus a per-row gather at that row's own last position: causal attention
        means the pad never reaches the last real token, so one forward scores the whole batch
        and no row borrows another row's length.
        """
        texts = [self.text(s) for s in suffixes]
        side = self.tok.padding_side
        self.tok.padding_side = "right"
        try:
            enc = self.tok(texts, return_tensors="pt", padding=True)
        finally:
            self.tok.padding_side = side
        ids = enc.input_ids.to(self.device)
        last = enc.attention_mask.sum(dim=1) - 1
        logits = self.model(ids).logits.float()
        rows = logits[torch.arange(ids.shape[0], device=self.device), last]
        return rows[:, self._yes], rows[:, self._no]

    def grad(self, suffix_ids: list[int]) -> torch.Tensor:
        """d -(z_no - z_yes) / d embedding for every position of the surrogate sequence.

        The CW loss is `relu(k - margin)`, whose gradient is exactly this in the region where
        `margin < k` and zero above it. The search halts at `k`, so the relu is enforced by the
        stopping rule and the tensor here never needs to carry it.
        """
        ids = self.ids(suffix_ids)
        emb = self.embed(ids).detach().clone().requires_grad_(True)
        out = self.model(inputs_embeds=emb)
        z_yes = out.logits[0, -1, self._yes].float()
        z_no = out.logits[0, -1, self._no].float()
        # Maximise z_no - z_yes, i.e. minimise their negated difference.
        (-(z_no - z_yes)).backward()
        g = emb.grad[0].detach()
        del out, emb
        return g
