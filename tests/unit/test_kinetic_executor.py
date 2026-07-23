"""Wave K2 — the one governed executor for declared KineticActions.

Locks the pipeline contract: coerce params → evaluate submission criteria → graduated-approval
gate → dispatch → audit, with NO side effect on any rejection, the authored criterion message
returned verbatim, criteria short-circuiting BEFORE approval, and a declared risk tier respected
(a LOW action is not treated as HIGH just because it is not in the static registry). Hermetic: the
kernel ledger is the conftest temp DB; dispatch is injected or its httpx/SSRF calls are faked.
"""
from __future__ import annotations

import pytest

import aughor.govern.actions as govern
from aughor.kinetic.executor import (
    CriterionError,
    ParamError,
    coerce_params,
    evaluate_predicate,
    execute_kinetic_action,
)
from aughor.ontology.models import ActionParameter, KineticAction, SideEffect, SubmissionCriterion

MSG = "Refunds over €10,000 need finance sign-off — route to the approvals queue instead."


def _action(**kw) -> KineticAction:
    base = dict(
        id="refund", kind="side_effect",
        params=[ActionParameter(name="amount", data_type="NUMERIC", required=True)],
        submission_criteria=[SubmissionCriterion(expr="amount <= 10000", message=MSG)],
        side_effects=[SideEffect(kind="webhook", config={"url": "https://hooks.example.com/x"})],
        risk="high",
    )
    base.update(kw)
    return KineticAction(**base)


def _recorder():
    calls: list = []

    def d(action, params):
        calls.append((action.id, dict(params)))
        return {"dispatched": True}

    d.calls = calls
    return d


@pytest.fixture(autouse=True)
def _approval_off_by_default(monkeypatch):
    monkeypatch.delenv("AUGHOR_ACTION_APPROVAL", raising=False)


# ── the safe submission-criterion evaluator ──────────────────────────────────────

def test_predicate_comparisons_and_logic():
    assert evaluate_predicate("amount <= 10000", {"amount": 500}) is True
    assert evaluate_predicate("amount <= 10000", {"amount": 20000}) is False
    assert evaluate_predicate("region in ['EU','UK'] and amount <= 100",
                              {"region": "EU", "amount": 50}) is True
    assert evaluate_predicate("not (amount > 10)", {"amount": 5}) is True


@pytest.mark.parametrize("expr", [
    "__import__('os').system('boom')",   # call
    "amount.__class__",                  # attribute
    "open('/etc/passwd')",               # call
    "[x for x in y]",                    # comprehension
    "amount.bit_length()",               # method call
    "lambda: 1",                         # lambda
])
def test_predicate_rejects_code_execution(expr):
    with pytest.raises(CriterionError):
        evaluate_predicate(expr, {"amount": 1, "y": [1], "region": "EU"})


def test_predicate_rejects_unknown_parameter():
    with pytest.raises(CriterionError):
        evaluate_predicate("mystery > 1", {"amount": 1})


# ── parameter coercion ───────────────────────────────────────────────────────────

def test_coerce_casts_declared_types():
    a = _action(params=[ActionParameter(name="n", data_type="INTEGER"),
                        ActionParameter(name="f", data_type="NUMERIC"),
                        ActionParameter(name="s", data_type="VARCHAR")],
                submission_criteria=[])
    assert coerce_params(a, {"n": "5", "f": "1.5", "s": 7}) == {"n": 5, "f": 1.5, "s": "7"}


def test_coerce_missing_required_raises():
    a = _action(params=[ActionParameter(name="x", data_type="INTEGER", required=True)],
                submission_criteria=[])
    with pytest.raises(ParamError):
        coerce_params(a, {})


def test_coerce_fills_default_and_ignores_extras():
    a = _action(params=[ActionParameter(name="x", data_type="INTEGER", required=False,
                                        default_value="9")],
                submission_criteria=[])
    assert coerce_params(a, {"junk": "z"}) == {"x": 9}


