"""Integration: GET /ontology/duplicate-entities returns merge suggestions through the real app.

The ontology graph loader and the embedder are both faked, so this exercises the route → detect →
response path without needing a built ontology or a running embed model.
"""
from __future__ import annotations

from types import SimpleNamespace

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


# ── apply-merge endpoint ──────────────────────────────────────────────────────

def test_merge_requires_two_distinct(client: TestClient):
    r = client.post("/ontology/entities/merge", json={"merge_ids": ["A"], "canonical_id": "A"})
    assert r.status_code == 400


def test_merge_canonical_must_be_in_list(client: TestClient):
    r = client.post("/ontology/entities/merge", json={"merge_ids": ["A", "B"], "canonical_id": "C"})
    assert r.status_code == 400


def test_merge_404_without_ontology(client: TestClient, monkeypatch):
    monkeypatch.setattr(onto, "_get_ontology_graph", lambda *a, **k: None)
    r = client.post("/ontology/entities/merge",
                    json={"merge_ids": ["Customer", "Client"], "canonical_id": "Customer"})
    assert r.status_code == 404


def test_merge_404_on_unknown_entity(client: TestClient, monkeypatch):
    monkeypatch.setattr(onto, "_get_ontology_graph", lambda *a, **k: _GRAPH)
    r = client.post("/ontology/entities/merge",
                    json={"merge_ids": ["Customer", "Ghost"], "canonical_id": "Customer"})
    assert r.status_code == 404 and "Ghost" in r.json()["detail"]
    # The merge itself is counted against a warehouse — tests/unit/test_entity_merge.py drives it end to end.
