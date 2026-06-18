"""Build a richer **BeautyCommerce 'analytics'** warehouse for the intelligence-trace run.

Unlike the simple 6-table `beauty` seed (aughor/samples/beautycommerce.py), this builds a
realistic, multi-domain DTC-beauty warehouse — orders/items with COGS, carts with an
abandoned flag, payments with retries, refunds with reasons, multi-touch attribution,
marketing spend, invoices, and inventory snapshots/movements — into schema ``analytics`` of
``data/beautycommerce_analytics.duckdb``.

Everything is deterministic (range() + modular arithmetic, no RNG) so the run is reproducible.

It bakes in real *patterns* an analyst should find AND a few deliberate *schema-reasoning
traps* that exercise Aughor's SQL-trust guards — these are what make the cold-trace-vs-pipeline
diff interesting:

  TRAPS
  T1  fan-out:        orders 1→N order_items. Summing order-level money after joining items
                      over-counts; rate denominators double-count. (chasm/fan-out guard)
  T2  bounded rate:   carts.abandoned. Cart→order conversion = orders / ALL carts. Filtering the
                      denominator to abandoned=false yields a nonsense ~100%. (bounded-rate guard)
  T3  margin-leak:    Fragrance SKUs carry >90% gross margin AND the highest refund rate
                      (allergic reaction / scent too strong) — the "high margin but bleeding
                      returns" question that needs an AND across two domains.
  T4  multi-touch:    attribution.weight sums to 1 per order across channels. Last-touch ROAS
                      over-credits one channel; correct ROAS allocates revenue by weight.
  T5  retry grain:    payments has attempt_no. "Payment success rate" per-attempt != per-order;
                      klarna fails first attempt often but usually succeeds on retry.
  T6  degenerate col: products.gift_message is ~95% NULL; customers.middle_name all NULL —
                      should be recognised as non-signal, not surfaced as an insight.

  PATTERNS
  P1  Gold/Platinum loyalty tiers carry a higher AOV.
  P2  Skincare & Fragrance dominate revenue; Tools/Haircare trail.
  P3  Logistics-related refunds (damaged/late/wrong-item) cluster on the 'Riverside' warehouse.
  P4  TikTok drives high cart volume but low conversion; Email converts best.
  P5  klarna/paypal have lower payment success than card/apple_pay.
  P6  TikTok ROAS is negative once refunds are netted out, despite high last-touch revenue.

Run:  ``.venv/bin/python -m evals.beautycommerce_trace.build_warehouse``
Idempotent: drops & recreates the ``analytics`` schema each run.
"""
from __future__ import annotations

from pathlib import Path

import duckdb

DB_PATH = Path("data") / "beautycommerce_analytics.duckdb"
SCHEMA = "analytics"


