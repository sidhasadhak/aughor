"""Integration tests for the cross-source federated planner (Rec 2, Stage 3, N-source).

The LLM plan step is faked (returns a canned FederatedPlan); everything after it — deterministic
validation and the folded batched-foreach execution across real registered DuckDB sources — runs for real.
"""
from __future__ import annotations

import duckdb
from fastapi.testclient import TestClient

import aughor.llm.provider as provider_mod
from aughor.agent.federated_planner import FederatedPlan, FederatedStep, validate_plan
from aughor.db import registry


def _duck_file(path, *stmts):
    con = duckdb.connect(str(path))
    for s in stmts:
        con.execute(s)
    con.close()
    return str(path)


def _two_sources(tmp_path):
    lp = _duck_file(
        tmp_path / "orders.duckdb",
        "CREATE TABLE orders (order_id INT, cust VARCHAR, amount INT)",
        "INSERT INTO orders VALUES (1,'C1',100),(2,'C2',50),(3,'C1',30)",
    )
    rp = _duck_file(
        tmp_path / "crm.duckdb",
        "CREATE TABLE customers (cust VARCHAR, region VARCHAR)",
        "INSERT INTO customers VALUES ('C1','EU'),('C2','US')",
    )
    return [registry.add_connection("fp-a", "duckdb", lp), registry.add_connection("fp-b", "duckdb", rp)]


def _three_sources(tmp_path):
    a = _duck_file(tmp_path / "orders3.duckdb",
                   "CREATE TABLE orders (order_id INT, cust VARCHAR)",
                   "INSERT INTO orders VALUES (1,'C1'),(2,'C2')")
    b = _duck_file(tmp_path / "crm3.duckdb",
                   "CREATE TABLE customers (cust VARCHAR, region VARCHAR)",
                   "INSERT INTO customers VALUES ('C1','EU'),('C2','US')")
    c = _duck_file(tmp_path / "geo3.duckdb",
                   "CREATE TABLE regions (region VARCHAR, manager VARCHAR)",
                   "INSERT INTO regions VALUES ('EU','Alice'),('US','Bob')")
    return [registry.add_connection("fp3-0", "duckdb", a),
            registry.add_connection("fp3-1", "duckdb", b),
            registry.add_connection("fp3-2", "duckdb", c)]


def _fake_planner(monkeypatch, plan: FederatedPlan):
    class _Fake:
        def complete(self, *, system, user, response_model):
            assert response_model is FederatedPlan
            return plan
    monkeypatch.setattr(provider_mod, "get_provider", lambda role="coder", **kw: _Fake())


# ── the endpoint ─────────────────────────────────────────────────────────────

def test_federated_answer_disabled_by_default(client: TestClient, monkeypatch):
    monkeypatch.delenv("AUGHOR_FEDERATION_PLANNER", raising=False)
    resp = client.post("/query/federated-answer", json={"question": "x", "conn_ids": ["a", "b"]})
    assert resp.status_code == 404


def test_federated_answer_requires_at_least_two_connections(client: TestClient, monkeypatch):
    monkeypatch.setenv("AUGHOR_FEDERATION_PLANNER", "1")
    resp = client.post("/query/federated-answer", json={"question": "x", "conn_ids": ["only-one"]})
    assert resp.status_code == 400


def test_federated_answer_two_sources(client: TestClient, monkeypatch, tmp_path):
    monkeypatch.setenv("AUGHOR_FEDERATION_PLANNER", "1")
    cids = _two_sources(tmp_path)
    _fake_planner(monkeypatch, FederatedPlan(steps=[
        FederatedStep(source=0, sql="SELECT order_id, cust, amount FROM orders ORDER BY order_id", join_key="cust"),
        FederatedStep(source=1, sql="SELECT cust, region FROM customers", join_key="cust", left_key="cust"),
    ]))

    resp = client.post("/query/federated-answer",
                       json={"question": "order amounts with each customer's region", "conn_ids": cids})

    assert resp.status_code == 200
    data = resp.json()
    assert data["error"] is None and data["issues"] == []
    assert data["row_count"] == 3
    regions = [r[data["columns"].index("region")] for r in data["rows"]]
    assert regions == ["EU", "US", "EU"]
    assert len(data["plan"]["steps"]) == 2


