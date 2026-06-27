"""Intake injection hook — a pack steering a run (flag-gated, 2026-06-27).

injection_for_question selects an active pack, grounds it on the connection, and returns the
steering payload; render_injection turns it into a planner prompt block. Off by default.
See aughor/packs/intake.py.
"""
from pathlib import Path

import pytest

import aughor.packs.intake as intake
from aughor.packs import load_pack

REPO = Path(__file__).resolve().parents[2]

TABLE_COLS = {
    "dim_customers": ["customer_id", "signup_ts"],
    "fct_orders": ["order_id", "order_ts", "customer_id"],
}
Q = "How is retention trending by cohort?"


def _active_sample():
    pack = load_pack(REPO / "packs" / "customer-analytics")
    return pack.model_copy(update={"manifest": pack.manifest.model_copy(update={"status": "active"})})


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setattr(intake, "flag_enabled", lambda name: True)


@pytest.fixture
def flag_off(monkeypatch):
    monkeypatch.setattr(intake, "flag_enabled", lambda name: False)


def test_flag_off_never_steers(flag_off):
    assert intake.injection_for_question(Q, "c1", TABLE_COLS, packs=[_active_sample()]) is None


def test_steers_when_active_pack_matches_and_grounds(flag_on):
    inj = intake.injection_for_question(Q, "c1", TABLE_COLS, business_model="transactional",
                                        packs=[_active_sample()])
    assert inj is not None and inj.pack_id == "customer-analytics"
    assert inj.default_temporal_grain == "cohort"
    block = intake.render_injection(inj)
    assert "SPECIALIST CONTEXT" in block
    assert "Cohort Retention" in block
    assert "dim_customers.signup_ts" in block   # recipe grain grounded to a real column


def test_no_steer_when_pack_cannot_ground(flag_on):
    # Missing the entity/event tables → not fully bound → don't steer.
    inj = intake.injection_for_question(Q, "c1", {"unrelated": ["x", "y"]}, packs=[_active_sample()])
    assert inj is None


def test_no_steer_for_off_topic_question(flag_on):
    inj = intake.injection_for_question("what is the weather", "c1", TABLE_COLS, packs=[_active_sample()])
    assert inj is None


def test_draft_pack_does_not_steer(flag_on):
    draft = load_pack(REPO / "packs" / "customer-analytics")  # status: draft
    assert intake.injection_for_question(Q, "c1", TABLE_COLS, packs=[draft]) is None
