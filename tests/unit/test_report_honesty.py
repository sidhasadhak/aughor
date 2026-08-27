"""Report honesty — three fixes from the CI-0 specimen dissection.

  1. Machine caveats are STRUCTURED phase metadata, never fused into summary prose
     (a fused caveat became the TITLE of a shipped executive report — the "$14"
     specimen).
  2. A degraded (synthesis-failed) report says so first-class and never promotes
     phase prose into its headline — including OLD cached phases whose summaries
     still carry the fused ⚠ prefix.
  3. The opportunity lens never benchmarks lifecycle stages against each other
     (the specimen proposed a €2.06M "opportunity" by aspiring to the basket size
     of RETURNED orders).
"""
from __future__ import annotations

from aughor.agent.investigate import _degraded_report, _phase_result, _phases_summary
from aughor.agent.opportunity import annotate_opportunity, compute_opportunity

_CAVEAT = ("This finding's scan touched ~112,439 rows but the metric's table has only ~2 — "
           "a join multiplied the rows, so its magnitude is inflated by a fan-out.")


def _phase(summary: str, caveats=None):
    return _phase_result("xsec", "Cross-Sectional Scan", "📊", "complete",
                         summary, [], caveats=caveats)


# ── 1 · caveats are structured, not fused ─────────────────────────────────────────

def test_phase_caveats_render_labelled_never_fused():
    ph = _phase("Revenue is most concentrated in the luxury segment.", caveats=[_CAVEAT])
    text = _phases_summary([ph])
    assert "⚠ CAVEAT:" in text, "the synthesis prompt still sees the caveat, labelled"
    assert ph["summary"].startswith("Revenue is"), "the prose stays clean"
    assert _CAVEAT not in ph["summary"]


# ── 2 · degraded reports look degraded ────────────────────────────────────────────

def test_degraded_headline_never_promotes_phase_prose():
    """Old cached phases still carry ⚠-fused summaries — the headline must be immune
    to WHATEVER the first summary contains."""
    phases = [_phase(f"⚠ {_CAVEAT} Revenue is most concentrated in luxury.")]
    rep = _degraded_report("Investigate: The total revenue generated across all orders is $14.",
                           phases, {})
    assert "scan touched" not in rep["headline"], "a machine caveat can never be the title"
    assert rep["headline"].startswith("Investigate: The total revenue")
    assert rep["degraded"] is True


def test_degraded_report_carries_caveats_labelled():
    phases = [_phase("Revenue is concentrated in luxury.", caveats=[_CAVEAT])]
    rep = _degraded_report("Where is revenue concentrated?", phases, {})
    assert "⚠ Caveats:" in rep["executive_summary"]
    assert rep["confidence"] == "LOW"


def test_degraded_report_with_no_phases_is_still_honest():
    rep = _degraded_report("", [], {})
    assert rep["degraded"] is True
    assert rep["headline"] == "Phase findings (no synthesized answer)"


def test_degraded_report_never_claims_queries_ran_when_none_did():
    """The false claim that sent an operator hunting through a warehouse connector.

    The degraded notice asserted "the underlying queries ran" unconditionally. That is true
    for the case it was written for — synthesis dying AFTER the phases produced results —
    and false for the one a user meets first: every phase failing at PLANNING, so no SQL was
    ever written. Both directions are asserted together, because a fix that simply deletes
    the claim would also stop reporting the case where it IS true.
    """
    planned_nothing = [_phase_result("baseline", "Baseline & Anomaly", "📊", "error",
                                     "Could not plan baseline queries.", [])]
    rep = _degraded_report("Why did orders drop?", planned_nothing, {})
    assert "NO query ran" in rep["confidence_justification"]
    assert "underlying queries ran" not in rep["confidence_justification"]

    executed = [_phase_result("baseline", "Baseline & Anomaly", "📊", "complete",
                              "Orders fell 12% against the trailing baseline.",
                              [{"sql": "SELECT COUNT(*) FROM orders", "error": None}])]
    ran = _degraded_report("Why did orders drop?", executed, {})
    assert "queries ran (1 executed)" in ran["confidence_justification"]
    assert "NO query ran" not in ran["confidence_justification"]


def test_a_query_that_errored_does_not_count_as_having_run():
    """`sql` is present on a finding whose execution FAILED too. Counting those would
    restore the same false reassurance one layer down — the phase produced no results."""
    failed = [_phase_result("baseline", "Baseline & Anomaly", "📊", "error",
                            "All baseline queries failed to execute.",
                            [{"sql": "SELECT COUNT(*) FROM nope", "error": "no such table"}])]
    rep = _degraded_report("Why did orders drop?", failed, {})
    assert "NO query ran" in rep["confidence_justification"]


# ── 3 · lifecycle stages are not performance peers ───────────────────────────────

_STATUS_ROWS = [["shipped", "25427809.0", "64962"],
                ["returned", "18167767.0", "42941"],
                ["cancelled", "1841968.0", "4536"]]


def test_status_dimension_yields_no_opportunity():
    """The specimen: shipped benchmarked against returned. Silence is the honest output."""
    assert compute_opportunity(["status", "metric_total", "n"], _STATUS_ROWS) is None
    finding = {"columns": ["status", "metric_total", "n"], "rows": _STATUS_ROWS,
               "row_count": 3}
    assert annotate_opportunity(finding, metric_label="GMV") is False
    assert not finding.get("key_numbers")


def test_lifecycle_values_caught_under_any_column_name():
    """An oddly-named column whose VALUES are lifecycle vocabulary is the same trap."""
    assert compute_opportunity(["flow_bucket", "metric_total", "n"], _STATUS_ROWS) is None


def test_real_dimension_still_annotates():
    """The positive control: the guard must not silence legitimate peers."""
    rows = [["West", "3000", "100"], ["East", "4000", "100"], ["Central", "3900", "100"]]
    gap = compute_opportunity(["region", "metric_total", "n"], rows)
    assert gap is not None
    assert gap["worst_segment"] == "West" and gap["best_segment"] == "East"
    finding = {"columns": ["region", "metric_total", "n"], "rows": rows, "row_count": 3}
    assert annotate_opportunity(finding, metric_label="GMV") is True
    assert finding["key_numbers"], "the legitimate opportunity still lands"
