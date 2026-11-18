"""Hard checks performed before any edit is accepted.

The most valuable thing to take from Hybrid GCG is not the algorithm but this discipline:
**before accepting an edit, confirm it did not swap the trajectory for a different one.**

Three gates must pass:

1. Length unchanged — radius-1 coordinate search replaces tokens, it never changes length.
2. Pinned prefix is token-exact — re-tokenize the head text; the resulting ids must equal
   the original sequence position by position.
3. Target string is self-consistent — the ids produced by tokenizing the target text must
   be exactly the ids used to compute the loss.

Gate 2 is where things fail silently: the text looks unchanged, the token boundaries have
moved, and you are now optimizing a trajectory you are not measuring. Failing loudly is
better than optimizing the wrong thing.
"""

from __future__ import annotations

from typing import Any


def check_length(layout, adv_len: int) -> tuple[bool, str]:
    if adv_len != layout.adv_len:
        return False, f"adv length {adv_len} != expected {layout.adv_len}"
    return True, "length unchanged"


def check_head_retokenize(tok, head: str, before_ids) -> tuple[bool, str]:
    """Re-tokenize the head and compare token by token. A mismatch means boundary drift."""
    re_ids = tok(head, return_tensors="pt").input_ids[0].to(before_ids.device)
    if re_ids.numel() != before_ids.numel():
        return False, (
            f"prefix length {re_ids.numel()} != {before_ids.numel()} (token boundary drift)"
        )
    if not bool((re_ids == before_ids).all()):
        bad = int((re_ids != before_ids).nonzero()[0])
        return False, f"prefix token {bad} differs ({int(re_ids[bad])} vs {int(before_ids[bad])})"
    return True, f"prefix of {before_ids.numel()} tokens is token-exact"


def check_target_single(tok, layout, target_text: str) -> tuple[bool, str]:
    """Confirm the ids used for the loss are the ones produced by the target text itself."""
    span = layout.targets[0]
    ids = layout.after_ids[span.start : span.end]
    re_ids = tok(target_text, return_tensors="pt", add_special_tokens=False).input_ids[0].to(ids.device)
    if ids.numel() != re_ids.numel() or not bool((ids == re_ids).all()):
        return False, "target span ids do not match the tokenization of the target text"
    return True, f"target span of {ids.numel()} tokens matches"


def gate(tok, layout, head: str, target_text: str, adv_len: int) -> dict[str, Any]:
    checks = [
        check_length(layout, adv_len),
        check_head_retokenize(tok, head, layout.before_ids),
        check_target_single(tok, layout, target_text),
    ]
    results = [{"ok": ok, "why": why} for ok, why in checks]
    return {"ok": all(c["ok"] for c in checks), "checks": results}
