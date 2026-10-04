"""Every SQL-writing prompt names the engine and the clock, and hands a window over as a
half-open filter.

Measured 2026-09-29 on five Agent-mode runs (theLook, BigQuery), prompts captured: none
named the engine, the date or how far the data runs. The intake placed "last 6 months" in
2024; the analyst wrote ``<= '2026-07-31'`` on a TIMESTAMP column and lost the day; with
an empty intake it anchored on CURRENT_DATE into a month still filling; the ledger wrote
Postgres for BigQuery and every planned query needed a repair; the writer scheduled a
recommendation for a quarter nine months gone.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from aughor.agent import sql_context as C


class _Native:
    dialect = "bigquery"
    writes_native_sql = True


class _Translated:
    dialect = "postgres"
    writes_native_sql = False


# ── The block ─────────────────────────────────────────────────────────────────────────

def test_the_engine_is_named_as_the_statement_must_be_written():
    assert C.engine_dialect(_Native()) == "bigquery"
    assert C.engine_dialect(_Translated()) == "duckdb"        # the door translates from DuckDB
    assert C.engine_dialect(None) == ""
    block = C.sql_context(_Native(), today="2026-09-30", coverage_end="2026-10-02")
    assert block.startswith("SQL DIALECT: BigQuery (GoogleSQL) — write every statement for this engine")
    assert "TODAY: 2026-09-30 (UTC)." in block
    assert "The data runs to 2026-10-02; its last SETTLED day is 2026-09-29" in block
    assert "CURRENT_DATE" in block and "counts back from the settled day" in block


def test_no_engine_known_means_no_engine_line_and_still_a_clock():
    block = C.sql_context(None, today="2026-09-30")
    assert "SQL DIALECT" not in block
    assert block.startswith("TODAY: 2026-09-30 (UTC). The last settled day is 2026-09-29.")


@pytest.mark.parametrize("today, end, settle, expected", [
    ("2026-09-30", "2026-10-02", 1, "2026-09-29"),   # live data reaches past today: yesterday
    ("2026-09-30", "2026-10-02", 3, "2026-09-27"),   # a source that restates three days
    ("2026-09-30", "2024-12-31", 1, "2024-12-31"),   # a closed dataset: its own last day
    ("2026-09-30", "", 1, "2026-09-29"),             # coverage unknown: the clock alone
    ("garbage", "2024-12-31", 1, "2024-12-31"),      # an unreadable date never raises
])
def test_the_settled_day(today, end, settle, expected):
    assert C.settled_day(today, end, settle) == expected


# ── The window ────────────────────────────────────────────────────────────────────────

def test_a_window_is_a_half_open_filter_with_quoted_dates():
    assert C.window_filter("created_at", "2026-07-01", "2026-07-31") == \
        "created_at >= '2026-07-01' AND created_at < '2026-08-01'"
    assert C.window_filter("order_items.created_at", "2026-03-02", "2026-08-31") == \
        "order_items.created_at >= '2026-03-02' AND order_items.created_at < '2026-09-01'"
    assert C.window_filter("t.d", "2025-12-01", "2025-12-31") == "t.d >= '2025-12-01' AND t.d < '2026-01-01'"


@pytest.mark.parametrize("col, s, e", [("", "2026-07-01", "2026-07-31"), ("c", "", "2026-07-31"),
                                       ("c", "2026-07-01", ""), ("c", "2026-07-01", "not a date")])
def test_an_incomplete_window_makes_no_filter(col, s, e):
    assert C.window_filter(col, s, e) == ""


def test_window_text_says_inclusive_dates_and_the_filter():
    assert C.window_text("July 2026", "2026-07-01", "2026-07-31", "created_at") == \
        "July 2026 (2026-07-01 to 2026-07-31 inclusive) — filter: created_at >= '2026-07-01' AND created_at < '2026-08-01'"
    assert C.window_text("July 2026", "2026-07-01", "2026-07-31") == "July 2026 (2026-07-01 to 2026-07-31 inclusive)"
    assert C.window_text("the observation period", "", "") == "the observation period"


# ── Where it reaches ──────────────────────────────────────────────────────────────────

INTAKE = {"metric_label": "revenue", "metric_sql": "SUM(sale_price)", "metric_table": "order_items",
          "date_column": "order_items.created_at", "observation_label": "July 2026",
          "observation_start": "2026-07-01", "observation_end": "2026-07-31",
          "comparison_label": "June 2026 (MoM)", "comparison_start": "2026-06-01",
          "comparison_end": "2026-06-30", "dimensions": [],
          "sql_context": "SQL DIALECT: BigQuery (GoogleSQL) — x\nTODAY: 2026-09-30 (UTC). y"}


def test_the_analyst_is_told_the_engine_the_clock_and_each_window_as_a_filter():
    from aughor.agent.analyst import analyst_system_prompt
    prompt = analyst_system_prompt("8233e4fd", INTAKE, 24)
    assert "SQL DIALECT: BigQuery (GoogleSQL)" in prompt and "TODAY: 2026-09-30 (UTC)." in prompt
    assert ("  observation: July 2026 (2026-07-01 to 2026-07-31 inclusive) — filter: "
            "order_items.created_at >= '2026-07-01' AND order_items.created_at < '2026-08-01'") in prompt
    assert ("  comparison: June 2026 (MoM) (2026-06-01 to 2026-06-30 inclusive) — filter: "
            "order_items.created_at >= '2026-06-01' AND order_items.created_at < '2026-07-01'") in prompt


def test_an_analyst_with_no_spec_still_knows_the_engine_and_the_date():
    """Q3, 2026-09-29: the intake returned nothing, the analyst got no spec, and with no
    date it anchored on CURRENT_DATE into a month still filling."""
    from aughor.agent.analyst import analyst_system_prompt
    prompt = analyst_system_prompt("8233e4fd", {}, 24, sql_context="SQL DIALECT: BigQuery (GoogleSQL) — x\nTODAY: 2026-09-30 (UTC). y")
    assert "intake produced no spec" in prompt
    assert "SQL DIALECT: BigQuery (GoogleSQL)" in prompt and "TODAY: 2026-09-30" in prompt


def test_the_shared_grounding_shows_a_half_open_window_and_claims_no_engine():
    from aughor.agent.investigate import _ADA_SQL_GROUNDING as G
    assert "orders.order_ts >= '2023-03-10' AND orders.order_ts < '2024-03-10'" in G
    assert "EXCLUSIVE" in G and "DATE '" not in G
    assert "DuckDB" not in G                                    # the SQL DIALECT line says which engine


def test_every_phase_template_writes_each_window_as_a_filter():
    from aughor.agent import prompts_investigate as P
    for name in ("DECOMPOSE_PLAN_PROMPT", "DIMENSIONAL_PLAN_PROMPT", "BEHAVIORAL_PLAN_PROMPT"):
        t = getattr(P, name)
        assert "{obs_filter}" in t and "{comp_filter}" in t, name
    assert "{clock_section}" in P.ADA_SYNTHESIZE_PROMPT
    from aughor.agent.prompts_explore import BUILD_LEDGER_PROMPT
    assert "{sql_context}" in BUILD_LEDGER_PROMPT


def test_the_phase_runner_puts_the_context_on_every_phase_by_construction(monkeypatch):
    """The five callers pass the intake's block; a caller that passes none still gets the
    connection's own — an engine and a date are never left to the model."""
    from aughor.agent import investigate as I
    seen: list[str] = []

    class _Prov:
        def complete(self, *, system, user, response_model=None, **kw):
            seen.append(system)
            return SimpleNamespace(queries=[])
    monkeypatch.setattr(I, "_provider", lambda role="coder": _Prov())
    monkeypatch.setattr(I, "_phase_grounding", lambda *a, **k: "")
    conn = SimpleNamespace(dialect="bigquery", writes_native_sql=True, get_schema=lambda: "")
    I.run_analysis_phase(conn, phase_id="p", title="t", emoji="", plan_system="Write SQL.",
                         plan_user="q", interpret_system="x", interpret_user_fn=lambda t: "x",
                         sql_context="SQL DIALECT: BigQuery (GoogleSQL) — x\nTODAY: 2026-09-30 (UTC). y")
    assert seen and seen[0].endswith("SQL DIALECT: BigQuery (GoogleSQL) — x\nTODAY: 2026-09-30 (UTC). y")
    seen.clear()
    I.run_analysis_phase(conn, phase_id="p", title="t", emoji="", plan_system="Write SQL.",
                         plan_user="q", interpret_system="x", interpret_user_fn=lambda t: "x")
    assert seen and "SQL DIALECT: BigQuery (GoogleSQL)" in seen[0] and "TODAY: " in seen[0]


