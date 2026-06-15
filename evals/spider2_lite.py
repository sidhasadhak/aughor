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
        ans: Linked = get_provider("coder").complete(
            system="You are a database expert selecting relevant tables for a SQL query.",
            user=prompt, response_model=Linked, temperature=0.0,
        )
        valid = {t.lower() for t in table_names}
        picked = [t for t in ans.tables if t.lower() in valid]
        return picked or table_names
    except Exception:
        return table_names


def generate_sql(question: str, schema: str, doc_section: str, temperature: float = 0.0) -> str:
    from aughor.llm.provider import get_provider
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
        document_section=_SQLITE_HINT + doc_section,
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

    ans: Answer = get_provider("coder").complete(
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

    ans: FixAnswer = get_provider("coder").complete(
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

    ans: FixAnswer = get_provider("coder").complete(
        system=CHAT_SQL_SYSTEM,
        user=fix_prompt,
        response_model=FixAnswer,
        temperature=temperature,
    )
    return (ans.sql or "").strip()


# ── per-instance worker ───────────────────────────────────────────────────────

def run_instance(inst: dict, spider_root: Path, out_dir: Path, temperature: float,
                 consensus_k: int = 1) -> dict:
    iid = inst["instance_id"]
    db_name = inst["db"]
    started_at = datetime.now(timezone.utc).isoformat()
    t0 = time.monotonic()

    try:
        doc = load_external_knowledge(spider_root, inst.get("external_knowledge"))
        db_path = spider_root / "resource" / "databases" / f"{db_name}.sqlite"

        # Schema linking for wide databases: pick relevant tables first so the
        # prompt isn't bloated with dozens of irrelevant tables (faster + sharper).
        all_tables = list_tables(spider_root, db_name)
        linked: set[str] | None = None
        link_detail = "skipped (small schema)"
        if len(all_tables) > 6:
            picked = link_tables(inst["question"], all_tables, doc)
            if 0 < len(picked) < len(all_tables):
                linked = set(picked)
                link_detail = f"selected {len(picked)}/{len(all_tables)} tables: {', '.join(sorted(picked))}"
            else:
                link_detail = f"kept all {len(all_tables)} tables"

        schema = build_schema(spider_root, db_name, only_tables=linked)
        if not schema:
            return {"id": iid, "ok": False, "error": f"no DDL for db '{db_name}'"}

        schema_fetched_at = datetime.now(timezone.utc).isoformat()

        steps = [
            {"step": 1, "timestamp": schema_fetched_at, "action": "schema_linking",
             "detail": link_detail},
            {"step": 2, "timestamp": schema_fetched_at, "action": "schema_extraction",
             "detail": f"Built DDL + FK paths + sample rows for database '{db_name}'"},
            {"step": 3, "timestamp": schema_fetched_at, "action": "external_knowledge",
             "detail": f"Loaded external knowledge: {inst.get('external_knowledge') or 'none'}"},
        ]

        if consensus_k > 1 and db_path.exists():
            # ── Self-consistency path: generate K, execute, vote ──
            from aughor.agent.sql_consensus import generate_consensus_sql
            q = inst["question"]
            result = generate_consensus_sql(
                generate_fn=lambda temp: generate_sql(q, schema, doc, temp),
                execute_fn=lambda s: _sqlite_exec(db_path, s),
                repair_fn=lambda bad, err, temp: _fix_sql(q, schema, doc, bad, err, temp),
                empty_recovery_fn=lambda bad, msg, temp: _recover_empty(q, schema, doc, bad, msg, temp),
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
                    generate_fn=lambda temp: generate_sql(q, full_schema, doc, temp),
                    execute_fn=lambda s: _sqlite_exec(db_path, s),
                    repair_fn=lambda bad, err, temp: _fix_sql(q, full_schema, doc, bad, err, temp),
                    empty_recovery_fn=lambda bad, msg, temp: _recover_empty(q, full_schema, doc, bad, msg, temp),
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
            sql = generate_sql(inst["question"], schema, doc, temperature)
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
             consensus_k: int = 1) -> None:
    instances = load_local_instances(spider_root)
    if ids:
        instances = [r for r in instances if r["instance_id"] in ids]
    if limit:
        instances = instances[:limit]

    out_dir.mkdir(parents=True, exist_ok=True)
    run_ts = datetime.now(timezone.utc).isoformat()
    mode = f"consensus k={consensus_k}" if consensus_k > 1 else "single-shot"
    print(f"[{run_ts}] Generating {len(instances)} local predictions → {out_dir} "
          f"(workers={workers}, temp={temperature}, mode={mode})")

    done = ok = 0
    fails: list[dict] = []

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(run_instance, r, spider_root, out_dir, temperature, consensus_k): r["instance_id"]
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
    ap.add_argument("--workers", type=int, default=4,
                    help="Concurrent generation / eval workers")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--consensus", type=int, default=1,
                    help="Number of candidates for self-consistency voting (1 = single-shot)")
    ap.add_argument("--score", action="store_true",
                    help="Run Spider's evaluator after generation")
    ap.add_argument("--score-only", action="store_true",
                    help="Skip generation; only score existing predictions")
    ap.add_argument("--package", action="store_true",
                    help="Package output into a submission zip")
    args = ap.parse_args()

    ids = set(s.strip() for s in args.ids.split(",")) if args.ids else None

    if not args.score_only:
        generate(args.spider_root, args.out, args.limit, ids, args.workers,
                 args.temperature, args.consensus)

    if args.score or args.score_only:
        score(args.spider_root, args.out, args.workers)

    if args.package:
        package(args.out)


if __name__ == "__main__":
    main()
