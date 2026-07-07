#!/usr/bin/env python3
"""Spider 2.0 campaign harness (WS5) — generate → guard → execute-with-repair → CSV → score.

Rebuilt for the top-3 campaign (docs/10X_AND_SPIDER2_PROGRAM_2026-07-06.md §5; the June
harness was deliberately removed with that arc's conclusion — this one differs where the
study said it must):

  * the per-instance **external-knowledge doc is READ and injected** (the June pipeline
    never read them — a known scoring leak);
  * every instance runs the PRODUCT guard chain (``safety.preflight_repair``) before the
    closed loop, so the campaign measures Aughor, not a bench fork;
  * every instance emits a **submission-ready reasoning trace** (the leaderboard requires
    per-instance traces) with timestamps;
  * results materialize through ``closed_loop.rows_to_csv`` (the evaluator's exact CSV
    contract — real NULLs, cursor column order, no row cap).

P0 scope: the 135 offline SQLite instances of Spider2-Lite (``--subset local``). The same
skeleton later takes the Snowflake connection for Snow/Lite-cloud.

Usage:
  uv run python evals/spider2.py --limit 5                     # smoke
  uv run python evals/spider2.py --ids local002,local009
  uv run python evals/spider2.py --score                       # official evaluate.py over the outdir
  SPIDER2_ROOT=/path/to/Spider2 overrides the default clone location.

NEVER submits anywhere — output stays on disk; leaderboard submission is a
human-approved step by standing rule.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Load .env so the harness uses the CONFIGURED coder model (AUGHOR_CODER_MODEL) —
# same lesson as run_golden: a standalone script never imports api.py, so without
# this the provider silently falls back to its hardcoded default model and the
# run measures the wrong thing.
try:
    from dotenv import load_dotenv
    load_dotenv(_REPO_ROOT / ".env")
except Exception:
    pass

SPIDER2_ROOT = Path(os.environ.get("SPIDER2_ROOT", "/Users/amitkamlapure/dev/Spider2"))
LITE = SPIDER2_ROOT / "spider2-lite"

MAX_SCHEMA_CHARS = 24_000
MAX_EK_CHARS = 5_000
SAMPLE_ROWS = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_instances(subset: str = "local") -> list[dict]:
    recs = [json.loads(l) for l in (LITE / "spider2-lite.jsonl").open() if l.strip()]
    if subset == "local":
        recs = [r for r in recs if r["instance_id"].startswith("local")]
    return recs


def _key_context(conn, tables: list[str]) -> str:
    """PK markers + FK edges from PRAGMA (A2 — the June 56.3% context had 'DDL + FK
    paths from PRAGMA'; the rebuild had dropped them, leaving the model to guess join
    paths). Emitted as `--` comment lines, which `parse_schema_tables` ignores, so the
    guard battery's schema parsing is untouched."""
    lines = ["\nKEYS & JOIN PATHS (from the database's declared constraints):"]
    emitted = 0
    for t in tables:
        try:
            _c, info, _t = conn.raw_execute(f'PRAGMA table_info("{t}")')
            pks = [r[1] for r in info if r[5]]  # (cid, name, type, notnull, dflt, pk)
            if pks:
                lines.append(f"-- {t} PRIMARY KEY: ({', '.join(pks)})")
                emitted += 1
        except Exception:
            pass
        try:
            _c, fks, _t = conn.raw_execute(f'PRAGMA foreign_key_list("{t}")')
            # (id, seq, ref_table, from_col, to_col, on_update, on_delete, match)
            for fk in fks:
                lines.append(f"-- {t}.{fk[3]} -> {fk[2]}.{fk[4] or '(pk)'}")
                emitted += 1
        except Exception:
            pass
    return "\n".join(lines) + "\n" if emitted else ""


