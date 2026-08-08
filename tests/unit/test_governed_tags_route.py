"""S1/J13 — the governed-tag read route: the governance axis, renderable at last.

G2 built the tag store and the clearances that read it, but no HTTP route ever
served the tags — so a 'Certified' table could never LOOK certified anywhere.
This is the render path only; writes stay with the clearance machinery.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aughor.routers import governance as G


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(G.router)
    return TestClient(app)


def test_tags_route_serves_what_the_store_holds(client):
    from aughor.govern import tag_store

    tag_store.set_tag("table:c.s.orders", "cert", "gold", set_by="alice")
    try:
        rows = client.get("/governance/tags", params={"securable_prefix": "table:"}).json()
        mine = [r for r in rows if r["securable"] == "table:c.s.orders" and r["key"] == "cert"]
        assert mine and mine[0]["value"] == "gold"
        assert mine[0]["set_by"] == "alice", "provenance is what makes a tag evidence"
    finally:
        tag_store.clear_tag("table:c.s.orders", "cert", cleared_by="test")


def test_tags_route_filters_by_key(client):
    from aughor.govern import tag_store

    tag_store.set_tag("table:c.s.k1", "pii", "email", set_by="alice")
    tag_store.set_tag("table:c.s.k2", "tier", "restricted", set_by="alice")
    try:
        rows = client.get("/governance/tags", params={"key": "pii"}).json()
        assert all(r["key"] == "pii" for r in rows)
        assert any(r["securable"] == "table:c.s.k1" for r in rows)
    finally:
        tag_store.clear_tag("table:c.s.k1", "pii", cleared_by="test")
        tag_store.clear_tag("table:c.s.k2", "tier", cleared_by="test")


def test_empty_plane_is_an_empty_list(client):
    rows = client.get("/governance/tags",
                      params={"securable_prefix": "artifact:never-tagged-"}).json()
    assert rows == []
