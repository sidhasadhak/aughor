"""The Briefing on data that has ENDED (the Olist run, 2026-10-22; decided on the mockup 2026-10-23).

Olist's orders run from 2016-09-04 to 2018-10-17. Every edition anchored to today, so Day, Week, Month,
Year and both to-date editions could only ever be empty, and a range the reader typed in 2018 was told to
wait out a settling lag (Gaps 18 and 38). The user's decisions: when the data's newest day is more than a
month before today, each edition reads as if today were the day after the data's LAST ROW; its figures
are final; a comparison whose earlier range starts before the data does is withheld and says why; the
next range is not predicted; a scheduled send pauses while the edge does not move. Live data is
unchanged.
"""
from __future__ import annotations

import contextlib
from datetime import date

import duckdb
import pytest

from aughor.briefing import ranges

TODAY = date(2026, 10, 23)
LAST, FIRST = date(2018, 10, 17), date(2016, 9, 4)          # Olist's last and first purchase day
ENDED = {"through": LAST, "from": FIRST, "held_by": ["orders"], "tables": {"orders": LAST}, "why": ""}


def _ended(preset, edge=ENDED, **kw):
    spec, why = ranges.resolve_range(preset, today=TODAY, edge=edge, lag_days=2, **kw)
    assert spec is not None, why
    return spec


# ── the resolver ────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("preset, start, last_day, previous_start, previous_end, withheld", [
    ("yesterday", date(2018, 10, 17), date(2018, 10, 17), date(2018, 10, 10), date(2018, 10, 11), False),
    ("last_week", date(2018, 10, 8), date(2018, 10, 14), date(2018, 10, 1), date(2018, 10, 8), False),
    ("last_month", date(2018, 9, 1), date(2018, 9, 30), date(2018, 8, 1), date(2018, 9, 1), False),
    ("last_year", date(2017, 1, 1), date(2017, 12, 31), date(2016, 1, 1), date(2017, 1, 1), True),
    ("month_to_date", date(2018, 10, 1), date(2018, 10, 17), date(2018, 9, 1), date(2018, 9, 18), False),
    ("year_to_date", date(2018, 1, 1), date(2018, 10, 17), date(2017, 1, 1), date(2017, 10, 18), False),
    ("current_month", date(2018, 10, 1), date(2018, 10, 17), date(2018, 9, 1), date(2018, 9, 18), False),
    ("previous_month", date(2018, 9, 1), date(2018, 9, 30), date(2018, 8, 1), date(2018, 9, 1), False),
])
def test_each_edition_reads_as_if_today_were_the_day_after_the_last_row(preset, start, last_day, previous_start,
                                                                        previous_end, withheld):
    spec = _ended(preset)
    assert (spec.start, spec.last_day, spec.previous_start, spec.previous_end) == (
        start, last_day, previous_start, previous_end)
    # final: no settling lag, nothing still moving, and dated today
    assert (spec.data_ended, spec.lag_days, spec.lag_source, spec.still_moving) == (True, 0, "data_ended", ())
    assert spec.as_of == TODAY and spec.data_through == LAST and spec.data_from == FIRST
    assert bool(spec.compare_withheld) is withheld


def test_the_edition_says_where_the_data_ended_in_the_ended_voice():
    month = _ended("last_month")
    assert month.edge_note == ("The data ended on 2018-10-17 (Wednesday). Each edition reads as if today "
                               "were the day after, so this one covers September 2018.")
    assert "arrived yet" not in month.edge_note             # a live source's words, false of data that stopped
    words = ranges.phrases(_ended("month_to_date"))
    assert words["covers"] == "October 2018 to the data's last day, 2018-10-01 to 2018-10-17"
    assert "so far" not in ranges.phrases(_ended("current_month"))["covers"]


def test_a_comparison_the_data_only_partly_covers_is_withheld_and_says_why():
    """2017 against a 2016 the data holds from September read +13,558% on Olist's raw files."""
    year = _ended("last_year")
    assert year.compare_withheld == "the data starts on 2016-09-04, so 2016 holds only part of its days"
    assert ranges.phrases(year)["compared_with"] == f"no earlier period ({year.compare_withheld})"
    assert ranges.compared_word(year) == "no earlier period"
    # a month whose year-earlier range starts before the data loses that comparison too, silently
    # only because the line that names it is gone: the block has no last-year label to say it with
    oct16 = _ended("last_month", edge={**ENDED, "through": date(2017, 10, 20)})
    assert (oct16.start, oct16.last_year_start) == (date(2017, 9, 1), None)
    block = ranges.range_block(year)
    assert block["data_ended"] is True and block["data_from"] == "2016-09-04"
    assert block["compare_withheld"] == year.compare_withheld


