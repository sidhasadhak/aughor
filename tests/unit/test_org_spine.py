"""Phase 1 — the Org/tenant spine (PLATFORM_ARCHITECTURE.md, Invariant #1).

Every persisted store carries an ``org_id`` from day one. These tests prove the
three things that make that safe: the contextvar defaults to the bootstrap org and
scopes cleanly; the additive column migrations are idempotent on both fresh and
legacy (pre-org) databases; and writes stamp the current tenant.
"""
from __future__ import annotations

import sqlite3

import pytest

from aughor.org import (
    DEFAULT_ORG_ID,
    current_org_id,
    ensure_default_org,
    get_org,
    list_orgs,
    using_org,
)


# ── the context ───────────────────────────────────────────────────────────────

class TestOrgContext:
    def test_defaults_to_bootstrap_org(self):
        assert current_org_id() == DEFAULT_ORG_ID == "default"

    def test_using_org_scopes_and_restores(self):
        assert current_org_id() == "default"
        with using_org("acme") as scoped:
            assert scoped == "acme"
            assert current_org_id() == "acme"
        assert current_org_id() == "default"

    def test_empty_org_falls_back_to_default(self):
        with using_org(""):
            assert current_org_id() == "default"


# ── the org store + bootstrap ─────────────────────────────────────────────────

@pytest.fixture()
def org_store(tmp_path, monkeypatch):
    import aughor.org.store as store
    monkeypatch.setattr(store, "_DB_PATH", tmp_path / "orgs.db")
    return store


class TestOrgStore:
    def test_bootstrap_creates_then_is_idempotent(self, org_store):
        assert org_store.ensure_default_org() is True   # created
        assert org_store.ensure_default_org() is False  # already there
        org = org_store.get_org("default")
        assert org is not None and org.id == "default" and org.name == "Default"
        assert org.region == ""  # present from day one, empty with one region

    def test_create_get_list_roundtrip(self, org_store):
        org_store.ensure_default_org()
        org_store.create_org(name="Acme", org_id="acme", region="us-east")
        assert org_store.get_org("acme").region == "us-east"
        assert {o.id for o in org_store.list_orgs()} == {"default", "acme"}


# ── idempotent migrations: fresh + legacy DBs ─────────────────────────────────

