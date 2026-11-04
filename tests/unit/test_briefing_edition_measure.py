"""Arc BG-2 (ROADMAP §3.66) — the guide's checks measured against their usual range.

A DuckDB shop: storefront A sells 30 orders a day, B 10, a tiny one 1; the average order steps a
little week to week, then A's jumps in the week of 19–25 Oct. A storefront OUT sold until 30 Apr.
The edition must place the jump far outside the usual range (and so on every reader's page), name
the storefront that carries it, call the tiny one too few, and compare a year earlier without OUT
only when a PERSON published that rule.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date

import duckdb
import pytest

from aughor.briefing import edition as E
from aughor.briefing import guide as G
from aughor.briefing import ranges
from aughor.semantic.metrics import MetricDefinition

OCT29 = date(2026, 10, 29)


@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute("""CREATE TABLE orders AS
        WITH days AS (SELECT d::DATE AS d FROM range(DATE '2025-09-01', DATE '2026-10-29', INTERVAL 1 DAY) t(d))
        SELECT d AS order_date, 'A' AS platform,
               CASE WHEN d BETWEEN DATE '2026-10-19' AND DATE '2026-10-25' THEN 160.0
                    ELSE 100.0 + (EXTRACT(week FROM d) % 3) * 4 END AS gmv
        FROM days, range(30) k(i)
        UNION ALL SELECT d, 'B', 50.0 + (EXTRACT(week FROM d) % 2) * 2, FROM days, range(10) k(i)
        UNION ALL SELECT d, 'tiny', 75.0 FROM days
        UNION ALL SELECT d, 'OUT', 20.0 FROM days, range(20) k(i) WHERE d < DATE '2026-04-30'""")
    yield c
    c.close()


def _run(con):
    def run(sql):
        try:
            cur = con.execute(sql)
            return [d[0] for d in cur.description], cur.fetchall(), None
        except Exception as exc:  # noqa: BLE001
            return [], [], str(exc)
    return run


@pytest.fixture
def week():
    spec, why = ranges.resolve_range("last_week", today=OCT29, lag_days=1, lag_source="learned")
    assert spec is not None and spec.start == date(2026, 10, 19), why
    return spec


@pytest.fixture(autouse=True)
def no_metrics(monkeypatch):
    monkeypatch.setattr(ranges, "governed_metrics", lambda *a, **k: [])


SALES = G.Check(id="sales", label="Sales", sql="SUM(gmv)", tables=["orders"], time_column="orders.order_date",
                unit="EUR", better="up", dimensions=["platform"])
AOV = G.Check(id="aov", label="Average order", sql="AVG(gmv)", tables=["orders"],
              time_column="orders.order_date", unit="EUR", better="up")
OUT_RULE = G.Comparison(text="OUT was sold on 30 April 2026",
                        exclude_from_last_year=G.LikeForLike(column="orders.platform", value="OUT",
                                                             until="2026-04-30"))


def test_a_jump_far_outside_its_usual_range_is_on_every_readers_page(con, week):
    guide = G.BriefingGuide(checks=[AOV])
    out = E.measure_edition("c1", week, guide, published=False, run_sql=_run(con), dialect="duckdb")
    (aov,) = out["figures"]
    assert aov["usual"]["n"] == 8                                 # the eight weeks before
    assert aov["usual"]["low"] < aov["usual"]["mean"] < aov["usual"]["high"] < aov["current"]
    assert aov["z"] > 2 and aov["outside"] and aov["floor"]
    assert out["floor"] == ["aov"]
    assert aov["extreme"] == {"which": "highest", "of": 9}
    assert aov["streak"] >= 1
    assert [p["label"] for p in aov["series"]][-1] == "current" and len(aov["series"]) == 9
    assert aov["current_text"] and aov["usual"]["low_text"]       # worded as every Briefing words a figure


def test_the_storefront_that_carries_the_move_leads_and_a_tiny_one_is_too_few_to_call(con, week):
    guide = G.BriefingGuide(checks=[SALES])
    (sales,) = E.measure_edition("c1", week, guide, published=False, run_sql=_run(con),
                                 dialect="duckdb")["figures"]
    cells = sales["cells"]["platform"]["cells"]
    assert cells[0]["group"] == "A" and cells[0]["delta"] > 0     # furthest from its usual, first
    tiny = next(c for c in cells if c["group"] == "tiny")
    assert tiny["thin"] and cells[-1]["group"] == "tiny"          # 7 rows: listed last, never headlined
    assert "OUT" not in {c["group"] for c in cells}               # no rows this week, no segment


def test_like_for_like_applies_only_from_a_published_guide(con, week):
    guide = G.BriefingGuide(checks=[SALES], comparisons=[OUT_RULE])
    draft = E.measure_edition("c1", week, guide, published=False, run_sql=_run(con), dialect="duckdb")
    pub = E.measure_edition("c1", week, guide, published=True, run_sql=_run(con), dialect="duckdb")
    d, p = draft["figures"][0], pub["figures"][0]
    assert d["like_for_like"] == "" and p["like_for_like"] == "without OUT before 2026-04-30"
    assert p["last_year"] < d["last_year"]                        # a year earlier without OUT's sales
    assert p["current"] == d["current"]                           # this week never had OUT
    assert p["last_year"] == pytest.approx(d["last_year"] - 7 * 20 * 20.0)


def test_what_could_not_be_measured_is_said(con, week):
    guide = G.BriefingGuide(
        checks=[AOV, G.Check(id="broken", label="Broken", sql="SUM(nope)", tables=["orders"],
                             time_column="orders.order_date")],
        care=[G.CareNote(text="Prices end on 5 April 2024.", tables=["price_history"])],
        dropped=[G.DroppedCheck(id="ghost", label="Ghost", reason="no approved metric is named ghost")])
    out = E.measure_edition("c1", week, guide, published=False, run_sql=_run(con), dialect="duckdb")
    assert [f["id"] for f in out["figures"]] == ["aov"]
    assert out["unmeasured"][0]["id"] == "broken" and "query failed" in out["unmeasured"][0]["reason"]
    labels = [n["label"] for n in out["not_read"]]
    assert labels == ["Prices end on 5 April 2024.", "Broken", "Ghost"]


@pytest.fixture
def settling_week():
    """theLook's shape: its tables were still moving at the oldest age read, so its lag is a floor and its flows never
    settle. The same dates and rows as ``week``, so the tables the platform has seen settle are all that differs."""
    spec, why = ranges.resolve_range("last_week", today=OCT29, lag_days=1, lag_source="beyond_horizon",
                                     still_moving=("orders",))
    assert spec is not None and spec.start == date(2026, 10, 19), why
    return spec


def test_a_flow_still_settling_is_shown_but_not_read_against_its_usual_range(con, week, settling_week):
    """Measured 2026-11-04: on theLook six of ten figures were floor, five of them flows the Dashboard marks as not at
    equal age, and the edition called them final. ``status`` alone would never have fired the guard."""
    guide = G.BriefingGuide(checks=[AOV])
    settled = E.measure_edition("c1", week, guide, published=False, run_sql=_run(con), dialect="duckdb")["figures"][0]
    assert settled["outside"] and settled["floor"] and settled["extreme"] and settled["z"] > 2     # these rows do fire
    assert settled["status"] == "final" and settled["equal_age"] == {"equal": True, "why": ""}

    out = E.measure_edition("c1", settling_week, guide, published=False, run_sql=_run(con), dialect="duckdb")
    (aov,) = out["figures"]
    assert aov["status"] == "provisional"
    assert aov["equal_age"]["equal"] is False and aov["equal_age"]["why"].startswith("Average order is still provisional")
    assert not aov["outside"] and not aov["floor"] and out["floor"] == []
    assert aov["z"] is None and aov["extreme"] is None and E.score(aov, watched=False) == 0.0
    assert aov["current"] == settled["current"] and aov["usual"] == settled["usual"]       # the number and band stay
    assert [n["reason"] for n in out["not_read"] if n["label"] == "Average order against its usual range"] \
        == [aov["equal_age"]["why"]]


RETURNS = G.BriefingGuide(checks=[G.Check(id="returns", label="Return rate", metric="return_rate")])


@pytest.fixture
def return_rate(con, monkeypatch):
    """An approved cohort: nine of ten items sold in the week of 19–25 Oct came back, one to three of ten before it."""
    con.execute("""CREATE TABLE items AS
        WITH days AS (SELECT d::DATE AS d FROM range(DATE '2026-06-01', DATE '2026-10-29', INTERVAL 1 DAY) t(d))
        SELECT d AS sold_on, CASE WHEN i < (CASE WHEN d BETWEEN DATE '2026-10-19' AND DATE '2026-10-25' THEN 9
                                                 ELSE 1 + (EXTRACT(week FROM d) % 3) END)
                                  THEN d + INTERVAL 1 DAY END AS returned_on
        FROM days, range(10) k(i)""")
    rate = MetricDefinition(name="return_rate", label="Return rate", connection="c1", status="approved",
                            sql="AVG(CASE WHEN returned_on IS NOT NULL THEN 1.0 ELSE 0.0 END)", tables=["items"],
                            time_column="items.sold_on", time_kind="cohort", outcome_column="returned_on")
    monkeypatch.setattr(ranges, "governed_metrics", lambda *a, **k: [rate])


def test_a_cohort_on_a_table_still_settling_stays_news(con, settling_week, return_rate):
    """A cohort is read at each window's own age, so it IS at equal age, as theLook's sell-through is: the guard must
    leave it floor. A cohort only arrives as an approved metric; a check's own aggregate has no outcome to read."""
    spec = replace(settling_week, still_moving=("items",))
    out = E.measure_edition("c1", spec, RETURNS, published=False, run_sql=_run(con), dialect="duckdb")
    (fig,) = out["figures"]
    assert fig["time_kind"] == "cohort" and fig["status"] == "provisional" and fig["equal_age"]["equal"] is True
    assert fig["outside"] and fig["floor"] and out["floor"] == ["returns"] and fig["z"] > 2
    assert not [n for n in out["not_read"] if "usual range" in n["label"]]


