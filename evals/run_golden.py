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
import os
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Load .env so the eval uses the CONFIGURED coder model (AUGHOR_CODER_MODEL),
# not the provider's stale hardcoded default. As a standalone script this never
# imports api.py (which is what loads dotenv for the app), so without this the
# whole run silently fell back to qwen2.5-coder:32b — uninstalled → every
# generation 404'd and scored 0 (a measurement that looked stable but was empty).
try:
    from dotenv import load_dotenv
    load_dotenv(_REPO_ROOT / ".env")
except ImportError:
    pass

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


def generate_sql_chat(question: str, connection_id: str, schema: str, temperature: float = 0.0) -> str:
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
        temperature=temperature,
    )
    return answer.sql.strip()


def generate_sql_full_pipeline(question: str, connection_id: str, db, temperature: float = 0.0, return_answer: bool = False):
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
        s = build_metrics_block(schema_text=schema_text, connection_id=connection_id)
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
        schema = link_schema_for_prompt(question, schema, top_k_tables=8, top_k_cols=8, connection_id=connection_id)
    except Exception:
        pass
    linked_tables: list[str] = []
    try:
        from aughor.tools.data_catalog import build_data_catalog
        from aughor.tools.schema import _parse_schema_tables, fk_neighbor_expand, temporal_dimension_tables
        linked_tables = list(_parse_schema_tables(schema).keys())
        if linked_tables:
            # Add the date/time dimension first (before FK expansion + the 10-table
            # cap) so a temporal question keeps it; then pull in FK neighbours.
            for _dt in temporal_dimension_tables(full_schema, linked_tables, question):
                if _dt not in linked_tables:
                    linked_tables.append(_dt)
            linked_tables = fk_neighbor_expand(full_schema, linked_tables, cap=10)
            catalog = build_data_catalog(db, linked_tables)
            if catalog:
                schema = catalog
    except Exception:
        pass

    # M24c: verified semantic layer (object sets + computed properties) for the
    # linked entities — mirrors the chat path so the eval measures the same lift.
    semantic_layer_section = ""
    try:
        from aughor.ontology.store import load_latest_ontology
        from aughor.ontology.semantic_block import render_semantic_layer
        semantic_layer_section = render_semantic_layer(
            load_latest_ontology(connection_id), linked_tables
        )
    except Exception:
        semantic_layer_section = ""
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
    # M24c: verified semantic layer (object sets + computed properties), below trusted.
    if semantic_layer_section:
        prompt = semantic_layer_section + "\n\n" + prompt
    # Trusted query templates (authoritative) — prepended last so they sit at the
    # very top. Verified patterns the model reuses to avoid fan-out/grain errors.
    try:
        from aughor.semantic.trusted_queries import retrieve_trusted, build_trusted_block
        _tblk = build_trusted_block(retrieve_trusted(question, connection_id))
        if _tblk:
            prompt = _tblk + "\n" + prompt
    except Exception:
        pass

    from pydantic import field_validator

    class ChatAnswerModel(BaseModel):
        sql: str = ""
        headline: str = ""
        chart_type: str = "auto"
        intent: str = ""
        approach: list[str] = Field(default_factory=list)

        @field_validator("approach", mode="before")
        @classmethod
        def _coerce_approach(cls, v):
            # Local models sometimes return approach as a JSON-encoded string or
            # newline-joined list — mirror _ChatAnswer's coercion so it doesn't
            # trigger a validation retry (noise + latency) on every question.
            if isinstance(v, str):
                import json as _j
                try:
                    x = _j.loads(v)
                    if isinstance(x, list):
                        return [str(i) for i in x]
                except Exception:
                    pass
                return [s.strip() for s in v.splitlines() if s.strip()]
            return v

    answer: ChatAnswerModel = get_provider("coder").complete(
        system=CHAT_SQL_SYSTEM, user=prompt, response_model=ChatAnswerModel,
        temperature=temperature,
    )
    final_sql = (answer.sql or "").strip()
    if not final_sql:
        return (final_sql, answer) if return_answer else final_sql

    # ── Semantic column alignment (pre-execution) ────────────────────────────
    _semantic_fix_hint = ""
    try:
        from aughor.tools.semantic_validator import check_entity_column_alignment
        _sem_warnings = check_entity_column_alignment(question, final_sql, schema)
        if _sem_warnings:
            _semantic_fix_hint = " | ".join(w.to_prompt_text() for w in _sem_warnings)
    except Exception:
        pass

    # ── Fan-out: deterministic de-fan first, else LLM hint (mirrors _stream_chat) ─
    _fanout_fix_hint = ""
    try:
        from aughor.sql.fanout import detect_fanout, defan
        from aughor.tools.schema import _parse_schema_tables as _pst
        _ff = detect_fanout(final_sql, _pst(full_schema), dialect=db.dialect)
        if _ff:
            _rw = defan(final_sql, _ff, dialect=db.dialect)
            if _rw and _rw.strip() != final_sql.strip() and db.dry_run(_rw)[0]:
                final_sql = _rw
            else:
                _fanout_fix_hint = _ff.to_prompt_text()
    except Exception:
        pass

    # ── Lint → fix before execution ──────────────────────────────────────────
    from aughor.sql.writer import SqlWriter
    try:
        from aughor.sql.lint import lint as _lint_sql, error_hint as _lint_hint, has_errors as _lint_has_errors
        _lint_issues = _lint_sql(final_sql, dialect=db.dialect)
        if _lint_has_errors(_lint_issues):
            _writer = SqlWriter(db, schema_str=schema, temperature=temperature)
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

    if result.error or _zero_diag or _semantic_fix_hint or _fanout_fix_hint:
        try:
            _writer2 = SqlWriter(db, schema_str=schema, temperature=temperature)
            _fix_error = (result.error or (_semantic_fix_hint or None) or
                          (_fanout_fix_hint or None) or
                          "Query returned 0 rows — the SQL logic is likely wrong.")
            _combined_hint = " | ".join(filter(None, [_zero_diag or "", _semantic_fix_hint, _fanout_fix_hint]))
            fix = _writer2.fix(final_sql, _fix_error, hint=_combined_hint, max_retries=1)
            if fix.ok:
                retry = db.execute("__eval_full__", fix.sql)
                if not retry.error and (retry.row_count > 0 or not _zero_diag or _semantic_fix_hint or _fanout_fix_hint):
                    final_sql = fix.sql
        except Exception:
            pass

    if return_answer:
        return final_sql.strip(), answer
    return final_sql.strip()


