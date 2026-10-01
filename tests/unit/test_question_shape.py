"""Item 3 — an Agent turn works a question by its shape.

Measured 2026-09-29 on five theLook questions, all asking to SEE the data: the analyst was
told to stop only "when a cause is named with its size", so one answered an unasked
2024-vs-2025 comparison; and where it answered what was asked — a table of ten
distribution centres, a table of twelve months — the writer replaced that with an average
nobody computed, a recommendation over a 0.15-day spread and data gaps. A describe question
now gets a roster and a stopping rule for measuring, and its answer is the analyst's own.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from aughor.agent import investigate as I
from aughor.agent.analyst import analyst_system_prompt, analyst_tools

ASKED = [  # the five theLook questions, 2026-09-29
    "What was total revenue and how many units were sold in July 2026?",
    "Which 10 product categories brought in the most revenue in the last 6 months, and what is "
    "the average order value for each?",
    "How has monthly revenue from completed orders trended over the last 12 months, and which "
    "months grew or shrank the most versus the month before?",
    "How long does it take an order to go from placed to shipped to delivered, by distribution "
    "center — and which centers are slowest?",
    "Of customers who placed their first order in each month of 2025, what share ordered again "
    "within 90 days — and does that repeat rate differ by traffic source and country?",
]


@pytest.mark.parametrize("q", ASKED)
def test_a_question_that_asks_to_see_the_data_is_described(q):
    assert I.question_shape(q) == "describe"


@pytest.mark.parametrize("q", [
    "Why did revenue drop in August?",
    "Which product categories drove the change in revenue over the last 90 days, and what is "
    "behind the biggest mover?",
    "Where are we losing money since last 6 months?",
    "Where do we optimise for costs based on the data from last 3 months?",
    "What is driving refund promise breaches on returns, and which carriers are worst?",
    "How can we improve repeat purchases?",
    "Revenue in August",                                   # no ask to read: unclear
])
def test_why_advice_weakness_or_unclear_keeps_the_investigation(q):
    assert I.question_shape(q) == "diagnose"


# ── The analyst ───────────────────────────────────────────────────────────────────────

INVESTIGATION_TOOLS = {"baseline", "decompose", "premise_check", "cross_section"}


def test_a_describe_question_is_not_offered_the_tools_that_explain_a_movement():
    turn = SimpleNamespace(connection_id="test-conn")
    described = {t.name for t in analyst_tools(turn, session_id="s", shape="describe")}
    diagnosed = {t.name for t in analyst_tools(turn, session_id="s")}
    assert INVESTIGATION_TOOLS <= diagnosed
    assert not (INVESTIGATION_TOOLS & described)
    assert {"run_sql", "z_score", "value_lookup", "describe_table"} <= described


def test_the_describe_rule_asks_for_the_answer_not_a_cause():
    described = analyst_system_prompt("c", {}, 12, shape="describe")
    diagnosed = analyst_system_prompt("c", {}, 12)
    assert "asks to SEE the data" in described and "`totals`" in described
    assert "cause is named WITH ITS SIZE" not in described
    assert "cause is named WITH ITS SIZE" in diagnosed


# ── The answer is the analyst's own ───────────────────────────────────────────────────

CONCLUSION = ("Fulfilment takes about 3 days at every centre.\n\n"
              "| Centre | Total (days) |\n| :--- | :--- |\n| NY/NJ | 3.12 |\n| Savannah | 2.97 |\n\n"
              "NY/NJ is slowest at 3.12 days and Savannah fastest at 2.97 days.")


def test_the_lead_sentence_heads_the_answer_and_a_table_first_answer_has_no_headline():
    assert I._lead_sentence(CONCLUSION) == (
        "Fulfilment takes about 3 days at every centre", CONCLUSION.split("\n\n", 1)[1])
    table_first = "| a | b |\n| - | - |\n| 1 | 2 |"
    assert I._lead_sentence(table_first) == ("", table_first)


def test_only_a_describe_question_with_a_conclusion_is_answered_in_the_analysts_words():
    q = ASKED[3]
    got = I._conclusion_as_answer({"_analyst_conclusion": CONCLUSION}, {"question_shape": "describe"}, q)
    assert got.headline == "Fulfilment takes about 3 days at every centre"
    assert "| NY/NJ | 3.12 |" in got.executive_summary
    assert got.recommendations == [] and got.data_gaps == [] and got.attribution_waterfall == []
    assert I._conclusion_as_answer({"_analyst_conclusion": CONCLUSION}, {"question_shape": "diagnose"}, q) is None
    assert I._conclusion_as_answer({}, {"question_shape": "describe"}, q) is None


SQL = ("SELECT dc.name AS centre, SUM(oi.sale_price) AS revenue FROM order_items AS oi "
       "JOIN distribution_centers AS dc ON oi.dc_id = dc.id GROUP BY 1")


def _state(conclusion: str) -> dict:
    finding = {"finding_id": "f1", "title": "Revenue by centre", "sql": SQL,
               "columns": ["centre", "revenue"], "rows": [["NY/NJ", "1200.5"], ["Savannah", "800.25"]],
               "row_count": 2, "error": "", "interpretation": "", "stat_note": "", "trust_caveat": "",
               "is_significant": False, "key_numbers": [], "chart_type": "bar"}
    return {"question": "Which centres brought in the most revenue?", "connection_id": "",
            "investigation_id": "", "_analyst_conclusion": conclusion,
            "_ada_intake": {"metric_label": "revenue", "question_shape": "describe"},
            "investigation_phases": [{"phase_id": "adhoc_1", "phase_name": "Revenue by centre",
                                      "phase_icon": "", "status": "complete", "summary": "",
                                      "findings": [finding], "skipped_reason": None, "caveats": []}]}


def test_the_writer_is_never_called_for_a_describe_answer(monkeypatch):
    """The conclusion becomes the report through the real synthesis step, with no model:
    a figure it states that the rows do not hold is withheld, and said."""
    calls: list = []

    def _no_model(*a, **k):
        calls.append(a)                      # recorded: the repair step swallows a raise
        raise AssertionError("the writer was called for a describe answer")
    monkeypatch.setattr(I, "_provider", _no_model)
    monkeypatch.setattr(I, "_fast_synthesis_rescue", _no_model)
    _synthesize = I.ada_synthesize

    out = _synthesize(_state("NY/NJ led with 1,200.50. Together the two made 2,000.75. "
                             "Savannah made 800.25."))["answer_report"]
    assert out["headline"] == "NY/NJ led with 1,200.50"
    assert out["recommendations"] == [] and out["data_gaps"] == []
    assert "2,000.75" in out["executive_summary"]               # the code's total: it traces

    out = _synthesize(_state("NY/NJ led with 1,200.50. Together the two made 2,111.00. "
                             "Savannah made 800.25."))["answer_report"]
    assert "2,111.00" not in out["executive_summary"]
    assert out["executive_summary"].endswith("so the sentence stating it was withheld.")
    assert calls == []


# ── Totals the analyst can quote ─────────────────────────────────────────────────────

def test_run_sql_hands_the_model_code_computed_totals(monkeypatch):
    from aughor.agent import converse_tools as ct
    monkeypatch.setattr(ct, "_connection", lambda cid: SimpleNamespace(get_schema=lambda: ""))
    result = SimpleNamespace(sql="", columns=["centre", "revenue"], rows=[["a", "1200.5"], ["b", "800.25"]],
                             row_count=2, error=None, caveats=[])
    monkeypatch.setattr("aughor.sql.executor.execute_guarded", lambda *a, **k: result)
    out = ct.run_sql("c1", {"sql": SQL})
    assert out["totals"] == {"revenue": "2000.75"}


# ── 2026-10-01, second round ─────────────────────────────────────────────────────────

def test_the_describe_rule_leads_with_the_answer_and_shows_every_group():
    described = analyst_system_prompt("c", {}, 12, shape="describe")
    assert "Open with the answer itself in one sentence" in described
    assert "never a definition or a restatement of the question" in described
    assert "Show every group of a cut, or say how many you left out" in described
    assert "never at the top" in described


def test_a_sentence_about_sample_size_claims_no_cause():
    """Live, twice: "small sample sizes, which may lead to volatile rates" was refused as a
    causal claim under an associational licence, and the quote began at a table heading."""
    from aughor.agent.claim_type import overreaching_sentences
    prose = ("| Country | Rate |\n| :--- | :--- |\n| Colombia | 25.0% |\n\n*Note: Some countries have "
             "very small sample sizes, which may lead to volatile rates.*\nThe promotion led to more orders.")
    hits = overreaching_sentences(prose, "associational")
    assert [s for s, _ in hits] == ["The promotion led to more orders."]


def test_the_disclosure_says_whether_a_repair_was_attempted():
    from aughor.agent.report_checks import Violation, reader_disclosure
    v = [Violation("fix it", "a figure could not be traced (#36)")]
    assert reader_disclosure(v).startswith("Deterministic checks after the repair attempt:")
    assert reader_disclosure(v, repaired=False).startswith("Deterministic checks on this answer:")


def test_the_analyst_measures_on_the_measures_table_and_acts_on_a_caveat():
    """Q4's re-run (2026-10-01): the spec measured shipping time on `orders`; the analyst cut it
    by centre on `order_items`, kept the 30% of rows a guard flagged out of it twice, and opened
    with one centre's figure as the overall and a "slowest" over a 0.06-day spread."""
    from aughor.agent.analyst import analyst_system_prompt
    for shape in ("describe", "diagnose"):
        p = analyst_system_prompt("c", {}, 10, shape=shape)
        assert "JOIN that table to the measure's" in p
        assert "re-measure the way it says, then answer from that result" in p
        assert "Leaving out the rows a guard flagged is not a re-measure." in p
    p = analyst_system_prompt("c", {}, 10, shape="describe")
    assert "Groups within a few percent of each other are alike" in p
    assert "never one group's value, never an average of the groups' averages" in p
