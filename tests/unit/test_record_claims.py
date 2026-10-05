"""Phase 1 of the 2027 study (ROADMAP §3.53) — the Record: one claim ledger in the kernel, two
clocks, supersede-not-delete, and decisions with their expectations booked as a by-product.

Runs on the hermetic test ledger (conftest sets AUGHOR_SYSTEM_DB). Every key is unique per test
so versions do not leak between them.
"""
from __future__ import annotations

import datetime as dt
import uuid

import pytest

from aughor.record import claims as C
from aughor.record import decisions as D


def _key(*parts):
    return C.claim_key(*parts, uuid.uuid4().hex[:8])


def _observation(text="revenue was 1,744 for 12 September", value=1744.0, **kw):
    fields = dict(kind="observation", tier="measured", about=C.About(kind="connection", key="conn-t"),
                  statement=C.Statement(text=text, metric="revenue", value=value, unit="EUR"),
                  status="Provisional", as_of="2026-09-12",
                  warrants=[C.Warrant(kind="run", ref="rcpt-1", detail="SELECT SUM(sale_price) …")],
                  author="analyst", author_kind="agent")
    fields.update(kw)
    return C.Claim(**fields)


# ── the three laws at the door ──────────────────────────────────────────────────────

def test_a_measured_claim_needs_a_run_warrant():
    with pytest.raises(C.ClaimRefused, match="run warrant"):
        C.book(_observation(warrants=[]), key=_key("obs"))


def test_a_models_inference_is_not_a_claim():
    with pytest.raises(C.ClaimRefused, match="hypothesis"):
        C.book(_observation(tier="inferred", warrants=[]), key=_key("obs"))


def test_an_approved_tier_is_a_persons_or_attested():
    with pytest.raises(C.ClaimRefused, match="person"):
        C.book(_observation(kind="definition", tier="approved", author_kind="agent"), key=_key("def"))
    # a person's declaration books; an agent's with an attestation books
    C.book(_observation(kind="definition", tier="approved", author="user:ana", author_kind="person"),
           key=_key("def"))
    C.book(_observation(kind="definition", tier="approved", author_kind="agent",
                        warrants=[C.Warrant(kind="attestation", ref="verdict-9")]), key=_key("def"))


def test_a_writer_cannot_set_confidence():
    c = _observation()
    c.confidence = C.Confidence(reference_class="x", hit_rate=0.9, n=10)
    with pytest.raises(C.ClaimRefused, match="counted"):
        C.book(c, key=_key("obs"))


# ── two clocks, supersession, the belief view ──────────────────────────────────────

def test_a_booked_claim_carries_both_clocks_and_its_warrant_edge():
    key = _key("obs")
    cid = C.book(_observation(), key=key)
    got = C.get(cid)
    assert got is not None and got.as_of == "2026-09-12" and got.recorded_at   # the data's date and the booking's
    assert got.version == 1 and got.supersedes == "" and got.superseded_by == ""
    assert got.confidence is None                                             # nothing counted yet
    from aughor.kernel.ledger import Ledger
    rec = Ledger.default().receipt_by_id(cid)
    assert any(e["relation"] == "warrant:run" and e["ref"] == "rcpt-1" for e in rec["lineage"])


def test_a_restatement_supersedes_and_keeps_the_old_text():
    key = _key("obs")
    first = C.book(_observation(), key=key)
    second = C.restate(key, _observation(text="revenue was 1,802 for 12 September — late rows", value=1802.0))
    old, new = C.get(first), C.get(second)
    assert old.superseded_by == second and old.statement.value == 1744.0        # kept, with its text
    assert new.supersedes == first and new.version == 2 and C.latest(key).id == second
    assert [v.statement.value for v in C.versions(key)] == [1802.0, 1744.0]


def test_restating_nothing_is_refused():
    with pytest.raises(C.ClaimRefused, match="book it first"):
        C.restate(_key("never"), _observation())


def test_belief_is_a_view_as_recorded_on_a_date(monkeypatch):
    """What did we believe on the day between the booking and the restatement?"""
    key = _key("obs")
    first = C.book(_observation(), key=key)
    # Put the first version two days back, so a cutoff can fall between the two bookings.
    from aughor.kernel.ledger import Ledger
    led = Ledger.default()
    past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)).isoformat()
    with led._lock, led._conn:
        led._conn.execute("UPDATE artifacts SET created_at=? WHERE id=?", (past, first))
    C.restate(key, _observation(text="restated", value=1802.0))
    yesterday = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).date().isoformat()
    then = [c for c in C.as_recorded(yesterday) if c.key == key]
    now = [c for c in C.as_recorded(dt.datetime.now(dt.timezone.utc).date().isoformat()) if c.key == key]
    assert [c.statement.value for c in then] == [1744.0]
    assert [c.statement.value for c in now] == [1802.0]
    three_days_ago = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)).date().isoformat()
    assert [c for c in C.as_recorded(three_days_ago) if c.key == key] == []       # not yet believed


