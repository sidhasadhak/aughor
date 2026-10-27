"""DATA-05 — the versioned SQLite migration runner.

Forward-only, version-gated on PRAGMA user_version, idempotent, and loud on failure
(unlike the old try/except-pass ALTER idiom).
"""
from __future__ import annotations

import sqlite3

import pytest

from aughor.db.migrations import Migration, add_column_if_missing, run_migrations


def _base(tmp_path):
    c = sqlite3.connect(tmp_path / "m.db")
    c.execute("CREATE TABLE t(id TEXT)")  # v1 base
    return c


def test_applies_pending_in_order(tmp_path):
    c = _base(tmp_path)
    migs = [
        Migration(2, "add a", lambda x: add_column_if_missing(x, "t", "a", "TEXT")),
        Migration(3, "add b", lambda x: add_column_if_missing(x, "t", "b", "INTEGER DEFAULT 0")),
    ]
    assert run_migrations(c, migs, store="t") == 3
    assert c.execute("PRAGMA user_version").fetchone()[0] == 3
    cols = {r[1] for r in c.execute("PRAGMA table_info(t)").fetchall()}
    assert {"a", "b"} <= cols


def test_skips_already_applied(tmp_path):
    c = _base(tmp_path)
    c.execute("PRAGMA user_version = 2")
    calls = []
    migs = [
        Migration(2, "skip", lambda x: calls.append(2)),
        Migration(3, "run", lambda x: calls.append(3)),
    ]
    run_migrations(c, migs, store="t")
    assert calls == [3]  # v2 is <= current → skipped
    assert c.execute("PRAGMA user_version").fetchone()[0] == 3


def test_second_run_is_a_noop(tmp_path):
    c = _base(tmp_path)
    migs = [Migration(2, "add a", lambda x: add_column_if_missing(x, "t", "a", "TEXT"))]
    run_migrations(c, migs, store="t")
    run_migrations(c, migs, store="t")  # no error, no re-apply
    assert c.execute("PRAGMA user_version").fetchone()[0] == 2


def test_add_column_if_missing_is_idempotent(tmp_path):
    c = _base(tmp_path)
    add_column_if_missing(c, "t", "x", "TEXT")
    add_column_if_missing(c, "t", "x", "TEXT")  # must not raise
    cols = {r[1] for r in c.execute("PRAGMA table_info(t)").fetchall()}
    assert "x" in cols


def test_failure_is_loud_and_leaves_version_at_last_good(tmp_path):
    c = _base(tmp_path)

    def _boom(_):
        raise RuntimeError("bad DDL")

    migs = [
        Migration(2, "ok", lambda x: add_column_if_missing(x, "t", "a", "TEXT")),
        Migration(3, "boom", _boom),
    ]
    with pytest.raises(RuntimeError):
        run_migrations(c, migs, store="t")
    # v2 committed, v3 failed → resumable from 2 (not silently swallowed)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 2


def test_converted_stores_migrate_cleanly():
    """Every store converted to the framework brings a fresh (isolated) DB to its
    latest version with the migrated columns present — idempotent, no error."""
    from aughor.metastore import store as ms
    from aughor.packs import bindings
    from aughor.security import audit
    from aughor.feedback import verdicts
    from aughor.workspace import store as ws

    def _prep(connect, ensure):
        c = connect()
        ensure(c)  # some stores ensure in _conn, others on first op — force it here
        return c

    cases = [
        (_prep(ms._conn, ms._ensure_schema),           "grants",           {"source"},                           2, "metastore"),
        (_prep(ws._conn, ws._ensure_schema),           "workspaces",       {"settings_override_json", "org_id"}, 3, "workspace"),
        (_prep(audit._connect, audit._ensure_schema),  "audit_log",        {"org_id"},                           2, "audit"),
        (_prep(verdicts._conn, verdicts._ensure_schema), "finding_verdicts", {"sql_source", "corrected_sql"},    2, "verdicts"),
        (_prep(bindings._conn, bindings._ensure_schema), "pack_bindings",    {"schema_name"},                    2, "pack_bindings"),
    ]
    for conn, table, need, version, name in cases:
        try:
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            assert need <= cols, f"{name}: missing {need - cols}"
            assert conn.execute("PRAGMA user_version").fetchone()[0] >= version, f"{name} user_version"
        finally:
            conn.close()


def test_ledger_schema_is_versioned():
    from aughor.kernel.ledger import Ledger

    led = Ledger.default()  # AUGHOR_SYSTEM_DB → temp in tests
    jcols = {r[1] for r in led._conn.execute("PRAGMA table_info(jobs)").fetchall()}
    assert {"metrics", "org_id"} <= jcols
    assert led._conn.execute("PRAGMA user_version").fetchone()[0] >= 3


# ── Arc SV-1 — a labelled backup before every migration (ROADMAP §3.63) ──────────────────────────────────────────────

@pytest.fixture
def report(monkeypatch):
    """The module, with this process's report emptied for the test — a store held back here must not leave /health
    degraded for the tests after it."""
    from aughor.db import migrations as m
    monkeypatch.setattr(m, "_HELD_BACK", {})
    monkeypatch.setattr(m, "_BACKED_UP", [])
    return m


def _store_with_rows(tmp_path, name="s.db"):
    c = sqlite3.connect(tmp_path / name)
    c.execute("CREATE TABLE t(id TEXT)")
    c.execute("INSERT INTO t VALUES ('a'), ('b')")
    c.commit()
    c.execute("PRAGMA user_version = 1")
    return c


