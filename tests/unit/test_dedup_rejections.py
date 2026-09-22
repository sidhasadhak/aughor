"""CB-4 — remember a rejected duplicate (Arc CB, 2026-09-23).

Measured before this wave: `GET /ontology/duplicate-entities` recomputed the same near-duplicate
clusters on every read and nothing recorded a person's "no, these are different", so a pair someone
had rejected came back every visit. The ontology already does this right twice (a dismissed
recommendation never returns; a withdrawn explorer proposal is not made again) — this repeats the
pattern. These tests pin: a rejected pair is hidden on the next read and counted; the key is the
unordered pair; the reason and the person are kept; a larger cluster with one pair rejected stays,
annotated, because its other pairs were never judged; a rejection can be reconsidered; and the doors.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from aughor.ontology import dedup_decisions as D


@pytest.fixture(autouse=True)
def _root(tmp_path, monkeypatch):
    import aughor.ontology.recommendations as R
    monkeypatch.setattr(R, "_ROOT", tmp_path / "decisions")
    yield


def _cluster(*ids, sim=0.93):
    return {"entities": [{"id": i, "display_name": i, "source_tables": [i.lower()]} for i in ids], "similarity": sim}


class TestARejectionIsRemembered:
    def test_a_rejected_pair_is_hidden_on_the_next_read_and_counted(self):
        shown, hidden = D.apply_rejections([_cluster("Customer", "Client")], D.rejected_pairs("c1", "main"))
        assert len(shown) == 1 and hidden == 0
        D.reject("c1", "main", ["Customer", "Client"], reason="Client is a B2B account, Customer a shopper", rejected_by="user:ana@corp")
        shown, hidden = D.apply_rejections([_cluster("Customer", "Client")], D.rejected_pairs("c1", "main"))
        assert shown == [] and hidden == 1

    def test_the_key_is_the_unordered_pair(self):
        D.reject("c1", "main", ["Client", "Customer"])
        assert ("Client", "Customer") in D.rejected_pairs("c1", "main")
        shown, hidden = D.apply_rejections([_cluster("Customer", "Client")], D.rejected_pairs("c1", "main"))
        assert hidden == 1

    def test_the_reason_and_the_person_are_kept(self):
        D.reject("c1", "main", ["Customer", "Client"], reason="  different   things ", rejected_by="user:ana@corp")
        row = D.rejected_pairs("c1", "main")[("Client", "Customer")]
        assert row["reason"] == "different things" and row["rejected_by"] == "user:ana@corp" and row["rejected_at"]

    def test_a_larger_cluster_with_one_pair_rejected_stays_annotated(self):
        D.reject("c1", "main", ["Customer", "Client"], reason="B2B vs shopper")
        shown, hidden = D.apply_rejections([_cluster("Customer", "Client", "Buyer")], D.rejected_pairs("c1", "main"))
        assert hidden == 0 and len(shown) == 1
        assert shown[0]["rejected_pairs"] == [{"pair": ["Client", "Customer"], "reason": "B2B vs shopper"}]
        assert "rejected_pairs" not in _cluster("a", "b")                    # untouched clusters carry no key

    def test_rejecting_three_rejects_every_pair(self):
        rows = D.reject("c1", "main", ["A", "B", "C"])
        assert sorted(tuple(r["pair"]) for r in rows) == [("A", "B"), ("A", "C"), ("B", "C")]
        shown, hidden = D.apply_rejections([_cluster("A", "B", "C")], D.rejected_pairs("c1", "main"))
        assert shown == [] and hidden == 1

    def test_a_rejection_can_be_reconsidered(self):
        D.reject("c1", "main", ["Customer", "Client"])
        assert D.reconsider("c1", "main", "Client", "Customer") is True
        assert D.reconsider("c1", "main", "Client", "Customer") is False
        shown, hidden = D.apply_rejections([_cluster("Customer", "Client")], D.rejected_pairs("c1", "main"))
        assert hidden == 0 and len(shown) == 1

    def test_scopes_do_not_bleed_and_fewer_than_two_ids_is_refused(self):
        D.reject("c1", "main", ["Customer", "Client"])
        assert D.rejected_pairs("c1", "other") == {} and D.rejected_pairs("c2", "main") == {}
        with pytest.raises(ValueError):
            D.reject("c1", "main", ["Customer"])

    def test_the_detector_stays_pure_and_the_read_applies_decisions(self, monkeypatch):
        import aughor.ontology.dedup as X
        monkeypatch.setattr(X, "detect_duplicate_entities", lambda graph, threshold=0.85: [_cluster("Customer", "Client"), _cluster("Order", "SalesOrder")])
        D.reject("c1", "main", ["Customer", "Client"], reason="B2B")
        out = D.detect_with_decisions(SimpleNamespace(), "c1", "main")
        assert [c["entities"][0]["id"] for c in out["clusters"]] == ["Order"]
        assert out["hidden"] == 1 and out["rejected"][0]["reason"] == "B2B"


class TestTheDoors:
    def test_reject_then_the_read_hides_it_then_reconsider(self, client, monkeypatch):
        import aughor.routers.ontology as R
        import aughor.ontology.dedup as X
        monkeypatch.setattr(R, "_get_ontology_graph", lambda cid, schema=None: SimpleNamespace())
        monkeypatch.setattr(X, "detect_duplicate_entities", lambda graph, threshold=0.85: [_cluster("Customer", "Client")])
        r = client.get("/ontology/duplicate-entities", params={"connection_id": "fixture"})
        assert r.status_code == 200 and len(r.json()["clusters"]) == 1 and r.json()["hidden"] == 0
        r = client.post("/ontology/duplicate-entities/reject", params={"connection_id": "fixture"},
                        json={"entity_ids": ["Customer", "Client"], "reason": "B2B vs shopper"})
        assert r.status_code == 201 and r.json()["rejected"][0]["pair"] == ["Client", "Customer"]
        r = client.get("/ontology/duplicate-entities", params={"connection_id": "fixture"})
        assert r.json()["clusters"] == [] and r.json()["hidden"] == 1 and r.json()["rejected"][0]["reason"] == "B2B vs shopper"
        assert client.post("/ontology/duplicate-entities/reject", params={"connection_id": "fixture"},
                           json={"entity_ids": ["Customer"]}).status_code == 422
        r = client.delete("/ontology/duplicate-entities/reject", params={"connection_id": "fixture", "a": "Customer", "b": "Client"})
        assert r.status_code == 200
        assert client.delete("/ontology/duplicate-entities/reject", params={"connection_id": "fixture", "a": "Customer", "b": "Client"}).status_code == 404
        assert len(client.get("/ontology/duplicate-entities", params={"connection_id": "fixture"}).json()["clusters"]) == 1