class TestWorkspaceMigration:
    def test_legacy_db_gets_org_id_backfilled(self, tmp_path, monkeypatch):
        import aughor.workspace.store as store
        db = tmp_path / "workspaces.db"
        monkeypatch.setattr(store, "_DB_PATH", db)
        # Simulate an OLD database that predates org_id (and settings_override).
        c = sqlite3.connect(str(db))
        c.execute("""CREATE TABLE workspaces (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT DEFAULT '',
            connection_ids_json TEXT NOT NULL DEFAULT '[]', is_default INTEGER DEFAULT 0,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        c.execute("INSERT INTO workspaces VALUES ('w1','Legacy','','[]',0,'t','t')")
        c.commit()
        c.close()
        # Reading through the store triggers the idempotent migration.
        ws = store.get_workspace("w1")
        assert ws is not None and ws.org_id == "default"
        # And it's truly idempotent — a second open must not raise.
        assert store.get_workspace("w1").org_id == "default"

    def test_create_stamps_current_org(self, tmp_path, monkeypatch):
        import aughor.workspace.store as store
        monkeypatch.setattr(store, "_DB_PATH", tmp_path / "workspaces.db")
        default_ws = store.create_workspace(name="A", workspace_id="a")
        assert default_ws.org_id == "default"
        with using_org("acme"):
            scoped_ws = store.create_workspace(name="B", workspace_id="b")
        assert scoped_ws.org_id == "acme"
        # persisted, not just returned
        assert store.get_workspace("b").org_id == "acme"


class TestConnectionMigration:
    def test_legacy_registry_gets_org_id(self, tmp_path, monkeypatch):
        import aughor.db.registry as registry
        db = tmp_path / "connections.db"
        monkeypatch.setattr(registry, "REGISTRY_DB", db)
        c = sqlite3.connect(str(db))
        c.execute("""CREATE TABLE connections (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, conn_type TEXT NOT NULL,
            dsn_enc TEXT NOT NULL, meta TEXT DEFAULT '{}')""")
        c.execute("INSERT INTO connections VALUES ('c1','Legacy','duckdb','enc','{}')")
        c.commit()
        c.close()
        # _db() runs the migration on open.
        conn = registry._db()
        cols = {r[1] for r in conn.execute("PRAGMA table_info(connections)").fetchall()}
        assert "org_id" in cols
        row = conn.execute("SELECT org_id FROM connections WHERE id='c1'").fetchone()
        assert row[0] == "default"
        conn.close()

    def test_add_connection_stamps_org(self, tmp_path, monkeypatch):
        import aughor.db.registry as registry
        db = tmp_path / "connections.db"
        monkeypatch.setattr(registry, "REGISTRY_DB", db)
        with using_org("acme"):
            cid = registry.add_connection("X", "duckdb", "duckdb:///:memory:")
        conn = registry._db()
        row = conn.execute("SELECT org_id FROM connections WHERE id=?", (cid,)).fetchone()
        conn.close()
        assert row[0] == "acme"


class TestLedgerMigrationAndStamping:
    def test_fresh_ledger_has_org_id_columns(self, tmp_path):
        from aughor.kernel.ledger import Ledger
        led = Ledger(tmp_path / "system.db")
        for table in ("jobs", "artifacts", "lineage"):
            cols = {r[1] for r in led._conn.execute(f"PRAGMA table_info({table})").fetchall()}
            assert "org_id" in cols, f"{table} missing org_id"

    def test_reopen_is_idempotent(self, tmp_path):
        from aughor.kernel.ledger import Ledger
        path = tmp_path / "system.db"
        Ledger(path)
        # A second instance on the same file must not raise (migration re-runs clean).
        led2 = Ledger.__new__(Ledger)  # bypass the _instances cache for a true re-open
        led2.__init__(path)
        cols = {r[1] for r in led2._conn.execute("PRAGMA table_info(artifacts)").fetchall()}
        assert "org_id" in cols

    def test_artifact_and_lineage_stamp_org(self, tmp_path):
        from aughor.kernel.ledger import Ledger
        led = Ledger(tmp_path / "system.db")
        with using_org("acme"):
            led.artifact_write(
                "finding", "insight:c1:x", {"v": 1},
                lineage=[("source_sql", "SELECT 1", None)],
            )
        art = led._conn.execute("SELECT org_id FROM artifacts WHERE natural_key='insight:c1:x'").fetchone()
        lin = led._conn.execute("SELECT org_id FROM lineage").fetchone()
        assert art[0] == "acme" and lin[0] == "acme"

    def test_job_insert_stamps_org(self, tmp_path):
        from aughor.kernel.ledger import Ledger
        led = Ledger(tmp_path / "system.db")
        with using_org("acme"):
            led.job_insert({"id": "j1", "kind": "exploration", "state": "PENDING",
                            "attempt": 1, "created_at": "t"})
        row = led._conn.execute("SELECT org_id FROM jobs WHERE id='j1'").fetchone()
        assert row[0] == "acme"


class TestAuditMigrationAndStamping:
    def test_legacy_audit_gets_org_id_and_log_stamps(self, tmp_path, monkeypatch):
        import aughor.security.audit as audit
        db = tmp_path / "audit.db"
        monkeypatch.setattr(audit, "_DB_PATH", db)
        # Legacy audit_log without org_id.
        c = sqlite3.connect(str(db))
        c.execute("""CREATE TABLE audit_log (
            id TEXT PRIMARY KEY, ts TEXT NOT NULL, connection_id TEXT NOT NULL,
            hypothesis_id TEXT NOT NULL DEFAULT '', sql_digest TEXT NOT NULL,
            sql_full TEXT NOT NULL, verdict TEXT NOT NULL DEFAULT 'safe',
            row_count INTEGER NOT NULL DEFAULT 0, duration_ms REAL NOT NULL DEFAULT 0,
            pii_redacted INTEGER NOT NULL DEFAULT 0, error TEXT)""")
        c.execute("INSERT INTO audit_log (id, ts, connection_id, sql_digest, sql_full) "
                  "VALUES ('a0','t','c1','SELECT 1','SELECT 1')")
        c.commit()
        c.close()
        with using_org("acme"):
            audit.AuditLogger.log(connection_id="c1", sql="SELECT 2")
        c = sqlite3.connect(str(db))
        legacy = c.execute("SELECT org_id FROM audit_log WHERE id='a0'").fetchone()
        fresh = c.execute("SELECT org_id FROM audit_log WHERE sql_full='SELECT 2'").fetchone()
        c.close()
        assert legacy[0] == "default"   # back-filled
        assert fresh[0] == "acme"       # stamped from context


class TestMeteringStamping:
    def test_register_job_stamps_org(self):
        from aughor.kernel import metering
        token = metering.start()
        try:
            with using_org("acme"):
                metering.register_job("job-x")
            assert metering.metrics_for_job("job-x").org_id == "acme"
        finally:
            metering.unregister_job("job-x")
            metering.reset(token)
