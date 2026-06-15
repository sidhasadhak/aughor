#!/usr/bin/env python3
"""Bootstrap acceptance gate for Spider 2.0 dev-set iteration.

Compares a CHILD run against a PARENT run on the fixed 19-instance dev set and
decides — with a paired bootstrap confidence interval — whether the child is a
GENUINE improvement or just noise. This is the antidote to the optimizer's curse
(per the evolving-agent-harnesses lesson: an R=3-selected champion at 0.809
re-evaluated honestly at 0.598).

A change is ACCEPTED only when the 95% CI lower bound on (child - parent) dev
accuracy is > 0. Per-tier breakdown (easy/medium/hard) is shown so we can see
*where* a change helps or regresses.

Usage:
  python evals/dev_compare.py <parent_run_dir> <child_run_dir>

Each run dir is what spider2_lite.py --out produced; its sibling
"<dir>-ids.csv" lists the correct instance ids (written by Spider's evaluate.py).
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

_REPO = Path(__file__).parent.parent
random_seed = 12345  # fixed so the gate verdict is reproducible


def _correct_ids(run_dir: Path) -> set[str]:
    ids_csv = Path(str(run_dir) + "-ids.csv")
    if not ids_csv.exists():
        sys.exit(f"missing {ids_csv} — run spider2_lite with --score first")
    out = set()
    for i, line in enumerate(ids_csv.read_text().splitlines()):
        if i == 0:
            continue
        out.add(line.strip().replace("sf_", ""))
    return out


def _bootstrap_ci(parent_vec: list[int], child_vec: list[int], B: int = 10000):
    """Paired bootstrap over per-instance outcomes. Returns (mean, lo, hi)."""
    import random
    rng = random.Random(random_seed)
    n = len(parent_vec)
    diffs = []
    for _ in range(B):
        idx = [rng.randrange(n) for _ in range(n)]
        pc = sum(parent_vec[i] for i in idx) / n
        cc = sum(child_vec[i] for i in idx) / n
        diffs.append(cc - pc)
    diffs.sort()
    return (sum(diffs) / B, diffs[int(0.025 * B)], diffs[int(0.975 * B)])


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: dev_compare.py <parent_run_dir> <child_run_dir>")
    parent_dir, child_dir = Path(sys.argv[1]), Path(sys.argv[2])

    dev = json.loads((_REPO / "evals" / "spider2_dev_set.json").read_text())
    tiers = {d["id"]: tier for tier, ds in dev.items() for d in ds}
    ids = list(tiers.keys())

    p_correct, c_correct = _correct_ids(parent_dir), _correct_ids(child_dir)
    p_vec = [1 if i in p_correct else 0 for i in ids]
    c_vec = [1 if i in c_correct else 0 for i in ids]

    print(f"Dev set: {len(ids)} instances  ({parent_dir.name} → {child_dir.name})\n")

    # Per-tier breakdown
    for tier in ("easy", "medium", "hard"):
        t_ids = [i for i in ids if tiers[i] == tier]
        p = sum(1 for i in t_ids if i in p_correct)
        c = sum(1 for i in t_ids if i in c_correct)
        arrow = "→" if p == c else ("↑" if c > p else "↓")
        print(f"  {tier:7}: {p}/{len(t_ids)} {arrow} {c}/{len(t_ids)}")

    p_total, c_total = sum(p_vec), sum(c_vec)
    print(f"\n  TOTAL : {p_total}/{len(ids)} → {c_total}/{len(ids)}")

    gained = sorted(i for i in ids if i not in p_correct and i in c_correct)
    lost = sorted(i for i in ids if i in p_correct and i not in c_correct)
    if gained:
        print(f"  gained: {', '.join(gained)}")
    if lost:
        print(f"  lost  : {', '.join(lost)}")

    mean, lo, hi = _bootstrap_ci(p_vec, c_vec)
    print(f"\n  Δ accuracy: {mean:+.3f}  (95% CI [{lo:+.3f}, {hi:+.3f}])")
    if lo > 0:
        print("  VERDICT: ✅ ACCEPT — child is a genuine improvement (CI lower bound > 0)")
    elif hi < 0:
        print("  VERDICT: ❌ REJECT — child is genuinely worse")
    else:
        print("  VERDICT: ⚪ INCONCLUSIVE — within noise; need more signal "
              "(replicate, enlarge dev set, or a bigger change)")


if __name__ == "__main__":
    main()
