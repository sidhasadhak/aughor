"""Integration: GET /ontology/duplicate-entities returns merge suggestions through the real app.

The ontology graph loader and the embedder are both faked, so this exercises the route → detect →
response path without needing a built ontology or a running embed model.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import aughor.routers.ontology as onto
import aughor.semantic.embedder as embedder


def _ent(eid, name, tables):
    return SimpleNamespace(id=eid, display_name=name, description="", source_tables=tables)


_GRAPH = SimpleNamespace(entities={
    e.id: e for e in [
        _ent("Customer", "Customer", ["customers"]),
        _ent("Client", "Client", ["clients"]),
        _ent("Order", "Order", ["orders"]),
    ]
})

# Customer & Client embed identically (duplicates); Order is orthogonal.
def _fake_embed(texts):
    out = []
    for t in texts:
        if "Customer" in t or "Client" in t:
            out.append([1.0, 0.0, 0.0])
        else:
            out.append([0.0, 0.0, 1.0])
    return out


def test_duplicate_entities_returns_clusters(client: TestClient, monkeypatch):
    monkeypatch.setattr(onto, "_get_ontology_graph", lambda *a, **k: _GRAPH)
    monkeypatch.setattr(embedder, "embed", _fake_embed)

    r = client.get("/ontology/duplicate-entities", params={"connection_id": "fixture", "threshold": 0.85})
    assert r.status_code == 200, r.text
    clusters = r.json()["clusters"]
    assert len(clusters) == 1
    ids = {e["id"] for e in clusters[0]["entities"]}
    assert ids == {"Customer", "Client"}            # Order not clustered


def test_duplicate_entities_fail_open_when_embeddings_unavailable(client: TestClient, monkeypatch):
    monkeypatch.setattr(onto, "_get_ontology_graph", lambda *a, **k: _GRAPH)
    def boom(texts):
        raise RuntimeError("embed model unavailable")
    monkeypatch.setattr(embedder, "embed", boom)

    r = client.get("/ontology/duplicate-entities", params={"connection_id": "fixture"})
    assert r.status_code == 200
    assert r.json()["clusters"] == []               # fail-open, not a 500


def test_duplicate_entities_404_without_ontology(client: TestClient, monkeypatch):
    monkeypatch.setattr(onto, "_get_ontology_graph", lambda *a, **k: None)
    r = client.get("/ontology/duplicate-entities", params={"connection_id": "nope"})
    assert r.status_code == 404
