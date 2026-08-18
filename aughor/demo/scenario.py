"""The bundled demo scenario — a realistic SaaS revenue dataset with a real story.

Seeded into ``data/aughor.duckdb`` (the builtin ``fixture`` connection) on request
— by ``aughor seed`` or ``setup.ensure_fixture_db`` — so a user who wants something to
explore gets an actual discoverable finding rather than uniform noise (W14), and both
packaged CLI commands operate on the same file (W15). Nothing seeds it at boot: a data
platform should not fabricate 72,000 rows on a fresh install nobody asked.

Scenario baked in (deterministic, seed 42):
  - 90 days of revenue for ~800 customers
  - Regions: APAC, EMEA, NA | Segments: SMB, Enterprise
  - Day 83 (2025-11-23): a 4-hour APAC payment-gateway outage
  - Effect: ~35% of APAC/SMB transactions fail on the outage day (~10% residual
    retry failures the day after) → a verified ~−38.8% APAC/SMB revenue drop
  - EMEA and Enterprise are unaffected
  - A red herring: an NA promotion 3 days earlier that does NOT explain the drop

The agent can discover the root cause by segmenting revenue by region/segment,
correlating with the events table, and checking failure rates in daily_revenue.
Tables live in the ``main`` schema so unqualified names resolve.
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

SEED = 42
START_DATE = date(2025, 9, 1)
DAYS = 90
OUTAGE_DAY = 83  # day index from START_DATE

#: Rows per INSERT in :func:`_bulk_insert`. DuckDB is columnar: a prepared single-row
#: INSERT pays per-statement overhead that dwarfs the write, so `executemany` over the
#: 72,000 daily_revenue rows cost ~98s — the entire first-boot delay, for 2 MB of data.
#: Batching the same rows into multi-row VALUES measured 27x faster. 2,000 keeps the
#: statement and its parameter list comfortably small.
_INSERT_CHUNK = 2000


def _bulk_insert(conn, table: str, rows: list, n_cols: int) -> None:  # noqa: ANN001
    """INSERT `rows` into `table` in multi-row batches.

    Same data and same order as `executemany` — only the statement shape changes, so
    the deterministic seed still produces byte-identical content.
    """
    if not rows:
        return
    placeholder = f"({','.join('?' * n_cols)})"
    for start in range(0, len(rows), _INSERT_CHUNK):
        batch = rows[start:start + _INSERT_CHUNK]
        conn.execute(
            f"INSERT INTO {table} VALUES {','.join([placeholder] * len(batch))}",
            [value for row in batch for value in row],
        )


def seed_scenario(conn) -> None:  # noqa: ANN001
    """Create + populate customers · events · daily_revenue · kpi_daily on ``conn``.

    Deterministic: a local ``random.Random(SEED)`` drives every draw, so two seeds
    of the same version produce byte-identical data.
    """
    rng = random.Random(SEED)

    # ── Customers ──────────────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE main.customers (
            customer_id   VARCHAR PRIMARY KEY,
            name          VARCHAR,
            segment       VARCHAR,
            region        VARCHAR,
            plan          VARCHAR,
            mrr           DOUBLE,
            acquired_at   DATE
        )
    """)

    customers = []
    cid = 1
    # Distribution: 250 APAC, 300 NA, 250 EMEA; each ~60% SMB, ~40% Enterprise
    for region, count in [("APAC", 250), ("NA", 300), ("EMEA", 250)]:
        for _ in range(count):
            segment = "SMB" if rng.random() < 0.60 else "Enterprise"
            plan = (
                rng.choice(["starter", "growth", "scale"])
                if segment == "SMB"
                else rng.choice(["business", "enterprise"])
            )
            mrr = rng.uniform(100, 800) if segment == "SMB" else rng.uniform(2000, 15000)
            acquired_days_ago = rng.randint(30, 720)
            customers.append({
                "customer_id": f"cust_{cid:04d}",
                "name": f"Company {cid}",
                "segment": segment,
                "region": region,
                "plan": plan,
                "mrr": round(mrr, 2),
                "acquired_at": (START_DATE - timedelta(days=acquired_days_ago)).isoformat(),
            })
            cid += 1

    _bulk_insert(
        conn, "main.customers",
        [[c[k] for k in ("customer_id", "name", "segment", "region", "plan", "mrr", "acquired_at")]
         for c in customers],
        7,
    )

    # ── Events ────────────────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE main.events (
            event_id          VARCHAR PRIMARY KEY,
            event_type        VARCHAR,
            title             VARCHAR,
            description       VARCHAR,
            start_date        DATE,
            end_date          DATE,
            affected_region   VARCHAR,
            affected_segment  VARCHAR
        )
    """)

    outage_date = START_DATE + timedelta(days=OUTAGE_DAY)
    conn.execute("""
        INSERT INTO main.events VALUES
        ('evt_001', 'outage',    'APAC Payment Gateway Degradation',
         'Stripe APAC payment gateway experienced intermittent failures for 4 hours on the morning of this date. SMB plans on shared infrastructure were disproportionately affected.',
         ?, ?, 'APAC', 'SMB'),
        ('evt_002', 'promotion', 'NA Back-to-Business Promo',
         '15% discount offered to NA SMB customers renewing in this period.',
         ?, ?, 'NA', 'SMB'),
        ('evt_003', 'holiday',   'Golden Week (Japan/South Korea)',
         'Public holidays across Japan and South Korea reducing business activity.',
         ?, ?, 'APAC', 'ALL')
    """, [
        outage_date.isoformat(), (outage_date + timedelta(days=1)).isoformat(),
        (START_DATE + timedelta(days=80)).isoformat(), (START_DATE + timedelta(days=83)).isoformat(),
        (START_DATE + timedelta(days=55)).isoformat(), (START_DATE + timedelta(days=60)).isoformat(),
    ])

    # ── Daily revenue ──────────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE main.daily_revenue (
            date         DATE,
            customer_id  VARCHAR,
            amount       DOUBLE,
            status       VARCHAR
        )
    """)

    rows = []
    for day_idx in range(DAYS):
        current_date = START_DATE + timedelta(days=day_idx)
        is_weekend = current_date.weekday() >= 5

        for c in customers:
            # Base daily revenue with mild day-of-week and growth trend
            base = c["mrr"] / 30.0
            base *= 0.85 if is_weekend else 1.0
            base *= 1 + day_idx * 0.001  # slight upward trend
            base += rng.gauss(0, base * 0.05)  # 5% noise
            base = max(0, base)

            apac_smb = c["region"] == "APAC" and c["segment"] == "SMB"
            if day_idx == OUTAGE_DAY and apac_smb:
                # Outage: ~35% failure rate for APAC SMB on the outage day
                status = "failed" if rng.random() < 0.35 else "success"
            elif day_idx == OUTAGE_DAY + 1 and apac_smb:
                # Day after: some retry failures remain (~10%)
                status = "failed" if rng.random() < 0.10 else "success"
            else:
                # Normal failure rate: ~1.5%
                status = "failed" if rng.random() < 0.015 else "success"

            rows.append((current_date.isoformat(), c["customer_id"], round(base, 4), status))

    _bulk_insert(conn, "main.daily_revenue", rows, 4)

    # ── KPI daily (pre-aggregated) ─────────────────────────────────────────
    conn.execute("""
        CREATE TABLE main.kpi_daily AS
        SELECT
            dr.date,
            c.region,
            c.segment,
            'revenue'                                       AS metric,
            SUM(CASE WHEN dr.status = 'success' THEN dr.amount ELSE 0 END) AS value,
            COUNT(*)                                        AS transaction_count,
            SUM(CASE WHEN dr.status = 'failed' THEN 1 ELSE 0 END) AS failure_count,
            ROUND(
                100.0 * SUM(CASE WHEN dr.status = 'failed' THEN 1 ELSE 0 END) / COUNT(*),
                2
            ) AS failure_rate_pct
        FROM main.daily_revenue dr
        JOIN main.customers c USING (customer_id)
        GROUP BY dr.date, c.region, c.segment
        ORDER BY dr.date, c.region, c.segment
    """)


