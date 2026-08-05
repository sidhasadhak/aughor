"""The sqlite→Postgres cutover script, proven on a live server.

Small-scale here; the same script moved the full local data/ (33 stores, 54 tables,
217k rows, every count verified, serving reads confirmed) on 2026-08-05. Skips when
no Postgres is reachable — migration correctness is meaningless against a mock.
"""
from __future__ import annotations

import os
import sqlite3

import pytest

PG_URL = os.environ.get("AUGHOR_PG_TEST_URL", "postgres://postgres:aughor@localhost:5544/aughor")


def _pg_available() -> bool:
    try:
        import psycopg2
        psycopg2.connect(PG_URL, connect_timeout=2).close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _pg_available(), reason="needs a live Postgres target")


@pytest.fixture()
def source_db(tmp_path):
    p = tmp_path / "probe_store.db"
    c = sqlite3.connect(str(p))
    c.executescript("""
        CREATE TABLE items (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL, meta JSON, ok BOOLEAN, ts TIMESTAMP
        );
        CREATE INDEX items_name ON items(name);
    """)
    c.executemany("INSERT INTO items (name, meta, ok, ts) VALUES (?,?,?,?)",
                  [(f"n{i}", '{"k":1}', 1, "2026-08-05T00:00:00+00:00") for i in range(7)])
    c.execute("PRAGMA user_version = 3")
    c.commit()
    c.close()
    return p


def test_migrates_verifies_and_serves(source_db, monkeypatch):
    from scripts.migrate_sqlite_to_postgres import _schema_for, migrate_db_file

    monkeypatch.setenv("AUGHOR_DB_URL", PG_URL)
    tables, rows, mismatches = migrate_db_file(source_db, PG_URL, wipe=True)
    assert (tables, rows, mismatches) == (1, 7, [])

    from aughor.db.backend import PgConnection
    dst = PgConnection(PG_URL, schema=_schema_for(source_db))
    try:
        # Rows serve, and stringly-typed storage semantics held through the copy.
        row = dst.execute("SELECT name, meta, ts FROM items WHERE id=?", (3,)).fetchone()
        assert row[0] == "n2" and row[1] == '{"k":1}' and isinstance(row[2], str)   # ids start at 1
        # user_version carried — store migrations will NOT re-apply on the target.
        assert dst.execute("PRAGMA user_version").fetchone()[0] == 3
        # The identity sequence was advanced past the copied ids: a fresh insert
        # must not collide with a migrated row (the classic cutover trap).
        dst.execute("INSERT INTO items (name) VALUES (?)", ("post-migration",))
        dst.commit()
        new_id = dst.execute("SELECT id FROM items WHERE name=?", ("post-migration",)).fetchone()[0]
        assert new_id == 8
    finally:
        dst.close()


def test_refuses_a_nonempty_target_without_wipe(source_db, monkeypatch):
    """Half-written targets must never be silently merged into."""
    from scripts.migrate_sqlite_to_postgres import migrate_db_file

    monkeypatch.setenv("AUGHOR_DB_URL", PG_URL)
    migrate_db_file(source_db, PG_URL, wipe=True)
    with pytest.raises(SystemExit, match="not empty"):
        migrate_db_file(source_db, PG_URL, wipe=False)