def build_schema_context(conn) -> str:
    """The connector's schema text + PK/FK key context + up to SAMPLE_ROWS real rows per
    table (the June design: DDL + FK paths + samples ground the joins and literals),
    capped so a wide DB can't blow the prompt."""
    schema = conn.get_schema() or ""
    try:
        cols, rows, _ = conn.raw_execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = [r[0] for r in rows]
    except Exception:
        tables = []
    parts = [schema, _key_context(conn, tables),
             "\nSAMPLE ROWS (first rows per table, for value formats — not exhaustive):"]
    for t in tables[:60]:
        try:
            cols, rows, _ = conn.raw_execute(f'SELECT * FROM "{t}" LIMIT {SAMPLE_ROWS}')
            head = ", ".join(cols)
            lines = [f"-- {t} ({head})"]
            for r in rows:
                cells = ", ".join(repr(v)[:40] for v in r)
                lines.append(f"--   {cells[:300]}")
            parts.append("\n".join(lines))
        except Exception:
            continue
        if sum(len(p) for p in parts) > MAX_SCHEMA_CHARS:
            parts.append("-- (sample truncated: schema is wide)")
            break
    return "\n".join(parts)[: MAX_SCHEMA_CHARS + 2_000]


def column_semantics_section(conn, max_tables: int = 40, max_distinct: int = 24) -> str:
    """Distinct-value enumeration for low-cardinality TEXT columns + explicit date-column tags.

    The fail-analysis showed a recurring COLUMN-CHOICE failure: the model picks
    `primary_collision_factor` over `pcf_violation_category` for "cause", or the
    administrative `db_year` over the real `collision_date`, because it sees only DDL +
    3 sample rows — not which column actually holds the domain values. This surfaces, per
    low-cardinality text column, its full value set (so "cause categories" is identifiable),
    and tags DATE/TIME columns explicitly. This is Aughor's data-portrait signal, harness-side.
    General (no per-question tuning); bounded so it can't blow the prompt.
    """
    lines = ["\nCOLUMN SEMANTICS (categorical value sets + date columns — pick the column whose "
             "VALUES match the question's entities):"]
    try:
        _c, rows, _t = conn.raw_execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = [r[0] for r in rows]
    except Exception:
        return ""
    emitted = 0
    for t in tables[:max_tables]:
        try:
            cols, _r, _ty = conn.raw_execute(f'SELECT * FROM "{t}" LIMIT 1')
            info_cols, info_rows, _ = conn.raw_execute(f'PRAGMA table_info("{t}")')
            types = {r[1]: (r[2] or "").upper() for r in info_rows}
        except Exception:
            continue
        for c in cols:
            typ = types.get(c, "")
            try:
                if any(k in typ for k in ("DATE", "TIME")) or c.lower().endswith(("_date", "_at")):
                    lines.append(f"-- {t}.{c}: DATE/TIME column (use for time filters/grain)")
                    emitted += 1
                    continue
                if typ and not any(k in typ for k in ("CHAR", "TEXT", "CLOB", "")):
                    continue  # numeric — skip value enumeration
                dc, dr, _ = conn.raw_execute(f'SELECT COUNT(DISTINCT "{c}") FROM "{t}"')
                nd = dr[0][0] if dr else 0
                if nd and 1 < nd <= max_distinct:
                    vc, vr, _ = conn.raw_execute(
                        f'SELECT DISTINCT "{c}" FROM "{t}" WHERE "{c}" IS NOT NULL LIMIT {max_distinct}')
                    vals = ", ".join(repr(r[0])[:30] for r in vr)
                    lines.append(f"-- {t}.{c} ∈ {{{vals[:280]}}}")
                    emitted += 1
            except Exception:
                continue
        if sum(len(x) for x in lines) > 6_000:
            break
    return "\n".join(lines) + "\n" if emitted else ""


def external_knowledge_section(record: dict) -> str:
    name = record.get("external_knowledge")
    if not name:
        return ""
    path = LITE / "resource" / "documents" / name
    try:
        text = path.read_text()[:MAX_EK_CHARS]
    except Exception:
        return ""
    return (
        "\nEXTERNAL KNOWLEDGE (authoritative for this question — apply its exact "
        "definitions/formulas):\n" + text + "\n"
    )


