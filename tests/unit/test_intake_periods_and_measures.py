"""Item 4 — the intake holds every measure asked for, and only the periods asked for.

Measured on the theLook Agent runs of 2026-09-29 and 2026-10-01: four of five questions asked
for two measures and the intake held one (the fulfilment intake put two `AVG(…) AS …` in its one
metric field); "how long does it take an order to go from placed to shipped to delivered"
names no period and was answered for 1 August to 2 September 2026; a 2025 cohort question asks
to compare nothing and was labelled "Full Year 2025 vs Full Year 2024 (YoY)".
"""
from __future__ import annotations

import pytest

import aughor.agent.investigate as I
from aughor.agent.investigate import (_clamp_intake_to_coverage, _comparison_basis, _measures_label,
                                      _metric_definition_receipt, _one_expression_per_measure,
                                      periods_asked, route_after_intake)
from aughor.agent.prompts_investigate import IntakeOutput

Q1 = "What was total revenue and how many units were sold in July 2026?"
Q2 = ("Which 10 product categories brought in the most revenue in the last 6 months, and what is "
      "the average order value for each?")
Q3 = ("How has monthly revenue from completed orders trended over the last 12 months, and which "
      "months grew or shrank the most versus the month before?")
Q4 = ("How long does it take an order to go from placed to shipped to delivered, by distribution "
      "center — and which centers are slowest?")
Q5 = ("Of customers who placed their first order in each month of 2025, what share ordered again "
      "within 90 days — and does that repeat rate differ by traffic source and country?")


# ── What the question says about time ─────────────────────────────────────────────────

def test_the_five_theLook_questions():
    assert periods_asked(Q1) == (True, False)       # July 2026, nothing compared
    assert periods_asked(Q2) == (True, False)       # the last 6 months, nothing compared
    assert periods_asked(Q3) == (True, True)        # "grew or shrank … versus the month before"
    assert periods_asked(Q4) == (False, False)      # no period at all
    assert periods_asked(Q5) == (True, False)       # 2025; "differ by" compares segments, not periods


def test_a_grain_is_not_a_period_and_an_investigation_keeps_both():
    assert periods_asked("What is the monthly order count by status?") == (False, False)
    assert periods_asked("Show me orders by status for May 2026") == (True, False)
    assert periods_asked("Why did revenue drop?") == (True, True)
    assert periods_asked("Where are we losing money?") == (True, True)


# ── One expression per measure ────────────────────────────────────────────────────────

FULFIL_METRIC = ("AVG(TIMESTAMP_DIFF(shipped_at, created_at, HOUR)) AS avg_hours_to_ship, "
                 "AVG(TIMESTAMP_DIFF(delivered_at, shipped_at, HOUR)) AS avg_hours_to_deliver")


def _intake(**kw) -> IntakeOutput:
    base = dict(metric_label="m", metric_sql="SUM(x)", date_column="orders.created_at",
                metric_table="orders", dimensions=[], intake_notes="")
    base.update(kw)
    return IntakeOutput(**base)


def test_two_measures_in_one_field_become_two_kept_verbatim():
    it = _intake(metric_label="average time to ship and deliver", metric_sql=FULFIL_METRIC)
    _one_expression_per_measure(it)
    assert it.metric_sql == "AVG(TIMESTAMP_DIFF(shipped_at, created_at, HOUR))"
    assert it.metric_label == "avg hours to ship"
    assert [(m.label, m.sql) for m in it.other_measures] == [
        ("avg hours to deliver", "AVG(TIMESTAMP_DIFF(delivered_at, shipped_at, HOUR))")]


def test_a_comma_inside_an_expression_splits_nothing():
    for sql in ("SUM(a) / NULLIF(SUM(b), 0)", "COUNT(CASE WHEN status IN ('a', 'b') THEN 1 END)",
                "SUM(CASE WHEN note = 'x, y' THEN 1 ELSE 0 END)"):
        it = _intake(metric_sql=sql)
        _one_expression_per_measure(it)
        assert it.metric_sql == sql and it.other_measures == []


def test_a_parenthesis_inside_a_string_does_not_move_the_split():
    sql = ("SUM(CASE WHEN note = 'late)' THEN 1 ELSE 0 END) AS late, "
           "COUNT(CASE WHEN note = '(early' THEN 1 END) AS early")
    it = _intake(metric_sql=sql)
    _one_expression_per_measure(it)
    assert it.metric_sql == "SUM(CASE WHEN note = 'late)' THEN 1 ELSE 0 END)"
    assert [(m.label, m.sql) for m in it.other_measures] == [("early", "COUNT(CASE WHEN note = '(early' THEN 1 END)")]