def test_list_claims_filters_by_kind_and_about():
    key = _key("hyp")
    C.book(C.Claim(kind="hypothesis", tier="said", about=C.About(kind="object", key="order:O1"),
                   statement=C.Statement(text="late dispatch drove the returns"), state="open",
                   author="inquirer", author_kind="agent"), key=key)
    found = C.list_claims(kind="hypothesis", about_kind="object", about_key="order:O1", state="open")
    assert any(c.key == key for c in found)
    assert not any(c.key == key for c in C.list_claims(kind="observation", about_key="order:O1"))


# ── decisions, expectations, outcomes ──────────────────────────────────────────────

def test_a_decision_books_its_expectation_as_a_prediction_and_records_what_it_relied_on(monkeypatch):
    monkeypatch.setattr("aughor.settling.store.learned_lag_days", lambda cid: 8)
    relied = C.book(_observation(), key=_key("obs"))
    src = D.Source(kind="recommendation", ref="inv1_rec_0:" + uuid.uuid4().hex[:6])
    did = D.book_decision(D.Decision(question="raise the free-shipping threshold?", owner="user:ana",
                                     options=[D.Option(id="a", description="raise to 60"),
                                              D.Option(id="b", description="keep 50")],
                                     chosen="a", relied_on=[relied], decided_by="user:ana",
                                     decided_at="2026-10-05T10:00:00+00:00", connection_id="conn-t", source=src),
                          expectation=D.Expectation(metric="conversion", direction="up", low=2, high=4, unit="%"),
                          author="user:ana")
    d = D.get_decision(did)
    assert d.review_on == "2026-11-12" and "settling lag of 8 days" in d.extra["review_on_why"]   # 30 + 8
    pred = C.get(d.expectation_claim)
    assert pred.kind == "prediction" and pred.tier == "declared" and pred.state == "open"
    assert pred.statement.text == "expected: conversion +2% to +4% by 2026-11-12"
    assert pred.extra["settles_on"] == "2026-11-12"
    assert C.relied_on_by(relied) == [did]
    assert D.latest_decision(src).id == did


def test_an_outcome_stamps_the_decision_and_scores_the_prediction():
    src = D.Source(kind="approval", ref="prop-" + uuid.uuid4().hex[:6])
    did = D.book_decision(D.Decision(question="pause the promotion?", chosen="yes", decided_by="user:ana",
                                     decided_at="2026-09-01T00:00:00+00:00", source=src),
                          expectation=D.Expectation(metric="return_rate", direction="down", low=-3, high=-1, unit="%"))
    due = D.due_for_review(now=dt.datetime(2026, 12, 1, tzinfo=dt.timezone.utc))
    assert any(d.id == did for d in due)
    oid = D.book_outcome(D.Outcome(of=did, measured_on="2026-10-02", actual=9.7, baseline=10.0,
                                   effect=D.Effect(value=-0.3, low=-0.8, high=0.2, method="history"),
                                   verdict="worse", why="inside the baseline's own noise",
                                   against_expectation="below"))
    latest = D.latest_decision(src)
    assert latest.outcome == oid and latest.version == 2 and D.get_decision(did).superseded_by == latest.id
    assert D.get_outcome(did).verdict == "worse"
    pred = C.latest(C.claim_key("prediction", D.decision_key(src)))
    assert pred.state == "scored" and pred.extra["scored_against"] == "below" and pred.version == 2
    assert not any(d.id == latest.id for d in D.due_for_review(now=dt.datetime(2026, 12, 1, tzinfo=dt.timezone.utc)))


def test_an_outcome_of_nothing_is_refused():
    with pytest.raises(ValueError, match="no decision"):
        D.book_outcome(D.Outcome(of="nope", measured_on="2026-10-02"))


def test_the_review_date_says_which_rule_it_used(monkeypatch):
    monkeypatch.setattr("aughor.settling.store.learned_lag_days", lambda cid: None)
    on, why = D.propose_review_on("conn-t", dt.datetime(2026, 10, 5, tzinfo=dt.timezone.utc))
    assert on == "2026-11-04" and "no learned settling lag" in why
