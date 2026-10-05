"""Phase 1 of the 2027 study, P1-3 — decisions booked as a BY-PRODUCT of the doors that exist
(`aughor/record/byproducts.py`, `aughor/routers/record.py`).

What these hold: accepting a recommendation books a Decision with the deep analysis's claims as
what was relied on, the review date proposed from the settling lag (one date, the outcome
record's and the decision's), and the expectation line as a prediction claim when the request
carries one — never guessed when it does not, and said so; a decline before any acceptance is a
decision too; the person's answer at review books the Outcome against the expectation and says
the comparison against the metric's own history is still owed; approving or rejecting a staged
proposal books a decision with the action it arms; the declare door takes a decision in its own
words and refuses a relied-on id the Record does not hold; and the Record's read doors answer
as recorded on a date.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from aughor.actions import inbox
from aughor.db.history import complete_investigation, create_investigation
from aughor.playbook import outcomes as O
from aughor.record import claims as C
from aughor.record import decisions as D
from aughor.routers import investigations as inv
from aughor.routers import record as R

SPEC = {"metric_label": "total sales", "metric_sql": "SUM(sale_price)", "metric_table": "thelook.order_items",
        "date_column": "thelook.order_items.created_at", "window_days": 14, "window_basis": "observation"}


@pytest.fixture(autouse=True)
def _hermetic(tmp_path, monkeypatch):
    monkeypatch.setattr(O, "_DEFAULT_PATH", tmp_path / "recommendation_outcomes.json")
    import aughor.settling.store as settling
    monkeypatch.setattr(settling, "learned_lag_days", lambda conn_id: 5)


def _deep_answer(conn: str, *, spec=SPEC) -> str:
    """A completed deep analysis with its receipt, so the Record holds its observation."""
    inv_id = create_investigation("why did sales fall?", conn)
    complete_investigation(inv_id, report={"headline": "Sales fell on fewer first orders", "spec": spec,
                                           "recommended_actions": ["Raise the free-shipping threshold"]},
                           hypotheses=[], query_history=[], question="why did sales fall?", connection_id=conn,
                           skip_index=True, cache=False)
    from aughor.kernel.ledger import DEEP_REPORT_KIND
    out = inv.write_answer_receipt(kind=DEEP_REPORT_KIND, natural_key=f"deep:{conn}:{inv_id}",
                                   question="why did sales fall?", sqls=["SELECT SUM(sale_price) FROM order_items"],
                                   headline="Sales fell on fewer first orders", schema="", connection_id=conn,
                                   payload_extra={"investigation_id": inv_id})
    assert out["claim_id"]
    return inv_id


def _conn():
    return "conn-" + uuid.uuid4().hex[:6]


# ── the acceptance door ────────────────────────────────────────────────────────────────────

def test_accepting_a_recommendation_books_the_decision_with_its_expectation_and_what_it_relied_on():
    conn = _conn()
    inv_id = _deep_answer(conn)
    req = inv.OutcomeRequest(rec_text="Raise the free-shipping threshold", status="accepted", metric_before=100.0,
                             expectation=inv.ExpectationRequest(direction="up", low=2, high=4, unit="%"))
    rec = inv.log_recommendation_outcome(inv_id, 0, req, principal=None)
    d = D.latest_decision(D.Source(kind="recommendation", ref=f"{inv_id}_rec_0"))
    assert d is not None and d.chosen == "accept" and d.question == "Raise the free-shipping threshold"
    assert [o.id for o in d.options] == ["accept", "decline"]
    # one review date: the outcome record's and the decision's, 30 days plus the learned lag of 5
    today = datetime.now(timezone.utc).date()
    assert d.review_on == rec["review_at"][:10] == (today + timedelta(days=35)).isoformat()
    assert "settling lag of 5 days" in d.extra["review_on_why"]
    # relied on: the deep analysis's observation, as recorded
    obs = C.latest(C.claim_key("observation", "answer", conn, inv_id))
    assert obs is not None and d.relied_on == [obs.id] and C.relied_on_by(obs.id) == [d.id]
    # the expectation, as a prediction claim: the metric from the answer's own definition
    pred = C.get(d.expectation_claim)
    assert pred.kind == "prediction" and pred.statement.metric == "total sales" and pred.state == "open"
    assert pred.statement.text == f"expected: total sales +2% to +4% by {d.review_on}"
    assert pred.extra["settles_on"] == d.review_on
    assert "expectation_note" not in d.extra


def test_an_acceptance_without_an_expectation_says_so_and_a_named_review_days_is_kept():
    conn = _conn()
    inv_id = _deep_answer(conn, spec=None)
    req = inv.OutcomeRequest(rec_text="Call the top ten accounts", status="accepted", review_days=10)
    rec = inv.log_recommendation_outcome(inv_id, 0, req, principal=None)
    d = D.latest_decision(D.Source(kind="recommendation", ref=f"{inv_id}_rec_0"))
    assert d.expectation_claim == "" and "nothing to score" in d.extra["expectation_note"]
    assert d.review_on == rec["review_at"][:10] == (datetime.now(timezone.utc).date() + timedelta(days=10)).isoformat()
    assert d.extra["review_on_why"] == "10 days, as the person asked"
    assert "no measurable definition" in d.extra["review_note"]


def test_a_decline_before_any_acceptance_is_a_decision_too():
    conn = _conn()
    inv_id = _deep_answer(conn)
    inv.log_recommendation_outcome(inv_id, 0, inv.OutcomeRequest(rec_text="Cut the catalogue", status="rejected"),
                                   principal=None)
    d = D.latest_decision(D.Source(kind="recommendation", ref=f"{inv_id}_rec_0"))
    assert d is not None and d.chosen == "decline" and d.outcome == "" and d.relied_on


def test_the_answer_at_review_books_the_outcome_against_the_expectation_and_owes_the_baseline():
    conn = _conn()
    inv_id = _deep_answer(conn)
    inv.log_recommendation_outcome(
        inv_id, 0, inv.OutcomeRequest(rec_text="Raise the threshold", status="accepted", metric_before=100.0,
                                      expectation=inv.ExpectationRequest(direction="up", low=2, high=4, unit="%")),
        principal=None)
    inv.log_recommendation_outcome(
        inv_id, 0, inv.OutcomeRequest(rec_text="Raise the threshold", status="verified", metric_after=103.0),
        principal=None)
    src = D.Source(kind="recommendation", ref=f"{inv_id}_rec_0")
    d = D.latest_decision(src)
    assert d.version == 2 and d.outcome
    o = D.outcome_by_id(d.outcome)
    assert o.verdict == "as_expected" and o.against_expectation == "inside" and o.baseline is None
    assert o.actual == 103.0 and o.extra["before"] == 100.0 and o.effect.method == "before_after"
    assert "not yet against the metric's own history" in o.why
    pred = C.latest(C.claim_key("prediction", D.decision_key(src)))
    assert pred.state == "scored" and pred.extra["scored_against"] == "inside"
    # a second answer books no second outcome: it is laid beside the first as a restatement (phase 3),
    # the decision pointing at the new version — both answers kept
    inv.log_recommendation_outcome(
        inv_id, 0, inv.OutcomeRequest(rec_text="Raise the threshold", status="rejected"), principal=None)
    latest = D.latest_decision(src)
    restated = D.outcome_by_id(latest.outcome)
    assert restated.key == o.key and restated.id != o.id and restated.extra["answer"] == "rejected"
    assert restated.verdict == "as_expected"                    # the measured verdict stays as booked


def test_a_relative_expectation_with_no_before_value_cannot_be_compared_and_says_so():
    conn = _conn()
    inv_id = _deep_answer(conn)
    inv.log_recommendation_outcome(
        inv_id, 0, inv.OutcomeRequest(rec_text="r", status="accepted",
                                      expectation=inv.ExpectationRequest(direction="up", low=2, high=4, unit="%")),
        principal=None)
    inv.log_recommendation_outcome(inv_id, 0, inv.OutcomeRequest(rec_text="r", status="rejected", metric_after=90.0),
                                   principal=None)
    o = D.outcome_by_id(D.latest_decision(D.Source(kind="recommendation", ref=f"{inv_id}_rec_0")).outcome)
    assert o.verdict == "worse" and o.against_expectation == "cannot_tell"


# ── the approval door ──────────────────────────────────────────────────────────────────────

def _proposal(**kw) -> inbox.StagedProposal:
    base = dict(connection_id=_conn(), action_id="refund", params={"order_id": "8821"}, source="agent",
                reasoning="the order is 40 days past its return window")
    base.update(kw)
    return inbox.StagedProposal(**base)


def test_approving_and_rejecting_a_proposal_each_book_a_decision():
    p = inbox.stage_proposal(_proposal())
    inbox.accept_proposal(p.id, actor="human:ana")        # the action no longer exists; the decision stands
    d = D.latest_decision(D.Source(kind="approval", ref=p.id))
    assert d.chosen == "approve" and d.actions == ["refund"] and d.decided_by == "human:ana"
    assert d.question == "refund: the order is 40 days past its return window"
    assert d.extra["proposal_kind"] == "declared_action" and "no expectation line" in d.extra["expectation_note"]
    assert d.connection_id == p.connection_id and d.review_on   # proposed, 30 + 5
    q = inbox.stage_proposal(_proposal())
    assert inbox.reject_proposal(q.id, actor="human:bo")
    dq = D.latest_decision(D.Source(kind="approval", ref=q.id))
    assert dq.chosen == "decline" and dq.actions == [] and dq.decided_by == "human:bo"
    # a double accept resolves nothing and books nothing more
    inbox.accept_proposal(p.id, actor="human:ana")
    assert D.latest_decision(D.Source(kind="approval", ref=p.id)).version == 1


def test_a_proposal_raised_from_an_investigation_relies_on_its_claims():
    conn = _conn()
    inv_id = _deep_answer(conn)
    p = inbox.stage_proposal(_proposal(connection_id=conn, source=f"investigation:{inv_id}"))
    inbox.accept_proposal(p.id, actor="human")
    d = D.latest_decision(D.Source(kind="approval", ref=p.id))
    assert d.relied_on == [C.latest(C.claim_key("observation", "answer", conn, inv_id)).id]


# ── the declare door and the read doors ────────────────────────────────────────────────────

def test_the_declare_door_books_a_decision_in_its_own_words():
    conn = _conn()
    inv_id = _deep_answer(conn)
    obs = C.latest(C.claim_key("observation", "answer", conn, inv_id))
    view = R.declare_record_decision(R.DeclareDecisionRequest(
        question="Pause the spring promotion?", chosen="pause", options=["pause", "continue"],
        owner="user:ana", relied_on=[obs.id], connection_id=conn, decided_by="user:ana",
        dissent=[R.DissentIn(who="user:bo", why="the promotion funds the Q2 target")],
        expectation=R.ExpectationIn(metric="return_rate", direction="down", low=-3, high=-1, unit="%"),
        note="decided in the Monday meeting"), principal=None)
    assert view["chosen"] == "pause" and view["source"]["kind"] == "declared"
    assert [o["id"] for o in view["options"]] == ["pause", "continue"]
    assert view["relied_on_claims"][0]["id"] == obs.id and view["dissent"][0]["who"] == "user:bo"
    assert view["expectation"]["kind"] == "prediction" and view["expectation"]["tier"] == "declared"
    assert view["review_on"] == (datetime.now(timezone.utc).date() + timedelta(days=35)).isoformat()
    assert view["outcome_record"] is None
    # an outcome booked through the door
    booked = R.book_record_outcome(view["id"], R.OutcomeIn(measured_on="2026-11-20", actual=9.1, baseline=10.0,
                                                           verdict="better", why="below the band", against_expectation="below"),
                                   principal=None)
    assert booked["decision"]["outcome"] == booked["outcome_id"] and booked["decision"]["version"] == 2
    assert R.get_record_decision(view["id"])["outcome_record"]["verdict"] == "better"


def test_the_declare_door_refuses_what_it_cannot_cite_or_name():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        R.declare_record_decision(R.DeclareDecisionRequest(question="q", chosen="x", relied_on=["not-a-claim"]),
                                  principal=None)
    assert exc.value.status_code == 422 and "not a claim in the Record" in exc.value.detail
    with pytest.raises(HTTPException):
        R.declare_record_decision(R.DeclareDecisionRequest(question="  ", chosen="x"), principal=None)
    with pytest.raises(HTTPException):
        R.book_record_outcome("nope", R.OutcomeIn(measured_on="2026-11-20"), principal=None)


def test_the_read_doors_list_claims_as_recorded_and_decisions_due():
    conn = _conn()
    inv_id = _deep_answer(conn)
    key = C.claim_key("observation", "answer", conn, inv_id)
    first = C.latest(key)
    C.restate(key, first.model_copy(update={"statement": C.Statement(text="restated", metric=""), "confidence": None}))
    now = [c for c in R.list_record_claims(connection_id=conn, kind="observation") if c["key"] == key]
    assert [c["statement"]["text"] for c in now] == ["restated"]
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    assert [c for c in R.list_record_claims(connection_id=conn, as_of=yesterday) if c["key"] == key] == []
    versions = R.get_record_claim_versions(first.id)
    assert [v["statement"]["text"] for v in versions] == ["restated", "Sales fell on fewer first orders"]
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        R.list_record_claims(as_of="not a date")
    # a decision due: declared with a review date in the past
    view = R.declare_record_decision(R.DeclareDecisionRequest(question="q", chosen="x", connection_id=conn,
                                                              review_on="2026-01-01"), principal=None)
    due = R.list_record_decisions(connection_id=conn, due=True)
    assert any(d["id"] == view["id"] for d in due)
    assert R.get_record_claim(first.id)["relied_on_by"] == []
