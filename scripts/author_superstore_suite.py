"""Author the Superstore (8d36d4c2) ACCURACY suite — every case carries a reference SQL
that is executed against the live data before it is written, so a pass means "the right
numbers", not "the numbers reached before".

    AUGHOR_SYSTEM_DB=$PWD/data/system.db .venv/bin/python scripts/author_superstore_suite.py

Why this exists (2026-08-14): the only answer-quality suites target `workspace`, whose
schema context is 116,744 chars — past the 60k linker budget — so any small-schema flag
(`grounding.full_schema_first`) is INERT there and cannot be measured. Superstore is 3
tables / ~5k chars: the exact regime where "send the whole schema" vs "prune to top-k"
is a real question. Cases are chosen so pruning has something to lose: cross-table joins
(orders↔returns), the manager lookup with no shared key, and columns a keyword linker
would drop for a question that never names them.

Idempotent by name: re-running finds the existing suite, deletes its cases, re-adds.
The reference checker (`aughor.evals.targets.reference_checker`) is order-insensitive,
float-normalised and tolerant of extra columns, so a richer-but-correct answer passes.
"""
from __future__ import annotations

import os
import sys

if not os.environ.get("AUGHOR_SYSTEM_DB"):
    sys.exit("set AUGHOR_SYSTEM_DB (a bare script does not load conftest's isolation)")

from aughor.db.connection import open_connection_for  # noqa: E402
from aughor.evals import store  # noqa: E402

CONN = "8d36d4c2"
SUITE_NAME = "Superstore — accuracy (reference SQL, small schema)"
SUITE_DESC = (
    "Ground-truth suite on the Superstore demo (3 tables, ~5k-char schema). Every case "
    "declares expected.reference_sql executed against the live data; a pass is an "
    "execution-grounded results_match. Authored 2026-08-14 to unblock small-schema grids "
    "(grounding.full_schema_first). This suite MEASURES ACCURACY."
)