def test_the_report_names_and_defines_every_measure():
    it = _intake(metric_label="average time to ship and deliver", metric_sql=FULFIL_METRIC)
    _one_expression_per_measure(it)
    d = it.model_dump()
    assert _measures_label(d) == "avg hours to ship · avg hours to deliver"
    assert "and avg hours to deliver computed as `AVG(TIMESTAMP_DIFF(delivered_at, shipped_at, HOUR))`" \
        in _metric_definition_receipt(d)


# ── No comparison is invented for a question that asks for none ───────────────────────

def test_the_clamp_supplies_no_comparison_the_question_did_not_ask_for():
    it = _intake(observation_start="2025-01-01", observation_end="2025-12-31", observation_label="Full Year 2025",
                 comparison_asked=False)
    note = _clamp_intake_to_coverage(it, "2019-01-09", "2026-09-29", Q5)
    assert (it.comparison_start, it.comparison_end, it.comparison_label) == ("", "", "")
    assert it.no_prior_period is False and not note
    asked = _intake(observation_start="2025-01-01", observation_end="2025-12-31", observation_label="Full Year 2025")
    _clamp_intake_to_coverage(asked, "2019-01-09", "2026-09-29", "Why did revenue fall in 2025?")
    assert asked.comparison_label.startswith("Preceding period")          # asked: unchanged


def test_a_breakdown_with_no_comparison_routes_to_the_breakdown():
    """The phase graph's router (it serves deep turns when the converse door is off)."""
    assert route_after_intake({"_ada_intake": {"comparison_asked": False}}) == "deep_breakdown"
    # a cross-sectional scan, and any question that asks to compare, keep their own routes
    assert route_after_intake({"_ada_intake": {"comparison_asked": False, "cross_sectional": True}}) \
        != "deep_breakdown"
    assert route_after_intake({"_ada_intake": {}}) != "deep_breakdown"


# ── Through the intake, as the live model answered ────────────────────────────────────

class _Model:
    """Answers the way the live intake model did on 2026-10-01."""
    def __init__(self, **answer):
        self.answer = answer

    def complete(self, **kw):
        return IntakeOutput(**{**dict(date_column="orders.created_at", metric_table="orders", dimensions=[],
                                      intake_notes=""), **self.answer})


class _Grounding:
    trusted_used: list = []

    def grounding_block(self):
        return ""


@pytest.fixture
def run(monkeypatch):
    import aughor.agent.explore as ex
    import aughor.semantic.data_understanding as du
    monkeypatch.setattr(ex, "build_analysis_ledger", lambda state: "")
    monkeypatch.setattr(du, "build_data_understanding", lambda *a, **k: _Grounding())
    monkeypatch.setattr(I, "_measure_date_span", lambda *a, **k: ("2019-01-09", "2026-09-29"))

    def _run(question, **answer):
        monkeypatch.setattr(I, "_provider", lambda role: _Model(**answer))
        state = {"question": question, "schema_context": "TABLE: orders\n  created_at TIMESTAMP\n",
                 "scan_context": "", "connection_id": "", "scope_schema": ""}
        out = I.ada_intake(state, conn=object())
        _run.phase = out["investigation_phases"][0]
        return out["_ada_intake"], out["investigation_phases"][0]["findings"][0]["rows"]
    return _run


def test_a_question_with_no_period_is_answered_over_all_the_data_with_both_measures(run):
    spec, rows = run(Q4, metric_label="average time to ship and deliver", metric_sql=FULFIL_METRIC,
                     observation_start="2026-08-01", observation_end="2026-09-02", observation_label="August 2026",
                     comparison_start="2026-06-29", comparison_end="2026-07-31", comparison_label="Prior 33 days")
    assert spec["period_named"] is False and spec["comparison_asked"] is False
    assert (spec["observation_start"], spec["observation_end"]) == ("2019-01-09", "2026-09-29")
    assert spec["observation_label"] == "All data (2019-01-09 → 2026-09-29)"
    assert spec["comparison_label"] == "" and _comparison_basis(spec) == ""
    assert ["Observation", "All data (2019-01-09 → 2026-09-29)"] in rows
    assert ["Measure", "avg hours to deliver (AVG(TIMESTAMP_DIFF(delivered_at, shipped_at, HOUR)))"] in rows
    assert not any(r[0] == "Comparison" for r in rows)
    from aughor.agent.analyst import _spec_section
    said = _spec_section(spec)
    assert "also asked: avg hours to deliver = AVG(TIMESTAMP_DIFF(delivered_at, shipped_at, HOUR))" in said
    assert "comparison: none — the question asks to compare no periods" in said
    assert "2026-08-01" not in said


