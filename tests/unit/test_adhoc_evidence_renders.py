"""A query the model framed itself is evidence the report can show.

Live: deep analysis answered "give me route wise number of flights" with one `run_sql`
and rendered three sentences — no table, no chart — while the QUICK path, which draws
its rows directly, showed the whole breakdown. Deep read as thinner than quick for the
same question.

Only the phase tools (baseline, decompose, cross_section, intake) built a phase, and the
report draws its exhibits from phase findings. `run_sql` rows reached the narrator's
prose and stopped there.
"""
from __future__ import annotations

from aughor.agent import analyst as an


class _Turn:
    """The parts of AnalystTurn `_record_evidence` touches."""
    def __init__(self):
        self.state = {"investigation_phases": [], "question": "give me route wise flights"}
        self.evidence_rows = 0
        self.phase_tools_run: list[str] = []
        self.merged: list[tuple] = []

    def merge(self, node_return, *, tool):
        self.state.update(node_return or {})
        self.phase_tools_run.append(tool)
        self.merged.append((tool, node_return))
        return []


_RESULT = {"columns": ["route_id", "n_flights"],
           "rows": [["GVA-FRA", 42], ["ZRH-VIE", 42], ["ZRH-BUD", 35]]}


def test_an_ad_hoc_query_becomes_a_finding_the_report_can_draw():
    t = _Turn()
    an._record_evidence(t, {"sql": "SELECT route_id, COUNT(*) FROM flights GROUP BY 1"}, _RESULT)

    phases = t.state["investigation_phases"]
    assert len(phases) == 1
    finding = phases[0]["findings"][0]
    assert finding["rows"] == _RESULT["rows"]
    assert finding["columns"] == ["route_id", "n_flights"]
    assert finding["row_count"] == 3
    # the SQL rides along, so the exhibit carries its own provenance
    assert finding["sql"].startswith("SELECT route_id")
    # …and it counts as evidence for the report's no-data floor
    assert t.evidence_rows == 3


def test_the_finding_is_named_from_the_shape_of_the_result():
    """`run_sql` supplies no title — the phase tools get theirs from a plan."""
    t = _Turn()
    an._record_evidence(t, {"sql": "SELECT 1"}, _RESULT)
    assert t.state["investigation_phases"][0]["findings"][0]["title"] == "n_flights by route_id"


def test_it_streams_as_a_phase_so_the_turn_shows_its_work_live():
    t = _Turn()
    an._record_evidence(t, {"sql": "SELECT 1"}, _RESULT)
    assert [tool for tool, _ in t.merged] == ["run_sql"]


def test_each_query_is_its_own_slice():
    """The loop's cuts ARE the story of the turn; folding them into one box would hide
    that it took several to get there."""
    t = _Turn()
    an._record_evidence(t, {"sql": "SELECT 1"}, _RESULT)
    an._record_evidence(t, {"sql": "SELECT 2"}, _RESULT)
    assert len(t.state["investigation_phases"]) == 2
    assert t.state["investigation_phases"][1]["phase_id"] == "adhoc_2"


def test_a_query_with_no_rows_builds_nothing():
    """Nothing to draw, and an empty exhibit is worse than none."""
    t = _Turn()
    an._record_evidence(t, {"sql": "SELECT 1"}, {"columns": ["a"], "rows": []})
    assert t.state["investigation_phases"] == []
    assert t.evidence_rows == 0


def test_a_tool_result_that_is_not_a_result_set_passes_through_untouched():
    t = _Turn()
    out = an._record_evidence(t, {}, "just a string")
    assert out == "just a string"
    assert t.state["investigation_phases"] == []


def test_the_result_still_reaches_the_model_unchanged():
    """The capture is a side effect; the loop must get exactly what the tool returned."""
    t = _Turn()
    assert an._record_evidence(t, {"sql": "x"}, _RESULT) is _RESULT