# (question, reference_sql, tags, accept_sql alternates)
CASES: list[tuple[str, str, list[str], list[str]]] = [
    # ── single-table aggregates ──────────────────────────────────────────────
    ("What is our total sales revenue?",
     "SELECT SUM(sales) AS revenue FROM orders", ["agg"], []),
    ("How many distinct orders have we shipped in total?",
     "SELECT COUNT(DISTINCT order_id) AS orders FROM orders", ["agg", "distinct"], []),
    ("What is the total profit by category?",
     "SELECT category, SUM(profit) AS profit FROM orders GROUP BY category", ["agg", "group"], []),
    ("Which region generates the most sales?",
     "SELECT region, SUM(sales) AS sales FROM orders GROUP BY region ORDER BY sales DESC LIMIT 1",
     ["agg", "rank"],
     ["SELECT region, SUM(sales) AS sales FROM orders GROUP BY region ORDER BY sales DESC"]),
    ("Show sales by customer segment.",
     "SELECT segment, SUM(sales) AS sales FROM orders GROUP BY segment", ["agg", "group"], []),
    ("What is the average discount by ship mode?",
     "SELECT ship_mode, AVG(discount) AS avg_discount FROM orders GROUP BY ship_mode",
     ["agg", "avg"], []),
    ("How many line items were sold in each sub-category?",
     "SELECT sub_category, COUNT(*) AS line_items FROM orders GROUP BY sub_category",
     ["agg", "group"], []),
    ("What is the total quantity sold in the Technology category?",
     "SELECT SUM(quantity) AS quantity FROM orders WHERE category = 'Technology'",
     ["agg", "filter"], []),
    # ── ranking / top-N ──────────────────────────────────────────────────────
    ("Who are the top 5 customers by total sales?",
     "SELECT customer_name, SUM(sales) AS sales FROM orders GROUP BY customer_name "
     "ORDER BY sales DESC LIMIT 5", ["rank", "topn"],
     ["SELECT customer_id, customer_name, SUM(sales) AS sales FROM orders "
      "GROUP BY customer_id, customer_name ORDER BY sales DESC LIMIT 5"]),
    ("Which 3 states have the lowest total profit?",
     "SELECT state, SUM(profit) AS profit FROM orders GROUP BY state ORDER BY profit ASC LIMIT 3",
     ["rank", "bottomn"], []),
    ("What are the 10 best-selling products by quantity?",
     "SELECT product_name, SUM(quantity) AS quantity FROM orders GROUP BY product_name "
     "ORDER BY quantity DESC LIMIT 10", ["rank", "topn"],
     ["SELECT product_id, product_name, SUM(quantity) AS quantity FROM orders "
      "GROUP BY product_id, product_name ORDER BY quantity DESC LIMIT 10"]),
    ("Which sub-category loses the most money?",
     "SELECT sub_category, SUM(profit) AS profit FROM orders GROUP BY sub_category "
     "ORDER BY profit ASC LIMIT 1", ["rank"],
     ["SELECT sub_category, SUM(profit) AS profit FROM orders GROUP BY sub_category "
      "ORDER BY profit ASC"]),
    # ── time ─────────────────────────────────────────────────────────────────
    ("What were total sales per year?",
     "SELECT EXTRACT(YEAR FROM order_date) AS year, SUM(sales) AS sales FROM orders "
     "GROUP BY 1 ORDER BY 1", ["time"], []),
    ("Show monthly sales for 2017.",
     "SELECT EXTRACT(MONTH FROM order_date) AS month, SUM(sales) AS sales FROM orders "
     "WHERE order_date >= '2017-01-01' AND order_date < '2018-01-01' GROUP BY 1 ORDER BY 1",
     ["time", "filter"],
     ["SELECT DATE_TRUNC('month', order_date) AS month, SUM(sales) AS sales FROM orders "
      "WHERE order_date >= '2017-01-01' AND order_date < '2018-01-01' GROUP BY 1 ORDER BY 1"]),
    ("How many orders were placed in Q4 2016?",
     "SELECT COUNT(DISTINCT order_id) AS orders FROM orders "
     "WHERE order_date >= '2016-10-01' AND order_date < '2017-01-01'", ["time", "distinct"], []),
    ("What is the average number of days between order date and ship date?",
     "SELECT AVG(ship_date - order_date) AS avg_days FROM orders", ["time", "avg"],
     ["SELECT AVG(DATEDIFF('day', order_date, ship_date)) AS avg_days FROM orders",
      "SELECT AVG(DATE_DIFF('day', order_date, ship_date)) AS avg_days FROM orders"]),
    # ── cross-table: orders ↔ returns (the join the pruner can lose) ─────────
    ("How many orders were returned?",
     "SELECT COUNT(DISTINCT o.order_id) AS returned_orders FROM orders o "
     "JOIN returns r ON o.order_id = r.order_id", ["join", "returns"],
     ["SELECT COUNT(DISTINCT order_id) AS returned_orders FROM returns"]),
    ("What is the total sales value of returned orders?",
     "SELECT SUM(o.sales) AS returned_sales FROM orders o JOIN returns r ON o.order_id = r.order_id",
     ["join", "returns"], []),
    ("Which category has the most returned orders?",
     "SELECT o.category, COUNT(DISTINCT o.order_id) AS returned_orders FROM orders o "
     "JOIN returns r ON o.order_id = r.order_id GROUP BY o.category "
     "ORDER BY returned_orders DESC LIMIT 1", ["join", "returns", "rank"],
     ["SELECT o.category, COUNT(DISTINCT o.order_id) AS returned_orders FROM orders o "
      "JOIN returns r ON o.order_id = r.order_id GROUP BY o.category ORDER BY returned_orders DESC"]),
    ("What is the return rate by region, as a share of distinct orders?",
     "SELECT o.region, COUNT(DISTINCT r.order_id) * 1.0 / COUNT(DISTINCT o.order_id) AS return_rate "
     "FROM orders o LEFT JOIN returns r ON o.order_id = r.order_id GROUP BY o.region",
     ["join", "returns", "ratio"], []),
    ("Show total sales for orders that were NOT returned, by segment.",
     "SELECT o.segment, SUM(o.sales) AS sales FROM orders o LEFT JOIN returns r "
     "ON o.order_id = r.order_id WHERE r.order_id IS NULL GROUP BY o.segment",
     ["join", "returns", "antijoin"],
     ["SELECT segment, SUM(sales) AS sales FROM orders WHERE order_id NOT IN "
      "(SELECT order_id FROM returns) GROUP BY segment"]),
    # ── cross-table: regional_managers (lookup a linker drops on 'manager' alone) ─
    ("Which regional manager is responsible for the most sales?",
     "SELECT m.manager, SUM(o.sales) AS sales FROM orders o JOIN regional_managers m "
     "ON o.region = m.region GROUP BY m.manager ORDER BY sales DESC LIMIT 1", ["join", "managers"],
     ["SELECT m.manager, SUM(o.sales) AS sales FROM orders o JOIN regional_managers m "
      "ON o.region = m.region GROUP BY m.manager ORDER BY sales DESC"]),
    ("Show total profit per regional manager.",
     "SELECT m.manager, SUM(o.profit) AS profit FROM orders o JOIN regional_managers m "
     "ON o.region = m.region GROUP BY m.manager", ["join", "managers"], []),
    ("How many returned orders fall under each regional manager?",
     "SELECT m.manager, COUNT(DISTINCT r.order_id) AS returned_orders FROM orders o "
     "JOIN returns r ON o.order_id = r.order_id JOIN regional_managers m ON o.region = m.region "
     "GROUP BY m.manager", ["join", "managers", "returns", "three_way"], []),
]


