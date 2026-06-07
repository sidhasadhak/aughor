#!/usr/bin/env python3
"""NL2SQL eval on ClickBench — wide single-table web-analytics aggregations.

ClickBench (benchmark.clickhouse.com) is a DBMS *performance* benchmark: 43 SQL
queries on one denormalised 105-column `hits` table (web analytics). We repurpose
it for NL2SQL: it tests a dimension TPC-H/DS don't — wide-table aggregations with
COUNT(DISTINCT) across many dimensions, top-N, and time buckets, no joins.

Setup materialises a sample of the public hits parquet into a local DuckDB; the
generated and reference queries run on the SAME sample, so execution comparison
(run_tpch's measure-based _equiv) is valid for correctness regardless of scale.

Usage:
    AUGHOR_LLM_BACKEND=ollama AUGHOR_CODER_MODEL=qwen3-coder-next:cloud \
      .venv/bin/python evals/run_clickbench.py [--rows 1000000] [--output out.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

_REPO = Path(__file__).parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from evals.run_tpch import _equiv

_HITS_URL = "https://datasets.clickhouse.com/hits_compatible/hits.parquet"
_DB = "/tmp/clickbench.duckdb"

# (natural-language question, verbatim ClickBench reference SQL). Portable subset
# (standard SQL that runs on DuckDB). Generated SQL is compared to the reference
# executed on the same sample.
CASES: list[tuple[str, str]] = [
    ("How many total hits (rows) are in the dataset?",
     "SELECT COUNT(*) FROM hits"),
    ("How many hits came from an advertising engine (AdvEngineID not equal to 0)?",
     "SELECT COUNT(*) FROM hits WHERE AdvEngineID <> 0"),
    ("What is the sum of AdvEngineID, the total number of hits, and the average ResolutionWidth?",
     "SELECT SUM(AdvEngineID), COUNT(*), AVG(ResolutionWidth) FROM hits"),
    ("What is the number of distinct users (UserID)?",
     "SELECT COUNT(DISTINCT UserID) FROM hits"),
    ("How many distinct non-empty search phrases are there?",
     "SELECT COUNT(DISTINCT SearchPhrase) FROM hits"),
    ("What are the earliest and latest event dates?",
     "SELECT MIN(EventDate), MAX(EventDate) FROM hits"),
    ("For each advertising engine (excluding 0), how many hits? Order by the count descending.",
     "SELECT AdvEngineID, COUNT(*) FROM hits WHERE AdvEngineID <> 0 GROUP BY AdvEngineID ORDER BY COUNT(*) DESC"),
    ("Which 10 regions have the most distinct users? Show region id and the distinct-user count.",
     "SELECT RegionID, COUNT(DISTINCT UserID) AS u FROM hits GROUP BY RegionID ORDER BY u DESC LIMIT 10"),
    ("What are the top 10 non-empty search phrases by number of hits?",
     "SELECT SearchPhrase, COUNT(*) AS c FROM hits WHERE SearchPhrase <> '' GROUP BY SearchPhrase ORDER BY c DESC LIMIT 10"),
    ("Which 10 mobile phone models have the most distinct users? (exclude empty model)",
     "SELECT MobilePhoneModel, COUNT(DISTINCT UserID) AS u FROM hits WHERE MobilePhoneModel <> '' GROUP BY MobilePhoneModel ORDER BY u DESC LIMIT 10"),
]


def ensure_db(rows: int) -> str:
    import duckdb
    if not os.path.exists(_DB):
        c = duckdb.connect(_DB)
        c.execute("INSTALL httpfs; LOAD httpfs;")
        t0 = time.time()
        c.execute(f"CREATE TABLE hits AS SELECT * FROM read_parquet('{_HITS_URL}') LIMIT {rows}")
        n = c.execute("SELECT count(*) FROM hits").fetchone()[0]
        print(f"[setup] materialised {n:,} hits rows in {time.time()-t0:.1f}s")
        c.close()
    return _DB


def ensure_connection(path: str) -> str:
    from aughor.db.registry import add_connection, list_connections
    for c in list_connections():
        if c.get("name") == "clickbench":
            return c.get("id")
    return add_connection(name="clickbench", conn_type="duckdb", dsn=path, meta={})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=1_000_000)
    ap.add_argument("--output", default=None)
    args = ap.parse_args()

    import duckdb
    from aughor.db.connection import open_connection_for
    from evals.run_golden import generate_sql_full_pipeline

    path = ensure_db(args.rows)
    cid = ensure_connection(path)
    db = open_connection_for(cid)
    raw = getattr(db, "_conn", None) or duckdb.connect(path, read_only=True)

    results = []
    for i, (q, ref_sql) in enumerate(CASES, 1):
        rec = {"n": i, "question": q}
        t0 = time.time()
        try:
            gen_sql = generate_sql_full_pipeline(q, cid, db)
            rec["generated_sql"] = gen_sql
            gen = raw.execute(gen_sql).fetchall() if gen_sql else []
            ref = raw.execute(ref_sql).fetchall()
            rec.update(verdict="CORRECT" if _equiv(gen, ref) else "WRONG", error=None)
        except Exception as e:
            rec.update(verdict="ERROR", error=str(e)[:200])
        rec["latency_s"] = round(time.time() - t0, 1)
        results.append(rec)
        print(f"  Q{i:<2} {rec['verdict']:8} ({rec['latency_s']}s)  {q[:58]}…")
        if rec.get("error"):
            print(f"        {rec['error']}")

    n = len(results)
    cor = sum(1 for r in results if r["verdict"] == "CORRECT")
    err = sum(1 for r in results if r["verdict"] == "ERROR")
    print("\n" + "=" * 60)
    print(f" ClickBench (sample)  generator: {os.getenv('AUGHOR_CODER_MODEL','default')}")
    print(f" Correct (exec-validated): {cor}/{n}   Errors: {err}")
    print("=" * 60)
    if args.output:
        json.dump({"results": results, "summary": {"total": n, "correct": cor, "errors": err}},
                  open(args.output, "w"), indent=2, default=str)
        print(f"written to {args.output}")


if __name__ == "__main__":
    main()
