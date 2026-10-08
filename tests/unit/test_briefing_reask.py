"""BR-7 (2026-09-26): the explorer's findings re-asked for a range, no model.

Pinned: the grain is the first table the statement reads that has a main date, else the finding
is apart with why; the figure is the one-row value, the row the finding's statement names when
its rows are labelled (else it is apart, with why), or across a series of dates the total, or the
mean for a rate, of the measure column (2026-10-09); the statement is cut for the range and the previous range and the change
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


def _runner(answers: dict, grouped: dict | None = None):
    """A run_sql that answers by the window it sees in the SQL: '2026-08-17' → current, '2026-08-10' → previous.
    A statement that reads ``status`` gets ``grouped``'s answer, when given."""
    calls: list[str] = []

    def run_sql(sql: str):
        calls.append(sql)
        label = "current" if "2026-08-17" in sql and "2026-08-10" not in sql else "previous"
        if "boom" in sql:
            return [], [], "boom failed"
        return (grouped if grouped and "status" in sql else answers)[label]
    return run_sql, calls


def test_the_figure_is_the_value_the_named_row_or_a_series_total():
    assert rk.figure_of(["n"], [[42]], []) == (42.0, "value", "n", 1)
    # Labelled rows: the row the finding names, never their total or mean — theLook's Day tiles read
    # "35.18, mean of percentage_share" (two departments' shares averaged) before this.
    rows = [["Shipped", "60"], ["Complete", "50"]]
    assert rk.figure_of(["status", "order_count"], rows, [], row=("Shipped",)) == (60.0, "row", "order_count", 2)
    assert rk.figure_of(["status", "order_count"], rows, [], row=("shipped",))[0] == 60.0
    assert rk.figure_of(["status", "order_count"], rows, []) == (None, "unnamed", "order_count", 2)
    assert rk.figure_of(["status", "order_count"], rows, [], row=("Returned",)) == (None, "row", "order_count", 2)
    assert rk.figure_of(["status", "order_count"], [], [], row=("Shipped",)) == (None, "row", "", 0)
    # A series of dates over the range: its total, or the mean for a rate. A date names nothing.
    assert rk.figure_of(["day", "order_count"], [["2026-08-17", 2], ["2026-08-18", 3]], []) == (5.0, "total", "order_count", 2)
    assert rk.figure_of(["day", "return_rate"], [[date(2026, 8, 17), 0.1], [date(2026, 8, 18), 0.3]], ["return_rate"]) \
        == (0.2, "mean", "return_rate", 2)
    # A date that splits the named row: its days combine the way a series does.
    split = [["2026-08-17", "Shipped", 2], ["2026-08-18", "Shipped", 3], ["2026-08-18", "Complete", 9]]
    assert rk.figure_of(["day", "status", "order_count"], split, [], row=("Shipped",)) == (5.0, "row", "order_count", 3)
    # A declared measure wins; undeclared, the LAST numeric column is the finding's figure (theLook's
    # return-rate finding: `category, sold_lines, returned_lines, return_rate`).
    assert rk.figure_of(["cat", "sold", "returned"], [["Jeans", 10, 1]], ["sold"], row=("Jeans",)) == (10.0, "row", "sold", 1)
    assert rk.figure_of(["cat", "sold_lines", "returned_lines", "return_rate"],
                        [["Jeans", 10, 1, 0.1], ["Skirts", 20, 4, 0.2]], [], row=("Skirts",)) == (0.2, "row", "return_rate", 2)
    assert rk.figure_of(["cat"], [["a"], ["b"]], []) == (None, "", "", 2)
    assert rk.figure_of([], [], []) == (None, "", "", 0)


def test_the_row_a_finding_is_about_is_the_one_its_statement_names_first():
    status = (["status", "order_count"], [["Complete", "50"], ["Shipped", "60"], ["Returned", "25"]])
    said = "Current order status distribution: Shipped leads with 37,483 orders, followed by Complete (31,085)."
    assert rk.named_row(said, [status], [], []) == (True, ("Shipped",))
    # Whole words: "Men" is said in "Men's", never inside "Women".
    dept = (["department", "percentage_share"], [["Women", 24.7], ["Men", 38.4]])
    assert rk.named_row("The Men's department maintains a higher ratio of 38.39%", [dept], [], []) == (True, ("Men",))
    assert rk.named_row("The share for the Women category is 0.47, while Men hold 0.53", [dept], [], []) == (True, ("Women",))
    # The longer label on a tie.
    cats = (["category", "n"], [["Pants", 1], ["Pants & Capris", 2]])
    assert rk.named_row("Pants & Capris lead the catalog", [cats], [], []) == (True, ("Pants & Capris",))
    # A declared dimension is the label; a one-letter code is never taken as said, so a finding
    # about "male customers" over rows coded M and F names no row (theLook's average-age finding).
    gender = (["gender", "m_age"], [["M", 41.0], ["F", 40.9]])
    assert rk.named_row("The average age of male customers is 40.95, while female is 40.89.", [gender], [], ["gender"]) == (True, None)
    assert rk.named_row("Segment b holds a share of 40%", [(["segment", "share"], [["a", 0.6], ["b", 0.4]])], [], []) == (True, None)
    # Two labels: both must be said.
    two = (["category", "department", "ratio"], [["Outerwear & Coats", "Men", 2.1], ["Outerwear & Coats", "Women", 2.0]])
    assert rk.named_row("The retail value of the Outerwear & Coats category is the highest", [two], [], []) == (True, None)
    # A row the range has no data for is found in the compared range.
    assert rk.named_row("Skirts has the highest return rate", [(["category", "r"], [["Pants", 0.1]]),
                                                               (["category", "r"], [["Skirts", 0.2]])], [], []) == (True, ("Skirts",))
    # Dates and numbers label nothing: a series is not labelled, and names no row.
    assert rk.named_row("Orders climbed", [(["day", "n"], [["2026-08-17", 2], ["2026-08-18", 3]])], [], []) == (False, None)