def test_a_cohort_still_under_way_is_outside_but_not_on_every_readers_page(con, settling_week, return_rate):
    """At equal age, and part of a range: far enough to be news, not yet enough to put on everyone's page."""
    spec = replace(settling_week, as_of=date(2026, 10, 24), still_moving=())
    out = E.measure_edition("c1", spec, RETURNS, published=False, run_sql=_run(con), dialect="duckdb")
    (fig,) = out["figures"]
    assert fig["status"] == "to_date" and fig["equal_age"]["equal"] is True and abs(fig["z"]) >= 2
    assert fig["outside"] and not fig["floor"] and out["floor"] == []


def test_the_dashboard_and_the_edition_give_a_figure_one_status(con, settling_week, monkeypatch):
    aov = MetricDefinition(name="aov", label="Average order", connection="c1", status="approved", sql="AVG(gmv)",
                           tables=["orders"], time_column="orders.order_date", time_kind="flow")
    monkeypatch.setattr(ranges, "governed_metrics", lambda *a, **k: [aov])
    dashboard = ranges.measure_range("c1", settling_week, run_sql=_run(con), dialect="duckdb")["measured"][0]
    guide = G.BriefingGuide(checks=[G.Check(id="aov", label="Average order", metric="aov")])
    (figure,) = E.measure_edition("c1", settling_week, guide, published=False, run_sql=_run(con),
                                  dialect="duckdb")["figures"]
    assert dashboard["status"] == figure["status"] == "provisional"
    assert dashboard["equal_age"] == figure["equal_age"] and figure["equal_age"]["equal"] is False


@pytest.mark.parametrize("m,expected", [
    ({"tables": ["bigquery-public-data.thelook_ecommerce.orders"], "sql": "SUM(x)"}, "provisional"),
    ({"tables": [], "sql": "SELECT SUM(x) FROM orders"}, "provisional"),      # a statement names its own tables
    ({"tables": ["returns"], "sql": "SUM(x)"}, "final")])
def test_a_figure_is_unsettled_by_the_tables_it_reads_however_they_are_spelled(settling_week, m, expected):
    assert ranges.range_status({**m, "time_kind": "flow"}, settling_week) == expected


@pytest.mark.parametrize("series,expected", [
    ([1, 2, 3, 2.5, 2, 1.5], -3), ([1, 2, 3], 2), ([1, 1], 0), ([3, 2, 2], 0), ([None, 1, 2], 1)])
def test_streak(series, expected):
    assert E._streak(series) == expected


def test_an_unusual_figure_outranks_a_watched_usual_one():
    unusual = {"z": 2.4, "streak": -3}
    watched_usual = {"z": 0.4, "streak": 1}
    assert E.score(unusual, watched=False) > E.score(watched_usual, watched=True)
    assert E.score({"z": 1.2}, watched=True) > E.score({"z": 1.2}, watched=False)