def test_a_named_period_stays_and_an_unasked_comparison_goes(run):
    spec, rows = run(Q5, metric_label="90-day repeat rate", metric_sql="COUNT(DISTINCT r) / COUNT(DISTINCT c)",
                     observation_start="2025-01-01", observation_end="2025-12-31", observation_label="Full Year 2025",
                     comparison_start="2024-01-01", comparison_end="2024-12-31",
                     comparison_label="Full Year 2024 (YoY)", yoy_start="2024-01-01", yoy_end="2024-12-31")
    assert (spec["observation_start"], spec["observation_end"]) == ("2025-01-01", "2025-12-31")
    assert spec["comparison_label"] == "" and spec["yoy_start"] is None
    assert _comparison_basis(spec) == ""                       # the page no longer reads "vs Full Year 2024"
    assert not any(r[0] == "Comparison" for r in rows)


def test_a_question_that_asks_for_a_comparison_keeps_it(run):
    spec, rows = run(Q3, metric_label="revenue", metric_sql="SUM(sale_price)",
                     observation_start="2025-09-01", observation_end="2026-08-31", observation_label="Last 12 months",
                     comparison_start="2024-09-01", comparison_end="2025-08-31", comparison_label="Prior 12 months")
    assert spec["comparison_asked"] is True and spec["comparison_label"] == "Prior 12 months"
    assert any(r[0] == "Comparison" for r in rows)


def test_the_incomplete_month_note_is_for_an_answer_read_period_by_period(run, monkeypatch):
    """Q2 (2026-10-03) ranked ten categories over six months ending on 4 September by design, and its period
    line said "September 2026 may be incomplete". A question that cuts by month, or compares periods, keeps it."""
    monkeypatch.setattr(I, "_monthly_counts", lambda *a, **k: [("2026-07", 30), ("2026-08", 32), ("2026-09", 5)])
    window = dict(metric_label="revenue", metric_sql="SUM(sale_price)", observation_start="2026-03-05",
                  observation_end="2026-09-04", observation_label="Last 6 months")
    assert "may be incomplete" not in run(Q2, **window)[0]["observation_label"]
    for asked in ("What was monthly revenue over the last 6 months?", "How did revenue change over the last 6 months?"):
        assert run(asked, **window)[0]["observation_label"].endswith("September 2026 may be incomplete"), asked


def test_with_no_coverage_measured_the_invented_window_still_goes(run, monkeypatch):
    """The all-data window needs the data's span; without it the model's window must not
    survive in its place."""
    monkeypatch.setattr(I, "_measure_date_span", lambda *a, **k: ("", ""))
    spec, rows = run(Q4, metric_label="average days to ship", metric_sql="AVG(x)",
                     observation_start="2026-08-01", observation_end="2026-09-02", observation_label="August 2026")
    assert (spec["observation_start"], spec["observation_end"], spec["observation_label"]) == ("", "", "")
    from aughor.agent.analyst import _spec_section
    assert "observation: all the data — the question names no period." in _spec_section(spec)


def test_a_question_that_asks_to_see_the_groups_is_not_described_as_a_weakness_scan(run):
    """Q4's spec (2026-10-01) read "rank the metric across dimensions to find where value is weakest, and trend it
    … to see whether the weakness is growing" — for a question asking how long each centre takes."""
    spec, rows = run(Q4, metric_label="average days to ship", metric_sql="AVG(x)", cross_sectional=True)
    assert spec["cross_sectional"] is True
    assert ["Approach", "Cross-sectional — measure each group the question names, side by side"] in rows
    assert run.phase["summary"] == "Measuring average days to ship for each group the question names."
    spec, rows = run("Where are we losing money on orders?", metric_label="margin", metric_sql="SUM(x)",
                     cross_sectional=True)
    assert next(r[1] for r in rows if r[0] == "Approach").startswith(
        "Cross-sectional — rank the metric across dimensions to find where value is weakest")
    assert "where value is weakest" in run.phase["summary"]


def test_a_window_dated_but_not_named_is_named_from_its_dates(run):
    """The Q5 re-run of 2026-10-01: 2025's dates, no label — and a blank period on the report."""
    spec, rows = run(Q5, metric_label="90-day repeat rate", metric_sql="COUNT(DISTINCT r) / COUNT(DISTINCT c)",
                     observation_start="2025-01-01", observation_end="2025-12-31", observation_label="")
    assert spec["observation_label"] == "January–December 2025"
    assert ["Observation", "January–December 2025 (2025-01-01 → 2025-12-31)"] in rows


# ── Each further measure follows its governed definition (2026-10-02) ─────────────────