def test_coerce_uncastable_raises():
    a = _action(params=[ActionParameter(name="x", data_type="INTEGER")], submission_criteria=[])
    with pytest.raises(ParamError):
        coerce_params(a, {"x": "abc"})


# ── the governance pipeline (the decision gate) ──────────────────────────────────

def test_criterion_pass_dispatches_exactly_once():
    d = _recorder()
    r = execute_kinetic_action(_action(), {"amount": 500}, dispatch=d)
    assert r.ok and r.status == "executed"
    assert d.calls == [("refund", {"amount": 500.0})]   # coerced, dispatched once


def test_criterion_fail_returns_authored_message_and_never_dispatches():
    d = _recorder()
    r = execute_kinetic_action(_action(), {"amount": 20000}, dispatch=d)
    assert not r.ok and r.status == "criterion_failed"
    assert r.message == MSG          # authored, byte-for-byte
    assert d.calls == []             # zero side effects on a rejection


def test_criterion_short_circuits_before_the_approval_gate(monkeypatch):
    # Approval ON + HIGH + not allowlisted would 428 — but a criterion failure must win first.
    # If it returns criterion_failed (not approval_required), criteria ran before the guard.
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "1")
    d = _recorder()
    r = execute_kinetic_action(_action(), {"amount": 20000}, scope="conn-crit", dispatch=d)
    assert r.status == "criterion_failed" and d.calls == []


def test_invalid_params_never_dispatches():
    d = _recorder()
    r = execute_kinetic_action(_action(), {}, dispatch=d)   # missing required 'amount'
    assert r.status == "invalid_params" and d.calls == []


def test_approval_off_high_risk_auto_executes(monkeypatch):
    # Governance disabled ⇒ guard is a no-op ⇒ byte-for-byte the pre-Wave-K posture.
    monkeypatch.delenv("AUGHOR_ACTION_APPROVAL", raising=False)
    d = _recorder()
    r = execute_kinetic_action(_action(), {"amount": 500}, scope="s", dispatch=d)
    assert r.ok and len(d.calls) == 1


def test_high_risk_blocks_then_executes_once_after_approval(monkeypatch):
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "1")
    d = _recorder()
    r1 = execute_kinetic_action(_action(), {"amount": 500}, scope="conn-approve", dispatch=d)
    assert r1.status == "approval_required" and r1.detail.get("risk") == "high"
    assert d.calls == []                                    # blocked → no side effect

    govern.allow("kinetic.refund", "conn-approve")          # POST /approvals/allow equivalent

    r2 = execute_kinetic_action(_action(), {"amount": 500}, scope="conn-approve", dispatch=d)
    assert r2.ok and r2.status == "executed" and len(d.calls) == 1   # exactly once


def test_low_risk_declared_action_is_not_treated_as_high(monkeypatch):
    # The risk-override fix: a declared LOW action is unregistered in govern._RISK, which would
    # classify it HIGH by default — but the executor passes the DECLARED risk, so it auto-runs.
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "1")
    d = _recorder()
    r = execute_kinetic_action(_action(risk="low"), {"amount": 500}, scope="conn-low", dispatch=d)
    assert r.ok and r.status == "executed" and len(d.calls) == 1


# ── the default dispatcher: webhook is wired; the rest are clean seams ────────────

def test_default_webhook_dispatch_posts(monkeypatch):
    monkeypatch.setattr("aughor.util.url_guard.is_safe_webhook_url", lambda u: True)
    import httpx

    class _Resp:
        status_code = 200
        is_success = True

    seen = {}
    monkeypatch.setattr(httpx, "post", lambda url, **k: seen.update(url=url, **k) or _Resp())
    r = execute_kinetic_action(_action(), {"amount": 500})   # default_dispatch
    assert r.ok and r.outcome["side_effects"][0]["http_status"] == 200
    assert seen["url"] == "https://hooks.example.com/x"
    assert seen["json"]["params"] == {"amount": 500.0} and "url" not in seen["json"]["config"]


