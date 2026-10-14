"""P4 of the canvas-output study (2026-10-14): the narrator is asked only for what has a reader, and on
an analyst turn writes from the results the analyst cited.

Measured before: `attribution_waterfall` empty in 86 of 88 stored reports while three of the seven
narrator rules governed it; `owner` and `timeline` REQUIRED, so invented ("Logistics Operations",
"2026-10-30"); a five-phase plan declared on every analyst turn and reconciled as "skipped" on 87 of 88;
live (5b6fb57c) the narrator wrote one story over two measurements of revenue, one of them from a
result the analyst had not cited."""
from __future__ import annotations

import aughor.agent.investigate as I
from aughor.agent.prompts_investigate import (
    SynthesisAsk,
    ADASynthesisModel,
    AnswerRecommendationModel,
    synthesis_ask_model,
    synthesis_system_prompt,
    widen_synthesis,
)


def test_the_waterfall_is_asked_for_only_when_one_can_exist():
    assert synthesis_ask_model(True) is ADASynthesisModel
    assert synthesis_ask_model(False) is SynthesisAsk
    assert "attribution_waterfall" not in SynthesisAsk.model_fields
    assert set(SynthesisAsk.model_fields) == set(ADASynthesisModel.model_fields) - {"attribution_waterfall"}


def test_an_answer_without_a_waterfall_widens_to_the_full_model_with_an_empty_one():
    asked = SynthesisAsk(headline="h", executive_summary="s", total_change_label="", confidence="HIGH",
                            confidence_justification="j", recommendations=[], data_gaps=[])
    full = widen_synthesis(asked)
    assert isinstance(full, ADASynthesisModel) and full.attribution_waterfall == [] and full.headline == "h"
    assert widen_synthesis(full) is full and widen_synthesis(None) is None


def test_the_waterfall_rule_rides_only_a_call_that_asks_for_one():
    assert "attribution_waterfall: entries account for" in synthesis_system_prompt(waterfall=True)
    assert "attribution_waterfall" not in synthesis_system_prompt(waterfall=False)
    assert "Signs: losses/declines NEGATIVE" in synthesis_system_prompt(waterfall=False)


def test_a_recommendation_needs_only_its_action():
    rec = AnswerRecommendationModel(action="Audit the August Search campaign logs")
    assert (rec.expected_impact, rec.owner, rec.timeline) == ("", "", "")
    for name in ("expected_impact", "owner", "timeline"):
        assert "never" in AnswerRecommendationModel.model_fields[name].description


def test_below_a_causal_licence_the_section_no_longer_lectures_about_a_field_not_asked():
    section = I._claim_licence_section({"intake_notes": "CLAIM LICENCE: associational — a scan."}, [])
    assert "ATTRIBUTION WATERFALL" not in section and "attribution_waterfall" not in section
    assert "total_change_label" in section


def test_an_analyst_turn_declares_no_plan_and_reconciles_none():
    from aughor.agent.analyst import _base_state
    state = _base_state("q", "c1", "inv", "schema", origin_finding=None, scope_schema="", canvas_id=None,
                        canvas_schema_context="", data_catalog="")
    assert state["analyst_turn"] is True


def _phases():
    cited = {"finding_id": "adhoc_4_1", "title": "Aug and jul by department", "sql": "SELECT 1", "error": None,
             "columns": ["department", "aug", "jul"], "rows": [["Men", "212664", "175966"], ["Women", "172725", "160417"]],
             "row_count": 2, "interpretation": "", "key_numbers": [], "chart_type": "auto", "stat_note": None,
             "is_significant": False}
    uncited = {"finding_id": "decomp_2", "title": "Revenue change: new vs returning customers", "sql": "SELECT 2",
               "error": None, "columns": ["customer_type", "comp_rev", "obs_rev"],
               "rows": [["Returning", "110695", "135595"], ["New", "186221", "200137"]], "row_count": 2,
               "interpretation": "Returning customers added 24,900.", "key_numbers": [], "chart_type": "auto",
               "stat_note": None, "is_significant": False}
    return [{"phase_id": "intake", "phase_name": "Question Intake", "status": "complete", "summary": "spec", "findings": []},
            {"phase_id": "decomposition", "phase_name": "Metric Decomposition", "status": "complete",
             "summary": "Volume carried it.", "findings": [uncited]},
            {"phase_id": "adhoc_4", "phase_name": "Aug and jul by department", "status": "complete", "summary": "",
             "findings": [cited]}]


def test_the_narrator_reads_the_cited_results_and_only_the_names_of_the_rest():
    phases = _phases()
    narr, uncited = I._phases_cited(phases, ["adhoc_4_1"])
    assert uncited == [("decomp_2", "Revenue change: new vs returning customers")]
    assert narr[1]["_hidden"] is True and narr[1]["findings"] == []
    assert [f["finding_id"] for f in narr[2]["findings"]] == ["adhoc_4_1"]
    assert phases[1]["findings"][0]["finding_id"] == "decomp_2" and "_hidden" not in phases[1]   # untouched
    evidence = I._phases_evidence_budgeted(narr)
    assert "212664" in evidence and "135595" not in evidence


def test_on_an_analyst_turn_the_narrator_prompt_carries_the_cited_rows_and_names_the_uncited(monkeypatch):
    seen: dict = {}

    class _Narrator:
        def complete(self, *, system, user, response_model):
            seen["system"], seen["user"], seen["model"] = system, user, response_model
            return response_model(headline="August rose on Men", executive_summary="Men added 36,698.",
                                  total_change_label="", confidence="MEDIUM", confidence_justification="j",
                                  recommendations=[], data_gaps=[])
    monkeypatch.setattr(I, "_provider", lambda role: _Narrator())
    monkeypatch.setattr(I, "report_delta_emitter", lambda: None, raising=False)
    state = {"question": "Why did revenue change in August 2026 against July 2026?", "connection_id": "",
             "investigation_id": "", "_analyst_conclusion": "Men carried it.",
             "_analyst_conclude": {"headline": "August rose on Men", "answer": "Men carried it.",
                                   "exhibits": [{"finding_id": "adhoc_4_1", "claim": "Men added $36.7K of the $49.0K"}],
                                   "figures": [], "gaps": ""},
             "_ada_intake": {"question_shape": "diagnose", "metric_label": "revenue", "metric_sql": "SUM(x)",
                             "metric_table": "order_items", "cross_sectional": False,
                             "intake_notes": "CLAIM LICENCE: descriptive — a period comparison."},
             "investigation_phases": _phases()}
    report = I.ada_synthesize(state)["answer_report"]
    assert "212664" in seen["user"] and "135595" not in seen["user"]
    assert "Revenue change: new vs returning customers (decomp_2)" in seen["user"]
    assert "Men added $36.7K of the $49.0K" in seen["user"]
    assert seen["model"] is SynthesisAsk                      # descriptive licence: no waterfall asked
    assert "attribution_waterfall" not in seen["system"]
    assert report["attribution_waterfall"] == [] and report["plan_reconciliation"] is None
    assert [f["finding_id"] for p in report["phases"] for f in p["findings"]] == ["decomp_2", "adhoc_4_1"]
