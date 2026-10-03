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
    assert _adhoc_title(*COHORTS[:1], QUESTION, "", COHORTS[1]) == "Repeat rate by cohort month"
    assert _adhoc_title(*SOURCES[:1], QUESTION, "", SOURCES[1]) == "Repeat rate by traffic source"


def test_an_average_stands_for_the_count_it_was_taken_over():
    assert (_adhoc_title(*CENTRES[:1], "q", "", CENTRES[1])
            == "Avg hours to ship and avg hours to deliver by distribution center")


def test_two_measures_on_one_row_are_both_named():
    """The fulfilment answer's overall row (2026-10-01) was titled "overall_avg_shipped_to_delivered_days by
    overall_avg_placed_to_shipped_days" — one measure cut by the other."""
    cols = ["overall_avg_placed_to_shipped_days", "overall_avg_shipped_to_delivered_days"]
    assert _adhoc_title(cols, "q", "", [["1.4981", "2.4970"]]) == (
        "Overall avg placed to shipped days and overall avg shipped to delivered days")
    # a cut still reads "measure by cut" — on one row, and a number down many rows is the cut
    assert _adhoc_title(["category", "revenue"], "q", "", [["Jeans", "220935.5"]]) == "Revenue by category"
    assert _adhoc_title(["age", "users"], "q", "", [["30", "120"], ["31", "95"]]) == "Users by age"


def test_a_rate_whose_parts_do_not_divide_into_it_is_one_measure_among_others():
    rows = [["Email", "901", "106", "0.2"], ["Search", "12351", "1157", "0.3"]]
    assert _adhoc_title(SOURCES[0], "q", "", rows) == (
        "Total first time customers, repeat customers and repeat rate by traffic source")


def test_a_rate_written_as_a_rounded_percentage_still_finds_its_parts():
    cols = ["country", "customers", "repeaters", "repeat_pct"]
    rows = [["Belgium", "233", "25", "10.7"], ["Australia", "406", "30", "7.4"]]
    assert _adhoc_title(cols, "q", "", rows) == "Repeat pct by country"
    rows[1][3] = "7.6"                                  # 7.39 is not 7.6 at one decimal
    assert _adhoc_title(cols, "q", "", rows).startswith("Customers, repeaters and repeat pct")


def test_the_scope_still_rides_and_rows_that_say_nothing_keep_the_question():
    sql = "SELECT … FROM orders WHERE created_at >= '2025-01-01' AND created_at < '2026-01-01'"
    assert _adhoc_title(*COHORTS[:1], QUESTION, sql, COHORTS[1]) == (
        "Repeat rate by cohort month — 2025")      # `< 2026-01-01` ends on 12-31: the whole year
    assert _adhoc_title(*COHORTS[:1], QUESTION, "", None) == QUESTION[:80]


# ── A title says the rows its result is over (2026-10-02) ─────────────────────────────

JULY = "created_at >= '2026-07-01' AND created_at < '2026-08-01'"
LINES = "SELECT SUM(sale_price) AS total_revenue, COUNT(id) AS units_sold FROM order_items WHERE "
TOTALS = ["total_revenue", "units_sold"]
ONE_ROW = [["359224.30043935776", "6012"]]


def test_a_window_ends_on_the_last_day_it_includes():
    """July was titled "2026-07-01 → 2026-08-01", and Q2's chart "→ 2026-09-04" under a label that
    said its period ended on 09-03 — the half-open bound printed as the end."""
    def title(where: str) -> str:
        return _adhoc_title(TOTALS, "q", LINES + where, ONE_ROW)
    assert title(JULY) == "Total revenue and units sold — Jul 2026"
    assert title("created_at >= '2026-07-01' AND created_at <= '2026-07-31'").endswith("— Jul 2026")
    assert title("created_at >= TIMESTAMP '2026-07-01' AND created_at < TIMESTAMP '2026-08-01 00:00:00'"
                 ).endswith("— Jul 2026")
    # a bound that is not the start of a day keeps part of that day
    assert title("created_at >= '2026-07-01' AND created_at < '2026-08-01 12:00:00'").endswith("— 1 Jul – 1 Aug 2026")
    assert title("created_at >= '2026-07-01' AND created_at < '2026-07-02'").endswith("— 1 Jul 2026")
    # an observation and its comparison read as the span they cover, earliest first
    assert title("(created_at >= '2026-07-01' AND created_at < '2026-08-01') OR "
                 "(created_at >= '2026-06-01' AND created_at < '2026-07-01')").endswith("— Jun – Jul 2026")


