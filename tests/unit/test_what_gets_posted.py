"""What gets posted — a Slack step's say over its post, and names a reader can read (2026-11-06).

The Daily Briefing's 09:00 post: a chart titled with the automation's name, its legend "r28 · r29"
over an axis called "Value". The model had aliased revenue on Oct 28 and Oct 29 that way; the engine
chose the picture alone. The fixture is that run's own results and SQL.

Measured while building, and each held here:
* names are display labels, never renamed columns — a column renamed "Oct 28" was read as a date and
  the chart lost a series;
* "Revenue" only where the query computes the governed metric, filter and all;
* a kind that would drop a series (horizontal bars or a pie over two) is drawn as auto and says so.
"""
from __future__ import annotations

from types import SimpleNamespace as N

import pytest

from aughor.answer.series_names import cryptic, names_for
from aughor.automations import picture

REVENUE = N(name="revenue", label="Revenue", status="approved",
            sql="SELECT (SUM(sale_price)) AS revenue FROM order_items WHERE status <> 'Cancelled'",
            filters=["status <> 'Cancelled'"])
BY_CATEGORY = ("SELECT p.category, SUM(IF(DATE(oi.created_at)='2026-10-29',oi.sale_price,0)) r29, "
               "SUM(IF(DATE(oi.created_at)='2026-10-28',oi.sale_price,0)) r28 FROM order_items oi "
               "JOIN products p ON p.id=oi.product_id WHERE oi.status<>'Cancelled' AND oi.created_at>='2026-10-28' "
               "AND oi.created_at<'2026-10-30' GROUP BY p.category ORDER BY r29-r28 LIMIT 5")
DAILY = ("SELECT DATE(created_at) d, SUM(sale_price) rev, COUNT(DISTINCT order_id) orders, COUNT(id) items "
         "FROM order_items WHERE status<>'Cancelled' AND created_at>='2026-10-20' AND created_at<'2026-10-31' "
         "GROUP BY d ORDER BY d")
CATEGORY_ROWS = [["Outerwear & Coats", "3000.36", "12737.46"], ["Jeans", "3130.27", "9743.79"],
                 ["Sweaters", "2669.22", "7730.77"], ["Active", "1222.21", "4461.41"], ["Tops & Tees", "1140.20", "4182.75"]]
DAILY_ROWS = [["2026-10-27", "60910.1", "950", "1001"], ["2026-10-28", "90229.42", "1405", "1500"],
              ["2026-10-29", "29775.03", "431", "460"]]
CLAIM = "Outerwear & Coats was the largest category decline, from $12,737.46 to $3,000.36."


# ── names ────────────────────────────────────────────────────────────────────────────────

def test_the_models_aliases_are_named_from_their_own_sql():
    assert names_for(["category", "r29", "r28"], [BY_CATEGORY], metrics=[REVENUE]) == {
        "labels": {"r29": "Oct 29", "r28": "Oct 28"}, "y_title": "Revenue"}
    assert names_for(["d", "rev", "orders", "items"], ["SELECT 1", DAILY], metrics=[REVENUE]) == {
        "labels": {"d": "Date", "rev": "Revenue"}, "y_title": "Revenue"}


def test_the_governed_name_needs_the_governed_filter():
    """SUM(sale_price) without the revenue metric's status filter is not revenue."""
    unfiltered = BY_CATEGORY.replace("WHERE oi.status<>'Cancelled' AND ", "WHERE ")
    assert names_for(["category", "r29", "r28"], [unfiltered], metrics=[REVENUE])["y_title"] == "Sale price"


def test_a_name_made_of_words_is_left_to_the_renderers():
    assert not cryptic("revenue_change") and cryptic("r29") and cryptic("d")
    assert names_for(["category", "revenue"], [BY_CATEGORY], metrics=[REVENUE]) == {}


# ── the picture's settings ───────────────────────────────────────────────────────────────

def _source():
    main = {"claim": CLAIM, "columns": ["category", "r29", "r28"], "rows": CATEGORY_ROWS, "chart_type": "auto",
            "chart_config": {"names": {"labels": {"r29": "Oct 29", "r28": "Oct 28"}, "y_title": "Revenue"}}}
    daily = {"claim": "Daily revenue ramped to 10-28, then 10-29 fell.", "columns": ["d", "rev", "orders", "items"],
             "rows": DAILY_ROWS, "chart_type": "auto", "chart_config": {}}
    return {**main, "results": [main, daily], "sql": [DAILY, BY_CATEGORY]}


@pytest.fixture(autouse=True)
def _metrics(monkeypatch):
    monkeypatch.setattr("aughor.answer.series_names.connection_metrics", lambda cid: [REVENUE])


