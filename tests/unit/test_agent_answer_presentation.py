"""An Agent answer's results are titled by what they measure, and its PDF reads as written.

Measured 2026-10-01 on the theLook repeat-rate answer (Agent mode, describe): each of its three
results was titled with the question cut at 80 characters — the same words over three different
tables, printed three times apiece in the PDF — and the PDF printed the answer's markdown raw:
"### 90-Day Repeat Rate by Cohort Month (2025) | Cohort Month | … | :--- |".
"""
from __future__ import annotations

from aughor.agent.analyst import _adhoc_title

QUESTION = ("Of customers who placed their first order in each month of 2025, what share ordered "
            "again within 90 days — and does that repeat rate differ by traffic source and country?")

# The rows the Agent's queries returned, as stored (theLook, 2026-10-01).
COHORTS = (["cohort_month", "total_first_time_customers", "repeat_customers", "repeat_rate"],
           [["2025-01-01", "1238", "86", "0.06946688206785137"],
            ["2025-02-01", "1214", "106", "0.08731466227347612"],
            ["2025-12-01", "1823", "220", "0.12068019747668678"]])
SOURCES = (["traffic_source", "total_first_time_customers", "repeat_customers", "repeat_rate"],
           [["Email", "901", "106", "0.11764705882352941"],
            ["Facebook", "1082", "105", "0.09704251386321626"],
            ["Search", "12351", "1157", "0.09367662537446361"]])
CENTRES = (["distribution_center", "avg_hours_to_ship", "avg_hours_to_deliver", "order_count"],
           [["Port Authority of New York/New Jersey NY/NJ", "34.88826815642459", "61.7932960893855", "179"],
            ["Philadelphia PA", "34.17412935323385", "61.79104477611939", "201"]])


# ── A result is titled by what it measures and what it is cut by ──────────────────────

def test_a_rate_beside_its_own_parts_titles_the_result():
    assert _adhoc_title(*COHORTS[:1], QUESTION, "", COHORTS[1]) == "repeat_rate by cohort_month"
    assert _adhoc_title(*SOURCES[:1], QUESTION, "", SOURCES[1]) == "repeat_rate by traffic_source"


def test_an_average_stands_for_the_count_it_was_taken_over():
    assert (_adhoc_title(*CENTRES[:1], "q", "", CENTRES[1])
            == "avg_hours_to_ship and avg_hours_to_deliver by distribution_center")


def test_two_measures_on_one_row_are_both_named():
    """The fulfilment answer's overall row (2026-10-01) was titled "overall_avg_shipped_to_delivered_days by
    overall_avg_placed_to_shipped_days" — one measure cut by the other."""
    cols = ["overall_avg_placed_to_shipped_days", "overall_avg_shipped_to_delivered_days"]
    assert _adhoc_title(cols, "q", "", [["1.4981", "2.4970"]]) == (
        "overall_avg_placed_to_shipped_days and overall_avg_shipped_to_delivered_days")
    # a cut still reads "measure by cut" — on one row, and a number down many rows is the cut
    assert _adhoc_title(["category", "revenue"], "q", "", [["Jeans", "220935.5"]]) == "revenue by category"
    assert _adhoc_title(["age", "users"], "q", "", [["30", "120"], ["31", "95"]]) == "users by age"


def test_a_rate_whose_parts_do_not_divide_into_it_is_one_measure_among_others():
    rows = [["Email", "901", "106", "0.2"], ["Search", "12351", "1157", "0.3"]]
    assert _adhoc_title(SOURCES[0], "q", "", rows) == (
        "total_first_time_customers, repeat_customers and repeat_rate by traffic_source")


def test_a_rate_written_as_a_rounded_percentage_still_finds_its_parts():
    cols = ["country", "customers", "repeaters", "repeat_pct"]
    rows = [["Belgium", "233", "25", "10.7"], ["Australia", "406", "30", "7.4"]]
    assert _adhoc_title(cols, "q", "", rows) == "repeat_pct by country"
    rows[1][3] = "7.6"                                  # 7.39 is not 7.6 at one decimal
    assert _adhoc_title(cols, "q", "", rows).startswith("customers, repeaters and repeat_pct")


