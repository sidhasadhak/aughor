"""S5 — cited memory: remembered, cited, revocable.

The ledger's readings were injected into every matching plan but were invisible
and irrevocable from the product — memory the user could neither inspect nor
retract. These routes are the missing two-thirds of the contract; the tests pin
that a revoked reading is GONE from retrieval, not just hidden from the list.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aughor.org.context import current_org_id
from aughor.routers import learning as L
from aughor.semantic.ambiguity_ledger import (
    crystallize_user_choice,
    list_resolutions,
    purge_connections,
)


def _remember(subject: str, reading: str) -> None:
    # As production writes: the live call sites always pass the caller's org
    # (the route scopes to it — a tenant sees and revokes only its own memory).
    crystallize_user_choice("cited-mem-conn", subject, reading,
                            org_id=current_org_id() or "default")


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(L.router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean():
    purge_connections(["cited-mem-conn"])
    yield
    purge_connections(["cited-mem-conn"])


def test_remembered_readings_list_with_their_citations(client):
    _remember("total revenue", "net of refunds")
    rows = client.get("/learning/resolutions",
                      params={"connection_id": "cited-mem-conn"}).json()
    assert len(rows) == 1
    r = rows[0]
    assert r["resolved_reading"] == "net of refunds"
    assert r["resolution_source"] == "user", "the citation: WHO settled it"
    assert "use_count" in r, "the citation: how often it served as a prior"


def test_revoke_removes_the_reading_from_retrieval(client):
    _remember("total revenue", "net of refunds")
    res_id = list_resolutions("cited-mem-conn")[0].id
    assert client.delete(f"/learning/resolutions/{res_id}").status_code == 204
    # Gone from the STORE (the next matching question re-ambiguates), not
    # merely from the listing.
    assert list_resolutions("cited-mem-conn") == []


def test_revoking_a_ghost_is_404(client):
    assert client.delete("/learning/resolutions/no-such-id").status_code == 404
