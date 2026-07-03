"""
Create and seed the bundled samples DuckDB database.

Called once at API startup via ensure_samples_db(). Safe to call multiple
times — checks for existing schema before creating anything.

Schema layout
─────────────
ecommerce
  customers   (500 rows)   — customer_id, full_name, email, city, country,
                             signup_date, lifetime_orders, lifetime_spend
  products    (150 rows)   — product_id, product_name, category, price,
                             stock_quantity, is_out_of_stock
  orders      (5 000 rows) — order_id, customer_id, status, total_amount,
                             order_date, shipped_at, delivered_at,
                             payment_method, item_count
  order_items (12 000 rows) — item_id, order_id, product_id, quantity,
                              unit_price, line_total
  reviews     (3 000 rows) — review_id, order_id, customer_id, rating,
                             review_text, review_date
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SAMPLES_PATH = Path("data") / "samples.duckdb"
SAMPLES_ID   = "samples"
# The builtin "Fixture DB (demo)" connection (registry.BUILTIN_ID) points here.
FIXTURE_PATH = Path(__file__).parent.parent.parent / "data" / "aughor.duckdb"


def ensure_fixture_db() -> Path:
    """Guarantee the builtin ``fixture`` connection's DB (``data/aughor.duckdb``)
    exists and is openable.

    That file is gitignored and nothing seeds it, so a fresh install — or a clean
    CI checkout — otherwise has a BROKEN builtin connection: opening a missing file
    read-only raises ``IOException``. We only guarantee an openable (empty) DB; the
    seeded ecommerce demo lives in the separate ``samples`` connection. Idempotent.
    """
    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if FIXTURE_PATH.exists():
        return FIXTURE_PATH
    try:
        import duckdb
        conn = duckdb.connect(str(FIXTURE_PATH))  # read-write open materializes the file
        conn.close()
        logger.info("Created empty fixture DB at %s", FIXTURE_PATH)
    except Exception as exc:
        logger.warning("Failed to create fixture DB: %s", exc)
    return FIXTURE_PATH


# ── Public entry point ────────────────────────────────────────────────────────

def ensure_samples_db() -> Path:
    """Create + seed samples.duckdb if it doesn't exist yet. Returns its path."""
    SAMPLES_PATH.parent.mkdir(parents=True, exist_ok=True)

    try:
        import duckdb
    except ImportError:
        logger.warning("duckdb not installed — samples DB not created")
        return SAMPLES_PATH

    conn = duckdb.connect(str(SAMPLES_PATH))
    try:
        existing = {
            r[0]
            for r in conn.execute(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name NOT IN ('information_schema', 'main', 'temp', 'pg_catalog')"
            ).fetchall()
        }
        if "ecommerce" not in existing:
            logger.info("Seeding samples.duckdb — ecommerce schema…")
            _seed_ecommerce(conn)
            logger.info("Samples DB ready.")
    except Exception as exc:
        logger.warning("Failed to seed samples DB: %s", exc)
    finally:
        conn.close()

    return SAMPLES_PATH


# ── Schema seed ───────────────────────────────────────────────────────────────

