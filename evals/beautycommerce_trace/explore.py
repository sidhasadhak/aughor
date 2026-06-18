"""Cold-trace exploratory battery — the analyst's working session.

Each block states the QUESTION, the TRAP (the naive SQL that gets it wrong), and the
CORRECT grain — then runs both so the difference is visible. This is the evidence the
trace narrates and the diff measures Aughor against.
"""
import duckdb

c = duckdb.connect("data/beautycommerce_analytics.duckdb", read_only=True)


def show(label, sql):
    print(f"### {label}")
    try:
        rows = c.execute(sql).fetchall()
        cols = [d[0] for d in c.description]
        print("   ", " | ".join(cols))
        for r in rows:
            print("   ", " | ".join(str(x) for x in r))
    except Exception as e:
        print("    ERROR:", e)
    print()


# A. Referential integrity / join graph -----------------------------------------------
print("========== A. JOIN GRAPH & REFERENTIAL INTEGRITY ==========\n")
show("A1 orphan order_items (→orders / →products) — expect 0/0", """
SELECT
  COUNT(*) FILTER (WHERE o.order_id IS NULL) AS items_wo_order,
  COUNT(*) FILTER (WHERE p.product_id IS NULL) AS items_wo_product
FROM analytics.order_items oi
LEFT JOIN analytics.orders o ON o.order_id = oi.order_id
LEFT JOIN analytics.products p ON p.product_id = oi.product_id""")

show("A2 cart→order linkage: carts, converted (non-abandoned), orders, 1:1?", """
SELECT
  (SELECT COUNT(*) FROM analytics.carts) carts,
  (SELECT COUNT(*) FROM analytics.carts WHERE NOT abandoned) not_abandoned,
  (SELECT COUNT(*) FROM analytics.orders) orders,
  (SELECT COUNT(DISTINCT cart_id) FROM analytics.orders) distinct_cart_on_order""")

show("A3 grain check: rows-per-order across child tables", """
SELECT 'order_items' tbl, ROUND(AVG(n),2) avg_per_order, MAX(n) max FROM (SELECT order_id, COUNT(*) n FROM analytics.order_items GROUP BY 1)
UNION ALL SELECT 'payments', ROUND(AVG(n),2), MAX(n) FROM (SELECT order_id, COUNT(*) n FROM analytics.payments GROUP BY 1)
UNION ALL SELECT 'invoices', ROUND(AVG(n),2), MAX(n) FROM (SELECT order_id, COUNT(*) n FROM analytics.invoices GROUP BY 1)
UNION ALL SELECT 'refunds', ROUND(AVG(n),2), MAX(n) FROM (SELECT order_id, COUNT(*) n FROM analytics.refunds GROUP BY 1)
UNION ALL SELECT 'attribution', ROUND(AVG(n),2), MAX(n) FROM (SELECT order_id, COUNT(*) n FROM analytics.attribution GROUP BY 1)""")

# C. Conversion (T2 bounded-rate) -----------------------------------------------------
print("========== C. CART→ORDER CONVERSION (T2 bounded-rate trap) ==========\n")
show("C1 TRAP: conversion = orders / NON-abandoned carts  → nonsense ~100%", """
SELECT traffic_source,
  ROUND(100.0 * COUNT(*) FILTER (WHERE NOT abandoned) / NULLIF(COUNT(*) FILTER (WHERE NOT abandoned),0),1) conv_pct_WRONG
FROM analytics.carts GROUP BY 1 ORDER BY 1""")

show("C1 CORRECT: conversion = orders / ALL carts (denominator = full population)", """
SELECT traffic_source,
  ROUND(100.0 * COUNT(*) FILTER (WHERE NOT abandoned) / COUNT(*),1) conv_pct
FROM analytics.carts GROUP BY 1 ORDER BY conv_pct DESC""")

# D. Gross margin (T1 fan-out + T3) ---------------------------------------------------
print("========== D. GROSS MARGIN (T1 fan-out trap) ==========\n")
show("D1 TRAP: margin from orders⋈items but summing an order-level number inflates", """
WITH j AS (
  SELECT o.order_id, i.revenue_net_usd, oi.line_cogs_usd
  FROM analytics.orders o
  JOIN analytics.invoices i ON i.order_id=o.order_id
  JOIN analytics.order_items oi ON oi.order_id=o.order_id)
SELECT ROUND(SUM(revenue_net_usd),0) revenue_DOUBLE_COUNTED FROM j""")

show("D1 CORRECT: revenue at item grain; invoice revenue summed once at order grain", """
SELECT
  (SELECT SUM(line_revenue_usd) FROM analytics.order_items) item_grain_revenue,
  (SELECT SUM(revenue_net_usd) FROM analytics.invoices) invoice_grain_revenue""")

show("D2 gross margin % by category (item grain, correct)", """
SELECT p.category,
  ROUND(SUM(oi.line_revenue_usd),0) revenue,
  ROUND(100.0*SUM(oi.line_revenue_usd - oi.line_cogs_usd)/SUM(oi.line_revenue_usd),1) margin_pct
FROM analytics.order_items oi JOIN analytics.products p ON p.product_id=oi.product_id
GROUP BY 1 ORDER BY margin_pct DESC""")

