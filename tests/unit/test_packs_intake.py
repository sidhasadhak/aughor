"""Intake injection hook — a pack steering a run (flag-gated, pinned-binding-gated, 2026-06-27).

Steering requires the flag ON, an active pack that owns the question, AND a human-confirmed
PINNED binding on the connection (auto-proposals are deploy-UI only). See aughor/packs/intake.py.
"""
from pathlib import Path

import pytest

import aughor.packs.intake as intake
import aughor.packs.bindings as bnd
from aughor.packs import load_pack, save_binding
from aughor.org.context import using_org

REPO = Path(__file__).resolve().parents[2]
Q = "How is retention trending by cohort?"

BINDING = {
    "customer": {"table": "customers", "column": "customer_unique_id"},
    "event": {"table": "orders", "column": "order_purchase_ts"},
    "cohort_anchor": {"table": "customers", "column": "signup_date"},
    "active_definition": {"value": "purchased_in_window"},
}


def _active_sample():
    pack = load_pack(REPO / "packs" / "customer-analytics")
    return pack.model_copy(update={"manifest": pack.manifest.model_copy(update={"status": "active"})})


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(intake, "flag_enabled", lambda name: True)
    monkeypatch.setattr(bnd, "_DB_PATH", tmp_path / "pack_bindings.db")
    return tmp_path


def test_steers_when_active_pack_matches_and_pinned(env):
    with using_org("default"):
        save_binding("customer-analytics", "workspace", BINDING, verified=True)
        inj = intake.injection_for_question(Q, "workspace", business_model="transactional",
                                            packs=[_active_sample()])
    assert inj is not None and inj.pack_id == "customer-analytics"
    block = intake.render_injection(inj)
    assert "SPECIALIST CONTEXT" in block and "Cohort Retention" in block
    assert "customers.signup_date" in block        # recipe grain grounded to the pinned column


def test_no_steer_without_pinned_binding(env):
    with using_org("default"):
        inj = intake.injection_for_question(Q, "workspace", packs=[_active_sample()])
    assert inj is None                              # active + matches, but not deployed → no steer


def test_flag_off_never_steers(env, monkeypatch):
    monkeypatch.setattr(intake, "flag_enabled", lambda name: False)
    with using_org("default"):
        save_binding("customer-analytics", "workspace", BINDING, verified=True)
        assert intake.injection_for_question(Q, "workspace", packs=[_active_sample()]) is None


def test_off_topic_question_does_not_steer(env):
    with using_org("default"):
        save_binding("customer-analytics", "workspace", BINDING, verified=True)
        assert intake.injection_for_question("what is the weather", "workspace",
                                             packs=[_active_sample()]) is None


def test_draft_pack_does_not_steer(env):
    draft = load_pack(REPO / "packs" / "customer-analytics")   # status: draft
    with using_org("default"):
        save_binding("customer-analytics", "workspace", BINDING, verified=True)
        assert intake.injection_for_question(Q, "workspace", packs=[draft]) is None
