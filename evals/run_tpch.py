#!/usr/bin/env python3
"""Real-scale NL2SQL eval on TPC-H — massive data, unseen schema, validated answers.

Why this exists: the golden_sql fixture is 53 hand-written questions on a 5-table
toy DB scored by exact reference-shape match — brittle and overfittable. TPC-H is
the opposite: DuckDB generates a real 8-table analytics star schema at any scale
(SF=1 → 6M lineitems) and ships 22 canonical business questions WITH validated
answers (`tpch_queries()` / `tpch_answers()`). We run our FULL chat pipeline on the
natural-language form of those questions against a schema the platform has never
seen, then score by EXECUTION against the official query result — no hand-written
reference SQL, generalizes to any database.

Usage:
    AUGHOR_LLM_BACKEND=ollama AUGHOR_CODER_MODEL=kimi-k2.6:cloud \
      .venv/bin/python evals/run_tpch.py --sf 1 [--only 1,3,6] [--output out.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

_REPO = Path(__file__).parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


# ── Natural-language form of the canonical TPC-H business questions ───────────
# Mapped to the official query number so we can pull DuckDB's reference query +
# validated answer. Phrased as a business user would — the parameters match the
# standard substitution values so the official query is the ground truth.
QUESTIONS: dict[int, str] = {
    1: "For every lineitem shipped on or before 1998-09-02, group by return flag and "
       "line status and report total quantity, total extended price, total revenue "
       "(extended price after discount), total revenue including tax, average quantity, "
       "average extended price, average discount, and the number of lineitems. Order by "
       "return flag and line status.",
    3: "List the 10 highest-revenue unshipped orders in the BUILDING market segment: "
       "orders placed before 1995-03-15 with lineitems shipped after 1995-03-15. Revenue "
       "is the sum of extended price times (1 minus discount). Show the order key, revenue, "
       "order date, and shipping priority, ordered by revenue descending then order date.",
    5: "For customers and suppliers both in the ASIA region, and orders placed in 1994, "
       "compute total revenue (extended price times (1 minus discount)) per nation where "
       "the customer's nation equals the supplier's nation. Order by revenue descending.",
    6: "What is the total potential revenue increase from lineitems shipped in 1994 with a "
       "discount between 0.05 and 0.07 and a quantity below 24? Revenue increase is the sum "
       "of extended price times discount.",
    10: "Find the top 20 customers who generated the most lost revenue from returned items: "
        "orders placed between 1993-10-01 and 1993-12-31 with returned lineitems (return flag "
        "'R'). Revenue is extended price times (1 minus discount). Show customer name, that "
        "revenue, account balance, nation name, address, phone, and comment, ordered by "
        "revenue descending.",
    12: "For ship modes MAIL and SHIP, count for orders received in 1994 how many lineitems "
        "were high priority (order priority '1-URGENT' or '2-HIGH') versus not, where the "
        "lineitem was committed before its receipt, shipped before commit, and received in "
        "1994. Group by ship mode.",
    14: "What percentage of the revenue (extended price times (1 minus discount)) from "
        "lineitems shipped in September 1995 came from promotional parts, i.e. parts whose "
        "type starts with 'PROMO'?",
}


def ensure_tpch_db(sf: float) -> str:
    """Generate (once) a TPC-H DuckDB file at the given scale factor; return its path."""
    import duckdb
    path = f"/tmp/tpch_sf{sf:g}.duckdb"
    if not os.path.exists(path):
        c = duckdb.connect(path)
        c.execute("INSTALL tpch; LOAD tpch;")
        t0 = time.time()
        c.execute(f"CALL dbgen(sf={sf})")
        print(f"[setup] generated TPC-H SF={sf:g} in {time.time()-t0:.1f}s "
              f"({c.execute('SELECT count(*) FROM lineitem').fetchone()[0]:,} lineitems)")
        c.close()
    return path


def ensure_connection(path: str) -> str:
    """Register (idempotently) an Aughor connection pointing at the TPC-H DB."""
    from aughor.db.registry import add_connection, list_connections
    name = f"tpch::{Path(path).stem}"
    for c in list_connections():
        if c.get("name") == name:
            return c.get("id")
    return add_connection(name=name, conn_type="duckdb", dsn=path, meta={})


def _norm_cells(rows) -> tuple[Counter, Counter]:
    """Split all result cells into a multiset of rounded numbers and a multiset of
    lowercased strings — lets us compare results regardless of column order/naming."""
    nums, strs = [], []
    for r in rows:
        for v in r:
            if v is None:
                continue
            try:
                nums.append(round(float(v), 2))
            except (ValueError, TypeError):
                strs.append(str(v).strip().lower())
    return Counter(nums), Counter(strs)


def _equiv(gen_rows, ref_rows) -> bool:
    """True if every numeric and string value in the OFFICIAL result is present in
    the generated result (generated ⊇ reference). Tolerates extra/renamed/reordered
    columns and helpful additions; catches missing or wrong values."""
    gn, gs = _norm_cells(gen_rows)
    rn, rs = _norm_cells(ref_rows)
    nums_ok = all(gn[k] >= v for k, v in rn.items())
    strs_ok = all(gs[k] >= v for k, v in rs.items())
    return nums_ok and strs_ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sf", type=float, default=1.0, help="TPC-H scale factor")
    ap.add_argument("--only", default="", help="comma list of query numbers, e.g. 1,3,6")
    ap.add_argument("--output", default=None)
    args = ap.parse_args()

    import duckdb
    from aughor.db.connection import open_connection_for
    from evals.run_golden import generate_sql_full_pipeline

    path = ensure_tpch_db(args.sf)
    cid = ensure_connection(path)

    wanted = [int(x) for x in args.only.split(",") if x.strip()] or sorted(QUESTIONS)
    db = open_connection_for(cid)

    # Reuse the Aughor connection's own DuckDB cursor for scoring — opening the
    # same file a second time fails with a config mismatch. tpch_queries() needs
    # the extension loaded in this session.
    raw = getattr(db, "_conn", None) or duckdb.connect(path, read_only=True)
    try:
        raw.execute("LOAD tpch")
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
            off_sql = raw.execute("SELECT query FROM tpch_queries() WHERE query_nr=?", [nr]).fetchone()[0]
            ref_rows = raw.execute(off_sql).fetchall()
            ok = _equiv(gen_rows, ref_rows)
            rec.update(verdict="CORRECT" if ok else "WRONG", error=None,
                       gen_row_count=len(gen_rows), ref_row_count=len(ref_rows))
        except Exception as e:
            rec.update(verdict="ERROR", error=str(e)[:200])
        rec["latency_s"] = round(time.time() - t0, 1)
        results.append(rec)
        print(f"  Q{nr:<2} {rec['verdict']:8} ({rec['latency_s']}s)  {q[:60]}…")
        if rec.get("error"):
            print(f"        ERROR: {rec['error']}")

    n = len(results)
    correct = sum(1 for r in results if r["verdict"] == "CORRECT")
    errors = sum(1 for r in results if r["verdict"] == "ERROR")
    print("\n" + "=" * 60)
    print(f" TPC-H SF={args.sf:g}  |  generator: {os.getenv('AUGHOR_CODER_MODEL','default')}")
    print(f" Correct (exec-validated): {correct}/{n}   Errors: {errors}")
    print("=" * 60)

    if args.output:
        json.dump({"results": results, "summary": {"total": n, "correct": correct, "errors": errors}},
                  open(args.output, "w"), indent=2, default=str)
        print(f"written to {args.output}")


if __name__ == "__main__":
    main()
