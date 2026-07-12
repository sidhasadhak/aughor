"""WP-4 — agents.db relocation + migration-framework adoption.

The store's default path was a bare ``"agents.db"``, so a live runtime DB materialized at
the repo root, escaped data/'s gitignore, and was tracked + churned in git. The default is
now ``data/agents.db``; a one-time shim relocates a pre-existing repo-root file (preserving
its agents); and the additive columns moved from an ad-hoc PRAGMA-probe ALTER block onto the
forward-only migration framework.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from aughor.user_agents import store


def _connect_at(monkeypatch, path: Path) -> sqlite3.Connection:
    monkeypatch.setenv("AUGHOR_AGENTS_DB", str(path))
    return store._connect()


def test_fresh_db_migrates_to_v4_with_all_columns(tmp_path, monkeypatch):
    conn = _connect_at(monkeypatch, tmp_path / "fresh.db")
    try:
        ver = conn.execute("PRAGMA user_version").fetchone()[0]
        cols = {r[1] for r in conn.execute("PRAGMA table_info(user_agents)")}
    finally:
        conn.close()
    assert ver == 4
    assert {"schema_scope", "pack_ids", "last_eval"} <= cols


def test_migration_is_idempotent_on_a_preexisting_columns_db(tmp_path, monkeypatch):
    # A DB that already grew the columns via the OLD ad-hoc ALTER, still at user_version 1.
    dbp = tmp_path / "legacy_cols.db"
    c = sqlite3.connect(str(dbp))
    c.execute(
        "CREATE TABLE user_agents (id TEXT PRIMARY KEY, name TEXT NOT NULL, "
        "instructions TEXT DEFAULT '', connection_id TEXT DEFAULT '', doc_ids TEXT DEFAULT '[]', "
        "owner TEXT DEFAULT '', enabled INTEGER DEFAULT 1, created_at TEXT, updated_at TEXT, "
        "schema_scope TEXT DEFAULT '', pack_ids TEXT DEFAULT '[]', last_eval TEXT DEFAULT '')"
    )
    c.execute("PRAGMA user_version=1")
    c.commit()
    c.close()
    # add_column_if_missing must no-op (not raise "duplicate column").
    conn = _connect_at(monkeypatch, dbp)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
    finally:
        conn.close()


def test_crud_roundtrip_on_migrated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_AGENTS_DB", str(tmp_path / "crud.db"))
    a = store.create_agent("Reloc Test", instructions="x", schema_scope="public")
    got = store.get_agent(a.id)
    assert got is not None and got.name == "Reloc Test" and got.schema_scope == "public"
    assert store.delete_agent(a.id) is True


def test_legacy_root_db_is_relocated_preserving_agents(tmp_path, monkeypatch):
    # Build a legacy repo-root-style agents.db with an agent row.
    legacy = tmp_path / "agents.db"
    c = sqlite3.connect(str(legacy))
    c.execute(
        "CREATE TABLE user_agents (id TEXT PRIMARY KEY, name TEXT NOT NULL, "
        "instructions TEXT DEFAULT '', connection_id TEXT DEFAULT '', doc_ids TEXT DEFAULT '[]', "
        "owner TEXT DEFAULT '', enabled INTEGER DEFAULT 1, created_at TEXT, updated_at TEXT)"
    )
    c.execute("INSERT INTO user_agents (id, name, created_at, updated_at) "
              "VALUES ('ua_legacy', 'Legacy Agent', 't', 't')")
    c.commit()
    c.close()

    target = tmp_path / "data" / "agents.db"
    # Simulate the real default-path context: no env override, CWD holds the legacy file.
    monkeypatch.delenv("AUGHOR_AGENTS_DB", raising=False)
    monkeypatch.chdir(tmp_path)                       # so Path("agents.db") == the legacy file
    monkeypatch.setattr(store, "_legacy_checked", False)

    store._maybe_adopt_legacy_db(target)

    assert target.exists(), "the legacy DB should have been relocated into data/"
    conn = sqlite3.connect(str(target))
    try:
        names = [r[0] for r in conn.execute("SELECT name FROM user_agents")]
    finally:
        conn.close()
    assert "Legacy Agent" in names


def test_relocation_is_skipped_when_env_override_is_set(tmp_path, monkeypatch):
    # With AUGHOR_AGENTS_DB set (tests / on-prem), the shim must never read a repo-root file.
    legacy = tmp_path / "agents.db"
    sqlite3.connect(str(legacy)).close()             # a legacy file exists...
    target = tmp_path / "data" / "agents.db"
    monkeypatch.setenv("AUGHOR_AGENTS_DB", str(target))   # ...but an override is set
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(store, "_legacy_checked", False)

    store._maybe_adopt_legacy_db(target)
    assert not target.exists()                        # skipped — no relocation happened
