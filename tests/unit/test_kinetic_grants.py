"""Wave A4 — target-bound standing grants and their executor consultation.

The J2 invariants: a grant is bound to ONE exact target value (a different value still needs
approval), eligible only for a single-parameter action, cited on every auto-allowed run, owned by
its minter, and — the safety line — it bypasses APPROVAL only, never the submission criteria.

The executor runs unmocked so the real approval pipeline (govern.guard, 428, audit) is exercised;
``AUGHOR_ACTION_APPROVAL`` is forced on per test so HIGH-risk actions actually gate.
"""
from __future__ import annotations

import pytest

from aughor.kinetic import grants
from aughor.kinetic.executor import execute_kinetic_action
from aughor.ontology.models import ActionParameter, KineticAction, SubmissionCriterion


def _single(**kw) -> KineticAction:
    base = dict(id="refund", kind="side_effect",
                params=[ActionParameter(name="order_id", data_type="VARCHAR", required=True)],
                submission_criteria=[], side_effects=[], risk="high")
    base.update(kw)
    return KineticAction(**base)


def _multi() -> KineticAction:
    return KineticAction(id="transfer", kind="side_effect",
                         params=[ActionParameter(name="frm", data_type="VARCHAR"),
                                 ActionParameter(name="to", data_type="VARCHAR")],
                         side_effects=[], risk="high")


@pytest.fixture
def proposals_on(monkeypatch):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled",
                        lambda n: n == "automations.proposals")


@pytest.fixture
def approval_on(monkeypatch):
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "1")


# ── eligibility ──────────────────────────────────────────────────────────────────

def test_single_target_arg_detection():
    assert grants.single_target_arg(_single()) == "order_id"
    assert grants.single_target_arg(_multi()) is None
    assert grants.single_target_arg(KineticAction(id="x", kind="side_effect", params=[])) is None


def test_mint_refuses_a_multi_param_action():
    assert grants.mint_from_action(_multi(), {"frm": "a", "to": "b"}, connection_id="c") is None


def test_mint_binds_the_single_target_value():
    g = grants.mint_from_action(_single(), {"order_id": "8821"}, connection_id="c",
                                owner_kind="automation", owner_id="auto-1", created_by="me")
    assert g is not None
    assert (g.target_arg, g.target_value) == ("order_id", "8821")
    assert (g.owner_kind, g.owner_id) == ("automation", "auto-1")


def test_mint_is_idempotent_on_the_binding():
    a = grants.mint_from_action(_single(), {"order_id": "8821"}, connection_id="c")
    b = grants.mint_from_action(_single(), {"order_id": "8821"}, connection_id="c")
    assert a.id == b.id
    assert len(grants.list_grants("c")) == 1


# ── matching: exact string equality ───────────────────────────────────────────────

def test_matching_grant_is_exact_value_equality(proposals_on):
    grants.mint_from_action(_single(), {"order_id": "8821"}, connection_id="c-match")
    assert grants.matching_grant("refund", {"order_id": "8821"}, connection_id="c-match") is not None
    assert grants.matching_grant("refund", {"order_id": "8822"}, connection_id="c-match") is None
    assert grants.matching_grant("refund", {"order_id": "8821"}, connection_id="other") is None


def test_standing_grant_id_is_empty_when_the_flag_is_off(monkeypatch):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda n: False)
    grants.mint_from_action(_single(), {"order_id": "8821"}, connection_id="c-off")
    assert grants.standing_grant_id(_single(), {"order_id": "8821"}, "c-off") == ""


def test_standing_grant_id_bumps_use(proposals_on):
    grants.mint_from_action(_single(), {"order_id": "8821"}, connection_id="c-bump")
    gid = grants.standing_grant_id(_single(), {"order_id": "8821"}, "c-bump")
    assert gid
    assert grants.get_grant(gid).use_count == 1


# ── the executor consultation (the wire) ──────────────────────────────────────────

def test_a_high_risk_action_needs_approval_without_a_grant(proposals_on, approval_on):
    """Baseline: with approval on and no grant, a HIGH action is blocked (428/approval_required)."""
    r = execute_kinetic_action(_single(), {"order_id": "8821"}, scope="c-need",
                               dispatch=lambda a, p, s="": {"ok": True})
    assert r.status == "approval_required"


