"""DE-3c (ROADMAP §3.51) — typed metadata with a coverage table; declared foreign keys lead the
join inference and are still checked against values.

Measured first: no engine read a declared key or a comment (finding 8); DuckDB's DESCRIBE and
SQLite's PRAGMA fetched the key flag and dropped it; `duckdb_constraints()` and the comment
columns answer directly. The receipt the plan asked for — a schema with declared keys whose
join inference shows them — is here on DuckDB and SQLite, which the test can run; the
Postgres and MySQL recipes parse in their dialects and wait for a live engine.
"""
from __future__ import annotations

import sqlite3

import duckdb
import pytest
import sqlglot

from aughor.connectors import declarations as D
from aughor.connectors.declarations import METADATA_FACTS
from aughor.db.metadata import (
    DeclaredKey,
    MetadataRead,
    declared_join_candidates,
    engine_type_of,
    read_declared_metadata,
)
from aughor.tools.schema import compute_join_map

STATUSES = {"supported", "unsupported", "unknown"}


# ── the coverage table: every engine states its row ─────────────────────────────────

@pytest.mark.parametrize("decl", D.ENGINES, ids=lambda e: e.type)
def test_every_engine_states_all_four_facts_and_why(decl):
    assert set(decl.metadata_facts) == set(METADATA_FACTS)
    assert set(decl.metadata_facts.values()) <= STATUSES
    if any(v != "supported" for v in decl.metadata_facts.values()):
        assert decl.metadata_detail, f"{decl.type}: a fact that is not supported says why"
    # A read the declaration calls supported must have a recipe for its dialect.
    from aughor.db.metadata import _RECIPES
    if any(decl.metadata_facts[f] == "supported" for f in ("primary_keys", "foreign_keys", "comments")):
        assert decl.dialect in _RECIPES, f"{decl.type} declares a supported read with no recipe"


def test_the_coverage_rows_are_in_the_catalog_and_the_web_map():
    import json
    from scripts.gen_connector_catalog import CATALOG, WEB_GEN
    cat = {e["type"]: e for e in json.loads(CATALOG.read_text())["types"]}
    assert cat["duckdb"]["metadata"] == {"columns": "supported", "primary_keys": "supported",
                                         "foreign_keys": "supported", "comments": "supported"}
    assert cat["sqlite"]["metadata"]["comments"] == "unsupported"
    assert cat["bigquery"]["metadata"]["primary_keys"] == "unknown" and "read yet" in cat["bigquery"]["metadata_detail"]
    assert cat["trino"]["metadata"]["foreign_keys"] == "unsupported"
    assert '"metadata": {"columns": "supported", "primary_keys": "supported"' in WEB_GEN.read_text()


# ── the typed read, live on DuckDB ──────────────────────────────────────────────────

@pytest.fixture
def duck(tmp_path):
    from aughor.db.connection import DuckDBConnection
    path = tmp_path / "keys.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY, country TEXT)")
    con.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, buyer INTEGER REFERENCES customers(id), status TEXT)")
    con.execute("CREATE TABLE events (id INTEGER, customer_id INTEGER, kind TEXT)")
    con.execute("COMMENT ON COLUMN orders.status IS 'the order state'")
    con.execute("COMMENT ON TABLE orders IS 'one row per order'")
    con.execute("INSERT INTO customers VALUES (1, 'PT'), (2, 'ES')")
    con.execute("INSERT INTO orders VALUES (10, 1, 'Complete'), (11, 2, 'Shipped')")
    con.close()
    db = DuckDBConnection(str(path))
    yield db
    db.close()


def test_duckdb_reads_its_declared_keys_and_comments_through_the_door(duck):
    assert engine_type_of(duck) == "duckdb"
    read = read_declared_metadata(duck)
    assert read.facts == {"columns": "supported", "primary_keys": "supported",
                          "foreign_keys": "supported", "comments": "supported"}, read.detail
    assert {(k.table, k.columns) for k in read.primary_keys} == {("customers", ("id",)), ("orders", ("id",))}
    (fk,) = read.foreign_keys
    assert fk == DeclaredKey("orders", ("buyer",), "foreign", "customers", ("id",))
    assert read.comments == {"orders.status": "the order state", "orders": "one row per order"}


