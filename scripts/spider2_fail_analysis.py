#!/usr/bin/env python3
"""Offline fail-analysis of a Spider2-Lite local run (WS5 Phase-0, no LLM, no spend).

Classifies every MISS in evals/spider2_out by failure type so the campaign can target
the lift instead of guessing. Pure comparison of our exec_result CSV against the gold
CSV variants — the same column-containment logic the official evaluator uses (a gold
column must match some predicted column; extras are free; abs_tol 1e-2).

Categories (June histogram vocabulary):
  exec_error     — our SQL produced no result (missing/broken CSV)
  empty_result   — we returned 0 rows but a gold variant has rows
  wrong_shape    — no gold variant's columns are all contained in ours
  wrong_values   — columns contain-match a gold variant but the values don't
"""
from __future__ import annotations

import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path

OUT = Path("evals/spider2_out")
LITE = Path(__file__).parent.parent.parent / "Spider2" / "spider2-lite"
GOLD = LITE / "evaluation_suite" / "gold" / "exec_result"


def _read_csv(path: Path):
    with path.open() as fh:
        rows = list(csv.reader(fh))
    if not rows:
        return [], []
    return rows[0], rows[1:]


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _col_contained(gold_col, pred_cols_data):
    """Is the gold column vector matched by SOME predicted column (as a multiset, tol 1e-2)?"""
    g = sorted((v if v != "" else "0") for v in gold_col)
    for pcol in pred_cols_data:
        p = sorted((v if v != "" else "0") for v in pcol)
        if len(p) != len(g):
            continue
        ok = True
        for a, b in zip(g, p):
            na, nb = _num(a), _num(b)
            if na is not None and nb is not None:
                if not math.isclose(na, nb, abs_tol=1e-2):
                    ok = False
                    break
            elif str(a).strip().lower() != str(b).strip().lower():
                ok = False
                break
        if ok:
            return True
    return False


def _gold_variants(iid: str):
    return sorted(GOLD.glob(f"{iid}_*.csv")) or sorted(GOLD.glob(f"{iid}.csv"))


def classify(iid: str) -> str:
    pred_csv = OUT / "exec_result" / f"{iid}.csv"
    if not pred_csv.exists():
        return "exec_error"
    pcols, prows = _read_csv(pred_csv)
    golds = _gold_variants(iid)
    if not golds:
        return "no_gold"
    # transpose predicted to column vectors
    pred_col_data = [[r[i] if i < len(r) else "" for r in prows] for i in range(len(pcols))]

    best = "wrong_shape"
    for gpath in golds:
        gcols, grows = _read_csv(gpath)
        if not grows and not prows:
            return "correct"  # both empty
        gcol_data = [[r[i] if i < len(r) else "" for r in grows] for i in range(len(gcols))]
        all_contained = all(_col_contained(gc, pred_col_data) for gc in gcol_data)
        if all_contained:
            return "correct"
        # shape check: did we at least have as many rows as this gold?
        if grows and not prows:
            best = "empty_result"
        elif len(pcols) >= len(gcols) and best != "empty_result":
            best = "wrong_values"
    return best


def main() -> int:
    ids_file = OUT / "sql-ids.csv"
    correct = set()
    if ids_file.exists():
        for line in ids_file.read_text().splitlines()[1:]:
            correct.add(line.strip().replace("sf_", ""))

    recs = {r["instance_id"]: r for r in
            (json.loads(l) for l in (LITE / "spider2-lite.jsonl").open() if l.strip())
            if r["instance_id"].startswith("local")}

    cats = Counter()
    ek_miss = 0
    miss_detail = []
    for iid in sorted(recs):
        if iid in correct:
            cats["correct"] += 1
            continue
        c = classify(iid)
        cats[c] += 1
        has_ek = bool(recs[iid].get("external_knowledge"))
        if has_ek:
            ek_miss += 1
        miss_detail.append((iid, c, "EK" if has_ek else "", recs[iid]["question"][:70]))

    total = sum(cats.values())
    print(f"\n=== Spider2-Lite local fail-analysis ({total} instances) ===")
    for cat, n in cats.most_common():
        print(f"  {cat:14} {n:3}  ({100*n/total:.0f}%)")
    n_miss = total - cats.get("correct", 0)
    print(f"\n  misses: {n_miss}  |  of which carry an external-knowledge doc: {ek_miss}")
    print("\n=== miss detail ===")
    for iid, c, ek, q in miss_detail:
        print(f"  {iid:10} {c:13} {ek:3} {q}")

    (OUT / "fail_analysis.json").write_text(json.dumps(
        {"categories": dict(cats), "misses": [
            {"id": i, "cat": c, "ek": bool(e), "q": q} for i, c, e, q in miss_detail]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
