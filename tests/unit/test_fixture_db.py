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

    # The exact failure mode on CI was a read-only open of a missing file.
    c = duckdb.connect(str(fake), read_only=True)
    try:
        assert c.execute("SELECT 42 AS answer").fetchone()[0] == 42
    finally:
        c.close()

    # Idempotent — a second call is a no-op and does not raise.
    setup.ensure_fixture_db()
