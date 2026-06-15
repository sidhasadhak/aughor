"""Unit tests for ontology entity dedup (aughor/ontology/dedup).

The clustering core is pure (takes precomputed vectors), so these use hand-made embeddings — no
model. `detect_duplicate_entities` is tested with a fake graph + an injected embed fn, including the
fail-open path.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from aughor.ontology.dedup import cluster_by_similarity, cosine, detect_duplicate_entities, merge_entities
from aughor.ontology.models import (
    OntologyEntity,
    OntologyGraph,
    OntologyInterface,
    OntologyMetric,
    OntologyRelationship,
)


def test_cosine_basic():
    assert cosine([1, 2, 3], [1, 2, 3]) == 1.0
    assert cosine([1, 0], [0, 1]) == 0.0
    assert cosine([0, 0], [1, 1]) == 0.0          # zero vector → 0, never divide-by-zero


def test_cluster_identical_pair_orthogonal_singleton():
    # 0 and 1 identical, 2 orthogonal → one cluster {0,1}, 2 omitted (singleton)
    emb = [[1, 0, 0], [1, 0, 0], [0, 1, 0]]
    assert cluster_by_similarity(emb, threshold=0.85) == [[0, 1]]


def test_cluster_transitive_connected_components():
    # A~B and B~C above threshold, A~C below → connected components still groups {A,B,C}
    r = math.radians
    A = [1.0, 0.0]
    B = [math.cos(r(15)), math.sin(r(15))]   # ~15° from A
    C = [math.cos(r(30)), math.sin(r(30))]   # ~30° from A, ~15° from B
    # cos(A,B)=cos15≈.966, cos(B,C)=cos15≈.966 (both ≥ .9); cos(A,C)=cos30≈.866 (< .9)
    assert cosine(A, C) < 0.9 <= cosine(A, B)
    assert cluster_by_similarity([A, B, C], threshold=0.9) == [[0, 1, 2]]


def test_cluster_threshold_respected():
    A = [1.0, 0.0]
    C = [math.cos(math.radians(30)), math.sin(math.radians(30))]  # ~0.866
    assert cluster_by_similarity([A, C], threshold=0.9) == []     # below threshold → no cluster
    assert cluster_by_similarity([A, C], threshold=0.8) == [[0, 1]]


def test_cluster_empty_and_single():
    assert cluster_by_similarity([]) == []
    assert cluster_by_similarity([[1, 0]]) == []


def _ent(eid, name, desc="", tables=None):
    return SimpleNamespace(id=eid, display_name=name, description=desc, source_tables=tables or [])


def _graph(entities):
    return SimpleNamespace(entities={e.id: e for e in entities})


def test_detect_returns_suggestion_shape():
    g = _graph([_ent("Customer", "Customer", tables=["customers"]),
                _ent("Client", "Client", tables=["clients"]),
                _ent("Order", "Order", tables=["orders"])])
    # Customer & Client share an embedding (duplicates); Order is distinct
    vecs = {"Customer": [1, 0, 0], "Client": [1, 0, 0], "Order": [0, 0, 1]}
    fake_embed = lambda texts: [vecs["Customer"] if "Customer" in t else vecs["Client"] if "Client" in t else vecs["Order"] for t in texts]

    out = detect_duplicate_entities(g, threshold=0.85, embed=fake_embed)

    assert len(out) == 1
    ids = {e["id"] for e in out[0]["entities"]}
    assert ids == {"Customer", "Client"}
    assert out[0]["similarity"] == 1.0
    assert out[0]["entities"][0]["source_tables"]      # shape carries source tables


def test_detect_fewer_than_two_entities():
    assert detect_duplicate_entities(_graph([_ent("Only", "Only")])) == []
    assert detect_duplicate_entities(_graph([])) == []


def test_detect_fail_open_on_embed_error():
    g = _graph([_ent("A", "A"), _ent("B", "B")])
    def boom(texts):
        raise RuntimeError("no ollama")
    assert detect_duplicate_entities(g, embed=boom) == []   # fail-open → no suggestions


def test_detect_fail_open_on_vector_mismatch():
    g = _graph([_ent("A", "A"), _ent("B", "B")])
    assert detect_duplicate_entities(g, embed=lambda texts: [[1, 0]]) == []   # wrong count → []


# ── merge_entities (the apply-merge rewrite) ──────────────────────────────────

def _E(i, t):
    return OntologyEntity(id=i, display_name=i, description="", source_tables=[t],
                          identity_key="id", grain_verified=True)


def _R(fe, te):
    return OntologyRelationship(id=f"{fe}_RELATES_TO_{te}", from_entity=fe, to_entity=te, verb="has",
                               cardinality="1:N", join_sql=f"{fe}.id={te}.fk",
                               from_table=fe.lower(), from_col="id", to_table=te.lower(), to_col="fk")


def _full_graph():
    return OntologyGraph(
        connection_id="c", schema_fingerprint="fp",
        entities={"Customer": _E("Customer", "customers"), "Client": _E("Client", "clients"),
                  "Order": _E("Order", "orders")},
        relationships={"Client_RELATES_TO_Order": _R("Client", "Order"),
                       "Customer_RELATES_TO_Order": _R("Customer", "Order")},
        metrics={"m": OntologyMetric(id="m", display_name="M", entity="Client", formula_sql="SUM(x)")},
        interfaces={"HasTime": OntologyInterface(id="HasTime", display_name="HasTime",
                                                 implementing_entities=["Customer", "Client"])},
        entity_to_tables={"Customer": ["customers"], "Client": ["clients"], "Order": ["orders"]},
        table_to_entity={"customers": "Customer", "clients": "Client", "orders": "Order"},
        relationship_index={"Customer": ["Order"], "Client": ["Order"], "Order": ["Customer", "Client"]},
    )


def test_merge_rewrites_all_cross_references():
    m = merge_entities(_full_graph(), ["Customer", "Client"], "Customer")

    assert "Client" not in m.entities                                   # merged away
    assert sorted(m.entities["Customer"].source_tables) == ["clients", "customers"]  # tables unioned
    assert set(m.relationships) == {"Customer_RELATES_TO_Order"}        # the two Order rels deduped to one
    assert m.metrics["m"].entity == "Customer"                          # metric repointed
    assert m.interfaces["HasTime"].implementing_entities == ["Customer"]  # interface repointed + deduped
    assert m.table_to_entity["clients"] == "Customer"                   # table map repointed
    assert "Client" not in m.entity_to_tables
    assert sorted(m.entity_to_tables["Customer"]) == ["clients", "customers"]
    assert m.relationship_index["Order"] == ["Customer"]               # index rebuilt


def test_merge_is_pure_original_untouched():
    g = _full_graph()
    merge_entities(g, ["Customer", "Client"], "Customer")
    assert "Client" in g.entities                                      # original graph unchanged
    assert g.metrics["m"].entity == "Client"


def test_merge_drops_relationship_that_becomes_self_loop():
    g = _full_graph()
    g.relationships["Customer_RELATES_TO_Client"] = _R("Customer", "Client")
    m = merge_entities(g, ["Customer", "Client"], "Customer")
    # the Customer↔Client relationship is now internal → dropped, not a self-loop
    assert all(r.from_entity != r.to_entity for r in m.relationships.values())
    assert "Customer_RELATES_TO_Customer" not in m.relationships


def test_merge_noop_when_only_canonical():
    g = _full_graph()
    assert merge_entities(g, ["Customer"], "Customer") is g            # nothing to remove


def test_merge_unknown_canonical_raises():
    with pytest.raises(ValueError, match="canonical"):
        merge_entities(_full_graph(), ["Customer", "Nope"], "Nope")


def test_merge_unknown_member_raises():
    with pytest.raises(ValueError, match="unknown"):
        merge_entities(_full_graph(), ["Customer", "Ghost"], "Customer")
