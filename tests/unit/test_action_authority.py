"""Phase 4 of the 2027 study — verification and undo on every declaration, Action as a ledger
entry, the earned ladder keyed by action and scope, graduation on a receipt, automatic demotion
(`aughor/actions/authority.py`).

What these hold: a side-effect action is declared with a verification read and an undo, or
declared irreversible by name, else the declare door refuses it; the executor runs the verification
read after dispatch through the query door and books the execution as an Action entry citing what
it ran under; a read that cannot run is unavailable, never failed; a failed verification demotes the
(action, scope) as a ledger entry and withdraws its standing grants; L4 is granted only on a
graduation receipt the record earns — n verified executions, no failure, and an outcome inside
expectation on a decision that ran the action — so with no outcome recorded nothing graduates; an
irreversible action never passes L3; L5 is unreachable until missions exist; a policy grant is
minted only at L4, cites its receipt, and allows nothing once expired or spent.
"""
from __future__ import annotations

import uuid

import pytest

from aughor.actions import authority as A
from aughor.actions import grants
from aughor.actions.executor import execute_kinetic_action
from aughor.ontology.models import ActionParameter, KineticAction, Undo, Verification
from aughor.record import decisions as D


def _conn():
    return "conn-" + uuid.uuid4().hex[:6]


def _action(**kw) -> KineticAction:
    base = dict(id="refund", kind="side_effect",
                params=[ActionParameter(name="order_id", data_type="VARCHAR", required=True)],
                submission_criteria=[], side_effects=[], risk="high", reversibility="compensable",
                verification=Verification(sql="SELECT 1 FROM refunds WHERE order_id = '{order_id}'", expects="rows"),
                undo=Undo(action_id="reverse_refund", window_hours=72, params={"order_id": "{order_id}"}))
    base.update(kw)
    return KineticAction(**base)


def _recorder():
    calls: list = []

    def d(action, params, scope=""):
        calls.append((action.id, dict(params)))
        return {"dispatched": True}
    d.calls = calls
    return d


@pytest.fixture(autouse=True)
def _approval_off(monkeypatch):
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "0")


def _warehouse(rows_for: dict[str, list]):
    """A fake query door: the verification SQL's filled order id picks the rows it returns."""
    def run_sql_for(connection_id, **kw):
        def run_sql(sql):
            for key, rows in rows_for.items():
                if key in sql:
                    if rows == "error":
                        return ([], [], "relation refunds does not exist")
                    return (["one"], rows, None)
            return (["one"], [], None)
        return run_sql
    return run_sql_for


# ── the declaration ────────────────────────────────────────────────────────────────────────

def test_a_side_effect_action_is_declared_with_verification_and_undo_or_irreversible_by_name():
    assert A.declaration_problem(_action()) == ""
    assert "verification statement" in A.declaration_problem(_action(verification=None))
    assert "undo" in A.declaration_problem(_action(undo=None))
    assert A.declaration_problem(_action(undo=None, reversibility="irreversible")) == ""
    assert A.declaration_problem(KineticAction(id="note", kind="annotate", params=[])) == ""   # withdrawable: built in
    assert A.declaration_problem(KineticAction(id="q", kind="query", params=[], rule="SELECT 1")) == ""


def test_the_declare_door_refuses_an_incomplete_side_effect_action(monkeypatch):
    from fastapi import HTTPException
    from aughor.routers import ontology as ONT
    monkeypatch.setattr(ONT, "_object_types_problem", lambda declared, graph: "")
    monkeypatch.setattr(ONT, "_get_ontology_graph", lambda c, s: None)
    monkeypatch.setattr(ONT, "_resolve_schema", lambda c, s: None)
    monkeypatch.setattr("aughor.ontology.overrides.find_override", lambda *a, **k: None)
    monkeypatch.setattr("aughor.ontology.models.encrypt_action_secrets", lambda fields, prior: fields)
    body = ONT._KineticActionBody(kind="side_effect", params=[{"name": "order_id", "data_type": "VARCHAR"}],
                                  side_effects=[{"kind": "webhook", "config": {"url": "https://x.example/h"}}], risk="high")
    with pytest.raises(HTTPException) as exc:
        ONT.author_kinetic_action("refund", body, connection_id="c", schema_name=None)
    assert exc.value.status_code == 422 and "incomplete declaration" in exc.value.detail
    assert "verification statement" in exc.value.detail


# ── the verification read and the Action entry ─────────────────────────────────────────────

