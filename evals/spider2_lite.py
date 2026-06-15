#!/usr/bin/env python3
"""Spider 2.0-Lite benchmark harness for Aughor NL2SQL.

Follows the official Spider 2.0-Lite submission guidelines:
  - Generates one {instance_id}.sql per local (SQLite) instance
  - Writes a timestamped reasoning trace {instance_id}_trace.json per instance
  - Invokes Spider's evaluate.py (mode=sql) for engine-faithful EX scoring,
    which also emits {instance_id}.csv execution results into {out}_csv/
  - Packages sql/ + csv/ + traces/ into a submission zip

Prerequisites:
  - Spider2 repo cloned: https://github.com/xlang-ai/Spider2
  - SQLite databases unzipped into spider2-lite/resource/databases/ as flat .sqlite files
  - Aughor .env configured with AUGHOR_CODER_MODEL

Generate predictions:
  python evals/spider2_lite.py \\
      --spider-root /path/to/Spider2/spider2-lite \\
      --out evals/spider2_out/submission

Score (runs Spider's evaluate.py after generation):
  python evals/spider2_lite.py --spider-root ... --out ... --score

Score only (skip generation, score existing .sql files):
  python evals/spider2_lite.py --spider-root ... --out ... --score-only

Package for submission:
  python evals/spider2_lite.py --spider-root ... --out ... --package
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(_REPO_ROOT / ".env")
except ImportError:
    pass

csv.field_size_limit(10 ** 7)

METHOD_NAME = "Aughor NL2SQL (single-shot, full-DDL, SQLite-targeted)"


# ── instance loading ──────────────────────────────────────────────────────────

def load_local_instances(spider_root: Path) -> list[dict]:
    """Return all 135 local (SQLite-backed) Spider 2.0-Lite instances."""
    jsonl = spider_root / "spider2-lite.jsonl"
    rows = [json.loads(l) for l in jsonl.read_text().splitlines() if l.strip()]
    return [r for r in rows if r["instance_id"].startswith("local")]


# ── schema ────────────────────────────────────────────────────────────────────

def _norm(name: str) -> str:
    return name.lower().replace("-", "_").replace(" ", "_")


def _table_of_ddl(ddl: str) -> str:
    """Extract the table name from a CREATE TABLE statement."""
    m = re.search(r'CREATE\s+TABLE\s+["\[\']?(\w+)', ddl, re.IGNORECASE)
    return m.group(1) if m else ""


def list_tables(spider_root: Path, db_name: str) -> list[str]:
    """Return the table names for a database (from the live SQLite file)."""
    db_path = spider_root / "resource" / "databases" / f"{db_name}.sqlite"
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()]
        conn.close()
        return tables
    except Exception:
        return []


def build_schema(spider_root: Path, db_name: str,
                 only_tables: set[str] | None = None) -> str:
    """Return schema context: DDL + FK join paths + 3 sample rows per table.

    When ``only_tables`` is given, the schema is trimmed to those tables plus any
    table reachable from them by a foreign key (so joins still resolve). This is
    how schema-linking shrinks huge-database prompts without breaking joins.
    """
    sqlite_meta = spider_root / "resource" / "databases" / "sqlite"
    ddl_path = sqlite_meta / db_name / "DDL.csv"
    if not ddl_path.exists():
        want = _norm(db_name)
        match = next((d for d in sqlite_meta.iterdir()
                      if d.is_dir() and _norm(d.name) == want), None)
        if match is None:
            return ""
        ddl_path = match / "DDL.csv"
    if not ddl_path.exists():
        return ""

    ddl_by_table: dict[str, str] = {}
    for row in csv.DictReader(ddl_path.open()):
        ddl = (row.get("DDL") or "").strip()
        if ddl:
            ddl_by_table[_table_of_ddl(ddl) or f"_{len(ddl_by_table)}"] = ddl

    db_path = spider_root / "resource" / "databases" / f"{db_name}.sqlite"
    if not db_path.exists():
        return "\n\n".join(ddl_by_table.values())

    try:
        conn = sqlite3.connect(str(db_path))
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()]

        # FK edges from PRAGMA: (table, from_col, ref_table, to_col)
        fk_edges: list[tuple[str, str, str, str]] = []
        for tbl in tables:
            try:
                for fk in conn.execute(f"PRAGMA foreign_key_list({tbl})").fetchall():
                    fk_edges.append((tbl, fk[3], fk[2], fk[4]))
            except Exception:
                pass

        # Schema-link trim: keep selected tables + their FK neighbours
        keep: set[str] | None = None
        if only_tables:
            ci = {t.lower(): t for t in tables}
            keep = {ci[t.lower()] for t in only_tables if t.lower() in ci}
            for (a, _c1, b, _c2) in fk_edges:
                if a in keep or b in keep:
                    keep.add(a); keep.add(b)
            if not keep:           # linking produced nothing usable → keep all
                keep = None

        sel_tables = [t for t in tables if (keep is None or t in keep)]

        fk_lines = [f"  {a}.{c1} → {b}.{c2}" for (a, c1, b, c2) in fk_edges
                    if keep is None or (a in keep or b in keep)]

        sample_parts = []
        for tbl in sel_tables:
            try:
                cols = [r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()]
                rows = conn.execute(f"SELECT * FROM {tbl} LIMIT 3").fetchall()
                if rows:
                    header = " | ".join(cols)
                    sample_rows = [" | ".join(str(v)[:40] for v in r) for r in rows]
                    sample_parts.append(f"-- {tbl} sample rows:\n-- " +
                                        "\n-- ".join([header] + sample_rows))
            except Exception:
                pass

        conn.close()
    except Exception:
        return "\n\n".join(ddl_by_table.values())

    # Assemble DDL for selected tables (match by name, case-insensitive)
    if keep is not None:
        keep_lc = {t.lower() for t in keep}
        ddl_parts = [d for name, d in ddl_by_table.items() if name.lower() in keep_lc]
        if not ddl_parts:
            ddl_parts = list(ddl_by_table.values())
    else:
        ddl_parts = list(ddl_by_table.values())

    result = "\n\n".join(ddl_parts)
    if fk_lines:
        result += (
            "\n\nFOREIGN KEY RELATIONSHIPS (from database schema — use these exact columns for JOINs):\n"
            + "\n".join(fk_lines)
            + "\nNote: These are directional FK declarations. Only join in the direction the question requires — "
            "do not automatically expand to include both sides of a relationship unless the question explicitly asks for both."
        )
    if sample_parts:
        result += (
            "\n\nSAMPLE DATA (3 rows per table — reveals actual value formats and encodings):\n"
            "Use sample data to understand how values are stored (e.g. comma-separated IDs, date formats, encodings). "
            "Do NOT copy column formatting or concatenation patterns from sample rows into your SELECT output — "
            "return columns separately as the question requires.\n\n"
            + "\n\n".join(sample_parts)
        )
    return result


# ── external knowledge ────────────────────────────────────────────────────────

def load_external_knowledge(spider_root: Path, ek: str | None) -> str:
    if not ek:
        return ""
    doc = spider_root / "resource" / "documents" / ek
    if not doc.exists():
        return ""
    text = doc.read_text(errors="replace").strip()
    return f"EXTERNAL KNOWLEDGE (apply these definitions/formulas exactly):\n{text}\n\n"


# ── NL2SQL generation ─────────────────────────────────────────────────────────

_SQLITE_HINT = (
    "DIALECT: Write SQL for the SQLite engine. Use only SQLite-supported syntax "
    "and functions (e.g. strftime() for dates, || for string concat, "
    "CAST(x AS REAL) for division). Do NOT use DuckDB/BigQuery/Snowflake-only "
    "functions. Return a single SELECT statement.\n\n"
)


def link_tables(question: str, table_names: list[str], doc_section: str) -> list[str]:
    """Schema linking: pick the tables relevant to the question (one cheap call).

    Returns a subset of table_names. On any failure or empty result, returns
    the full list (caller falls back to the complete schema). This shrinks the
    prompt for wide databases — both faster and more accurate, since the model
    isn't distracted by dozens of irrelevant tables.
    """
    from aughor.llm.provider import get_provider
    from pydantic import BaseModel, Field

    prompt = (
        f"{doc_section}"
        f"QUESTION: {question}\n\n"
        f"AVAILABLE TABLES:\n{', '.join(table_names)}\n\n"
        "Select ONLY the tables needed to answer the question. Include tables required "
        "for JOINs (e.g. a bridge/lookup table connecting two others). Be inclusive when "
        "unsure — a missing table makes the query impossible, an extra one is harmless. "
        "Return the table names exactly as listed above."
    )

    class Linked(BaseModel):
        tables: list[str] = Field(default_factory=list)

    try:
        ans: Linked = _coder().complete(
            system="You are a database expert selecting relevant tables for a SQL query.",
            user=prompt, response_model=Linked, temperature=0.0,
        )
        valid = {t.lower() for t in table_names}
        picked = [t for t in ans.tables if t.lower() in valid]
        return picked or table_names
    except Exception:
        return table_names


# B1/B2 — diverse generation strategies (CHASE-SQL style). Each consensus
# candidate uses a DIFFERENT strategy, not just a different temperature, so the
# candidate pool genuinely explores the solution space (and the decompose
# strategy can crack multi-step questions the direct one collapses).
_STRATEGY_HINTS = {
    "direct": "",
    "decompose": (
        "SOLVE BY DECOMPOSITION (divide-and-conquer): In your reasoning, first break the "
        "question into an ordered list of sub-steps (e.g. 1. compute per-entity totals, "
        "2. rank them, 3. take top-N, 4. aggregate over those). Then write ONE SQL query "
        "that implements each sub-step as a chained CTE (step_1, step_2, ...), where each "
        "CTE fully materialises before the next references it. Do NOT collapse sequential "
        "steps into a single SELECT — this is essential for multi-step analytical questions.\n\n"
    ),
    "plan": (
        "SOLVE BY PLANNING (reason first): Before writing SQL, explicitly determine "
        "(a) the UNIT OF ANALYSIS / grain, (b) EVERY filter the question requires "
        "(time, entity, status, threshold), and (c) the exact sequence of operations and "
        "the expected result cardinality ('which X' => 1 row; 'top N' => N rows). Then write "
        "SQL that implements that plan precisely.\n\n"
    ),
}

_STRATEGIES = ["direct", "decompose", "plan"]

# Optional coder-model override (e.g. gpt-oss:120b-cloud) for A/B experiments.
# The runtime config (data/llm_config.json) takes precedence over env, so we
# must construct an explicit provider to override it.
_CODER_MODEL: str | None = None
_CODER_PROVIDER = None


def _coder():
    global _CODER_PROVIDER
    if _CODER_MODEL is None:
        from aughor.llm.provider import get_provider
        return get_provider("coder")
    if _CODER_PROVIDER is None:
        from aughor.llm.provider import LLMProvider
        _CODER_PROVIDER = LLMProvider(
            backend=os.getenv("AUGHOR_BACKEND", "ollama"), role="coder", model=_CODER_MODEL)
    return _CODER_PROVIDER


# ── Full Aughor engine path ───────────────────────────────────────────────────
# Route generation through the REAL production pipeline (generate_sql_full_pipeline
# in run_golden.py): schema-linker → data catalog → FK-neighbour expansion →
# semantic ontology layer → metrics catalog → trusted templates → coder LLM →
# semantic-alignment + fan-out + lint guards → execute-retry — against a real
# SQLiteConnection with profiles + ontology built. "Aughor is the engine."
import threading as _threading
_ENGINE_LOCK = _threading.Lock()
_ENGINE_BASE: dict = {}   # db_name -> base SQLiteConnection (intelligence built once)


def _engine_conn(spider_root: Path, db_name: str):
    """Return a thread-safe reader connection for db_name, building heavy
    intelligence (value profiles + ontology) once per DB and caching it."""
    with _ENGINE_LOCK:
        if db_name not in _ENGINE_BASE:
            from aughor.connectors.file.sqlite import SQLiteConnection
            path = spider_root / "resource" / "databases" / f"{db_name}.sqlite"
            base = SQLiteConnection(dsn=str(path), connection_id=f"spider_{db_name}")
            t0 = time.monotonic()
            try:
                base.build_intelligence()
                print(f"  [intel] {db_name}: built in {time.monotonic()-t0:.0f}s")
            except Exception as e:
                print(f"  [intel] {db_name}: build_intelligence failed ({str(e)[:60]}) — fast schema")
            _ENGINE_BASE[db_name] = base
        base = _ENGINE_BASE[db_name]
    return base.make_reader()


def generate_sql_engine(question: str, db_name: str, reader, temperature: float,
                        doc_section: str, strategy: str = "direct") -> str:
    """Generate via the full Aughor engine. External knowledge + strategy hint are
    prepended to the question (the pipeline builds all other context itself)."""
    from run_golden import generate_sql_full_pipeline
    q = question
    hint = _STRATEGY_HINTS.get(strategy, "")
    if hint:
        q = hint + q
    if doc_section:
        q = doc_section + "\n\n" + q
    return (generate_sql_full_pipeline(q, f"spider_{db_name}", reader, temperature) or "").strip()


def generate_sql(question: str, schema: str, doc_section: str,
                 temperature: float = 0.0, strategy: str = "direct") -> str:
    from aughor.agent.prompts import CHAT_SQL_SYSTEM, CHAT_PROMPT
    from pydantic import BaseModel, Field

    prompt = CHAT_PROMPT.format(
        schema=schema,
        history_section="",
        question=question,
        metrics_section="",
        conn_kb_section="",
        exploration_section="",
        causal_section="",
        document_section=_STRATEGY_HINTS.get(strategy, "") + _SQLITE_HINT + doc_section,
        sql_examples_section="",
        kb_patterns_section="",
    )

    from typing import Any

    class Answer(BaseModel):
        sql: str = ""
        headline: str = ""
        chart_type: str = "auto"
        intent: str = ""
        approach: Any = Field(default_factory=list)

        model_config = {"arbitrary_types_allowed": True}

    ans: Answer = _coder().complete(
        system=CHAT_SQL_SYSTEM,
        user=prompt,
        response_model=Answer,
        temperature=temperature,
    )
    return (ans.sql or "").strip()


# ── SQLite execute-and-retry ──────────────────────────────────────────────────

def _sqlite_try(db_path: Path, sql: str) -> tuple[bool, str]:
    """Try executing sql against the SQLite DB. Returns (ok, error_message)."""
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute(sql).fetchmany(5)
        conn.close()
        return True, ""
    except Exception as e:
        return False, str(e)


def _sqlite_exec(db_path: Path, sql: str):
    """Execute sql and return an ExecResult (ok, rows, error) for consensus voting."""
    from aughor.agent.sql_consensus import ExecResult
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.execute(sql)
        rows = cur.fetchall()
        conn.close()
        return ExecResult(ok=True, rows=rows)
    except Exception as e:
        return ExecResult(ok=False, error=str(e))


_REASONER = None


def _reasoner():
    """Lazily build a strong-reasoning provider (kimi) for the reflection pass."""
    global _REASONER
    if _REASONER is None:
        from aughor.llm.provider import LLMProvider
        model = os.getenv("AUGHOR_REASONER_MODEL", "kimi-k2.6:cloud")
        _REASONER = LLMProvider(backend="ollama", role="narrator", model=model)
    return _REASONER


def _preview(db_path: Path, sql: str, n: int = 8) -> tuple[int, str]:
    """Return (row_count, preview_text) for a query — for the selection judge."""
    res = _sqlite_exec(db_path, sql)
    if not res.ok:
        return -1, f"(error: {res.error[:80]})"
    rows = res.rows or []
    body = "\n".join(" | ".join(str(v)[:40] for v in r) for r in rows[:n]) or "(no rows)"
    return len(rows), body


def _judge_pair(question: str, doc_section: str, db_path: Path,
                a_sql: str, b_sql: str) -> str:
    """Pairwise judge (CHASE-SQL style): which query better answers the question?
    Returns 'A', 'B', or '' (no decision). Uses the strong reasoning model."""
    from pydantic import BaseModel
    from typing import Literal

    a_n, a_prev = _preview(db_path, a_sql)
    b_n, b_prev = _preview(db_path, b_sql)

    class Verdict(BaseModel):
        better: Literal["A", "B"]
        reason: str = ""

    prompt = (
        f"{doc_section}QUESTION: {question}\n\n"
        f"--- CANDIDATE A ({a_n} rows) ---\nSQL:\n{a_sql}\nRESULT:\n{a_prev}\n\n"
        f"--- CANDIDATE B ({b_n} rows) ---\nSQL:\n{b_sql}\nRESULT:\n{b_prev}\n\n"
        "Which candidate's RESULT more correctly and completely answers the question? "
        "Judge by: correct cardinality (does the row count fit 'which/top-N/per-group'?), "
        "correct aggregation grain, the right columns, and all question constraints applied. "
        "Return 'A' or 'B'."
    )
    try:
        v: Verdict = _reasoner().complete(
            system="You are a meticulous SQL judge choosing the query whose result best answers the question.",
            user=prompt, response_model=Verdict, temperature=0.0,
        )
        return v.better
    except Exception:
        return ""


def _make_selector(question: str, doc_section: str, db_path: Path):
    """Build a selector_fn for consensus: a round-robin pairwise tournament
    judged by the reasoning model. Returns the candidate with the most wins."""
    def selector(reps):
        if len(reps) < 2:
            return reps[0] if reps else None
        wins = {id(c): 0 for c in reps}
        for i in range(len(reps)):
            for j in range(i + 1, len(reps)):
                a, b = reps[i], reps[j]
                verdict = _judge_pair(question, doc_section, db_path, a.sql, b.sql)
                if verdict == "A":
                    wins[id(a)] += 1
                elif verdict == "B":
                    wins[id(b)] += 1
        # winner = most wins; tie-break toward fewer repairs then shorter SQL
        return max(reps, key=lambda c: (wins[id(c)], -c.repairs, -len(c.sql)))
    return selector


def _reflect_revise(question: str, schema: str, doc_section: str,
                    sql: str, db_path: Path) -> tuple[str, dict]:
    """Reflection pass: a reasoning model judges whether the result answers the
    question; if not, it proposes a fix. The revision is adopted ONLY if it
    executes cleanly and returns rows — so reflection can correct but never break.

    Returns (possibly-revised sql, trace_step).
    """
    from pydantic import BaseModel
    from typing import Optional

    # Build a compact preview of the actual result the query produces
    res = _sqlite_exec(db_path, sql)
    if not res.ok:
        return sql, {"action": "reflection", "detail": "skipped (winner did not execute)"}
    rows = res.rows or []
    preview = rows[:8]
    preview_str = "\n".join(" | ".join(str(v)[:40] for v in r) for r in preview) or "(no rows)"

    class Reflection(BaseModel):
        answers_question: bool
        problem: str = ""
        corrected_sql: Optional[str] = None

    judge_prompt = (
        f"{doc_section}"
        f"QUESTION: {question}\n\n"
        f"CANDIDATE SQL:\n{sql}\n\n"
        f"ACTUAL RESULT ({len(rows)} rows, showing first {len(preview)}):\n{preview_str}\n\n"
        "Judge whether this result actually answers the question. Check carefully:\n"
        "- CARDINALITY: 'which/the [single entity]' expects 1 row; 'top N' expects N rows; "
        "a per-group question expects one row per group. Does the row count fit?\n"
        "- COLUMNS: does the result expose the value(s) the question asks for?\n"
        "- AGGREGATION GRAIN: is the metric computed at the right level (per entity vs per row)?\n"
        "- FILTERS: are all constraints in the question reflected in the result?\n\n"
        "If it correctly answers, set answers_question=true. "
        "If NOT, set answers_question=false, describe the problem briefly, and provide corrected_sql "
        "(a complete SQLite SELECT). Only provide corrected_sql when you are confident it is better."
    )

    try:
        r: Reflection = _reasoner().complete(
            system="You are a meticulous SQL reviewer. You judge whether a query's result truly answers "
                   "the user's question, focusing on cardinality, grain, columns, and filters.",
            user=judge_prompt, response_model=Reflection, temperature=0.0,
        )
    except Exception as e:
        return sql, {"action": "reflection", "detail": f"skipped (reasoner error: {str(e)[:80]})"}

    if r.answers_question or not r.corrected_sql:
        return sql, {"action": "reflection", "detail": "winner judged correct",
                     "verdict": r.answers_question}

    revised = r.corrected_sql.strip()
    rev_res = _sqlite_exec(db_path, revised)
    if rev_res.ok and rev_res.rows:
        return revised, {"action": "reflection", "detail": f"revised: {r.problem[:140]}",
                         "verdict": False, "applied": True, "output": revised}
    return sql, {"action": "reflection",
                 "detail": f"flagged but revision rejected (ran={rev_res.ok}, rows={len(rev_res.rows or [])}): {r.problem[:100]}",
                 "verdict": False, "applied": False}


def _recover_empty(question: str, schema: str, doc_section: str,
                   sql: str, _msg: str, temperature: float) -> str:
    """Recover from a 0-row result — usually a wrong literal or over-tight filter."""
    from aughor.llm.provider import get_provider
    from aughor.agent.prompts import CHAT_SQL_SYSTEM
    from pydantic import BaseModel
    from typing import Any

    prompt = (
        f"DATABASE SCHEMA:\n{schema}\n\n"
        f"{_SQLITE_HINT}{doc_section}"
        f"QUESTION: {question}\n\n"
        f"PREVIOUS SQL returned ZERO rows:\n{sql}\n\n"
        "A 0-row result for an analytical question almost always means a filter is wrong. "
        "Check each WHERE/HAVING literal against the SAMPLE DATA in the schema:\n"
        "1. Literal spelling/case may be wrong ('Italy' vs 'ITALY' vs 'IT').\n"
        "2. A date format may not match the stored format (check sample rows).\n"
        "3. A filter may be too restrictive or join may drop all rows.\n"
        "Fix the filter(s) so the query returns the intended rows. Preserve all other logic. "
        "Return the corrected SELECT statement."
    )

    class FixAnswer(BaseModel):
        sql: str = ""
        headline: str = ""
        chart_type: str = "auto"
        intent: str = ""
        approach: Any = None
        model_config = {"arbitrary_types_allowed": True}

    ans: FixAnswer = _coder().complete(
        system=CHAT_SQL_SYSTEM, user=prompt,
        response_model=FixAnswer, temperature=temperature,
    )
    return (ans.sql or "").strip()


def _fix_sql(question: str, schema: str, doc_section: str,
             bad_sql: str, error: str, temperature: float) -> str:
    """Ask the model to surgically fix the SQL given the execution error.

    The repair must be MINIMAL — fix only the specific error (wrong column name,
    syntax issue, missing table alias). Do NOT restructure, simplify, or rewrite
    the query logic. Preserve CTEs, CASE WHEN, PARTITION BY, LIMIT, and all
    semantic structure from the original SQL.
    """
    from aughor.llm.provider import get_provider
    from aughor.agent.prompts import CHAT_SQL_SYSTEM
    from pydantic import BaseModel
    from typing import Any

    fix_prompt = (
        f"DATABASE SCHEMA:\n{schema}\n\n"
        f"{_SQLITE_HINT}{doc_section}"
        f"QUESTION: {question}\n\n"
        f"PREVIOUS SQL (failed with the error below):\n{bad_sql}\n\n"
        f"EXECUTION ERROR:\n{error}\n\n"
        "Fix ONLY the specific error above. Rules:\n"
        "1. Make the minimal change needed — fix the column name, syntax, or alias that caused the error.\n"
        "2. Preserve ALL query structure: CTEs, CASE WHEN, PARTITION BY, ORDER BY, LIMIT, HAVING.\n"
        "3. Do NOT rewrite or simplify. Do NOT remove steps. Do NOT change the logic.\n"
        "4. If the error is an unknown column, look it up in the schema and substitute the correct name.\n"
        "Return the corrected SELECT statement with the same structure as the original."
    )

    class FixAnswer(BaseModel):
        sql: str = ""
        headline: str = ""
        chart_type: str = "auto"
        intent: str = ""
        approach: Any = None
        model_config = {"arbitrary_types_allowed": True}

    ans: FixAnswer = _coder().complete(
        system=CHAT_SQL_SYSTEM,
        user=fix_prompt,
        response_model=FixAnswer,
        temperature=temperature,
    )
    return (ans.sql or "").strip()


# ── per-instance worker ───────────────────────────────────────────────────────

def run_instance(inst: dict, spider_root: Path, out_dir: Path, temperature: float,
                 consensus_k: int = 1, reflect: bool = False, select: bool = False,
                 engine: bool = False) -> dict:
    iid = inst["instance_id"]
    db_name = inst["db"]
    started_at = datetime.now(timezone.utc).isoformat()
    t0 = time.monotonic()

    try:
        doc = load_external_knowledge(spider_root, inst.get("external_knowledge"))
        db_path = spider_root / "resource" / "databases" / f"{db_name}.sqlite"
        q = inst["question"]

        if engine:
            # ── Full Aughor engine: real SQLiteConnection + production pipeline ──
            reader = _engine_conn(spider_root, db_name)
            try:
                schema = reader.get_schema()
            except Exception:
                schema = build_schema(spider_root, db_name)
            link_detail = "full Aughor engine (schema-linker + ontology + guards)"
            linked = None
        else:
            # ── Lite path: hand-built schema + harness schema-linking ──
            all_tables = list_tables(spider_root, db_name)
            linked = None
            link_detail = "skipped (small schema)"
            if len(all_tables) > 6:
                picked = link_tables(q, all_tables, doc)
                if 0 < len(picked) < len(all_tables):
                    linked = set(picked)
                    link_detail = f"selected {len(picked)}/{len(all_tables)} tables: {', '.join(sorted(picked))}"
                else:
                    link_detail = f"kept all {len(all_tables)} tables"
            schema = build_schema(spider_root, db_name, only_tables=linked)
            reader = None

        if not schema:
            return {"id": iid, "ok": False, "error": f"no schema for db '{db_name}'"}

        schema_fetched_at = datetime.now(timezone.utc).isoformat()

        steps = [
            {"step": 1, "timestamp": schema_fetched_at, "action": "schema_linking",
             "detail": link_detail},
            {"step": 2, "timestamp": schema_fetched_at, "action": "schema_extraction",
             "detail": ("Aughor build_intelligence (profiles + ontology)" if engine
                        else f"Built DDL + FK paths + sample rows for '{db_name}'")},
            {"step": 3, "timestamp": schema_fetched_at, "action": "external_knowledge",
             "detail": f"Loaded external knowledge: {inst.get('external_knowledge') or 'none'}"},
        ]

        def _gen(idx, temp):
            strat = _STRATEGIES[idx % len(_STRATEGIES)]
            if engine:
                return generate_sql_engine(q, db_name, reader, temp, doc, strat)
            return generate_sql(q, schema, doc, temp, strat)

        if consensus_k > 1 and db_path.exists():
            # ── Self-consistency path: generate K, execute, vote ──
            from aughor.agent.sql_consensus import generate_consensus_sql
            selector = _make_selector(q, doc, db_path) if select else None
            result = generate_consensus_sql(
                generate_fn=_gen,
                execute_fn=lambda s: _sqlite_exec(db_path, s),
                repair_fn=lambda bad, err, temp: _fix_sql(q, schema, doc, bad, err, temp),
                empty_recovery_fn=lambda bad, msg, temp: _recover_empty(q, schema, doc, bad, msg, temp),
                selector_fn=selector,
                k=consensus_k,
                repair_rounds=2,
            )
            sql = result.sql
            # Full-schema fallback: if linking trimmed too aggressively and every
            # candidate failed, retry consensus on the COMPLETE schema. Schema
            # linking then only ever helps (speed) — it can never lose a question.
            if not sql and linked is not None:
                full_schema = build_schema(spider_root, db_name, only_tables=None)
                result = generate_consensus_sql(
                    generate_fn=lambda idx, temp: generate_sql(q, full_schema, doc, temp, _STRATEGIES[idx % len(_STRATEGIES)]),
                    execute_fn=lambda s: _sqlite_exec(db_path, s),
                    repair_fn=lambda bad, err, temp: _fix_sql(q, full_schema, doc, bad, err, temp),
                    empty_recovery_fn=lambda bad, msg, temp: _recover_empty(q, full_schema, doc, bad, msg, temp),
                    selector_fn=selector,
                    k=consensus_k, repair_rounds=2,
                )
                sql = result.sql
                steps.append({"step": 4, "timestamp": datetime.now(timezone.utc).isoformat(),
                              "action": "schema_link_fallback",
                              "detail": "Linked schema yielded no valid candidate — retried on full schema"})
            if not sql:
                return {"id": iid, "ok": False, "error": "no valid candidate after consensus"}
            steps.append({
                "step": 5, "timestamp": datetime.now(timezone.utc).isoformat(),
                "action": "self_consistency_vote",
                "detail": f"Generated {consensus_k} candidates, {result.total_valid} executed, "
                          f"winner agreed by {result.vote_count}/{result.total_valid}",
                "candidates": result.steps,
                "output": sql,
            })
            sql_generated_at = datetime.now(timezone.utc).isoformat()
        else:
            # ── Single-shot path with 1 repair on error ──
            sql = _gen(0, temperature)
            sql_generated_at = datetime.now(timezone.utc).isoformat()
            if not sql:
                return {"id": iid, "ok": False, "error": "empty SQL from model"}
            steps.append({
                "step": 4, "timestamp": sql_generated_at, "action": "nl2sql_generation",
                "detail": "NL2SQL via Aughor chat prompt (SQLite dialect)", "output": sql,
            })
            if db_path.exists():
                ok, err = _sqlite_try(db_path, sql)
                if not ok:
                    fixed_sql = _fix_sql(inst["question"], schema, doc, sql, err, temperature)
                    steps.append({"step": 4, "timestamp": datetime.now(timezone.utc).isoformat(),
                                  "action": "execute_error", "detail": f"Execution failed: {err[:200]}"})
                    if fixed_sql:
                        ok2, err2 = _sqlite_try(db_path, fixed_sql)
                        steps.append({"step": 5, "timestamp": datetime.now(timezone.utc).isoformat(),
                                      "action": "self_correction",
                                      "detail": f"Retry {'succeeded' if ok2 else 'also failed: ' + err2[:200]}",
                                      "output": fixed_sql})
                        if ok2:
                            sql = fixed_sql

        # ── Result-reflection pass: a reasoning model checks the winner answers
        # the question (cardinality/grain/columns/filters) and revises if not.
        if reflect and sql and db_path.exists():
            revised, refl_step = _reflect_revise(inst["question"], schema, doc, sql, db_path)
            refl_step["step"] = 6
            refl_step["timestamp"] = datetime.now(timezone.utc).isoformat()
            steps.append(refl_step)
            sql = revised

        # Write prediction SQL
        (out_dir / f"{iid}.sql").write_text(sql + "\n")

        # Write reasoning trace (required by submission guidelines)
        trace = {
            "instance_id": iid,
            "db": db_name,
            "question": inst["question"],
            "external_knowledge": inst.get("external_knowledge"),
            "method": METHOD_NAME,
            "timestamps": {
                "started": started_at,
                "schema_fetched": schema_fetched_at,
                "sql_generated": sql_generated_at,
            },
            "steps": steps,
            "elapsed_seconds": round(time.monotonic() - t0, 2),
        }
        (out_dir / f"{iid}_trace.json").write_text(json.dumps(trace, indent=2))

        return {"id": iid, "ok": True, "secs": round(time.monotonic() - t0, 1)}

    except Exception as e:
        return {"id": iid, "ok": False, "error": f"{type(e).__name__}: {e}"}


# ── generation loop ───────────────────────────────────────────────────────────

def generate(spider_root: Path, out_dir: Path, limit: int | None,
             ids: set[str] | None, workers: int, temperature: float,
             consensus_k: int = 1, reflect: bool = False, select: bool = False,
             engine: bool = False) -> None:
    instances = load_local_instances(spider_root)
    if ids:
        instances = [r for r in instances if r["instance_id"] in ids]
    if limit:
        instances = instances[:limit]

    out_dir.mkdir(parents=True, exist_ok=True)
    run_ts = datetime.now(timezone.utc).isoformat()
    mode = f"consensus k={consensus_k}" if consensus_k > 1 else "single-shot"
    if engine:
        mode += " +ENGINE"
    if select:
        mode += " +select"
    if reflect:
        mode += " +reflect"
    print(f"[{run_ts}] Generating {len(instances)} local predictions → {out_dir} "
          f"(workers={workers}, temp={temperature}, mode={mode})")

    done = ok = 0
    fails: list[dict] = []

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(run_instance, r, spider_root, out_dir, temperature, consensus_k, reflect, select, engine): r["instance_id"]
                for r in instances}
        for fut in as_completed(futs):
            res = fut.result()
            done += 1
            if res["ok"]:
                ok += 1
            else:
                fails.append(res)
            ts = datetime.now(timezone.utc).isoformat()
            tag = f"ok ({res['secs']}s)" if res["ok"] else f"FAIL {res.get('error','')[:80]}"
            print(f"  [{ts}] [{done}/{len(instances)}] {res['id']}: {tag}")

    print(f"\nGenerated {ok}/{len(instances)} SQL files.")
    if fails:
        print(f"Failures ({len(fails)}):")
        for f in fails:
            print(f"  - {f['id']}: {f.get('error')}")


# ── BigQuery stub (evaluate.py imports it unconditionally) ────────────────────

def _make_bq_stub(base: Path) -> Path:
    stub = base / "_bq_stub"
    (stub / "google" / "cloud" / "bigquery").mkdir(parents=True, exist_ok=True)
    (stub / "google" / "__init__.py").write_text("")
    (stub / "google" / "cloud" / "__init__.py").write_text("")
    (stub / "google" / "cloud" / "bigquery" / "__init__.py").write_text(
        "# stub: local/SQLite evaluation never calls BigQuery\n"
    )
    return stub


# ── scoring via Spider's official evaluate.py ─────────────────────────────────

def score(spider_root: Path, out_dir: Path, workers: int) -> None:
    eval_suite = spider_root / "evaluation_suite"
    evaluate_py = eval_suite / "evaluate.py"
    gold_dir = eval_suite / "gold"

    if not evaluate_py.exists():
        print(f"ERROR: evaluate.py not found at {evaluate_py}", file=sys.stderr)
        sys.exit(2)

    n_sql = len(list(out_dir.glob("*.sql")))
    if n_sql == 0:
        print("No .sql files found in output dir — run generation first.", file=sys.stderr)
        sys.exit(2)

    stub = _make_bq_stub(out_dir.resolve().parent)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(stub.resolve()) + os.pathsep + env.get("PYTHONPATH", "")

    cmd = [
        sys.executable, str(evaluate_py),
        "--mode", "sql",
        "--result_dir", str(out_dir.resolve()),
        "--gold_dir", str(gold_dir.resolve()),
        "--max_workers", str(workers),
    ]
    print(f"\n[{datetime.now(timezone.utc).isoformat()}] Running Spider's evaluator:")
    print("  " + " ".join(cmd))
    subprocess.run(cmd, cwd=str(eval_suite), check=False, env=env)

    ids_csv = Path(str(out_dir.resolve()) + "-ids.csv")
    csv_dir = Path(str(out_dir.resolve()) + "_csv")
    if ids_csv.exists():
        correct = sum(1 for _ in ids_csv.read_text().splitlines()) - 1
        ex = (correct / n_sql * 100) if n_sql else 0.0
        print(f"\n=== Spider 2.0-Lite (local/SQLite) EX = {correct}/{n_sql} = {ex:.2f}% ===")
        print(f"Correct IDs saved to: {ids_csv}")
    if csv_dir.exists():
        n_csv = len(list(csv_dir.glob("*.csv")))
        print(f"Execution result CSVs: {n_csv} files in {csv_dir}")


# ── submission packaging ──────────────────────────────────────────────────────

def package(out_dir: Path) -> None:
    """Package sql/, csv/, traces/ into aughor_spider2lite_submission.zip."""
    sql_dir = out_dir
    csv_dir = Path(str(out_dir) + "_csv")
    traces_dir = out_dir  # trace files are co-located with sql files

    sql_files = sorted(sql_dir.glob("*.sql"))
    csv_files = sorted(csv_dir.glob("*.csv")) if csv_dir.exists() else []
    trace_files = sorted(traces_dir.glob("*_trace.json"))

    if not sql_files:
        print("No .sql files to package.", file=sys.stderr)
        sys.exit(2)

    zip_path = out_dir.parent / "aughor_spider2lite_submission.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sql_files:
            zf.write(f, f"sql/{f.name}")
        for f in csv_files:
            zf.write(f, f"csv/{f.name}")
        for f in trace_files:
            zf.write(f, f"traces/{f.name}")

    print(f"\nSubmission package: {zip_path}")
    print(f"  sql/    : {len(sql_files)} files")
    print(f"  csv/    : {len(csv_files)} files")
    print(f"  traces/ : {len(trace_files)} files")
    print("\nNext: email to lfy79001@gmail.com with:")
    print("  - This zip attached")
    print("  - Method name: Aughor NL2SQL")
    print("  - Brief description of the approach")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Spider 2.0-Lite benchmark for Aughor NL2SQL")
    ap.add_argument("--spider-root", required=True, type=Path,
                    help="Path to the spider2-lite directory")
    ap.add_argument("--out", required=True, type=Path,
                    help="Output dir for predictions (*.sql + *_trace.json)")
    ap.add_argument("--limit", type=int, default=None,
                    help="Only the first N instances (smoke test)")
    ap.add_argument("--ids", type=str, default=None,
                    help="Comma-separated instance IDs to (re)generate")
    ap.add_argument("--dev", action="store_true",
                    help="Run only the fixed 19-instance dev set (evals/spider2_dev_set.json)")
    ap.add_argument("--coder-model", type=str, default=None,
                    help="Override the coder model for generation (e.g. gpt-oss:120b-cloud)")
    ap.add_argument("--engine", action="store_true",
                    help="Route generation through the FULL Aughor engine (SQLiteConnection + "
                         "build_intelligence + generate_sql_full_pipeline guards)")
    ap.add_argument("--workers", type=int, default=4,
                    help="Concurrent generation / eval workers")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--consensus", type=int, default=1,
                    help="Number of candidates for self-consistency voting (1 = single-shot)")
    ap.add_argument("--select", action="store_true",
                    help="Pairwise candidate selection (reasoning judge) on consensus ties")
    ap.add_argument("--reflect", action="store_true",
                    help="Run a reasoning-model reflection pass on the consensus winner")
    ap.add_argument("--score", action="store_true",
                    help="Run Spider's evaluator after generation")
    ap.add_argument("--score-only", action="store_true",
                    help="Skip generation; only score existing predictions")
    ap.add_argument("--package", action="store_true",
                    help="Package output into a submission zip")
    args = ap.parse_args()

    ids = set(s.strip() for s in args.ids.split(",")) if args.ids else None
    if args.dev:
        ds = json.loads((_REPO_ROOT / "evals" / "spider2_dev_set.json").read_text())
        ids = {d["id"] for tier in ds.values() for d in tier}
        print(f"Dev mode: {len(ids)} instances (7 easy / 7 medium / 5 hard)")

    if args.coder_model:
        global _CODER_MODEL
        _CODER_MODEL = args.coder_model
        print(f"Coder model override: {_CODER_MODEL}")

    if not args.score_only:
        generate(args.spider_root, args.out, args.limit, ids, args.workers,
                 args.temperature, args.consensus, args.reflect, args.select, args.engine)

    if args.score or args.score_only:
        score(args.spider_root, args.out, args.workers)

    if args.package:
        package(args.out)


if __name__ == "__main__":
    main()