def test_federated_answer_three_sources_chain(client: TestClient, monkeypatch, tmp_path):
    monkeypatch.setenv("AUGHOR_FEDERATION_PLANNER", "1")
    cids = _three_sources(tmp_path)
    _fake_planner(monkeypatch, FederatedPlan(steps=[
        FederatedStep(source=0, sql="SELECT order_id, cust FROM orders ORDER BY order_id", join_key="cust"),
        FederatedStep(source=1, sql="SELECT cust, region FROM customers", join_key="cust", left_key="cust"),
        FederatedStep(source=2, sql="SELECT region, manager FROM regions", join_key="region", left_key="region"),
    ]))

    resp = client.post("/query/federated-answer",
                       json={"question": "orders → each customer's region → that region's manager", "conn_ids": cids})

    assert resp.status_code == 200
    data = resp.json()
    assert data["error"] is None
    assert data["row_count"] == 2
    assert "manager" in data["columns"]                    # a value carried across THREE sources
    managers = [r[data["columns"].index("manager")] for r in data["rows"]]
    assert managers == ["Alice", "Bob"]


def test_federated_answer_surfaces_plan_validation_issues(client: TestClient, monkeypatch, tmp_path):
    monkeypatch.setenv("AUGHOR_FEDERATION_PLANNER", "1")
    cids = _two_sources(tmp_path)
    # step 1's left_key 'nope' is not a column of the assembled driver result → caught, no execution
    _fake_planner(monkeypatch, FederatedPlan(steps=[
        FederatedStep(source=0, sql="SELECT order_id, cust FROM orders", join_key="cust"),
        FederatedStep(source=1, sql="SELECT cust, region FROM customers", join_key="cust", left_key="nope"),
    ]))

    resp = client.post("/query/federated-answer", json={"question": "q", "conn_ids": cids})

    assert resp.status_code == 200
    data = resp.json()
    assert data["row_count"] == 0
    assert data["error"] and "validation" in data["error"]
    assert any("left_key 'nope'" in i for i in data["issues"])


# ── validate_plan (deterministic gate) ───────────────────────────────────────

def test_validate_plan_flags_bad_subquery(tmp_path):
    cids = _two_sources(tmp_path)
    plan = FederatedPlan(steps=[
        FederatedStep(source=0, sql="SELECT cust FROM no_such_table", join_key="cust"),
        FederatedStep(source=1, sql="SELECT cust, region FROM customers", join_key="cust", left_key="cust"),
    ])
    assert any("did not execute" in i for i in validate_plan(plan, cids))


def test_validate_plan_flags_source_index_out_of_range(tmp_path):
    cids = _two_sources(tmp_path)
    plan = FederatedPlan(steps=[FederatedStep(source=5, sql="SELECT cust FROM orders", join_key="cust")])
    assert any("out of range" in i for i in validate_plan(plan, cids))


def test_auto_federated_answer_disabled_by_default(client: TestClient, monkeypatch):
    monkeypatch.delenv("AUGHOR_FEDERATION_PLANNER", raising=False)
    resp = client.post("/query/auto-federated-answer", json={"question": "x", "conn_ids": ["a", "b"]})
    assert resp.status_code == 404


def test_auto_federated_answer_selects_connections_then_joins(client: TestClient, monkeypatch, tmp_path):
    """The user names NO connections a question spans — the deterministic selector picks the relevant
    subset (dropping the irrelevant products source), and the planner answers over exactly those."""
    monkeypatch.setenv("AUGHOR_FEDERATION_PLANNER", "1")
    a = _duck_file(tmp_path / "ao.duckdb", "CREATE TABLE orders (order_id INT, cust VARCHAR, amount INT)",
                   "INSERT INTO orders VALUES (1,'C1',100),(2,'C2',50)")
    b = _duck_file(tmp_path / "ac.duckdb", "CREATE TABLE customers (cust VARCHAR, region VARCHAR)",
                   "INSERT INTO customers VALUES ('C1','EU'),('C2','US')")
    c = _duck_file(tmp_path / "ap.duckdb", "CREATE TABLE products (product_id INT, price INT)",
                   "INSERT INTO products VALUES (1,9)")
    oid = registry.add_connection("auto-orders", "duckdb", a)
    cid = registry.add_connection("auto-crm", "duckdb", b)
    pid = registry.add_connection("auto-prod", "duckdb", c)
    # orders grounds 3 question terms (orders/order/amount) vs customers' 2 → orders is the driver, source 0
    _fake_planner(monkeypatch, FederatedPlan(steps=[
        FederatedStep(source=0, sql="SELECT order_id, cust, amount FROM orders ORDER BY order_id", join_key="cust"),
        FederatedStep(source=1, sql="SELECT cust, region FROM customers", join_key="cust", left_key="cust"),
    ]))

    resp = client.post("/query/auto-federated-answer",
                       json={"question": "orders and their amounts by customer region", "conn_ids": [oid, cid, pid]})

    assert resp.status_code == 200
    data = resp.json()
    assert data["selection"]["multi_source"] is True
    assert set(data["selection"]["conn_ids"]) == {oid, cid}       # products dropped by the selector
    assert data["selection"]["conn_ids"][0] == oid                # orders drives (higher term coverage)
    assert data["single_source"] is False
    assert data["error"] is None and data["row_count"] == 2
    assert "region" in data["columns"]


