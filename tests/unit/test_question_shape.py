"""Item 3 — an Agent turn works a question by its shape.

Measured 2026-09-29 on five theLook questions, all asking to SEE the data: the analyst was
told to stop only "when a cause is named with its size", so one answered an unasked
2024-vs-2025 comparison; and where it answered what was asked — a table of ten
distribution centres, a table of twelve months — the writer replaced that with an average
nobody computed, a recommendation over a 0.15-day spread and data gaps. A describe question
now gets a roster and a stopping rule for measuring, and its answer is the analyst's own.
"""
from __future__ import annotations

import re
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
    assert "one that announces what follows" in described, "Q2's opener announced its table (2026-10-02)"
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


Q2 = ("Which 10 product categories brought in the most revenue in the last 6 months, and what is the "
      "average order value for each?")
TABLE = "| Category | Revenue |\n| :--- | :--- |\n| Outerwear & Coats | $237,836.63 |"


def test_a_lead_that_announces_the_answer_does_not_head_it():
    """Q2's answer (2026-10-02) opened "The following table lists the 10 product categories … between
    March 4, 2026, and September 3, 2026": its numbers were the question's and the period's."""
    announced = ("The following table lists the 10 product categories with the highest revenue between "
                 "March 4, 2026, and September 3, 2026, along with their average order value (AOV).\n\n" + TABLE)
    assert I._lead_sentence(announced, Q2) == ("", announced)
    answered = "Outerwear & Coats brought in the most, $237,836.63, of the 10.\n\n" + TABLE
    assert I._lead_sentence(answered, Q2) == ("Outerwear & Coats brought in the most, $237,836.63, of the 10", TABLE)


CATEGORIES = ["Outerwear & Coats", "Jeans", "Sweaters", "Suits & Sport Coats", "Fashion Hoodies & Sweatshirts",
              "Swim", "Sleep & Lounge", "Shorts", "Tops & Tees", "Intimates"]


def test_a_lead_that_names_what_came_back_heads_the_answer():
    """Q2's answer of 2026-10-03 opened with its leader and its last, and no figure: an answer all the same."""
    lead = ("The product category with the highest revenue over the last six months (March 4, 2026, to "
            "September 3, 2026) was Outerwear & Coats, while Intimates generated the least among the top 10 "
            "categories.")
    text = lead + "\n\n" + TABLE
    assert I._lead_sentence(text, Q2, CATEGORIES) == (lead.rstrip("."), TABLE)
    assert I._lead_sentence(text, Q2) == ("", text), "without the rows it names nothing it read"
    announced = "The following table lists the 10 product categories by revenue.\n\n" + TABLE
    assert I._lead_sentence(announced, Q2, CATEGORIES) == ("", announced)
    # a value the question itself named is the question's, not the answer's
    assert I._lead_sentence("Jeans is listed below.\n\n" + TABLE, "How did Jeans do?", ["Jeans"])[0] == ""
    # an opener that ends in a colon introduces its table, whatever it names (Q2, 2026-10-03)
    colon = ("The product categories generating the highest revenue between March 5, 2026, and September 4, 2026, are "
             "led by Outerwear & Coats and Jeans, with the following breakdown of total revenue and average order "
             "value (AOV):\n\n" + TABLE)
    assert I._lead_sentence(colon, Q2, CATEGORIES) == ("", colon)


def test_the_values_a_lead_can_name_are_the_text_its_rows_hold():
    state = {"investigation_phases": [{"findings": [{"rows": [
        ["Outerwear & Coats", "237836.63", "2026-07-01", "July 2026", "NULL", None, "Q3 2026"],
        ["Jeans", "214128.38", "2026-08-01", "August 2026", "", "nan", "Outerwear & Coats"]]}]}]}
    assert I._result_values(state) == ["Outerwear & Coats", "Jeans"]


def test_a_long_lead_heads_the_answer_by_its_first_clause_and_a_sentence_runs_past_vs():
    clause = "Outerwear & Coats led with $237,836.63 at an AOV of $150.82"
    tail = "jeans followed with $214,128.38, " + ", ".join(f"category {i} with ${i},000" for i in range(12))
    head, body = I._lead_sentence(f"{clause}; {tail}.\n\n{TABLE}", Q2)
    assert head == clause and body.startswith("Jeans followed with $214,128.38") and body.endswith(TABLE)
    unbroken = "Revenue rose " + " ".join(f"by {i} points" for i in range(60)) + "."
    head, body = I._lead_sentence(unbroken)
    assert head.endswith("…") and len(head) <= 241 and body == unbroken
    assert I._lead_sentence("July was $117,163.37 vs. $98,000 in June. Then more.")[0] == (
        "July was $117,163.37 vs. $98,000 in June")


def test_only_a_describe_question_with_a_conclusion_is_answered_in_the_analysts_words():
    q = ASKED[3]
    got = I._conclusion_as_answer({"_analyst_conclusion": CONCLUSION}, {"question_shape": "describe"}, q)
    assert got.headline == "Fulfilment takes about 3 days at every centre"
    assert "| NY/NJ | 3.12 |" in got.executive_summary
    assert got.recommendations == [] and got.data_gaps == [] and got.attribution_waterfall == []
    # a one-sentence answer is its headline, and nothing again beneath it (Q1, 2026-10-03)
    one = I._conclusion_as_answer({"_analyst_conclusion": "July 2026 brought in $359,224.30 from 7,027 units."},
                                  {"question_shape": "describe"}, ASKED[0])
    assert (one.headline, one.executive_summary) == ("July 2026 brought in $359,224.30 from 7,027 units", "")
    assert I._conclusion_as_answer({"_analyst_conclusion": CONCLUSION}, {"question_shape": "diagnose"}, q) is None
    assert I._conclusion_as_answer({}, {"question_shape": "describe"}, q) is None


