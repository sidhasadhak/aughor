"""Bets 1/3/5/6/7 logic — flywheel, org, standing agents, marketplace, instruments (2026-06-27).

Pure cores; the engine/connection-dependent wiring is layered on later. See aughor/packs/.
"""
from aughor.packs import (
    distill_deltas, resolve_metric_definition, MetricClaim, route_escalation,
    Mandate, evaluate_mandate, import_readiness, Instrument, can_invoke,
)
from aughor.agent.state import VerificationManifest, VerificationCheck, DataQualityNote


def _verified_manifest():
    return VerificationManifest(checks=[], coverage=1.0, earned_confidence=0.9,
                                confidence_band="high", data_trust=1.0, signals=[])


def _unverified_manifest():
    return VerificationManifest(checks=[], coverage=0.5, earned_confidence=0.3,
                                confidence_band="low", data_trust=0.5, signals=[])


# ── Bet 1: flywheel only compounds verified runs ──────────────────────────────

def test_flywheel_compounds_verified_run_into_caveats():
    dq = [DataQualityNote(table="tickets", column="days_to_departure",
                          issue="negative values present", impact="x", recommended_fix="profile it")]
    res = distill_deltas("p", _verified_manifest(), data_quality_notes=dq, source_run="run1")
    assert res.compounded
    assert any(d.kind == "caveat" and d.target == "tickets.days_to_departure" for d in res.deltas)


def test_flywheel_quarantines_unverified_run():
    dq = [DataQualityNote(table="t", column="c", issue="x", impact="y", recommended_fix="z")]
    res = distill_deltas("p", _unverified_manifest(), data_quality_notes=dq)
    assert not res.compounded and res.deltas == [] and res.skipped_reason


def test_flywheel_turns_reject_verdict_into_diagnostic():
    res = distill_deltas("p", _verified_manifest(), human_verdict="reject",
                         verdict_note="this is a billing artifact, not churn")
    assert any(d.kind == "diagnostic" for d in res.deltas)


# ── Bet 3: governed canonical wins; conflicts surfaced ────────────────────────

def test_governed_metric_wins_over_pack_definitions():
    claims = [MetricClaim("ca", "SUM(net)"), MetricClaim("finance", "SUM(gross)")]
    r = resolve_metric_definition("revenue", claims, governed_definition="SUM(governed_net)")
    assert r.winner == "governed" and r.conflict and r.definition == "SUM(governed_net)"


def test_conflict_without_governance_is_surfaced():
    claims = [MetricClaim("a", "def1"), MetricClaim("b", "def2")]
    r = resolve_metric_definition("x", claims)
    assert r.conflict and "CONFLICT" in r.note


def test_escalation_routes_to_domain():
    e = route_escalation("customer-analytics", "finance", "churn spike is a billing artifact")
    assert e.to_domain == "finance"


# ── Bet 5: mandate breach decisions ───────────────────────────────────────────

def test_mandate_breach_triggers_investigate_and_escalate():
    m = Mandate(metric="NRR", operator="gte", threshold=1.10)
    out = evaluate_mandate(m, 0.95)
    assert out.breached and out.should_investigate and out.should_escalate


def test_mandate_within_bounds_is_ok():
    m = Mandate(metric="NRR", operator="gte", threshold=1.10)
    assert evaluate_mandate(m, 1.20).severity == "ok"


def test_mandate_lte_breach():
    m = Mandate(metric="CAC", operator="lte", threshold=100.0)
    assert evaluate_mandate(m, 130.0).breached


# ── Bet 6: imported pack is inert until it re-grounds locally ──────────────────

def test_import_ready_only_when_all_local_checks_pass():
    assert import_readiness(True, True, True).ready
    r = import_readiness(True, False, True)
    assert not r.ready and any("binds" in b for b in r.blockers)


# ── Bet 7: instruments are capability-gated ───────────────────────────────────

def test_instrument_requires_granted_capability():
    surv = Instrument(name="Survival", method="kaplan_meier", required_capability="stats.survival")
    assert can_invoke(surv, {"stats.survival"})
    assert not can_invoke(surv, {"sql.read"})