def test_the_scope_still_rides_and_rows_that_say_nothing_keep_the_question():
    sql = "SELECT … FROM orders WHERE created_at >= '2025-01-01' AND created_at < '2026-01-01'"
    assert _adhoc_title(*COHORTS[:1], QUESTION, sql, COHORTS[1]) == (
        "repeat_rate by cohort_month — 2025-01-01 → 2026-01-01")
    assert _adhoc_title(*COHORTS[:1], QUESTION, "", None) == QUESTION[:80]


COUNTRIES = (["country", "total_first_orders", "repeat_customers", "repeat_rate"],
             [["Colombia", "2", "1", "0.5"], ["Poland", "49", "6", "0.12244897959183673"],
              ["Spain", "722", "60", "0.08310249307479224"]])


def test_the_groups_too_small_to_compare_are_counted_and_handed_to_the_analyst():
    """The repeat-rate answer of 2026-10-01 said "many groups represent small sample sizes" where one country of
    thirteen (Colombia, two first-time buyers) and no traffic source was."""
    from aughor.agent.analyst import AnalystTurn, _record_evidence, _too_few_to_compare
    assert _too_few_to_compare(*COUNTRIES) == {"Colombia": 2}               # Poland's 49 compares
    assert _too_few_to_compare(*SOURCES) == {}
    all_small = [COUNTRIES[1][0], ["Peru", "3", "1", "0.3333333333333333"]]
    assert _too_few_to_compare(COUNTRIES[0], all_small) == {}               # nothing larger to compare with
    unparted = [r[:3] + ["0.2"] for r in COUNTRIES[1]]                      # a rate its columns do not make
    assert _too_few_to_compare(COUNTRIES[0], unparted) == {}
    turn = AnalystTurn(connection_id="c", conn=None, state={"question": QUESTION, "investigation_phases": []})
    out = _record_evidence(turn, {"sql": "SELECT 1"}, {"columns": COUNTRIES[0], "rows": COUNTRIES[1], "row_count": 3})
    assert out.get("too_few") == {"Colombia": 2}                            # read by the model with the rows
    from aughor.agent.analyst import analyst_system_prompt
    rule = analyst_system_prompt("c", {}, 10, shape="describe")
    assert "under `too_few`" in rule and "call no other group small" in rule


def test_the_analyst_records_one_title_for_the_phase_and_its_finding():
    from aughor.agent.analyst import AnalystTurn, _record_evidence
    turn = AnalystTurn(connection_id="c", conn=None, state={"question": QUESTION, "investigation_phases": []})
    _record_evidence(turn, {"sql": "SELECT 1"}, {"columns": COHORTS[0], "rows": COHORTS[1], "row_count": 3})
    phase = turn.state["investigation_phases"][-1]
    assert phase["phase_name"] == phase["findings"][0]["title"] == "repeat_rate by cohort_month"


# ── The PDF prints the answer as it is written, and a title once ──────────────────────

SUMMARY = (
    "### 90-Day Repeat Rate by Cohort Month (2025)\n"
    "| Cohort Month | First-Time Customers | Repeat Customers | Repeat Rate |\n"
    "| :--- | :--- | :--- | :--- |\n"
    "| 2025-01-01 | 1,238 | 86 | 6.9% |\n"
    "| 2025-12-01 | 1,823 | 220 | 12.1% |\n"
    "\n"
    "### Repeat Rate by Traffic Source and Country\n"
    "The repeat rate varies by acquisition channel and geography. Customers acquired via Email "
    "showed the highest repeat rate (11.8%).\n"
    "\n"
    "By Traffic Source:\n"
    "*   Email: 11.8%\n"
    "*   Display: 8.0%\n"
    "\n"
    "*Note: The repeat rate is the share of first-time customers who ordered again within 90 days.*")


def test_the_summary_prints_its_headings_table_and_lists_as_such():
    from aughor.export.document import _summary_blocks
    blocks = _summary_blocks(SUMMARY)
    assert [b.kind for b in blocks] == ["prose", "table", "prose", "prose", "prose", "bullets", "prose"]
    assert blocks[0].text == "**90-Day Repeat Rate by Cohort Month (2025)**"
    assert blocks[1].columns == ["Cohort Month", "First-Time Customers", "Repeat Customers", "Repeat Rate"]
    assert blocks[1].rows == [["2025-01-01", "1,238", "86", "6.9%"], ["2025-12-01", "1,823", "220", "12.1%"]]
    assert blocks[5].items == ["Email: 11.8%", "Display: 8.0%"]
    assert blocks[6].text.startswith("Note: The repeat rate") and "*" not in blocks[6].text
    assert not any("|" in b.text or "###" in b.text for b in blocks)


