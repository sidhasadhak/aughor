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


def build_schema_context(conn) -> str:
    """The connector's schema text + up to SAMPLE_ROWS real rows per table (the June
    design: DDL + samples ground the literals), capped so a wide DB can't blow the prompt."""
    schema = conn.get_schema() or ""
    parts = [schema, "\nSAMPLE ROWS (first rows per table, for value formats — not exhaustive):"]
    try:
        cols, rows, _ = conn.raw_execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = [r[0] for r in rows]
    except Exception:
        tables = []
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
    """One product-prompt generation (same shape as evals/run_golden.generate_sql_chat)."""
    from pydantic import BaseModel, Field

    from aughor.agent.prompts import CHAT_PROMPT, CHAT_SQL_SYSTEM
    from aughor.llm.provider import get_provider

    class ChatAnswerModel(BaseModel):
        sql: str = ""
        headline: str = ""
        chart_type: str = "auto"
        intent: str = ""
        approach: list[str] = Field(default_factory=list)

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
        document_section=document_section,
    )
    answer = get_provider("coder").complete(
        system=CHAT_SQL_SYSTEM, user=prompt,
        response_model=ChatAnswerModel, temperature=temperature,
    )
    return (answer.sql or "").strip()


def run_instance(record: dict, outdir: Path, temperature: float, use_ek: bool = True) -> dict:
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
        step("schema", chars=len(schema))
        ek = external_knowledge_section(record) if use_ek else ""
        if ek:
            step("external_knowledge", doc=record.get("external_knowledge"), chars=len(ek))
        engine_note = ("\nENGINE: SQLite. Emit ONE SQLite-compatible SELECT (no DuckDB/Postgres "
                       "extensions). Answer the question's implied output shape exactly.\n")

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

        loop = execute_with_repair(guarded, execute_fn, repair_fn, max_rounds=2)
        step("closed_loop", ok=loop.ok, rounds=loop.rounds, rows=loop.row_count,
             receipt=loop.receipt)

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
          f"temp={args.temperature} ek={'off' if args.no_ek else 'on'} out={outdir}")

    results = []
    for i, rec in enumerate(records, 1):
        print(f"  [{i}/{len(records)}] {rec['instance_id']} ...", flush=True)
        try:
            r = run_instance(rec, outdir, args.temperature, use_ek=not args.no_ek)
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