@pytest.mark.parametrize("age, ended", [(31, False), (32, True)])
def test_data_ends_only_when_its_newest_day_is_more_than_a_month_old(age, ended):
    """Live data — theLook settles 29 days late — is never "ended"; the line is STOPPED_DAYS."""
    from datetime import timedelta
    through = TODAY - timedelta(days=age)
    spec = _ended("last_month", edge={**ENDED, "through": through, "tables": {"orders": through}})
    assert spec.data_ended is ended
    if not ended:
        assert (spec.lag_days, spec.start) == (2, date(2026, 9, 1))    # exactly as before


def test_a_custom_range_over_ended_data_is_final_and_cut_at_the_last_row():
    """Gap 38: "the range ends 2 days before today because of a 2-day settling lag", of August 2018."""
    aug = _ended("custom", start=date(2018, 8, 1), end=date(2018, 8, 31))
    assert (aug.start, aug.last_day, aug.lag_days, aug.data_ended) == (date(2018, 8, 1), date(2018, 8, 31), 0, True)
    assert aug.edge_note == "The data ended on 2018-10-17 (Wednesday)."
    past = _ended("custom", start=date(2018, 10, 1), end=date(2018, 10, 31))
    assert past.last_day == LAST
    assert past.edge_note.startswith("Asked to 2018-10-31, read to 2018-10-17. The data ended on")


def test_the_narrator_is_told_the_figures_are_final_and_never_to_mention_settling():
    from aughor.knowledge.period_brief import period_note
    note = period_note(ranges.range_block(_ended("last_month")), today=TODAY)
    assert "The data ended on 2018-10-17" in note and "every figure in it is final" in note
    assert "settling lag" not in note
    year = period_note(ranges.range_block(_ended("last_year")), today=TODAY)
    assert "It is not compared with an earlier period, because the data starts on 2016-09-04" in year
    assert "compares it with" not in year


def test_the_sent_markdown_and_the_narrator_context_say_final():
    from aughor.briefing.delivery import render_period_markdown
    from aughor.knowledge.brief_context import _period_lines
    block = ranges.range_block(_ended("last_year"))
    md = render_period_markdown(block, [], 0)
    assert "*Not compared: the data starts on 2016-09-04" in md and "every figure here is final" in md
    assert "settling" not in md
    said = " ".join(_period_lines(block))
    assert "the data ended on 2018-10-17, so every figure is final" in said and "not settled" not in said


# ── measuring ───────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def olist(monkeypatch, tmp_path):
    """One order a day worth 100 from Olist's first day to its last, and an approved revenue."""
    monkeypatch.setenv("AUGHOR_METRICS_PATH", str(tmp_path / "metrics.instance.json"))
    from aughor.semantic.metrics import MetricDefinition, save_metric
    save_metric(MetricDefinition(name="gmv", connection="c1", label="GMV", sql="SUM(amount)", tables=["orders"],
                                 unit="BRL", status="approved", approved_by="test",
                                 time_kind="flow", time_column="orders.created_at"))   # dated, as Olist's GMV is
    monkeypatch.setattr("aughor.tools.profile_cache.latest_profile_entry", lambda cid: {
        "tables": {"orders": {"primary_timestamp": "created_at"}},
        "columns": {f"orders.{c}": {"table": "orders", "column": c, "dtype": d}
                    for c, d in (("created_at", "TIMESTAMP"), ("amount", "DOUBLE"))}})
    c = duckdb.connect()
    c.execute("""CREATE TABLE orders AS SELECT d::TIMESTAMP + INTERVAL 9 HOUR AS created_at, 100.0 AS amount
                 FROM range(DATE '2016-09-04', DATE '2018-10-18', INTERVAL 1 DAY) t(d)""")

    @contextlib.contextmanager
    def runner():
        def run_sql(sql):
            try:
                cur = c.execute(sql)
                return [d[0] for d in cur.description], cur.fetchall(), None
            except Exception as exc:  # noqa: BLE001
                return [], [], str(exc)
        yield run_sql, "duckdb"
    ranges._EDGE_CACHE.clear()
    yield runner
    c.close()


def test_the_edge_reads_where_the_data_starts_as_well_as_where_it_ends(olist):
    edge = ranges.data_edge("c1", today=TODAY, runner=olist)
    assert (edge["through"], edge["from"]) == (LAST, FIRST)


def test_a_withheld_comparison_is_measured_without_its_earlier_value_and_says_why(olist):
    with olist() as (run_sql, dialect):
        year = ranges.measure_range("c1", _ended("last_year"), run_sql=run_sql, dialect=dialect)
        month = ranges.measure_range("c1", _ended("last_month"), run_sql=run_sql, dialect=dialect)
    [y] = year["measured"]
    assert y["current"] == 36500.0 and y["previous"] is None and y["rel"] is None
    line = ranges.metric_line(y, ranges.range_block(_ended("last_year")), "BRL")
    assert line.endswith("it is not compared, because the data starts on 2016-09-04, so 2016 holds only "
                         "part of its days."), line
    assert "has no rows" not in line                       # the earlier range is not empty: it is partial
    [m] = month["measured"]
    assert (m["current"], m["previous"], m["compare_withheld"]) == (3000.0, 3100.0, "")
    assert m["rel"] == pytest.approx(-100 / 3100)


