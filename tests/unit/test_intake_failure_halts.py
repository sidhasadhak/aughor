"""A failed intake must STOP the run — it may not fall through to the baseline.

Diagnosed 2026-09-18 from two stored runs of the SAME question, on the SAME connection
(theLook `8233e4fd`), 42 seconds apart:

  29c3c169  "Gross Margin Analysis: No Financial Loss Identified"   confidence HIGH
            metric: SUM(order_items.sale_price - inventory_items.cost)
            window: 2026-03-20 → 2026-09-18   (data spans 2019-01-13 → 2026-09-21)

  18345353  "Revenue grew 11.8%; final week drop is likely a data artifact"  LOW
            metric: SUM(order_items.sale_price)
            window: 2023-10-01 → 2024-04-01   ← 2.5 years stale

The second run's intake phase came back `status=error` ("structured output empty: the
model returned no content"). `ada_intake` handled that correctly and returned early —
but it returned only `investigation_phases` and `answer_report`, leaving `_ada_intake`
at its `None` seed. `route_after_intake` reads `state.get("_ada_intake") or {}`, so a
FAILED intake and a healthy temporal question were the same empty dict, and both routed
to `ada_baseline`.

The run then walked its full length with no metric, no table, no date column and no
window. Each downstream phase filled the holes from its own `.get(..., default)`
literals — six sites defaulted `metric_sql` to the hardcoded `"SUM(revenue)"`, which is
where that report's "Revenue" came from; it was never any model's judgement. With no
comparison window, `_no_prior` went True, so the prompt asserted "no period before the
observation window exists in the data" over 7.7 years of history.

Unpinned, the planner invented a window, and the report's headline finding was the
right edge of its own filter: `WHERE created_at < TIMESTAMP('2024-04-01')` bucketed by
`DATE_TRUNC(DATE(created_at), WEEK)`. 2024-03-31 is a Sunday, so the final bucket held
exactly ONE day — $4,071.43 against a $28,351.31 prior week, i.e. 1/7, reported as an
"85.6% collapse" and escalated to Data Engineering with a one-day deadline.

Every deterministic guard written to prevent this (`_clamp_intake_to_coverage`'s stale
-window re-anchor, `_flag_trailing_partial`, `_validate_intake_windows`) sits inside
`if intake is not None:` — skipped in exactly the case they exist for. A run with no
spec cannot be guarded into correctness; it can only be stopped.

Sibling of tests/unit/test_deep_analysis_honest_failure.py, which pins the same law one
layer down: a failure may not become a *report*. This pins: it may not become a *run*.
"""
import inspect

from aughor.agent import investigate as I
from aughor.agent import graph as G


_HEALTHY = {
    "metric_label": "net revenue", "metric_sql": "SUM(sale_price)",
    "metric_table": "main.order_items", "date_column": "main.order_items.created_at",
    "observation_start": "2026-03-20", "observation_end": "2026-09-18",
    "comparison_start": "2025-09-19", "comparison_end": "2026-03-19",
    "dimensions": ["main.products.category"],
}


def _state(**over):
    return {"question": "Where are we losing money since last 6 months?",
            "schema_context": "", "connection_id": "8233e4fd",
            "investigation_phases": [], **over}


class TestTheRouteStops:
    def test_a_failed_intake_does_not_reach_the_baseline(self):
        """The regression itself: run 18345353's state shape must not route to work."""
        st = _state(_ada_intake=None, _intake_failed="structured output empty: the model returned no content")
        assert I.route_after_intake(st) == "intake_failed"

    def test_the_verdict_outranks_every_other_route(self):
        """A half-populated intake alongside the failure must still stop. The failure is
        the strongest verdict on the state — nothing downstream can use a partial spec."""
        for over in ({"descriptive_only": True}, {"cross_sectional": True}, {}):
            st = _state(_ada_intake={**_HEALTHY, **over}, _intake_failed="empty")
            assert I.route_after_intake(st) == "intake_failed", over

    def test_the_clarify_gate_stops_too(self):
        """`route_after_intake_clarify` delegates, so the gate must inherit the halt."""
        st = _state(_ada_intake=None, _intake_failed="empty")
        assert I.route_after_intake_clarify(st) == "intake_failed"

    def test_a_healthy_intake_is_untouched(self):
        """The halt keys on the verdict, not on emptiness — a real run must still run."""
        assert I.route_after_intake(_state(_ada_intake=dict(_HEALTHY))) == "ada_baseline"
        assert I.route_after_intake(
            _state(_ada_intake={**_HEALTHY, "cross_sectional": True})) == "ada_cross_section"
        assert I.route_after_intake(
            _state(_ada_intake={**_HEALTHY, "descriptive_only": True})) == "deep_breakdown"


class TestTheWiring:
    def test_the_graph_can_reach_the_end(self):
        """A route string with no edge in the map is a runtime error, not a test failure."""
        src = inspect.getsource(G._compile)
        assert src.count('"intake_failed": END') == 2, (
            "both the intake and the clarify gate must be able to reach END")

    def test_the_node_sets_the_verdict(self):
        """`ada_intake`'s `intake is None` branch must emit `_intake_failed`, or the
        router above can never see it."""
        src = inspect.getsource(I.ada_intake)
        head, _, tail = src.partition("if intake is None:")
        assert tail, "the failure branch moved — re-pin this test"
        branch = tail[:tail.find("return {") + tail[tail.find("return {"):].find("}") + 1]
        assert "_intake_failed" in branch

    def test_the_state_declares_it(self):
        from aughor.agent.state import AgentState
        assert "_intake_failed" in AgentState.__annotations__


class TestNoFabricatedMetric:
    """A ratchet. These defaults are what turned a failure into a plausible report."""

    def test_no_phase_invents_a_metric(self):
        src = inspect.getsource(I)
        for bad in ('"metric_sql", "SUM(revenue)"',
                    '"metric_label", "the metric"',
                    '"metric_label", "the core metric"'):
            # The prose above quotes the old literals; count CODE occurrences only.
            hits = [ln for ln in src.splitlines()
                    if bad in ln and not ln.lstrip().startswith("#")]
            assert not hits, f"a phase still defaults to {bad}: {hits[:2]}"
