"""The dates a metric could be measured by, as the Dates editor offers them (`metric_statement.date_candidates`,
`dates_one_join_away`, `year_only`).

The user, 2026-10-13, on LuxExperience: "Date, timestamp or other date format columns do not appear as [a] drop down".
Four approved metrics offered nothing. Each for its own reason, all read from the profile, no warehouse call:
- Session Conversion reads `web_sessions`, whose day is `session_start` kept as ISO TEXT — the profiler counts only
  date- and time-typed columns, so it was never offered. Now it is, said to be text.
- Gross Margin % reads `order_items`, which has no date; `orders.order_date` is one join away (`order_id`). It is said,
  with what the definition must change — never offered as a grain the period filter could not use.
- Marketing ROAS reads `marketing_campaigns`, which has only `fiscal_year`, a year number.
"""
from __future__ import annotations

from aughor.semantic.metric_statement import date_candidates, dates_one_join_away, year_only


def _col(table, column, dtype):
    return f"{table}.{column}", {"table": table, "column": column, "dtype": dtype}


LUX = {
    "tables": {"orders": {"primary_timestamp": "order_date"}, "order_items": {}, "returns": {}, "web_sessions": {},
               "marketing_campaigns": {}},
    "columns": dict([
        _col("order_items", "order_item_id", "text"), _col("order_items", "order_id", "text"),
        _col("order_items", "product_id", "text"), _col("order_items", "unit_price_eur", "numeric"),
        _col("order_items", "returned", "boolean"),
        _col("orders", "order_id", "text"), _col("orders", "order_date", "date"), _col("orders", "fiscal_year", "integer"),
        _col("returns", "return_id", "text"), _col("returns", "order_id", "text"), _col("returns", "return_date", "date"),
        _col("web_sessions", "session_id", "text"), _col("web_sessions", "session_start", "text"),
        _col("web_sessions", "time_zone", "text"), _col("web_sessions", "converted", "boolean"),
        _col("marketing_campaigns", "campaign_id", "text"), _col("marketing_campaigns", "fiscal_year", "integer"),
        _col("marketing_campaigns", "spend_eur", "numeric"),
    ]),
}


def test_a_day_kept_as_text_is_offered_and_said_to_be_text():
    out = date_candidates("SELECT SUM(CASE WHEN converted THEN 1 ELSE 0 END) * 1.0 / COUNT(*) FROM web_sessions", [], LUX)
    assert [(c["grain"], c.get("text")) for c in out] == [("web_sessions.session_start", True)]   # never time_zone


def test_a_typed_date_comes_before_a_text_one_and_the_main_date_first():
    out = date_candidates("SELECT COUNT(*) FROM orders", [], LUX)
    assert [c["grain"] for c in out] == ["orders.order_date"]
    assert out[0]["primary"] is True and not out[0].get("text")


def test_a_table_with_no_date_points_at_the_one_its_key_names_and_never_at_another_that_carries_it():
    sql = "SELECT (SUM(unit_price_eur) - 0) / NULLIF(SUM(unit_price_eur), 0) FROM order_items"
    assert date_candidates(sql, [], LUX) == []
    away = dates_one_join_away(sql, [], LUX)
    assert [(r["grain"], r["via"], r["from"]) for r in away] == [("orders.order_date", "order_id", "order_items")]
    # schema-qualified as the statement wrote it
    away = dates_one_join_away("SELECT COUNT(*) FROM luxexperience.order_items", [], LUX)
    assert [r["grain"] for r in away] == ["luxexperience.orders.order_date"]


def test_a_table_with_only_a_year_says_so():
    assert year_only(["marketing_campaigns"], LUX).startswith(
        "marketing_campaigns has no date — only fiscal_year, a year number")
    assert year_only(["order_items"], LUX) == ""


def test_the_route_says_where_the_date_is(client, monkeypatch):
    monkeypatch.setattr("aughor.tools.profile_cache.profile_entry_for", lambda conn, tables: LUX)
    r = client.post("/metrics/proposals", json={"connection": "c1", "sql": "SELECT SUM(unit_price_eur) FROM order_items"})
    body = r.json()
    assert body["candidates"] == [] and [x["grain"] for x in body["reachable"]] == ["orders.order_date"]
    assert body["note"] == ("order_items has no date of its own — orders.order_date is one join away (on order_id); "
                            "to be measured by it, the definition must read orders")
    r = client.post("/metrics/proposals", json={"connection": "c1", "sql": "SELECT SUM(spend_eur) FROM marketing_campaigns"})
    assert r.json()["note"].startswith("marketing_campaigns has no date — only fiscal_year")
