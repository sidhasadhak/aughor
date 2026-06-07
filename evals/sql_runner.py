#!/usr/bin/env python3
"""SQL correctness evaluator for Aughor chat/direct mode.

Feeds golden questions into the chat path, captures generated SQL,
executes it, and scores correctness based on result shape and execution success.

Usage:
    .venv/bin/python evals/sql_runner.py --dataset evals/golden_sql.jsonl --connection fixture --limit 5
"""
from __future__ import annotations

import argparse
import json
import sys
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from aughor.db.connection import open_connection_for
from aughor.llm.provider import get_provider
from aughor.agent.prompts import CHAT_PROMPT, CHAT_SQL_SYSTEM
from aughor.semantic.metrics import build_metrics_block
from aughor.semantic.glossary import load_merged_glossary
from aughor.semantic.kb_retriever import retrieve_for_planning
from aughor.semantic.connection_kb import retrieve_for_question as retrieve_conn_kb
from aughor.tools.prior_analyses import search_sql_examples
from aughor.explorer.store import render_exploration_annotations


def run_chat_sql(question: str, db, connection_id: str) -> dict:
    """Run a single question through the chat SQL generator and return the result."""
    schema = db.get_schema()
    _schema_name = getattr(db, "_schema_name", None)
    schema_qualifier = (_schema_name or "main") if db.dialect == "duckdb" else (_schema_name or "public")

    # Build context sections (simplified from _stream_chat)
    metrics_section = build_metrics_block()
    if metrics_section:
        metrics_section = metrics_section + "\n\n"
    else:
        metrics_section = ""

    kb_patterns_section = ""
    try:
        s = retrieve_for_planning(question, top_k=2) or ""
        if s:
            kb_patterns_section = s + "\n\n"
    except Exception:
        pass

    conn_kb_section = ""
    try:
        from aughor.semantic.connection_kb import retrieve_for_question as _r
        s = _r(question, connection_id)
        if s:
            conn_kb_section = s + "\n\n"
    except Exception:
        pass

    sql_examples_section = ""
    try:
        from aughor.tools.prior_analyses import search_sql_examples
        s = search_sql_examples(question, connection_id) or ""
        if s:
            sql_examples_section = s + "\n\n"
    except Exception:
        pass

    exploration_section = ""
    try:
        from aughor.explorer.store import render_exploration_annotations
        s = render_exploration_annotations(connection_id)
        if s:
            exploration_section = s + "\n\n"
    except Exception:
        pass

    prompt = CHAT_PROMPT.format(
        schema=schema,
        metrics_section=metrics_section,
        conn_kb_section=conn_kb_section,
        exploration_section=exploration_section,
        causal_section="",
        document_section="",
        sql_examples_section=sql_examples_section,
        kb_patterns_section=kb_patterns_section,
        history_section="",
        question=question,
        schema_qualifier=schema_qualifier,
    )

    # Call LLM
    provider = get_provider("coder")
    answer = provider.complete(system=CHAT_SQL_SYSTEM, user=prompt, response_model=None)

    # Parse the answer - if it's a string, try to extract JSON or SQL
    sql = ""
    headline = ""
    chart_type = "auto"
    intent = ""
    approach = []

    if isinstance(answer, str):
        # Try to find SQL block
        sql_match = re.search(r"```sql\s*(.*?)\s*```", answer, re.DOTALL | re.IGNORECASE)
        if sql_match:
            sql = sql_match.group(1).strip()
        else:
            # Try to find SELECT statement
            select_match = re.search(r"(SELECT\s+.*?;?)(?:\n|$)", answer, re.DOTALL | re.IGNORECASE)
            if select_match:
                sql = select_match.group(1).strip()
        text = answer.lower()
        # Simple headline extraction
        lines = [l.strip() for l in answer.split('\n') if l.strip() and not l.strip().startswith('```') and not l.strip().startswith('SELECT')]
        if lines:
            headline = lines[0]
    elif isinstance(answer, dict):
        sql = answer.get("sql", "")
        headline = answer.get("headline", "")
        chart_type = answer.get("chart_type", "auto")
        intent = answer.get("intent", "")
        approach = answer.get("approach", [])
    else:
        # Pydantic model
        sql = getattr(answer, "sql", "")
        headline = getattr(answer, "headline", "")
        chart_type = getattr(answer, "chart_type", "auto")
        intent = getattr(answer, "intent", "")
        approach = getattr(answer, "approach", [])

    return {
        "sql": sql,
        "headline": headline,
        "chart_type": chart_type,
        "intent": intent,
        "approach": approach,
    }


def execute_sql(db, sql: str) -> dict:
    """Execute SQL and return result metadata."""
    result = db.execute("__eval__", sql)
    return {
        "success": not result.error,
        "error": result.error,
        "row_count": result.row_count,
        "columns": result.columns,
        "first_rows": result.rows[:5] if result.rows else [],
    }


