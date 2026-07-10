"""The builtin 'fixture' demo connection must have an openable DB on any checkout.

`data/aughor.duckdb` is gitignored and nothing seeded it, so a fresh install / CI
run had a broken builtin connection (opening a missing file read-only raises).
`ensure_fixture_db` guarantees it exists.
"""
from __future__ import annotations

import duckdb


def test_ensure_fixture_db_creates_openable_db(monkeypatch, tmp_path):
    from aughor.samples import setup

    fake = tmp_path / "aughor.duckdb"
    monkeypatch.setattr(setup, "FIXTURE_PATH", fake)
    assert not fake.exists()

    path = setup.ensure_fixture_db()
    assert path == fake and fake.exists()

    # The exact failure mode on CI was a read-only open of a missing file; the
    # builtin connection also needs demo tables (in `main`, unqualified-resolvable).
    c = duckdb.connect(str(fake), read_only=True)
    try:
        assert c.execute("SELECT 42 AS answer").fetchone()[0] == 42
        tables = {r[0] for r in c.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()}
        assert {"customers", "daily_revenue", "events", "kpi_daily"} <= tables
        # unqualified name resolves + has rows (what /tables/{name}/sample needs)
        assert c.execute("SELECT COUNT(*) FROM customers").fetchone()[0] > 0
    finally:
        c.close()

    # Idempotent — a second call is a no-op and does not raise.
    setup.ensure_fixture_db()


def test_fixture_db_has_a_real_discoverable_signal(monkeypatch, tmp_path):
    """W14 regression: the demo data must contain the outage scenario, not noise.

    The old auto-seed produced uniform noise with `plan` a perfect alias of
    `region`, so the first-run Briefing narrated a non-finding. Assert the three
    properties that make the demo honest: a dated outage event, a real failure
    spike confined to APAC/SMB on that day, and no plan≡region collinearity."""
    from aughor.samples import setup

    fake = tmp_path / "aughor.duckdb"
    monkeypatch.setattr(setup, "FIXTURE_PATH", fake)
    setup.ensure_fixture_db()

    c = duckdb.connect(str(fake), read_only=True)
    try:
        # The outage event exists and is dated.
        outage = c.execute(
            "SELECT start_date, affected_region, affected_segment FROM events WHERE event_type='outage'"
        ).fetchone()
        assert outage is not None
        outage_date, region, segment = outage
        assert (region, segment) == ("APAC", "SMB")

        # Failure rate on the outage day: elevated for APAC/SMB, normal elsewhere.
        apac_smb_rate = c.execute(
            "SELECT AVG(failure_rate_pct) FROM kpi_daily WHERE date = ? AND region='APAC' AND segment='SMB'",
            [outage_date],
        ).fetchone()[0]
        other_rate = c.execute(
            "SELECT AVG(failure_rate_pct) FROM kpi_daily WHERE date = ? AND NOT (region='APAC' AND segment='SMB')",
            [outage_date],
        ).fetchone()[0]
        assert apac_smb_rate > 25, f"outage-day APAC/SMB failure rate {apac_smb_rate} not elevated"
        assert other_rate < 5, f"non-outage segments failure rate {other_rate} not normal"

        # APAC/SMB revenue drops materially vs its own 7-day baseline.
        drop = c.execute("""
            SELECT 1 - (SELECT SUM(value) FROM kpi_daily WHERE date = ? AND region='APAC' AND segment='SMB')
                     / (SELECT AVG(v) FROM (
                          SELECT SUM(value) AS v FROM kpi_daily
                          WHERE date BETWEEN ? - INTERVAL 7 DAY AND ? - INTERVAL 1 DAY
                            AND region='APAC' AND segment='SMB' GROUP BY date))
        """, [outage_date, outage_date, outage_date]).fetchone()[0]
        assert drop > 0.25, f"APAC/SMB outage-day revenue drop {drop:.1%} too small to discover"

        # plan must NOT be a perfect alias of region (the old degenerate cross-tab
        # had exactly 3 populated cells — one plan per region).
        cells = c.execute(
            "SELECT COUNT(*) FROM (SELECT DISTINCT plan, region FROM customers)"
        ).fetchone()[0]
        n_plans = c.execute("SELECT COUNT(DISTINCT plan) FROM customers").fetchone()[0]
        assert cells > n_plans, "plan is an alias of region — degenerate demo data"
    finally:
        c.close()


def test_seed_scenario_db_overwrite_contract(tmp_path):
    """`aughor seed` replaces an existing file; the auto-seed path never may."""
    from aughor.samples.scenario import seed_scenario_db

    target = tmp_path / "demo.duckdb"
    summary = seed_scenario_db(target, overwrite=False)
    assert target.exists()
    assert summary["customers"] == 800
    assert summary["apac_smb_drop_pct"] > 25

    # Without overwrite, an existing file is refused (protects a real dev DB).
    import pytest
    with pytest.raises(FileExistsError):
        seed_scenario_db(target, overwrite=False)

    # With overwrite, it reseeds cleanly and deterministically.
    summary2 = seed_scenario_db(target, overwrite=True)
    assert summary2 == summary
