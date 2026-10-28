"""The inquiry, as people read it — a decision read from where it arose to what was learned, forwards and backwards, with its loops (the
decision-framework study §3.1 and §3.3; `aughor/record/inquiry_view.py`).

What these hold: a decision taken on an answer reads back to the inquiry it came out of and the claim it stood on,
its options and dissent, who decided, what it expected, its outcome with the numbers, and the scored expectation;
a relied-on claim restated shows as restated and as a reopening loop; a decision that revises another reads
backwards to it, and the older one forwards to it; a stage with nothing in it says so; a reference can be the
decision, a claim it relied on, or its inquiry; and every step carries its why in three layers, composed by code.
"""
from __future__ import annotations

import uuid

import pytest

from aughor.kernel.ledger import DEEP_REPORT_KIND
from aughor.record import byproducts as B
from aughor.record import claims as C
from aughor.record import decisions as D
from aughor.record import inquiry as I
from aughor.record import inquiry_view as T
from aughor.record import writers as W


@pytest.fixture(autouse=True)
def _settled(monkeypatch):
    import aughor.settling.store as settling
    monkeypatch.setattr(settling, "learned_lag_days", lambda conn_id: 0)


def _answered(conn: str) -> tuple[str, str, str]:
    run = "inv-" + uuid.uuid4().hex[:6]
    q = I.attach_run_result(run_id=run, connection_id=conn, question="What did paid social bring?",
                            report={"headline": "Paid social brought 132 of 923 orders", "data_gaps": []}, hypotheses=[])
    out = W.book_from_receipt(kind=DEEP_REPORT_KIND, natural_key=f"ada:{conn}:{run}", receipt_id="rcpt-" + run,
                              connection_id=conn, question="What did paid social bring?",
                              headline="Paid social brought 132 of 923 orders", sql="SELECT 1",
                              payload_extra={"investigation_id": run})
    now = I.for_run(run, conn_id=conn)                 # the receipt landed its claim on the inquiry: a new version
    assert now.id != q.id and now.claims == [out["observation"]]
    return run, out["observation"], now.id


def _stage(t: dict, name: str) -> list[dict]:
    return next(s["steps"] for s in t["stages"] if s["stage"] == name)


def test_a_decision_on_an_answer_reads_from_where_it_arose_to_what_was_learned():
    conn = "conn-" + uuid.uuid4().hex[:6]
    run, observation, inquiry = _answered(conn)
    did = B.declare_decision(question="Pause paid social on Mytheresa?", chosen="pause it",
                             options=["pause it", B.NOT_ACT], dissent=[{"who": "person:ben", "why": "September is peak"}],
                             connection_id=conn, decided_by="user:amit", run_id=run,
                             expectation={"metric": "gmv", "direction": "hold", "low": -3, "high": 3, "unit": "%"})
    D.book_outcome(D.Outcome(of=did, measured_on="2026-10-02", actual=110.0, baseline=100.0, verdict="missed",
                             why="the metric moved +10 against its comparison group, above the ±3% its hold allowed",
                             against_expectation="above", effect=D.Effect(value=10, low=5, high=15, method="comparison")))
    t = T.view_of(did)
    assert [s["stage"] for s in t["stages"]] == list(T.STAGES)
    arising = _stage(t, "arising")
    assert arising[0]["kind"] == "inquiry" and arising[0]["ref"] == inquiry
    assert any(s["kind"] == "door" and s["line"] == "decided on an answer" for s in arising)
    gathering = _stage(t, "gathering")
    assert gathering[0]["ref"] == observation and "Paid social brought 132 of 923 orders" in gathering[0]["why"]
    assert gathering[0]["receipt"]["warrants"] == ["run rcpt-" + run]
    options = _stage(t, "options")
    assert [o["line"] for o in options[:2]] == ["chosen", "not chosen"] and options[2]["line"] == "dissent · person:ben"
    decided = _stage(t, "decided")
    assert decided[0]["line"] == "decided by user:amit" and decided[1]["kind"] == "expectation"
    assert _stage(t, "acting")[0]["line"] == "nothing recorded as run under it"
    reviewed = _stage(t, "reviewed")[0]
    assert reviewed["line"] == "missed" and "above the ±3%" in reviewed["why"]
    assert reviewed["receipt"]["effect"] == 10 and reviewed["receipt"]["method"] == "comparison"
    learned = _stage(t, "learned")
    assert learned[0]["line"] == "the expectation scored above"
    assert t["composed_by"].endswith("no model")
    # the same inquiry, from a claim it relied on and from its inquiry
    assert T.view_of(observation)["decision"] == t["decision"]
    q = I.get_inquiry(inquiry)
    q.decisions.append(did)
    I._book(q)
    assert T.view_of(I.latest(q.key).id)["decision"] == t["decision"]