def _build(conn: duckdb.DuckDBPyConnection) -> None:
    s = SCHEMA
    conn.execute(f"DROP SCHEMA IF EXISTS {s} CASCADE")
    conn.execute(f"CREATE SCHEMA {s}")

    # ── products (150) — category-correlated price/COGS; Fragrance ≈ luxury margin ──────
    # gift_message ~95% NULL (T6). shade only populated for Makeup (NULLs are meaningful).
    conn.execute(f"""
    CREATE TABLE {s}.products AS
    SELECT
        printf('SKU%04d', i) AS product_id,
        CASE i % 8
            WHEN 0 THEN 'Lumiere' WHEN 1 THEN 'Velvet'  WHEN 2 THEN 'Pure Glow'
            WHEN 3 THEN 'AuraBeaute' WHEN 4 THEN 'Noir'  WHEN 5 THEN 'Botanica'
            WHEN 6 THEN 'Hydra'   ELSE 'Eclat' END AS brand,
        cat.category,
        CASE cat.category
            WHEN 'Skincare'  THEN 'Serum'   WHEN 'Makeup'   THEN 'Foundation'
            WHEN 'Haircare'  THEN 'Shampoo' WHEN 'Fragrance' THEN 'Eau de Parfum'
            ELSE 'Brush Set' END
          || ' ' || CASE i % 4 WHEN 0 THEN 'Classic' WHEN 1 THEN 'Pro' WHEN 2 THEN 'Sensitive' ELSE 'Limited' END
          AS product_name,
        CASE WHEN cat.category = 'Makeup'
             THEN CASE i % 6 WHEN 0 THEN 'Porcelain' WHEN 1 THEN 'Ivory' WHEN 2 THEN 'Sand'
                             WHEN 3 THEN 'Honey' WHEN 4 THEN 'Caramel' ELSE 'Espresso' END
             ELSE NULL END AS shade,
        -- Fragrance & Skincare priced high; Fragrance COGS very low ⇒ >90% margin (T3)
        ROUND(cat.base_price + (i * 13) % 40, 2) AS list_price_usd,
        ROUND(cat.base_cogs  + (i * 5)  % 6,  2) AS unit_cogs_usd,
        (i % 3 = 0) AS is_organic,
        -- gift_message: mostly NULL noise column (T6)
        CASE WHEN i % 20 = 0 THEN 'Happy Birthday!' ELSE NULL END AS gift_message,
        (DATE '2022-06-01' + ((i * 9) % 600 || ' days')::INTERVAL)::DATE AS launch_date
    FROM range(1, 151) t(i)
    CROSS JOIN LATERAL (
        SELECT CASE (i * 7) % 5
                 WHEN 0 THEN 'Skincare' WHEN 1 THEN 'Makeup' WHEN 2 THEN 'Haircare'
                 WHEN 3 THEN 'Fragrance' ELSE 'Tools' END AS category,
               CASE (i * 7) % 5
                 WHEN 0 THEN 46 WHEN 1 THEN 30 WHEN 2 THEN 16 WHEN 3 THEN 88 ELSE 12 END AS base_price,
               CASE (i * 7) % 5
                 WHEN 0 THEN 12 WHEN 1 THEN 11 WHEN 2 THEN 7  WHEN 3 THEN 6  ELSE 5  END AS base_cogs
    ) cat
    """)

    # ── customers (800) — loyalty tier (P1), acquisition channel, middle_name all-NULL (T6) ──
    conn.execute(f"""
    CREATE TABLE {s}.customers AS
    SELECT
        printf('CUST%05d', i) AS customer_id,
        CASE i % 12 WHEN 0 THEN 'Ava' WHEN 1 THEN 'Mia' WHEN 2 THEN 'Zoe' WHEN 3 THEN 'Leah'
            WHEN 4 THEN 'Nora' WHEN 5 THEN 'Ivy' WHEN 6 THEN 'Ruby' WHEN 7 THEN 'Maya'
            WHEN 8 THEN 'Sara' WHEN 9 THEN 'Lena' WHEN 10 THEN 'Emma' ELSE 'Aria' END
          || ' ' || CASE (i * 3) % 8 WHEN 0 THEN 'Kim' WHEN 1 THEN 'Patel' WHEN 2 THEN 'Garcia'
            WHEN 3 THEN 'Chen' WHEN 4 THEN 'Silva' WHEN 5 THEN 'Khan' WHEN 6 THEN 'Rossi' ELSE 'Dubois' END
          AS full_name,
        NULL AS middle_name,                              -- all-NULL noise column (T6)
        'cust' || i || '@' || CASE i % 4 WHEN 0 THEN 'gmail.com' WHEN 1 THEN 'icloud.com'
            WHEN 2 THEN 'outlook.com' ELSE 'mail.com' END AS email,
        CASE i % 9 WHEN 0 THEN 'US' WHEN 1 THEN 'GB' WHEN 2 THEN 'FR' WHEN 3 THEN 'IT'
            WHEN 4 THEN 'KR' WHEN 5 THEN 'AE' WHEN 6 THEN 'AU' WHEN 7 THEN 'CA' ELSE 'SG' END AS country,
        CASE i % 5 WHEN 0 THEN 'Oily' WHEN 1 THEN 'Dry' WHEN 2 THEN 'Combination'
            WHEN 3 THEN 'Sensitive' ELSE 'Normal' END AS skin_type,
        CASE WHEN i % 25 = 0 THEN 'Platinum' WHEN i % 25 < 4 THEN 'Gold'
             WHEN i % 25 < 11 THEN 'Silver' ELSE 'Bronze' END AS loyalty_tier,
        CASE i % 4 WHEN 0 THEN '18-24' WHEN 1 THEN '25-34' WHEN 2 THEN '35-44' ELSE '45+' END AS age_group,
        CASE i % 6 WHEN 0 THEN 'Meta' WHEN 1 THEN 'TikTok' WHEN 2 THEN 'Google'
            WHEN 3 THEN 'Email' WHEN 4 THEN 'Organic' ELSE 'Referral' END AS acquisition_channel,
        (i % 7 <> 0) AS marketing_opt_in,
        (DATE '2022-01-01' + ((i * 5) % 900 || ' days')::INTERVAL)::DATE AS signup_date
    FROM range(1, 801) t(i)
    """)

    # ── carts (9000) — abandoned flag varies by traffic_source (P4 + T2) ────────────────
    # Abandonment rate: TikTok ~78%, Meta ~55%, Google ~48%, Organic ~42%, Email ~32%, Direct ~38%.
    conn.execute(f"""
    CREATE TABLE {s}.carts AS
    SELECT
        printf('CART%06d', i) AS cart_id,
        printf('CUST%05d', 1 + (i * 7) % 800) AS customer_id,
        src.traffic_source,
        CASE WHEN i % 2 = 0 THEN 'mobile' ELSE 'desktop' END AS device,
        -- per-source abandonment threshold on a 0-99 hash bucket
        ((i * 31) % 100) < src.abandon_pct AS abandoned,
        (DATE '2023-01-01' + (i % 730 || ' days')::INTERVAL)::DATE AS created_date
    FROM range(1, 9001) t(i)
    CROSS JOIN LATERAL (
        SELECT CASE i % 6 WHEN 0 THEN 'TikTok' WHEN 1 THEN 'Meta' WHEN 2 THEN 'Google'
                          WHEN 3 THEN 'Email' WHEN 4 THEN 'Organic' ELSE 'Direct' END AS traffic_source,
               CASE i % 6 WHEN 0 THEN 78 WHEN 1 THEN 55 WHEN 2 THEN 48
                          WHEN 3 THEN 32 WHEN 4 THEN 42 ELSE 38 END AS abandon_pct
    ) src
    """)

    # ── orders — exactly the non-abandoned carts convert (clean conversion semantics, T2) ──
    # Gold/Platinum carry a higher subtotal (P1). ~7% refunded tail. channel = cart source.
    conn.execute(f"""
    CREATE TABLE {s}.orders AS
    SELECT
        printf('ORD%06d', row_number() OVER (ORDER BY c.cart_id)) AS order_id,
        c.cart_id,
        c.customer_id,
        c.traffic_source AS channel,
        cust.loyalty_tier,
        c.created_date AS order_date,
        CASE
            WHEN (rn * 3) % 100 < 4  THEN 'pending'
            WHEN (rn * 3) % 100 < 10 THEN 'processing'
            WHEN (rn * 3) % 100 < 24 THEN 'shipped'
            WHEN (rn * 3) % 100 < 86 THEN 'delivered'
            WHEN (rn * 3) % 100 < 93 THEN 'refunded'
            ELSE 'cancelled' END AS order_status,
        CASE rn % 5 WHEN 0 THEN 'card' WHEN 1 THEN 'apple_pay' WHEN 2 THEN 'paypal'
            WHEN 3 THEN 'klarna' ELSE 'card' END AS payment_method,
        -- fulfilment warehouse; Riverside is the logistics-trouble site (P3)
        CASE rn % 4 WHEN 0 THEN 'Riverside' WHEN 1 THEN 'Hillcrest' WHEN 2 THEN 'Bayview' ELSE 'Lakeside' END AS warehouse
    FROM (SELECT cart_id, customer_id, traffic_source, created_date,
                 row_number() OVER (ORDER BY cart_id) AS rn
          FROM {s}.carts WHERE NOT abandoned) c
    JOIN {s}.customers cust ON cust.customer_id = c.customer_id
    """)

    # ── order_items (1→N per order; T1 fan-out) — price/COGS DERIVED from product ─────────
    # Gold/Platinum buy more units (P1); each item carries its own revenue & COGS.
    conn.execute(f"""
    CREATE TABLE {s}.order_items AS
    WITH ord AS (
        SELECT order_id, loyalty_tier, channel,
               row_number() OVER (ORDER BY order_id) AS rn,
               COUNT(*) OVER () AS n FROM {s}.orders
    ), gen AS (
        SELECT i AS item_id,
               -- multiplier coprime to the order count ⇒ every order receives items
               1 + (i * 13) % (SELECT COUNT(*) FROM {s}.orders) AS rn,
               printf('SKU%04d', 1 + (i * 11) % 150) AS product_id,
               1 + (i * 3) % 4 AS quantity
        FROM range(1, 16001) t(i)
    )
    SELECT
        printf('OI%06d', gen.item_id) AS order_item_id,
        ord.order_id,
        gen.product_id,
        -- Gold/Platinum baskets a bit larger (P1)
        gen.quantity + CASE WHEN ord.loyalty_tier IN ('Gold','Platinum') THEN 1 ELSE 0 END AS quantity,
        p.list_price_usd AS unit_price_usd,
        p.unit_cogs_usd,
        ord.channel AS traffic_source,
        ROUND(p.list_price_usd * (gen.quantity + CASE WHEN ord.loyalty_tier IN ('Gold','Platinum') THEN 1 ELSE 0 END), 2) AS line_revenue_usd,
        ROUND(p.unit_cogs_usd  * (gen.quantity + CASE WHEN ord.loyalty_tier IN ('Gold','Platinum') THEN 1 ELSE 0 END), 2) AS line_cogs_usd
    FROM gen
    JOIN ord ON ord.rn = gen.rn
    JOIN {s}.products p ON p.product_id = gen.product_id
    """)

    # ── T3 correlation: Fragrance orders refund at a much higher rate ────────────────────
    # Built here (after items exist, before refunds reads status) so the margin-leak is real:
    # Fragrance is BOTH the highest-margin AND the highest-return category — the cross-domain
    # "high margin but bleeding returns" signal a good analyst must catch.
    conn.execute(f"""
    UPDATE {s}.orders SET order_status = 'refunded'
    FROM (
        SELECT oi.order_id,
               (ARRAY_AGG(p.category ORDER BY oi.order_item_id))[1] AS top_cat
        FROM {s}.order_items oi JOIN {s}.products p ON p.product_id = oi.product_id
        GROUP BY oi.order_id
    ) d
    WHERE {s}.orders.order_id = d.order_id
      AND d.top_cat = 'Fragrance'
      AND {s}.orders.order_status = 'delivered'
      AND CAST(substr({s}.orders.order_id, 4) AS INT) % 100 < 22
    """)

    # ── invoices (1:1 order) — net revenue rolled up from items + tax/shipping ───────────
    conn.execute(f"""
    CREATE TABLE {s}.invoices AS
    SELECT
        printf('INV%06d', row_number() OVER (ORDER BY o.order_id)) AS invoice_id,
        o.order_id,
        ROUND(SUM(oi.line_revenue_usd), 2) AS revenue_net_usd,
        ROUND(SUM(oi.line_revenue_usd) * 0.08, 2) AS tax_usd,
        ROUND(4.99 + (length(o.order_id) % 3), 2) AS shipping_usd,
        o.order_date AS invoice_date
    FROM {s}.orders o
    JOIN {s}.order_items oi ON oi.order_id = o.order_id
    GROUP BY o.order_id, o.order_date
    """)

    # ── payments — 1 per order, + a retry row for klarna/paypal first-attempt failures (T5/P5) ──
    # First-attempt success: card ~98%, apple_pay ~96%, paypal ~88%, klarna ~80%.
    conn.execute(f"""
    CREATE TABLE {s}.payments AS
    WITH base AS (
        SELECT o.order_id, o.payment_method,
               row_number() OVER (ORDER BY o.order_id) AS rn,
               COALESCE(inv.revenue_net_usd, 0) AS amount
        FROM {s}.orders o LEFT JOIN {s}.invoices inv ON inv.order_id = o.order_id
    ),
    attempt1 AS (
        SELECT order_id, payment_method, 1 AS attempt_no, amount,
               ((rn * 17) % 100) >= CASE payment_method
                   WHEN 'card' THEN 2 WHEN 'apple_pay' THEN 4
                   WHEN 'paypal' THEN 12 ELSE 20 END AS success,
               (rn % 200 = 0) AS fraud_flag, rn
        FROM base
    ),
    -- failed first attempts retry; retry succeeds ~92% of the time
    attempt2 AS (
        SELECT order_id, payment_method, 2 AS attempt_no, amount,
               ((rn * 29) % 100) >= 8 AS success, false AS fraud_flag, rn
        FROM attempt1 WHERE NOT success
    )
    SELECT printf('PAY%07d', row_number() OVER (ORDER BY order_id, attempt_no)) AS payment_id,
           order_id, payment_method, attempt_no, amount AS amount_usd, success, fraud_flag
    FROM (SELECT order_id, payment_method, attempt_no, amount, success, fraud_flag FROM attempt1
          UNION ALL
          SELECT order_id, payment_method, attempt_no, amount, success, fraud_flag FROM attempt2)
    """)

    # ── refunds — only for refunded orders; reason biased by category + warehouse (P3 + T3) ──
    # Fragrance ⇒ 'Allergic reaction'/'Scent too strong' (high-margin returns, T3);
    # Makeup ⇒ 'Shade mismatch'; Riverside warehouse ⇒ logistics reasons (P3).
    conn.execute(f"""
    CREATE TABLE {s}.refunds AS
    WITH refunded AS (
        SELECT o.order_id, o.order_date, o.warehouse,
               row_number() OVER (ORDER BY o.order_id) AS rn,
               -- dominant category of the order (first item)
               (SELECT p.category FROM {s}.order_items oi
                  JOIN {s}.products p ON p.product_id = oi.product_id
                 WHERE oi.order_id = o.order_id ORDER BY oi.order_item_id LIMIT 1) AS top_category,
               (SELECT SUM(oi.line_revenue_usd) FROM {s}.order_items oi WHERE oi.order_id = o.order_id) AS order_revenue
        FROM {s}.orders o WHERE o.order_status = 'refunded'
    )
    SELECT
        printf('RF%05d', rn) AS refund_id,
        order_id,
        reason.refund_reason,
        reason.logistics_related,
        ROUND(COALESCE(order_revenue, 30) * (0.6 + (rn % 5) * 0.1), 2) AS refund_amount_usd,
        (order_date + ((rn % 14) + 3 || ' days')::INTERVAL)::DATE AS refund_completed_date
    FROM refunded
    CROSS JOIN LATERAL (
        SELECT * FROM (
            SELECT CASE
                -- Riverside drives logistics refunds (P3)
                WHEN warehouse = 'Riverside' AND rn % 2 = 0 THEN 'Damaged in transit'
                WHEN warehouse = 'Riverside' AND rn % 3 = 0 THEN 'Late delivery'
                WHEN top_category = 'Fragrance' AND rn % 2 = 0 THEN 'Allergic reaction'
                WHEN top_category = 'Fragrance' THEN 'Scent too strong'
                WHEN top_category = 'Makeup' THEN 'Shade mismatch'
                WHEN rn % 5 = 0 THEN 'Wrong item shipped'
                ELSE 'Changed mind' END AS refund_reason,
                CASE
                WHEN warehouse = 'Riverside' AND (rn % 2 = 0 OR rn % 3 = 0) THEN true
                WHEN rn % 5 = 0 THEN true        -- wrong item is logistics
                ELSE false END AS logistics_related
        )
    ) reason
    """)

    # ── campaigns ───────────────────────────────────────────────────────────────────────
    conn.execute(f"""
    CREATE TABLE {s}.campaigns AS
    SELECT printf('CMP%02d', i) AS campaign_id,
        CASE i % 6 WHEN 0 THEN 'Spring Glow' WHEN 1 THEN 'Summer Radiance' WHEN 2 THEN 'Holiday Edit'
            WHEN 3 THEN 'Clean Beauty' WHEN 4 THEN 'New You' ELSE 'VIP Rewards' END
          || ' ' || (2023 + i % 2)::VARCHAR AS campaign_name,
        CASE i % 4 WHEN 0 THEN 'Meta' WHEN 1 THEN 'TikTok' WHEN 2 THEN 'Google' ELSE 'Email' END AS channel,
        (DATE '2023-01-01' + ((i * 45) % 700 || ' days')::INTERVAL)::DATE AS start_date,
        (DATE '2023-01-01' + ((i * 45) % 700 + 30 || ' days')::INTERVAL)::DATE AS end_date,
        ROUND(5000 + (i * 1700) % 40000, 2) AS budget_usd
    FROM range(1, 17) t(i)
    """)

    # ── marketing_ledger — channel × day spend; TikTok overspends (P6) ───────────────────
    conn.execute(f"""
    CREATE TABLE {s}.marketing_ledger AS
    SELECT
        printf('ML%06d', row_number() OVER ()) AS ledger_id,
        ch.channel,
        (DATE '2023-01-01' + (d || ' days')::INTERVAL)::DATE AS spend_date,
        ROUND(ch.daily_base + (d * 7) % 300, 2) AS spend_usd,
        (ch.daily_base * 40 + (d * 53) % 5000)::BIGINT AS impressions,
        (ch.daily_base + (d * 11) % 200)::BIGINT AS clicks
    FROM range(0, 365) g(d)
    CROSS JOIN (VALUES
        ('TikTok', 900), ('Meta', 650), ('Google', 500), ('Email', 80)
    ) AS ch(channel, daily_base)
    """)

    # ── attribution — multi-touch weights sum to 1 per order (T4) ────────────────────────
    # ~50% of orders are single-touch (weight 1.0); the rest split last/first touch 0.6/0.4.
    conn.execute(f"""
    CREATE TABLE {s}.attribution AS
    WITH o AS (
        SELECT order_id, channel AS last_touch,
               row_number() OVER (ORDER BY order_id) AS rn
        FROM {s}.orders
    )
    -- last touch
    SELECT order_id, last_touch AS channel,
           CASE WHEN rn % 2 = 0 THEN 1.0 ELSE 0.6 END AS weight
    FROM o
    UNION ALL
    -- first touch (only multi-touch orders)
    SELECT order_id,
           CASE rn % 4 WHEN 0 THEN 'Google' WHEN 1 THEN 'Meta' WHEN 2 THEN 'TikTok' ELSE 'Email' END AS channel,
           0.4 AS weight
    FROM o WHERE rn % 2 = 1
    """)

    # ── inventory_snapshots — product × month; hero SKUs stock out, slow movers overstock ──
    conn.execute(f"""
    CREATE TABLE {s}.inventory_snapshots AS
    SELECT
        (DATE '2023-01-01' + (m || ' months')::INTERVAL)::DATE AS snapshot_date,
        p.product_id,
        wh.warehouse,
        -- hero SKUs (id ending 1) run low/stock out; slow movers (Tools) pile up
        CASE
            WHEN right(p.product_id, 1) = '1' THEN GREATEST(0, 12 - (m * 3) % 20)
            WHEN p.category = 'Tools' THEN 400 + (m * 17) % 200
            ELSE 80 + (m * 23) % 150 END AS stock_level
    FROM {s}.products p
    CROSS JOIN (VALUES ('Riverside'), ('Hillcrest'), ('Bayview')) AS wh(warehouse)
    CROSS JOIN range(0, 12) g(m)
    """)

    # ── inventory_movements — inbound/outbound/adjustment per product ─────────────────────
    conn.execute(f"""
    CREATE TABLE {s}.inventory_movements AS
    SELECT
        printf('MV%07d', i) AS movement_id,
        printf('SKU%04d', 1 + (i * 11) % 150) AS product_id,
        CASE i % 3 WHEN 0 THEN 'Riverside' WHEN 1 THEN 'Hillcrest' ELSE 'Bayview' END AS warehouse,
        CASE i % 5 WHEN 0 THEN 'inbound' WHEN 4 THEN 'adjustment' ELSE 'outbound' END AS movement_type,
        CASE WHEN i % 5 = 0 THEN 50 + (i * 7) % 200
             WHEN i % 5 = 4 THEN -((i * 3) % 10)
             ELSE -(1 + (i * 5) % 30) END AS quantity,
        (DATE '2023-01-01' + ((i * 13) % 730 || ' days')::INTERVAL)::DATE AS movement_date
    FROM range(1, 8001) t(i)
    """)


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(DB_PATH))
    try:
        _build(conn)
        print(f"Built {SCHEMA} schema in {DB_PATH}\n")
        tables = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            f"WHERE table_schema = '{SCHEMA}' ORDER BY table_name"
        ).fetchall()
        for (t,) in tables:
            n = conn.execute(f"SELECT COUNT(*) FROM {SCHEMA}.{t}").fetchone()[0]
            print(f"  {SCHEMA}.{t:<22} {n:>7,} rows")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
