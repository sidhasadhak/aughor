"""F2 regression: the cardinality-aware chasm guard must
  (a) STOP flagging the correct weighted-attribution chart (attribution ⋈ 1:1 invoices), and
  (b) STILL flag the genuine 3-satellite chasm (attribution ⋈ invoices ⋈ order_items).
"""
from dotenv import load_dotenv
load_dotenv(".env")

from aughor.db.connection import open_connection_for
from aughor.profile.validate import audit_chart_sql, _make_uniqueness_oracle
from aughor.sql.fanout import sum_over_chasm_fanout
from aughor.tools.schema import _parse_schema_tables

conn = open_connection_for("8090c60f")
table_cols = _parse_schema_tables(conn.get_schema())
uniq = _make_uniqueness_oracle(conn, table_cols)

# (a) CORRECT — fact (attribution, many) ⋈ dimension (invoices, 1:1) — must PASS now
correct = ("SELECT a.channel, ROUND(SUM(i.revenue_net_usd * a.weight),0) rev "
           "FROM analytics.attribution a JOIN analytics.invoices i ON i.order_id=a.order_id "
           "GROUP BY 1 ORDER BY 2 DESC")

# (b) GENUINE chasm — TWO facts (attribution + order_items) of one hub — must still FAIL
genuine = ("SELECT a.channel, SUM(i.revenue_net_usd * a.weight) rev, SUM(oi.line_revenue_usd) items_rev "
           "FROM analytics.attribution a "
           "JOIN analytics.invoices i ON i.order_id=a.order_id "
           "JOIN analytics.order_items oi ON oi.order_id=a.order_id "
           "GROUP BY 1")

print("is_unique_on(invoices, order_id)   =", uniq("invoices", "order_id"), "(expect True → dimension)")
print("is_unique_on(attribution, order_id)=", uniq("attribution", "order_id"), "(expect False → satellite)")
print("is_unique_on(order_items, order_id)=", uniq("order_items", "order_id"), "(expect False → satellite)")
print()

# direct guard check (with vs without the oracle)
print("WITHOUT oracle (old behaviour):")
print("  correct  →", "FLAGGED" if sum_over_chasm_fanout(correct, table_cols) else "ok")
print("  genuine  →", "FLAGGED" if sum_over_chasm_fanout(genuine, table_cols) else "ok")
print("WITH oracle (fixed):")
print("  correct  →", "FLAGGED" if sum_over_chasm_fanout(correct, table_cols, is_unique_on=uniq) else "ok (PASS)")
print("  genuine  →", "FLAGGED (caught)" if sum_over_chasm_fanout(genuine, table_cols, is_unique_on=uniq) else "ok")
print()

# full audit path (what the pipeline actually calls)
ok_c, why_c = audit_chart_sql(correct, table_cols, conn)
ok_g, why_g = audit_chart_sql(genuine, table_cols, conn)
print(f"audit_chart_sql correct → {'PASS' if ok_c else 'FAIL: '+why_c}")
print(f"audit_chart_sql genuine → {'PASS (BAD!)' if ok_g else 'FAIL (correctly blocked): '+why_g[:80]}")