def generate_sql(question: str, schema: str, document_section: str,
                 temperature: float = 0.0) -> str:
    """One SQL-only generation (A3). Keeps CHAT_SQL_SYSTEM (the SQL discipline incl.
    ANSWER_SHAPE — the June-proven +8pt rule) but drops the product's CHAT_PROMPT, whose
    ~6.6k chars are chart-selection rules irrelevant here, and drops the multi-field
    answer model (headline/chart_type/intent/approach) whose output tax competes with
    the SQL. June's 56.3% harness generated SQL-only; this restores that configuration."""
    from pydantic import BaseModel

    from aughor.agent.prompts import CHAT_SQL_SYSTEM
    from aughor.llm.provider import get_provider

    class SqlOnly(BaseModel):
        sql: str = ""

    prompt = (
        f"DATABASE SCHEMA:\n{schema}\n"
        f"{document_section}"
        f"\nQUESTION: {question}\n\n"
        "Write ONE SQL query that answers the question exactly. Return only the SQL."
    )
    answer = get_provider("coder").complete(
        system=CHAT_SQL_SYSTEM, user=prompt,
        response_model=SqlOnly, temperature=temperature,
    )
    return (answer.sql or "").strip()


# Benchmark projection directive (WS5 fail-analysis, 2026-07-06). MEASURED NET-NEGATIVE —
# opt-in only (--bench-projection), NOT the default. The fail-analysis showed 4 of 8
# wrong_shape misses were a gold-wanted intermediate/grouping column the product's
# ANSWER_SHAPE rule TRIMMED, and a misses-only re-run recovered 12/63 — BUT the controlled
# same-instance comparison (62 instances, projection on vs the original off) scored 31 vs 33:
# net -2 (5 recovered, 7 regressed). The misses-only view could only SEE recoveries; on
# previously-correct queries the directive restructures the grain and regresses ~as often,
# and temp-0 cloud noise inflated the apparent win. Kept as an ablation lever + a recorded
# negative result — the June meta-pattern (machinery perturbs correct queries) reproduced.
_BENCH_PROJECTION = (
    "\nOUTPUT COLUMNS (benchmark scoring is by column CONTAINMENT — the expected columns "
    "must each appear among yours; EXTRA columns never hurt, a MISSING one fails the row):\n"
    "- INCLUDE every column your query GROUPS BY (the grouping keys) and every entity id "
    "(customer_id, store_id, product_id, actor_id) that identifies a result row.\n"
    "- INCLUDE the intermediate metrics behind a final computed value (e.g. keep the raw "
    "total AND the ratio; the count AND the average) — do NOT collapse to a single answer column.\n"
    "- If the requested metric is AMBIGUOUS (rounded vs raw, per-unit vs total), emit BOTH as "
    "separate columns rather than guessing one.\n"
    "- Do NOT trim to a minimal 'answer' column set — that loses columns the expected output keeps.\n"
)


def crystallize_resolution(connection_id: str, question: str, outcome, adopted_sql: str) -> bool:
    """Ambiguity Ledger write path (I1): when B1 settles a disagreement with executable
    evidence, crystallize it so the same question class never re-ambiguates on this connection.
    Subject = the question (so future similar questions match); source = probe. Best-effort."""
    try:
        from aughor.semantic.ambiguity_ledger import (
            AmbiguityResolution, Reading, save_resolution)
        for dim in outcome.resolved_dims:
            save_resolution(AmbiguityResolution(
                connection_id=connection_id, dim_kind=dim.kind, dim_facet=dim.facet,
                subject=question, schema_scope=dim.subject,
                readings=[Reading(label=o[:80]) for o in (dim.options or ())][:4],
                resolved_reading=f"{dim.facet}: {outcome.source}",
                resolved_sql=adopted_sql, resolution_source="probe",
                evidence=outcome.reason[:200]))
        return bool(outcome.resolved_dims)
    except Exception:
        return False


