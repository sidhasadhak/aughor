"""Seed the **BeautyCommerce** demo workspace — a mature, populated workspace for demos.

Unlike the bundled `samples` ecommerce DB (data only), this creates a *complete* workspace:
a registered connection, a richer beauty/cosmetics dataset, several governed metrics, a
Canvas with saved insights + a deep-analysis report, several saved Query-Builder entries, and
a Slack alert trigger. It's the "what a real, lived-in workspace looks like" demo.

Run once:  ``python -m aughor.samples.beautycommerce``  (or call ``seed_beautycommerce()``).
Idempotent: every step checks for an existing object by name/id and skips it, so re-running is
safe and never duplicates.

Dataset (schema ``beauty`` in data/beautycommerce.duckdb), all foreign keys consistent:
  products(120)  customers(600)  campaigns(12)  orders(6 000)  order_items(15 000)  reviews(3 500)
Baked-in patterns for the explorer to find: Gold/Platinum loyalty tiers carry a higher AOV;
Skincare/Fragrance dominate revenue; refunds cluster on a couple of channels.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

BEAUTY_PATH   = Path("data") / "beautycommerce.duckdb"
BEAUTY_SCHEMA = "beauty"
BEAUTY_NAME   = "BeautyCommerce"


# ── 1. Dataset ────────────────────────────────────────────────────────────────

def _seed_beauty_db(conn) -> None:  # noqa: ANN001
    s = BEAUTY_SCHEMA
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {s}")

    # products — beauty SKUs with category-correlated price/cost (margin signal)
    conn.execute(f"""
    CREATE TABLE {s}.products AS
    SELECT
        printf('P%04d', i) AS product_id,
        CASE i % 8
            WHEN 0 THEN 'Lumière'  WHEN 1 THEN 'Velvet'   WHEN 2 THEN 'Pure Glow'
            WHEN 3 THEN 'AuraBeauté' WHEN 4 THEN 'Noir'    WHEN 5 THEN 'Botanica'
            WHEN 6 THEN 'Hydra'     ELSE 'Éclat'
        END AS brand,
        CASE (i * 7) % 5
            WHEN 0 THEN 'Skincare' WHEN 1 THEN 'Makeup' WHEN 2 THEN 'Haircare'
            WHEN 3 THEN 'Fragrance' ELSE 'Tools'
        END AS category,
        CASE (i * 7) % 5
            WHEN 0 THEN 'Serum'      WHEN 1 THEN 'Foundation' WHEN 2 THEN 'Shampoo'
            WHEN 3 THEN 'Eau de Parfum' ELSE 'Brush Set'
        END || ' ' || CASE i % 4 WHEN 0 THEN 'Classic' WHEN 1 THEN 'Pro' WHEN 2 THEN 'Sensitive' ELSE 'Limited' END
            AS product_name,
        -- Fragrance + Skincare priced higher (margin pattern)
        ROUND((CASE (i * 7) % 5 WHEN 3 THEN 48 WHEN 0 THEN 32 WHEN 1 THEN 24 WHEN 2 THEN 14 ELSE 11 END
              + (i * 13) % 40)::NUMERIC, 2) AS price,
        ROUND((CASE (i * 7) % 5 WHEN 3 THEN 14 WHEN 0 THEN 10 WHEN 1 THEN 9 WHEN 2 THEN 6 ELSE 5 END
              + (i * 7) % 14)::NUMERIC, 2) AS unit_cost,
        CASE WHEN i % 3 = 0 THEN true ELSE false END AS is_organic,
        (i * 17) % 400 AS stock_quantity,
        (DATE '2022-06-01' + ((i * 9) % 600 || ' days')::INTERVAL)::DATE AS launch_date
    FROM range(1, 121) t(i)
    """)

    # customers — loyalty tier derived from id; skin type; country
    conn.execute(f"""
    CREATE TABLE {s}.customers AS
    SELECT
        printf('C%05d', i) AS customer_id,
        CASE i % 12
            WHEN 0 THEN 'Ava'   WHEN 1 THEN 'Mia'   WHEN 2 THEN 'Zoe'   WHEN 3 THEN 'Leah'
            WHEN 4 THEN 'Nora'  WHEN 5 THEN 'Ivy'   WHEN 6 THEN 'Ruby'  WHEN 7 THEN 'Maya'
            WHEN 8 THEN 'Sara'  WHEN 9 THEN 'Lena'  WHEN 10 THEN 'Emma' ELSE 'Aria'
        END || ' ' || CASE (i * 3) % 8
            WHEN 0 THEN 'Kim' WHEN 1 THEN 'Patel' WHEN 2 THEN 'Garcia' WHEN 3 THEN 'Chen'
            WHEN 4 THEN 'Silva' WHEN 5 THEN 'Khan' WHEN 6 THEN 'Rossi' ELSE 'Dubois'
        END AS full_name,
        'cust' || i || '@' || CASE i % 4 WHEN 0 THEN 'gmail.com' WHEN 1 THEN 'icloud.com'
            WHEN 2 THEN 'outlook.com' ELSE 'mail.com' END AS email,
        CASE i % 9
            WHEN 0 THEN 'New York' WHEN 1 THEN 'London' WHEN 2 THEN 'Paris' WHEN 3 THEN 'Milan'
            WHEN 4 THEN 'Seoul'    WHEN 5 THEN 'Dubai'  WHEN 6 THEN 'Sydney' WHEN 7 THEN 'Toronto'
            ELSE 'Singapore'
        END AS city,
        CASE i % 9 WHEN 0 THEN 'US' WHEN 1 THEN 'GB' WHEN 2 THEN 'FR' WHEN 3 THEN 'IT'
            WHEN 4 THEN 'KR' WHEN 5 THEN 'AE' WHEN 6 THEN 'AU' WHEN 7 THEN 'CA' ELSE 'SG' END AS country,
        CASE i % 5 WHEN 0 THEN 'Oily' WHEN 1 THEN 'Dry' WHEN 2 THEN 'Combination'
            WHEN 3 THEN 'Sensitive' ELSE 'Normal' END AS skin_type,
        CASE WHEN i % 20 = 0 THEN 'Platinum' WHEN i % 20 < 3 THEN 'Gold'
             WHEN i % 20 < 9 THEN 'Silver' ELSE 'Bronze' END AS loyalty_tier,
        CASE i % 4 WHEN 0 THEN '18-24' WHEN 1 THEN '25-34' WHEN 2 THEN '35-44' ELSE '45+' END AS age_group,
        CASE WHEN i % 7 = 0 THEN false ELSE true END AS marketing_opt_in,
        (DATE '2022-01-01' + ((i * 5) % 900 || ' days')::INTERVAL)::DATE AS signup_date
    FROM range(1, 601) t(i)
    """)

    # campaigns
    conn.execute(f"""
    CREATE TABLE {s}.campaigns AS
    SELECT
        printf('CMP%02d', i) AS campaign_id,
        CASE i % 6 WHEN 0 THEN 'Spring Glow' WHEN 1 THEN 'Summer Radiance' WHEN 2 THEN 'Holiday Edit'
            WHEN 3 THEN 'Clean Beauty' WHEN 4 THEN 'New You' ELSE 'VIP Rewards' END
            || ' ' || (2023 + i % 2)::VARCHAR AS campaign_name,
        CASE i % 3 WHEN 0 THEN 'email' WHEN 1 THEN 'paid_social' ELSE 'influencer' END AS channel,
        (DATE '2023-01-01' + ((i * 60) % 720 || ' days')::INTERVAL)::DATE AS start_date,
        (DATE '2023-01-01' + ((i * 60) % 720 + 30 || ' days')::INTERVAL)::DATE AS end_date,
        ROUND((5000 + (i * 1700) % 40000)::NUMERIC, 2) AS budget,
        ROUND((4200 + (i * 1500) % 38000)::NUMERIC, 2) AS spend,
        (5 + (i * 3) % 25) AS discount_pct
    FROM range(1, 13) t(i)
    """)

    # orders — customer assigned modularly; Gold/Platinum carry a higher basket (AOV pattern);
    # status mix with a ~7% refund tail; channel + campaign attribution
    conn.execute(f"""
    CREATE TABLE {s}.orders AS
    SELECT *, ROUND(subtotal - discount_amount, 2) AS total_amount
    FROM (
        SELECT
            printf('O%06d', i) AS order_id,
            printf('C%05d', cnum) AS customer_id,
            CASE
                WHEN (i * 3) % 100 < 4  THEN 'pending'
                WHEN (i * 3) % 100 < 10 THEN 'processing'
                WHEN (i * 3) % 100 < 24 THEN 'shipped'
                WHEN (i * 3) % 100 < 86 THEN 'delivered'
                WHEN (i * 3) % 100 < 93 THEN 'refunded'
                ELSE 'cancelled'
            END AS status,
            CASE WHEN cnum % 20 = 0 THEN 'app' WHEN cnum % 9 = 5 THEN 'store'
                 WHEN i % 3 = 0 THEN 'app' ELSE 'web' END AS channel,
            ROUND((CASE WHEN cnum % 20 < 3 THEN 95 ELSE 38 END + (i * 19.7) % 140)::NUMERIC, 2) AS subtotal,
            ROUND((CASE WHEN i % 4 = 0 THEN ((i * 7) % 25) ELSE 0 END)::NUMERIC, 2) AS discount_amount,
            (DATE '2023-01-01' + (i % 730 || ' days')::INTERVAL)::DATE AS order_date,
            CASE i % 5 WHEN 0 THEN 'card' WHEN 1 THEN 'apple_pay' WHEN 2 THEN 'paypal'
                WHEN 3 THEN 'klarna' ELSE 'card' END AS payment_method,
            CASE WHEN i % 4 = 0 THEN printf('CMP%02d', 1 + (i * 5) % 12) ELSE NULL END AS campaign_id
        FROM (SELECT i, 1 + (i * 7) % 600 AS cnum FROM range(1, 6001) t(i)) base
    )
    """)

    # order_items — reference real orders + products; price DERIVED from the product so
    # category price differences (Fragrance/Skincare priced higher) flow into category revenue
    conn.execute(f"""
    CREATE TABLE {s}.order_items AS
    SELECT
        gen.item_id, gen.order_id, gen.product_id, gen.quantity,
        p.price AS unit_price,
        ROUND(p.price * gen.quantity, 2) AS line_total
    FROM (
        SELECT i AS item_id,
               printf('O%06d', 1 + (i * 3) % 6000) AS order_id,
               printf('P%04d', 1 + (i * 11) % 120) AS product_id,
               1 + (i * 7) % 4 AS quantity
        FROM range(1, 15001) t(i)
    ) gen
    JOIN {s}.products p ON gen.product_id = p.product_id
    """)

    # reviews — reference real products + customers; rating-correlated text + verified flag
    conn.execute(f"""
    CREATE TABLE {s}.reviews AS
    SELECT
        i AS review_id,
        printf('P%04d', 1 + (i * 11) % 120) AS product_id,
        printf('C%05d', 1 + (i * 13) % 600) AS customer_id,
        1 + (i * 3) % 5 AS rating,
        CASE
            WHEN 1 + (i * 3) % 5 >= 4 THEN CASE i % 5
                WHEN 0 THEN 'My skin has never looked better!' WHEN 1 THEN 'Holy grail product'
                WHEN 2 THEN 'Gentle and effective' WHEN 3 THEN 'Worth every penny' ELSE 'Repurchasing for sure' END
            WHEN 1 + (i * 3) % 5 = 3 THEN CASE i % 3
                WHEN 0 THEN 'It''s fine, nothing wow' WHEN 1 THEN 'Decent but pricey' ELSE 'Average results' END
            ELSE CASE i % 4
                WHEN 0 THEN 'Broke me out' WHEN 1 THEN 'Scent is too strong'
                WHEN 2 THEN 'Did nothing for me' ELSE 'Returning it' END
        END AS review_text,
        CASE WHEN i % 6 = 0 THEN false ELSE true END AS verified_purchase,
        (i * 2) % 80 AS helpful_votes,
        (DATE '2023-02-01' + ((i * 2) % 700 || ' days')::INTERVAL)::DATE AS review_date
    FROM range(1, 3501) t(i)
    """)


def ensure_beauty_db() -> Path:
    """Create + seed beautycommerce.duckdb if its schema isn't there yet. Returns the path."""
    BEAUTY_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        import duckdb
    except ImportError:
        logger.warning("duckdb not installed — BeautyCommerce DB not created")
        return BEAUTY_PATH
    conn = duckdb.connect(str(BEAUTY_PATH))
    try:
        schemas = {r[0] for r in conn.execute(
            "SELECT schema_name FROM information_schema.schemata"
        ).fetchall()}
        if BEAUTY_SCHEMA not in schemas:
            logger.info("Seeding beautycommerce.duckdb — %s schema…", BEAUTY_SCHEMA)
            _seed_beauty_db(conn)
            logger.info("BeautyCommerce dataset ready.")
    finally:
        conn.close()
    return BEAUTY_PATH


