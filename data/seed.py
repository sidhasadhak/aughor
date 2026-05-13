"""
Seed a realistic SaaS fixture database for Hermes investigations.

Scenario baked in:
  - 90 days of revenue data for ~800 customers
  - Regions: APAC, EMEA, NA | Segments: SMB, Enterprise
  - Day 83: payment gateway outage in APAC (4-hour window)
  - Effect: ~30% of APAC SMB transactions fail on days 83–84
  - Total company revenue drops ~8% for that week
  - Enterprise and EMEA are unaffected and tracking above forecast
  - A red herring: minor promotion in NA on day 80 (doesn't explain the drop)

This lets the agent discover root cause by:
  1. Segmenting revenue by region/segment
  2. Correlating with the events table
  3. Checking payment failure rates in daily_revenue
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

import duckdb
import numpy as np

SEED = 42
random.seed(SEED)
np.random.seed(SEED)

DB_PATH = Path(__file__).parent / "hermes.duckdb"
START_DATE = date(2025, 9, 1)
DAYS = 90
OUTAGE_DAY = 83  # day index from START_DATE
OUTAGE_DURATION_HOURS = 4


def main():
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = duckdb.connect(str(DB_PATH))

    # ── Customers ──────────────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE customers (
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
    # Distribution: 250 APAC, 300 NA, 250 EMEA; each 60% SMB, 40% Enterprise
    for region, count in [("APAC", 250), ("NA", 300), ("EMEA", 250)]:
        for i in range(count):
            segment = "SMB" if random.random() < 0.60 else "Enterprise"
            plan = random.choice(["starter", "growth", "scale"]) if segment == "SMB" else random.choice(["business", "enterprise"])
            mrr = random.uniform(100, 800) if segment == "SMB" else random.uniform(2000, 15000)
            acquired_days_ago = random.randint(30, 720)
            customers.append({
                "customer_id": f"cust_{cid:04d}",
                "name": f"Company {cid}",
                "segment": segment,
                "region": region,
                "plan": plan,
                "mrr": round(mrr, 2),
                "acquired_at": (date(2025, 9, 1) - timedelta(days=acquired_days_ago)).isoformat(),
            })
            cid += 1

    conn.executemany(
        "INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?, ?)",
        [[c[k] for k in ["customer_id", "name", "segment", "region", "plan", "mrr", "acquired_at"]] for c in customers]
    )

    # ── Events ────────────────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE events (
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
        INSERT INTO events VALUES
        ('evt_001', 'outage',    'APAC Payment Gateway Degradation',
         'Stripe APAC payment gateway experienced intermittent failures for 4 hours on the morning of this date. SMB plans on shared infrastructure were disproportionately affected.',
         ?, ?, 'APAC', 'SMB'),
        ('evt_002', 'promotion', 'NA Back-to-Business Promo',
         '15% discount offered to NA SMB customers renewing in this period.',
         ?, ?, 'NA', 'SMB'),
        ('evt_003', 'holiday',   'Golden Week (Japan/South Korea)',
         'Public holidays across Japan and South Korea reducing business activity.',
         ?, ?, 'APAC', 'ALL')
    """,
    [
        outage_date.isoformat(), (outage_date + timedelta(days=1)).isoformat(),
        (START_DATE + timedelta(days=80)).isoformat(), (START_DATE + timedelta(days=83)).isoformat(),
        (START_DATE + timedelta(days=55)).isoformat(), (START_DATE + timedelta(days=60)).isoformat(),
    ])

    # ── Daily Revenue ──────────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE daily_revenue (
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
        is_outage = day_idx == OUTAGE_DAY

        for c in customers:
            # Base daily revenue with mild day-of-week and growth trend
            base = c["mrr"] / 30.0
            base *= (0.85 if is_weekend else 1.0)
            base *= (1 + day_idx * 0.001)  # slight upward trend
            base += random.gauss(0, base * 0.05)  # 5% noise
            base = max(0, base)

            # Outage: APAC SMB has ~35% failure rate on outage day
            if is_outage and c["region"] == "APAC" and c["segment"] == "SMB":
                status = "failed" if random.random() < 0.35 else "success"
                # Day after outage: some retry failures remain (~10%)
            elif day_idx == OUTAGE_DAY + 1 and c["region"] == "APAC" and c["segment"] == "SMB":
                status = "failed" if random.random() < 0.10 else "success"
            else:
                # Normal failure rate: ~1.5%
                status = "failed" if random.random() < 0.015 else "success"

            rows.append((current_date.isoformat(), c["customer_id"], round(base, 4), status))

    conn.executemany("INSERT INTO daily_revenue VALUES (?, ?, ?, ?)", rows)

    # ── KPI Daily (pre-aggregated) ─────────────────────────────────────────
    conn.execute("""
        CREATE TABLE kpi_daily AS
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
        FROM daily_revenue dr
        JOIN customers c USING (customer_id)
        GROUP BY dr.date, c.region, c.segment
        ORDER BY dr.date, c.region, c.segment
    """)

    # ── Verification ──────────────────────────────────────────────────────
    outage_str = outage_date.isoformat()
    baseline_start = (outage_date - timedelta(days=7)).isoformat()
    baseline_end   = (outage_date - timedelta(days=1)).isoformat()

    total_rev = conn.execute("SELECT ROUND(SUM(amount), 0) FROM daily_revenue WHERE status='success'").fetchone()[0]
    outage_apac_smb = conn.execute(
        "SELECT ROUND(SUM(value), 0) FROM kpi_daily WHERE date = ? AND region='APAC' AND segment='SMB'",
        [outage_str]
    ).fetchone()[0]
    baseline_apac_smb = conn.execute(
        "SELECT ROUND(AVG(value), 0) FROM kpi_daily WHERE date BETWEEN ? AND ? AND region='APAC' AND segment='SMB'",
        [baseline_start, baseline_end]
    ).fetchone()[0]

    failure_rate = conn.execute(
        "SELECT ROUND(AVG(failure_rate_pct), 2) FROM kpi_daily WHERE date = ? AND region='APAC' AND segment='SMB'",
        [outage_str]
    ).fetchone()[0]

    print(f"Database seeded at: {DB_PATH}")
    print(f"  Customers:         {len(customers):,}")
    print(f"  Revenue rows:      {len(rows):,}")
    print(f"  Total revenue:     ${total_rev:,.0f}")
    print(f"  Outage date:       {outage_str}")
    print(f"  APAC SMB revenue on outage day: ${outage_apac_smb:,.0f}")
    print(f"  APAC SMB baseline (7-day avg):  ${baseline_apac_smb:,.0f}")
    drop = round((1 - outage_apac_smb / baseline_apac_smb) * 100, 1) if baseline_apac_smb else 0
    print(f"  Revenue drop in APAC SMB:       {drop}%")
    print(f"  Failure rate APAC SMB on outage: {failure_rate}%")

    conn.close()


if __name__ == "__main__":
    main()