def test_a_matching_grant_auto_allows_and_cites_itself(proposals_on, approval_on):
    """The J2 gate: a target-bound grant lets an unattended HIGH-risk run through, and the run
    records WHICH grant authorized it."""
    g = grants.mint_from_action(_single(), {"order_id": "8821"}, connection_id="c-auto")
    r = execute_kinetic_action(_single(), {"order_id": "8821"}, scope="c-auto",
                               dispatch=lambda a, p, s="": {"ok": True})
    assert r.status == "executed"
    assert r.granted_by == g.id


def test_a_numeric_grant_minted_from_coerced_params_actually_matches(proposals_on, approval_on):
    """Regression (live proof caught it): the grant's bound value must be the COERCED form. A
    NUMERIC action accepted with 500 coerces to 500.0; a grant bound as raw '500' would never match
    the executor's coerced '500.0'. Minting from coerced params is what makes the grant it just
    created usable. (VARCHAR tests miss this because coercion is identity there.)"""
    from aughor.kinetic.executor import coerce_params
    action = KineticAction(
        id="refund_eur", kind="side_effect",
        params=[ActionParameter(name="amount_eur", data_type="NUMERIC", required=True)],
        submission_criteria=[], side_effects=[], risk="high")

    # Mint the way accept_proposal does — from coerced params.
    coerced = coerce_params(action, {"amount_eur": 500})     # -> {"amount_eur": 500.0}
    g = grants.mint_from_action(action, coerced, connection_id="c-num")
    assert g.target_value == "500.0"

    # A direct execute with the raw int 500 coerces to 500.0 inside the executor → matches.
    r = execute_kinetic_action(action, {"amount_eur": 500}, scope="c-num",
                               dispatch=lambda a, p, s="": {"ok": True})
    assert r.status == "executed" and r.granted_by == g.id


def test_a_grant_for_a_different_target_does_not_help(proposals_on, approval_on):
    grants.mint_from_action(_single(), {"order_id": "8821"}, connection_id="c-diff")
    r = execute_kinetic_action(_single(), {"order_id": "9999"}, scope="c-diff",
                               dispatch=lambda a, p, s="": {"ok": True})
    assert r.status == "approval_required"


def test_a_grant_bypasses_approval_but_not_criteria(proposals_on, approval_on):
    """The safety line: a granted target whose value fails a criterion is STILL refused, with the
    authored message, and never dispatches."""
    msg = "Only order 8821 is pre-cleared."
    action = _single(submission_criteria=[SubmissionCriterion(expr="order_id == '8821'", message=msg)])
    # Grant the value 9999 — but the criterion only passes 8821.
    grants.mint_from_action(action, {"order_id": "9999"}, connection_id="c-safe")
    calls: list = []
    r = execute_kinetic_action(action, {"order_id": "9999"}, scope="c-safe",
                               dispatch=lambda a, p, s="": calls.append(1))
    assert r.status == "criterion_failed"
    assert r.message == msg
    assert calls == []


def test_the_executor_is_byte_identical_when_the_flag_is_off(monkeypatch, approval_on):
    """No grant is consulted when proposals are off — a HIGH action gates exactly as pre-A4."""
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda n: False)
    grants.mint_from_action(_single(), {"order_id": "8821"}, connection_id="c-flagoff")
    r = execute_kinetic_action(_single(), {"order_id": "8821"}, scope="c-flagoff",
                               dispatch=lambda a, p, s="": {"ok": True})
    assert r.status == "approval_required"       # the grant existed but was never consulted


# ── revoke + purge ────────────────────────────────────────────────────────────────

def test_revoke(proposals_on):
    g = grants.mint_from_action(_single(), {"order_id": "8821"}, connection_id="c-rev")
    assert grants.revoke_grant(g.id) is True
    assert grants.matching_grant("refund", {"order_id": "8821"}, connection_id="c-rev") is None
    assert grants.revoke_grant(g.id) is False


def test_purge_owner_and_connection():
    grants.mint_from_action(_single(), {"order_id": "1"}, connection_id="c-purge",
                            owner_kind="automation", owner_id="auto-x")
    grants.mint_from_action(_single(), {"order_id": "2"}, connection_id="c-purge")
    assert grants.purge_owner("automation", "auto-x") == 1
    assert grants.purge_connection("c-purge") == 1
    assert grants.list_grants("c-purge") == []