def test_three_results_over_different_rows_get_three_titles():
    """July's cancelled lines, the rest, and the completed ones — titled alike, they read as one figure
    three times (59,704.10, 359,224.30, 418,928.40 under one title, theLook 2026-10-02). Revenue's own
    declared filter is part of revenue, so it is not repeated in the title."""
    declared = ["status <> 'Cancelled'"]
    titles = [_adhoc_title(TOTALS, "q", f"{LINES}{JULY} AND {cond}", ONE_ROW, declared=declared,
                           dialect="bigquery")
              for cond in ("status = 'Cancelled'", "status != 'Cancelled'", "status = 'Complete'")]
    assert titles == ["Total revenue and units sold where status = Cancelled — Jul 2026",
                      "Total revenue and units sold — Jul 2026",
                      "Total revenue and units sold where status = Complete — Jul 2026"]
    # with no metric declaring it, the exclusion is the query's own and is named
    assert _adhoc_title(TOTALS, "q", f"{LINES}{JULY} AND status != 'Cancelled'", ONE_ROW) == (
        "Total revenue and units sold where status ≠ Cancelled — Jul 2026")


def test_a_title_names_lists_and_exclusions_from_the_where_alone():
    cols, rows = ["category", "revenue"], [["Jeans", "1"], ["Swim", "2"]]
    sql = ("SELECT category, SUM(CASE WHEN status = 'Returned' THEN sale_price END) AS revenue FROM t "
           "WHERE status IN ('Complete', 'Shipped') AND country NOT IN ('Spain') "
           "AND order_month = '2026-07-01' GROUP BY 1")
    assert _adhoc_title(cols, "q", sql, rows) == (
        "Revenue by category where status in Complete, Shipped, country not in Spain")
    many = "SELECT category, SUM(x) AS revenue FROM t WHERE status IN ('A', 'B', 'C', 'D') GROUP BY 1"
    assert _adhoc_title(cols, "q", many, rows) == "Revenue by category where status in A, B, C and 1 more"


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


MONTHLY = (["month", "monthly_revenue", "revenue_change", "pct_change"],
           [["2026-07-01", "109975.57", "17173.15", "18.5"], ["2025-10-01", "58007.77", "7463.84", "14.77"],
            ["2025-12-01", "59989.80", "-4261.90", "-6.63"], ["2025-09-01", "50543.93", "NULL", "NULL"]])


def test_the_first_period_s_missing_change_is_named_to_the_analyst():
    """2026-10-02: each month's change was taken inside the twelve months asked; September 2025's came back empty,
    and the answer called December "the only decline" when September had fallen 9.7% against August."""
    from aughor.agent.analyst import AnalystTurn, _first_change_missing, _record_evidence, analyst_system_prompt
    first = {"period": "2025-09-01", "columns": ["revenue_change", "pct_change"]}
    assert _first_change_missing(*MONTHLY, "2025-09-01") == first
    with_base = (MONTHLY[0], [r if r[0] != "2025-09-01" else ["2025-09-01", "50543.93", "-5421.84", "-9.69"]
                              for r in MONTHLY[1]] + [["2025-08-01", "55965.77", "NULL", "NULL"]])
    assert _first_change_missing(*with_base, "2025-09-01") == {}          # the month before was read too
    assert _first_change_missing(*MONTHLY, "") == {}                      # no window asked
    noted = (MONTHLY[0] + ["note"], [r + ([""] if r[0] == "2025-09-01" else ["promo"]) for r in MONTHLY[1]])
    assert _first_change_missing(*noted, "2025-09-01") == first           # a word missing is no change missing
    turn = AnalystTurn(connection_id="c", conn=None, state={"question": "q", "investigation_phases": [],
                                                            "_ada_intake": {"observation_start": "2025-09-01"}})
    out = _record_evidence(turn, {"sql": "SELECT 1"}, {"columns": MONTHLY[0], "rows": MONTHLY[1], "row_count": 4})
    assert out.get("first_change_missing") == first                       # read by the model with the rows
    assert "`first_change_missing`" in analyst_system_prompt("c", {}, 10, shape="describe")