def test_the_grain_is_the_first_read_table_with_a_main_date_or_why_not():
    assert rk.grain_for("SELECT COUNT(*) FROM products p JOIN orders o ON o.id = p.id", [], PROFILE, "duckdb") == ("orders", "created_at", "")
    assert rk.grain_for("SELECT COUNT(*) FROM products", [], PROFILE, "duckdb") == (None, "", "no date on products")
    assert rk.grain_for("SELECT 1", [], PROFILE, "duckdb") == (None, "", "its SQL names no table")


def test_findings_are_re_asked_for_both_ranges_and_ranked_by_the_change():
    findings = [
        {"id": "f1", "domain": "Orders", "sql": "SELECT status, COUNT(*) AS order_count FROM orders GROUP BY 1",
         "finding": "Shipped leads with 37,483 orders, followed by Complete.",
         "signature": {"tables": ["orders"], "measures": ["order_count"]}},
        # Labelled rows its statement does not name: no one row is its figure, and it says so.
        {"id": "f6", "domain": "Orders", "sql": "SELECT status, COUNT(*) AS order_count FROM orders GROUP BY 1",
         "finding": "Order statuses are spread evenly.", "signature": {"tables": ["orders"]}},
        {"id": "f2", "domain": "Orders", "sql": "SELECT COUNT(*) AS n FROM orders", "signature": {"tables": ["orders"]}},
        {"id": "f3", "domain": "Catalog", "sql": "SELECT COUNT(*) AS n FROM products", "signature": {"tables": ["products"]}},
        {"id": "f4", "domain": "Orders", "sql": "", "signature": {}},
        {"id": "f5", "domain": "Orders", "sql": "SELECT boom FROM orders", "signature": {"tables": ["orders"]}},
        # The aggregate view lists a pinned finding once per schema: the same (id, SQL) is asked once, and said.
        {"id": "f2", "domain": "Orders", "sql": "SELECT COUNT(*) AS n FROM orders", "signature": {"tables": ["orders"]}},
    ]
    run_sql, calls = _runner({"current": (["n"], [[10]], None), "previous": (["n"], [[8]], None)},
                             grouped={"current": (["status", "order_count"], [["Shipped", 6], ["Complete", 4]], None),
                                      "previous": (["status", "order_count"], [["Shipped", 4], ["Complete", 4]], None)})
    out = rk.reask_findings(findings, SPEC, run_sql=run_sql, dialect="duckdb", profile_entry=PROFILE)
    assert out["covers"] and out["compared_with"] and out["key"] == SPEC.key and out["capped"] == 0
    got = {r["id"]: r for r in out["reasked"]}
    assert set(got) == {"f1", "f2"}
    # f1 is about Shipped: 6 against 4, the row its statement names, not the 10 the rows add up to.
    assert got["f1"]["current"] == 6.0 and got["f1"]["previous"] == 4.0 and got["f1"]["how"] == "row"
    assert got["f1"]["row"] == ["Shipped"] and got["f2"]["row"] is None and got["f2"]["how"] == "value"
    assert got["f1"]["rel"] == 0.5 and got["f1"]["grain"] == "orders.created_at" and got["f1"]["rows_current"] == 2
    assert "2026-08-17" in got["f1"]["sql"] and "orders" in got["f1"]["sql"]
    # The compared range's statement rides too, cut on its own window: the rows behind "vs 8".
    assert got["f1"]["sql_previous"] != got["f1"]["sql"] and "orders" in got["f1"]["sql_previous"]
    assert calls[1] == got["f1"]["sql_previous"]
    assert [r["id"] for r in out["reasked"]] == ["f1", "f2"]
    apart = {a["id"]: a["why"] for a in out["apart"]}
    assert apart["f3"] == "no date on products" and apart["f4"] == "it kept no SQL"
    assert apart["f5"].startswith("its query failed for current: boom failed")
    assert apart["f6"] == "its statement names none of the rows its query returns, so no one row is its figure"
    # Every distinct finding in exactly one list; two queries per re-asked finding, one for the failed one.
    assert out["duplicates"] == 1
    assert len(out["reasked"]) + len(out["apart"]) == len(findings) - 1
    assert len(calls) == 3 * 2 + 1


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
    monkeypatch.setattr("aughor.tools.profile_cache.merged_profile_entry", lambda cid: PROFILE)
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