def test_a_declared_key_no_name_would_find_leads_the_join_map(duck):
    """`orders.buyer → customers.id` shares no name root; the name pass would never propose it,
    and would instead join `events.customer_id → customers.id`. The declared key is seated first,
    and the name pass still fills in what the schema did not declare."""
    table_cols = {"customers": ["id", "country"], "orders": ["id", "buyer", "status"],
                  "events": ["id", "customer_id", "kind"]}
    name_only = compute_join_map(table_cols)
    assert not any(j["t1"] == "orders" and j["c1"] == "buyer" for j in name_only["joins"])

    read = read_declared_metadata(duck)
    declared = declared_join_candidates(read, table_cols)
    assert declared == [{"t1": "orders", "c1": "buyer", "t2": "customers", "c2": "id", "match": "declared"}]
    jmap = compute_join_map(table_cols, declared=declared)
    assert jmap["joins"][0] == declared[0], "the declared key is the first edge"
    assert any(j["t1"] == "events" and j["t2"] == "customers" and j["match"] != "declared" for j in jmap["joins"])
    assert not any(j["t1"] == "orders" and j["t2"] == "customers" and j["match"] != "declared" for j in jmap["joins"]), \
        "the pair is claimed by the declaration; no name match takes it"


def test_join_map_for_reads_the_engine_and_falls_back_to_names_when_it_cannot(duck):
    from aughor.tools.schema import join_map_for
    table_cols = {"customers": ["id", "country"], "orders": ["id", "buyer", "status"]}
    jmap = join_map_for(duck, table_cols, cache_key="de3c-duck")
    assert jmap["joins"][0]["match"] == "declared"

    class Broken:
        dialect = "duckdb"
        def execute(self, *a, **k):
            raise RuntimeError("no catalog here")
    jmap = join_map_for(Broken(), {"orders": ["id", "customer_id"], "customers": ["id"]}, cache_key="de3c-broken")
    assert jmap["joins"] and all(j["match"] != "declared" for j in jmap["joins"])


def test_a_declared_fk_matched_by_bare_name_when_the_schema_text_is_qualified(duck):
    read = read_declared_metadata(duck)
    table_cols = {"main.customers": ["id", "country"], "main.orders": ["id", "buyer", "status"]}
    assert declared_join_candidates(read, table_cols) == [
        {"t1": "main.orders", "c1": "buyer", "t2": "main.customers", "c2": "id", "match": "declared"}]


# ── SQLite, live ─────────────────────────────────────────────────────────────────────

def test_sqlite_reads_keys_and_says_comments_are_not_a_thing(tmp_path):
    from aughor.connectors.file.sqlite import SQLiteConnection
    path = tmp_path / "k.sqlite"
    con = sqlite3.connect(str(path))
    con.executescript("""
        CREATE TABLE customers (id INTEGER PRIMARY KEY, country TEXT);
        CREATE TABLE orders (id INTEGER PRIMARY KEY, buyer INTEGER REFERENCES customers(id), status TEXT);
        INSERT INTO customers VALUES (1, 'PT'); INSERT INTO orders VALUES (10, 1, 'x');
    """)
    con.commit()
    con.close()
    db = SQLiteConnection(dsn=str(path), connection_id="de3c-sqlite")
    try:
        read = read_declared_metadata(db)
    finally:
        db.close()
    assert read.facts["comments"] == "unsupported" and "no comments" in read.detail["comments"]
    assert read.facts["primary_keys"] == "supported" and read.facts["foreign_keys"] == "supported", read.detail
    assert {(k.table, k.columns) for k in read.primary_keys} == {("customers", ("id",)), ("orders", ("id",))}
    assert read.foreign_keys == [DeclaredKey("orders", ("buyer",), "foreign", "customers", ("id",))]
    assert read.comments == {}


