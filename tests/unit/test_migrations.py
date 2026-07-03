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
    from aughor.verify import verdicts
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