def run_eval(record: dict, db, live: bool = False, schema: str = "", mode: str | None = None,
             temperature: float = 0.0) -> dict:
    """Score a single golden record.

    mode: "reference" (replay reference_sql), "raw" (schema-only LLM, = legacy
    --live), or "full" (full intelligence-injected pipeline). If mode is None it
    is derived from `live` for backward compatibility.

    temperature: decode temperature for the coder (0.0 = deterministic, the eval
    default — see the noise-control caveat in eval_golden_baseline).
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
                generated_sql = generate_sql_full_pipeline(question, conn_id, db, temperature=temperature)
            else:
                generated_sql = generate_sql_chat(question, conn_id, schema, temperature=temperature)
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


def _volatile_semantic_state(connection_id: str) -> dict:
    """Measure the run-to-run-VOLATILE injected context for a connection.

    Exploration insights drift every time the explorer runs, and they steer the
    model's metric choice (the #13 confound: workspace's ~25 insights pushed
    revenue onto order_items). The ontology is curated but connection-specific.
    A trustworthy FULL run must pin these to a known state.
    """
    expl_bytes = 0
    ont_state = "none"
    try:
        from aughor.explorer.store import render_exploration_annotations
        expl_bytes = len(render_exploration_annotations(connection_id) or "")
    except Exception:
        pass
    try:
        from aughor.ontology.store import load_latest_ontology
        ont_state = "present" if load_latest_ontology(connection_id) else "none"
    except Exception:
        pass
    return {"exploration_bytes": expl_bytes, "ontology": ont_state}


def _print_provenance(connection_id: str, mode: str, temperature: float, runs: int) -> dict:
    """Print (and return) the full run configuration so every eval self-documents
    WHAT was measured — model, decode temperature, and the injected semantic
    state. Without this, a cross-connection confound is invisible after the fact."""
    from aughor.llm.provider import get_provider
    p = get_provider("coder")
    vol = _volatile_semantic_state(connection_id)
    fallback_disabled = os.environ.get("AUGHOR_FALLBACK_DISABLED", "") not in ("", "0", "false", "False")
    print(f"\n{'-'*60}")
    print(" Run provenance (pin this to compare runs)")
    print(f"{'-'*60}")
    print(f"  connection        : {connection_id}")
    print(f"  coder backend     : {p.backend}")
    print(f"  coder model       : {p._model}")
    print(f"  temperature       : {temperature}  ({'deterministic' if temperature == 0.0 else 'stochastic'})")
    print(f"  anthropic fallback: {'disabled' if fallback_disabled else 'ENABLED (model not pinned!)'}")
    print(f"  runs/question     : {runs}")
    if mode == "full":
        print(f"  exploration state : {vol['exploration_bytes']} bytes "
              f"({'CLEAN' if vol['exploration_bytes'] == 0 else 'POLLUTED — steers metric choice'})")
        print(f"  ontology          : {vol['ontology']}")
    print(f"{'-'*60}")
    return vol


def _assert_frozen_semantics(connection_id: str, allow_exploration: bool) -> None:
    """Refuse a FULL run on a connection carrying volatile exploration insights,
    unless explicitly allowed. This is the guard that makes the #13 confound
    (running on `workspace` with ~25 drifting insights) impossible to reintroduce
    silently — the eval aborts loudly instead of quietly mismeasuring."""
    vol = _volatile_semantic_state(connection_id)
    if vol["exploration_bytes"] > 0 and not allow_exploration:
        print(f"\n*** FROZEN-STATE GUARD: connection '{connection_id}' carries "
              f"{vol['exploration_bytes']} bytes of exploration insights. ***")
        print("    These steer the model's metric definition and drift run-to-run,")
        print("    so the eval cannot measure capability lift comparably (the #13")
        print("    confound). Use a pinned, unexplored connection (e.g. `samples`),")
        print("    or pass --allow-exploration to override deliberately.")
        raise SystemExit(2)


def _aggregate_runs(runs: list[dict]) -> dict:
    """Collapse N repeated runs of ONE question into a single result carrying the
    per-question score band — the proof that decode noise is (or isn't) controlled."""
    overalls = [r["scores"].get("overall", 0.0) for r in runs]
    lo, hi = min(overalls), max(overalls)
    mean = round(sum(overalls) / len(overalls), 3)
    base = dict(runs[0])
    base["scores"] = dict(runs[0]["scores"])
    base["scores"]["overall"] = mean  # summary uses the expected (mean) score
    base["runs_overall"] = overalls
    # Cache each run's generated SQL + key sub-scores so the whole N-run batch can
    # be RE-SCORED offline (e.g. under a different metric definition) WITHOUT
    # re-spending LLM calls — decouples generation cost from scoring iteration.
    base["runs_detail"] = [
        {"generated_sql": r.get("generated_sql"),
         "overall": r["scores"].get("overall", 0.0),
         "matched_reference": r["scores"].get("matched_reference", 0),
         "error": r["scores"].get("error")}
        for r in runs
    ]
    base["overall_min"] = lo
    base["overall_max"] = hi
    base["overall_band"] = round(hi - lo, 3)
    base["unstable"] = (hi - lo) > 0.05
    return base


def main():
    # Eval integrity: pin the model by disabling the silent Anthropic fallback
    # (so a backend hiccup can't swap models mid-run), unless the user overrode.
    os.environ.setdefault("AUGHOR_FALLBACK_DISABLED", "1")

    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="evals/golden_sql_expanded.jsonl")
    parser.add_argument("--connection", default="samples")
    parser.add_argument("--output", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--live", action="store_true", help="Raw schema-only LLM generation (no intelligence injection)")
    parser.add_argument("--full-pipeline", action="store_true", help="Full intelligence-injected pipeline (schema-linker + KB + metrics + retry)")
    parser.add_argument("--by-category", action="store_true", help="Print breakdown by category")
    parser.add_argument("--temperature", type=float, default=0.0,
                        help="Coder decode temperature (default 0.0 = deterministic, noise-controlled)")
    parser.add_argument("--runs", type=int, default=1,
                        help="Run each question N times and report the score band (noise control / stability)")
    parser.add_argument("--allow-exploration", action="store_true",
                        help="Override the frozen-state guard and run FULL on a connection with exploration insights")
    args = parser.parse_args()

    # Resolve mode: --full-pipeline > --live > reference replay
    mode = "full" if args.full_pipeline else ("raw" if args.live else "reference")

    records = [json.loads(line) for line in open(args.dataset) if line.strip()]
    if args.limit:
        records = records[:args.limit]

    # Lever 1 (freeze-guard): a FULL run must use a pinned, unexplored connection.
    if mode == "full":
        _assert_frozen_semantics(args.connection, args.allow_exploration)

    db = open_connection_for(args.connection)

    # Self-document the run (model / temperature / injected state).
    if mode in ("raw", "full"):
        _print_provenance(args.connection, mode, args.temperature, args.runs)

    # Grab schema once for raw generation (full mode fetches+links its own per question)
    schema = ""
    if mode == "raw":
        try:
            schema = db.get_schema()
        except Exception:
            pass

    _live = mode in ("raw", "full")
    n_runs = max(1, args.runs) if _live else 1
    results = []
    for idx, rec in enumerate(records, 1):
        if _live:
            print(f"  [{idx}/{len(records)}] {rec['id']} ...", file=sys.stderr, flush=True)
        if n_runs > 1:
            reps = [run_eval(rec, db, schema=schema, mode=mode, temperature=args.temperature)
                    for _ in range(n_runs)]
            results.append(_aggregate_runs(reps))
        else:
            results.append(run_eval(rec, db, schema=schema, mode=mode, temperature=args.temperature))

    db.close()

    # Summary
    total = len(results)
    perfect = sum(1 for r in results if r["scores"].get("overall", 0) >= 0.99)
    passed_80 = sum(1 for r in results if r["scores"].get("overall", 0) >= 0.80)
    errors = sum(1 for r in results if r["scores"].get("error"))
    # Metric-aware: how many answers matched an ACCEPTED ALTERNATIVE (e.g. a valid
    # but different revenue definition than the golden's). >0 means the scorer's
    # metric-awareness is doing real work this run.
    alt_matches = sum(1 for r in results if r["scores"].get("matched_reference", 0))

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
    if _live:
        print(f"Metric-alt hits : {alt_matches}  (valid non-golden metric definition accepted)")
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

    # Stability / noise band (only meaningful when each question ran N>1 times).
    # This is the PROOF that decode noise is controlled: at temperature 0 the band
    # should collapse toward 0, versus the documented ±2-4 question run-to-run swing.
    if n_runs > 1:
        unstable = [r for r in results if r.get("unstable")]
        bands = [r.get("overall_band", 0.0) for r in results if "overall_band" in r]
        avg_band = round(sum(bands) / len(bands), 4) if bands else 0.0
        print(f"\n--- Stability across {n_runs} runs (temperature={args.temperature}) ---")
        print(f"  Unstable questions (band > 0.05): {len(unstable)}/{total}")
        print(f"  Mean per-question score band    : {avg_band}")
        if unstable:
            print("  Most volatile:")
            for r in sorted(unstable, key=lambda x: -x.get("overall_band", 0))[:5]:
                print(f"    [{r['id']}] band={r.get('overall_band')} runs={r.get('runs_overall')} | {r['question'][:50]}")

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
