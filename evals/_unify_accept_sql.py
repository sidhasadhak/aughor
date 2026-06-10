#!/usr/bin/env python3
"""UNIFY — make the golden scorer convention-neutral on the gross/net choice.

The #13b deep-test proved most of FULL's apparent regression was the
ex-cancelled REVENUE CONVENTION, not capability: the pipeline (driven by the
registered `revenue` metric, data/metrics.json) computes net-of-cancelled
revenue, while the golden references were authored GROSS. On a question that
does NOT specify a status filter ("what is total revenue"), both gross and net
are defensible — penalising the model for the more-correct net answer was the
confound, and the old accept_sql only carried GROSS line_total alts, so FULL's
NET answers matched nothing (metric-alt hits = 0).

This registers, for each revenue question whose gross/net convention is
UNSPECIFIED, the net-of-cancelled variant of its own reference as an accepted
alternative — at identical column shape. The scorer takes MAX over
{reference} ∪ accept_sql, so a correct answer in either convention scores full.

Status-SEMANTIC questions are deliberately left untouched — there the filter is
the question, not a free convention:
  sql006 (delivered only), sql014 (delivered vs cancelled), sql025 (% refunded).

Idempotent + validated: every variant is executed against `samples` and must
return a non-empty, numerically-distinct-or-equal result before being written;
the script aborts on any broken variant rather than poison the dataset.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_REPO = Path(__file__).parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from aughor.db.connection import open_connection_for

DATASET = _REPO / "evals" / "golden_sql_expanded.jsonl"

# Status-semantic questions — the filter IS the question. Never neutralise.
FROZEN = {"sql006", "sql014", "sql025"}

# How to derive the net-of-cancelled variant from a reference, per shape.
# Each entry: id -> list of net variants (validated below). We hand-write these
# rather than regex-inject a WHERE clause, because correct placement (pre vs
# post GROUP BY, inside a JOIN, inside a CTE) is shape-specific and a wrong
# auto-insert would silently change the result.
NET_VARIANTS: dict[str, list[str]] = {
    # order-grain total_amount → exclude cancelled
    "sql004": [
        "SELECT ROUND(SUM(total_amount), 2) AS total_revenue FROM ecommerce.orders WHERE status <> 'cancelled'",
        "SELECT ROUND(SUM(total_amount), 2) AS total_revenue FROM ecommerce.orders WHERE status NOT IN ('cancelled','refunded')",
    ],
    # AOV — gross vs net barely differ here, but encode both so it's neutral
    "sql002": [
        "SELECT ROUND(AVG(total_amount), 2) AS average_order_value FROM ecommerce.orders WHERE status <> 'cancelled'",
    ],
    # customer spend — net of cancelled
    "sql010": [
        "SELECT customer_id, ROUND(SUM(total_amount), 2) AS total_spent FROM ecommerce.orders WHERE status <> 'cancelled' GROUP BY customer_id ORDER BY total_spent DESC LIMIT 5",
    ],
    # highest-value orders — exclude cancelled
    "sql029": [
        "SELECT order_id, total_amount FROM ecommerce.orders WHERE status <> 'cancelled' ORDER BY total_amount DESC LIMIT 10",
    ],
}


def main() -> int:
    rows = [json.loads(l) for l in open(DATASET) if l.strip()]
    by_id = {r["id"]: r for r in rows}

    db = open_connection_for("samples")
    conn = db._conn

    def runs(sql: str):
        try:
            conn.execute(sql)
            return conn.fetchall(), None
        except Exception as e:
            return None, str(e)

    added = 0
    for qid, variants in NET_VARIANTS.items():
        if qid in FROZEN:
            print(f"SKIP {qid}: status-semantic (frozen)")
            continue
        rec = by_id.get(qid)
        if rec is None:
            print(f"WARN {qid}: not in dataset")
            continue
        existing = list(rec.get("accept_sql") or [])
        for v in variants:
            res, err = runs(v)
            if err is not None:
                print(f"ABORT {qid}: net variant failed to execute: {err}\n  {v}")
                db.close()
                return 1
            if not res:
                print(f"ABORT {qid}: net variant returned 0 rows:\n  {v}")
                db.close()
                return 1
            if v not in existing:
                existing.append(v)
                added += 1
        rec["accept_sql"] = existing

    db.close()

    # Re-emit the dataset in original order.
    with open(DATASET, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    total_alts = sum(len(r.get("accept_sql") or []) for r in rows)
    print(f"\nUNIFY: added {added} net-of-cancelled accept_sql variants; "
          f"{total_alts} total alternatives across "
          f"{sum(1 for r in rows if r.get('accept_sql'))} questions.")
    print(f"Frozen (status-semantic, untouched): {sorted(FROZEN)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
