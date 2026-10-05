"""Phase 1 of the 2027 study, P1-4 and P1-5 — counted confidence and the receipt's two lines.

What these hold: the two reference classes are tallied from what the platform already measures
(re-checks on chat answers; the skeptic's record on deep analyses) and nothing else; a hit rate is
shown only with its n and only from the threshold up — below it the count alone, with why; a claim
on a connection with too few cases is counted across every connection and says so; a kind no
class counts shows nothing and says why; the count is filled on READ and never lands in the
ledger row; and the public receipt carries line two — the counted confidence and who else was
told — rebuilt live on each read, inside the signed body.
"""
from __future__ import annotations

import json
import uuid

import pytest

from aughor.db.history import append_recheck, complete_investigation, create_investigation, save_chat_turn
from aughor.record import claims as C
from aughor.record import confidence as K
from aughor.routers import investigations as inv


def _conn():
    return "conn-" + uuid.uuid4().hex[:6]


def _chat_answer(conn: str, *, rechecks: list[str]) -> str:
    inv_id = save_chat_turn(question="q", connection_id=conn, headline="12", sql="SELECT 12", session_id="s",
                            columns=["total"], rows=[[12]])
    for status in rechecks:
        append_recheck(inv_id, {"checked_at": "2026-09-23T06:00:00Z", "status": status, "changes": [], "cause": "none"})
    return inv_id


def _deep(conn: str, *, refutation: str) -> str:
    inv_id = create_investigation("why?", conn)
    report = {"headline": "Revenue fell because of the price rise",
              "causal_checks": {"licence": "causal", "claims": [], "refutation": {"status": refutation}}}
    complete_investigation(inv_id, report=report, hypotheses=[], query_history=[], question="why?",
                           connection_id=conn, skip_index=True, cache=False)
    return inv_id


# ── the tallies ────────────────────────────────────────────────────────────────────────────

def test_rechecks_are_tallied_per_answer_and_an_unchecked_entry_is_not_a_case():
    conn = _conn()
    _chat_answer(conn, rechecks=["unchanged", "unchanged"])          # held
    _chat_answer(conn, rechecks=["unchanged", "changed"])            # moved once: not a hit
    _chat_answer(conn, rechecks=["unchecked"])                       # measured nothing
    _chat_answer(conn, rechecks=[])                                  # never re-checked
    assert K._tally(K.RECHECKED, conn) == (2, 1)


def test_challenges_are_tallied_only_where_the_check_ran():
    conn = _conn()
    _deep(conn, refutation="survived")
    _deep(conn, refutation="survived")
    _deep(conn, refutation="refuted")
    _deep(conn, refutation="not_run")
    assert K._tally(K.CHALLENGED, conn) == (3, 2)


# ── the counter's rules ────────────────────────────────────────────────────────────────────

def test_below_the_threshold_the_count_is_shown_and_the_rate_is_not():
    conn = _conn()
    _chat_answer(conn, rechecks=["unchanged"])
    c = K.count_class(K.RECHECKED, connection_id=conn)
    assert c.hit_rate is None and c.n >= 1 and c.note.startswith("too few to count")
    assert c.reference_class == K.RECHECKED


def test_from_the_threshold_up_the_rate_is_shown_with_its_n(monkeypatch):
    monkeypatch.setattr(K, "MIN_N", 3)
    conn = _conn()
    for status in (["unchanged"], ["unchanged"], ["changed"], ["unchanged", "unchanged"]):
        _chat_answer(conn, rechecks=status)
    c = K.count_class(K.RECHECKED, connection_id=conn)
    assert (c.n, c.hit_rate, c.scope) == (4, 0.75, conn) and c.note == "3 of 4 held"


def test_a_connection_with_too_few_cases_is_counted_across_every_connection_and_says_so(monkeypatch):
    monkeypatch.setattr(K, "MIN_N", 2)
    thin, thick = _conn(), _conn()
    _deep(thin, refutation="survived")
    for status in ("survived", "refuted", "survived"):
        _deep(thick, refutation=status)
    c = K.count_class(K.CHALLENGED, connection_id=thin)
    assert c.scope == K.ALL and c.n >= 4 and c.hit_rate is not None
    assert "counted across every connection, this one has too few" in c.note