def test_the_writer_is_told_the_date():
    from aughor.agent.investigate import _clock_section
    line = _clock_section({"data_coverage_end": "2026-10-02"})
    assert line.startswith("TODAY: ") and "AFTER this date" in line and "runs to 2026-10-02" in line
    assert "runs to" not in _clock_section({})


def test_an_empty_intake_reply_is_asked_once_more(monkeypatch):
    """The provider returned no content in 0.6 s twice in five runs. One more ask — not a
    loop — before the run is stopped for want of a spec."""
    from aughor.agent import investigate as I
    from aughor.agent.prompts_investigate import IntakeAsk
    calls: list[str] = []

    class _Prov:
        def complete(self, *, system, user, response_model=None, **kw):
            calls.append(user)
            if len(calls) == 1:
                raise RuntimeError("structured output empty: the model returned no content")
            return IntakeAsk(metric_label="revenue", metric_sql="SUM(sale_price)",
                             observation_start="2026-07-01", observation_end="2026-07-31",
                             observation_label="July 2026", comparison_start="2026-06-01",
                             comparison_end="2026-06-30", comparison_label="June 2026 (MoM)",
                             date_column="order_items.created_at", metric_table="order_items",
                             dimensions=[], intake_notes="")
    monkeypatch.setattr(I, "_provider", lambda role="coder": _Prov())
    monkeypatch.setattr(I, "_measure_date_span", lambda *a, **k: (None, None))
    monkeypatch.setattr("aughor.agent.explore.build_analysis_ledger", lambda *a, **k: "")
    # this source restates its recent days for 29 days (theLook); the intake counts back from
    # the day the platform has learned is settled, not from yesterday
    monkeypatch.setattr("aughor.agent.sql_context.learned_settle_days", lambda cid: 29)
    state = {"question": "What was total revenue in July 2026?", "connection_id": "c1",
             "schema_context": "TABLE: order_items (1 rows) [id INTEGER, sale_price FLOAT, created_at TIMESTAMP]",
             "scan_context": "", "events_context": "", "investigation_phases": []}
    out = I.ada_intake(state, None)
    assert len(calls) == 2 and "TODAY: " in calls[0]           # the date rides the intake prompt
    assert f"The last settled day is {C.settled_day(C.today_utc(), '', 29)}." in calls[0]
    assert not out.get("_intake_failed")
    assert out["_ada_intake"]["metric_sql"] == "SUM(sale_price)"
    assert "TODAY: " in out["_ada_intake"]["sql_context"]