def main() -> int:
    db = open_connection_for(CONN)
    con = db._conn

    # Verify every reference (and alternate) runs and is non-empty BEFORE writing anything.
    bad: list[str] = []
    for q, ref, _tags, alts in CASES:
        for sql in [ref, *alts]:
            try:
                rows = con.execute(sql).fetchall()
            except Exception as exc:
                bad.append(f"{q!r}: {type(exc).__name__}: {exc}\n    {sql}")
                continue
            if not rows:
                bad.append(f"{q!r}: reference returned ZERO rows\n    {sql}")
    if bad:
        print("⛔ reference SQL problems — nothing written:\n" + "\n".join(bad))
        return 1

    existing = [s for s in store.list_suites(limit=200) if s.get("name") == SUITE_NAME]
    if existing:
        suite_id = existing[0]["id"]
        for c in store.list_cases(suite_id, limit=1000):
            store.delete_case(c["id"])
        print(f"reusing suite {suite_id} (cases cleared)")
    else:
        suite = store.create_suite(SUITE_NAME, description=SUITE_DESC,
                                   target="reference", connection_id=CONN)
        suite_id = suite["id"]
        print(f"created suite {suite_id}")

    n = store.add_cases(suite_id, [
        {"question": q, "artifact": ref,
         "expected": {"reference_sql": ref, "accept_sql": alts, "tables": sorted({
             t for t in ("orders", "returns", "regional_managers") if t in ref})},
         "tags": ["accuracy", "superstore", *tags]}
        for q, ref, tags, alts in CASES
    ])
    print(f"wrote {n} cases to suite {suite_id} on connection {CONN}")
    print(f"\nnext:\n  FLAG=grounding.full_schema_first SUITE={suite_id} CONNECTION_ID={CONN} "
          f"DEPTH=quick TEMPERATURE=0 REPLICATE=1 AUGHOR_FALLBACK_DISABLED=1 \\\n"
          f"    AUGHOR_LLM_RPM=16 AUGHOR_LLM_MAX_CONCURRENCY=2 "
          f".venv/bin/python -u scripts/flag_ab_grid.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
