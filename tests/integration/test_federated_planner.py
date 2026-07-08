"""Integration tests for the cross-source federated planner (Rec 2, Stage 3).

The LLM plan step is faked (returns a canned FederatedPlan); everything after it — deterministic
validation and the batched-foreach execution across two real registered DuckDB sources — runs for real.
"""
from __future__ import annotations

import duckdb
from fastapi.testclient import TestClient

import aughor.llm.provider as provider_mod
from aughor.agent.federated_planner import (
    FederatedPlan,
    FederatedSide,
    validate_plan,
)
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
    lid = registry.add_connection("fp-left", "duckdb", lp)
    rid = registry.add_connection("fp-right", "duckdb", rp)
    return lid, rid


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


def test_federated_answer_requires_two_connections(client: TestClient, monkeypatch):
    monkeypatch.setenv("AUGHOR_FEDERATION_PLANNER", "1")
    resp = client.post("/query/federated-answer", json={"question": "x", "conn_ids": ["only-one"]})
    assert resp.status_code == 400


def test_federated_answer_end_to_end(client: TestClient, monkeypatch, tmp_path):
    monkeypatch.setenv("AUGHOR_FEDERATION_PLANNER", "1")
    lid, rid = _two_sources(tmp_path)
    _fake_planner(monkeypatch, FederatedPlan(
        left=FederatedSide(sql="SELECT order_id, cust, amount FROM orders ORDER BY order_id", join_key="cust"),
        right=FederatedSide(sql="SELECT cust, region FROM customers", join_key="cust"),
        how="inner",
    ))

    resp = client.post("/query/federated-answer",
                       json={"question": "order amounts with each customer's region", "conn_ids": [lid, rid]})

    assert resp.status_code == 200
    data = resp.json()
    assert data["error"] is None
    assert data["issues"] == []
    assert data["row_count"] == 3                      # 3 orders joined to their customer region
    assert "region" in data["columns"]
    regions = [r[data["columns"].index("region")] for r in data["rows"]]
    assert regions == ["EU", "US", "EU"]
    assert data["plan"]["how"] == "inner"              # the plan is returned (inspectable)


def test_federated_answer_surfaces_plan_validation_issues(client: TestClient, monkeypatch, tmp_path):
    monkeypatch.setenv("AUGHOR_FEDERATION_PLANNER", "1")
    lid, rid = _two_sources(tmp_path)
    # left sub-query does NOT output its declared join key 'cust' → validation must catch it, no execution
    _fake_planner(monkeypatch, FederatedPlan(
        left=FederatedSide(sql="SELECT order_id FROM orders", join_key="cust"),
        right=FederatedSide(sql="SELECT cust, region FROM customers", join_key="cust"),
    ))

    resp = client.post("/query/federated-answer", json={"question": "q", "conn_ids": [lid, rid]})

    assert resp.status_code == 200
    data = resp.json()
    assert data["row_count"] == 0
    assert data["error"] and "validation" in data["error"]
    assert any("join key 'cust'" in i for i in data["issues"])


# ── validate_plan (deterministic gate) ───────────────────────────────────────

def test_validate_plan_flags_bad_subquery(tmp_path):
    lid, rid = _two_sources(tmp_path)
    plan = FederatedPlan(
        left=FederatedSide(sql="SELECT cust FROM no_such_table", join_key="cust"),
        right=FederatedSide(sql="SELECT cust, region FROM customers", join_key="cust"),
    )
    issues = validate_plan(plan, lid, rid)
    assert any("did not execute" in i for i in issues)


def test_validate_plan_passes_a_good_plan(tmp_path):
    lid, rid = _two_sources(tmp_path)
    plan = FederatedPlan(
        left=FederatedSide(sql="SELECT order_id, cust FROM orders", join_key="cust"),
        right=FederatedSide(sql="SELECT cust, region FROM customers", join_key="cust"),
    )
    assert validate_plan(plan, lid, rid) == []