def test_default_webhook_ssrf_is_blocked(monkeypatch):
    monkeypatch.setattr("aughor.util.url_guard.is_safe_webhook_url", lambda u: False)
    a = _action(side_effects=[SideEffect(kind="webhook", config={"url": "http://169.254.169.254/"})])
    r = execute_kinetic_action(a, {"amount": 500})
    assert r.status == "dispatch_error" and "SSRF" in r.message


def test_annotate_kind_is_a_seam_to_k3():
    a = _action(kind="annotate", side_effects=[], submission_criteria=[])
    r = execute_kinetic_action(a, {"amount": 1})
    assert r.status == "dispatch_error" and "K3" in r.message


def test_trigger_investigation_is_a_seam_to_k4():
    a = _action(side_effects=[SideEffect(kind="trigger_investigation")], submission_criteria=[])
    r = execute_kinetic_action(a, {"amount": 1})
    assert r.status == "dispatch_error" and "K4" in r.message


# ── the HTTP surface ─────────────────────────────────────────────────────────────

def _graph_with(action):
    from aughor.ontology.models import OntologyGraph
    g = OntologyGraph(connection_id="c", schema_name="s", schema_fingerprint="fp")
    g.kinetic_actions[action.id] = action
    return g


def _flag_on(monkeypatch):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda n: n == "kinetic.actions")


def test_router_404_when_flag_off(monkeypatch):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda n: False)
    from fastapi import HTTPException

    from aughor.routers import kinetic as K
    with pytest.raises(HTTPException) as e:
        K.execute_action("refund", K.ExecuteRequest(params={"amount": 1}),
                         connection_id="c", schema_name=None)
    assert e.value.status_code == 404


def test_router_criterion_fail_is_422_with_authored_message(monkeypatch):
    _flag_on(monkeypatch)
    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology",
                        lambda *a, **k: _graph_with(_action()))
    from fastapi import HTTPException

    from aughor.routers import kinetic as K
    with pytest.raises(HTTPException) as e:
        K.execute_action("refund", K.ExecuteRequest(params={"amount": 20000}),
                         connection_id="c", schema_name=None)
    assert e.value.status_code == 422 and e.value.detail["message"] == MSG


def test_router_approval_required_is_428(monkeypatch):
    _flag_on(monkeypatch)
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "1")
    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology",
                        lambda *a, **k: _graph_with(_action()))
    from fastapi import HTTPException

    from aughor.routers import kinetic as K
    with pytest.raises(HTTPException) as e:
        K.execute_action("refund", K.ExecuteRequest(params={"amount": 500}),
                         connection_id="c", schema_name=None)
    assert e.value.status_code == 428


def test_router_success_is_200(monkeypatch):
    _flag_on(monkeypatch)
    a = _action(side_effects=[SideEffect(kind="webhook", config={"url": "https://ok.example.com"})])
    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology", lambda *x, **k: _graph_with(a))
    monkeypatch.setattr("aughor.util.url_guard.is_safe_webhook_url", lambda u: True)
    import httpx

    class _Resp:
        status_code = 200
        is_success = True

    monkeypatch.setattr(httpx, "post", lambda url, **k: _Resp())
    from aughor.routers import kinetic as K
    out = K.execute_action("refund", K.ExecuteRequest(params={"amount": 500}),
                           connection_id="c", schema_name=None)
    assert out["status"] == "executed"


def test_router_unknown_action_is_404(monkeypatch):
    _flag_on(monkeypatch)
    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology",
                        lambda *a, **k: _graph_with(_action()))
    from fastapi import HTTPException

    from aughor.routers import kinetic as K
    with pytest.raises(HTTPException) as e:
        K.execute_action("nope", K.ExecuteRequest(), connection_id="c", schema_name=None)
    assert e.value.status_code == 404
