"""API tests for the dashboard-card CRUD router (Briefing cockpit, Slice 0).

Hermetic: conftest isolates AUGHOR_DASHBOARD_DB. Each test uses a distinct scope_ref so
list assertions never see another test's cards.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from aughor.api import app

client = TestClient(app)


def _payload(**kw) -> dict:
    base = {
        "connection_id": "workspace",
        "scope": "canvas",
        "scope_ref": "cv_api",
        "source": "insight",
        "kind": "kpi",
        "title": "Refund rate",
        "sql": "SELECT AVG(refunded) FROM orders",
        "render": {"chartType": "line"},
        "provenance": {"insight_id": "ins_1", "receipt_ref": "insight:workspace:ins_1"},
        "links": ["ins_1"],
    }
    base.update(kw)
    return base


def test_create_then_get_roundtrips():
    r = client.post("/cards", json=_payload(scope_ref="cv_create"))
    assert r.status_code == 201, r.text
    card = r.json()
    assert card["id"] and card["created_at"]
    assert card["render"] == {"chartType": "line"}
    assert card["provenance"]["insight_id"] == "ins_1"

    got = client.get(f"/cards/{card['id']}")
    assert got.status_code == 200
    assert got.json()["title"] == "Refund rate"


def test_list_filters_by_scope_ref():
    client.post("/cards", json=_payload(scope_ref="cv_list", title="a"))
    client.post("/cards", json=_payload(scope_ref="cv_list", title="b"))
    client.post("/cards", json=_payload(scope_ref="cv_other", title="c"))

    r = client.get("/cards", params={"scope": "canvas", "scope_ref": "cv_list"})
    assert r.status_code == 200
    assert {c["title"] for c in r.json()} == {"a", "b"}


def test_update_and_delete():
    created = client.post("/cards", json=_payload(scope_ref="cv_upd", title="v1")).json()
    cid = created["id"]

    upd = client.put(f"/cards/{cid}", json=_payload(scope_ref="cv_upd", title="v2"))
    assert upd.status_code == 200
    assert upd.json()["title"] == "v2"
    assert upd.json()["created_at"] == created["created_at"]   # preserved

    d = client.delete(f"/cards/{cid}")
    assert d.status_code == 204
    assert client.get(f"/cards/{cid}").status_code == 404


def test_missing_card_is_404():
    assert client.get("/cards/nope").status_code == 404
    assert client.put("/cards/nope", json=_payload()).status_code == 404
    assert client.delete("/cards/nope").status_code == 404
