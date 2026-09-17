"""HB-5 — arrivals: a sentence in Slack becomes a staged note on the filed object,
with provenance, through customs. The thread→object link (HB-3) is what makes the
routing deterministic; the blast-radius law is what makes the landing safe."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aughor.hub import links as L
from aughor.ontology.agent_notes import accept_note, object_notes_for, propose_note

_PROMISE = "promise:order_to_delivery.dispatch"


@pytest.fixture()
def client():
    from aughor.api import app
    return TestClient(app)


def _file_thread(monkeypatch, channel="C1", ts="1712.001", conn="olist"):
    monkeypatch.setattr(L, "stamped_measures",
                        lambda ref: {"breach_rate": 0.0935, "connection_id": conn})
    return L.file_link(object_ref=_PROMISE, kind="thread", ref=f"{channel}:{ts}",
                       title="Dispatch promise breached", source="automation:a1")


# ── the object note target ────────────────────────────────────────────────────────

def test_an_object_note_always_stages_and_keeps_its_provenance():
    out = propose_note("c1", "arrivals", target="object", table=_PROMISE,
                       note="the carrier switched hubs mid-August",
                       evidence="said in thread", confidence="high",   # even at HIGH
                       provenance={"authority": "said", "author": "Ana"})
    assert out.ok and out.action == "staged"       # blast radius: never direct-apply
    rows = object_notes_for("c1", _PROMISE)
    assert rows and rows[-1]["provenance"]["author"] == "Ana"
    assert rows[-1]["status"] == "pending"


def test_accepting_an_object_note_keeps_it_in_the_store_as_accepted():
    out = propose_note("c2", "arrivals", target="object", table=_PROMISE,
                       note="a note to accept", evidence="e", confidence="low")
    written = accept_note("c2", "arrivals", out.recommendation_id)
    assert written and written["object_ref"] == _PROMISE
    rows = object_notes_for("c2", _PROMISE)
    assert rows[-1]["status"] == "accepted"


# ── the door: filed thread → staged note; unfiled → honest 404 ────────────────────

def test_a_filed_threads_reply_becomes_a_staged_note_with_provenance(
        client, monkeypatch):
    _file_thread(monkeypatch, channel="C7", ts="1712.007")
    resp = client.post("/arrivals/slack", json={
        "channel": "C7", "thread_ts": "1712.007",
        "text": "carrier X was on strike last week — reach me at ana@corp.example",
        "author": "Ana", "author_ref": "slack:U123"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["action"] == "staged" and body["object_ref"] == _PROMISE
    assert "[EMAIL]" in body["note"]                       # customs: PII redacted
    assert "ana@corp.example" not in body["note"]
    assert body["provenance"]["authority"] == "said"
    assert body["provenance"]["where"] == "#C7"

    shown = client.get("/arrivals/notes", params={"object_ref": _PROMISE,
                                                  "connection_id": "olist"}).json()
    assert shown["notes"] and "[said by Ana in #C7" in shown["notes"][-1]["stamp"]


def test_an_unfiled_thread_is_refused_not_guessed(client):
    resp = client.post("/arrivals/slack", json={
        "channel": "C9", "thread_ts": "999.999", "text": "hello"})
    assert resp.status_code == 404
    assert "not filed on any object" in resp.json()["detail"]


# ── the envelope adapter reads the arrival back, ranked and stamped ──────────────

def test_the_adapter_wraps_arrival_notes_for_the_ranker(client, monkeypatch):
    _file_thread(monkeypatch, channel="C8", ts="1712.008", conn="hb5conn")
    client.post("/arrivals/slack", json={
        "channel": "C8", "thread_ts": "1712.008",
        "text": "south region depots flooded in week 36", "author": "Ola"})
    from aughor.hub.adapters import conversation_note_pieces
    from aughor.hub.ranker import rank
    pieces = conversation_note_pieces("hb5conn")
    assert pieces and pieces[-1].provenance.authority == "said"
    ranked = rank(pieces)
    assert "south region depots flooded" in ranked.rendered()
    assert "[said by Ola in #C8" in ranked.rendered()