def test_no_settings_draws_the_main_result_titled_by_its_own_sentence():
    [p] = picture.plan({}, _source(), automation_name="The Look - Daily Briefing")
    assert (p["as"], p["kind"], p["result"], p["title"]) == ("chart", "auto", 0, CLAIM)
    assert p["names"]["labels"] == {"r29": "Oct 29", "r28": "Oct 28"} and not p["note"]


@pytest.mark.parametrize("kind, said", [
    ("pie", "Asked for a pie: one series only, so Oct 28 would be left out — drawn as auto"),
    ("bar_horizontal", "Asked for horizontal bars: one series only, so Oct 28 would be left out — drawn as auto"),
    ("line", "Asked for a line: no time column in this result — drawn as auto"),
])
def test_a_kind_that_would_drop_a_series_is_drawn_as_auto_and_says_why(kind, said):
    [p] = picture.plan({"chart_kind": kind}, _source(), automation_name="x")
    assert p["kind"] == "auto" and p["note"] == said


def test_bars_over_several_series_draw_every_series():
    """The renderer's plain bar draws one measure: "Bars" over Oct 28 and Oct 29 drew Oct 29 alone.
    Rendered for real — a planned kind name alone cannot show a series went missing."""
    import re

    [p] = picture.plan({"chart_kind": "bar"}, _source(), automation_name="x")
    assert p["kind"] == "grouped_bar" and not p["note"]
    from aughor.export.echarts import render_chart_svg
    svg = render_chart_svg(p["columns"], p["rows"], p["kind"], p["title"], chart_config={"names": p["names"]})
    assert sorted(set(re.findall(r">(Oct 2\d)<", svg or ""))) == ["Oct 28", "Oct 29"]
    one = {**_source(), "results": [{**_source()["results"][0], "columns": ["category", "r28"],
                                     "rows": [[r[0], r[2]] for r in CATEGORY_ROWS]}]}
    [q] = picture.plan({"chart_kind": "bar"}, one, automation_name="x")
    assert q["kind"] == "bar"


def test_the_rule_picks_among_this_runs_results():
    assert [p["result"] for p in picture.plan({"picture_from": "over_time"}, _source(), automation_name="x")] == [1]
    assert [p["result"] for p in picture.plan({"picture_from": "every"}, _source(), automation_name="x")] == [0, 1]
    one = {**_source(), "results": _source()["results"][:1]}
    [p] = picture.plan({"picture_from": "over_time"}, one, automation_name="x")
    assert p["result"] == 0 and "no result this run had a time column" in p["note"]


def test_none_table_titles_and_a_persons_names():
    assert picture.plan({"picture": "none"}, _source(), automation_name="x") == []
    [t] = picture.plan({"picture": "table", "picture_title": "name"}, _source(), automation_name="Daily")
    assert (t["as"], t["title"]) == ("table", "Daily")
    [c] = picture.plan({"picture_title": "custom", "picture_title_text": "Categories, day on day",
                        "picture_names": {"r28": "Tuesday", "axis": "Revenue ($)", "gone": "x"}},
                       _source(), automation_name="x")
    assert c["title"] == "Categories, day on day"
    assert c["names"] == {"labels": {"r29": "Oct 29", "r28": "Tuesday"}, "y_title": "Revenue ($)"}


def test_a_result_from_before_names_were_recorded_is_named_from_the_answers_sql():
    src = _source()
    src["results"][1]["chart_config"] = {}
    [p] = picture.plan({"picture_from": "over_time"}, src, automation_name="x")
    assert p["names"] == {"labels": {"d": "Date", "rev": "Revenue"}, "y_title": "Revenue"}


def test_a_table_picture_reads_its_names_and_numbers():
    svg = picture.table_svg(["category", "r29", "r28"], CATEGORY_ROWS, CLAIM,
                            {"labels": {"r29": "Oct 29", "r28": "Oct 28"}})
    assert ">Oct 29<" in svg and ">r29<" not in svg and ">12,737.46<" in svg and "Outerwear &amp; Coats" in svg


# ── the post, and the preview that shows it ─────────────────────────────────────────────

def _post(monkeypatch, config: dict) -> list[dict]:
    """Run the engine's own attach with the renderer and the upload counted."""
    from aughor.automations import engine
    from aughor.automations.models import Effect
    from aughor.export import echarts
    from aughor.slackbots import post
    calls: list[dict] = []
    monkeypatch.setattr(echarts, "render_chart_svg", lambda *a, **k: calls.append({"render": a, **k}) or "<svg/>")
    monkeypatch.setattr(echarts, "svg_to_png", lambda *a, **k: b"PNG")
    monkeypatch.setattr(post, "upload_file", lambda *a, **k: calls.append({"upload": k}) or (True, {}))
    eff = Effect(kind="slack_post", config={"bot_id": "b", "channel": "#c", "message": "m",
                                            engine.CHART_GRID_KEY: _source(), **config})
    bot = N(bot_token="t", name="Aughor", enabled=True)
    engine._attach_chart(eff, N(id="a", name="The Look - Daily Briefing", conn_id=""), bot,
                         {"channel": "C1", "ts": "1.1"}, "#c")
    return calls