def scenario_summary(conn) -> dict:  # noqa: ANN001
    """Verify the seeded scenario by querying it and return the headline numbers."""
    outage_date = START_DATE + timedelta(days=OUTAGE_DAY)
    outage_str = outage_date.isoformat()
    baseline_start = (outage_date - timedelta(days=7)).isoformat()
    baseline_end = (outage_date - timedelta(days=1)).isoformat()

    n_customers = conn.execute("SELECT COUNT(*) FROM main.customers").fetchone()[0]
    n_rows = conn.execute("SELECT COUNT(*) FROM main.daily_revenue").fetchone()[0]
    total_rev = conn.execute(
        "SELECT ROUND(SUM(amount), 0) FROM main.daily_revenue WHERE status='success'"
    ).fetchone()[0]
    outage_apac_smb = conn.execute(
        "SELECT ROUND(SUM(value), 0) FROM main.kpi_daily WHERE date = ? AND region='APAC' AND segment='SMB'",
        [outage_str],
    ).fetchone()[0]
    baseline_apac_smb = conn.execute(
        "SELECT ROUND(AVG(value), 0) FROM main.kpi_daily WHERE date BETWEEN ? AND ? AND region='APAC' AND segment='SMB'",
        [baseline_start, baseline_end],
    ).fetchone()[0]
    failure_rate = conn.execute(
        "SELECT ROUND(AVG(failure_rate_pct), 2) FROM main.kpi_daily WHERE date = ? AND region='APAC' AND segment='SMB'",
        [outage_str],
    ).fetchone()[0]

    drop_pct = (
        round((1 - outage_apac_smb / baseline_apac_smb) * 100, 1) if baseline_apac_smb else 0.0
    )
    return {
        "customers": n_customers,
        "revenue_rows": n_rows,
        "total_revenue": total_rev,
        "outage_date": outage_str,
        "outage_apac_smb_revenue": outage_apac_smb,
        "baseline_apac_smb_revenue": baseline_apac_smb,
        "apac_smb_drop_pct": drop_pct,
        "apac_smb_outage_failure_rate_pct": failure_rate,
    }


def seed_scenario_db(db_path: Path, *, overwrite: bool = False) -> dict:
    """Seed the scenario into a DuckDB file and return its verified summary.

    ``overwrite=True`` (the explicit ``aughor seed`` command) replaces an existing
    file; ``ensure_fixture_db`` (the idempotent opt-in path) never passes it.
    """
    import duckdb

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        if not overwrite:
            raise FileExistsError(f"{db_path} already exists (pass overwrite=True to replace)")
        db_path.unlink()

    conn = duckdb.connect(str(db_path))
    try:
        seed_scenario(conn)
        return scenario_summary(conn)
    finally:
        conn.close()