def score_result(record: dict, generated: dict, execution: dict) -> dict:
    """Score a single result."""
    scores = {}

    # Execution success (0 or 1)
    scores["execution_success"] = 1.0 if execution["success"] else 0.0

    # SQL shape: column count within expected range
    col_count = len(execution.get("columns", []))
    expected_min = record.get("expected_columns_min", 1)
    expected_max = record.get("expected_columns_max", 5)
    if expected_min <= col_count <= expected_max:
        scores["column_shape"] = 1.0
    else:
        scores["column_shape"] = 0.0

    # Keyword presence in SQL
    expected_keywords = record.get("expected_sql_contains", [])
    sql_lower = generated.get("sql", "").lower()
    keyword_hits = sum(1 for kw in expected_keywords if kw.lower() in sql_lower)
    if expected_keywords:
        scores["keyword_presence"] = keyword_hits / len(expected_keywords)
    else:
        scores["keyword_presence"] = 1.0

    # Row count check: should return some rows (unless it's a count that might return 0)
    if execution["success"] and execution["row_count"] > 0:
        scores["returns_rows"] = 1.0
    elif execution["success"]:
        scores["returns_rows"] = 0.5  # executed but 0 rows
    else:
        scores["returns_rows"] = 0.0

    # Overall score (weighted)
    overall = (
        scores["execution_success"] * 0.4 +
        scores["column_shape"] * 0.2 +
        scores["keyword_presence"] * 0.2 +
        scores["returns_rows"] * 0.2
    )
    scores["overall"] = round(overall, 3)

    return scores


def main():
    parser = argparse.ArgumentParser(description="Aughor SQL correctness evaluator")
    parser.add_argument("--dataset", default="evals/golden_sql.jsonl", help="Path to golden dataset")
    parser.add_argument("--connection", default="fixture", help="Connection ID to test against")
    parser.add_argument("--limit", type=int, default=None, help="Limit to first N records")
    parser.add_argument("--output", default=None, help="Output JSON file for results")
    args = parser.parse_args()

    # Load dataset
    records = []
    with open(args.dataset) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    if args.limit:
        records = records[:args.limit]

    # Open connection
    db = open_connection_for(args.connection)

    results = []
    total_scores = {
        "execution_success": [],
        "column_shape": [],
        "keyword_presence": [],
        "returns_rows": [],
        "overall": [],
    }

    for i, record in enumerate(records, 1):
        print(f"\n[{i}/{len(records)}] {record['id']}: {record['question']}")
        try:
            generated = run_chat_sql(record["question"], db, args.connection)
            execution = execute_sql(db, generated["sql"])
            scores = score_result(record, generated, execution)

            for k in total_scores:
                total_scores[k].append(scores[k])

            results.append({
                "id": record["id"],
                "question": record["question"],
                "category": record.get("category", "unknown"),
                "sql": generated["sql"],
                "headline": generated["headline"],
                "execution": execution,
                "scores": scores,
            })

            status = "PASS" if scores["overall"] >= 0.7 else "FAIL"
            print(f"  SQL: {generated['sql'][:100]}...")
            print(f"  Execution: {'OK' if execution['success'] else 'ERROR'} ({execution.get('error', '')[:80]})")
            print(f"  Columns: {execution.get('columns', [])} | Rows: {execution.get('row_count', 0)}")
            print(f"  Score: {scores['overall']} {status}")

        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({
                "id": record["id"],
                "question": record["question"],
                "error": str(e),
                "scores": {"overall": 0.0},
            })
            for k in total_scores:
                total_scores[k].append(0.0)

    db.close()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for k, vals in total_scores.items():
        if vals:
            avg = sum(vals) / len(vals)
            passed = sum(1 for v in vals if v >= 0.7) if k == "overall" else sum(1 for v in vals if v >= 0.7)
            print(f"  {k}: avg={avg:.2f} | passed={passed}/{len(vals)}")

    overall_avg = sum(total_scores["overall"]) / len(total_scores["overall"]) if total_scores["overall"] else 0
    overall_passed = sum(1 for v in total_scores["overall"] if v >= 0.7)
    print(f"\n  OVERALL PASS RATE: {overall_passed}/{len(records)} ({100*overall_passed/len(records):.1f}%)")
    print(f"  OVERALL AVG SCORE: {overall_avg:.2f}")

    if args.output:
        with open(args.output, "w") as f:
            json.dump({"results": results, "summary": {k: sum(v)/len(v) if v else 0 for k,v in total_scores.items()}}, f, indent=2, default=str)
        print(f"\nResults written to {args.output}")


if __name__ == "__main__":
    main()
