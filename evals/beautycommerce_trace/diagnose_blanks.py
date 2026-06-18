"""Root-cause: are the blanked value_sql / key_question_sql empty because the AUDIT
over-blanks correct SQL, or because GENERATION produced broken SQL?

Decisive test: feed the OBVIOUS CORRECT SQL (validated by the cold trace) through Aughor's
own audit functions. PASS ⇒ data+audit are fine, the blank is a generation failure with no
fallback. FAIL ⇒ the audit itself is the problem.
"""
from dotenv import load_dotenv
load_dotenv(".env")

from aughor.db.connection import open_connection_for
from aughor.profile import store as pstore
from aughor.profile.validate import audit_value_sql, audit_chart_sql, audit_finding_sql
from aughor.tools.schema import _parse_schema_tables

CID = "8090c60f"
SCHEMA = "analytics"
conn = open_connection_for(CID)
schema = conn.get_schema()
table_cols = _parse_schema_tables(schema)

# correct value_sql for the metrics Aughor blanked (from the cold trace)
VALUE_SQL = {
    "Repeat Purchase Rate (ratio 0-1)":
        "SELECT COUNT(*) FILTER (WHERE oc > 1) * 1.0 / NULLIF(COUNT(*),0) AS repeat_rate "
        "FROM (SELECT customer_id, COUNT(*) oc FROM analytics.orders GROUP BY 1)",
    "Refund Rate by revenue (percent 0-100)":
        "SELECT (SELECT SUM(refund_amount_usd) FROM analytics.refunds) * 100.0 / "
        "NULLIF((SELECT SUM(revenue_net_usd) FROM analytics.invoices),0) AS refund_rate_pct",
    "Inventory Turnover (ratio 0-inf)":
        "SELECT (SELECT SUM(quantity) FROM analytics.order_items) * 1.0 / "
        "NULLIF((SELECT AVG(stock_level) FROM analytics.inventory_snapshots),0) AS turnover",
}
CHART_SQL = {
    "Channel Contribution weighted (USD series)":
        "SELECT a.channel, ROUND(SUM(i.revenue_net_usd * a.weight),0) rev "
        "FROM analytics.attribution a JOIN analytics.invoices i ON i.order_id=a.order_id "
        "GROUP BY 1 ORDER BY 2 DESC",
}
FINDING_SQL = {
    "Q2 top-5 refund reasons (logistics vs product)":
        "SELECT refund_reason, COUNT(*) n, BOOL_OR(logistics_related) any_logistics "
        "FROM analytics.refunds GROUP BY 1 ORDER BY 2 DESC LIMIT 5",
    "Q3 gross-margin trend (last 6 months)":
        "SELECT date_trunc('month',o.order_date) m, "
        "ROUND(100.0*SUM(oi.line_revenue_usd-oi.line_cogs_usd)/SUM(oi.line_revenue_usd),1) margin_pct "
        "FROM analytics.order_items oi JOIN analytics.orders o ON o.order_id=oi.order_id "
        "GROUP BY 1 ORDER BY 1 DESC LIMIT 6",
    "Q5 mobile vs desktop abandonment":
        "SELECT device, ROUND(100.0*COUNT(*) FILTER(WHERE abandoned)/COUNT(*),1) abandon_pct "
        "FROM analytics.carts GROUP BY 1",
    "Q7 cart abandonment by traffic source":
        "SELECT traffic_source, ROUND(100.0*COUNT(*) FILTER(WHERE abandoned)/COUNT(*),1) abandon_pct "
        "FROM analytics.carts GROUP BY 1 ORDER BY 2 DESC",
    "Q8 refund rate by warehouse":
        "SELECT o.warehouse, ROUND(100.0*COUNT(DISTINCT r.order_id)/COUNT(DISTINCT o.order_id),2) refund_pct "
        "FROM analytics.orders o LEFT JOIN analytics.refunds r ON r.order_id=o.order_id "
        "GROUP BY 1 ORDER BY 2 DESC",
}

print("=== VALUE_SQL (scalar) — Aughor left these EMPTY ===")
for label, sql in VALUE_SQL.items():
    unit = "ratio 0-1" if "ratio 0-1" in label else ("percent 0-100" if "percent" in label else "ratio 0-∞")
    ok, reason = audit_value_sql(sql, table_cols, conn, unit)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}  {('' if ok else '— '+reason)}")

print("\n=== CHART_SQL (series) — Aughor left this EMPTY ===")
for label, sql in CHART_SQL.items():
    ok, reason = audit_chart_sql(sql, table_cols, conn)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}  {('' if ok else '— '+reason)}")

print("\n=== FINDING_SQL (key questions) — Aughor left these EMPTY ===")
for label, sql in FINDING_SQL.items():
    ok, reason = audit_finding_sql(sql, table_cols, conn)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}  {('' if ok else '— '+reason)}")
