"""Decision kinds and the proposal of a declared kind under a mission (the decision-framework study §3.1 and §8 step 4,
`docs/DECISION_FRAMEWORK_STUDY_2026-10-26.md`; `aughor/record/kinds.py`).

What these hold: people declare kinds and a model never does; a kind is edited as a new version, the old kept; a
decision of a declared kind keeps its kind's rules at the door — refused without the expectation its kind requires,
its approvers and review date defaulted from the kind, the kind kept on it; an undeclared or retired kind is refused
by name; method 4 reads the past decisions of the same declared kind; and under an active mission the platform
proposes a decision of each declared kind that usually moves the objective, each option with what the Record
predicts for it — composed by code, booked by nobody until a person decides.
"""
from __future__ import annotations

import uuid

import pytest

from aughor.kernel.flags import flag_overrides
from aughor.record import byproducts as B
from aughor.record import decisions as D
from aughor.record import kinds as K
from aughor.record import mission as M
from aughor.record import scenario as S


@pytest.fixture(autouse=True)
def _no_lag(monkeypatch):
    import aughor.settling.store as settling
    monkeypatch.setattr(settling, "learned_lag_days", lambda conn_id: 0)


def _name(stem: str) -> str:
    return f"{stem} {uuid.uuid4().hex[:6]}"


def _kind(**kw) -> K.DecisionKind:
    base = dict(name=_name("a price change"), metrics=["gmv"], review_days=14, approvers=["person:ana"])
    base.update(kw)
    return K.write_kind(K.DecisionKind(**base), by="user:amit")


def test_people_declare_kinds_and_a_model_never_does():
    with pytest.raises(K.KindRefused, match="a model never does"):
        K.write_kind(K.DecisionKind(name="a price change"), by="agent:analyst", by_kind="agent")
    with pytest.raises(K.KindRefused, match="a model never does"):
        K.write_kind(K.DecisionKind(name="a price change"), by="system", by_kind="system")
    with pytest.raises(K.KindRefused, match="has a name"):
        K.write_kind(K.DecisionKind(name="  "), by="user:amit")
    with pytest.raises(K.KindRefused, match="between 1 and 366"):
        K.write_kind(K.DecisionKind(name="x", review_days=0), by="user:amit")
    with pytest.raises(K.KindRefused, match="L0–L5"):
        K.write_kind(K.DecisionKind(name="x", authority_ceiling=7), by="user:amit")


def test_a_kind_is_edited_as_a_new_version_and_read_as_it_stands():
    k = _kind()
    assert k.key == K.kind_key(k.name) and k.declared_by == "user:amit" and k.version == 1
    edited = K.write_kind(k.model_copy(update={"expectation_required": True}), by="user:ana")
    assert edited.version == 2 and edited.id != k.id and edited.declared_by == "user:ana"
    assert K.get_kind(k.name).expectation_required and K.get_kind(k.key).id == edited.id
    assert K.get_kind(k.id).id == edited.id                       # an old id reads the kind as it stands now
    assert [x.id for x in K.list_kinds() if x.key == k.key] == [edited.id]


def test_a_decision_of_a_declared_kind_keeps_its_rules_at_the_door():
    k = _kind(expectation_required=True)
    with pytest.raises(ValueError, match=f"a decision of the kind {k.name} says what it expects"):
        B.declare_decision(question="Cut the discount?", chosen="cut it", connection_id="c1", decided_by="user:amit",
                           kind=k.key)
    did = B.declare_decision(question="Cut the discount?", chosen="cut it", connection_id="c1", decided_by="user:amit",
                             decided_at="2026-08-01T09:00:00+00:00", kind=k.name,
                             expectation={"metric": "gmv", "direction": "up"})
    d = D.get_decision(did)
    assert d.kind == k.key and d.approvers == ["person:ana"] and d.review_on == "2026-08-15"
    named = B.declare_decision(question="Cut it?", chosen="cut it", connection_id="c1", decided_by="user:amit",
                               approvers=["person:ben"], kind=k.key, expectation={"metric": "gmv"})
    assert D.get_decision(named).approvers == ["person:ben"]


def test_an_undeclared_or_retired_kind_is_refused_by_name():
    with pytest.raises(ValueError, match="no kind of decision named 'a supplier switch' is declared"):
        B.declare_decision(question="Switch?", chosen="switch", decided_by="user:amit", kind="a supplier switch")
    k = _kind()
    K.write_kind(k.model_copy(update={"state": "retired"}), by="user:amit")
    with pytest.raises(ValueError, match="is retired"):
        B.declare_decision(question="Cut?", chosen="cut", decided_by="user:amit", kind=k.key)
    plain = B.declare_decision(question="Cut?", chosen="cut", decided_by="user:amit")
    assert D.get_decision(plain).kind == ""                      # without a kind, nothing changes