def test_auto_federated_answer_single_source_is_not_federated(client: TestClient, monkeypatch, tmp_path):
    """A question that sits in ONE source must NOT be handed to the cross-database planner — the endpoint
    reports single_source routing instead (no federated LLM call)."""
    monkeypatch.setenv("AUGHOR_FEDERATION_PLANNER", "1")
    cids = _two_sources(tmp_path)   # orders(order_id,cust,amount) + customers(cust,region)
    # provider NOT faked — if the planner were (wrongly) invoked, the test would hit the real LLM/fail
    resp = client.post("/query/auto-federated-answer",
                       json={"question": "total order amount", "conn_ids": cids})
    assert resp.status_code == 200
    data = resp.json()
    assert data["single_source"] is True
    assert data["selection"]["multi_source"] is False
    assert data["selection"]["conn_ids"] == [cids[0]]     # orders only
    assert data["plan"] is None and data["row_count"] == 0


def test_auto_federated_answer_422_when_no_connection_relevant(client: TestClient, monkeypatch, tmp_path):
    monkeypatch.setenv("AUGHOR_FEDERATION_PLANNER", "1")
    cids = _two_sources(tmp_path)
    resp = client.post("/query/auto-federated-answer",
                       json={"question": "the meaning of life", "conn_ids": cids})
    assert resp.status_code == 422


def test_validate_plan_passes_a_good_plan(tmp_path):
    cids = _two_sources(tmp_path)
    plan = FederatedPlan(steps=[
        FederatedStep(source=0, sql="SELECT order_id, cust FROM orders", join_key="cust"),
        FederatedStep(source=1, sql="SELECT cust, region FROM customers", join_key="cust", left_key="cust"),
    ])
    assert validate_plan(plan, cids) == []


def test_collision_chain_validates_faithfully_and_joins_correctly(client: TestClient, monkeypatch, tmp_path):
    """A shared NON-driver column name ('region') across a 3-source chain: validate mirrors the engine's
    _uniquify so it passes truthfully, and — because 'region' is the join key — the fold is correct."""
    monkeypatch.setenv("AUGHOR_FEDERATION_PLANNER", "1")
    a = _duck_file(tmp_path / "o.duckdb", "CREATE TABLE orders (order_id INT, region VARCHAR)",
                   "INSERT INTO orders VALUES (1,'EU'),(2,'US')")
    b = _duck_file(tmp_path / "s.duckdb", "CREATE TABLE stores (store VARCHAR, region VARCHAR)",
                   "INSERT INTO stores VALUES ('S1','EU'),('S2','US')")
    c = _duck_file(tmp_path / "m.duckdb", "CREATE TABLE mgrs (region VARCHAR, manager VARCHAR)",
                   "INSERT INTO mgrs VALUES ('EU','Alice'),('US','Bob')")
    cids = [registry.add_connection("cc0", "duckdb", a),
            registry.add_connection("cc1", "duckdb", b),
            registry.add_connection("cc2", "duckdb", c)]
    plan = FederatedPlan(steps=[
        FederatedStep(source=0, sql="SELECT order_id, region FROM orders ORDER BY order_id", join_key="region"),
        FederatedStep(source=1, sql="SELECT store, region FROM stores", join_key="region", left_key="region"),
        FederatedStep(source=2, sql="SELECT region, manager FROM mgrs", join_key="region", left_key="region"),
    ])
    assert validate_plan(plan, cids) == []          # faithful: no phantom-schema false pass/fail
    _fake_planner(monkeypatch, plan)

    resp = client.post("/query/federated-answer", json={"question": "orders → store region → manager", "conn_ids": cids})

    assert resp.status_code == 200
    data = resp.json()
    assert data["error"] is None and data["row_count"] == 2
    managers = [r[data["columns"].index("manager")] for r in data["rows"]]
    assert managers == ["Alice", "Bob"]
