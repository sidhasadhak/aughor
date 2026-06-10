#!/usr/bin/env python3
"""Attach metric-aware `accept_sql` alternatives to the golden dataset (#13b).

The golden set spells "revenue" inconsistently: order-grain questions use
SUM(orders.total_amount) while category/product-grain questions use
SUM(order_items.line_total). Both are defensible revenue definitions, and on the
sample data they disagree ~4.3x. So whichever the model picks, it was scored
"wrong" on ~half the revenue questions — the #13 confound.

This script registers, for each ORDER-GRAIN revenue question, the equally-valid
SUM(order_items.line_total) computation as an accepted alternative reference
(`accept_sql`), at identical column shape. The scorer (`score_single`) takes the
best match across {reference_sql} ∪ accept_sql, so a correct answer using the
other canonical revenue definition is no longer penalised.

NOT touched: category/product-grain revenue (sql009/013/020/026/036 — only
line_total is expressible there, so it is unambiguous) and AOV questions
(AVG(total_amount) is canonical per the platform's own per-grain guard).

Idempotent: re-running overwrites accept_sql for the listed ids only. Validates
every alternative executes against `samples` before writing; aborts otherwise.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from aughor.db.connection import open_connection_for

DATASET = _REPO_ROOT / "evals" / "golden_sql_expanded.jsonl"

# id -> list of equally-valid alternative reference SQLs (order-grain revenue
# computed via order_items.line_total, matching the primary reference's shape).
ACCEPT_SQL: dict[str, list[str]] = {
    "sql004": [
        "SELECT ROUND(SUM(line_total), 2) AS total_revenue FROM ecommerce.order_items"
    ],
    "sql007": [
        "SELECT DATE_TRUNC('month', o.order_date) AS month, ROUND(SUM(oi.line_total), 2) AS total_revenue "
        "FROM ecommerce.orders o JOIN ecommerce.order_items oi ON o.order_id = oi.order_id "
        "WHERE o.order_date >= '2024-01-01' AND o.order_date < '2025-01-01' "
        "GROUP BY DATE_TRUNC('month', o.order_date) ORDER BY month"
    ],
    "sql008": [
        "SELECT o.payment_method, ROUND(SUM(oi.line_total), 2) AS total_revenue "
        "FROM ecommerce.orders o JOIN ecommerce.order_items oi ON o.order_id = oi.order_id "
        "GROUP BY o.payment_method ORDER BY total_revenue DESC LIMIT 1"
    ],
    "sql015": [
        "WITH monthly AS (SELECT DATE_TRUNC('month', o.order_date) AS month, SUM(oi.line_total) AS revenue "
        "FROM ecommerce.orders o JOIN ecommerce.order_items oi ON o.order_id = oi.order_id "
        "GROUP BY DATE_TRUNC('month', o.order_date)) "
        "SELECT month, revenue, LAG(revenue) OVER (ORDER BY month) AS prev_month_revenue, "
        "ROUND((revenue - LAG(revenue) OVER (ORDER BY month)) * 100.0 / "
        "NULLIF(LAG(revenue) OVER (ORDER BY month), 0), 2) AS mom_change_pct "
        "FROM monthly ORDER BY month DESC LIMIT 1"
    ],
    "sql032": [
        "SELECT c.country, COUNT(DISTINCT o.order_id) AS order_count, ROUND(SUM(oi.line_total), 2) AS total_revenue "
        "FROM ecommerce.customers c JOIN ecommerce.orders o ON c.customer_id = o.customer_id "
        "JOIN ecommerce.order_items oi ON o.order_id = oi.order_id "
        "GROUP BY c.country ORDER BY total_revenue DESC"
    ],
    "sql041": [
        "SELECT CASE WHEN c.signup_date >= '2024-01-01' THEN 'new' ELSE 'old' END AS customer_type, "
        "ROUND(SUM(oi.line_total), 2) AS total_revenue, COUNT(DISTINCT o.order_id) AS order_count "
        "FROM ecommerce.customers c JOIN ecommerce.orders o ON c.customer_id = o.customer_id "
        "JOIN ecommerce.order_items oi ON o.order_id = oi.order_id "
        "GROUP BY CASE WHEN c.signup_date >= '2024-01-01' THEN 'new' ELSE 'old' END ORDER BY total_revenue DESC"
    ],
    "sql043": [
        "SELECT ROUND(SUM(oi.line_total), 2) AS total_revenue "
        "FROM ecommerce.customers c JOIN ecommerce.orders o ON c.customer_id = o.customer_id "
        "JOIN ecommerce.order_items oi ON o.order_id = oi.order_id WHERE c.country = 'BR'"
    ],
    "sql053": [
        "SELECT DATE_TRUNC('month', o.order_date) AS month, c.customer_id, c.full_name, "
        "ROUND(SUM(oi.line_total), 2) AS revenue "
        "FROM ecommerce.orders o JOIN ecommerce.customers c ON o.customer_id = c.customer_id "
        "JOIN ecommerce.order_items oi ON o.order_id = oi.order_id "
        "WHERE o.order_date >= '2024-01-01' AND o.order_date < '2025-01-01' "
        "GROUP BY DATE_TRUNC('month', o.order_date), c.customer_id, c.full_name ORDER BY month, revenue DESC"
    ],
}


def main() -> int:
    db = open_connection_for("samples")
    conn = getattr(db, "_conn", None)

    # 1) Validate every alternative executes and report its shape.
    print("Validating accept_sql alternatives against `samples`:")
    ok = True
    for sid, alts in ACCEPT_SQL.items():
        for j, sql in enumerate(alts):
            try:
                conn.execute(sql)
                rows = conn.fetchall()
                cols = [d[0] for d in conn.description] if conn.description else []
                print(f"  {sid}[{j}]: OK  rows={len(rows)} cols={cols}")
            except Exception as e:
                ok = False
                print(f"  {sid}[{j}]: FAIL  {e}")
    if not ok:
        print("\nAborting — fix the failing alternatives before writing.")
        db.close()
        return 1

    # 2) Attach and rewrite the dataset (preserving order + all other fields).
    records = [json.loads(l) for l in open(DATASET) if l.strip()]
    n_attached = 0
    for rec in records:
        if rec["id"] in ACCEPT_SQL:
            rec["accept_sql"] = ACCEPT_SQL[rec["id"]]
            n_attached += 1
        elif "accept_sql" in rec and rec["id"] not in ACCEPT_SQL:
            # leave any pre-existing alternatives on other ids untouched
            pass
    with open(DATASET, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")

    db.close()
    print(f"\nAttached accept_sql to {n_attached} records → {DATASET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