def run_probe_repair(conn, question: str, seed_sql: str, alt_sqls: list[str],
                     schema: str, exec_fn, *, connection_id: str = "", ledger: bool = False
                     ) -> tuple[str, dict]:
    """B1 — the probe-and-repair back half of SOMA-lite. Reached ONLY on candidate
    disagreement (the caller gates on n_signatures > 1). Deterministic AST-diff disagreement
    extraction (I2) → deterministic-first probes over the value/grain guards Aughor already
    owns (I3) → evidence-gated minimal repair with the never-go-backwards acceptance gates
    (I7). Returns (sql, trace_info); sql is the seed unchanged unless a repair cleared all gates.
    Design: docs/SOMA_LEVERAGE_AND_AMBIGUITY_LEDGER_2026-07-06.md §2/B1."""
    from aughor.sql.grain_intent import check_result_grain
    from aughor.sql.join_guard import check_filter_value_domains
    from aughor.sql.tables import extract_tables
    from evals.spider2_probes import ProbeResult, extract_disagreements, resolve, run_probes

    others = [s for s in alt_sqls if s and s.strip() != seed_sql.strip()]
    dims = extract_disagreements([seed_sql, *others])
    if not dims:
        return seed_sql, {"fired": False, "reason": "no parseable disagreement"}

    def _grain_diag(sql: str):
        """Execution-grounded grain diagnosis for one candidate (None ⇒ conforms)."""
        try:
            _c, rows, _t = conn.raw_execute(sql.strip().rstrip(";"))
        except Exception:
            return "ERR"
        scope_cols: list = []
        try:
            for ref in extract_tables(sql, "sqlite"):
                _c2, info, _ = conn.raw_execute(f'PRAGMA table_info("{ref.table}")')
                scope_cols.extend(r[1] for r in info)
        except Exception:
            pass

        def _probe_distinct(col: str):
            try:
                for ref in extract_tables(sql, "sqlite"):
                    try:
                        _c3, r, _ = conn.raw_execute(
                            f'SELECT COUNT(DISTINCT "{col}") FROM "{ref.table}"')
                        if r and r[0][0]:
                            return int(r[0][0])
                    except Exception:
                        continue
            except Exception:
                return None
            return None

        return check_result_grain(question, len(rows), columns_in_scope=scope_cols,
                                  count_distinct=_probe_distinct)

    def _grain_probe(dim):
        seed_bad = _grain_diag(seed_sql)
        if seed_bad is None:
            return None  # seed already conforms — nothing to resolve
        for alt in others:
            if _grain_diag(alt) is None:
                return ProbeResult(dim, True, "grain probe: the seed's row count contradicts the "
                                   "asked grain; an alternative reading matches it",
                                   preferred_sql=alt, source="det:grain")
        diag = seed_bad if isinstance(seed_bad, str) and seed_bad != "ERR" else \
            "the result grain contradicts the question's declared grain"
        return ProbeResult(dim, True, diag, hint=diag, source="det:grain")

    def _value_probe(dim):
        try:
            w = check_filter_value_domains(conn, seed_sql)
        except Exception:
            w = []
        if not w:
            return None  # seed's filter literals all bind — nothing to resolve
        for alt in others:
            try:
                if not check_filter_value_domains(conn, alt):
                    return ProbeResult(dim, True, f"value probe: the seed filters on "
                                       f"{w[0].bad_value!r} (matches no rows); an alternative "
                                       f"reading uses a value present in the data",
                                       preferred_sql=alt, source="det:value")
            except Exception:
                continue
        hint = "; ".join(x.to_prompt_text() for x in w[:2])
        return ProbeResult(dim, True, hint, hint=hint, source="det:value")

    probe_results = run_probes(dims, det_probes={"grain": _grain_probe, "value": _value_probe})

    def _repair(seed: str, instruction: str):
        try:
            from aughor.sql.writer import SqlWriter
            fixed = SqlWriter(conn, schema_str=schema).fix(seed, instruction, max_retries=1)
            return fixed.sql if fixed.ok and fixed.sql else None
        except Exception:
            return None

    reprobe = {
        "grain": lambda sql, dim: _grain_diag(sql) is None,
        "value": lambda sql, dim: not _safe_filter_ok(conn, sql, check_filter_value_domains),
    }
    outcome = resolve(question, seed_sql, dims, probe_results, execute_fn=exec_fn,
                      repair_fn=_repair, alternatives=others, reprobe=reprobe)
    crystallized = False
    if outcome.accepted and ledger and connection_id:
        crystallized = crystallize_resolution(connection_id, question, outcome, outcome.sql)
    return (outcome.sql if outcome.accepted else seed_sql), {
        "fired": outcome.accepted,
        "dims": [f"{d.kind}/{d.facet}:{d.subject}" for d in dims],
        "resolved": [f"{d.facet}:{d.subject}" for d in outcome.resolved_dims],
        "source": outcome.source, "reason": outcome.reason[:120], "gates": outcome.gates,
        "crystallized": crystallized,
    }


