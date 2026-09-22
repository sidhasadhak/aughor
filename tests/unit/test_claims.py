"""CB-8 — said versus measured (Arc CB, 2026-09-23).

Measured before this wave: a reply in a filed Slack thread arrived as a staged note at the `said`
tier and stayed there; no prompt saw it (the injection list was empty by design) and nothing checked
what it claimed. Now the numbers a reply states are checked against the measures its thread was
filed with: agreement raises the note to `measured` and lets it through the injection gate (the
first kind through, and only that kind); disagreement makes it `contradicted` and writes the
question for the object's owner, saying when that owner cannot be reached; no number or nothing
measured stays `unchecked`. Deterministic, no model.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from aughor.hub import claims as C
from aughor.hub.claims import CONTRADICTED, MEASURED, UNCHECKED, check_claim

PROMISE = "promise:order_to_delivery.dispatch"
FILED = {"breached": 187, "reached": 2000, "breach_rate": 0.0935, "as_of": "2026-09-18", "connection_id": "olist"}


class TestTheThreeOutcomes:
    def test_a_stated_number_the_data_confirms_is_measured(self):
        c = check_claim("we breached on 187 orders last week, about 9.35%", PROMISE, "olist", measures=FILED)
        assert c.verification == MEASURED and c.matched["label"] == "breached" and c.matched["value"] == 187
        c2 = check_claim("the breach rate is 9.35%", PROMISE, "olist", measures=FILED)
        assert c2.verification == MEASURED and c2.matched["label"] == "breach_rate"     # a rate said as a percentage

    def test_a_stated_number_the_data_contradicts_raises_the_owners_question(self, monkeypatch):
        monkeypatch.setattr(C, "owner_of", lambda ref, cid: ("user:ops@corp", "Ops lead"))
        c = check_claim("we breached on 400 orders last week", PROMISE, "olist", measures=FILED)
        assert c.verification == CONTRADICTED and c.question_to == "user:ops@corp" and c.note == ""
        assert c.question == ('You said "400" about promise:order_to_delivery.dispatch; the platform measured 187 (breached) '
                              "when the thread was filed. Which is right?")

    def test_an_unresolved_owner_is_said_not_hidden(self, monkeypatch):
        monkeypatch.setattr(C, "owner_of", lambda ref, cid: ("", "Ops lead"))
        c = check_claim("breach rate was 40%", PROMISE, "olist", measures=FILED)
        assert c.verification == CONTRADICTED and c.question_to == "" and "not linked to a person" in c.note
        monkeypatch.setattr(C, "owner_of", lambda ref, cid: ("", ""))
        assert "no owner is declared" in check_claim("breach rate was 40%", PROMISE, "olist", measures=FILED).note

    def test_no_number_or_nothing_measured_stays_unchecked(self):
        assert check_claim("the carrier switched hubs mid-August", PROMISE, "olist", measures=FILED).verification == UNCHECKED
        assert check_claim("we breached on 187 orders", PROMISE, "olist", measures={}).verification == UNCHECKED
        assert check_claim("we breached on 187 orders", PROMISE, "olist", measures={"as_of": "2026-09-18", "connection_id": "x"}).verification == UNCHECKED


class TestWhoIsAsked:
    def test_a_metrics_catalog_owner_and_a_processs_owner_resolve_the_cb3_way(self, monkeypatch):
        monkeypatch.setattr("aughor.semantic.metrics.get_metric", lambda name, path=None, connection_id=None: SimpleNamespace(owner="group:finance"))
        assert C.owner_of("metric:revenue", "c1") == ("group:finance", "group:finance")
        proc = SimpleNamespace(owner="Ops lead")
        monkeypatch.setattr("aughor.agent.framing.served_graph", lambda cid, schema=None: SimpleNamespace(processes={"order_to_delivery": proc}, rules={}))
        assert C.owner_of(PROMISE, "c1") == ("", "Ops lead")        # declared, not linked
        from aughor.rbac import owners as OW
        OW.link_owner("default", "Ops lead", "user:ops@corp")
        try:
            assert C.owner_of(PROMISE, "c1") == ("user:ops@corp", "Ops lead")
        finally:
            OW.unlink_owner("default", "Ops lead")
        assert C.owner_of("table:orders", "c1") == ("", "")


class TestTheArrivalIsChecked:
    def test_a_filed_reply_is_checked_stored_and_listed(self, client, monkeypatch):
        from aughor.hub import links as L
        monkeypatch.setattr(L, "stamped_measures", lambda ref: FILED)
        L.file_link(object_ref=PROMISE, kind="thread", ref="C9:1712.009", title="Dispatch promise breached", source="automation:a1")
        monkeypatch.setattr(C, "owner_of", lambda ref, cid: ("user:ops@corp", "Ops lead"))
        r = client.post("/arrivals/slack", json={"channel": "C9", "thread_ts": "1712.009", "text": "we breached on 187 orders", "author": "Ana"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["check"]["verification"] == "measured" and body["provenance"]["authority"] == "measured"
        r2 = client.post("/arrivals/slack", json={"channel": "C9", "thread_ts": "1712.009", "text": "no, it was 400 orders", "author": "Bo"})
        assert r2.json()["check"]["verification"] == "contradicted" and r2.json()["check"]["question_to"] == "user:ops@corp"
        notes = client.get("/arrivals/notes", params={"object_ref": PROMISE, "connection_id": "olist"}).json()["notes"]
        assert notes and notes[-1]["check"]["verification"] == "contradicted"
        claims = client.get("/arrivals/claims", params={"connection_id": "olist"}).json()
        assert claims["counts"]["contradicted"] >= 1 and claims["contradictions"][0]["question_to"] == "user:ops@corp"


class TestOnlyACheckedNoteReachesAPrompt:
    def _pieces(self, *verifications):
        from aughor.hub.provenance import ContextPiece, Provenance
        return [ContextPiece(text=f"note {i} says 187 breached", subject=PROMISE, piece_id=str(i),
                             provenance=Provenance(source_kind="conversation", authority="measured" if v == "measured" else "said",
                                                   author="Ana", author_kind="person", scope_kind="object", scope_key=PROMISE,
                                                   observed_at="2026-09-23T00:00:00+00:00", verification=v))
                for i, v in enumerate(verifications)]

    def test_measured_notes_are_let_through_said_and_contradicted_are_not(self, monkeypatch):
        from aughor.hub import injection as I
        monkeypatch.setattr("aughor.hub.adapters.conversation_note_pieces", lambda cid: self._pieces("measured", "unverified", "contradicted"))
        block = I.ranked_notes_block("olist")
        assert block.startswith("CONTEXT FROM PEOPLE, CHECKED AGAINST THE DATA")
        assert "note 0" in block and "note 1" not in block and "note 2" not in block
        monkeypatch.setattr("aughor.hub.adapters.conversation_note_pieces", lambda cid: self._pieces("unverified"))
        assert I.ranked_notes_block("olist") == ""

    def test_the_gate_admits_exactly_the_checked_kind(self):
        from aughor.hub.injection import INJECTABLE_SOURCE_KINDS
        assert INJECTABLE_SOURCE_KINDS == ("conversation:measured",)

    def test_the_adapter_reads_the_check_into_the_envelope(self, monkeypatch):
        from aughor.hub import adapters as A
        row = {"id": "n1", "note": "187 breached", "status": "pending", "provenance": {"author": "Ana"},
               "check": {"verification": "measured"}, "last_seen": "2026-09-23"}
        monkeypatch.setattr(A, "_noted_object_refs", lambda cid: [PROMISE])
        monkeypatch.setattr("aughor.ontology.agent_notes.object_notes_for", lambda cid, ref: [row])
        piece = A.conversation_note_pieces("olist")[0]
        assert piece.provenance.authority == "measured" and piece.provenance.verification == "measured"
