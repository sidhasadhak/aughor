"""SE-8C — the multiselect's whole journey: a LIST value through POST /query/run.

The unit tests on `expand_list_params` prove the rewrite; this proves the ROUTE — the
typed workbench path, a real DuckDB file, a list bind — because the SE-3 F lesson is
that a capability proven on one connector class can still be a no-op on the one the
editor actually opens.
"""
from __future__ import annotations

import duckdb
import pytest
from fastapi.testclient import TestClient

from aughor.api import app
from aughor.db import registry

client = TestClient(app)


@pytest.fixture()
def conn(tmp_path):
    db = tmp_path / "listparams.duckdb"
    c = duckdb.connect(str(db))
    c.execute(
        "CREATE TABLE orders AS "
        "SELECT * FROM (VALUES ('PT', 10), ('ES', 20), ('FR', 30)) t(country, amount)"
    )
    c.close()
    cid = registry.add_connection("se8c-list", "duckdb", str(db))
    yield cid
    registry.delete_connection(cid)


def _run(conn_id, sql, params):
    return client.post("/query/run", json={
        "conn_id": conn_id, "sql": sql, "limit": 50,
        "format": "typed", "source": "query_workbench", "params": params,
    })


def test_a_list_param_filters_like_an_in_list(conn):
    r = _run(conn, "SELECT country, amount FROM orders WHERE country IN :c ORDER BY country", {"c": ["PT", "ES"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["error"] is None
    assert [row[0] for row in body["rows"]] == ["ES", "PT"]


def test_an_empty_list_matches_no_row(conn):
    r = _run(conn, "SELECT * FROM orders WHERE country IN :c", {"c": []})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["error"] is None
    assert body["row_count"] == 0


def test_scalars_still_bind_beside_a_list(conn):
    r = _run(conn, "SELECT country FROM orders WHERE country IN :c AND amount > :min", {"c": ["PT", "ES"], "min": 15})
    assert r.status_code == 200, r.text
    assert [row[0] for row in r.json()["rows"]] == ["ES"]


def test_param_defs_round_trip_through_saved_queries(conn):
    """SE-8C's other half: widget definitions save WITH the query and come back."""
    defs = {"c": {"widget": "multiselect", "options": ["PT", "ES", "FR"], "label": "Countries"}}
    r = client.post("/saved-queries", json={
        "connection_id": conn, "name": "by country",
        "sql": "SELECT * FROM orders WHERE country IN :c",
        "spec": {}, "param_defs": defs,
    })
    assert r.status_code == 201, r.text
    qid = r.json()["id"]
    assert r.json()["param_defs"] == defs

    got = client.get(f"/saved-queries/{qid}")
    assert got.json()["param_defs"] == defs
    # A spec-less query with widgets still routes to the SQL editor: spec stays {}.
    assert got.json()["spec"] == {}

    upd = client.put(f"/saved-queries/{qid}", json={"param_defs": {"c": {"widget": "text"}}})
    assert upd.json()["param_defs"] == {"c": {"widget": "text"}}
    client.delete(f"/saved-queries/{qid}")
