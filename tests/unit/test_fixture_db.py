"""The builtin 'fixture' demo connection: seeded on request, and never advertised
before it is.

`data/aughor.duckdb` is gitignored, so a fresh install / CI run has no file behind the
builtin connection and opening a missing file read-only raises. That used to be papered
over by seeding on boot; the demo is now opt-in (`aughor seed` / `ensure_fixture_db`)
and the registry only offers the connection once the file exists.
"""
from __future__ import annotations

import duckdb


def test_ensure_fixture_db_creates_openable_db(monkeypatch, tmp_path):
    from aughor.demo import setup

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
    from aughor.demo import setup

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
    from aughor.demo.scenario import seed_scenario_db

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


# ── D1: no dataset ships by default ───────────────────────────────────────────

def test_boot_does_not_create_a_demo_dataset(monkeypatch, tmp_path):
    """A data platform must not fabricate data on startup.

    Booting used to call `ensure_fixture_db()`, writing 72,000 rows of synthetic
    revenue into a fresh install nobody asked for — and doing it inside the lifespan,
    so `Application startup complete` waited ~98s. The startup step now REPORTS what is
    present and creates nothing.
    """
    import asyncio

    from aughor import api
    from aughor.demo import setup

    fake = tmp_path / "aughor.duckdb"
    monkeypatch.setattr(setup, "FIXTURE_PATH", fake)

    asyncio.run(api._report_demo_data())

    assert not fake.exists(), (
        "startup created a demo dataset — nothing may seed on boot; `aughor seed` is the "
        "opt-in path")


def test_the_demo_connection_is_not_advertised_until_it_is_seeded(monkeypatch, tmp_path):
    """W4b. The registry listed the demo connection unconditionally, which auto-seeding
    made true by accident. Without a file behind it, opening it read-only raises — so an
    unseeded fixture must not appear in the connection list at all."""
    from aughor.db import registry
    from aughor.demo import setup

    fake = tmp_path / "aughor.duckdb"
    monkeypatch.setattr(setup, "FIXTURE_PATH", fake)

    listed = {c["id"] for c in registry.list_connections()}
    assert registry.BUILTIN_ID not in listed, (
        "an unseeded demo connection was offered to the user; it raises IOException on open")

    setup.ensure_fixture_db()          # the opt-in path
    listed = {c["id"] for c in registry.list_connections()}
    assert registry.BUILTIN_ID in listed, "once seeded, the demo connection must appear"


def test_seeding_the_demo_is_fast_enough_to_be_opt_in(monkeypatch, tmp_path):
    """W4c. `daily_revenue` was inserted row-by-row with `executemany`, costing ~98s for
    2 MB — the whole first-boot delay. Batched multi-row VALUES measured ~2s. Opt-in only
    works if opting in is quick, so hold the line well inside the old cost."""
    import time

    from aughor.demo import setup

    fake = tmp_path / "aughor.duckdb"
    monkeypatch.setattr(setup, "FIXTURE_PATH", fake)

    started = time.monotonic()
    setup.ensure_fixture_db()
    elapsed = time.monotonic() - started

    assert fake.exists()
    assert elapsed < 30, (
        f"seeding took {elapsed:.1f}s; it was ~98s with executemany and ~2s batched — "
        "a row-by-row INSERT has probably come back")


# ── The demo dataset is reachable without a terminal ──────────────────────────

def test_demo_endpoint_seeds_and_then_offers_the_connection(client, monkeypatch, tmp_path):
    """`aughor seed` is the opt-in, but a user who never opens a terminal cannot find
    it — so the first-run funnel needs the same act over HTTP."""
    from aughor.demo import setup

    fake = tmp_path / "aughor.duckdb"
    monkeypatch.setattr(setup, "FIXTURE_PATH", fake)
    assert "fixture" not in {c["id"] for c in client.get("/connections").json()}

    resp = client.post("/connections/demo")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id"] == "fixture" and body["seeded"] is True, body
    assert fake.exists()

    listed = {c["id"] for c in client.get("/connections").json()}
    assert "fixture" in listed, "seeding must make the connection appear"

    # …and it must actually open — an advertised-but-broken connection is the bug
    # auto-seeding used to hide.
    sample = client.get("/connections/fixture/tables/customers/sample", params={"limit": 2})
    assert sample.status_code == 200, sample.text
    assert sample.json()["rows"], "the seeded demo connection returned no rows"


def test_demo_endpoint_is_idempotent_and_never_clobbers(client, monkeypatch, tmp_path):
    """A second click must not re-seed. `ensure_fixture_db` only writes when the file is
    absent, so a user who has edited the demo keeps their edits."""
    from aughor.demo import setup

    fake = tmp_path / "aughor.duckdb"
    monkeypatch.setattr(setup, "FIXTURE_PATH", fake)

    assert client.post("/connections/demo").json()["seeded"] is True
    stamp = fake.stat().st_mtime_ns

    second = client.post("/connections/demo")
    assert second.status_code == 201, second.text
    assert second.json()["seeded"] is False, "a second call re-seeded"
    assert fake.stat().st_mtime_ns == stamp, "the existing demo file was rewritten"


def test_seeding_the_demo_requires_the_permission_that_adding_a_connection_does():
    """It writes a file and makes a connection appear — the same act as POST
    /connections, so it must not fall to the write floor a viewer clears."""
    from aughor.rbac.permissions import Permission
    from aughor.rbac.policy import required_permission

    assert required_permission("POST", "/connections/demo") == Permission.CONNECTION_CREATE
    assert (required_permission("POST", "/connections/demo")
            == required_permission("POST", "/connections"))
