#!/usr/bin/env python3
"""Execution-accuracy scorer for Aughor SQL generation.

Usage:
    .venv/bin/python evals/sql_accuracy.py --dataset evals/golden_sql_expanded.jsonl --connection samples
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from aughor.db.connection import open_connection_for


def _safe_exec(db, sql: str) -> tuple[bool, list[str], list[list], str | None]:
    """Execute SQL via raw DuckDB cursor to bypass _validate/_normalize_to_duckdb."""
    try:
        conn = getattr(db, "_conn", None)
        if conn is None:
            result = db.execute("__eval__", sql)
            if result.error is not None and result.error != "":
                return False, result.columns, result.rows, result.error
            return True, result.columns, result.rows, None
        conn.execute(sql)
        rows = conn.fetchall()
        columns = [d[0] for d in conn.description] if conn.description else []
        rows = [[str(v) if v is not None else "NULL" for v in row] for row in rows]
        return True, columns, rows, None
    except Exception as e:
        return False, [], [], str(e)


def _row_to_tuple(row: list) -> tuple:
    out = []
    for cell in row:
        if cell is None or cell == "NULL":
            out.append(None)
            continue
        s = str(cell).strip()
        try:
            out.append(int(s))
            continue
        except ValueError:
            pass
        try:
            out.append(round(float(s), 4))
            continue
        except ValueError:
            pass
        if "T" in s and s.count("-") >= 2:
            out.append(s[:10])
            continue
        out.append(s.lower())
    return tuple(out)


def compare_result_sets(ref_cols, ref_rows, gen_cols, gen_rows) -> dict:
    scores: dict[str, float] = {}
    scores["column_count_match"] = 1.0 if len(ref_cols) == len(gen_cols) else 0.0

    ref_norm = [c.lower().strip() for c in ref_cols]
    gen_norm = [c.lower().strip() for c in gen_cols]
    if ref_norm == gen_norm:
        scores["column_name_match"] = 1.0
    elif set(ref_norm) == set(gen_norm):
        scores["column_name_match"] = 0.5
    else:
        scores["column_name_match"] = 0.0

    ref_count = len(ref_rows)
    gen_count = len(gen_rows)
    if ref_count == 0 and gen_count == 0:
        scores["row_count_match"] = 1.0
    elif ref_count == 0 or gen_count == 0:
        scores["row_count_match"] = 0.0
    else:
        ratio = min(ref_count, gen_count) / max(ref_count, gen_count)
        scores["row_count_match"] = 1.0 if ratio >= 0.99 else ratio

    ref_set = {_row_to_tuple(r) for r in ref_rows}
    gen_set = {_row_to_tuple(r) for r in gen_rows}
    if ref_set == gen_set:
        scores["result_set_match"] = 1.0
    else:
        intersection = ref_set & gen_set
        union = ref_set | gen_set
        scores["result_set_match"] = len(intersection) / len(union) if union else 1.0

    ref_top = ref_rows[:5]
    gen_top = gen_rows[:5]
    matches = sum(1 for r, g in zip(ref_top, gen_top) if _row_to_tuple(r) == _row_to_tuple(g))
    scores["top_row_overlap"] = matches / max(len(ref_top), len(gen_top), 1)

    return scores


def _score_vs_reference(ref_cols, ref_rows, gen_cols, gen_rows, gen_ok: bool,
                        ordered: bool = True) -> dict:
    """Score one already-executed generated result against one reference result.

    ``ordered=False`` means the reference SQL carries no ORDER BY, so row order is
    engine nondeterminism, not intent — ``top_row_overlap`` then mirrors the
    set-based ``result_set_match`` instead of penalising a correct answer (or even
    a byte-identical replay) for the order DuckDB's parallel operators happened to
    emit. Two identical EMPTY results are likewise a perfect match, not a 0.
    """
    comparison = compare_result_sets(ref_cols, ref_rows, gen_cols, gen_rows)
    if not ref_rows and not gen_rows:
        comparison["top_row_overlap"] = 1.0
    elif not ordered:
        comparison["top_row_overlap"] = comparison.get("result_set_match", 0.0)
    overall = (
        comparison.get("column_count_match", 0.0) * 0.15 +
        comparison.get("column_name_match", 0.0) * 0.15 +
        comparison.get("row_count_match", 0.0) * 0.15 +
        comparison.get("result_set_match", 0.0) * 0.30 +
        comparison.get("top_row_overlap", 0.0) * 0.10
    )
    # Include execution success (0.15 weight) so total = 1.0
    exec_success = 1.0 if gen_ok else 0.0
    overall = overall + exec_success * 0.15
    comparison["overall"] = round(min(overall, 1.0), 3)
    comparison["execution_success"] = exec_success
    comparison["reference_row_count"] = len(ref_rows)
    comparison["generated_row_count"] = len(gen_rows)
    return comparison


def score_single(db, record: dict, generated_sql: str) -> dict:
    """Score a generated query against the golden reference(s).

    Metric-aware (multi-reference): a record may carry `accept_sql` — a list of
    ALTERNATIVE reference SQLs that are equally-valid ground truth (e.g. revenue
    as SUM(orders.total_amount) vs SUM(order_items.line_total), both defensible
    on the same data). The generated query is scored against the primary
    reference AND every accept_sql; the BEST overall wins. This stops the scorer
    from penalising a correct answer that simply picked a different — but
    canonical — metric definition than the one the reference happened to spell
    (the #13 confound). `matched_reference` records which won (0 = primary,
    1..n = accept_sql index); `num_references` how many were considered.
    """
    ref_sql = record.get("reference_sql", "")
    if not ref_sql:
        return {"overall": 0.0, "error": "No reference SQL"}

    ref_ok, ref_cols, ref_rows, ref_err = _safe_exec(db, ref_sql)
    if not ref_ok:
        return {"overall": 0.0, "execution_success": 0.0, "error": f"Reference failed: {ref_err}", "reference_row_count": 0}

    gen_ok, gen_cols, gen_rows, gen_err = _safe_exec(db, generated_sql)
    if not gen_ok:
        return {"overall": 0.0, "execution_success": 0.0, "error": f"Generated failed: {gen_err}", "reference_row_count": len(ref_rows)}

    # Row order is only part of the ground truth when the reference SQL asked
    # for one — otherwise top-5 comparison is engine nondeterminism (see
    # _score_vs_reference). A subquery-only ORDER BY is treated as ordered too:
    # over-inclusive is the safe direction (may still apply the order check).
    ordered = bool(re.search(r"\border\s+by\b", ref_sql, re.IGNORECASE))

    # Primary reference first; then any equally-valid alternatives.
    best = _score_vs_reference(ref_cols, ref_rows, gen_cols, gen_rows, gen_ok, ordered=ordered)
    best["matched_reference"] = 0
    alts = record.get("accept_sql") or []
    num_refs = 1
    for i, alt_sql in enumerate(alts, start=1):
        alt_ok, alt_cols, alt_rows, _ = _safe_exec(db, alt_sql)
        if not alt_ok:
            # A broken alternative is a dataset-authoring issue, not the model's
            # fault — skip it rather than let it drag the score down.
            continue
        num_refs += 1
        cand = _score_vs_reference(alt_cols, alt_rows, gen_cols, gen_rows, gen_ok,
                                   ordered=bool(re.search(r"\border\s+by\b", alt_sql, re.IGNORECASE)))
        if cand["overall"] > best["overall"]:
            cand["matched_reference"] = i
            best = cand
    best["num_references"] = num_refs
    return best


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="evals/golden_sql_expanded.jsonl")
    parser.add_argument("--connection", default="samples")
    parser.add_argument("--output", default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    records = [json.loads(line) for line in open(args.dataset) if line.strip()]
    if args.limit:
        records = records[:args.limit]

    db = open_connection_for(args.connection)

    all_scores = []
    for rec in records:
        sql = rec.get("reference_sql", "")
        if not sql:
            continue
        ok, cols, rows, err = _safe_exec(db, sql)
        all_scores.append({
            "id": rec["id"],
            "question": rec["question"],
            "category": rec.get("category", "unknown"),
            "difficulty": rec.get("difficulty", "unknown"),
            "reference_sql": sql,
            "execution_success": 1.0 if ok else 0.0,
            "error": err,
            "columns": cols,
            "row_count": len(rows),
            "sample_rows": rows[:3],
        })

    db.close()

    total = len(all_scores)
    passed = sum(1 for r in all_scores if r["execution_success"])
    by_diff = {}
    for r in all_scores:
        d = r["difficulty"]
        by_diff.setdefault(d, {"total": 0, "passed": 0})
        by_diff[d]["total"] += 1
        if r["execution_success"]:
            by_diff[d]["passed"] += 1

    print(f"\nReference SQL validation: {passed}/{total} passed")
    for d, stats in sorted(by_diff.items()):
        print(f"  {d}: {stats['passed']}/{stats['total']} passed")

    if args.output:
        with open(args.output, "w") as f:
            json.dump({"results": all_scores, "summary": {"total": total, "passed": passed, "by_difficulty": by_diff}}, f, indent=2, default=str)
        print(f"\nResults written to {args.output}")


if __name__ == "__main__":
    main()
