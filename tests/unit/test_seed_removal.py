"""Removed-seed tombstone — a sample schema/table the user deletes must STAY deleted across
the per-request connector rebuild (the bug: `ecommerce` re-materialized from the seed DB on
every construction, so removal never stuck). Hermetic: a throwaway seed DuckDB + an isolated
upload root."""
from __future__ import annotations

import json

import duckdb
import pytest

from aughor.connectors.file.local_upload import LocalUploadConnection
from aughor.platform import vending


@pytest.fixture
def seed_db(tmp_path):
    p = tmp_path / "seed.duckdb"
    con = duckdb.connect(str(p))
    con.execute("CREATE SCHEMA demo")
    con.execute("CREATE TABLE demo.orders AS SELECT * FROM range(3) t(id)")
    con.execute("CREATE TABLE demo.items  AS SELECT * FROM range(3) t(id)")
    con.close()
    return str(p)


@pytest.fixture(autouse=True)
def _isolate_uploads(tmp_path, monkeypatch):
    # Patch the canonical storage root (the vending seam); the connector resolves
    # its upload dir through vend_storage(), which reads this.
    monkeypatch.setattr(vending, "STORAGE_ROOT", tmp_path / "uploads")


def _schemas(c):
    return sorted(r[0] for r in c._duckdb.execute(
        "select distinct schema_name from duckdb_tables() where internal=false").fetchall())


def _tables(c, schema):
    return sorted(r[0] for r in c._duckdb.execute(
        f"select table_name from duckdb_tables() where schema_name='{schema}'").fetchall())


def _conn(seed):
    return LocalUploadConnection(connection_id="ws", meta={"seed_duckdb": seed})


def test_seed_schema_is_materialized(seed_db):
    c = _conn(seed_db)
    assert "demo" in _schemas(c)
    c.close()


def test_dropped_seed_schema_stays_removed_across_rebuild(seed_db):
    c = _conn(seed_db)
    c.drop_schema("demo")
    c.close()
    c2 = _conn(seed_db)                 # a fresh construction = the next request
    assert "demo" not in _schemas(c2)   # the bug was that it came back here
    c2.close()


def test_tombstone_is_persisted(seed_db, tmp_path):
    c = _conn(seed_db)
    c.drop_schema("demo")
    c.close()
    # Storage is tenant-pathed: {root}/{org_id}/{conn_id}/...
    p = tmp_path / "uploads" / "default" / "ws" / "_removed_seeds.json"
    assert p.exists() and "demo" in json.loads(p.read_text())["schemas"]


def test_restore_brings_the_seed_back(seed_db):
    c = _conn(seed_db); c.drop_schema("demo"); c.close()
    c2 = _conn(seed_db); c2.restore_seeds(); c2.close()
    c3 = _conn(seed_db)
    assert "demo" in _schemas(c3)
    c3.close()


def test_recreating_the_schema_lifts_the_tombstone(seed_db):
    c = _conn(seed_db); c.drop_schema("demo"); c.close()
    c2 = _conn(seed_db); c2.create_schema("demo"); c2.close()
    c3 = _conn(seed_db)
    assert "demo" in _schemas(c3)
    c3.close()


def test_deleting_one_seed_table_sticks_and_keeps_siblings(seed_db):
    c = _conn(seed_db)
    c.delete_table("orders", "demo")
    c.close()
    c2 = _conn(seed_db)
    tbls = _tables(c2, "demo")
    assert "orders" not in tbls and "items" in tbls   # only the deleted table stays gone
    c2.close()


def test_make_reader_clone_does_not_crash_and_materializes_seed(seed_db):
    """The parallel-lens/wave paths call make_reader() per branch. The clone bypasses __init__, so it
    must set the seed tombstones itself before seeding — otherwise _seed_from_duckdb raised
    AttributeError('_removed_seed_schemas') on every attach (fail-open, but log-spamming)."""
    c = _conn(seed_db)
    reader = c.make_reader()                              # must NOT raise
    assert hasattr(reader, "_removed_seed_schemas") and hasattr(reader, "_removed_seed_tables")
    assert "demo" in _schemas(reader)                     # seed still materialized on the clone
    reader.close(); c.close()


def test_make_reader_clone_honours_the_seed_tombstone(seed_db):
    """A user-removed seed schema must STAY removed on a reader clone (the tombstone is copied), not
    silently re-materialize because the clone skipped the tombstone filter."""
    c = _conn(seed_db)
    c.drop_schema("demo")
    reader = c.make_reader()
    assert "demo" in reader._removed_seed_schemas         # tombstone carried onto the clone
    assert "demo" not in _schemas(reader)                 # and honoured — not re-materialized
    reader.close(); c.close()
