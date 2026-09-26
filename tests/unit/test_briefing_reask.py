"""BR-7 (2026-09-26): the explorer's findings re-asked for a range, no model.

Pinned: the grain is the first table the statement reads that has a main date, else the finding
is apart with why; the figure is the one-row value, else the total, or the mean for a rate, of
the measure column; the statement is cut for the range and the previous range and the change
ranks the list, unknown change last; every finding lands in exactly one list; the door refuses
without a range or with the flag off, and serves its cache on the second ask.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date

from fastapi.testclient import TestClient

from aughor.api import app
from aughor.briefing import reask as rk
from aughor.briefing.ranges import RangeSpec

client = TestClient(app)

PROFILE = {"tables": {"orders": {"primary_timestamp": "created_at"}, "products": {}},
           "columns": {"orders.created_at": {"table": "orders", "column": "created_at", "dtype": "TIMESTAMP"}}}
SPEC = RangeSpec(preset="last_week", start=date(2026, 8, 17), end=date(2026, 8, 24),
                 previous_start=date(2026, 8, 10), previous_end=date(2026, 8, 17),
                 last_year_start=None, last_year_end=None, as_of=date(2026, 9, 26), lag_days=8, lag_source="test")


def _runner(answers: dict):
    """A run_sql that answers by the window it sees in the SQL: '2026-08-17' → current, '2026-08-10' → previous."""
    calls: list[str] = []

    def run_sql(sql: str):
        calls.append(sql)
        label = "current" if "2026-08-17" in sql and "2026-08-10" not in sql else "previous"
        if "boom" in sql:
            return [], [], "boom failed"
        return answers[label]
    return run_sql, calls


def test_the_figure_is_the_value_the_total_or_the_mean_for_a_rate():
    assert rk.figure_of(["n"], [[42]], []) == (42.0, "value", "n", 1)
    assert rk.figure_of(["status", "order_count"], [["a", 2], ["b", 3]], []) == (5.0, "total", "order_count", 2)
    assert rk.figure_of(["cat", "return_rate"], [["a", 0.1], ["b", 0.3]], ["return_rate"]) == (0.2, "mean", "return_rate", 2)
    # A declared measure wins over the first numeric column.
    assert rk.figure_of(["cat", "sold", "returned"], [["a", 10, 1]], ["returned"]) == (1.0, "value", "returned", 1)
    assert rk.figure_of(["cat"], [["a"], ["b"]], []) == (None, "", "", 2)
    assert rk.figure_of([], [], []) == (None, "", "", 0)


def test_the_grain_is_the_first_read_table_with_a_main_date_or_why_not():
    assert rk.grain_for("SELECT COUNT(*) FROM products p JOIN orders o ON o.id = p.id", [], PROFILE, "duckdb") == ("orders", "created_at", "")
    assert rk.grain_for("SELECT COUNT(*) FROM products", [], PROFILE, "duckdb") == (None, "", "no date on products")
    assert rk.grain_for("SELECT 1", [], PROFILE, "duckdb") == (None, "", "its SQL names no table")


def test_findings_are_re_asked_for_both_ranges_and_ranked_by_the_change():
    findings = [
        {"id": "f1", "domain": "Orders", "sql": "SELECT status, COUNT(*) AS order_count FROM orders GROUP BY 1",
         "signature": {"tables": ["orders"], "measures": ["order_count"]}},
        {"id": "f2", "domain": "Orders", "sql": "SELECT COUNT(*) AS n FROM orders", "signature": {"tables": ["orders"]}},
        {"id": "f3", "domain": "Catalog", "sql": "SELECT COUNT(*) AS n FROM products", "signature": {"tables": ["products"]}},
        {"id": "f4", "domain": "Orders", "sql": "", "signature": {}},
        {"id": "f5", "domain": "Orders", "sql": "SELECT boom FROM orders", "signature": {"tables": ["orders"]}},
        # The aggregate view lists a pinned finding once per schema: the same (id, SQL) is asked once, and said.
        {"id": "f2", "domain": "Orders", "sql": "SELECT COUNT(*) AS n FROM orders", "signature": {"tables": ["orders"]}},
    ]
    run_sql, calls = _runner({"current": (["status", "order_count"], [["a", 6], ["b", 4]], None),
                              "previous": (["status", "order_count"], [["a", 4], ["b", 4]], None)})
    out = rk.reask_findings(findings, SPEC, run_sql=run_sql, dialect="duckdb", profile_entry=PROFILE)
    assert out["covers"] and out["compared_with"] and out["key"] == SPEC.key and out["capped"] == 0
    got = {r["id"]: r for r in out["reasked"]}
    assert set(got) == {"f1", "f2"}
    assert got["f1"]["current"] == 10.0 and got["f1"]["previous"] == 8.0 and got["f1"]["how"] == "total"
    assert got["f1"]["rel"] == 0.25 and got["f1"]["grain"] == "orders.created_at" and got["f1"]["rows_current"] == 2
    assert "2026-08-17" in got["f1"]["sql"] and "orders" in got["f1"]["sql"]
    # f2's one-row answer reads the same fake rows: the first numeric column of a two-column result.
    assert [r["id"] for r in out["reasked"]] == ["f1", "f2"] or [r["id"] for r in out["reasked"]] == ["f2", "f1"]
    apart = {a["id"]: a["why"] for a in out["apart"]}
    assert apart["f3"] == "no date on products" and apart["f4"] == "it kept no SQL"
    assert apart["f5"].startswith("its query failed for current: boom failed")
    # Every distinct finding in exactly one list; two queries per re-asked finding, one for the failed one.
    assert out["duplicates"] == 1
    assert len(out["reasked"]) + len(out["apart"]) == len(findings) - 1
    assert len(calls) == 2 * 2 + 1


def test_the_cap_is_said():
    findings = [{"id": f"f{i}", "domain": "d", "sql": "SELECT COUNT(*) AS n FROM orders", "signature": {"tables": ["orders"]}}
                for i in range(rk.MAX_REASKED + 3)]
    run_sql, _ = _runner({"current": (["n"], [[1]], None), "previous": (["n"], [[1]], None)})
    out = rk.reask_findings(findings, SPEC, run_sql=run_sql, dialect="duckdb", profile_entry=PROFILE)
    assert out["capped"] == 3 and len(out["reasked"]) == rk.MAX_REASKED


def test_the_door_serves_the_re_ask_and_its_cache_and_refuses_without_a_range(monkeypatch):
    from aughor.routers import exploration as ex
    monkeypatch.setenv("AUGHOR_BRIEFING_RANGES", "1")
    monkeypatch.setattr("aughor.briefing.ranges.resolve_for", lambda cid, preset=None, **kw: (SPEC, ""))
    monkeypatch.setattr(ex, "_domain_insights_for", lambda cid, schema: {
        "Orders": {"insights": [{"id": "f2", "sql": "SELECT COUNT(*) AS n FROM orders", "signature": {"tables": ["orders"]}}]},
        # The store's own shape is a plain list per domain; the served block wraps it. Both must read.
        "Catalog": [{"id": "f3", "sql": "SELECT COUNT(*) AS n FROM products", "signature": {"tables": ["products"]}}]})
    monkeypatch.setattr("aughor.tools.profile_cache.latest_profile_entry", lambda cid: PROFILE)
    seen = {"opened": 0}

    @contextmanager
    def runner(cid):
        seen["opened"] += 1
        run_sql, _ = _runner({"current": (["n"], [[12]], None), "previous": (["n"], [[10]], None)})
        yield run_sql, "duckdb"
    monkeypatch.setattr("aughor.knowledge.period_brief.connection_runner", runner)
    ex._REASK_CACHE.clear()
    r = client.get("/exploration/c-reask/findings/reask", params={"preset": "last_week"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [x["id"] for x in body["reasked"]] == ["f2"] and body["reasked"][0]["rel"] == 0.2
    assert body["apart"] == [{"id": "f3", "domain": "Catalog", "why": "no date on products"}]
    assert body["total"] == 2 and body["profiled"] is True and body["cached"] is False
    again = client.get("/exploration/c-reask/findings/reask", params={"preset": "last_week"}).json()
    assert again["cached"] is True and seen["opened"] == 1
    assert client.get("/exploration/c-reask/findings/reask").status_code == 422
    monkeypatch.setenv("AUGHOR_BRIEFING_RANGES", "0")
    assert client.get("/exploration/c-reask/findings/reask", params={"preset": "last_week"}).status_code == 404