def _safe_filter_ok(conn, sql, check_filter_value_domains) -> bool:
    """True if the guard found an unbound literal (i.e. NOT clear). Wrapped so a guard
    exception fails the reprobe closed (unverifiable ⇒ don't adopt)."""
    try:
        return bool(check_filter_value_domains(conn, sql))
    except Exception:
        return True


def run_instance(record: dict, outdir: Path, temperature: float, use_ek: bool = True,
                 bench_projection: bool = False, col_semantics: bool = False,
                 candidates: int = 1, probes: bool = False, ledger: bool = False) -> dict:
    from aughor.connectors.file.sqlite import SQLiteConnection
    from aughor.sql.closed_loop import execute_with_repair, rows_to_csv
    from aughor.sql.safety import preflight_repair

    iid = record["instance_id"]
    trace: dict = {"instance_id": iid, "db": record["db"], "question": record["question"],
                   "started": _now(), "steps": []}

    def step(kind: str, **kw):
        trace["steps"].append({"t": _now(), "kind": kind, **kw})

    db_path = LITE / "resource" / "databases" / f"{record['db']}.sqlite"
    if not db_path.exists():
        step("error", detail=f"database file missing: {db_path}")
        return {"id": iid, "ok": False, "error": "db-missing", "trace": trace}

    conn = SQLiteConnection(dsn=str(db_path))
    try:
        t0 = time.time()
        schema = build_schema_context(conn)
        if col_semantics:
            sem = column_semantics_section(conn)
            if sem:
                schema = schema + "\n" + sem
                step("col_semantics", chars=len(sem))
        step("schema", chars=len(schema))
        ek = external_knowledge_section(record) if use_ek else ""
        if ek:
            step("external_knowledge", doc=record.get("external_knowledge"), chars=len(ek))
        engine_note = ("\nENGINE: SQLite. Emit ONE SQLite-compatible SELECT (no DuckDB/Postgres "
                       "extensions).\n")
        if bench_projection:
            engine_note += _BENCH_PROJECTION

        # Ambiguity Ledger read path (I1): a disagreement settled earlier on THIS db (connection
        # = db name) injects its resolution as an authoritative prior, so the class never
        # re-ambiguates. On the benchmark this compounds across runs/similar questions; the value
        # is amortization, not a single-run EX lever. Gated by --ledger.
        conn_id = record["db"]
        if ledger:
            from aughor.semantic.ambiguity_ledger import (
                build_resolution_block, record_hit, retrieve_resolutions)
            _matches = retrieve_resolutions(record["question"], conn_id)
            _led_block = build_resolution_block(_matches)
            if _led_block:
                for _res, _sc in _matches:
                    record_hit(_res.id)
                engine_note += "\n" + _led_block
                step("ledger_read", served=len(_matches),
                     subjects=[r.resolved_reading for r, _ in _matches])

        if candidates > 1:
            # Levers 4+5 — strategy-diverse candidates + execution-signature selection
            # (deterministic; no judge LLM). K calls per question — hard-subset use.
            from aughor.sql.grain_intent import check_result_grain
            from evals.spider2_candidates import STRATEGIES, run_candidates

            def _exec_lite(s: str):
                try:
                    _c, rows, _t = conn.raw_execute(s.strip().rstrip(";"))
                    return True, rows, ""
                except Exception as e:
                    return False, None, str(e)

            cr = run_candidates(
                record["question"], schema, ek + engine_note,
                generate_fn=lambda q, s, d: generate_sql(q, s, d, temperature),
                execute_fn=_exec_lite,
                columns_fn=lambda s: [],
                grain_check=lambda q, n: check_result_grain(q, n),
                strategies=list(STRATEGIES)[:candidates],
            )
            step("candidates", n=len(cr.candidates), signatures=cr.n_signatures,
                 agreed=cr.agreed, chosen=(cr.chosen.strategy if cr.chosen else None),
                 detail=[{"strategy": c.strategy, "ok": c.ok, "sig": c.signature,
                          "grain_ok": c.grain_ok, "err": c.error[:80]} for c in cr.candidates])
            sql = cr.chosen.sql if cr.chosen else ""
            # B1 — probe-and-repair (the SOMA back half): only on disagreement (free signal).
            if probes and cr.chosen and cr.n_signatures > 1:
                alt_sqls = [c.sql for c in cr.candidates if c.ok and c.sql]
                repaired, pinfo = run_probe_repair(
                    conn, record["question"], sql, alt_sqls, schema, _exec_lite,
                    connection_id=conn_id, ledger=ledger)
                step("probe_repair", **pinfo)
                if pinfo.get("fired"):
                    sql = repaired
        else:
            sql = generate_sql(record["question"], schema, ek + engine_note, temperature)
        step("generated", sql=sql)
        if not sql:
            return {"id": iid, "ok": False, "error": "empty-generation", "trace": trace}

        guarded, receipt = preflight_repair(conn, sql, schema)
        step("preflight", receipt=receipt, changed=guarded.strip() != sql.strip())

        def execute_fn(s: str):
            try:
                _cols, rows, _t = conn.raw_execute(s.strip().rstrip(";"))
                return True, rows, ""
            except Exception as e:
                return False, None, str(e)

        def repair_fn(bad_sql: str, err: str):
            try:
                from aughor.sql.writer import SqlWriter
                fixed = SqlWriter(conn, schema_str=schema).fix(bad_sql, err, max_retries=1)
                return fixed.sql if fixed.ok and fixed.sql else None
            except Exception:
                return None

        def recover_empty_fn(empty_sql: str):
            # A1: the June-built empty-result recovery, previously never wired here —
            # 6 of the 63 misses were 0-row results where gold has rows. Feed the
            # zero-row diagnosis + live filter-domain warnings to the typed fixer; the
            # closed loop adopts a rewrite ONLY if it executes AND returns rows.
            try:
                from aughor.sql.executor import zero_row_suspicious
                from aughor.sql.join_guard import check_filter_value_domains
                diag = zero_row_suspicious(empty_sql) or ""
                try:
                    fw = check_filter_value_domains(conn, empty_sql)
                    if fw:
                        diag = (diag + "\n" + "\n".join(w.to_prompt_text() for w in fw)).strip()
                except Exception:
                    pass
                err = ("The query executed but returned 0 rows. "
                       + (diag or "Re-examine the filter literals against the real stored "
                                  "values, the join path, and the date/year column choice."))
                from aughor.sql.writer import SqlWriter
                fixed = SqlWriter(conn, schema_str=schema).fix(empty_sql, err, max_retries=1)
                return fixed.sql if fixed.ok and fixed.sql else None
            except Exception:
                return None

        loop = execute_with_repair(guarded, execute_fn, repair_fn,
                                   recover_empty_fn=recover_empty_fn, max_rounds=2)
        step("closed_loop", ok=loop.ok, rounds=loop.rounds, rows=loop.row_count,
             receipt=loop.receipt)

        # Lever 7 — deterministic grain-of-intent check: a result that runs clean but
        # contradicts the question's declared grain ("top three…" → 7 rows, "for each
        # match" → per-ball rows) gets ONE diagnosis-fed repair round; adopt only if the
        # retry executes AND lands closer to the expected grain (never go backwards).
        if loop.ok:
            try:
                from aughor.sql.grain_intent import check_result_grain

                def _probe_distinct(col: str):
                    try:
                        from aughor.sql.tables import extract_tables
                        for ref in extract_tables(loop.sql, "sqlite"):
                            try:
                                _c, r, _t = conn.raw_execute(
                                    f'SELECT COUNT(DISTINCT "{col}") FROM "{ref.table}"')
                                if r and r[0][0]:
                                    return int(r[0][0])
                            except Exception:
                                continue
                    except Exception:
                        return None
                    return None

                try:
                    _cols_now, _rows_now, _ = conn.raw_execute(loop.sql)
                except Exception:
                    _cols_now, _rows_now = [], []
                _scope_cols: list = []
                try:
                    from aughor.sql.tables import extract_tables
                    for ref in extract_tables(loop.sql, "sqlite"):
                        _c2, info, _ = conn.raw_execute(f'PRAGMA table_info("{ref.table}")')
                        _scope_cols.extend(r[1] for r in info)
                except Exception:
                    pass
                diag = check_result_grain(record["question"], len(_rows_now),
                                          columns_in_scope=_scope_cols,
                                          count_distinct=_probe_distinct)
                if diag:
                    step("grain_intent", diagnosis=diag, rows=len(_rows_now))
                    cand = repair_fn(loop.sql, diag)
                    if cand and cand.strip() != loop.sql.strip():
                        ok2, rows2, _e2 = execute_fn(cand)
                        if ok2 and check_result_grain(
                                record["question"],
                                len(rows2) if isinstance(rows2, list) else -1,
                                columns_in_scope=_scope_cols,
                                count_distinct=_probe_distinct) is None:
                            from aughor.sql.closed_loop import LoopResult
                            loop = LoopResult(sql=cand.strip(), ok=True,
                                              row_count=len(rows2) if isinstance(rows2, list) else -1,
                                              rounds=loop.rounds + 1,
                                              receipt={**loop.receipt, "grain_repaired": True})
                            step("grain_repaired", rows=loop.row_count)
            except Exception as _exc:
                from aughor.kernel.errors import tolerate
                tolerate(_exc, "grain-of-intent check is best-effort; result ships as-is",
                         counter="spider2.grain_intent")

        final_sql = loop.sql.strip().rstrip(";")
        (outdir / "sql").mkdir(parents=True, exist_ok=True)
        (outdir / "exec_result").mkdir(parents=True, exist_ok=True)
        (outdir / "traces").mkdir(parents=True, exist_ok=True)
        (outdir / "sql" / f"{iid}.sql").write_text(final_sql + "\n")

        if loop.ok:
            cols, rows, _t = conn.raw_execute(final_sql)
            rows_to_csv(cols, rows, outdir / "exec_result" / f"{iid}.csv")
            step("csv", rows=len(rows), cols=len(cols))

        trace["finished"] = _now()
        trace["elapsed_s"] = round(time.time() - t0, 1)
        trace["final_sql"] = final_sql
        (outdir / "traces" / f"{iid}.json").write_text(json.dumps(trace, indent=1))
        return {"id": iid, "ok": loop.ok, "rounds": loop.rounds,
                "rows": loop.row_count, "elapsed_s": trace["elapsed_s"]}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def score(outdir: Path) -> int:
    """Run the OFFICIAL evaluator over the generated SQL (mode sql re-executes them)."""
    suite = LITE / "evaluation_suite"
    cmd = [sys.executable, "evaluate.py", "--mode", "sql",
           "--result_dir", str((outdir / "sql").resolve()),
           "--gold_dir", "gold"]
    print(f"[score] {' '.join(cmd)}  (cwd={suite})")
    return subprocess.call(cmd, cwd=suite)


