"""Search inside the invisible characters only.

A payload made of zero-width characters is seen by the tokenizer and by nothing else: no
reader, no regex, no human review. That makes it the natural place for a gradient search to
work, if the model can still be moved by it.

This module answers one question: which vocabulary entries render as nothing? The scan is
cached, because it costs one decode per id and the vocabulary is 150k entries.

Honest expectation, before running it: a payload of pure separators carries no words, so it
probably cannot ask for anything. The measurement decides, not the expectation.
"""

from __future__ import annotations

import json
import os
from typing import Iterable

# Code points that occupy no horizontal space. Anything outside this set is visible.
INVISIBLE_CHARS = frozenset(
    "\u200b\u200c\u200d\u2060\u2061\u2062\u2063\u2064\ufeff\u180e\u00ad"
)


def is_invisible_text(s: str) -> bool:
    """True when every character is zero-width. An empty string is not a payload."""
    return bool(s) and all(ch in INVISIBLE_CHARS for ch in s)


def _cache_path(tok, cache_dir: str) -> str:
    name = getattr(tok, "name_or_path", "tok").replace("/", "_").replace("\\", "_")
    return os.path.join(cache_dir, f"invisible-{name}.json")


def invisible_ids(tok, cache_dir: str = ".cache", log=print) -> list[int]:
    """Vocab ids whose decoded text is entirely zero-width. Cached on disk."""
    os.makedirs(cache_dir, exist_ok=True)
    path = _cache_path(tok, cache_dir)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    ids: list[int] = []
    n = int(tok.vocab_size)
    for i in range(n):
        try:
            s = tok.decode([i])
        except Exception:  # noqa: BLE001
            continue
        if is_invisible_text(s):
            ids.append(i)
        if i and i % 50000 == 0:
            log(f"[invisible] scanned {i}/{n}, kept {len(ids)}")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ids, f)
    log(f"[invisible] kept {len(ids)} of {n} ids")
    return ids


def as_mask(ids: Iterable[int], vocab_size: int, device):
    """Bool mask over the vocabulary: True where the id is usable."""
    import torch

    m = torch.zeros(int(vocab_size), dtype=torch.bool, device=device)
    idx = torch.tensor(list(ids), dtype=torch.long, device=device)
    m[idx] = True
    return m
