"""Packs API router (2026-06-27) — list / detail / propose-bindings over the real sample."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aughor.routers.packs import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


def test_list_packs_includes_sample():
    r = client.get("/packs")
    assert r.status_code == 200
    body = r.json()
    assert "enabled" in body
    ids = [p["id"] for p in body["packs"]]
    assert "customer-analytics" in ids
    ca = next(p for p in body["packs"] if p["id"] == "customer-analytics")
    assert ca["ok"] is True and ca["roles"] >= 1


def test_pack_detail():
    r = client.get("/packs/customer-analytics")
    assert r.status_code == 200
    body = r.json()
    assert body["manifest"]["id"] == "customer-analytics"
    assert body["validation"]["ok"] is True
    assert "customer" in body["entities"]


def test_unknown_pack_404():
    assert client.get("/packs/does-not-exist").status_code == 404


def test_propose_bindings_over_table_cols():
    payload = {
        "connection_id": "c1",
        "business_model": "transactional",
        "table_cols": {
            "dim_customers": ["customer_id", "signup_ts"],
            "fct_orders": ["order_id", "order_ts", "customer_id"],
        },
    }
    r = client.post("/packs/customer-analytics/propose-bindings", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["fully_bound"] is True
    assert body["proposals"]["customer"]["table"] == "dim_customers"