def test_the_post_draws_what_the_step_says(monkeypatch):
    calls = _post(monkeypatch, {})
    render = next(c for c in calls if "render" in c)
    assert render["render"][3] == CLAIM and render["chart_config"]["names"]["labels"]["r28"] == "Oct 28"
    assert [c["upload"]["title"] for c in calls if "upload" in c] == [CLAIM]
    assert not [c for c in _post(monkeypatch, {"picture": "none"}) if "upload" in c]
    pie = _post(monkeypatch, {"chart_kind": "pie"})
    assert [c["upload"]["title"] for c in pie if "upload" in c][0].startswith("Asked for a pie")


def test_the_preview_is_what_the_post_plans(monkeypatch):
    from fastapi.testclient import TestClient

    from aughor.api import app
    from aughor.automations.models import Automation, AutomationRun, Condition, Effect, EffectOutcome
    from aughor.automations.store import append_run, upsert_automation
    a = upsert_automation(Automation(
        id="wgp-preview", conn_id="", name="The Look - Daily Briefing",
        conditions=[Condition(kind="schedule", config={"cron": "0 9 * * *"})],
        effects=[Effect(kind="investigate", config={"question": "What changed in theLook in the last day?"}),
                 Effect(kind="slack_post", config={"bot_id": "b", "channel": "#c", "message": {"$from": "step1.summary"}})]))
    envelope = {"headline": "Revenue fell on 10-29", "grid": {"columns": ["category", "r29", "r28"], "rows": CATEGORY_ROWS},
                "chart": {"chart_type": "auto", "chart_config": {}},
                "exhibits": [{"claim": CLAIM, "grid": {"columns": ["category", "r29", "r28"], "rows": CATEGORY_ROWS}},
                             {"claim": "Daily revenue ramped, then fell.", "grid": {"columns": ["d", "rev", "orders", "items"], "rows": DAILY_ROWS}}],
                "provenance": {"sql": [DAILY, BY_CATEGORY]}}
    append_run(AutomationRun(automation_id=a.id, outcome="fired", effects=[
        EffectOutcome(kind="investigate", status="executed", data={"summary": "Revenue fell 67%.", "answer": "Revenue fell",
                                                                     "envelope": envelope}),
        EffectOutcome(kind="slack_post", status="executed", data={"ts": "1.1"})]))
    # A daily chain ticks every minute: its fired run sits behind hundreds of not_fired rows.
    for _ in range(300):
        append_run(AutomationRun(automation_id=a.id, outcome="not_fired", reason="not due"))
    client = TestClient(app)
    r = client.post(f"/automations/{a.id}/picture-preview", json={"step": 1, "config": {
        "message": {"$from": "step1.summary"}, "headline": {"$from": "step1.answer"}, "chart_kind": "pie"}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["words"] == "Revenue fell\n\nRevenue fell 67%."
    assert [x["claim"] for x in body["results"]] == [CLAIM, "Daily revenue ramped, then fell."]
    assert body["names"] == {"labels": {"r29": "Oct 29", "r28": "Oct 28"}, "y_title": "Revenue"}
    assert body["kinds"]["pie"]["ok"] is False and body["kinds"]["bar"]["ok"] is True
    [pic] = body["pictures"]
    assert pic["asked"] == "pie" and pic["kind"] == "auto" and pic["note"].startswith("Asked for a pie")
    assert pic["image"].startswith("data:image/png;base64,")
    assert client.post(f"/automations/{a.id}/picture-preview", json={"step": 0, "config": {}}).status_code == 422


def test_the_governed_metrics_come_through_the_platforms_seam(monkeypatch):
    """The platform names an axis by a governed metric without importing the semantic layer: the
    agent registers its reader at bootstrap (`kernel/registries/governed_metrics.py`)."""
    from aughor.kernel.registries import governed_metrics as gm
    monkeypatch.setattr(gm, "_reader", None)
    assert gm.metrics_for("c1") == []                                   # unregistered: none, so "Sale price"
    gm.register_metric_reader(lambda cid: [REVENUE] if cid == "c1" else [])
    assert gm.metrics_for("c1") == [REVENUE] and gm.metrics_for("c2") == []
    gm.register_metric_reader(lambda cid: 1 / 0)
    assert gm.metrics_for("c1") == []                                   # a reader that fails names nothing
