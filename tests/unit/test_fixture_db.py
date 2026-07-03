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
