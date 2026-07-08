"""Integration tests for POST /query/cross-source-join (Rec 2, Stage 2 wiring).

Registers two real DuckDB file connections and joins across them through the live API — proving the
batched-foreach engine is reachable end-to-end and flag-gated.
"""
from __future__ import annotations

import duckdb
from fastapi.testclient import TestClient


def _duck_file(path, *stmts):
    con = duckdb.connect(str(path))
    for s in stmts:
        con.execute(s)
    con.close()
    return str(path)


def test_cross_source_join_disabled_by_default(client: TestClient, monkeypatch):
    monkeypatch.delenv("AUGHOR_FEDERATION_REMOTE_JOIN", raising=False)
    resp = client.post("/query/cross-source-join", json={
        "left_conn_id": "x", "left_sql": "SELECT 1", "left_key": "a",
        "right_conn_id": "y", "right_table": "t", "right_key": "b",
    })
    assert resp.status_code == 404


def test_cross_source_join_end_to_end(client: TestClient, monkeypatch, tmp_path):
    from aughor.db import registry
    monkeypatch.setenv("AUGHOR_FEDERATION_REMOTE_JOIN", "1")

    lp = _duck_file(
        tmp_path / "left.duckdb",
        "CREATE TABLE orders (order_id INT, cust VARCHAR)",
        "INSERT INTO orders VALUES (1,'C1'),(2,'C2'),(3,'C1')",
    )
    rp = _duck_file(
        tmp_path / "right.duckdb",
        "CREATE TABLE customers (cust VARCHAR, name VARCHAR)",
        "INSERT INTO customers VALUES ('C1','Alice'),('C2','Bob')",
    )
    lid = registry.add_connection("xj-left", "duckdb", lp)
    rid = registry.add_connection("xj-right", "duckdb", rp)

    resp = client.post("/query/cross-source-join", json={
        "left_conn_id": lid,
        "left_sql": "SELECT order_id, cust FROM orders ORDER BY order_id",
        "left_key": "cust",
        "right_conn_id": rid, "right_table": "customers", "right_key": "cust",
        "right_cols": ["cust", "name"],
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["error"] is None
    assert data["row_count"] == 3                        # orders 1,2,3 joined across the two sources
    assert "name" in data["columns"]
    names = [r[data["columns"].index("name")] for r in data["rows"]]
    assert names == ["Alice", "Bob", "Alice"]


def test_cross_source_join_validates_required_fields(client: TestClient, monkeypatch):
    monkeypatch.setenv("AUGHOR_FEDERATION_REMOTE_JOIN", "1")
    resp = client.post("/query/cross-source-join", json={
        "left_conn_id": "a", "left_sql": "  ", "left_key": "k",
        "right_conn_id": "b", "right_table": "t", "right_key": "k",
    })
    assert resp.status_code == 400
    assert "left_sql" in resp.json()["detail"]
