"""The store-connection seam: sqlite unchanged by default, Postgres proven live.

Translation tests run everywhere. The live half runs against a real Postgres
(``AUGHOR_PG_TEST_URL``, defaulting to the local docker container) and SKIPS when
none is reachable — the point of the backend is behaviour identical enough that the
store suite passes on both, and that can only be shown on a real server, not a mock.
"""
from __future__ import annotations

import os
import sqlite3

import pytest

from aughor.db import backend as B

PG_URL = os.environ.get("AUGHOR_PG_TEST_URL", "postgres://postgres:aughor@localhost:5544/aughor")


def _pg_available() -> bool:
    try:
        import psycopg2
        psycopg2.connect(PG_URL, connect_timeout=2).close()
        return True
    except Exception:
        return False


needs_pg = pytest.mark.skipif(not _pg_available(), reason="no live Postgres to prove against")


# ── translation (no server needed) ───────────────────────────────────────────

def test_qmark_becomes_format_placeholder():
    out = B.translate("SELECT * FROM t WHERE a=? AND b=?")
    assert out.count("%s") == 2 and "?" not in out


def test_reserved_words_survive_as_column_names():
    """The overlay store has a column literally named `column` — legal bare in
    sqlite, a syntax error bare in Postgres. Identifier quoting must cover it."""
    out = B.translate('CREATE TABLE o (id TEXT PRIMARY KEY, "table" TEXT, column TEXT)')
    assert '"column"' in out


def test_insert_or_ignore_becomes_on_conflict_do_nothing():
    out = B.translate("INSERT OR IGNORE INTO t (a, b) VALUES (?, ?)")
    assert out.endswith("ON CONFLICT DO NOTHING")
    assert "OR IGNORE" not in out.upper()


def test_insert_or_replace_carries_the_sentinel_for_pk_expansion():
    out = B.translate("INSERT OR REPLACE INTO t (a, b) VALUES (?, ?)")
    assert B._ON_CONFLICT_SENTINEL in out
    assert "OR REPLACE" not in out.upper()


def test_order_by_rowid_maps_to_ctid():
    assert "ORDER BY ctid" in B.translate("SELECT id FROM t ORDER BY rowid")


def test_literal_percent_is_doubled_but_placeholders_survive():
    out = B.translate("SELECT * FROM t WHERE a LIKE '%x%' AND b=?")
    assert "'%%x%%'" in out and out.rstrip().endswith("%s")


def test_named_placeholders_survive_percent_escaping():
    """sqlite's :name params render as %(name)s — the escaper must not double them
    (that broke every automations-store write on first live contact)."""
    out = B.translate("INSERT INTO t (a, b) VALUES (:a, :b)")
    assert "%(a)s" in out and "%(b)s" in out and "%%(" not in out


def test_declared_types_keep_sqlite_storage_semantics():
    out = B.translate(
        "CREATE TABLE t (p JSON, ts TIMESTAMP, ok BOOLEAN, amt NUMERIC, r REAL)")
    up = out.upper()
    assert "JSON" not in up.replace("JSONB", "")           # JSON → TEXT
    assert "TIMESTAMP" not in up                            # TIMESTAMP → TEXT
    assert "BOOLEAN" not in up                              # BOOLEAN → SMALLINT
    assert "DOUBLE PRECISION" in up                         # NUMERIC/REAL


def test_translate_is_cached():
    sql = "SELECT 1 FROM cache_probe"
    B.translate(sql)
    assert sql in B._XLATE_CACHE


def test_sqlite_is_the_default_backend(tmp_path, monkeypatch):
    """No AUGHOR_DB_URL → a real, tuned sqlite3 connection: today's behaviour."""
    monkeypatch.delenv(B.DB_URL_ENV, raising=False)
    conn = B.connect_store(tmp_path / "probe.db", "data/probe.db", row_factory=True)
    try:
        assert isinstance(conn, sqlite3.Connection)
        assert conn.row_factory is sqlite3.Row
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"   # tune() ran
    finally:
        conn.close()


# ── live Postgres ────────────────────────────────────────────────────────────

@pytest.fixture()
def pg_store(monkeypatch, tmp_path):
    """A connected store on the live PG, isolated the same way redirected files are —
    a resolved path that differs from the default → its own schema."""
    monkeypatch.setenv(B.DB_URL_ENV, PG_URL)

    def make(row_factory=False):
        return B.connect_store(tmp_path / "probe.db", "data/probe.db", row_factory=row_factory)

    yield make