# ── 2. Connection ─────────────────────────────────────────────────────────────

def _connection_id() -> str:
    """The BeautyCommerce connection id, creating the registry entry if absent."""
    from aughor.db.registry import list_connections, add_connection
    for c in list_connections():
        if c.get("name") == BEAUTY_NAME:
            return c["id"]
    return add_connection(BEAUTY_NAME, "duckdb", str(BEAUTY_PATH), {"schema_name": BEAUTY_SCHEMA})


# ── 3. Metrics ────────────────────────────────────────────────────────────────

def _seed_metrics() -> int:
    from aughor.semantic.metrics import MetricDefinition, save_metric
    # Namespaced names (the metric store is GLOBAL; `beauty_*` avoids clobbering any existing
    # metric like a generic `revenue`). Labels stay clean for display.
    metrics = [
        MetricDefinition(name="beauty_revenue", label="Revenue", sql="SUM(total_amount)",
                         tables=["beauty.orders"], dimensions=["channel", "status", "country", "order_date"],
                         filters=["status NOT IN ('cancelled')"], unit="$", owner="Revenue team",
                         caveats="Excludes cancelled orders; refunds counted at gross."),
        MetricDefinition(name="beauty_aov", label="Average Order Value",
                         sql="SUM(total_amount) / NULLIF(COUNT(DISTINCT order_id), 0)",
                         tables=["beauty.orders"], dimensions=["channel", "loyalty_tier"], unit="$",
                         owner="Revenue team", target_value=72.0, target_period="monthly"),
        MetricDefinition(name="beauty_refund_rate", label="Refund Rate",
                         sql="COUNT(*) FILTER (WHERE status = 'refunded') * 100.0 / NULLIF(COUNT(*), 0)",
                         tables=["beauty.orders"], dimensions=["channel", "country"], unit="%",
                         owner="Ops team", warning_threshold=8.0, critical_threshold=12.0,
                         caveats="Refunds are order-level, not line-level."),
        MetricDefinition(name="beauty_units_sold", label="Units Sold", sql="SUM(quantity)",
                         tables=["beauty.order_items"], dimensions=["product_id"], unit="units"),
        MetricDefinition(name="beauty_avg_rating", label="Average Review Rating", sql="AVG(rating)",
                         tables=["beauty.reviews"], dimensions=["product_id"], unit="stars",
                         owner="Product team", target_value=4.2),
    ]
    for m in metrics:
        save_metric(m)
    return len(metrics)


