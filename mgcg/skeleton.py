"""Skeleton carriers: keep the instruction readable, search only the gaps.

The all-invisible payload was measured to fail. Five ids out of 151,643 fill sixteen slots,
so there is nothing left to encode and the agent reads the file and reports. The useful
inverse of that experiment is this: leave every letter where it is, and let the only free
variables be the gaps, meaning where an invisible character is inserted and how many.

That is a real search rather than a formality, because the keyword guard matches word
characters. One invisible character inside a word ends the match, while the model still
reads the word. So the choice has two consequences at once: it decides whether the guard
sees a request, and it decides how much the sentence costs the model in likelihood.

This module only handles text. The search over positions lives in `scripts/skel.py`.
"""

from __future__ import annotations

from typing import Iterable, Iterator

from .invisible import INVISIBLE_CHARS

# Fixed order so a sweep is reproducible and two runs can be compared row by row.
CHARS: tuple[str, ...] = tuple(sorted(INVISIBLE_CHARS))


def render(text: str, inserts: Iterable[tuple[int, str]]) -> str:
    """Insert (index, char) pairs into `text`.

    Indexes refer to the plain text, so a caller can describe several insertions at once
    without recomputing offsets. Insertions are applied right to left for that reason.
    """
    out = text
    for pos, ch in sorted(inserts, key=lambda p: p[0], reverse=True):
        if not 0 <= pos <= len(text):
            raise ValueError(f"insert position {pos} outside 0..{len(text)}")
        out = out[:pos] + ch + out[pos:]
    return out


def in_word_gaps(text: str) -> list[int]:
    """Gaps whose two neighbours are both word characters.

    An insertion here splits a word, which is the only thing that makes the keyword guard
    lose its match. Insertion elsewhere does not change what the guard sees.
    """
    return [i for i in range(1, len(text)) if text[i - 1].isalnum() and text[i].isalnum()]


def single_candidates(text: str, chars: Iterable[str] | None = None) -> Iterator[tuple[int, str]]:
    """Every (position, character) pair worth trying at one insertion."""
    for pos in in_word_gaps(text):
        for ch in (CHARS if chars is None else tuple(chars)):
            yield pos, ch


def describe(text: str, pos: int, ch: str) -> str:
    """A readable tag for one insertion, e.g. `For|ward` with U+200B."""
    left, right = text[max(0, pos - 3) : pos], text[pos : pos + 3]
    return f"{left}|{right} U+{ord(ch):04X}"
