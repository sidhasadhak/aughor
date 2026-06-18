"""Verify the baked-in patterns/traps in the analytics warehouse actually materialised."""
import duckdb

c = duckdb.connect("data/beautycommerce_analytics.duckdb", read_only=True)


def show(title, sql):
    print(title)
    for r in c.execute(sql).fetchall():
        print("   ", r)
    print()


show("T3 refund rate by category (Fragrance = highest margin AND highest returns):", """
WITH oc AS (
  SELECT o.order_id, o.order_status,
    (SELECT p.category FROM analytics.order_items oi JOIN analytics.products p ON p.product_id=oi.product_id
     WHERE oi.order_id=o.order_id ORDER BY oi.order_item_id LIMIT 1) cat
  FROM analytics.orders o)
SELECT cat, COUNT(*) n,
  ROUND(100.0*COUNT(*) FILTER(WHERE order_status='refunded')/COUNT(*),1) refund_pct
FROM oc GROUP BY 1 ORDER BY refund_pct DESC""")

show("T2 conversion by traffic_source (orders / ALL carts) — TikTok low, Email high:", """
SELECT traffic_source, COUNT(*) carts, COUNT(*) FILTER(WHERE NOT abandoned) converted,
  ROUND(100.0*COUNT(*) FILTER(WHERE NOT abandoned)/COUNT(*),1) conv_pct
FROM analytics.carts GROUP BY 1 ORDER BY conv_pct DESC""")

show("P5/T5 payment success by method: first-attempt vs any-attempt per order:", """
SELECT payment_method,
  ROUND(100.0*COUNT(*) FILTER(WHERE attempt_no=1 AND success)/COUNT(*) FILTER(WHERE attempt_no=1),1) first_attempt_pct,
  ROUND(100.0*COUNT(DISTINCT CASE WHEN success THEN order_id END)/COUNT(DISTINCT order_id),1) any_attempt_pct
FROM analytics.payments GROUP BY 1 ORDER BY first_attempt_pct""")

show("P3 logistics-related refund share by warehouse (Riverside leads):", """
SELECT o.warehouse, COUNT(*) refunds,
  ROUND(100.0*COUNT(*) FILTER(WHERE r.logistics_related)/COUNT(*),1) logistics_pct
FROM analytics.refunds r JOIN analytics.orders o ON o.order_id=r.order_id
GROUP BY 1 ORDER BY logistics_pct DESC""")

show("refund reasons distribution:", """
SELECT refund_reason, COUNT(*) n FROM analytics.refunds GROUP BY 1 ORDER BY 2 DESC""")

show("T1 fan-out sanity: order_items per order (avg, max) — joining inflates order-level sums:", """
SELECT ROUND(AVG(items),2) avg_items, MAX(items) max_items
FROM (SELECT order_id, COUNT(*) items FROM analytics.order_items GROUP BY 1)""")

show("T4 attribution weights sum to 1.0 per order (should always be 1.0):", """
SELECT ROUND(MIN(w),3) min_w, ROUND(MAX(w),3) max_w
FROM (SELECT order_id, SUM(weight) w FROM analytics.attribution GROUP BY 1)""")

# P6 ROAS by channel, naive last-touch vs weighted, net of refunds
show("P6 ROAS by channel — last-touch revenue / spend (TikTok should look strong here):", """
WITH spend AS (SELECT channel, SUM(spend_usd) s FROM analytics.marketing_ledger GROUP BY 1),
rev AS (SELECT o.channel, SUM(i.revenue_net_usd) r
        FROM analytics.orders o JOIN analytics.invoices i ON i.order_id=o.order_id GROUP BY 1)
SELECT s.channel, ROUND(rev.r,0) last_touch_rev, ROUND(s.s,0) spend,
  ROUND(rev.r/s.s,2) roas
FROM spend s JOIN rev ON rev.channel=s.channel ORDER BY roas DESC""")

show("P6b ROAS net of refunds (TikTok should drop hardest):", """
WITH spend AS (SELECT channel, SUM(spend_usd) s FROM analytics.marketing_ledger GROUP BY 1),
net AS (
  SELECT o.channel,
    SUM(i.revenue_net_usd) - COALESCE(SUM(rf.refund_amount_usd),0) r
  FROM analytics.orders o JOIN analytics.invoices i ON i.order_id=o.order_id
  LEFT JOIN analytics.refunds rf ON rf.order_id=o.order_id GROUP BY 1)
SELECT s.channel, ROUND(net.r,0) net_rev, ROUND(s.s,0) spend, ROUND(net.r/s.s,2) net_roas
FROM spend s JOIN net ON net.channel=s.channel ORDER BY net_roas DESC""")

show("T6 degenerate columns — null share of gift_message and middle_name:", """
SELECT
  ROUND(100.0*COUNT(*) FILTER(WHERE gift_message IS NULL)/COUNT(*),1) gift_null_pct
FROM analytics.products""")