def _decided_and_reviewed(conn: str, kind: str, effect: float, verdict: str = "as_expected") -> str:
    did = B.declare_decision(question=f"Cut the discount {uuid.uuid4().hex[:4]}", chosen="cut it", connection_id=conn,
                             decided_by="user:amit", kind=kind, expectation={"metric": "gmv", "direction": "up"})
    D.book_outcome(D.Outcome(of=did, measured_on="2026-09-01", actual=100 + effect, baseline=100.0, verdict=verdict,
                             effect=D.Effect(value=effect, low=effect - 1, high=effect + 1, method="comparison")))
    return did


def test_method_4_reads_the_past_decisions_of_the_same_declared_kind():
    conn = "conn-" + uuid.uuid4().hex[:6]
    k, other = _kind(), _kind(name=_name("a supplier switch"))
    for e in (4.0, 6.0, 5.0):
        _decided_and_reviewed(conn, k.key, e)
    _decided_and_reviewed(conn, other.key, -30.0, "worse")
    cases = S.intervention_cases(metric="gmv", connection_id=conn, kind=k.key)
    assert len(cases) == 3 and {c["matched_on"] for c in cases} == {"kind"}
    p = S.intervention(metric="gmv", connection_id=conn, kind=k.key)
    assert p.value == pytest.approx(5.0) and p.backtest["n"] == 3 and p.backtest["held"] == 3
    few = S.intervention(metric="gmv", connection_id=conn, kind=other.key)
    assert few.value is None and "only 1 past decision" in few.note


def _mission(conn: str, metric: str = "gmv") -> M.Mission:
    return M.write_mission(M.Mission(
        name=_name("Grow GMV in Canada"), objective=M.Objective(metric=metric, direction="up"),
        scope=M.Scope(connections=[conn]), owner="user:amit", state="active"), by="user:amit")


def test_under_a_mission_the_platform_proposes_each_declared_kind_that_moves_its_objective():
    conn = "conn-" + uuid.uuid4().hex[:6]
    k = _kind()
    elsewhere = _kind(name=_name("a supplier switch"), metrics=["weeks_of_cover"])   # moves another metric
    retired = _kind()
    K.write_kind(retired.model_copy(update={"state": "retired"}), by="user:amit")
    for e in (4.0, 6.0, 5.0):
        _decided_and_reviewed(conn, k.key, e)
    m = _mission(conn)
    report = {"objective": {"baseline": 1000.0, "baseline_low": 900.0, "baseline_high": 1100.0,
                            "baseline_note": "6 prior windows"}}
    every = K.proposals_for(m, report=report)
    assert elsewhere.key not in {p["kind"] for p in every} and retired.key not in {p["kind"] for p in every}
    props = [p for p in every if p["kind"] == k.key]
    assert len(props) == 1
    p = props[0]
    assert p["options"][0]["option"] == k.name and p["options"][1]["option"] == "not act"
    act, hold = p["options"][0]["predicted"], p["options"][1]["predicted"]
    assert act["method"] == "intervention" and act["effect"] == pytest.approx(5.0)
    assert hold == {"method": "history", "low": 900.0, "high": 1100.0, "value": 1000.0, "says": "6 prior windows"}
    assert p["approvers"] == ["person:ana"] and p["expectation"] == {"metric": "gmv", "direction": "up"}
    assert p["composed_by"].endswith("no model")
    # no report yet, no past decisions: both are said, nothing is invented
    fresh = _kind()
    q = next(x for x in K.proposals_for(_mission("conn-" + uuid.uuid4().hex[:6])) if x["kind"] == fresh.key)
    assert "only 0 past decisions" in q["options"][0]["predicted"]["says"]
    assert "was not measured" in q["options"][1]["predicted"]["says"]


def test_the_routes_declare_as_the_person_signed_in_and_list_proposals(monkeypatch):
    from fastapi import HTTPException

    from aughor.routers import record as R
    monkeypatch.setattr(R, "_who", lambda principal: "user:amit")
    out = R.declare_decision_kind(R.DecisionKindRequest(name=_name("a budget move"), metrics=["gmv"]), principal=None)
    assert out["declared_by"] == "user:amit" and out["key"].startswith("decision_kind:")
    assert any(k["key"] == out["key"] for k in R.list_decision_kinds()["kinds"])
    monkeypatch.setattr(R, "_who", lambda principal: "agent:analyst")
    with pytest.raises(HTTPException) as e:
        R.declare_decision_kind(R.DecisionKindRequest(name="x"), principal=None)
    assert e.value.status_code == 422
    conn = "conn-" + uuid.uuid4().hex[:6]
    m = _mission(conn)
    got = R.list_mission_proposals(m.id)
    assert got["mission"] == m.id and any(p["kind"] == out["key"] for p in got["proposals"])


def test_with_the_loop_off_a_kind_still_holds_its_rules():
    """Kinds are the organisation's declarations, not the review's: they hold at the door with the loop off too."""
    k = _kind(expectation_required=True)
    with flag_overrides({"record.decision_loop": False}):
        with pytest.raises(ValueError, match="says what it expects"):
            B.declare_decision(question="Cut?", chosen="cut", decided_by="user:amit", kind=k.key)
