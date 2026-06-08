# Quality Sweep Report

Total cases: **14**
Flagged: **3**  ·  Clean: **11**

## Defect histogram
- **ASK_NOAVG**: 2
- **ERROR**: 1

## Flagged cases

### [beautycommerce] ask — What is the average order value?
- headline: Average order value across all non-cancelled, non-test, non-fraud orders
- sql: `SELECT 
  ROUND(SUM(oi.final_price_usd * oi.quantity) / NULLIF(COUNT(DISTINCT oi.order_id), 0), 2) AS average_order_value
FROM analytics.order_items oi
JOIN analytics.orders o ON oi.order_id = o.order_id
WHERE o.order_status NOT IN ('cancel`
  - ⚑ ASK_NOAVG: average asked but SQL has no AVG()

### [tpch_sf1] ask — What is the average order value?
- headline: Average order value for completed orders is $184,112.61
- sql: `SELECT 
  ROUND(SUM(o_totalprice) / NULLIF(COUNT(DISTINCT o_orderkey), 0), 2) AS average_order_value
FROM orders
WHERE o_orderstatus = 'F';`
  - ⚑ ASK_NOAVG: average asked but SQL has no AVG()

### [tpch_sf1] investigate — Where are we losing money?
- ERROR: `TimeoutError: timed out`
- headline: None
- confidence=None metric=None obs=None wf=None