def _seed_ecommerce(conn) -> None:  # noqa: ANN001
    conn.execute("CREATE SCHEMA IF NOT EXISTS ecommerce")

    # ── customers ────────────────────────────────────────────────────────────
    conn.execute("""
    CREATE TABLE ecommerce.customers AS
    SELECT
        printf('C%05d', i)  AS customer_id,
        CASE i % 20
            WHEN 0  THEN 'Alice'   WHEN 1  THEN 'Bob'    WHEN 2  THEN 'Carol'
            WHEN 3  THEN 'David'   WHEN 4  THEN 'Eve'    WHEN 5  THEN 'Frank'
            WHEN 6  THEN 'Grace'   WHEN 7  THEN 'Henry'  WHEN 8  THEN 'Iris'
            WHEN 9  THEN 'James'   WHEN 10 THEN 'Kate'   WHEN 11 THEN 'Liam'
            WHEN 12 THEN 'Mia'     WHEN 13 THEN 'Noah'   WHEN 14 THEN 'Olivia'
            WHEN 15 THEN 'Paul'    WHEN 16 THEN 'Quinn'  WHEN 17 THEN 'Ruby'
            WHEN 18 THEN 'Sam'     ELSE     'Tina'
        END || ' ' || CASE (i * 3) % 10
            WHEN 0 THEN 'Smith'   WHEN 1 THEN 'Jones'  WHEN 2 THEN 'Brown'
            WHEN 3 THEN 'Taylor'  WHEN 4 THEN 'Wilson' WHEN 5 THEN 'Davis'
            WHEN 6 THEN 'Clark'   WHEN 7 THEN 'Lewis'  WHEN 8 THEN 'Hall'
            ELSE 'Young'
        END  AS full_name,
        'user' || i || '@' || CASE i % 5
            WHEN 0 THEN 'gmail.com'   WHEN 1 THEN 'yahoo.com'
            WHEN 2 THEN 'outlook.com' WHEN 3 THEN 'example.com'
            ELSE 'company.io'
        END  AS email,
        CASE i % 10
            WHEN 0 THEN 'New York'    WHEN 1 THEN 'London'
            WHEN 2 THEN 'Paris'       WHEN 3 THEN 'Berlin'
            WHEN 4 THEN 'Tokyo'       WHEN 5 THEN 'Sydney'
            WHEN 6 THEN 'Toronto'     WHEN 7 THEN 'Mumbai'
            WHEN 8 THEN 'Sao Paulo'   ELSE 'Lagos'
        END  AS city,
        CASE i % 10
            WHEN 0 THEN 'US' WHEN 1 THEN 'GB' WHEN 2 THEN 'FR'
            WHEN 3 THEN 'DE' WHEN 4 THEN 'JP' WHEN 5 THEN 'AU'
            WHEN 6 THEN 'CA' WHEN 7 THEN 'IN' WHEN 8 THEN 'BR'
            ELSE 'NG'
        END  AS country,
        (DATE '2020-01-01' + (i * 3 || ' days')::INTERVAL)::DATE  AS signup_date,
        (i * 13) % 50                                               AS lifetime_orders,
        ROUND(((i * 37.5) % 9850 + 10)::NUMERIC, 2)               AS lifetime_spend
    FROM range(1, 501) t(i)
    """)

    # ── products ─────────────────────────────────────────────────────────────
    conn.execute("""
    CREATE TABLE ecommerce.products AS
    SELECT
        printf('P%04d', i)  AS product_id,
        CASE (i - 1) % 20
            WHEN 0  THEN 'Wireless Headphones' WHEN 1  THEN 'Running Shoes'
            WHEN 2  THEN 'Coffee Maker'         WHEN 3  THEN 'Yoga Mat'
            WHEN 4  THEN 'Standing Desk'        WHEN 5  THEN 'Laptop Stand'
            WHEN 6  THEN 'Water Bottle'         WHEN 7  THEN 'Mechanical Keyboard'
            WHEN 8  THEN 'USB Hub'              WHEN 9  THEN 'Phone Case'
            WHEN 10 THEN 'Desk Lamp'            WHEN 11 THEN 'Notebook Set'
            WHEN 12 THEN 'Travel Backpack'      WHEN 13 THEN 'Smart Watch'
            WHEN 14 THEN 'Bluetooth Speaker'    WHEN 15 THEN 'Monitor Arm'
            WHEN 16 THEN 'Ergonomic Chair'      WHEN 17 THEN 'Cable Organiser'
            WHEN 18 THEN 'Air Purifier'         ELSE 'Webcam'
        END || ' ' || CASE i % 5
            WHEN 0 THEN 'Pro'  WHEN 1 THEN 'Lite' WHEN 2 THEN 'Plus'
            WHEN 3 THEN 'Basic' ELSE 'Elite'
        END  AS product_name,
        CASE (i * 7) % 6
            WHEN 0 THEN 'Electronics'  WHEN 1 THEN 'Apparel'
            WHEN 2 THEN 'Kitchen'      WHEN 3 THEN 'Fitness'
            WHEN 4 THEN 'Office'       ELSE 'Accessories'
        END  AS category,
        ROUND((9.99 + (i * 17.3) % 290)::NUMERIC, 2)  AS price,
        (i * 11) % 500                                  AS stock_quantity,
        CASE WHEN (i * 11) % 500 = 0 THEN true ELSE false END  AS is_out_of_stock
    FROM range(1, 151) t(i)
    """)

    # ── orders ───────────────────────────────────────────────────────────────
    conn.execute("""
    CREATE TABLE ecommerce.orders AS
    SELECT
        printf('O%06d', i)  AS order_id,
        printf('C%05d', 1 + (i * 7) % 500)  AS customer_id,
        CASE
            WHEN (i * 3) % 100 < 5  THEN 'pending'
            WHEN (i * 3) % 100 < 12 THEN 'processing'
            WHEN (i * 3) % 100 < 28 THEN 'shipped'
            WHEN (i * 3) % 100 < 78 THEN 'delivered'
            WHEN (i * 3) % 100 < 90 THEN 'cancelled'
            ELSE 'refunded'
        END  AS status,
        ROUND((15 + (i * 23.7) % 485)::NUMERIC, 2)  AS total_amount,
        (DATE '2023-01-01' + (i % 730 || ' days')::INTERVAL)::DATE  AS order_date,
        CASE WHEN (i * 3) % 100 >= 28
            THEN (DATE '2023-01-01' + ((i % 730 + 2 + (i * 11) % 5) || ' days')::INTERVAL)::DATE
            ELSE NULL
        END  AS shipped_at,
        CASE WHEN (i * 3) % 100 >= 28 AND (i * 3) % 100 < 78
            THEN (DATE '2023-01-01' + ((i % 730 + 7 + (i * 13) % 7) || ' days')::INTERVAL)::DATE
            ELSE NULL
        END  AS delivered_at,
        CASE i % 5
            WHEN 0 THEN 'card'          WHEN 1 THEN 'paypal'
            WHEN 2 THEN 'bank_transfer' WHEN 3 THEN 'apple_pay'
            ELSE 'crypto'
        END  AS payment_method,
        (i * 17) % 5 + 1  AS item_count
    FROM range(1, 5001) t(i)
    """)

    # ── order_items ──────────────────────────────────────────────────────────
    conn.execute("""
    CREATE TABLE ecommerce.order_items AS
    SELECT
        i  AS item_id,
        printf('O%06d', 1 + (i * 3) % 5000)  AS order_id,
        printf('P%04d', 1 + (i * 11) % 150)  AS product_id,
        1 + (i * 7) % 5                        AS quantity,
        ROUND((9.99 + (i * 17.3) % 290)::NUMERIC, 2)  AS unit_price,
        ROUND(((9.99 + (i * 17.3) % 290) * (1 + (i * 7) % 5))::NUMERIC, 2)  AS line_total
    FROM range(1, 12001) t(i)
    """)

    # ── reviews ──────────────────────────────────────────────────────────────
    conn.execute("""
    CREATE TABLE ecommerce.reviews AS
    SELECT
        i  AS review_id,
        printf('O%06d', 1 + (i * 5) % 5000)  AS order_id,
        printf('C%05d', 1 + (i * 11) % 500)  AS customer_id,
        1 + (i * 3) % 5  AS rating,
        CASE
            WHEN 1 + (i * 3) % 5 >= 4 THEN CASE i % 6
                WHEN 0 THEN 'Great product!'            WHEN 1 THEN 'Exactly as described'
                WHEN 2 THEN 'Fast shipping, happy!'     WHEN 3 THEN 'Would recommend'
                WHEN 4 THEN 'Exceeded expectations'     ELSE 'Very satisfied'
            END
            WHEN 1 + (i * 3) % 5 = 3 THEN CASE i % 3
                WHEN 0 THEN 'OK, nothing special'  WHEN 1 THEN 'Average product'
                ELSE 'Decent but overpriced'
            END
            ELSE CASE i % 4
                WHEN 0 THEN 'Disappointed'               WHEN 1 THEN 'Not as described'
                WHEN 2 THEN 'Poor quality'               ELSE 'Would not recommend'
            END
        END  AS review_text,
        (DATE '2023-01-15' + ((i * 2) % 700 || ' days')::INTERVAL)::DATE  AS review_date
    FROM range(1, 3001) t(i)
    """)
