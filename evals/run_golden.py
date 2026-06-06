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


def generate_sql_full_pipeline(question: str, connection_id: str, db) -> str:
    """Generate SQL through the FULL production chat pipeline (intelligence-injected).

    Faithfully mirrors the SQL-generation core of `_stream_chat`
    (aughor/routers/investigations.py) minus the SSE/streaming, final_text,
    insight and follow-up machinery: schema-linker → Data Catalog → context-cap →
    full CHAT_PROMPT (KB / connection-KB / SQL examples / metrics / exploration /
    causal / docs / playbook / rules) → coder LLM → semantic column alignment →
    lint fix → dialect-normalized execute → retry/fix. Returns the FINAL SQL the
    user would actually get (post-retry).

    NOTE: keep in sync with `_stream_chat`. This is a measurement harness, not the
    product path — it deliberately reuses the same building-block functions so the
    eval reflects real platform quality, not a re-implementation.
    """
    from pydantic import BaseModel, Field
    from aughor.llm.provider import get_provider
    from aughor.agent.prompts import CHAT_SQL_SYSTEM, CHAT_PROMPT
    from aughor.rules import get_chat_rules_block

    def _safe_str(fn) -> str:
        try:
            return fn() or ""
        except Exception:
            return ""

    # ── Context sections (same sources as _stream_chat) ──────────────────────
    def _kb() -> str:
        from aughor.semantic.kb_retriever import retrieve_for_planning
        s = retrieve_for_planning(question, top_k=2) or ""
        return (s + "\n\n") if s else ""

    def _ckb() -> str:
        from aughor.semantic.connection_kb import retrieve_for_question as _r
        s = _r(question, connection_id)
        return (s + "\n\n") if s else ""

    def _sqlex() -> str:
        from aughor.tools.prior_analyses import search_sql_examples
        return search_sql_examples(question, connection_id) or ""

    def _metrics(schema_text: str) -> str:
        from aughor.semantic.metrics import build_metrics_block
        s = build_metrics_block(schema_text=schema_text)
        return (s + "\n\n") if s else ""

    def _expl() -> str:
        from aughor.explorer.store import render_exploration_annotations
        s = render_exploration_annotations(connection_id)
        return (s + "\n\n") if s else ""

    def _causal() -> str:
        from aughor.process.causal import build_causal_context_section
        s = build_causal_context_section(question, conn_id=connection_id)
        return (s + "\n") if s else ""

    def _docs() -> str:
        from aughor.knowledge.indexer import build_external_context_section
        s = build_external_context_section(question, top_k=2)
        return (s + "\n\n") if s else ""

    rules_block = _safe_str(get_chat_rules_block)
    kb_patterns_section = _safe_str(_kb)
    conn_kb_section = _safe_str(_ckb)
    sql_examples_section = _safe_str(_sqlex)
    exploration_section = _safe_str(_expl)
    causal_section = _safe_str(_causal)
    document_section = _safe_str(_docs)

    pb_entries = []
    try:
        from aughor.playbook.retriever import retrieve_for_metric_and_phases
        pb_entries = retrieve_for_metric_and_phases([question], limit=4)
    except Exception:
        pb_entries = []

    _schema_name = getattr(db, "_schema_name", None)
    schema_qualifier = (_schema_name or "main") if db.dialect == "duckdb" else (_schema_name or "public")

    # ── Schema: full → schema-linked → Data Catalog → capped ─────────────────
    full_schema = db.get_schema()
    # Metrics are filtered against the FULL schema so a connection's own metrics
    # survive while metrics referencing absent columns (other-connection leakage)
    # are dropped.
    metrics_section = _safe_str(lambda: _metrics(full_schema))
    schema = full_schema
    try:
        from aughor.tools.schema_linker import link_schema_for_prompt
        schema = link_schema_for_prompt(question, schema, top_k_tables=4, top_k_cols=8, connection_id=connection_id)
    except Exception:
        pass
    try:
        from aughor.tools.data_catalog import build_data_catalog
        from aughor.tools.schema import _parse_schema_tables
        linked_tables = list(_parse_schema_tables(schema).keys())
        if linked_tables:
            catalog = build_data_catalog(db, linked_tables)
            if catalog:
                schema = catalog
    except Exception:
        pass
    try:
        from aughor.tools.data_catalog import enforce_context_cap
        schema = enforce_context_cap(schema, max_tables=10)
    except Exception:
        pass

    prompt = CHAT_PROMPT.format(
        schema=schema,
        history_section="",
        question=question,
        schema_qualifier=schema_qualifier,
        kb_patterns_section=kb_patterns_section,
        conn_kb_section=conn_kb_section,
        sql_examples_section=sql_examples_section,
        metrics_section=metrics_section,
        exploration_section=exploration_section,
        causal_section=causal_section,
        document_section=document_section,
    )
    if rules_block:
        prompt = rules_block + prompt
    if pb_entries:
        try:
            from aughor.playbook.retriever import build_playbook_prompt_section
            _pbsec = build_playbook_prompt_section(pb_entries)
            if _pbsec:
                prompt = _pbsec + "\n" + prompt
        except Exception:
            pass

    class ChatAnswerModel(BaseModel):
        sql: str = ""
        headline: str = ""
        chart_type: str = "auto"
        intent: str = ""
        approach: list[str] = Field(default_factory=list)

    answer: ChatAnswerModel = get_provider("coder").complete(
        system=CHAT_SQL_SYSTEM, user=prompt, response_model=ChatAnswerModel,
    )
    final_sql = (answer.sql or "").strip()
    if not final_sql:
        return final_sql

    # ── Semantic column alignment (pre-execution) ────────────────────────────
    _semantic_fix_hint = ""
    try:
        from aughor.tools.semantic_validator import check_entity_column_alignment
        _sem_warnings = check_entity_column_alignment(question, final_sql, schema)
        if _sem_warnings:
            _semantic_fix_hint = " | ".join(w.to_prompt_text() for w in _sem_warnings)
    except Exception:
        pass

    # ── Lint → fix before execution ──────────────────────────────────────────
    from aughor.sql.writer import SqlWriter
    try:
        from aughor.sql.lint import lint as _lint_sql, error_hint as _lint_hint, has_errors as _lint_has_errors
        _lint_issues = _lint_sql(final_sql, dialect=db.dialect)
        if _lint_has_errors(_lint_issues):
            _writer = SqlWriter(db, schema_str=schema)
            _lint_fix = _writer.fix(final_sql, "SQL quality issues detected before execution",
                                    hint=_lint_hint(_lint_issues), max_retries=1)
            if _lint_fix.ok:
                final_sql = _lint_fix.sql
    except Exception:
        pass

    # ── Execute (dialect-normalized) → diagnose → retry/fix ──────────────────
    result = db.execute("__eval_full__", final_sql)
    _zero_diag = None
    try:
        from aughor.agent.investigate import _zero_row_suspicious
        if not result.error and result.row_count == 0:
            _zero_diag = _zero_row_suspicious(final_sql)
    except Exception:
        _zero_diag = None

    if result.error or _zero_diag or _semantic_fix_hint:
        try:
            _writer2 = SqlWriter(db, schema_str=schema)
            _fix_error = (result.error or (_semantic_fix_hint or None) or
                          "Query returned 0 rows — the SQL logic is likely wrong.")
            _combined_hint = " | ".join(filter(None, [_zero_diag or "", _semantic_fix_hint]))
            fix = _writer2.fix(final_sql, _fix_error, hint=_combined_hint, max_retries=1)
            if fix.ok:
                retry = db.execute("__eval_full__", fix.sql)
                if not retry.error and (retry.row_count > 0 or not _zero_diag or _semantic_fix_hint):
                    final_sql = fix.sql
        except Exception:
            pass

    return final_sql.strip()


