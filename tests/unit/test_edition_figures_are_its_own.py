"""An edition's figures are its own range's and nothing else (the user, 2026-10-23).

LuxExperience's week of 12–18 October 2026 printed ten figures in "The week in numbers"; four were
other weeks — clienteling ends June 2025, markdowns April 2024, carts December 2024, inventory
snapshots June 2025 — each read over its own last week and dated in amber under its name, the box's
note saying "unless its own months are named". The user: *"The week range written under The Briefing
should make it clear… that written period should be the only one being compared."* The same rows
were candidate findings for the narrator, so a June 2025 move could lead an October edition.

Now a metric whose data ended before the range is NOT one of its figures: it is said as not measured,
with the day its data ends — in the Briefing and, at the user's word the same day, the Dashboard too. Its
own last week is not read at all.
"""
from __future__ import annotations

from datetime import date

from aughor.briefing import ranges
from aughor.semantic import metric_time as mt


class _Metric:
    status, connection, unit = "approved", "c", "count"
    time_kind, time_source, time_confirmed_by = "flow", "set by a person", "t"
    tables, filters = [], []
    version, owner, approved_by = 1, "", "t"

    def __init__(self, name: str, label: str, table: str):
        self.name, self.label = name, label
        self.time_column = f"lux.{table}.day"
        self.sql = f"SELECT COUNT(*) AS {name} FROM lux.{table}"


ORDERS = _Metric("orders", "Orders", "orders")              # live: rows to yesterday
CLIENTELING = _Metric("clienteling", "Clienteling GMV", "clienteling")   # stopped 2025-06-29


def _run_sql(sql: str):
    if "MAX(" in sql.upper():
        last = "2025-06-29" if "clienteling" in sql else "2026-10-22"
        return ["first_day", "last_day"], [("2024-01-01", last)], ""
    if "clienteling" in sql:
        if "current=2025-06-23" in sql:   # its own last week, and the week before
            return [], [("current", 13809, date(2025, 6, 23), date(2025, 6, 29), 40),
                        ("previous", 15574, date(2025, 6, 16), date(2025, 6, 22), 41)], ""
        return [], [("current", 0, None, None, 0), ("previous", 0, None, None, 0)], ""   # nothing this week
    return [], [("current", 520, date(2026, 10, 12), date(2026, 10, 18), 520),
                ("previous", 500, date(2026, 10, 5), date(2026, 10, 11), 500)], ""


def _measure(monkeypatch):
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda **k: [ORDERS, CLIENTELING])
    monkeypatch.setattr(mt, "ensure_dates", lambda *a, **k: {})
    monkeypatch.setattr(mt, "measure_sql", lambda m, windows, **k: (
        f"Q {m.name} " + " ".join(f"{w.label}={w.start}" for w in windows), ""))
    spec, _ = ranges.resolve_range("last_week", today=date(2026, 10, 23), lag_days=1)
    assert (spec.start, spec.last_day) == (date(2026, 10, 12), date(2026, 10, 18))
    return spec, ranges.measure_range("c", spec, run_sql=_run_sql, dialect="duckdb")


def test_a_metric_whose_data_ended_is_not_one_of_the_weeks_figures(monkeypatch):
    _spec, out = _measure(monkeypatch)
    assert [m["name"] for m in out["measured"]] == ["Orders"]
    assert not any(m.get("anchored") for m in out["measured"])
    [row] = out["unmeasured"]
    assert row["name"] == "Clienteling GMV"
    assert row["reason"] == "its data ends 2025-06-29, before this range"
    assert row["data_ends"] == "2025-06-29"


def test_its_own_last_week_is_not_read(monkeypatch):
    asked: list[str] = []

    def spy(sql):
        asked.append(sql)
        return _run_sql(sql)
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda **k: [ORDERS, CLIENTELING])
    monkeypatch.setattr(mt, "ensure_dates", lambda *a, **k: {})
    monkeypatch.setattr(mt, "measure_sql", lambda m, windows, **k: (
        f"Q {m.name} " + " ".join(f"{w.label}={w.start}" for w in windows), ""))
    spec, _ = ranges.resolve_range("last_week", today=date(2026, 10, 23), lag_days=1)
    out = ranges.measure_range("c", spec, run_sql=spy, dialect="duckdb")
    assert "latest" not in out["unmeasured"][0]
    assert not any("2025-06" in sql for sql in asked if sql.startswith("Q ")), asked


def test_the_narrator_is_offered_no_move_from_another_week(monkeypatch):
    spec, out = _measure(monkeypatch)
    block = {**ranges.range_block(spec), **out}
    found = ranges.range_findings(out["measured"], block, None)
    assert [f["id"].rsplit("::", 1)[1] for f in found] == ["orders"]
    assert not any("2025" in f["finding"] for f in found), found
    # The note it writes from names the metric as not measured for this week, and forbids a value.
    from aughor.knowledge.period_brief import period_note
    note = period_note(block, today=date(2026, 10, 23))
    assert "Not measured for this week: Clienteling GMV. Do not state a value" in note, note


def test_the_sent_edition_lists_it_as_not_measured_with_its_day(monkeypatch):
    spec, out = _measure(monkeypatch)
    block = {**ranges.range_block(spec), **out}
    ranges.say_figures(out["measured"], None)
    sections = dict(ranges.sheet_lines({"period": block}))
    assert len(sections["measured"]) == 1 and sections["measured"][0].startswith("Orders")
    assert sections["unmeasured"] == ["Not measured: Clienteling GMV — its data ends 2025-06-29, before this range."]
