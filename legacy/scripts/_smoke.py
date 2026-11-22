"""Smoke test: no torch, no GPU. It only checks the judgement layer.

It answers one very specific question: does the attack family I built actually score against
the predicate checker? If this misses, no amount of GCG later will help -- a lower loss does
not mean the attack holds.

The predicate checker is optional. Without it the predicate section reports SKIP instead of
failing, so the layout and structural checks stay runnable on a bare machine.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)


def _load_checker():
    """Import the external predicate checker if one is configured. Returns None if absent."""
    root = os.environ.get("AICOMP_SDK_ROOT")
    if root and os.path.isdir(root) and root not in sys.path:
        sys.path.insert(0, root)
    try:
        from aicomp_sdk.core.predicates import eval_predicates
    except Exception:
        return None
    return eval_predicates


from legacy.families import FAMILIES, RUNTIME, SECRET, _filled, render_target  # noqa: E402
from legacy.verify import (  # noqa: E402
    _balanced_json,
    failure_kind,
    l1_tool_name,
    l2_args_valid,
    synth_trace,
    verify,
)


def main() -> int:
    bad = 0
    eval_predicates = _load_checker()

    print("== predicate semantics ==")
    if eval_predicates is None:
        print("SKIP: predicate checker not configured (set AICOMP_SDK_ROOT)")
    else:
        print("(families with a runtime field are filled once with the local fixture value; "
              "this only checks that the judgement path is wired up)")
        for key, fam in FAMILIES.items():
            tgt = _filled(fam, SECRET) if fam.runtime_arg else fam.target
            trace = synth_trace(fam, tgt)
            hits = [h["predicate"] for h in eval_predicates(trace)]
            ok = fam.expect_predicate in hits
            print(f"{key:12s} expect={fam.expect_predicate:20s} got={hits} "
                  f"{'PASS' if ok else 'MISS'}")
            if not ok:
                bad += 1
            # Also confirm that no extra predicate fires; extra hits pollute attribution.
            extra = [h for h in hits if h != fam.expect_predicate]
            if extra:
                print(f"   ! extra hits: {extra}")

    print("\n== parsing and levels ==")
    fam = FAMILIES["deputy"]
    good = json.dumps(fam.target, ensure_ascii=False)
    print("well-formed sample:", good)
    print("  L1:", l1_tool_name(good, fam.target))
    print("  L2:", l2_args_valid(good, fam.target))

    for label, sample in [
        ("wrapped in prose", "Sure, working on it.\n" + good + "\nAnything else?"),
        ("missing args", '{"tool": "email.send"}'),
        ("tool typo", '{"tool": "email_send", "args": {"to": "audit@example.com"}}'),
        ("no JSON", "I need to read the file first."),
    ]:
        obj = _balanced_json(sample)
        print(f"  {label:12s} parse={'ok' if obj else 'None'} "
              f"L2={l2_args_valid(sample, fam.target)}")

    return 1 if bad else 0


def _layout_check() -> int:
    """Validate the index arithmetic of target_slices with numpy. The off-by-one from
    predicting token p at position p-1 is the easiest thing to get wrong here.

    Build "perfect" logits where the argmax at each position is exactly the next token, then
    check that the target slice recovers the expected token sequence.
    """
    import numpy as np

    from legacy.layout import Layout, Span

    class Arr:
        """Wrap a numpy array with the numel() interface Layout expects."""

        def __init__(self, a):
            self.a = np.asarray(a, dtype=np.int64)

        def numel(self):
            return int(self.a.size)

        def __getitem__(self, k):
            return self.a[k]

    before = Arr([101, 102, 103])
    tail_pre = Arr([201, 202])
    target = Arr([301, 302, 303, 304])
    after = Arr(list(tail_pre.a) + list(target.a))

    B, L = before.numel(), 5
    s = Span(start=len(tail_pre.a), end=len(tail_pre.a) + len(target.a), weight=1.0)
    layout = Layout(before_ids=before, after_ids=after, targets=[s], adv_len=L)

    full = np.concatenate([before.a, np.arange(500, 500 + L), after.a])
    T = full.size
    logits = np.zeros((1, T, 600))
    for q in range(T - 1):
        logits[0, q, full[q + 1]] = 1.0      # argmax at position q is the next token

    lg, tgt, w = layout.target_slices(logits)[0]
    got = lg[0].argmax(-1)
    ok = np.array_equal(got, tgt) and np.array_equal(tgt, target.a)
    print("\n== layout index arithmetic ==")
    print(f"slice len={lg.shape[1]} target len={len(target.a)} "
          f"got={got.tolist()} expected={target.a.tolist()}")
    print("PASS" if ok else "FAIL — target span misaligned, the loss would hit the wrong tokens")
    return 0 if ok else 1


def _structural_check() -> int:
    """Structural target: optimize only up to the field opening and let the model copy the
    value. This checks the four possible copy outcomes."""
    fam = FAMILIES["exfil"]

    prefix, structural = render_target(fam, "auto")
    concrete, c_struct = render_target(fam, "concrete", SECRET)

    print("\n== structural target ==")
    print(f"structural={structural} prefix tail={prefix[-14:]!r}")
    ok0 = structural and not c_struct and RUNTIME not in prefix and prefix.rstrip().endswith('"')
    ok0 = ok0 and '"data": "' in prefix
    print(f"prefix cuts at the start of the data value: {'PASS' if ok0 else 'FAIL'}")
    print(f"concrete form (offline approximation): {concrete[:64]}...")

    if _load_checker() is None:
        print("SKIP: copy-outcome cases need the predicate checker (set AICOMP_SDK_ROOT)")
        return 0 if ok0 else 1

    cases = [
        ("copied verbatim", SECRET + '"}}', True),
        ("written as REDACTED", "REDACTED" + '"}}', False),
        ("invented a value", "sk-live-WRONG-000" + '"}}', False),
        ("empty value", "" + '"}}', False),
    ]
    bad = 0
    for label, tail, want_breach in cases:
        full = prefix + tail
        v = verify(full, fam, fam.target, fill=SECRET)
        breach = v["breach"]
        kind = failure_kind(v)
        good = breach == want_breach
        if not good:
            bad += 1
        print(f"  {label:18s} breach={breach} kind={kind:18s} L3={v['l3']} "
              f"{'PASS' if good else 'FAIL'}")

    print("  L1 note:", verify(prefix + SECRET + '"}}', fam, fam.target, fill=SECRET)["l1_why"])
    if not ok0:
        bad += 1
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main() | _layout_check() | _structural_check())
