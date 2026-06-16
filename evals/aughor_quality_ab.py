#!/usr/bin/env python3
"""Holistic agent-quality probe on Aughor's OWN connected databases.

Runs a fixed set of business questions through the FULL production chat agent
(generate_sql_full_pipeline → SQL + chart_type + headline + intent + approach),
executes the SQL, and records everything the user-facing answer depends on:
the query fired, the result shape the viz renders on, the chart choice, and the
synthesis (headline/intent/approach) — plus latency.

Used to A/B the CURRENT platform vs the session's IMPROVED engine: run once on
each (swap prompts.py + schema.py to compare), then diff/judge the outputs.

Usage:
  python evals/aughor_quality_ab.py --connection c1c664b0 --label improved --out a.json
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path

_REPO = Path(__file__).parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# Fixed business questions per connection — span easy → hard, exercise
# aggregation, time, ranking, multi-table joins, and ratios (viz + synthesis).
QUESTIONS = {
    "c1c664b0": [  # beautycommerce (analytics schema)
        "What is total revenue by product category?",
        "Show me the monthly revenue trend over the last year.",
        "Which 10 customers have the highest lifetime spend?",
        "What is the average order value by marketing channel?",
        "What is the repeat-purchase rate, and how does it vary by acquisition channel?",
        "Which campaigns have the best return on ad spend, and what share of total revenue do the top 5 drive?",
    ],
    "workspace": [
        "What are the key metrics in this workspace?",
        "Show the trend of the main metric over time.",
    ],
}


def run(connection_id: str, label: str, out: Path):
    from aughor.db.connection import open_connection_for
    from evals.run_golden import generate_sql_full_pipeline

    db = open_connection_for(connection_id)
    qs = QUESTIONS.get(connection_id, QUESTIONS["c1c664b0"])
    results = []
    for i, q in enumerate(qs, 1):
        t0 = time.monotonic()
        rec = {"question": q}
        try:
            sql, ans = generate_sql_full_pipeline(q, connection_id, db, temperature=0.0, return_answer=True)
            rec["gen_secs"] = round(time.monotonic() - t0, 1)
            rec["sql"] = sql
            rec["chart_type"] = getattr(ans, "chart_type", "")
            rec["headline"] = getattr(ans, "headline", "")
            rec["intent"] = getattr(ans, "intent", "")
            rec["approach"] = getattr(ans, "approach", [])
            # Execute the fired query — what the viz/synthesis actually renders on
            res = db.execute("__ab__", sql)
            rec["exec_error"] = res.error
            rec["row_count"] = getattr(res, "row_count", None)
            rec["columns"] = list(getattr(res, "columns", []) or [])[:12]
            rec["sample_rows"] = [list(r)[:12] for r in (getattr(res, "rows", []) or [])[:3]]
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"
            rec["gen_secs"] = round(time.monotonic() - t0, 1)
        print(f"  [{i}/{len(qs)}] {q[:55]} → "
              f"{'ERR' if rec.get('exec_error') or rec.get('error') else str(rec.get('row_count'))+' rows'}, "
              f"{rec.get('chart_type','?')}, {rec['gen_secs']}s", flush=True)
        results.append(rec)

    out.write_text(json.dumps({"label": label, "connection": connection_id, "results": results}, indent=2))
    ok = sum(1 for r in results if not r.get("exec_error") and not r.get("error"))
    tot = sum(r.get("gen_secs", 0) for r in results)
    print(f"\n{label}: {ok}/{len(qs)} executed clean · total {tot:.0f}s · → {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--connection", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    run(a.connection, a.label, a.out)


if __name__ == "__main__":
    main()