def test_a_restated_claim_shows_as_restated_and_as_a_reopening_loop():
    conn = "conn-" + uuid.uuid4().hex[:6]
    run, observation, _q = _answered(conn)
    did = B.declare_decision(question="Pause paid social?", chosen="pause it", connection_id=conn,
                             decided_by="user:amit", run_id=run)
    first = C.get(observation)
    changed = first.model_copy(deep=True)
    changed.statement = C.Statement(text="Paid social brought 98 of 923 orders", metric="", value=98)
    restated = C.restate(first.key, changed, conn_id=conn)
    D.reopen_for_claim(observation, restated_as=restated, why="the attribution channel was wrong")
    t = T.view_of(did)
    assert "since restated as “Paid social brought 98 of 923 orders”" in _stage(t, "gathering")[0]["why"]
    assert t["loops"][0]["kind"] == "reopened" and "attribution channel was wrong" in t["loops"][0]["why"]
    assert "waiting for a person's answer" in t["loops"][0]["why"]


def test_a_modifying_decision_reads_backwards_and_the_older_one_forwards():
    conn = "conn-" + uuid.uuid4().hex[:6]
    old = B.declare_decision(question="Free shipping threshold for Canada", chosen="49 EUR", connection_id=conn,
                             decided_by="user:amit", decided_at="2024-05-01T09:00:00+00:00")
    new = B.declare_decision(question="Free shipping threshold for Canada", chosen="69 EUR", connection_id=conn,
                             decided_by="user:ana", revises=old)
    t = T.view_of(new)
    assert t["backwards"] == [{"decision": old, "question": "Free shipping threshold for Canada", "chosen": "49 EUR",
                               "decided_at": "2024-05-01", "why": "this decision revises it"}]
    assert any(s["kind"] == "revises" for s in _stage(t, "arising"))
    assert [f["decision"] for f in T.view_of(old)["forwards"]] == [new]
    with pytest.raises(ValueError, match="is not a decision in the Record"):
        B.declare_decision(question="x", chosen="y", decided_by="user:amit", revises="no-such")


def test_a_stage_with_nothing_in_it_says_so():
    did = B.declare_decision(question="Raise safety stock?", chosen="raise it", decided_by="user:amit")
    t = T.view_of(did)
    for stage in ("gathering", "acting", "reviewed", "learned"):
        steps = _stage(t, stage)
        assert steps and steps[0]["line"], stage
    assert _stage(t, "gathering")[0]["line"] == "it cites nothing"
    assert _stage(t, "decided")[1]["line"] == "nothing expected"
    assert T.view_of("nothing-at-all") is None


def test_the_route_reads_the_inquiry_and_says_when_nothing_reads():
    from fastapi import HTTPException

    from aughor.routers import record as R
    did = B.declare_decision(question="Raise safety stock?", chosen="raise it", decided_by="user:amit")
    assert R.read_record_inquiry_view(did)["decision"] == did
    with pytest.raises(HTTPException) as e:
        R.read_record_inquiry_view("nothing-at-all")
    assert e.value.status_code == 404