def test_the_analyst_records_one_title_for_the_phase_and_its_finding():
    from aughor.agent.analyst import AnalystTurn, _record_evidence
    turn = AnalystTurn(connection_id="c", conn=None, state={"question": QUESTION, "investigation_phases": []})
    _record_evidence(turn, {"sql": "SELECT 1"}, {"columns": COHORTS[0], "rows": COHORTS[1], "row_count": 3})
    phase = turn.state["investigation_phases"][-1]
    assert phase["phase_name"] == phase["findings"][0]["title"] == "Repeat rate by cohort month"


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


def test_a_title_is_written_in_words_a_reader_reads():
    """"units_sold — 2026-07-01 → 2026-07-31" titled Q1's figure and its source (2026-10-02): column
    names are for SQL, and a reader says a period, not its first and last ISO days."""
    from aughor.agent.analyst import _window_words, _words
    assert _words("units_sold") == "units sold" and _words("avg_aov_usd") == "avg AOV USD"
    assert [_window_words(w) for w in ("2026-07-01 → 2026-07-31", "2025-08-01 → 2026-08-31",
                                       "2025-01-01 → 2025-12-31", "2026-03-04 → 2026-09-03",
                                       "2026-07-01 → 2026-07-15", "2025-12-15 → 2026-01-14",
                                       "2026-07-01", "not a window")] == [
        "Jul 2026", "Aug 2025 – Aug 2026", "2025", "4 Mar – 3 Sep 2026",
        "1–15 Jul 2026", "15 Dec 2025 – 14 Jan 2026", "1 Jul 2026", "not a window"]


def test_a_cell_written_null_is_empty_not_a_cut():
    """Q3's change result (2026-10-03) carried "NULL" on its first row; its two measures were titled as what
    the result was cut by — "Monthly revenue by month, prev month revenue and revenue change"."""
    cols = ["month", "monthly_revenue", "prev_month_revenue", "revenue_change"]
    rows = [["2025-08-01", "55965.77", "NULL", "NULL"],
            ["2025-09-01", "50543.93", "55965.77", "-5421.84"],
            ["2025-10-01", "58007.77", "50543.93", "7463.84"]]
    sql = ("WITH m AS (SELECT DATE_TRUNC(DATE(o.created_at), MONTH) AS month, SUM(oi.sale_price) AS monthly_revenue "
           "FROM orders AS o JOIN order_items AS oi ON o.order_id = oi.order_id WHERE o.status = 'Complete' "
           "AND o.created_at >= '2025-08-01' AND o.created_at < '2026-09-01' GROUP BY 1) "
           "SELECT month, monthly_revenue, LAG(monthly_revenue) OVER (ORDER BY month) AS prev_month_revenue, "
           "monthly_revenue - LAG(monthly_revenue) OVER (ORDER BY month) AS revenue_change FROM m ORDER BY month")
    assert _adhoc_title(cols, "q", sql, rows, dialect="bigquery") == (
        "Monthly revenue, prev month revenue and revenue change by month where status = Complete — Aug 2025 – Aug 2026")