# ── 4. Canvas (insights + a deep-analysis report) ─────────────────────────────

def _seed_canvas(conn_id: str) -> int:
    from aughor.canvas.models import CanvasScope
    from aughor.canvas.store import list_canvases, create_canvas, create_artifact
    title = f"{BEAUTY_NAME} Analysis"
    existing = next((c for c in list_canvases() if c.name == title), None)
    if existing:
        return 0
    canvas = create_canvas(
        title, [CanvasScope(connection_id=conn_id, schema_name=BEAUTY_SCHEMA)],
        description="Lived-in analysis workspace for the BeautyCommerce demo store.",
    )
    artifacts = [
        ("insight", "Gold & Platinum customers punch above their weight",
         "Top loyalty tiers are ~15% of customers but a far larger share of revenue (higher AOV).",
         "SELECT c.loyalty_tier, COUNT(DISTINCT o.order_id) AS orders, "
         "ROUND(SUM(o.total_amount), 0) AS revenue, ROUND(AVG(o.total_amount), 2) AS aov "
         "FROM beauty.orders o JOIN beauty.customers c ON o.customer_id = c.customer_id "
         "GROUP BY c.loyalty_tier ORDER BY revenue DESC",
         "How does revenue and AOV split across loyalty tiers?"),
        ("insight", "Skincare & Fragrance lead category revenue",
         "Higher-priced Skincare and Fragrance SKUs drive the revenue mix versus Tools/Haircare.",
         "SELECT p.category, ROUND(SUM(oi.line_total), 0) AS revenue, SUM(oi.quantity) AS units "
         "FROM beauty.order_items oi JOIN beauty.products p ON oi.product_id = p.product_id "
         "GROUP BY p.category ORDER BY revenue DESC",
         "Which product categories drive the most revenue?"),
        ("report", "Refund-rate hotspots by channel",
         "Deep-analysis: where refunds concentrate and what it costs.",
         "SELECT channel, COUNT(*) AS orders, "
         "COUNT(*) FILTER (WHERE status = 'refunded') AS refunds, "
         "ROUND(COUNT(*) FILTER (WHERE status = 'refunded') * 100.0 / COUNT(*), 1) AS refund_rate_pct "
         "FROM beauty.orders GROUP BY channel ORDER BY refund_rate_pct DESC",
         "Which channels have the highest refund rate and why?"),
    ]
    for kind, t, desc, sql, q in artifacts:
        create_artifact(canvas.id, kind, t, description=desc, sql=sql, question=q)
    return len(artifacts)


