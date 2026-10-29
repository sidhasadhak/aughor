"""Arc BG-3 (ROADMAP §3.66) — an edition written for one reader, behind two gates.

The model chooses and words; the code decides what may be shown. A number no measurement holds and a
sentence that claims a cause or a forecast are withheld — after one rewrite — and said. A figure more
than two standard deviations from usual reaches every reader: when the model leaves it out, the code
adds it. An edition is kept per reader, and a read never writes one.
"""
from __future__ import annotations

import contextlib
from datetime import date

import duckdb
import pytest

from aughor.briefing import edition as E
from aughor.briefing import guide as G
from aughor.briefing import ranges

OCT29 = date(2026, 10, 29)


# ── the gates ────────────────────────────────────────────────────────────────────────────────

ALLOWED = E._allowed([{"unit": "EUR", "current": 166988.0, "previous": 158815.0, "last_year": None,
                       "rel": 0.05146, "rel_last_year": None, "n": 259,
                       "usual": {"mean": 160960.0, "low": 149913.0, "high": 172007.0}, "streak": 0,
                       "extreme": {"which": "highest", "of": 13}, "cells": {}},
                      {"unit": "ratio 0..1", "current": 0.0205, "previous": 0.0208, "last_year": None,
                       "rel": None, "rel_last_year": None, "n": 9873, "usual": {}, "streak": -3,
                       "extreme": None, "cells": {}}], usual_n=8)


@pytest.mark.parametrize("text", [
    "Sales were €167.0k in the week of 19–25 October 2026.",
    "That is 5.1% more than the week before.",
    "2.05% of visits ended in an order, the third fall in a row.",
    "The highest of the 13 weeks read, on 259 orders.",
    "Inside its usual range of €149.9k to €172.0k.",
])
def test_a_measured_number_passes(text):
    assert E.unmeasured_numbers(text, ALLOWED) == []


@pytest.mark.parametrize("text,miss", [
    ("Sales were €190.0k.", "190.0k"),
    ("That is 12% more than the week before.", "12%"),
    ("About 21 more orders would have been placed.", "21"),
])
def test_a_number_nobody_measured_is_caught(text, miss):
    assert miss in " ".join(E.unmeasured_numbers(text, ALLOWED))


def test_a_cause_and_a_forecast_are_held_and_said():
    held = dict(E.held_sentences("Sales were €167.0k. Bigger baskets drove the week. Sales will rise next "
                                 "week. Visits held alongside fewer orders.", ALLOWED))
    assert "Sales were €167.0k." not in held
    assert "cause" in held["Bigger baskets drove the week."]
    assert "forecast" in held["Sales will rise next week."]
    assert "Visits held alongside fewer orders." not in held          # "alongside" describes, it claims nothing


# ── the writer ───────────────────────────────────────────────────────────────────────────────

def _fig(fid, label, current, z, *, floor=False, streak=0):
    return {"id": fid, "label": label, "name": label, "unit": "EUR", "better": "up", "why": "",
            "current": current, "previous": current * 0.95, "last_year": None, "rel": 0.05, "rel_last_year": None,
            "n": 100, "status": "final", "streak": streak, "extreme": None, "cells": {}, "floor": floor,
            "z": z, "outside": abs(z) >= 1,
            "usual": {"mean": current / (1 + 0.1 * z), "low": 90.0, "high": 110.0, "n": 8,
                      "mean_text": "€100", "low_text": "€90", "high_text": "€110"},
            "current_text": f"€{current:.0f}", "previous_text": f"€{current * 0.95:.0f}", "last_year_text": None,
            "like_for_like": "", "series": [], "sql": "SELECT 1"}


MEASURED = {"figures": [_fig("aov", "Average order", 145.0, 2.6, floor=True, streak=2),
                        _fig("sales", "Sales", 104.0, 0.4)],
            "unmeasured": [], "not_read": [], "floor": ["aov"], "usual_n": 8}


class _LLM:
    def __init__(self, *drafts):
        self.drafts, self.users = list(drafts), []

    def complete(self, *, system, user, response_model, temperature):
        self.users.append(user)
        return self.drafts.pop(0)


def _week():
    spec, _ = ranges.resolve_range("last_week", today=OCT29, lag_days=1, lag_source="learned")
    return spec


def test_a_broken_draft_is_rewritten_once_then_what_still_breaks_is_withheld():
    first = E.EditionDraft(headline="A big week", lede="Sales reached €999 this week.",
                           stories=[E.Story(check_ids=["sales"], reason="watch", title="Sales held",
                                            body="Sales were €104, inside the usual range.")])
    second = E.EditionDraft(headline="Sales held near usual", lede="Sales were €104. Promotions lifted sales.",
                            stories=[E.Story(check_ids=["sales"], reason="watch", title="Sales held",
                                             body="Sales were €104, inside the usual range of €90 to €110.")],
                            steady=[E.SteadyLine(check_id="aov", line="Average order €145.")])
    llm = _LLM(first, second)
    out = E.write(G.BriefingGuide(), E.ORGANISATION, ranges.range_block(_week()), MEASURED, _week(),
                  published=True, llm=llm)
    assert out["model_calls"] == 2 and "€999" in llm.users[1]          # the rewrite is told what broke
    assert out["lede"] == "Sales were €104."                            # the cause withheld, the rest kept
    assert out["withheld"] == [{"sentence": "Promotions lifted sales.", "why": out["withheld"][0]["why"]}]
    assert "cause" in out["withheld"][0]["why"]
    # the floor figure was never a story: the code carries it for every reader, never as "steady"
    assert [a["check_id"] for a in out["also_unusual"]] == ["aov"]
    assert "outside its usual range of €90 to €110" in out["also_unusual"][0]["line"]
    assert out["steady"] == []


