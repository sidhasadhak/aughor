#!/usr/bin/env python3
"""A/B comparator for the model bake-off — turns "26 vs 24" into the per-question
truth: which questions one model REGRESSES and which it FIXES vs the other.

The aggregate pass-count hides the signal that matters for a model swap: a faster
model that nets the same count but quietly breaks 4 questions and fixes 4 others is
NOT a free swap — it moved the failure surface. This diffs by question id at the
0.8 pass threshold and on the mean overall score so that movement is visible.

Usage:
    .venv/bin/python evals/bakeoff_compare.py \
        --a evals/bakeoff_incumbent.json --a-label "qwen3-coder-next" \
        --b evals/bakeoff_gemma.json     --b-label "gemma4:31b"
"""
from __future__ import annotations

import argparse
import json

_PASS = 0.80
_PERFECT = 0.99


def _load(path: str) -> dict:
    with open(path) as f:
        data = json.load(f)
    by_id = {r["id"]: r for r in data.get("results", [])}
    return {"summary": data.get("summary", {}), "by_id": by_id}


def _overall(r: dict) -> float:
    return float((r.get("scores") or {}).get("overall", 0.0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--a-label", default="A")
    ap.add_argument("--b-label", default="B")
    args = ap.parse_args()

    A, B = _load(args.a), _load(args.b)
    sa, sb = A["summary"], B["summary"]

    def line(label, s):
        return (f"  {label:22} perfect {s.get('perfect',0):>2}/{s.get('total',0)}   "
                f"pass≥.80 {s.get('passed_80',0):>2}/{s.get('total',0)}   "
                f"errors {s.get('errors',0):>2}")

    print("=" * 70)
    print(" Model bake-off — quality A/B  (golden SQL, --live)")
    print("=" * 70)
    print(line(args.a_label, sa))
    print(line(args.b_label, sb))
    d_perfect = sb.get("perfect", 0) - sa.get("perfect", 0)
    d_pass = sb.get("passed_80", 0) - sa.get("passed_80", 0)
    print(f"\n  Δ (B − A):  perfect {d_perfect:+d}   pass {d_pass:+d}")

    ids = sorted(set(A["by_id"]) | set(B["by_id"]))
    regressions, fixes, both_fail = [], [], []
    for qid in ids:
        ra, rb = A["by_id"].get(qid), B["by_id"].get(qid)
        if not ra or not rb:
            continue
        oa, ob = _overall(ra), _overall(rb)
        pa, pb = oa >= _PASS, ob >= _PASS
        if pa and not pb:
            regressions.append((qid, oa, ob, rb.get("question", "")[:48]))
        elif pb and not pa:
            fixes.append((qid, oa, ob, rb.get("question", "")[:48]))
        elif not pa and not pb:
            both_fail.append((qid, oa, ob, rb.get("question", "")[:48]))

    print("\n" + "-" * 70)
    print(f" REGRESSIONS — {args.a_label} passed, {args.b_label} failed  ({len(regressions)})")
    print("-" * 70)
    for qid, oa, ob, q in regressions:
        print(f"  ✗ {qid:10} {oa:.2f}→{ob:.2f}  {q}")
    if not regressions:
        print("  (none — no question the faster model broke)")

    print("\n" + "-" * 70)
    print(f" FIXES — {args.b_label} passed, {args.a_label} failed  ({len(fixes)})")
    print("-" * 70)
    for qid, oa, ob, q in fixes:
        print(f"  ✓ {qid:10} {oa:.2f}→{ob:.2f}  {q}")
    if not fixes:
        print("  (none)")

    print(f"\n  both still failing: {len(both_fail)}")
    print("\nVERDICT: a swap is quality-safe when REGRESSIONS ≈ 0 (net pass ≥ 0 is")
    print("not enough — it can hide an even trade that relocates the failures).")


if __name__ == "__main__":
    main()