def test_the_executor_verifies_after_dispatch_and_books_the_action_entry(monkeypatch):
    conn = _conn()
    monkeypatch.setattr("aughor.db.measure.run_sql_for", _warehouse({"'8821'": [[1]]}))
    rec = _recorder()
    r = execute_kinetic_action(_action(), {"order_id": "8821"}, actor="user:ana", scope=conn, dispatch=rec, approved=True)
    assert r.ok and r.verification["status"] == "passed" and "1 row returned" in r.verification["why"]
    assert r.verification["sql"] == "SELECT 1 FROM refunds WHERE order_id = '8821'"
    assert rec.calls == [("refund", {"order_id": "8821"})]
    assert r.action_entry
    runs = A.executions("refund", conn)
    assert len(runs) == 1 and runs[0]["under"] == "human accept" and runs[0]["verification"]["status"] == "passed"
    assert runs[0]["undo"]["action_id"] == "reverse_refund" and runs[0]["params"] == {"order_id": "8821"}
    # a read that cannot run is unavailable — recorded, never a failed change, no demotion
    monkeypatch.setattr("aughor.db.measure.run_sql_for", _warehouse({"'9000'": "error"}))
    r2 = execute_kinetic_action(_action(), {"order_id": "9000"}, actor="user:ana", scope=conn, dispatch=_recorder(), approved=True)
    assert r2.ok and r2.verification["status"] == "unavailable" and "could not run" in r2.verification["why"] \
        or r2.verification["status"] == "unavailable" and "failed" in r2.verification["why"]
    assert A.record("refund", conn) == {**A.record("refund", conn), "executions": 2, "verified": 1,
                                         "failed_verifications": 0, "unverified": 1}
    assert A._latest(A.DEMOTION_KIND, "refund", conn) is None
    # an action with no verification declared is said so
    r3 = execute_kinetic_action(_action(verification=None), {"order_id": "1"}, actor="a", scope=conn, dispatch=_recorder(),
                                approved=True)
    assert r3.verification["status"] == "not_declared"


def test_a_failed_verification_demotes_and_withdraws_the_standing_grants(monkeypatch):
    conn = _conn()
    g = grants.mint_from_action(_action(), {"order_id": "8821"}, connection_id=conn, created_by="user:ana")
    assert grants.get_grant(g.id) is not None
    monkeypatch.setattr("aughor.db.measure.run_sql_for", _warehouse({"'8821'": []}))     # the change is not visible
    r = execute_kinetic_action(_action(), {"order_id": "8821"}, actor="user:ana", scope=conn, dispatch=_recorder(), approved=True)
    assert r.ok and r.verification["status"] == "failed" and "not visible" in r.verification["why"]
    demotion = A._latest(A.DEMOTION_KIND, "refund", conn)
    assert demotion is not None and demotion["grants_revoked"] == 1 and "verification failed" in demotion["why"]
    assert grants.get_grant(g.id) is None
    lv = A.level_for(_action(), conn)
    assert lv["level"] == 3 and "demoted on" in lv["why"] and lv["record"]["failed_verifications"] == 1


# ── the ladder ─────────────────────────────────────────────────────────────────────────────

def test_levels_from_the_record_and_the_ceilings(monkeypatch):
    conn = _conn()
    incomplete = A.level_for(_action(verification=None), conn)
    assert incomplete["level"] == 1 and incomplete["label"] == "recommend" and "verification statement" in incomplete["why"]
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "1")
    complete = A.level_for(_action(), conn)
    assert complete["level"] == 3 and complete["label"] == "execute with approval" and complete["ceiling"] == 4
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "0")
    off = A.level_for(_action(), conn)
    assert off["level"] == 3 and "kill switch" in off["why"] and "the operator's doing" in off["why"]
    irreversible = A.level_for(_action(undo=None, reversibility="irreversible"), conn)
    assert irreversible["ceiling"] == 3 and "irreversible: never above L3" in irreversible["notes"]
    assert any("L5 is unreachable" in n for n in irreversible["notes"])
    assert A.level_for(_action(), conn, ceiling=2)["level"] == 2                 # the ceiling a person set


def _run_n(action, conn, n, monkeypatch):
    monkeypatch.setattr("aughor.db.measure.run_sql_for", _warehouse({"'": [[1]]}))
    for i in range(n):
        r = execute_kinetic_action(action, {"order_id": str(1000 + i)}, actor="user:ana", scope=conn,
                                   dispatch=_recorder(), approved=True)
        assert r.verification["status"] == "passed"


