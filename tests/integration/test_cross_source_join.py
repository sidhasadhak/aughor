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


# test_cross_source_join_disabled_when_forced_off was DELETED with its flag (flag
# endgame Wave 2, 2026-08-06, receipt 41ec864723fb): the route is invocation-gated —
# field validation and the SQL safety gate below are the surviving controls.


def test_cross_source_join_end_to_end(client: TestClient, monkeypatch, tmp_path):
    from aughor.db import registry

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


def test_cross_source_join_driver_exceeds_500_row_cap(client: TestClient, monkeypatch, tmp_path):
    """The LEFT driver is read via execute_bounded, so a >500-row join isn't silently truncated."""
    from aughor.db import registry

    lpath = tmp_path / "big_left.duckdb"
    lcon = duckdb.connect(str(lpath))
    lcon.execute("CREATE TABLE orders (cust VARCHAR)")
    lcon.executemany("INSERT INTO orders VALUES (?)", [[str(i)] for i in range(600)])
    lcon.close()
    rpath = tmp_path / "big_right.duckdb"
    rcon = duckdb.connect(str(rpath))
    rcon.execute("CREATE TABLE customers (cust VARCHAR, name VARCHAR)")
    rcon.executemany("INSERT INTO customers VALUES (?, ?)", [[str(i), f"n{i}"] for i in range(600)])
    rcon.close()
    lid = registry.add_connection("xj-l600", "duckdb", str(lpath))
    rid = registry.add_connection("xj-r600", "duckdb", str(rpath))

    resp = client.post("/query/cross-source-join", json={
        "left_conn_id": lid, "left_sql": "SELECT cust FROM orders",
        "left_key": "cust", "right_conn_id": rid, "right_table": "customers", "right_key": "cust",
        "right_cols": ["cust", "name"],
    })

    assert resp.status_code == 200
    assert resp.json()["row_count"] == 600     # driver + right both read past the old 500 cap


def test_cross_source_join_validates_required_fields(client: TestClient, monkeypatch):
    resp = client.post("/query/cross-source-join", json={
        "left_conn_id": "a", "left_sql": "  ", "left_key": "k",
        "right_conn_id": "b", "right_table": "t", "right_key": "k",
    })
    assert resp.status_code == 400
    assert "left_sql" in resp.json()["detail"]


def test_the_joined_answer_passes_redaction_the_budget_and_the_audit_on_both_connections(
        client: TestClient, monkeypatch, tmp_path):
    """Both reads run under plumbing labels, which skip the post-execution gate, so the joined answer is posted once
    for the two connections it read: a PII column from the RIGHT side is redacted, the right connection's stricter
    row budget applies, and each connection's audit trail records the join (Arc ON leftovers, F7)."""
    from aughor.db import registry
    from aughor.security import sandbox
    from aughor.security.audit import AuditLogger

    lp = _duck_file(
        tmp_path / "pii_left.duckdb",
        "CREATE TABLE orders (order_id INT, cust VARCHAR)",
        "INSERT INTO orders VALUES (1,'C1'),(2,'C2'),(3,'C1')",
    )
    rp = _duck_file(
        tmp_path / "pii_right.duckdb",
        "CREATE TABLE customers (cust VARCHAR, email VARCHAR)",
        "INSERT INTO customers VALUES ('C1','alice@example.com'),('C2','bob@example.com')",
    )
    lid = registry.add_connection("xj-pii-left", "duckdb", lp)
    rid = registry.add_connection("xj-pii-right", "duckdb", rp)
    body = {
        "left_conn_id": lid, "left_sql": "SELECT order_id, cust FROM orders ORDER BY order_id", "left_key": "cust",
        "right_conn_id": rid, "right_table": "customers", "right_key": "cust", "right_cols": ["cust", "email"],
    }

    data = client.post("/query/cross-source-join", json=body).json()
    assert data["error"] is None and data["row_count"] == 3
    assert [r[data["columns"].index("email")] for r in data["rows"]] == ["[REDACTED]"] * 3
    for connection_id in (lid, rid):
        records = AuditLogger.recent(50, connection_id=connection_id, label="cross_source_join")
        assert any(r["verdict"] == "safe" and r["row_count"] == 3 for r in records), connection_id

    monkeypatch.setitem(sandbox._REGISTRY, rid, sandbox.QueryBudget(max_rows=1))
    capped = client.post("/query/cross-source-join", json=body).json()
    assert len(capped["rows"]) == 1 and capped["row_count"] == 3


