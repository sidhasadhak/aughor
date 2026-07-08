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


def test_validate_plan_passes_a_good_plan(tmp_path):
    cids = _two_sources(tmp_path)
    plan = FederatedPlan(steps=[
        FederatedStep(source=0, sql="SELECT order_id, cust FROM orders", join_key="cust"),
        FederatedStep(source=1, sql="SELECT cust, region FROM customers", join_key="cust", left_key="cust"),
    ])
    assert validate_plan(plan, cids) == []