# ── The last two model prompts GM-2's census named `unstated` ─────────────────────────


def test_the_explore_planner_and_the_ontology_enricher_are_told_the_engine(monkeypatch):
    """The explore branch runs no intake, so its sub-question planner was told no engine; the
    ontology enricher's formulas likewise. The planner gets the block and the writer rules; a
    formula gets the engine and the rules but never the clock — it reads today at query time."""
    from aughor.agent import explore as E
    from aughor.agent.prompts_explore import PLAN_SUBQ_PROMPT
    from aughor.db.dialects import writer_rules
    from aughor.ontology import enricher

    block = E._engine_block({"connection_id": "c1"}, _Native())
    assert block.startswith("SQL DIALECT: BigQuery") and "TODAY: " in block
    assert {"sql_context", "dialect_rules"} <= {
        f for _, f, _, _ in __import__("string").Formatter().parse(PLAN_SUBQ_PROMPT) if f}

    seen = {}

    class _LLM:
        def complete(self, *, system, user, response_model, temperature=None):
            seen["user"] = user
            raise RuntimeError("stop after the prompt")

    dialect = "\n\n".join((C.dialect_line(_Native()), writer_rules(_Native())))
    graph = SimpleNamespace(entities={}, relationships=[], metrics={}, computed_properties=[])
    monkeypatch.setattr(enricher, "_render_structural_summary", lambda g: "")
    with pytest.raises(RuntimeError):
        enricher.enrich_ontology_semantics(graph, _LLM(), {}, "", sql_dialect=dialect)
    assert seen["user"].endswith(dialect) and "TODAY:" not in seen["user"]