def test_a_pending_migration_is_copied_before_it_runs(tmp_path, report):
    c = _store_with_rows(tmp_path)
    seen_before_first: list = []

    def _first(x):
        seen_before_first.extend(sorted((tmp_path / "backups").glob("s.db.*.v1-before-v3.bak")))
        add_column_if_missing(x, "t", "a", "TEXT")

    migs = [Migration(2, "a", _first), Migration(3, "b", lambda x: add_column_if_missing(x, "t", "b", "TEXT"))]
    assert run_migrations(c, migs, store="s") == 3
    assert len(seen_before_first) == 1                  # the copy existed before the first migration ran
    copy = sqlite3.connect(seen_before_first[0])
    assert copy.execute("PRAGMA user_version").fetchone()[0] == 1
    assert copy.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
    assert {r[1] for r in copy.execute("PRAGMA table_info(t)")} == {"id"}   # the store as it was
    done = report.migration_report()
    assert done["ok"] and done["backed_up"][0]["store"] == "s" and done["backed_up"][0]["to"] == 3


def test_a_wal_store_is_copied_to_one_self_contained_file(tmp_path, report):
    c = _store_with_rows(tmp_path)
    c.execute("PRAGMA journal_mode=WAL")               # every store the platform opens runs in WAL (db/sqlite_util.py)
    c.execute("INSERT INTO t VALUES ('c')")
    c.commit()
    run_migrations(c, [Migration(2, "a", lambda x: add_column_if_missing(x, "t", "a", "TEXT"))], store="s")
    files = sorted(p.name for p in (tmp_path / "backups").iterdir())
    assert len(files) == 1 and files[0].endswith(".bak"), files     # no -wal or -shm beside the copy
    copy = sqlite3.connect(tmp_path / "backups" / files[0])
    assert copy.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert copy.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 3  # what sat in the WAL is in the copy


def test_nothing_pending_copies_nothing(tmp_path, report):
    c = _store_with_rows(tmp_path)
    c.execute("PRAGMA user_version = 2")
    run_migrations(c, [Migration(2, "a", lambda x: None)], store="s")
    assert not (tmp_path / "backups").exists()


def test_a_store_with_no_rows_is_not_copied(tmp_path, report):
    c = _base(tmp_path)
    assert run_migrations(c, [Migration(2, "a", lambda x: add_column_if_missing(x, "t", "a", "TEXT"))], store="t") == 2
    assert not (tmp_path / "backups").exists()
    assert report.migration_report()["backed_up"] == []


def test_a_store_in_memory_is_not_copied(report):
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE t(id TEXT)")
    c.execute("INSERT INTO t VALUES ('a')")
    c.commit()
    assert run_migrations(c, [Migration(2, "a", lambda x: add_column_if_missing(x, "t", "a", "TEXT"))], store="m") == 2
    assert report.migration_report()["backed_up"] == []


def test_copies_are_numbered_and_never_overwrite(tmp_path, report):
    c = _store_with_rows(tmp_path)
    migs = [Migration(2, "a", lambda x: add_column_if_missing(x, "t", "a", "TEXT"))]
    run_migrations(c, migs, store="s")
    c.execute("PRAGMA user_version = 1")
    run_migrations(c, migs, store="s")
    names = sorted(p.name for p in (tmp_path / "backups").iterdir())
    assert len(names) == 2
    assert names[0].endswith("v1-before-v2-2.bak") or names[1].endswith("v1-before-v2-2.bak")


def test_a_copy_that_cannot_be_made_holds_the_migration_back(tmp_path, report):
    c = _store_with_rows(tmp_path)
    (tmp_path / "backups").write_text("a file where the folder would go")   # the copy cannot be made
    ran: list = []
    assert run_migrations(c, [Migration(2, "a", lambda x: ran.append(2))], store="s") == 1
    assert ran == []                                                # nothing migrated
    assert c.execute("PRAGMA user_version").fetchone()[0] == 1
    held = report.migration_report()
    assert not held["ok"] and "held at v1" in held["held_back"]["s"]


def test_a_copy_that_does_not_check_is_removed_and_holds_back(tmp_path, report, monkeypatch):
    c = _store_with_rows(tmp_path)
    real_connect = sqlite3.connect

    class _Lies:
        """A read-only open of the copy that answers quick_check with damage."""
        def __init__(self, inner):
            self._inner = inner

        def execute(self, sql, *a):
            if "quick_check" in sql:
                return real_connect(":memory:").execute("SELECT 'row 3 missing from index'")
            return self._inner.execute(sql, *a)

        def close(self):
            self._inner.close()

    def _connect(target, *a, **k):
        conn = real_connect(target, *a, **k)
        return _Lies(conn) if "mode=ro" in str(target) else conn

    monkeypatch.setattr(report.sqlite3, "connect", _connect)
    ran: list = []
    assert run_migrations(c, [Migration(2, "a", lambda x: ran.append(2))], store="s") == 1
    assert ran == []
    assert list((tmp_path / "backups").glob("*.bak")) == []      # the partial copy is gone
    assert "row 3 missing from index" in report.migration_report()["held_back"]["s"]


def test_health_names_a_store_held_back(tmp_path, report):
    from aughor.routers.system import health
    c = _store_with_rows(tmp_path)
    (tmp_path / "backups").write_text("blocked")
    run_migrations(c, [Migration(2, "a", lambda x: None)], store="held_store")
    body = health()
    assert body["status"] == "degraded"
    assert "held_store" in body["migrations"]["held_back"]
    assert "held at their old version" in body["migrations"]["detail"]