def test_a_further_measure_follows_its_governed_definition_and_cogs_is_no_count(monkeypatch):
    """theLook, 2026-10-02: "how many units were sold in July" counted the order lines July's revenue was measured
    on (6,012); the declared units_sold counts inventory items by the day they sold (7,027). The user's decision:
    units sold follows the declared metric. And the matcher that took "cost of goods sold" for units_sold on the
    word "sold" must not now reach a further measure."""
    from types import SimpleNamespace
    from aughor.agent.analyst import _spec_section
    from aughor.agent.prompts_investigate import IntakeMeasure
    units = SimpleNamespace(name="units_sold", label="Units Sold", sql="COUNT(id)", tables=["inventory_items"],
                            filters=["sold_at IS NOT NULL"], rank=1)
    monkeypatch.setattr("aughor.semantic.canonical.resolve_planning_metrics", lambda *a, **k: [units])
    monkeypatch.setattr("aughor.semantic.metrics.get_metric", lambda name, **k: SimpleNamespace(time_column="sold_at"))
    monkeypatch.setattr(I, "_pinned_metric_runs", lambda conn, cid, table, sql: table == "inventory_items")
    it = _intake(metric_label="total revenue", metric_sql="SUM(sale_price)", metric_table="order_items")
    it.other_measures = [IntakeMeasure(label="units sold", sql="COUNT(*)"),
                         IntakeMeasure(label="cost of goods sold", sql="SUM(cost)")]
    notes = I._pin_other_measures(it, "c", "", None)
    assert [m.sql for m in it.other_measures] == ["COUNT(id)", "SUM(cost)"]
    assert it.measure_definitions == [{"label": "units sold", "metric": "units_sold", "table": "inventory_items",
                                       "date_column": "sold_at", "filters": ["sold_at IS NOT NULL"]}]
    assert notes == ["units sold is the governed units_sold: COUNT(id) on inventory_items, dated by sold_at, "
                     "over rows where sold_at IS NOT NULL."]
    d = it.model_dump()
    assert ("also asked: units sold = COUNT(id) — the governed units_sold on inventory_items, dated by sold_at, "
            "over rows where sold_at IS NOT NULL; measure it on that table, by that date, in a query of its own"
            in _spec_section(d))
    assert ("and units sold computed as `COUNT(id)` — the governed units_sold on inventory_items, dated by sold_at"
            in I._metric_definition_receipt(d))


def test_the_intake_ties_its_further_measures_and_says_so_in_the_spec(run, monkeypatch):
    from types import SimpleNamespace
    units = SimpleNamespace(name="units_sold", label="Units Sold", sql="COUNT(id)", tables=["inventory_items"],
                            filters=["sold_at IS NOT NULL"], rank=1)
    monkeypatch.setattr("aughor.semantic.canonical.resolve_planning_metrics", lambda *a, **k: [units])
    monkeypatch.setattr("aughor.semantic.metrics.get_metric", lambda name, **k: SimpleNamespace(time_column="sold_at"))
    monkeypatch.setattr(I, "_pinned_metric_runs", lambda conn, cid, table, sql: table == "inventory_items")
    spec, rows = run(Q1, metric_label="total revenue", metric_sql="SUM(sale_price)",
                     other_measures=[{"label": "units sold", "sql": "COUNT(*)"}],
                     observation_start="2026-07-01", observation_end="2026-07-31", observation_label="July 2026")
    assert ["Measure", "units sold (COUNT(id)) — the governed units_sold on inventory_items, dated by sold_at, "
                       "over rows where sold_at IS NOT NULL"] in rows
    assert spec["measure_definitions"][0]["date_column"] == "sold_at"


def test_columns_that_identify_people_are_not_offered_as_dimensions(monkeypatch):
    """Q5's intake (2026-10-01) offered `users.email` to group by: a cut by it lists customers one row each."""
    from types import SimpleNamespace
    from aughor.agent import investigate as I
    from aughor.tools import profile_cache
    monkeypatch.setattr(profile_cache, "load_concepts", lambda conn: {("users", "contact"): "contact.email"})
    intake = SimpleNamespace(intake_notes="", dimensions=[
        "users.email", "users.country", "users.traffic_source", "users.first_name", "users.contact",
        "orders.status", "users.user_email", "products.brand"])
    assert I._drop_identifying_dimensions(intake, "c") == ["users.email", "users.first_name", "users.contact",
                                                          "users.user_email"]
    assert intake.dimensions == ["users.country", "users.traffic_source", "orders.status", "products.brand"]
    assert intake.intake_notes.startswith("NOT OFFERED AS DIMENSIONS: users.email")
    assert I._drop_identifying_dimensions(SimpleNamespace(intake_notes="", dimensions=["users.state"]), "") == []
    # a flag or a domain is a cut, not a person
    kept = SimpleNamespace(intake_notes="", dimensions=["events.is_mobile", "users.email_opt_in", "users.email_domain",
                                                        "users.phone_number", "users.mobile"])
    assert I._drop_identifying_dimensions(kept, "") == ["users.phone_number", "users.mobile"]