def main() -> int:
    os.environ.setdefault("AUGHOR_FALLBACK_DISABLED", "1")  # pin the model (eval integrity)
    ap = argparse.ArgumentParser()
    ap.add_argument("--subset", default="local", choices=["local"])
    ap.add_argument("--ids", default=None, help="comma-separated instance ids")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--outdir", default="evals/spider2_out")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--no-ek", action="store_true", help="ablation: skip external-knowledge docs")
    ap.add_argument("--bench-projection", action="store_true",
                    help="ablation (measured NET-NEGATIVE, off by default): containment-aware "
                         "projection directive — keep intermediates/grouping keys, superset columns")
    ap.add_argument("--col-semantics", action="store_true",
                    help="enrich schema with categorical value sets + date-column tags (column-choice lever)")
    ap.add_argument("--candidates", type=int, default=1,
                    help="strategy-diverse candidates per question (K generations + execution-"
                         "signature selection; default 1 = single-shot)")
    ap.add_argument("--probes", action="store_true",
                    help="B1 probe-and-repair back half: on candidate disagreement, run "
                         "deterministic-first probes + evidence-gated minimal repair (needs "
                         "--candidates > 1; no-op on agreement)")
    ap.add_argument("--ledger", action="store_true",
                    help="Ambiguity Ledger (I1): inject resolutions settled earlier on this db "
                         "as an authoritative prior (read), and crystallize B1-settled "
                         "disagreements (write). Value compounds across runs — per-connection burn-down")
    ap.add_argument("--score", action="store_true", help="run the official evaluator over outdir")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    if args.score and not args.ids and not args.limit:
        return score(outdir)

    records = load_instances(args.subset)
    if args.ids:
        want = {x.strip() for x in args.ids.split(",")}
        records = [r for r in records if r["instance_id"] in want]
    if args.limit:
        records = records[: args.limit]

    from aughor.llm.provider import get_provider
    p = get_provider("coder")
    print(f"[spider2] {len(records)} instances | model={p._model} backend={p.backend} "
          f"temp={args.temperature} ek={'off' if args.no_ek else 'on'} "
          f"proj={'on' if args.bench_projection else 'off'} "
          f"colsem={'on' if args.col_semantics else 'off'} cand={max(1, args.candidates)} "
          f"probes={'on' if args.probes else 'off'} ledger={'on' if args.ledger else 'off'} out={outdir}")

    results = []
    for i, rec in enumerate(records, 1):
        print(f"  [{i}/{len(records)}] {rec['instance_id']} ...", flush=True)
        try:
            r = run_instance(rec, outdir, args.temperature, use_ek=not args.no_ek,
                             bench_projection=args.bench_projection, col_semantics=args.col_semantics,
                             candidates=max(1, args.candidates), probes=args.probes, ledger=args.ledger)
        except Exception as e:
            r = {"id": rec["instance_id"], "ok": False, "error": str(e)[:200]}
        print(f"      -> ok={r.get('ok')} rounds={r.get('rounds')} rows={r.get('rows')} "
              f"{r.get('error', '')}", flush=True)
        results.append(r)

    ok = sum(1 for r in results if r.get("ok"))
    print(f"\n[spider2] exec-success {ok}/{len(results)}")
    (outdir / "run_summary.json").write_text(json.dumps(
        {"when": _now(), "n": len(results), "exec_ok": ok, "results": results}, indent=1))
    if args.score:
        return score(outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