def test_each_claim_kind_knows_its_class_and_an_uncounted_kind_says_why():
    obs_chat = C.Claim(kind="observation", tier="said", statement=C.Statement(text="x"),
                       extra={"receipt_kind": "chat_answer"})
    obs_deep = C.Claim(kind="observation", tier="said", statement=C.Statement(text="x"),
                       extra={"receipt_kind": "ada_report"})
    finding = C.Claim(kind="finding", tier="said", statement=C.Statement(text="x"), extra={"investigation_id": "i"})
    pred = C.Claim(kind="prediction", tier="declared", statement=C.Statement(text="x", metric="m"), author_kind="person")
    definition = C.Claim(kind="definition", tier="said", statement=C.Statement(text="x"))
    assert K.reference_class_of(obs_chat) == K.RECHECKED
    assert K.reference_class_of(obs_deep) == K.CHALLENGED == K.reference_class_of(finding)
    assert K.reference_class_of(pred) == K.PREDICTED
    assert K.reference_class_of(definition) is None
    assert "no reference class counts a claim of kind 'definition'" in K.why_uncounted(definition)


def test_confidence_is_filled_on_read_and_never_lands_in_the_row(monkeypatch):
    monkeypatch.setattr(K, "MIN_N", 1)
    conn = _conn()
    inv_id = _chat_answer(conn, rechecks=["unchanged"])
    out = inv.write_answer_receipt(kind="chat_answer", natural_key=f"chat:{conn}:{inv_id}", question="q",
                                   sqls=["SELECT 12"], headline="12", schema="", connection_id=conn)
    stored = C.get(out["claim_id"])
    assert stored.confidence is None                                           # the row carries none
    seen = K.with_confidence(stored)
    assert seen.confidence is not None and seen.confidence.hit_rate == 1.0 and seen.confidence.n >= 1
    assert C.get(out["claim_id"]).confidence is None                           # still none after the read
    with pytest.raises(C.ClaimRefused, match="counted"):
        C.book(seen, key=stored.key)                                           # a writer still cannot set it
    from aughor.routers import record as R
    view = R.get_record_claim(stored.id)
    assert view["confidence"]["reference_class"] == K.RECHECKED and "confidence_note" not in view


# ── the receipt's two lines ────────────────────────────────────────────────────────────────

def test_the_receipt_carries_the_counted_confidence_and_who_else_was_told(client, monkeypatch):
    monkeypatch.setattr(K, "MIN_N", 1)
    from aughor.govern.departure_store import record_departure
    from aughor.trust.receipt import verify
    conn = _conn()
    inv_id = _chat_answer(conn, rechecks=["unchanged"])
    out = inv.write_answer_receipt(kind="chat_answer", natural_key=f"chat:{conn}:{inv_id}", question="q",
                                   sqls=["SELECT 12"], headline="12 orders", schema="", connection_id=conn)
    record_departure(id=uuid.uuid4().hex[:12], org_id="default", kind="briefing", state="departed", conn_id=conn,
                     automation_id="a1", automation_name="Daily", actor="automation:a1", target="sb:#ops",
                     reasons="[]", checks="{}", guards="{}", text_preview="12 orders", investigation_id=inv_id)
    record_departure(id=uuid.uuid4().hex[:12], org_id="default", kind="briefing", state="held_owner", conn_id=conn,
                     automation_id="a1", automation_name="Daily", actor="automation:a1", target="sb:#finance",
                     addressed_to="user:ana", reasons=json.dumps(["disagreement"]), checks="{}", guards="{}",
                     text_preview="12 orders", investigation_id=inv_id)
    r = client.get(f"/receipt/{out['receipt_id']}")
    assert r.status_code == 200, r.text
    body = r.json()
    rec = body["record"]
    assert rec["claim"]["id"] == out["claim_id"] and rec["claim"]["warrants_this_receipt"] is True
    assert rec["confidence"]["reference_class"] == K.RECHECKED and rec["confidence"]["hit_rate"] == 1.0
    assert [(t["state"], t["target"]) for t in rec["told"]] == [("held_owner", "sb:#finance"), ("departed", "sb:#ops")]
    assert rec["told_note"] == "" and verify(body)                          # inside the signed body
    # an answer that booked no claim says so, and a receipt nothing cited says so
    plain = inv.write_answer_receipt(kind="chat_answer", natural_key=f"chat:{conn}:none", question="how many?",
                                     sqls=["SELECT 1"], headline="how many?", schema="", connection_id=conn)
    rec = client.get(f"/receipt/{plain['receipt_id']}").json()["record"]
    assert rec["claim"] is None and "booked no claim" in rec["confidence_note"]
    assert rec["told"] == [] and "no message citing this answer" in rec["told_note"]


def test_exports_print_a_stated_confidence_as_a_word_never_a_percentage():
    pytest.importorskip("reportlab")                    # the PDF export's optional dependency
    from aughor.export.pdf import _confidence_chip
    assert _confidence_chip(0.83) == "stated confidence: High"
    assert _confidence_chip(0.5) == "stated confidence: Medium" and "%" not in _confidence_chip(0.2)