def test_graduation_is_earned_on_the_record_and_refused_without_an_outcome(monkeypatch):
    conn = _conn()
    action = _action()
    check = A.evaluate_graduation(action, conn)
    assert not check["can_graduate"] and "0 of 5 approved executions" in check["reasons"][0]
    _run_n(action, conn, 5, monkeypatch)
    check = A.evaluate_graduation(action, conn)
    assert not check["can_graduate"] and check["reasons"] == [
        "no outcome inside expectation on a decision that ran this action — phase 3's exit, the condition §4.8's amendment set"]
    with pytest.raises(ValueError, match="not earned"):
        A.graduate(action, conn, by="user:ana")
    with pytest.raises(ValueError, match="needs L4"):
        A.widen(action, conn, target_value="8821", by="user:ana")
    # an outcome inside expectation on a decision that ran this action — phase 3's exit — unlocks it
    did = D.book_decision(D.Decision(question="refund order 8821?", chosen="approve", decided_by="user:ana",
                                     actions=["refund"], connection_id=conn,
                                     source=D.Source(kind="approval", ref=uuid.uuid4().hex[:8])),
                          expectation=D.Expectation(metric="refund_rate", direction="down", low=-3, high=-1, unit="%"))
    D.book_outcome(D.Outcome(of=did, measured_on="2026-11-20", actual=9.8, baseline=10.0, verdict="as_expected",
                             against_expectation="inside"))
    check = A.evaluate_graduation(action, conn)
    assert check["can_graduate"] and check["record"]["outcomes_inside_expectation"] == 1
    receipt = A.graduate(action, conn, by="user:ana")
    assert receipt["level"] == 4 and receipt["id"]
    lv = A.level_for(action, conn)
    assert lv["level"] == 4 and lv["label"] == "execute within policy" and lv["graduation"] == receipt["id"]
    # a policy grant now cites the receipt, is bound and capped, and allows nothing once spent
    g = A.widen(action, conn, target_value="8821", by="user:ana", expires_days=30, max_uses=1)
    assert g.graduation_receipt == receipt["id"] and g.expires_at and g.max_uses == 1 and g.owner_kind == "authority"
    assert grants.matching_grant("refund", {"order_id": "8821"}, connection_id=conn).id == g.id
    grants.bump_use(g.id)
    assert grants.matching_grant("refund", {"order_id": "8821"}, connection_id=conn) is None
    assert grants.get_grant(g.id).spent() == "its 1 uses are spent"
    # an irreversible action never graduates, whatever its record
    irreversible = _action(undo=None, reversibility="irreversible")
    _run_n(irreversible, conn, 5, monkeypatch)
    assert "an irreversible action never passes L3" in A.evaluate_graduation(irreversible, conn)["reasons"]
    # a later demotion takes L4 away until a new receipt
    A.demote("refund", conn, why="an unexplained miss on the mission report", by="user:bo")
    after = A.level_for(action, conn)
    assert after["level"] == 3 and "demoted on" in after["why"]


def test_the_authority_door_lists_the_table_and_books_receipts(monkeypatch):
    from fastapi import HTTPException
    from aughor.routers import authority as R
    conn = _conn()
    actions = {"refund": _action(), "note": KineticAction(id="note", kind="annotate", params=[])}
    monkeypatch.setattr(R, "_actions", lambda c, s: actions)
    table = R.authority_table(connection_id=conn)
    rows = {r["action_id"]: r for r in table["actions"]}
    assert rows["refund"]["level"] == 3 and rows["refund"]["verification_declared"] and rows["refund"]["undo_declared"]
    assert rows["note"]["reversibility"] == "undeclared" and rows["refund"]["graduation_check"]
    with pytest.raises(HTTPException) as exc:
        R.authority_graduate("refund", R.GraduateBody(connection_id=conn), principal=None)
    assert exc.value.status_code == 422 and "not earned" in exc.value.detail
    entry = R.authority_demote("refund", R.DemoteBody(connection_id=conn, why="a drill"), principal=None)
    assert entry["to_level"] == 3 and A._latest(A.DEMOTION_KIND, "refund", conn)["by"] == "unidentified"
    with pytest.raises(HTTPException):
        R.authority_demote("refund", R.DemoteBody(connection_id=conn, why="  "), principal=None)
    rec = R.authority_record("refund", connection_id=conn)
    assert rec["demotion"] and rec["executions"] == []
