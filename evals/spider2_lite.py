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
import shutil
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


def build_schema(spider_root: Path, db_name: str) -> str:
    """Return CREATE TABLE DDL for all tables in the database."""
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
    parts = []
    for row in csv.DictReader(ddl_path.open()):
        ddl = (row.get("DDL") or "").strip()
        if ddl:
            parts.append(ddl)
    return "\n\n".join(parts)


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


# ── per-instance worker ───────────────────────────────────────────────────────

def run_instance(inst: dict, spider_root: Path, out_dir: Path, temperature: float) -> dict:
    iid = inst["instance_id"]
    db_name = inst["db"]
    started_at = datetime.now(timezone.utc).isoformat()
    t0 = time.monotonic()

    try:
        schema = build_schema(spider_root, db_name)
        if not schema:
            return {"id": iid, "ok": False, "error": f"no DDL for db '{db_name}'"}

        doc = load_external_knowledge(spider_root, inst.get("external_knowledge"))
        schema_fetched_at = datetime.now(timezone.utc).isoformat()

        sql = generate_sql(inst["question"], schema, doc, temperature)
        sql_generated_at = datetime.now(timezone.utc).isoformat()

        if not sql:
            return {"id": iid, "ok": False, "error": "empty SQL from model"}

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
            "steps": [
                {
                    "step": 1,
                    "timestamp": schema_fetched_at,
                    "action": "schema_extraction",
                    "detail": f"Extracted DDL for database '{db_name}' from DDL.csv",
                },
                {
                    "step": 2,
                    "timestamp": schema_fetched_at,
                    "action": "external_knowledge",
                    "detail": f"Loaded external knowledge: {inst.get('external_knowledge') or 'none'}",
                },
                {
                    "step": 3,
                    "timestamp": sql_generated_at,
                    "action": "nl2sql_generation",
                    "detail": "Single-shot NL2SQL via Aughor chat prompt (SQLite dialect)",
                    "output": sql,
                },
            ],
            "elapsed_seconds": round(time.monotonic() - t0, 2),
        }
        (out_dir / f"{iid}_trace.json").write_text(json.dumps(trace, indent=2))

        return {"id": iid, "ok": True, "secs": round(time.monotonic() - t0, 1)}

    except Exception as e:
        return {"id": iid, "ok": False, "error": f"{type(e).__name__}: {e}"}


# ── generation loop ───────────────────────────────────────────────────────────

def generate(spider_root: Path, out_dir: Path, limit: int | None,
             ids: set[str] | None, workers: int, temperature: float) -> None:
    instances = load_local_instances(spider_root)
    if ids:
        instances = [r for r in instances if r["instance_id"] in ids]
    if limit:
        instances = instances[:limit]

    out_dir.mkdir(parents=True, exist_ok=True)
    run_ts = datetime.now(timezone.utc).isoformat()
    print(f"[{run_ts}] Generating {len(instances)} local predictions → {out_dir} "
          f"(workers={workers}, temp={temperature})")

    done = ok = 0
    fails: list[dict] = []

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(run_instance, r, spider_root, out_dir, temperature): r["instance_id"]
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
    ap.add_argument("--score", action="store_true",
                    help="Run Spider's evaluator after generation")
    ap.add_argument("--score-only", action="store_true",
                    help="Skip generation; only score existing predictions")
    ap.add_argument("--package", action="store_true",
                    help="Package output into a submission zip")
    args = ap.parse_args()

    ids = set(s.strip() for s in args.ids.split(",")) if args.ids else None

    if not args.score_only:
        generate(args.spider_root, args.out, args.limit, ids, args.workers, args.temperature)

    if args.score or args.score_only:
        score(args.spider_root, args.out, args.workers)

    if args.package:
        package(args.out)


if __name__ == "__main__":
    main()
