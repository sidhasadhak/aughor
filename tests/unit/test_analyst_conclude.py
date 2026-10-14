"""P1 of the canvas-output study (`analyst.conclude`): the analyst's answer carries its own
structure — a headline, the answer, the results it cites with their claims — and nothing in it
is cut or guessed by code. Measured on 88 stored answers (2026-10-14): 58% of the results drawn
carried no words, 46 bodies tabulated rows a result below drew again, and the first-sentence
headline ran past 16 words in 43 — 32 at p90."""
from __future__ import annotations

from types import SimpleNamespace

from aughor.agent.analyst import (
    AnalystTurn,
    _attach_conclusion,
    _phase_payload,
    _record_evidence,
    analyst_system_prompt,
    analyst_tools,
    conclude,
)
from aughor.kernel.flags import flag_overrides

ON = {"analyst.conclude": True}


def _turn(findings: list[dict] | None = None) -> AnalystTurn:
    phases = [{"phase_id": "adhoc_1", "phase_name": "Revenue by category", "status": "complete",
               "summary": "", "findings": findings if findings is not None else [
                   {"finding_id": "adhoc_1_1", "title": "Revenue by category", "sql": "SELECT 1",
                    "columns": ["category", "revenue"], "rows": [["Jeans", 213177.98], ["Swim", 117253.8]],
                    "row_count": 2, "interpretation": "", "key_numbers": [], "chart_type": "auto", "error": None}]}]
    return AnalystTurn(connection_id="c1", conn=SimpleNamespace(dialect="duckdb"),
                       state={"question": "which category leads?", "investigation_phases": phases})


GOOD = {"headline": "Jeans lead six-month revenue at $213.2K; Swim trails at $117.3K",
        "answer": "Jeans lead at $213.2K; Swim trails at $117.3K.",
        "exhibits": [{"result": "adhoc_1_1", "claim": "Jeans lead Swim by $95.9K"}],
        "figures": [{"label": "Jeans", "value": "$213.2K", "note": "leads"}], "gaps": ""}


def test_a_good_conclusion_is_accepted_and_kept_on_the_turn():
    turn = _turn()
    out = conclude(turn, GOOD)
    assert out["concluded"] is True and out["answer"] == GOOD["answer"]
    assert turn.conclusion["exhibits"] == [{"finding_id": "adhoc_1_1", "claim": "Jeans lead Swim by $95.9K"}]
    assert turn.conclusion["figures"] == [{"label": "Jeans", "value": "$213.2K", "note": "leads"}]


def test_a_headline_over_one_line_is_refused_not_cut():
    turn = _turn()
    out = conclude(turn, {**GOOD, "headline": " ".join(["word"] * 17)})
    assert "concluded" not in out and "17 words" in out["refused"] and turn.conclusion is None


def test_an_answer_carrying_a_table_is_refused():
    turn = _turn()
    out = conclude(turn, {**GOOD, "answer": "Here:\n\n| category | revenue |\n|---|---|\n| Jeans | 213177 |\n"})
    assert "carries a table" in out["refused"] and turn.conclusion is None


def test_a_cited_result_this_turn_never_produced_is_refused_with_the_real_ids():
    turn = _turn()
    out = conclude(turn, {**GOOD, "exhibits": [{"result": "adhoc_9_1", "claim": "x"}]})
    assert "'adhoc_9_1'" in out["refused"] and "adhoc_1_1" in out["refused"]


def test_an_empty_citation_list_is_refused_while_results_exist():
    out = conclude(_turn(), {**GOOD, "exhibits": []})
    assert "exhibits is empty" in out["refused"]


def test_a_run_sql_result_carries_the_id_it_is_cited_by():
    turn = AnalystTurn(connection_id="c1", conn=SimpleNamespace(dialect="duckdb"),
                       state={"question": "q", "investigation_phases": []})
    result = _record_evidence(turn, {"sql": "SELECT category, SUM(x) AS revenue FROM t GROUP BY 1"},
                              {"rows": [["Jeans", 1.0]], "columns": ["category", "revenue"], "row_count": 1})
    assert result["result_id"] == "adhoc_1_1"
    assert turn.state["investigation_phases"][0]["findings"][0]["finding_id"] == "adhoc_1_1"


def test_a_phase_tool_names_its_results_ids_beside_the_evidence():
    payload = _phase_payload(_turn().state["investigation_phases"])
    assert payload["phases"][0]["results"] == [{"result_id": "adhoc_1_1", "title": "Revenue by category"}]


def test_the_tool_is_on_the_roster_only_with_the_flag():
    stub = SimpleNamespace(connection_id="c1")
    assert "conclude" not in {t.name for t in analyst_tools(stub, session_id="s")}
    with flag_overrides(ON):
        for shape in ("diagnose", "describe"):
            tools = analyst_tools(stub, session_id="s", shape=shape)
            assert tools[-1].name == "conclude" and tools[-1].concludes is True, shape


def test_the_prompt_asks_for_conclude_only_with_the_flag():
    for shape in ("diagnose", "describe"):
        off = analyst_system_prompt("c1", {}, 10, shape=shape)
        assert "conclude" not in off and "When you stop" in off, shape
        with flag_overrides(ON):
            on = analyst_system_prompt("c1", {}, 10, shape=shape)
        assert "call `conclude`" in on and "result_id" in on, shape
        assert "The following table lists" not in on or shape == "diagnose"


def test_the_conclusion_lands_on_the_report_as_exhibits_in_the_cited_order():
    report = {"phases": [{"phase_id": "adhoc_1", "findings": [
        {"finding_id": "adhoc_1_1", "claim": None}, {"finding_id": "adhoc_2_1", "claim": None}]}]}
    _attach_conclusion(report, {"headline": "h", "answer": "a", "figures": [{"label": "L", "value": "1", "note": ""}],
                                "gaps": "No carrier data.",
                                "exhibits": [{"finding_id": "adhoc_2_1", "claim": "Second first"},
                                             {"finding_id": "adhoc_1_1", "claim": "Then the first"},
                                             {"finding_id": "pruned_0", "claim": "gone"}]})
    assert [e["finding_id"] for e in report["exhibits"]] == ["adhoc_2_1", "adhoc_1_1"]
    assert report["phases"][0]["findings"][1]["claim"] == "Second first"
    assert report["figures"] == [{"label": "L", "value": "1", "note": ""}] and report["gaps"] == "No carrier data."


def test_a_report_whose_turn_did_not_conclude_is_untouched():
    report = {"phases": []}
    _attach_conclusion(report, None)
    assert report == {"phases": []}


def test_a_describe_answer_takes_the_conclusions_own_headline():
    from aughor.agent.investigate import _conclusion_as_answer
    state = {"_analyst_conclusion": "The following table lists the categories:\n\n| a | b |\n|---|---|\n| 1 | 2 |",
             "_analyst_conclude": {"headline": "Jeans lead at $213.2K", "answer": "Jeans lead; Swim trails.",
                                   "gaps": "The data holds no cost.", "exhibits": [], "figures": []},
             "investigation_phases": []}
    synth = _conclusion_as_answer(state, {"question_shape": "describe"}, "Which category leads?")
    assert synth.headline == "Jeans lead at $213.2K"
    assert synth.executive_summary == "Jeans lead; Swim trails.\n\nThe data holds no cost."
