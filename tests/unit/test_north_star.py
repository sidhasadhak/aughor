"""Track G5 (docs/TENX_PROGRAM_2026-11-05.md; the study's §X): the North Star as a query.

Closed loops per quarter, guarded by calibration error, each with its n — and every outcome that did
not close says the rule it failed. Built on real decisions, claims and outcomes in the suite's ledger,
so the five rules are tested against what booking actually writes. On the live install on 2026-11-06
it read: 0 loops closed of 16 outcomes written (all 16 predictions booked after back-dated decisions)
· calibration error 0.40 over 101 settled predictions.
"""
from __future__ import annotations

import datetime as dt
import uuid

import pytest

from aughor.record import claims as C
from aughor.record import decisions as D
from aughor.record import north_star as NS

TODAY = dt.datetime.now(dt.timezone.utc)
CONN = "ns-" + uuid.uuid4().hex[:6]
LABEL, START, END = NS.quarter_bounds("", today=TODAY.date())


def _decide(*, decided_at: str = "", expectation: bool = True, owner: str = "user:ana") -> str:
    src = D.Source(kind="declared", ref="ns-" + uuid.uuid4().hex[:8])
    return D.book_decision(
        D.Decision(question="pause the promotion?", chosen="yes", owner=owner, decided_by="user:ana",
                   decided_at=decided_at, review_on=TODAY.date().isoformat(), connection_id=CONN, source=src),
        expectation=D.Expectation(metric="return_rate", direction="down", low=-3, high=-1, unit="%")
        if expectation else None, author="user:ana")


def _outcome(did: str, **kw) -> str:
    base = dict(of=did, measured_on=TODAY.date().isoformat(), actual=9.7, baseline=10.0,
                effect=D.Effect(value=-0.3, low=-0.8, high=0.2, method="history"), verdict="worse",
                why="inside the baseline's own noise", against_expectation="below",
                writes_back=["claim class: return_rate · history", "playbook: pause-promotion"])
    return D.book_outcome(D.Outcome(**{**base, **kw}))


def _row(result: dict, did: str) -> dict:
    return next(r for r in result["closed"] + result["not_closed"] if r["decision"] == did or did in r["decision"])


@pytest.fixture
def star():
    return lambda: NS.north_star(LABEL, conn_id=CONN, today=TODAY.date())


def test_a_loop_with_all_five_parts_closes(star):
    did = _decide()
    _outcome(did)
    s = star()
    assert s["loops_closed"] >= 1 and any(r["question"].startswith("pause") for r in s["closed"])
    assert s["sentence"].startswith(f"{LABEL}: ") and "closed of" in s["sentence"]


def test_a_prediction_booked_after_a_back_dated_decision_is_hindsight(star):
    """The live install's 16: decided 2026-09-01 on paper, predicted weeks later."""
    did = _decide(decided_at=(TODAY - dt.timedelta(days=60)).isoformat())
    _outcome(did)
    latest = D.get_decision(did)
    s = star()
    row = next((r for r in s["closed"] + s["not_closed"] if r["decision"] in (did, latest.superseded_by)), None)
    assert row is not None, "the back-dated decision's outcome is missing from the quarter"
    assert "not_closed" in row, "a prediction booked weeks after its decision was counted as a closed loop"
    assert "hindsight" in row["not_closed"] and "after the decision it predicts" in row["not_closed"]


@pytest.mark.parametrize("change, rule", [
    ({"writes_back": []}, "the write-back did not run"),
    ({"verdict": "cannot_tell", "why": "", "against_expectation": ""}, "cannot tell, and not why"),
    ({"against_expectation": ""}, "none against the expectation"),
])
def test_each_missing_part_is_named(star, change, rule):
    did = _decide()
    _outcome(did, **change)
    assert any(rule in r.get("not_closed", "") for r in star()["not_closed"]), rule


def test_cannot_tell_with_its_reason_still_closes(star):
    did = _decide()
    _outcome(did, verdict="cannot_tell", why="the metric's own noise is wider than the effect", against_expectation="")
    assert any(r["verdict"] == "cannot_tell" for r in star()["closed"])


def test_reliance_without_an_expectation_is_counted_apart(star):
    before = star()["reliance_without_expectation"]
    _outcome(_decide(expectation=False))
    assert star()["reliance_without_expectation"] == before + 1


def test_an_outcome_written_in_another_quarter_is_not_this_quarters(star):
    other, ostart, oend = NS.quarter_bounds("2025-Q1")
    assert NS.closed_loops(ostart, oend, conn_id=CONN) == {"closed": [], "not_closed": [],
                                                           "reliance_without_expectation": 0}


def test_why_not_closed_reads_the_rules_in_order():
    from types import SimpleNamespace as S
    d = S(owner="", decided_at="", review_on="")
    assert NS.why_not_closed(d, None, None) == "no owner is named"
    d.owner = "user:ana"
    assert NS.why_not_closed(d, None, None) == "no prediction was booked with the decision"
    p = S(recorded_at="2026-10-01T00:00:00+00:00", extra={})
    assert NS.why_not_closed(d, None, p) == "the prediction states no day it settles on"
    p.extra = {"settles_on": "2026-11-01"}
    assert NS.why_not_closed(d, None, p) == "no outcome has been written"
    d.review_on = "2026-11-01"
    o = S(recorded_at="2026-10-20T00:00:00+00:00", verdict="better", why="", against_expectation="inside",
          writes_back=["x"])
    assert "before the review date" in NS.why_not_closed(d, o, p)


def test_calibration_error_is_weighted_by_what_each_class_judged():
    q, start, end = NS.quarter_bounds("2031-Q2")        # a quarter nothing else in the suite settles in
    for metric, against in [("ns_a", "inside"), ("ns_a", "inside"), ("ns_a", "above"), ("ns_a", "below"),
                            ("ns_b", "inside"), ("ns_b", "below"), ("ns_b", "cannot_tell")]:
        c = C.Claim(kind="prediction", statement=C.Statement(text=f"{metric} prediction", metric=metric),
                    tier="declared", state="scored", author="user:ana", author_kind="person",
                    extra={"method": "history", "coverage": 0.8, "settles_on": "2031-05-01", "scored_against": against})
        C.book(c, key=C.claim_key("prediction", f"ns-pred-{uuid.uuid4().hex[:8]}"), conn_id=CONN)
    cal = NS.calibration_error(start, end, conn_id=CONN)
    a = next(r for r in cal["classes"] if r["metric"] == "ns_a")
    b = next(r for r in cal["classes"] if r["metric"] == "ns_b")
    assert (a["judged"], a["observed"], a["gap"]) == (4, 0.5, 0.3)
    assert (b["judged"], b["observed"], b["cannot_tell"]) == (2, 0.5, 1)
    assert cal["n"] == 6 and cal["error"] == 0.3                  # (0.3×4 + 0.3×2) / 6


def test_nothing_settled_is_said_not_zero():
    _, start, end = NS.quarter_bounds("2019-Q3")
    assert NS.calibration_error(start, end, conn_id=CONN) == {"error": None, "n": 0, "classes": []}


def test_the_door_answers_and_refuses_a_bad_quarter(client):
    ok = client.get("/record/north-star", params={"quarter": "2026-Q4"})
    assert ok.status_code == 200 and ok.json()["quarter"] == "2026-Q4" and "sentence" in ok.json()
    bad = client.get("/record/north-star", params={"quarter": "2026-Q9"})
    assert bad.status_code == 422 and "2026-Q4" in bad.json()["detail"]
