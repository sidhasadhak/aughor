#!/usr/bin/env python3
"""Golden dataset SQL-generation evaluator for Aughor.

Runs the full Question → SQL → Execution → Score pipeline against a
reference dataset and reports accuracy breakdowns by difficulty / category.

Usage:
    .venv/bin/python evals/run_golden.py --dataset evals/golden_sql_expanded.jsonl --connection samples --output evals/results.json

If --live is omitted the runner replays the *reference* SQL as a sanity-check
(so you can verify the scoring harness itself).  To evaluate the LLM pass
--live which calls the internal chat pipeline for each question.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evals.sql_accuracy import compare_result_sets, score_single
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


def generate_sql_chat(question: str, connection_id: str, schema: str) -> str:
    """Generate SQL using the same chat pipeline as the UI."""
    from aughor.llm.provider import get_provider
    from aughor.agent.prompts import CHAT_SQL_SYSTEM, CHAT_PROMPT

    # Minimal prompt with schema only (no history, no KB)
    prompt = CHAT_PROMPT.format(
        schema=schema,
        history_section="",
        question=question,
        schema_qualifier="",
        kb_patterns_section="",
        conn_kb_section="",
        sql_examples_section="",
        metrics_section="",
        exploration_section="",
        causal_section="",
        document_section="",
    )

    class _ChatAnswer:
        sql: str = ""
        headline: str = ""
        chart_type: str = "auto"
        intent: str = ""
        approach: list[str] = []

    from pydantic import BaseModel, Field
    class ChatAnswerModel(BaseModel):
        sql: str = ""
        headline: str = ""
        chart_type: str = "auto"
        intent: str = ""
        approach: list[str] = Field(default_factory=list)

    answer: ChatAnswerModel = get_provider("coder").complete(
        system=CHAT_SQL_SYSTEM,
        user=prompt,
        response_model=ChatAnswerModel,
    )
    return answer.sql.strip()


def run_eval(record: dict, db, live: bool = False, schema: str = "") -> dict:
    """Score a single golden record."""
    question = record["question"]
    reference_sql = record.get("reference_sql", "")
    generated_sql = reference_sql

    if live:
        try:
            generated_sql = generate_sql_chat(question, record.get("connection_id", "samples"), schema)
        except Exception as e:
            return {
                "id": record["id"],
                "question": question,
                "difficulty": record.get("difficulty", "unknown"),
                "category": record.get("category", "unknown"),
                "reference_sql": reference_sql,
                "generated_sql": None,
                "scores": {"overall": 0.0, "error": f"Generation failed: {e}"},
                "latency_ms": 0,
            }

    t0 = time.time()
    scores = score_single(db, record, generated_sql)
    latency = round((time.time() - t0) * 1000, 1)

    return {
        "id": record["id"],
        "question": question,
        "difficulty": record.get("difficulty", "unknown"),
        "category": record.get("category", "unknown"),
        "reference_sql": reference_sql,
        "generated_sql": generated_sql if live else "(reference replay)",
        "scores": scores,
        "latency_ms": latency,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="evals/golden_sql_expanded.jsonl")
    parser.add_argument("--connection", default="samples")
    parser.add_argument("--output", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--live", action="store_true", help="Call the live LLM pipeline instead of replaying reference SQL")
    parser.add_argument("--by-category", action="store_true", help="Print breakdown by category")
    args = parser.parse_args()

    records = [json.loads(line) for line in open(args.dataset) if line.strip()]
    if args.limit:
        records = records[:args.limit]

    db = open_connection_for(args.connection)

    # Grab schema once for live generation
    schema = ""
    if args.live:
        try:
            schema = db.get_schema()
        except Exception:
            pass

    results = []
    for rec in records:
        results.append(run_eval(rec, db, live=args.live, schema=schema))

    db.close()

    # Summary
    total = len(results)
    perfect = sum(1 for r in results if r["scores"].get("overall", 0) >= 0.99)
    passed_80 = sum(1 for r in results if r["scores"].get("overall", 0) >= 0.80)
    errors = sum(1 for r in results if r["scores"].get("error"))

    print(f"\n{'='*60}")
    print(f" Golden SQL Eval  |  mode: {'LIVE LLM' if args.live else 'REFERENCE REPLAY (sanity check)'}")
    print(f"{'='*60}")
    print(f"Total questions : {total}")
    print(f"Perfect (≥0.99) : {perfect}")
    print(f"Passed  (≥0.80) : {passed_80}")
    print(f"Errors          : {errors}")
    print(f"{'='*60}")

    # By difficulty
    by_diff = {}
    for r in results:
        d = r["difficulty"]
        by_diff.setdefault(d, {"total": 0, "perfect": 0, "passed_80": 0, "errors": 0})
        by_diff[d]["total"] += 1
        if r["scores"].get("overall", 0) >= 0.99:
            by_diff[d]["perfect"] += 1
        if r["scores"].get("overall", 0) >= 0.80:
            by_diff[d]["passed_80"] += 1
        if r["scores"].get("error"):
            by_diff[d]["errors"] += 1

    print("\nBy difficulty:")
    for d in sorted(by_diff.keys()):
        s = by_diff[d]
        print(f"  {d:6}: {s['perfect']}/{s['total']} perfect, {s['passed_80']}/{s['total']} pass, {s['errors']} errors")

    if args.by_category:
        by_cat = {}
        for r in results:
            c = r["category"]
            by_cat.setdefault(c, {"total": 0, "perfect": 0, "passed_80": 0, "errors": 0})
            by_cat[c]["total"] += 1
            if r["scores"].get("overall", 0) >= 0.99:
                by_cat[c]["perfect"] += 1
            if r["scores"].get("overall", 0) >= 0.80:
                by_cat[c]["passed_80"] += 1
            if r["scores"].get("error"):
                by_cat[c]["errors"] += 1
        print("\nBy category:")
        for c in sorted(by_cat.keys()):
            s = by_cat[c]
            print(f"  {c:20}: {s['perfect']}/{s['total']} perfect, {s['passed_80']}/{s['total']} pass, {s['errors']} errors")

    # Show failures
    failures = [r for r in results if r["scores"].get("overall", 0) < 0.80 or r["scores"].get("error")]
    if failures:
        print(f"\n--- Failures ({len(failures)}) ---")
        for r in failures[:10]:
            print(f"  [{r['id']}] {r['question']} | diff={r['difficulty']} | score={r['scores'].get('overall', 0)}")
            if r["scores"].get("error"):
                print(f"      ERROR: {r['scores']['error']}")

    if args.output:
        with open(args.output, "w") as f:
            json.dump({"results": results, "summary": {
                "total": total,
                "perfect": perfect,
                "passed_80": passed_80,
                "errors": errors,
                "by_difficulty": by_diff,
            }}, f, indent=2, default=str)
        print(f"\nResults written to {args.output}")


if __name__ == "__main__":
    main()