def test_the_right_connection_passes_the_pre_execution_gate(client: TestClient, monkeypatch, tmp_path):
    """The right side is read under a plumbing label too, so its connection is gated before the read: a connection the
    gate refuses refuses the join, with the gate's reason (Arc ON leftovers, F7)."""
    import aughor.db.connection as C
    from aughor.control_plane.contracts.execution import QueryResult
    from aughor.db import registry

    lp = _duck_file(tmp_path / "gate_left.duckdb", "CREATE TABLE orders (cust VARCHAR)", "INSERT INTO orders VALUES ('C1')")
    rp = _duck_file(tmp_path / "gate_right.duckdb", "CREATE TABLE customers (cust VARCHAR, name VARCHAR)",
                    "INSERT INTO customers VALUES ('C1','Alice')")
    lid = registry.add_connection("xj-gate-left", "duckdb", lp)
    rid = registry.add_connection("xj-gate-right", "duckdb", rp)
    real_pre = C.security_pre

    def pre(connection_id, label, sql):
        if connection_id == rid:
            return QueryResult(hypothesis_id=label, sql=sql, columns=[], rows=[], row_count=0,
                               error="[BLOCKED] by policy")
        return real_pre(connection_id, label, sql)

    monkeypatch.setattr(C, "security_pre", pre)
    data = client.post("/query/cross-source-join", json={
        "left_conn_id": lid, "left_sql": "SELECT cust FROM orders", "left_key": "cust",
        "right_conn_id": rid, "right_table": "customers", "right_key": "cust", "right_cols": ["cust", "name"],
    }).json()
    assert data["rows"] == [] and data["error"] == "[BLOCKED] by policy"


def test_a_join_on_a_key_that_looks_like_pii_matches_before_the_answer_is_redacted(client: TestClient, tmp_path):
    """The reads are plumbing and only the ANSWER is redacted: a key that looks like PII (an email) still meets its
    rows, where a right read redacted before the join met none of them (Arc ON leftovers, F7)."""
    from aughor.db import registry

    lp = _duck_file(
        tmp_path / "email_left.duckdb",
        "CREATE TABLE orders (order_id INT, email VARCHAR)",
        "INSERT INTO orders VALUES (1,'alice@example.com'),(2,'bob@example.com'),(3,'alice@example.com')",
    )
    rp = _duck_file(
        tmp_path / "email_right.duckdb",
        "CREATE TABLE customers (email VARCHAR, tier VARCHAR)",
        "INSERT INTO customers VALUES ('alice@example.com','gold'),('bob@example.com','silver')",
    )
    lid = registry.add_connection("xj-email-left", "duckdb", lp)
    rid = registry.add_connection("xj-email-right", "duckdb", rp)
    data = client.post("/query/cross-source-join", json={
        "left_conn_id": lid, "left_sql": "SELECT order_id, email FROM orders ORDER BY order_id", "left_key": "email",
        "right_conn_id": rid, "right_table": "customers", "right_key": "email", "right_cols": ["email", "tier"],
    }).json()
    assert data["error"] is None and data["row_count"] == 3
    assert [r[data["columns"].index("tier")] for r in data["rows"]] == ["gold", "silver", "gold"]
    assert [r[data["columns"].index("email")] for r in data["rows"]] == ["[REDACTED]"] * 3