# ── the three answers are told apart ─────────────────────────────────────────────────

def test_unsupported_and_unknown_are_said_not_implied():
    class Upload:
        dialect = "duckdb"
    from aughor.connectors.file.local_upload import LocalUploadConnection
    assert engine_type_of(LocalUploadConnection.__new__(LocalUploadConnection)) == "local_upload"
    # A class with no declaration: unknown, and it says so.
    read = read_declared_metadata(Upload())
    assert read.facts["primary_keys"] == "unknown" and "no declaration" in read.detail["primary_keys"]

    class Lost:
        dialect = "duckdb"
        def execute(self, *a, **k):
            raise RuntimeError("catalog unreachable")
    from aughor.db import metadata as M
    M._TYPE_BY_CLASS["Lost"] = "duckdb"
    try:
        read = read_declared_metadata(Lost())
    finally:
        M._TYPE_BY_CLASS.pop("Lost", None)
    assert read.facts["primary_keys"] == "unknown" and "read failed" in read.detail["primary_keys"]
    assert read.facts["columns"] == "supported"


def test_postgres_and_mysql_recipes_parse_in_their_dialects():
    """Short of a live engine: the statements the recipes run are valid SQL for the engine."""
    import inspect
    from aughor.db import metadata as M
    for fn, dialect in ((M._read_postgres, "postgres"), (M._read_mysql, "mysql")):
        src = inspect.getsource(fn)
        statements = [s for s in src.split('"""')[1::2] if "SELECT" in s]
        assert len(statements) >= 3, dialect
        for s in statements:
            sqlglot.parse_one(s, read=dialect)


# ── the ontology keeps a declared key the values dispute, and says so ───────────────

def test_a_declared_edge_the_values_dispute_is_kept_with_its_overlap():
    from types import SimpleNamespace
    from aughor.ontology.builder import apply_join_verifications
    from aughor.sql.join_guard import VerifiedJoin, render_verified_joins

    rel_declared = SimpleNamespace(from_table="orders", from_col="buyer", to_table="customers", to_col="id",
                                   from_entity="order", to_entity="customer", join_confidence="declared", value_overlap=None)
    rel_named = SimpleNamespace(from_table="events", from_col="customer_id", to_table="customers", to_col="id",
                                from_entity="event", to_entity="customer", join_confidence="exact", value_overlap=None)
    graph = SimpleNamespace(connection_id="c", relationships={"r1": rel_declared, "r2": rel_named},
                            entities={"order": 1, "customer": 1, "event": 1}, relationship_index={})
    rejected = [VerifiedJoin("orders", "buyer", "customers", "id", overlap=0.02, match="declared"),
                VerifiedJoin("events", "customer_id", "customers", "id", overlap=0.0, match="exact")]
    apply_join_verifications(graph, verified=[], rejected=rejected)
    assert set(graph.relationships) == {"r1"}, "the name coincidence is dropped; the declared key stays"
    assert graph.relationships["r1"].join_confidence == "declared" and graph.relationships["r1"].value_overlap == 0.02

    text = render_verified_joins([VerifiedJoin("a", "x", "b", "id", overlap=0.98, match="declared")], rejected[:1])
    assert "98% value overlap; declared foreign key" in text
    assert "DECLARED foreign key, but only 2% value overlap" in text


def test_metadata_read_as_dict_is_json_shaped():
    read = MetadataRead(engine="duckdb", strategy="information_schema",
                        facts={f: "supported" for f in METADATA_FACTS}, detail={f: "" for f in METADATA_FACTS},
                        keys=[DeclaredKey("orders", ("buyer",), "foreign", "customers", ("id",))],
                        comments={"orders": "one row per order"})
    d = read.as_dict()
    assert d["keys"][0] == {"table": "orders", "columns": ["buyer"], "kind": "foreign", "ref_table": "customers", "ref_columns": ["id"]}
    assert d["detail"] == {} and d["comments"] == {"orders": "one row per order"}