# ── 5. Saved Query-Builder entries ────────────────────────────────────────────

def _seed_saved_queries(conn_id: str) -> int:
    from aughor.savedquery.store import list_saved_queries, create_saved_query
    have = {q.name for q in list_saved_queries(conn_id)}
    queries = [
        ("Monthly revenue trend",
         "SELECT date_trunc('month', order_date) AS month, ROUND(SUM(total_amount), 0) AS revenue "
         "FROM beauty.orders WHERE status <> 'cancelled' GROUP BY 1 ORDER BY 1"),
        ("Top 10 products by units sold",
         "SELECT p.product_name, p.category, SUM(oi.quantity) AS units, ROUND(SUM(oi.line_total),0) AS revenue "
         "FROM beauty.order_items oi JOIN beauty.products p ON oi.product_id = p.product_id "
         "GROUP BY 1,2 ORDER BY units DESC LIMIT 10"),
        ("Refund rate by channel",
         "SELECT channel, ROUND(COUNT(*) FILTER (WHERE status='refunded')*100.0/COUNT(*),1) AS refund_rate_pct "
         "FROM beauty.orders GROUP BY 1 ORDER BY 2 DESC"),
        ("New vs returning revenue by month",
         "WITH firsts AS (SELECT customer_id, MIN(order_date) AS first_dt FROM beauty.orders GROUP BY 1) "
         "SELECT date_trunc('month', o.order_date) AS month, "
         "CASE WHEN o.order_date = f.first_dt THEN 'new' ELSE 'returning' END AS cohort, "
         "ROUND(SUM(o.total_amount),0) AS revenue "
         "FROM beauty.orders o JOIN firsts f ON o.customer_id = f.customer_id GROUP BY 1,2 ORDER BY 1,2"),
    ]
    n = 0
    for name, sql in queries:
        if name not in have:
            create_saved_query(conn_id, name, sql=sql)
            n += 1
    return n


