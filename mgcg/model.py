"""Load the target model and return its tokenizer and input embedding matrix.

The embedding weights are required to compute gradients, so GCG inherently needs
"visible weights" -- which is why attacks of this kind only apply to open-weight models.

torch is imported inside functions so the judgement logic stays testable without a GPU.
"""

from __future__ import annotations

import os
from typing import Any


def pick_device(prefer: str = "auto") -> Any:
    import torch

    if prefer != "auto":
        return torch.device(prefer)
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def load_model(name: str, device: str = "auto", dtype: str = "auto"):
    """Return (tok, model, W). Parameters are frozen and the model is in eval mode."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    dev = pick_device(device)
    tok = AutoTokenizer.from_pretrained(name, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    if dtype == "auto":
        td = torch.bfloat16 if dev.type == "cuda" else torch.float32
    else:
        td = getattr(torch, dtype)

    model = AutoModelForCausalLM.from_pretrained(
        name,
        torch_dtype=td,
        trust_remote_code=True,
        low_cpu_mem_usage=True,
    ).to(dev)
    model.eval()
    for p in model.parameters():
        p.requires_grad_(False)

    W = model.get_input_embeddings().weight
    assert W.dim() == 2, f"unexpected embedding shape: {tuple(W.shape)}"
    return tok, model, W


def sdk_path() -> str | None:
    """Locate an external predicate checker package (``aicomp_sdk``).

    Set ``AICOMP_SDK_ROOT`` to the directory that *contains* the package. A ``vendor/``
    directory next to this repo also works. Nothing is hardcoded to a sibling checkout, so
    the repository stays self-contained and L3 simply reports SKIP when the checker is
    absent.
    """
    env = os.environ.get("AICOMP_SDK_ROOT")
    if env and os.path.isdir(env):
        return env
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    vendor = os.path.join(here, "vendor")
    if os.path.isdir(os.path.join(vendor, "aicomp_sdk")):
        return vendor
    return None
