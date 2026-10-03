"""Arc DE, closing (ROADMAP §3.51) — what the waves left named and buildable from the build machine.

* The typed response carries each output column's SOURCE table column, from DE-4's lineage, so the grid can
  read a column of a JOINED statement live (DE-5c) and open its related rows (DE-5f) — until now both knew a
  table only when the statement read exactly one. A computed column has no one source and carries none.
* `_output_sources` reads the lineage rows the receipt already writes; no second tracer.
* The bound path honours the limit (pinned in `test_de5d_count_and_more.py`).
"""
from __future__ import annotations

import json

import duckdb
import pytest
from fastapi.testclient import TestClient

from aughor.api import app
from aughor.db import registry

client = TestClient(app)


@pytest.fixture()
def shop(tmp_path):
    db = tmp_path / "close.duckdb"
    c = duckdb.connect(str(db))
    c.execute("CREATE TABLE customers(id INTEGER PRIMARY KEY, name VARCHAR)")
    c.execute("INSERT INTO customers VALUES (1, 'Ada'), (2, 'Bo')")
    c.execute("CREATE TABLE orders(order_id INTEGER, buyer INTEGER REFERENCES customers(id), total DOUBLE)")
    c.execute("INSERT INTO orders VALUES (1, 1, 10), (2, 1, 20), (3, 2, 5)")
    c.close()
    cid = registry.add_connection("de-close", "duckdb", str(db))
    yield cid
    registry.delete_connection(cid)


def _run(cid: str, sql: str) -> dict:
    r = client.post("/query/run", json={"conn_id": cid, "sql": sql, "format": "typed", "limit": 500,
                                        "source": "query_workbench"})
    assert r.status_code == 200, r.text
    return r.json()


def test_a_joined_statements_columns_carry_their_own_table_column(shop):
    body = _run(shop, "SELECT o.order_id, c.name AS who, o.total * 2 AS doubled "
                      "FROM orders o JOIN customers c ON c.id = o.buyer ORDER BY o.order_id")
    assert body["error"] is None and body["format"] == "typed"
    cols = {c["name"]: c for c in body["columns_typed"]}
    assert cols["order_id"]["source"]["table"].split(".")[-1] == "orders"
    assert cols["order_id"]["source"]["column"] == "order_id"
    assert cols["who"]["source"]["table"].split(".")[-1] == "customers" and cols["who"]["source"]["column"] == "name"
    assert cols["who"]["source"]["confidence"] in ("certain", "likely")
    # A computed column reads one table column and is still not that column — it carries no source.
    assert "source" not in cols["doubled"]


def test_a_one_table_statement_carries_sources_too_and_the_shape_is_unchanged_otherwise(shop):
    body = _run(shop, "SELECT name FROM customers ORDER BY id")
    cols = {c["name"]: c for c in body["columns_typed"]}
    assert cols["name"]["source"]["column"] == "name"
    assert set(cols["name"]) == {"name", "type", "source"}
    plain = _run(shop, "SELECT 1 AS one")
    assert [set(c) for c in plain["columns_typed"]] == [{"name", "type"}], "a literal has no source and says nothing"


def test_output_sources_read_the_lineage_rows_the_receipt_writes():
    from aughor.routers.query import _output_sources
    from aughor.trust.lineage_edges import RELATION
    rows = [
        (RELATION, "column:orders.order_id", json.dumps({"roles": ["output"], "confidence": "certain", "as": ["order_id"]})),
        (RELATION, "column:customers.name", json.dumps({"roles": ["output", "filter"], "confidence": "likely", "as": ["who"]})),
        # two columns feed one alias: no single source
        (RELATION, "column:orders.total", json.dumps({"roles": ["output"], "confidence": "certain", "as": ["sum"]})),
        (RELATION, "column:orders.tax", json.dumps({"roles": ["output"], "confidence": "certain", "as": ["sum"]})),
        # one column, but the output is an expression over it: not the column's values
        (RELATION, "column:orders.qty", json.dumps({"roles": ["output"], "confidence": "certain", "as": ["twice"],
                                                     "computed": ["twice"]})),
        # read for a filter only: not an output
        (RELATION, "column:orders.buyer", json.dumps({"roles": ["join"], "confidence": "certain"})),
        ("lineage", "level:column", None),
    ]
    assert _output_sources(rows) == {
        "order_id": {"table": "orders", "column": "order_id", "confidence": "certain"},
        "who": {"table": "customers", "column": "name", "confidence": "likely"},
    }
    assert _output_sources([]) == {} and _output_sources(None) == {}


@pytest.mark.parametrize("expression, bare", [
    ("c.name", True), ("name", True), ('"t"."c"', True), ("name AS who", True), ("o.total AS t", True),
    ("o.total * 2 AS doubled", False), ("CAST(x AS INT) AS y", False), ("COUNT(*) AS n", False),
    ("LOWER(name)", False), ("", False),
])
def test_an_output_is_the_column_or_an_expression_over_it(expression, bare):
    from aughor.sql.lineage import is_bare_column
    assert is_bare_column(expression) is bare


def test_related_rows_open_from_a_joined_statements_column_through_its_source(shop):
    # The web reads the source off the typed response; the route takes the table column it names.
    body = _run(shop, "SELECT o.order_id, c.name AS who FROM orders o JOIN customers c ON c.id = o.buyer")
    src = {c["name"]: c.get("source") for c in body["columns_typed"]}["who"]
    r = client.get(f"/connections/{shop}/related-joins", params={"table": src["table"], "column": "id"})
    assert r.status_code == 200
    joins = {(j["other_table"].split(".")[-1], j["other_column"]): j for j in r.json()["joins"]}
    assert joins[("orders", "buyer")]["openable"] is True
    opened = client.post("/query/related", json={"conn_id": shop, "table": src["table"], "column": "id", "value": 1,
                                                 "other_table": "orders", "other_column": "buyer"}).json()
    assert opened["error"] is None and sorted(row[0] for row in opened["rows"]) == [1, 2]