# E. Margin-leak cross-domain (T3) ----------------------------------------------------
print("========== E. MARGIN-LEAK: high margin AND high returns (T3 cross-domain) ==========\n")
show("E1 category: margin% AND refund-rate together → the leak is Fragrance", """
WITH cat_margin AS (
  SELECT p.category,
    ROUND(100.0*SUM(oi.line_revenue_usd-oi.line_cogs_usd)/SUM(oi.line_revenue_usd),1) margin_pct
  FROM analytics.order_items oi JOIN analytics.products p ON p.product_id=oi.product_id GROUP BY 1),
ord_cat AS (
  SELECT o.order_id, o.order_status,
    (SELECT p.category FROM analytics.order_items oi JOIN analytics.products p ON p.product_id=oi.product_id
     WHERE oi.order_id=o.order_id ORDER BY oi.order_item_id LIMIT 1) cat
  FROM analytics.orders o),
cat_refund AS (
  SELECT cat, ROUND(100.0*COUNT(*) FILTER(WHERE order_status='refunded')/COUNT(*),1) refund_pct
  FROM ord_cat GROUP BY 1)
SELECT m.category, m.margin_pct, r.refund_pct,
  CASE WHEN m.margin_pct>85 AND r.refund_pct>15 THEN '*** MARGIN LEAK ***' ELSE '' END flag
FROM cat_margin m JOIN cat_refund r ON r.cat=m.category ORDER BY m.margin_pct DESC""")

# F. AOV by loyalty (P1) --------------------------------------------------------------
print("========== F. AOV BY LOYALTY (P1, order grain) ==========\n")
show("F1 AOV = revenue / DISTINCT orders by loyalty tier", """
SELECT c.loyalty_tier,
  COUNT(DISTINCT o.order_id) orders,
  ROUND(SUM(i.revenue_net_usd)/COUNT(DISTINCT o.order_id),2) aov
FROM analytics.orders o
JOIN analytics.customers c ON c.customer_id=o.customer_id
JOIN analytics.invoices i ON i.order_id=o.order_id
GROUP BY 1 ORDER BY aov DESC""")

# G. Payment success (T5 retry grain) -------------------------------------------------
print("========== G. PAYMENT SUCCESS (T5 retry-grain trap) ==========\n")
show("G1 TRAP per-attempt vs CORRECT per-order (any successful attempt) by method", """
SELECT payment_method,
  ROUND(100.0*COUNT(*) FILTER(WHERE success)/COUNT(*),1) per_attempt_WRONG,
  ROUND(100.0*COUNT(DISTINCT CASE WHEN success THEN order_id END)/COUNT(DISTINCT order_id),1) per_order_CORRECT
FROM analytics.payments GROUP BY 1 ORDER BY per_order_CORRECT""")

# H. ROAS (T4 attribution) ------------------------------------------------------------
print("========== H. ROAS BY CHANNEL (T4 attribution model matters) ==========\n")
show("H1 last-touch vs weighted-attribution revenue per channel, net of refunds", """
WITH spend AS (SELECT channel, SUM(spend_usd) s FROM analytics.marketing_ledger GROUP BY 1),
last_touch AS (
  SELECT o.channel, SUM(i.revenue_net_usd) r
  FROM analytics.orders o JOIN analytics.invoices i ON i.order_id=o.order_id GROUP BY 1),
weighted AS (
  SELECT a.channel, SUM(i.revenue_net_usd * a.weight) r
  FROM analytics.attribution a JOIN analytics.invoices i ON i.order_id=a.order_id GROUP BY 1)
SELECT s.channel, ROUND(s.s,0) spend,
  ROUND(lt.r,0) last_touch_rev, ROUND(lt.r/s.s,2) last_touch_roas,
  ROUND(w.r,0) weighted_rev, ROUND(w.r/s.s,2) weighted_roas
FROM spend s
LEFT JOIN last_touch lt ON lt.channel=s.channel
LEFT JOIN weighted w ON w.channel=s.channel
ORDER BY weighted_roas DESC""")

# I. Refund reasons + logistics by warehouse (P3) -------------------------------------
print("========== I. REFUNDS: reason mix & logistics by warehouse (P3) ==========\n")
show("I1 logistics-related refund share by warehouse", """
SELECT o.warehouse, COUNT(*) refunds,
  ROUND(100.0*COUNT(*) FILTER(WHERE r.logistics_related)/COUNT(*),1) logistics_pct
FROM analytics.refunds r JOIN analytics.orders o ON o.order_id=r.order_id
GROUP BY 1 ORDER BY logistics_pct DESC""")

# J. Inventory (stockouts / overstock) ------------------------------------------------
print("========== J. INVENTORY: stockouts vs overstock ==========\n")
show("J1 stockout events (stock_level=0) and overstock by category", """
SELECT p.category,
  COUNT(*) FILTER (WHERE s.stock_level=0) stockout_snapshots,
  ROUND(AVG(s.stock_level),0) avg_stock
FROM analytics.inventory_snapshots s JOIN analytics.products p ON p.product_id=s.product_id
GROUP BY 1 ORDER BY avg_stock DESC""")

# K. Degenerate vs structural NULL ----------------------------------------------------
print("========== K. NULL SEMANTICS: noise vs structural ==========\n")
show("K1 shade NULL is STRUCTURAL (only Makeup has shade) — not noise", """
SELECT category,
  ROUND(100.0*COUNT(*) FILTER(WHERE shade IS NULL)/COUNT(*),0) shade_null_pct,
  COUNT(*) n FROM analytics.products GROUP BY 1 ORDER BY shade_null_pct""")