@needs_pg
def test_crud_round_trip_and_row_access(pg_store):
    conn = pg_store(row_factory=True)
    conn.execute("CREATE TABLE IF NOT EXISTS items (id TEXT PRIMARY KEY, n INTEGER, meta JSON)")
    conn.execute("INSERT INTO items (id, n, meta) VALUES (?, ?, ?)", ("a", 1, '{"k": 2}'))
    conn.commit()
    row = conn.execute("SELECT id, n, meta FROM items WHERE id=?", ("a",)).fetchone()
    assert row["id"] == "a" and row[1] == 1            # dict AND index access
    assert row["meta"] == '{"k": 2}'                    # JSON column returns TEXT, not dict
    assert isinstance(row["meta"], str)
    conn.close()


@needs_pg
def test_schema_isolation_matches_file_isolation(monkeypatch, tmp_path):
    """Two stores redirected to two paths must not see each other's rows — on files
    that was two files; on Postgres it must be two schemas."""
    monkeypatch.setenv(B.DB_URL_ENV, PG_URL)
    conns = []
    for name in ("one", "two"):
        c = B.connect_store(tmp_path / f"{name}.db", "data/iso.db")
        c.execute("CREATE TABLE IF NOT EXISTS t (v TEXT)")
        c.execute("INSERT INTO t (v) VALUES (?)", (name,))
        c.commit()
        conns.append(c)
    a = [r[0] for r in conns[0].execute("SELECT v FROM t").fetchall()]
    b = [r[0] for r in conns[1].execute("SELECT v FROM t").fetchall()]
    assert a == ["one"] and b == ["two"]
    for c in conns:
        c.close()


@needs_pg
def test_insert_or_replace_upserts_on_the_real_primary_key(pg_store):
    conn = pg_store()
    conn.execute("CREATE TABLE IF NOT EXISTS kv2 (k TEXT PRIMARY KEY, v TEXT, extra TEXT)")
    conn.execute("INSERT OR REPLACE INTO kv2 (k, v, extra) VALUES (?, ?, ?)", ("a", "1", "x"))
    conn.execute("INSERT OR REPLACE INTO kv2 (k, v, extra) VALUES (?, ?, ?)", ("a", "2", "y"))
    conn.commit()
    rows = conn.execute("SELECT k, v, extra FROM kv2").fetchall()
    assert rows == [("a", "2", "y")]                    # replaced, not duplicated
    conn.close()


@needs_pg
def test_insert_or_ignore_ignores_duplicates(pg_store):
    conn = pg_store()
    conn.execute("CREATE TABLE IF NOT EXISTS ig (k TEXT PRIMARY KEY, v TEXT)")
    conn.execute("INSERT OR IGNORE INTO ig (k, v) VALUES (?, ?)", ("a", "first"))
    conn.execute("INSERT OR IGNORE INTO ig (k, v) VALUES (?, ?)", ("a", "second"))
    conn.commit()
    assert conn.execute("SELECT v FROM ig WHERE k=?", ("a",)).fetchone()[0] == "first"
    conn.close()


@needs_pg
def test_with_conn_commits_on_success_and_rolls_back_on_error(pg_store):
    conn = pg_store()
    conn.execute("CREATE TABLE IF NOT EXISTS tx (v TEXT)")
    conn.commit()
    with conn:
        conn.execute("INSERT INTO tx (v) VALUES (?)", ("kept",))
    with pytest.raises(RuntimeError):
        with conn:
            conn.execute("INSERT INTO tx (v) VALUES (?)", ("lost",))
            raise RuntimeError("boom")
    vals = [r[0] for r in conn.execute("SELECT v FROM tx").fetchall()]
    assert vals == ["kept"]
    conn.close()


@needs_pg
def test_insert_returning_id_on_both_backends(pg_store, tmp_path, monkeypatch):
    conn = pg_store()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS seq_t (id INTEGER PRIMARY KEY AUTOINCREMENT, v TEXT)")
    rid = B.insert_returning_id(conn, "INSERT INTO seq_t (v) VALUES (?)", ("x",))
    assert isinstance(rid, int) and rid >= 1
    conn.close()

    monkeypatch.delenv(B.DB_URL_ENV, raising=False)
    lite = sqlite3.connect(str(tmp_path / "seq.db"))
    lite.execute("CREATE TABLE seq_t (id INTEGER PRIMARY KEY AUTOINCREMENT, v TEXT)")
    rid2 = B.insert_returning_id(lite, "INSERT INTO seq_t (v) VALUES (?)", ("x",))
    assert rid2 == 1
    lite.close()