def test_an_unusual_figure_is_shown_first_even_to_a_reader_who_does_not_watch_it():
    reader = G.Reader(group_id="finance", name="Finance", watches="cash", check_ids=["sales"])
    assert [f["id"] for f in E.candidates(MEASURED, reader)] == ["aov", "sales"]


def test_the_calendar_ahead_is_written_by_code():
    guide = G.BriefingGuide(calendar=[G.CalendarDay(name="Singles Day", when="11-11", source="calendar"),
                                      G.CalendarDay(name="Spring sale", when="03-20", source="data")])
    ahead = E._coming_up(guide, _week())
    assert ahead == [{"name": "Singles Day", "date": "2026-11-11", "line": "Singles Day, Wednesday 11 November.",
                      "source": "calendar"}]


# ── built, kept per reader, read without writing ─────────────────────────────────────────────

@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute("""CREATE TABLE orders AS
        SELECT d::DATE AS order_date,
               CASE WHEN d >= DATE '2026-10-19' AND d <= DATE '2026-10-25' THEN 160.0
                    ELSE 100.0 + (EXTRACT(week FROM d) % 3) * 4 END AS gmv
        FROM range(DATE '2026-06-01', DATE '2026-10-29', INTERVAL 1 DAY) t(d), range(30) k(i)""")
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


def test_an_edition_is_kept_per_reader_and_a_read_never_writes(con, monkeypatch, tmp_path):
    import aughor.knowledge.briefing as kb
    from aughor.routers import exploration as R

    monkeypatch.setattr(kb, "_CACHE_PATH", tmp_path / "briefing_cache.json")
    monkeypatch.setattr(ranges, "governed_metrics", lambda *a, **k: [])
    monkeypatch.setattr(ranges, "resolve_for", lambda *a, **k: (_week(), ""))
    monkeypatch.setattr("aughor.routers._shared.canonical_schema", lambda conn, schema: schema)
    monkeypatch.setattr("aughor.orgsettings.figure_currency", lambda *a, **k: "EUR")
    G.save("c9", None, G.BriefingGuide(
        checks=[G.Check(id="aov", label="Average order", sql="AVG(gmv)", tables=["orders"],
                        time_column="orders.order_date", unit="EUR", better="up")],
        readers=[G.Reader(group_id="finance", name="Finance", watches="cash", check_ids=["aov"])]),
        by="user:amit", publish=True)

    before = R.read_briefing_edition("c9", preset="last_week", reader="finance")
    assert before["built"] is False                                    # nothing written by reading

    draft = E.EditionDraft(headline="Baskets far above usual", lede="The average order was well above usual.",
                           stories=[E.Story(check_ids=["aov"], reason="unusual", title="Bigger baskets",
                                            body="The average order sat far outside its usual range.")])
    llm = _LLM(draft)
    entry = E.build("c9", _week(), scope_key="c9", reader_id="finance", llm=llm,
                    runner=lambda: contextlib.nullcontext((_run(con), "duckdb")))
    assert entry["reader"] == {"group_id": "finance", "name": "Finance"}
    assert entry["guide"]["state"] == "published" and entry["floor"] == ["aov"]
    assert entry["stories"][0]["figures"][0]["id"] == "aov"
    assert entry["version"]["kept"] is True

    after = R.read_briefing_edition("c9", preset="last_week", reader="finance")
    assert after["built"] is True and after["headline"] == "Baskets far above usual"
    other = R.read_briefing_edition("c9", preset="last_week", reader="")
    assert other["built"] is False                                     # another reader's edition is its own


def test_no_guide_no_edition(monkeypatch):
    with pytest.raises(LookupError):
        E.build("nobody", _week(), scope_key="nobody")


# ── what the live LuxExperience edition taught (2026-10-29) ──────────────────────────────────

def test_an_iso_day_is_a_date_not_a_figure():
    """"2026-04-30" lost its year to the year rule and read "30" as a figure: a true sentence withheld."""
    assert E.unmeasured_numbers("THE OUTNET has no orders after 2026-04-30.", ALLOWED) == []


def test_a_share_declared_as_a_ratio_reads_as_a_percentage_and_a_percent_keeps_its_sign():
    assert E._unit("ratio 0-1 (e-commerce typically 0.005-0.05)", [0.0205, 0.0217, None]) == "ratio 0..1"
    assert E._unit("ratio 0-1", [0.4, 1.7]) == "ratio 0-1"              # not a share when a value is past 1
    assert E._text(0.0205, "Session conversion", "ratio 0..1", "") == "2.05%"
    assert E._text(0.476, "Return rate", "ratio 0..1", "") == "47.6%"
    assert E._text(47.55, "Gross margin on items", "%", "").endswith("%")


def test_the_writer_is_told_weeks_not_ranges():
    fig = {**MEASURED["figures"][0], "extreme": {"which": "highest", "of": 9}, "streak": -4}
    out = E._for_model(fig, watched=False, period="week")
    assert out["extreme"] == "the highest of the last 9 weeks"
    assert out["in_a_row"] == "4 weeks in a row down"
    assert "the 8 weeks before" in out["usual_range"]