def test_nothing_is_predicted_after_the_data_ended():
    from aughor.briefing.expected import expected_next
    got = expected_next("c1", _ended("last_month"), today=TODAY)
    assert got == {"target": None, "items": [],
                   "why": "the data ended on 2018-10-17: no later range will have rows to predict"}


def test_what_each_edition_covers_lists_six_with_the_lead_figure(olist, monkeypatch):
    monkeypatch.setattr(ranges, "data_edge", lambda conn_id, schema=None, today=None: ENDED)
    got = ranges.edition_covers("c1", runner=olist, today=TODAY)
    assert (got["data_ended"], got["data_through"], got["data_from"]) == (True, "2018-10-17", "2016-09-04")
    assert got["metric"] == {"name": "gmv", "label": "GMV"}
    rows = {r["preset"]: r for r in got["editions"]}
    assert [r["label"] for r in got["editions"]] == ["Day", "Week", "Month", "Year", "Month to date", "Year to date"]
    assert rows["last_month"]["covers"] == "September 2018" and rows["last_month"]["rel"] == pytest.approx(-100 / 3100)
    assert rows["last_month"]["current_text"] and rows["last_month"]["previous_text"]
    assert rows["last_year"]["compare_withheld"] and rows["last_year"]["rel"] is None
    assert rows["yesterday"]["start"] == rows["yesterday"]["last_day"] == "2018-10-17"
    assert (rows["last_month"]["previous_start"], rows["last_month"]["previous_last_day"]) == ("2018-08-01", "2018-08-31")


# ── the send and Now ────────────────────────────────────────────────────────────────────────

def _sub(**kw):
    from aughor.briefing.models import BriefSubscription
    return BriefSubscription(id="s1", conn_id="c1", name="Olist daily", period="day", content="briefing",
                             trigger_id="t1", schema_name="olist", **kw)


@pytest.mark.parametrize("ended, sent_before, paused", [(True, True, True), (True, False, False), (False, True, False)])
def test_a_scheduled_send_pauses_while_ended_data_does_not_move(monkeypatch, ended, sent_before, paused):
    """Data that stopped sends the same edition every morning; the first goes, the repeats pause, and
    the send resumes by itself when new rows move the edge (the edition then covers new days)."""
    from aughor.briefing import delivery
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: name == "briefing.ranges")
    edge = ENDED if ended else {**ENDED, "through": date(2026, 10, 21), "tables": {"orders": date(2026, 10, 21)}}
    asked: dict = {}

    def resolve_for(conn_id, preset, *, workspace_id=None, schema=None, **_):
        asked.update(preset=preset, schema=schema)
        return ranges.resolve_range(preset, today=TODAY, edge=edge, lag_days=2)
    monkeypatch.setattr(ranges, "resolve_for", resolve_for)
    monkeypatch.setattr("aughor.briefing.deliveries.sent_at_for",
                        lambda conn_id, sub_id, covers: "2026-10-22T07:00:00Z" if sent_before else None)
    why = delivery._paused_on_ended_data(_sub())
    assert asked == {"preset": "yesterday", "schema": "olist"}         # the subscription's own dataset
    assert bool(why) is paused
    if paused:
        assert why == ("paused: the data ended on 2018-10-17 and has not moved since the Briefing for "
                       "2018-10-17 (Wednesday) was sent on 2026-10-22; sending resumes when new rows arrive")


def test_a_paused_send_builds_nothing_and_records_why(monkeypatch):
    from aughor.briefing import delivery
    monkeypatch.setattr(delivery, "_paused_on_ended_data", lambda sub: "paused: the data ended on 2018-10-17")
    monkeypatch.setattr(delivery, "_turned_off", lambda sub: "")
    monkeypatch.setattr("aughor.knowledge.period_brief.refusal", lambda period: "")
    monkeypatch.setattr(delivery, "build_period_departure",
                        lambda sub: (_ for _ in ()).throw(AssertionError("a paused send built a Briefing")))
    result: dict = {"status": "failed", "error": None}
    delivery._deliver_period(_sub(), None, result)
    assert result == {"status": "paused", "error": "not sent — paused: the data ended on 2018-10-17"}


def test_now_names_what_the_kept_edition_covers_and_where_the_data_ended(monkeypatch):
    from aughor.briefing import organisation
    monkeypatch.setattr(organisation, "_visible_connections", lambda: [{"id": "c1", "name": "Olist"}])
    monkeypatch.setattr(organisation, "latest_kept", lambda cid: {"id": "a1", "version": 1, "payload": {
        "as_of": "2026-10-23", "briefing": {"narrative": "September GMV fell.", "period": {
            "covers": "September 2018", "data_ended": True, "data_through": "2018-10-17"}}}})
    [row] = organisation.organisation_briefing()["briefings"]
    assert (row["covers"], row["data_ended"], row["data_through"]) == ("September 2018", True, "2018-10-17")
