"""Seed the demo DuckDB database — thin wrapper kept for `python data/seed.py`.

The scenario itself lives in ``aughor/samples/scenario.py`` (single source of
truth): 90 days of SaaS revenue for ~800 customers with a discoverable APAC
payment-gateway outage on day 83, EMEA/Enterprise unaffected, and an NA promo
planted as a red herring.

Writes ``data/aughor.duckdb`` — the same file the builtin ``fixture`` connection
and ``aughor investigate`` read (it used to write ``data/hermes.duckdb``, the
project's old name, so the packaged seed→investigate flow didn't compose).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

DB_PATH = Path(__file__).parent / "aughor.duckdb"


def main():
    from aughor.samples.scenario import seed_scenario_db

    summary = seed_scenario_db(DB_PATH, overwrite=True)
    print(f"Database seeded at: {DB_PATH}")
    print(f"  Customers:         {summary['customers']:,}")
    print(f"  Revenue rows:      {summary['revenue_rows']:,}")
    print(f"  Total revenue:     ${summary['total_revenue']:,.0f}")
    print(f"  Outage date:       {summary['outage_date']}")
    print(f"  APAC SMB revenue on outage day: ${summary['outage_apac_smb_revenue']:,.0f}")
    print(f"  APAC SMB baseline (7-day avg):  ${summary['baseline_apac_smb_revenue']:,.0f}")
    print(f"  Revenue drop in APAC SMB:       {summary['apac_smb_drop_pct']}%")
    print(f"  Failure rate APAC SMB on outage: {summary['apac_smb_outage_failure_rate_pct']}%")


if __name__ == "__main__":
    main()
