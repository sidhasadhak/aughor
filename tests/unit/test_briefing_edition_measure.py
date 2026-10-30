"""Arc BG-2 (ROADMAP §3.66) — the guide's checks measured against their usual range.

A DuckDB shop: storefront A sells 30 orders a day, B 10, a tiny one 1; the average order steps a
little week to week, then A's jumps in the week of 19–25 Oct. A storefront OUT sold until 30 Apr.
The edition must place the jump far outside the usual range (and so on every reader's page), name
the storefront that carries it, call the tiny one too few, and compare a year earlier without OUT
only when a PERSON published that rule.
"""
from __future__ import annotations

from datetime import date

import duckdb
import pytest

from aughor.briefing import edition as E
from aughor.briefing import guide as G
from aughor.briefing import ranges

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


@pytest.mark.parametrize("series,expected", [
    ([1, 2, 3, 2.5, 2, 1.5], -3), ([1, 2, 3], 2), ([1, 1], 0), ([3, 2, 2], 0), ([None, 1, 2], 1)])
def test_streak(series, expected):
    assert E._streak(series) == expected


def test_an_unusual_figure_outranks_a_watched_usual_one():
    unusual = {"z": 2.4, "streak": -3}
    watched_usual = {"z": 0.4, "streak": 1}
    assert E.score(unusual, watched=False) > E.score(watched_usual, watched=True)
    assert E.score({"z": 1.2}, watched=True) > E.score({"z": 1.2}, watched=False)
