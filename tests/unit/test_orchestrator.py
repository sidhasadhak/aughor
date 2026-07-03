"""Phase-2 structural — the Orchestrator declares the deterministic phase plan and
returns a typed cross-phase ContradictionReport. These tests pin (a) the plan mirrors
the routers, (b) the typed report's prompt section is byte-identical to the legacy
string the synthesizer received, and (c) everything is fail-open. Pure + hermetic."""
from __future__ import annotations


from aughor.agent.orchestrator import (
    plan_phases, reconcile, detect_contradictions,
    ContradictionReport,
)


# ── plan_phases — mirrors route_after_intake/baseline/decompose/dimensional ──────

def test_cross_sectional_plan_skips_the_temporal_battery():
    plan = plan_phases(question="which region has the lowest margin?",
                       cross_sectional=True, dimension_ask=True, behavioral=False)
    assert plan.question_kind == "cross_sectional"
    assert plan.planned_ids == ["intake", "cross_section", "synthesis"]
    # no baseline/decomposition/dimensional in a cross-sectional run
    assert "baseline" not in plan.planned_ids


def test_temporal_simple_question_gates_decompose_and_dimensional():
    # "why did revenue drop" — no dimension named, not behavioural.
    plan = plan_phases(question="why did revenue drop last month?",
                       cross_sectional=False, dimension_ask=False, behavioral=False)
    assert plan.question_kind == "temporal"
    steps = {s.phase_id: s.disposition for s in plan.steps}
    assert steps["intake"] == "planned" and steps["baseline"] == "planned"
    assert steps["decomposition"] == "conditional"   # runs unless within normal variance
    assert steps["dimensional"] == "conditional"
    assert steps["behavioral"] == "gated_off"        # no behavioural signal
    assert steps["synthesis"] == "planned"
    # behavioral is gated off → not in the planned set
    assert "behavioral" not in plan.planned_ids


def test_dimension_question_promotes_decompose_and_dimensional_to_planned():
    plan = plan_phases(question="which channel drove the revenue drop?",
                       cross_sectional=False, dimension_ask=True, behavioral=False)
    steps = {s.phase_id: s.disposition for s in plan.steps}
    assert steps["decomposition"] == "planned"
    assert steps["dimensional"] == "planned"


def test_behavioral_question_promotes_behavioral_to_planned():
    plan = plan_phases(question="why are customers churning?",
                       cross_sectional=False, dimension_ask=False, behavioral=True)
    steps = {s.phase_id: s.disposition for s in plan.steps}
    assert steps["behavioral"] == "planned"
    assert "behavioral" in plan.planned_ids


def test_plan_summary_is_a_one_line_declaration():
    plan = plan_phases(question="why did revenue drop?",
                       cross_sectional=False, dimension_ask=False, behavioral=False)
    s = plan.summary()
    assert s.startswith("[temporal]") and "intake → baseline" in s
    assert "skipping behavioral" in s   # gated-off phases are named


# ── reconcile — planned vs actual ────────────────────────────────────────────────

def test_reconcile_reports_skipped_and_unplanned():
    rec = reconcile(["intake", "baseline", "decomposition", "dimensional", "synthesis"],
                    ["intake", "baseline", "synthesis"])  # early-stopped after baseline
    assert rec["skipped"] == ["decomposition", "dimensional"]
    assert rec["unplanned"] == []
    assert rec["actual"] == ["baseline", "intake", "synthesis"]


def test_reconcile_handles_empty_plan():
    rec = reconcile([], ["intake", "baseline"])
    assert rec["planned"] == [] and rec["unplanned"] == ["baseline", "intake"]


# ── detect_contradictions — typed + byte-stable prompt section ───────────────────

def _legacy_prompt_section(contradictions: list) -> str:
    """The exact string the pre-Orchestrator _detect_phase_contradictions built."""
    if not contradictions:
        return ""
    lines = [
        "\n⚠ CROSS-PHASE CONTRADICTIONS DETECTED — address each explicitly in your report "
        "(surface them in the risks or data quality notes; do NOT silently average them out):"
    ]
    for i, c in enumerate(contradictions, 1):
        lines.append(f"  {i}. {c}")
    lines.append("")
    return "\n".join(lines)


def test_significance_flip_is_detected_and_typed():
    phases = [
        {"phase_name": "Baseline", "summary": "Revenue shows a significant anomalous drop (z=-2.4)."},
        {"phase_name": "Dimensional", "summary": "All segments are within normal variance."},
    ]
    report = detect_contradictions(phases)
    assert isinstance(report, ContradictionReport)
    assert report.has_contradictions and report.severity == "high"
    assert report.items[0].kind == "significance_flip"
    assert set(report.items[0].phases) == {"Baseline", "Dimensional"}


def test_direction_flip_is_detected():
    # NB: detection is byte-faithful to the legacy scanner, whose alternatives carry a
    # trailing \b — so it matches whole words ("grew"/"fell") but not stems
    # ("increased"). Preserving that exactly is the point of this structural refactor;
    # widening the stems is tracked separately as a detection-quality fix.
    phases = [
        {"phase_name": "Baseline", "summary": "Revenue grew sharply this month."},
        {"phase_name": "Behavioral", "summary": "Revenue fell among repeat customers."},
    ]
    report = detect_contradictions(phases)
    kinds = {c.kind for c in report.items}
    assert "direction_flip" in kinds
    flip = next(c for c in report.items if c.kind == "direction_flip")
    assert "revenue" in flip.detail.lower()


def test_prompt_section_is_byte_identical_to_legacy():
    phases = [
        {"phase_name": "Baseline", "summary": "Revenue shows a significant anomalous drop."},
        {"phase_name": "Dimensional", "summary": "Everything is within normal variance here."},
    ]
    report = detect_contradictions(phases)
    legacy = _legacy_prompt_section([c.detail for c in report.items])
    assert report.to_prompt_section() == legacy
    # the header + numbering shape is preserved exactly
    assert report.to_prompt_section().startswith("\n⚠ CROSS-PHASE CONTRADICTIONS DETECTED")


def test_clean_phases_yield_empty_report_and_section():
    phases = [
        {"phase_name": "Baseline", "summary": "Revenue fell 18% month over month."},
        {"phase_name": "Dimensional", "summary": "Mobile drove most of the decline."},
    ]
    report = detect_contradictions(phases)
    assert not report.has_contradictions
    assert report.severity == "none"
    assert report.to_prompt_section() == ""


def test_detect_is_fail_open_on_garbage():
    # malformed phases (not dicts) must not raise — returns an empty report
    report = detect_contradictions([object(), object()])
    assert isinstance(report, ContradictionReport) and not report.has_contradictions


def test_singleton_phase_list_is_a_noop():
    assert detect_contradictions([{"phase_name": "X", "summary": "significant"}]).items == []