def test_a_summary_written_as_prose_is_the_one_block_it_was():
    from aughor.export.document import _p, _summary_blocks
    text = "Load factors trail short-haul by 2.7 points.\n\nThe gap is **widest** on Mondays."
    assert _summary_blocks(text) == [_p(text)]


def _agent_report(monkeypatch):
    """The repeat-rate report as stored: each result's phase, finding and chart share a title."""
    import aughor.export.document as D
    drawn: list = []
    monkeypatch.setattr(D, "render_chart_svg", lambda c, r, t, title, **k: drawn.append(title) or "<svg/>")
    monkeypatch.setattr(D, "svg_to_png", lambda svg: None)
    title = QUESTION[:80]
    inv = {"question": QUESTION, "connection_id": "c", "completed_at": "2026-10-01T00:20:32Z",
           "report": {"_report_type": "investigate", "headline": "h", "executive_summary": SUMMARY,
                      "confidence": "HIGH", "recommendations": [], "data_gaps": [],
                      "phases": [{"phase_id": "adhoc_2", "phase_name": title, "status": "complete",
                                  "summary": "", "findings": [{"title": title, "columns": COHORTS[0],
                                                               "rows": COHORTS[1], "chart_type": "auto",
                                                               "interpretation": "", "key_numbers": []}]}]}}
    return D.build_export_doc(inv), drawn, title


def test_a_results_title_is_printed_once(monkeypatch):
    doc, drawn, title = _agent_report(monkeypatch)
    printed = [b.text for b in doc.blocks if b.kind == "heading"] + \
              [b.caption for b in doc.blocks if b.kind == "finding"] + drawn
    assert printed.count(title) == 1                     # the section heading; not the caption, not the figure
    chart = next(b for b in doc.blocks if b.kind == "chart")
    assert chart.caption == title                        # a slide still titles its chart with it


def test_a_finding_that_says_something_else_keeps_its_caption_and_its_figure_title(monkeypatch):
    import aughor.export.document as D
    drawn: list = []
    monkeypatch.setattr(D, "render_chart_svg", lambda c, r, t, title, **k: drawn.append(title) or "<svg/>")
    monkeypatch.setattr(D, "svg_to_png", lambda svg: None)
    inv = {"question": "q", "report": {"phases": [{"phase_id": "cross_section", "phase_name": "Where value is weakest",
           "status": "complete", "findings": [{"claim": "Long-haul trails by 2.7 points", "title": "Load factor by haul",
           "columns": ["haul", "load"], "rows": [["long", 74.5], ["short", 77.2]], "chart_type": "bar"}]}]}}
    doc = D.build_export_doc(inv)
    assert [b.caption for b in doc.blocks if b.kind == "finding"] == ["Long-haul trails by 2.7 points"]
    assert drawn == ["Load factor by haul"]


def test_an_ai_summary_replaces_the_whole_written_summary(monkeypatch):
    import aughor.export.document as D
    monkeypatch.setattr(D, "_llm_executive_summary", lambda inv, doc: "The rate rose through 2025.")
    inv = {"question": "q", "report": {"_report_type": "investigate", "executive_summary": SUMMARY,
                                       "metric": "90-day repeat rate", "phases": []}}
    doc = D.build_export_doc(inv, narrate=True)
    assert [(b.kind, b.tag) for b in doc.blocks[:3]] == [
        ("heading", ""), ("prose", "AI executive summary"), ("prose", "At a glance")]


def test_a_result_a_corrected_rerun_replaced_is_not_printed(monkeypatch):
    import aughor.export.document as D
    monkeypatch.setattr(D, "render_chart_svg", lambda *a, **k: "<svg/>")
    monkeypatch.setattr(D, "svg_to_png", lambda svg: None)
    phase = lambda pid, name, **kw: {"phase_id": pid, "phase_name": name, "status": "complete", **kw,  # noqa: E731
                                     "findings": [{"title": name, "columns": CENTRES[0], "rows": CENTRES[1],
                                                   "chart_type": "auto"}]}
    inv = {"question": "q", "report": {"_report_type": "investigate", "phases": [
        phase("adhoc_3", "the re-run"), phase("adhoc_2", "the flagged one", _hidden=True, superseded_by="adhoc_3")]}}
    doc = D.build_export_doc(inv)
    assert [b.text for b in doc.blocks if b.kind == "heading"] == ["the re-run"]