@needs_pg
def test_executescript_and_pragma_noop(pg_store):
    conn = pg_store()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS s1 (id TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS s2 (id TEXT PRIMARY KEY, ts TIMESTAMP);
        CREATE INDEX IF NOT EXISTS s2_ts ON s2(ts);
    """)
    assert conn.execute("PRAGMA journal_mode").fetchone() is None   # noop, not an error
    conn.execute("INSERT INTO s2 (id, ts) VALUES (?, ?)", ("a", "2026-08-05T00:00:00+00:00"))
    conn.commit()
    assert conn.execute("SELECT ts FROM s2").fetchone()[0] == "2026-08-05T00:00:00+00:00"
    conn.close()


@needs_pg
def test_bool_params_store_as_integers(pg_store):
    """sqlite3 adapts True → 1; the wrapper must match or flag-like columns diverge."""
    conn = pg_store()
    conn.execute("CREATE TABLE IF NOT EXISTS flags (k TEXT PRIMARY KEY, on_flag BOOLEAN)")
    conn.execute("INSERT INTO flags (k, on_flag) VALUES (?, ?)", ("a", True))
    conn.commit()
    assert conn.execute("SELECT on_flag FROM flags WHERE k=?", ("a",)).fetchone()[0] == 1
    conn.close()


@needs_pg
def test_user_version_round_trips_so_migrations_run_once(pg_store):
    """The migration framework gates on PRAGMA user_version. A no-op answer of 0
    forever would re-apply every migration on every connect — the version must
    persist per schema."""
    conn = pg_store()
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 0     # fresh schema
    conn.execute("PRAGMA user_version = 7")
    conn.commit()
    conn.close()
    conn2 = pg_store()
    assert conn2.execute("PRAGMA user_version").fetchone()[0] == 7    # survives reconnect
    conn2.close()


@needs_pg
def test_table_info_answers_in_sqlites_row_shape(pg_store):
    """add_column_if_missing reads column names from PRAGMA table_info row[1]; an
    empty answer would re-ALTER into a duplicate-column crash on second boot."""
    conn = pg_store()
    conn.execute("CREATE TABLE IF NOT EXISTS ti (id TEXT PRIMARY KEY, n INTEGER)")
    conn.commit()
    rows = conn.execute("PRAGMA table_info(ti)").fetchall()
    names = {r[1] for r in rows}
    assert names == {"id", "n"}
    assert [r[5] for r in rows if r[1] == "id"] == [1]                # pk flag
    assert conn.execute("PRAGMA table_info(never_created)").fetchall() == []


@needs_pg
def test_add_column_if_missing_is_idempotent_on_pg(pg_store):
    """The real migration helper, driven twice — second run must be a no-op."""
    from aughor.db.migrations import add_column_if_missing
    conn = pg_store()
    conn.execute("CREATE TABLE IF NOT EXISTS mig (id TEXT PRIMARY KEY)")
    conn.commit()
    add_column_if_missing(conn, "mig", "added", "TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(conn, "mig", "added", "TEXT NOT NULL DEFAULT ''")   # no crash
    conn.commit()
    assert "added" in {r[1] for r in conn.execute("PRAGMA table_info(mig)").fetchall()}
    conn.close()


@needs_pg
def test_run_migrations_applies_once_across_reconnects(pg_store):
    from aughor.db.migrations import Migration, add_column_if_missing, run_migrations
    applied = []
    migs = [Migration(2, "add col", lambda c: (applied.append(1), add_column_if_missing(
        c, "rm", "extra", "TEXT NOT NULL DEFAULT ''"))[1])]
    for expect_applied in (1, 1):     # second connect must NOT re-apply
        conn = pg_store()
        conn.execute("CREATE TABLE IF NOT EXISTS rm (id TEXT PRIMARY KEY)")
        conn.commit()
        run_migrations(conn, migs, store="probe")
        assert len(applied) == expect_applied
        conn.close()
