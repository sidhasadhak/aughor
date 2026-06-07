#!/usr/bin/env python3
"""Real-scale NL2SQL eval on TPC-DS — 24-table snowflake, validated ground truth.

Companion to run_tpch.py for a much harder schema: DuckDB generates TPC-DS
(`INSTALL tpcds; CALL dsdgen(sf=N)` → SF=1 = 2.88M store_sales rows, 24 tables,
99 official queries). We run the full chat pipeline on the natural-language form
of a tractable subset and score by EXECUTION against the official query (reusing
run_tpch's measure-based comparator). Tests join grounding where it matters most:
many tables, surrogate keys (_sk), and a role-played date dimension.

Usage:
    AUGHOR_LLM_BACKEND=ollama AUGHOR_CODER_MODEL=qwen3-coder-next:cloud \
      .venv/bin/python evals/run_tpcds.py --sf 1 [--only 3,42] [--output out.json]
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

from evals.run_tpch import _equiv  # measure-based execution comparator


# Natural-language forms of tractable TPC-DS business questions, mapped to the
# official query number. Parameters match the standard substitution values so the
# bundled query is the ground truth.
QUESTIONS: dict[int, str] = {
    3:  "For items from manufacturer 128, show the total store external sales price "
        "by year and brand for sales made in November (any year). List the year, the "
        "brand id, the brand, and the summed sales, ordered by year then sales descending.",
    42: "For items managed by manager 1, show the total store external sales price by "
        "category for November 2000. List the year, category id, category, and the "
        "total, ordered by the total descending.",
    52: "For items managed by manager 1, show the total store external sales price by "
        "brand for November 2000. List the year, brand id, brand, and the total, "
        "ordered by the total descending.",
    55: "For items managed by manager 28, show the total store external sales price by "
        "brand for November 1999. List the brand id, brand, and the total, ordered by "
        "the total descending.",
    96: "Count the store sales that occurred at hour 20 with the minute at least 30, "
        "where the buyer's household had a dependent count of 7 and the store name is 'ese'.",
}


def ensure_tpcds_db(sf: float) -> str:
    import duckdb
    path = f"/tmp/tpcds_sf{sf:g}.duckdb"
    if not os.path.exists(path):
        c = duckdb.connect(path)
        c.execute("INSTALL tpcds; LOAD tpcds;")
        t0 = time.time()
        c.execute(f"CALL dsdgen(sf={sf})")
        print(f"[setup] generated TPC-DS SF={sf:g} in {time.time()-t0:.1f}s "
              f"({c.execute('SELECT count(*) FROM store_sales').fetchone()[0]:,} store_sales rows)")
        c.close()
    return path


def ensure_connection(path: str) -> str:
    from aughor.db.registry import add_connection, list_connections
    name = f"tpcds::{Path(path).stem}"
    for c in list_connections():
        if c.get("name") == name:
            return c.get("id")
    return add_connection(name=name, conn_type="duckdb", dsn=path, meta={})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sf", type=float, default=1.0)
    ap.add_argument("--only", default="")
    ap.add_argument("--output", default=None)
    args = ap.parse_args()

    import duckdb
    from aughor.db.connection import open_connection_for
    from evals.run_golden import generate_sql_full_pipeline

    path = ensure_tpcds_db(args.sf)
    cid = ensure_connection(path)
    wanted = [int(x) for x in args.only.split(",") if x.strip()] or sorted(QUESTIONS)
    db = open_connection_for(cid)
    raw = getattr(db, "_conn", None) or duckdb.connect(path, read_only=True)
    try:
        raw.execute("LOAD tpcds")
    except Exception:
        pass

    results = []
    for nr in wanted:
        q = QUESTIONS[nr]
        rec = {"query_nr": nr, "question": q}
        t0 = time.time()
        try:
            gen_sql = generate_sql_full_pipeline(q, cid, db)
            rec["generated_sql"] = gen_sql
            gen_rows = raw.execute(gen_sql).fetchall() if gen_sql else []
            off_sql = raw.execute("SELECT query FROM tpcds_queries() WHERE query_nr=?", [nr]).fetchone()[0]
            ref_rows = raw.execute(off_sql).fetchall()
            ok = _equiv(gen_rows, ref_rows)
            rec.update(verdict="CORRECT" if ok else "WRONG", error=None,
                       gen_row_count=len(gen_rows), ref_row_count=len(ref_rows))
        except Exception as e:
            rec.update(verdict="ERROR", error=str(e)[:200])
        rec["latency_s"] = round(time.time() - t0, 1)
        results.append(rec)
        print(f"  Q{nr:<3} {rec['verdict']:8} ({rec['latency_s']}s)  {q[:58]}…")
        if rec.get("error"):
            print(f"        ERROR: {rec['error']}")

    n = len(results)
    correct = sum(1 for r in results if r["verdict"] == "CORRECT")
    errors = sum(1 for r in results if r["verdict"] == "ERROR")
    print("\n" + "=" * 60)
    print(f" TPC-DS SF={args.sf:g}  |  generator: {os.getenv('AUGHOR_CODER_MODEL','default')}")
    print(f" Correct (exec-validated): {correct}/{n}   Errors: {errors}")
    print("=" * 60)

    if args.output:
        json.dump({"results": results, "summary": {"total": n, "correct": correct, "errors": errors}},
                  open(args.output, "w"), indent=2, default=str)
        print(f"written to {args.output}")


if __name__ == "__main__":
    main()
