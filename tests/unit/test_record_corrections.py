"""Phase 5 of the 2027 study, P5-3 — Corrections as a first-class view (`aughor/record/corrections.py`,
`GET /record/corrections`).

What these hold: the five records the study §N names are read back from the ledger under one
heading, each with what was believed and what replaced it — a restated claim with its earlier text,
a refuted hypothesis with its evidence, a missed move booked by the review of a miss (and only when
the review found one), a scored prediction whose actual fell outside its band, and a decision whose
outcome was worse than expected with its question and expectation; the counts are by kind; an
unknown kind is refused by name.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest

from aughor.monitors import missed as MM
from aughor.record import claims as C
from aughor.record import corrections as X
from aughor.record import decisions as D
from aughor.record import scenario as S
from aughor.routers import record as R


def _conn():
    return "conn-" + uuid.uuid4().hex[:6]


def _said(conn: str, text: str, key: str, **extra) -> str:
    claim = C.Claim(kind="observation", tier="said", about=C.About(kind="connection", key=conn),
                    statement=C.Statement(text=text, metric="orders"), status="Provisional", as_of="2026-10-01",
                    author="system", extra=extra)
    return C.book(claim, key=key, conn_id=conn)


def test_a_restated_claim_is_a_correction_with_what_was_first_said():
    conn = _conn()
    key = C.claim_key("observation", "answer", conn, "inv1")
    first = _said(conn, "Orders were 1,200 last week", key)
    second = _said(conn, "Restated: orders were 1,310 last week. First said: 1,200", key, cause="late_rows")
    rows = X.restatements(conn_id=conn)
    assert len(rows) == 1 and rows[0]["ref"] == second and rows[0]["superseded"] == first
    assert rows[0]["believed"] == "Orders were 1,200 last week" and rows[0]["replaced_by"].startswith("Restated:")
    assert rows[0]["why"] == "late_rows" and rows[0]["claim_kind"] == "observation"


def test_a_refuted_hypothesis_is_a_correction_with_its_evidence():
    conn = _conn()
    claim = C.Claim(kind="hypothesis", tier="said", about=C.About(kind="connection", key=conn),
                    statement=C.Statement(text="late dispatch drove the returns"), status="Provisional", as_of="2026-10-01",
                    warrants=[C.Warrant(kind="run", ref="inv-7", detail="returns rose equally for on-time and late dispatch")],
                    author="inquirer", author_kind="agent", state="refuted",
                    extra={"run": "inv-7", "inquiry": "inquiry:x", "evidence": "returns rose equally for on-time and late dispatch"})
    cid = C.book(claim, key=C.claim_key("hypothesis", conn, "x", "H1"), conn_id=conn)
    open_claim = claim.model_copy(deep=True)
    open_claim.state, open_claim.warrants, open_claim.extra = "open", [], {}
    C.book(open_claim, key=C.claim_key("hypothesis", conn, "x", "H2"), conn_id=conn)
    rows = X.refuted_hypotheses(conn_id=conn)
    assert [r["ref"] for r in rows] == [cid] and rows[0]["believed"] == "late dispatch drove the returns"
    assert rows[0]["replaced_by"].startswith("returns rose equally") and rows[0]["run"] == "inv-7"


def _review(conn: str, verdict: str, value=12.4, z=3.1) -> MM.MissReview:
    return MM.MissReview(connection_id=conn, metric="refund rate", day="2026-09-30", value=value, z=z, verdict=verdict,
                         watches=[MM.Watch(kind="monitor", id="m1", name="refund watch", enabled=True, existed_on_day=True,
                                           rule="anomaly at 3σ", would_have_fired=False)])


def test_a_missed_move_is_booked_only_when_the_review_found_a_miss():
    conn = _conn()
    moved = "refund rate read 12.4 on 2026-09-30, 3.1σ from the 90 days before it"
    assert MM.is_miss(_review(conn, f"{moved}. Nothing was watching it. A 2.5σ watch would have caught it."))
    assert MM.is_miss(_review(conn, f"{moved}. 'refund watch' was watching it (anomaly at 3σ) and its rule did not count that as a breach."))
    assert MM.is_miss(_review(conn, f"{moved}. 'refund watch' watches it, but it was switched off."))
    assert not MM.is_miss(_review(conn, f"{moved}. It WAS flagged: 'refund watch' fired on 2026-09-30."))
    assert not MM.is_miss(_review(conn, f"{moved}. That day is still settling — it will be scored on 2026-10-02."))
    assert not MM.is_miss(_review(conn, f"{moved}. That is an ordinary day by this series' own spread.", z=0.4))
    assert not MM.is_miss(_review(conn, "The series of refund rate has no value on 2026-09-30.", value=None))
    assert MM.book_missed_move(_review(conn, f"{moved}. It WAS flagged: 'refund watch' fired.")) == ""
    first = MM.book_missed_move(_review(conn, f"{moved}. Nothing was watching it. A 2.5σ watch would have caught it."))
    assert first
    rows = X.missed_moves(conn_id=conn)
    assert len(rows) == 1 and rows[0]["ref"] == first and rows[0]["metric"] == "refund rate" and rows[0]["z"] == 3.1
    assert rows[0]["believed"] == "nothing on refund rate needed flagging on 2026-09-30"
    assert rows[0]["replaced_by"].startswith(moved) and rows[0]["watches"] == 1
    # a second review of the same day restates the one entry — one correction, not two
    second = MM.book_missed_move(_review(conn, f"{moved}. Nothing was watching it. It is proposed in the inbox (proposal p1)."))
    assert second != first and [r["ref"] for r in X.missed_moves(conn_id=conn)] == [second]


def test_a_prediction_outside_its_band_and_a_decision_worse_than_expected_are_corrections():
    conn = _conn()
    pid = S.predict(metric="orders", projection=S.identity("base * 1.1", {"base": 1000}, unit=""), settles_on="2026-10-01",
                    author="system", connection_id=conn, direction="up")
    inside = S.predict(metric="orders", projection=S.identity("base", {"base": 500}), settles_on="2026-10-01",
                       author="system", connection_id=conn)
    S.score_prediction(C.get(pid), actual=1400.0, measured_on="2026-10-02")
    S.score_prediction(C.get(inside), actual=500.0, measured_on="2026-10-02")
    preds = X.predictions_outside_interval(conn_id=conn)
    assert len(preds) == 1 and preds[0]["against"] == "above" and preds[0]["actual"] == 1400.0 and preds[0]["method"] == "identity"
    assert preds[0]["believed"].startswith("expected: orders 1,100") and "above the band" in preds[0]["replaced_by"]
    did = D.book_decision(D.Decision(question="raise the free-shipping threshold?", chosen="yes", decided_by="user:ana",
                                     connection_id=conn, source=D.Source(kind="declared", ref=uuid.uuid4().hex[:8])),
                          expectation=D.Expectation(metric="orders", direction="up", low=2, high=4, unit="%"), author="user:ana")
    D.book_outcome(D.Outcome(of=did, measured_on="2026-11-01", actual=900.0, baseline=1000.0, verdict="worse",
                             why="the metric moved -100 against its own history, the wrong way for 'up'",
                             against_expectation="below"))
    fine = D.book_decision(D.Decision(question="keep the price?", chosen="yes", decided_by="user:ana", connection_id=conn,
                                      source=D.Source(kind="declared", ref=uuid.uuid4().hex[:8])))
    D.book_outcome(D.Outcome(of=fine, measured_on="2026-11-01", actual=1.0, baseline=1.0, verdict="as_expected", why="flat"))
    worse = X.decisions_worse_than_expected(conn_id=conn)
    assert len(worse) == 1 and worse[0]["decision"] == did and worse[0]["actual"] == 900.0
    assert worse[0]["believed"].startswith("raise the free-shipping threshold? → yes; expected: orders +2% to +4%")
    assert "wrong way" in worse[0]["replaced_by"]


def test_the_door_counts_by_kind_and_refuses_an_unknown_kind():
    conn = _conn()
    key = C.claim_key("observation", "answer", conn, "inv2")
    _said(conn, "Returns were 4%", key)
    _said(conn, "Restated: returns were 5%", key)
    MM.book_missed_move(_review(conn, "refund rate read 9 on 2026-09-30, 3σ from the days before it. Nothing was watching it."))
    out = R.record_corrections(connection_id=conn)
    assert out["counts"] == {"restatement": 1, "refuted_hypothesis": 0, "missed_move": 1,
                             "prediction_outside_interval": 0, "decision_worse_than_expected": 0}
    assert [e["kind"] for e in out["entries"]] == ["missed_move", "restatement"] or \
           [e["kind"] for e in out["entries"]] == ["restatement", "missed_move"]
    assert set(out["labels"]) == set(X.KINDS) and "0 has none recorded" in out["note"]
    only = R.record_corrections(connection_id=conn, kind="restatement")
    assert [e["kind"] for e in only["entries"]] == ["restatement"] and only["counts"]["missed_move"] == 1
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        R.record_corrections(connection_id=conn, kind="typo")
    assert e.value.status_code == 422 and "no correction kind named 'typo'" in e.value.detail
    assert date.fromisoformat(out["entries"][0]["at"][:10])