# ── 6. Slack alert trigger ────────────────────────────────────────────────────

def _seed_slack_trigger() -> int:
    from aughor.actions.models import ActionTrigger
    from aughor.actions.store import list_triggers, save_trigger
    tid = "beautycommerce-slack"
    if any(t.id == tid for t in list_triggers()):
        return 0
    save_trigger(ActionTrigger(
        id=tid, name="BeautyCommerce Alerts", type="slack",
        # placeholder webhook — replace with a real Slack incoming-webhook URL; stored encrypted
        url="https://hooks.slack.com/services/T00000000/B00000000/REPLACE_WITH_REAL_WEBHOOK",
        channel="#beauty-alerts", enabled=False,
    ))
    return 1


# ── Orchestrator ──────────────────────────────────────────────────────────────

def seed_beautycommerce(*, with_slack: bool = True) -> dict:
    """Create the full BeautyCommerce demo workspace. Idempotent. Returns a summary."""
    ensure_beauty_db()
    conn_id = _connection_id()
    summary = {
        "connection_id": conn_id,
        "metrics": _seed_metrics(),
        "canvas_artifacts": _seed_canvas(conn_id),
        "saved_queries": _seed_saved_queries(conn_id),
        "slack_triggers": _seed_slack_trigger() if with_slack else 0,
        "duckdb": str(BEAUTY_PATH),
    }
    logger.info("BeautyCommerce workspace seeded: %s", summary)
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    import json as _json
    print(_json.dumps(seed_beautycommerce(), indent=2))