SQL = ("SELECT dc.name AS centre, SUM(oi.sale_price) AS revenue FROM order_items AS oi "
       "JOIN distribution_centers AS dc ON oi.dc_id = dc.id GROUP BY 1")


_synthesize = I.ada_synthesize


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


def test_an_opener_that_does_not_answer_gives_way_to_the_ranked_rows(monkeypatch):
    """Q2 had no headline in three runs (2026-10-02/03) — "The following table lists…" — over rows that held
    the answer. Its first and last row head it, by the measure the rows are ordered on, and the figures trace."""
    monkeypatch.setattr(I, "_provider", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no model")))
    state = _state("The following table lists the centres by revenue.\n\n| Centre | Revenue |\n| --- | --- |\n"
                   "| NY/NJ | $1,200.50 |\n| Savannah | $800.25 |\n| Houston | $310.00 |")
    state["investigation_phases"][0]["findings"][0]["rows"].append(["Houston", "310"])
    out = _synthesize(state)["answer_report"]
    assert out["headline"] == "NY/NJ has the highest revenue, $1,200.50, and Houston the lowest of the 3, $310"
    assert out["executive_summary"].startswith("The following table lists")
    state["investigation_phases"][0]["findings"][0]["rows"][1][1] = "1500"          # not ordered: no ranking
    assert I._ranked_headline(state, "") == ""


# ── Totals the analyst can quote ─────────────────────────────────────────────────────

def test_run_sql_hands_the_model_code_computed_totals(monkeypatch):
    from aughor.agent import converse_tools as ct
    monkeypatch.setattr(ct, "_connection", lambda cid, **kw: SimpleNamespace(get_schema=lambda: ""))
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


# ── 2026-10-01, re-run #5 — what may not be added up is said, with why ───────────────────

Q4_RERUN = ("WITH order_metrics AS (SELECT o.order_id, DATE_DIFF(CAST(o.shipped_at AS DATE), CAST(o.created_at AS "
            "DATE), DAY) AS days_placed_to_shipped, ii.product_distribution_center_id FROM orders AS o JOIN order_items "
            "AS oi ON o.order_id = oi.order_id JOIN inventory_items AS ii ON oi.inventory_item_id = ii.id GROUP BY 1, 2, 3) "
            "SELECT dc.name AS distribution_center, AVG(om.days_placed_to_shipped) AS avg_days_placed_to_shipped, "
            "COUNT(DISTINCT om.order_id) AS order_count FROM order_metrics AS om JOIN distribution_centers AS dc "
            "ON om.product_distribution_center_id = dc.id GROUP BY 1")


def test_run_sql_says_which_columns_do_not_add_up_and_why(monkeypatch):
    """Q4's re-run counted distinct orders per centre; the centres' counts add to 59,911 where the
    orders number 43,457, and the sentence carrying such a sum was withheld."""
    from aughor.agent import converse_tools as ct
    monkeypatch.setattr(ct, "_connection", lambda cid, **kw: SimpleNamespace(get_schema=lambda: ""))
    result = SimpleNamespace(sql="", columns=["distribution_center", "avg_days_placed_to_shipped", "order_count"],
                             rows=[["Houston TX", "1.488", "7502"], ["Memphis TN", "1.502", "7836"]],
                             row_count=2, error=None, caveats=[])
    monkeypatch.setattr("aughor.sql.executor.execute_guarded", lambda *a, **k: result)
    out = ct.run_sql("c1", {"sql": Q4_RERUN})
    assert "totals" not in out
    assert out["no_total"]["order_count"].startswith("counts distinct values per row")
    assert out["no_total"]["avg_days_placed_to_shipped"].startswith("an average or a ratio per row")
    assert "distribution_center" not in out["no_total"]


def test_a_ratio_holding_a_distinct_count_is_named_a_ratio_and_a_sum_is_totalled_not_named():
    from aughor.tools.postproc import untotalled
    sql = ("SELECT category, SUM(sale_price) AS total_revenue, SUM(sale_price) / COUNT(DISTINCT order_id) "
           "AS average_order_value FROM order_items GROUP BY 1")
    rows = [["Jeans", "220935.50", "100.79"], ["Swim", "114013.31", "57.76"]]
    said = dict(untotalled(sql, ["category", "total_revenue", "average_order_value"], rows, 2))
    assert list(said) == ["average_order_value"] and said["average_order_value"].startswith("an average or a ratio")
    assert untotalled(sql, ["category", "total_revenue", "average_order_value"], rows[:1], 2) == []   # not all in hand


def test_the_describe_rules_give_an_answer_no_figure_to_copy():
    """Re-run #6 (2026-10-01): the alike rule's example, "every centre takes 3.95–4.01 days", was the fulfilment
    question's own range of total days — a sum of two averages no row holds — and that answer then had a sentence
    withheld as untraced. A figure in a rule is a figure an answer can copy; the range is read from the rows."""
    from aughor.agent.analyst import _describe_rules
    text = " ".join(_describe_rules(7))
    assert re.findall(r"\d", text) == ["7"]                 # the budget, and no other figure
    assert "each read from a row" in text


def test_the_describe_rule_never_adds_up_a_column_under_no_total():
    from aughor.agent.analyst import analyst_system_prompt
    assert "a column under `no_total` is never added up at all" in analyst_system_prompt("c", {}, 10, shape="describe")