def run_eval(record: dict, db, live: bool = False, schema: str = "", mode: str | None = None) -> dict:
    """Score a single golden record.

    mode: "reference" (replay reference_sql), "raw" (schema-only LLM, = legacy
    --live), or "full" (full intelligence-injected pipeline). If mode is None it
    is derived from `live` for backward compatibility.
    """
    if mode is None:
        mode = "raw" if live else "reference"

    question = record["question"]
    reference_sql = record.get("reference_sql", "")
    generated_sql = reference_sql
    conn_id = record.get("connection_id", "samples")

    if mode in ("raw", "full"):
        try:
            if mode == "full":
                generated_sql = generate_sql_full_pipeline(question, conn_id, db)
            else:
                generated_sql = generate_sql_chat(question, conn_id, schema)
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
        "generated_sql": generated_sql if mode in ("raw", "full") else "(reference replay)",
        "scores": scores,
        "latency_ms": latency,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="evals/golden_sql_expanded.jsonl")
    parser.add_argument("--connection", default="samples")
    parser.add_argument("--output", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--live", action="store_true", help="Raw schema-only LLM generation (no intelligence injection)")
    parser.add_argument("--full-pipeline", action="store_true", help="Full intelligence-injected pipeline (schema-linker + KB + metrics + retry)")
    parser.add_argument("--by-category", action="store_true", help="Print breakdown by category")
    args = parser.parse_args()

    # Resolve mode: --full-pipeline > --live > reference replay
    mode = "full" if args.full_pipeline else ("raw" if args.live else "reference")

    records = [json.loads(line) for line in open(args.dataset) if line.strip()]
    if args.limit:
        records = records[:args.limit]

    db = open_connection_for(args.connection)

    # Grab schema once for raw generation (full mode fetches+links its own per question)
    schema = ""
    if mode == "raw":
        try:
            schema = db.get_schema()
        except Exception:
            pass

    results = []
    for rec in records:
        results.append(run_eval(rec, db, schema=schema, mode=mode))

    db.close()

    # Summary
    total = len(results)
    perfect = sum(1 for r in results if r["scores"].get("overall", 0) >= 0.99)
    passed_80 = sum(1 for r in results if r["scores"].get("overall", 0) >= 0.80)
    errors = sum(1 for r in results if r["scores"].get("error"))

    _mode_label = {
        "full": "FULL PIPELINE (intelligence-injected)",
        "raw": "RAW LLM (schema-only)",
        "reference": "REFERENCE REPLAY (sanity check)",
    }[mode]
    print(f"\n{'='*60}")
    print(f" Golden SQL Eval  |  mode: {_mode_label}")
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
