"""One answer to what can be said of a source's days, read by every surface.

A source redrawn whole at each refresh was told to readers, to the model and to other agents as one that "settles after
29 days" (measured 2026-11-04, every row across one refresh). Each surface below now reads the one answer, which comes
only from a source's own readings: these tests hand a surface a reading and check what it then says or does, with no
connection named anywhere, so a source connected tomorrow gets the same behaviour.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from aughor.briefing import ranges
from aughor.settling.answer import answer_from, answer_of_block, settling_answer

REWRITES = {"days": 29, "source": "beyond_horizon", "still_moving": ["items", "sales"], "horizon": 28, "rewrites": ["items", "sales"]}
MIXED = {"days": 29, "source": "beyond_horizon", "still_moving": ["items", "sales"], "horizon": 28, "rewrites": ["items"]}
MOVING = {"days": 15, "source": "beyond_horizon", "still_moving": ["items"], "horizon": 14, "rewrites": []}
SETTLES = {"days": 3, "source": "learned", "still_moving": [], "horizon": 14, "rewrites": []}
UNKNOWN = {"days": None, "source": None, "still_moving": [], "horizon": 0, "rewrites": []}
TODAY = date(2026, 11, 4)


@pytest.fixture
def source(monkeypatch):
    """Every reader goes through `store.connection_lag`, so this is the one place a source's reading comes from."""
    def set_reading(lag):
        monkeypatch.setattr("aughor.settling.store.connection_lag", lambda cid: lag)
    return set_reading


def _spec(lag: dict, preset: str = "last_week", **kw):
    spec, _ = ranges.resolve_range(preset, today=TODAY, lag_days=lag["days"] or 1, lag_source=lag["source"] or "default",
                                   still_moving=tuple(lag["still_moving"]), rewrites=tuple(lag["rewrites"]), horizon=lag["horizon"], **kw)
    return spec


# ── the answer ───────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("lag, kind, never", [(REWRITES, "rewrites", True), (MOVING, "moving", True),
                                              (SETTLES, "settles", False), (UNKNOWN, "unknown", False)])
def test_a_reading_gives_one_of_four_answers(lag, kind, never):
    said = answer_from(lag)
    assert said.kind == kind and said.never_settled is never


def test_each_answer_says_only_what_its_source_shows():
    assert "no day in them settles" in answer_from(REWRITES).says() and "items and sales change at every age" in answer_from(REWRITES).says()
    assert "items was still changing 14 days after a day ended" in answer_from(MOVING).says()
    assert answer_from(SETTLES).says() == "A day's numbers stop changing 3 days after it ends, which the platform measured."
    assert "has not read this source for long enough" in answer_from(UNKNOWN).says()
    # a floor is never called a lag it settles at, and a measured lag is never called a floor
    for lag in (REWRITES, MOVING):
        assert "settles after" not in answer_from(lag).says() and "learned" not in answer_from(lag).clause()
    assert "learned from observation" in answer_from(SETTLES).clause()


def test_a_table_rewriting_and_a_table_only_moving_are_each_said_for_what_they_are():
    said = answer_from(MIXED)
    assert said.kind == "rewrites" and said.moving == ("items", "sales") and said.rewrites == ("items",)
    assert "items changes at every age, so no day in it settles" in said.says()
    assert "sales was still changing 28 days after a day ended" in said.says()
    assert said.clause().startswith("items rewrites its history at each refresh, so no day in it settles, and sales was still")
    assert said.as_block()["tables"] == ["items", "sales"]


def test_it_is_said_of_a_table_or_of_them_as_its_tables_are_counted():
    assert "Treat every figure read from them as provisional" in answer_from(REWRITES).for_agents()
    assert "Treat every figure read from it as provisional" in answer_from(MOVING).for_agents()
    assert answer_from(REWRITES).clause().startswith("items and sales rewrite their history")
    assert answer_from(MOVING).clause() == "items was still changing 14 days after a day ended and has not been seen to stop"


def test_an_age_not_known_is_not_said_as_a_number():
    kept = answer_of_block({"lag_days": 0, "lag_source": "beyond_horizon", "still_moving": ["items"]})
    assert "still changing at the oldest age read" in kept.says() and "0 days" not in kept.says()


@pytest.mark.parametrize("reads, kind, tables", [
    ({"sql": "SELECT SUM(x) FROM items"}, "rewrites", ("items",)),
    ({"sql": "SELECT SUM(x) FROM analytics.sales"}, "moving", ("sales",)),
    ({"sql": "SELECT SUM(x) FROM items JOIN sales ON items.id = sales.id"}, "rewrites", ("items", "sales")),
    ({"sql": "SELECT SUM(x) FROM users"}, "unknown", ()),
    ({"sql": "SELECT 1", "time_column": "items.sold_at"}, "rewrites", ("items",)),    # dated by it, with no table named
    ({"sql": "not a statement at all"}, "rewrites", ("items", "sales")),               # which tables is not known: the whole source
    (None, "rewrites", ("items", "sales")),
])
def test_an_answer_is_narrowed_to_what_a_figure_reads(reads, kind, tables):
    said = answer_from(MIXED).about(reads)
    assert said.kind == kind and said.moving == tables


def test_narrowing_leaves_a_source_with_nothing_to_say_as_it_was():
    assert answer_from(SETTLES).about({"sql": "SELECT 1 FROM items"}).kind == "settles"


def test_a_dataset_that_ended_with_its_tables_settled_has_no_answer_to_give():
    edge = {"through": date(2018, 10, 17), "from": date(2016, 1, 1), "tables": {}}
    ended, _ = ranges.resolve_range("last_month", today=TODAY, lag_days=1, edge=edge)
    assert ended.data_ended and ranges.range_block(ended)["settling"] is None
    paused, _ = ranges.resolve_range("last_month", today=TODAY, lag_days=29, lag_source="beyond_horizon", still_moving=("items",), horizon=28, edge=edge)
    block = ranges.range_block(paused)
    assert (block["settling"] or {}).get("kind") == "moving" and "still changing 28 days" in block["settling"]["says"]


def test_two_tables_are_said_as_two():
    two = answer_from({**MOVING, "still_moving": ["items", "sales"]}).says()
    assert two.startswith("items and sales were still changing") and "have not been seen to stop" in two


def test_an_agent_is_told_what_to_do_about_it_and_nothing_when_nothing_is_known():
    for lag in (REWRITES, MOVING):
        told = answer_from(lag).for_agents()
        assert "provisional" in told and "do not read a difference against an earlier period as a move" in told
    assert "for 3 days after it ends (learned from observation)" in answer_from(SETTLES).for_agents()
    assert answer_from(UNKNOWN).for_agents() == "" and answer_from(UNKNOWN).clause() == ""


def test_a_block_carries_the_same_answer_and_one_kept_from_before_reads_from_what_it_holds():
    block = ranges.range_block(_spec(REWRITES))
    assert block["settling"]["kind"] == "rewrites" and block["rewrites"] == ["items", "sales"]
    assert block["settling"]["says"] == answer_of_block(block).says()
    kept = {"lag_days": 15, "lag_source": "beyond_horizon", "still_moving": ["items"]}
    assert answer_of_block(kept).kind == "moving" and answer_of_block({"lag_days": 3, "lag_source": "learned"}).kind == "settles"
    assert answer_of_block({"lag_days": 1, "lag_source": "default"}).kind == "unknown" and answer_of_block(None).kind == "unknown"


def test_an_unreadable_store_claims_nothing(monkeypatch):
    def boom(cid):
        raise OSError("gone")
    monkeypatch.setattr("aughor.settling.store.connection_lag", boom)
    assert settling_answer("c1").kind == "unknown" and settling_answer("").kind == "unknown"


def test_the_answer_names_no_connection():
    text = Path("aughor/settling/answer.py").read_text().lower()
    assert not any(name in text for name in ("thelook", "luxexperience", "8233e4fd", "dcc63d83"))


# ── a dashboard tile ─────────────────────────────────────────────────────────────────────

def test_a_range_is_provisional_while_a_table_it_reads_has_not_been_seen_to_stop():
    from aughor.dashboards.host import FINAL, PROVISIONAL, status_of
    old = SimpleNamespace(preset="custom", under_way=False, as_of=TODAY, lag_days=1, last_day=TODAY - timedelta(days=60),
                          still_moving=("items",))
    assert status_of(old) == PROVISIONAL                                     # the connection's own read
    assert status_of(old, {"tables": ["analytics.items"]}) == PROVISIONAL    # however the card spells it
    assert status_of(old, {"tables": ["sales"]}) == FINAL                    # another table's card is not held back
    assert status_of(SimpleNamespace(**{**old.__dict__, "still_moving": ()}), {"tables": ["items"]}) == FINAL


# ── a send with no guide ─────────────────────────────────────────────────────────────────

UNREAD = {"equal": False, "why": "Revenue reads a source that rewrites its whole history at each refresh."}
FIGURE = {"name": "Revenue", "metric": "revenue", "unit": "$", "current": 136.0, "previous": 124.0, "rel": 0.097, "status": "provisional",
          "sql": "SELECT 1", "equal_age": UNREAD}
SHARE = {"name": "Return rate", "metric": "return_rate", "unit": "ratio 0..1", "current": 0.14, "previous": 0.15, "rel": -0.05,
         "status": "provisional", "sql": "SELECT 1", "equal_age": {"equal": False, "why": "Return rate reads a source that rewrites its whole history at each refresh."}}
READ = {"name": "Cost", "metric": "cost", "unit": "$", "current": 136.0, "previous": 124.0, "rel": 0.097, "status": "final", "sql": "SELECT 1",
        "equal_age": {"equal": True, "why": ""}}


def test_a_figure_not_at_equal_age_is_sent_without_the_phrase_that_ranks_a_move():
    block = ranges.range_block(_spec(REWRITES))
    for m in (FIGURE, SHARE):
        line = ranges.metric_line(m, block, "USD")
        assert "moved from" not in line and "up " not in line and "down " not in line, line
        assert line.endswith("— not read as a move.")
    assert "14.0%" in ranges.metric_line(SHARE, block, "USD") and "15.0%" in ranges.metric_line(SHARE, block, "USD")


def test_a_figure_at_equal_age_still_reads_as_a_move():
    block = ranges.range_block(_spec(SETTLES))
    assert "not read as a move" not in ranges.metric_line(READ, block, "USD")
    assert "moved from" in ranges.metric_line({**SHARE, "equal_age": {"equal": True}}, block, "USD")


def test_only_a_figure_at_equal_age_is_a_candidate_to_lead():
    block = ranges.range_block(_spec(REWRITES))
    found = ranges.range_findings([FIGURE, READ, SHARE], block, "USD")
    assert [f["id"].rsplit("::", 1)[1] for f in found] == ["cost"]


def test_what_a_range_did_not_read_leaves_with_it():
    block = {**ranges.range_block(_spec(REWRITES)), "measured": [FIGURE, SHARE, READ]}
    sections = dict(ranges.sheet_lines({"period": block}))
    said = sections.get("not_read") or [""]
    assert len(said) == 1 and said[0].startswith("Revenue and Return rate: each reads a source that rewrites")
    assert "usual" not in said[0]              # a send with no guide read the period before, not a usual range
    assert "not_read" not in dict(ranges.sheet_lines({"period": {**block, "measured": [READ]}}))


def test_what_an_edition_did_not_read_leaves_with_it():
    from aughor.briefing.compose.write import sheet_lines
    out = dict(sheet_lines({"not_read": [{"label": "Revenue against its usual range", "reason": "it is not read against usual"},
                                         {"label": "a guide's note", "reason": ""}]}))
    assert out.get("not_read") == ["Revenue against its usual range: it is not read against usual"]
    assert "not_read" not in dict(sheet_lines({}))


def test_a_send_is_headed_by_what_is_true_of_its_source():
    from aughor.briefing.delivery import _SHEET_TITLES, render_period_markdown
    md = render_period_markdown(ranges.range_block(_spec(REWRITES)), [], 0)
    assert "rewrites its history at each refresh" in md and "settling as late rows arrive" not in md
    md = render_period_markdown(ranges.range_block(_spec(SETTLES, preset="last_week")), [], 0)
    assert "rewrites its history" not in md and "settling as late rows arrive, a lag the platform measured" in md
    assert _SHEET_TITLES["not_read"] == "Not read as a move" and "Still settling" not in _SHEET_TITLES["early"]
    assert render_period_markdown.__doc__ and "as it leaves" in render_period_markdown.__doc__


def test_the_narrator_is_told_of_a_source_that_rewrites():
    from aughor.knowledge.period_brief import period_note
    note = period_note(ranges.range_block(_spec(REWRITES)), TODAY)
    assert "rewrites its history at each refresh" in note and "do not call any figure from it final" in note
    assert "do not read a difference against an earlier period as a move" in note
    moving = period_note(ranges.range_block(_spec(MOVING)), TODAY)
    assert "rewrites" not in moving and "do not read a difference against an earlier period as a move" in moving
    assert "a difference against an earlier period" not in period_note(ranges.range_block(_spec(SETTLES)), TODAY)


def test_a_block_read_back_into_a_conversation_says_the_same():
    from aughor.knowledge.brief_context import _period_lines
    said = " ".join(_period_lines({"covers": "August", "lag_days": 29, "lag_source": "beyond_horizon", "still_moving": ["items"], "rewrites": ["items"]}))
    assert "rewrites its history" in said and "may still change" not in said and "not settled" not in said
    said = " ".join(_period_lines({"covers": "August", "lag_days": 3, "lag_source": "learned"}))
    assert "the newest 3 days of data may still change" in said and "rewrites" not in said


def test_the_desk_says_a_source_that_rewrites_as_one():
    from aughor.briefing import desk
    out = desk.gaps([], [], {"lag_days": 29, "key": "k", "lag_source": "beyond_horizon", "still_moving": ["items"], "rewrites": ["items"]})
    assert out[0]["title"] == "Figures are read 29 days behind" and "rewrites its history" in out[0]["text"]


def test_the_guide_writer_is_not_told_a_floor_is_a_settling_lag(source, monkeypatch):
    from aughor.briefing import guide
    monkeypatch.setattr("aughor.briefing.ranges.data_edge", lambda *a, **k: {"tables": {}})
    monkeypatch.setattr("aughor.briefing.ranges.governed_metrics", lambda *a, **k: [])
    monkeypatch.setattr("aughor.business_profile.infer.gather_context", lambda *a, **k: ("", []))
    monkeypatch.setattr("aughor.business_profile.store.load_raw", lambda *a, **k: {})
    source(REWRITES)
    told = guide._context("c1", None, today=TODAY)
    assert "READ BEHIND: 29 days" in told and "SETTLING LAG" not in told and "rewrites its history" in told
    source(SETTLES)
    told = guide._context("c1", None, today=TODAY)
    assert "SETTLING LAG: 3 days" in told and "READ BEHIND" not in told


# ── what other agents are told ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("lag", [REWRITES, MOVING])
def test_the_conversation_is_not_told_a_floor_is_a_learned_lag(source, lag):
    from aughor.agent.converse_tools import converse_system_prompt
    source(lag)
    told = converse_system_prompt("c1")
    assert answer_from(lag).for_agents() in told and "learned from observation" not in told


def test_an_intake_window_says_why_it_was_cut_in_the_answers_words():
    from aughor.agent.investigate import _clamp_intake_to_coverage
    intake = SimpleNamespace(observation_start="2026-09-10", observation_end="2026-09-23", observation_label="Last two weeks",
                             comparison_start="2026-08-27", comparison_end="2026-09-09", comparison_label="Prior two weeks",
                             cross_sectional=False, intake_notes="")
    note = _clamp_intake_to_coverage(intake, "2025-01-01", "2026-09-23", question="what changed?", today="2026-09-23", settle_days=29,
                                     settle_clause=answer_from(REWRITES).clause())
    assert "items and sales rewrite their history at each refresh, so no day in them settles" in note and "learned from observation" not in note


def test_a_scheduled_run_is_told_whatever_lag_its_step_reads_at():
    from aughor.automations.temporal import scheduled_grounding
    auto = SimpleNamespace(id="a1", conditions=[SimpleNamespace(kind="schedule", config={"cron": "0 7 * * *"})])
    told = answer_from(REWRITES).for_agents()
    assert told in scheduled_grounding(auto, {}, learned_lag=29, never_settles=told)
    assert told in scheduled_grounding(auto, {"observation_lag_days": 40}, learned_lag=29, never_settles=told)
    assert "rewrites its history" not in scheduled_grounding(auto, {}, learned_lag=3)


# ── a re-checked answer ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", ["moving", "rewrites"])
def test_a_change_on_a_source_never_seen_to_settle_is_neither_late_rows_nor_a_restatement(kind):
    from aughor.answer.recheck import classify
    changes = [{"day": "2026-09-20"}, {"day": "2026-01-01"}]
    assert classify(changes, date(2026, 9, 21), 29, kind) == kind and {c["cause"] for c in changes} == {kind}


@pytest.mark.parametrize("cause, told", [("rewrites", False), ("moving", True), ("late_rows", True)])
def test_a_source_redrawn_at_each_refresh_does_not_tell_anyone_each_time_it_was(monkeypatch, cause, told):
    from aughor.answer import recheck
    sent, recorded = [], []
    monkeypatch.setattr(recheck, "measure_answer", lambda answer, **kw: {"status": "changed", "cause": cause, "changes": [{}]})
    monkeypatch.setattr(recheck, "tell", lambda answer, entry: sent.append(entry) or {"status": "sent"})
    monkeypatch.setattr(recheck, "_record", lambda answer, entry: recorded.append(entry))
    recheck.recheck_and_tell({"connection_id": "c1"})
    assert bool(sent) is told and len(recorded) == 1                # recorded either way, and said on the answer


@pytest.mark.parametrize("lag, cause", [(REWRITES, "rewrites"), (MOVING, "moving"), (SETTLES, "restated")])
def test_a_recheck_records_what_is_true_of_its_source(source, lag, cause):
    from aughor.answer import recheck
    source(lag)
    answer = {"connection_id": "c1", "created_at": "2026-10-20T00:00:00Z",
              "report": {"sql": "SELECT day, n FROM items", "columns": ["day", "n"], "rows": [["2026-09-20", 100]]}}
    entry = recheck.measure_answer(answer, run_sql=lambda sql: (["day", "n"], [["2026-09-20", 140]], None))
    assert entry["status"] == "changed" and entry["cause"] == cause
    assert entry["settling_says"] == (answer_from(lag).about({"sql": "SELECT day, n FROM items"}).says() if lag is not SETTLES else "")


def test_a_recheck_of_an_answer_on_a_settled_table_is_not_blamed_on_its_sibling(source):
    from aughor.answer import recheck
    source({**REWRITES, "still_moving": ["events"], "rewrites": ["events"]})
    answer = {"connection_id": "c1", "created_at": "2026-10-20T00:00:00Z",
              "report": {"sql": "SELECT day, n FROM items", "columns": ["day", "n"], "rows": [["2026-09-20", 100]]}}
    entry = recheck.measure_answer(answer, run_sql=lambda sql: (["day", "n"], [["2026-09-20", 140]], None))
    assert entry["cause"] == "restated" and entry["settling_says"] == ""


def test_rows_that_vanished_on_a_redrawn_source_have_the_same_cause_and_tell_nobody(source, monkeypatch):
    from aughor.answer import recheck
    source(REWRITES)
    sent = []
    monkeypatch.setattr(recheck, "tell", lambda answer, entry: sent.append(entry) or {"status": "sent"})
    monkeypatch.setattr(recheck, "_record", lambda answer, entry: None)
    answer = {"connection_id": "c1", "created_at": "2026-10-20T00:00:00Z",
              "report": {"sql": "SELECT day, n FROM items", "columns": ["day", "n"], "rows": [["2026-09-20", 100], ["2026-09-21", 90]]}}
    entry = recheck.recheck_and_tell(answer, run_sql=lambda sql: (["day", "n"], [["2026-09-20", 100]], None))
    assert entry["status"] == "changed" and entry["cause"] == "rewrites" and sent == []


def test_a_metric_card_on_a_table_still_moving_is_not_at_equal_age(monkeypatch):
    import contextlib

    from aughor.routers import cards
    from aughor.semantic import metric_time as mt

    @contextlib.contextmanager
    def runner(conn_id):
        yield (lambda sql: ([], [], None)), "duckdb"

    monkeypatch.setattr("aughor.knowledge.period_brief.connection_runner", runner)
    monkeypatch.setattr(mt, "declared", lambda m: True)
    monkeypatch.setattr(mt, "run_measure", lambda *a, **k: ([{"window": "current", "value": 7}, {"window": "previous", "value": 5}], ""))
    card = SimpleNamespace(connection_id="c1", refresh=SimpleNamespace(model_dump=lambda: {}))
    metric = SimpleNamespace(name="revenue", version=1, status="approved", time_column="items.sold_at", tables=["items"], sql="")
    spec = _spec(MOVING, preset="last_month")
    old = ranges.RangeSpec(**{**spec.__dict__, "lag_days": 1})     # its days are old enough: only the table holds it back
    assert cards._metric_card_for_range(card, metric, old, True)["previous"]["equal_age"] is False
    other = ranges.RangeSpec(**{**old.__dict__, "still_moving": ("sales",)})
    assert cards._metric_card_for_range(card, metric, other, True)["previous"]["equal_age"] is True


def test_no_segment_is_asked_to_explain_a_figure_not_read_as_a_move(monkeypatch):
    from aughor.briefing import recipes
    seen = []
    metrics = [SimpleNamespace(name=n, status="approved", connection="c1") for n in ("revenue", "cost")]
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda connection_id=None: metrics)
    monkeypatch.setattr("aughor.tools.profile_cache.merged_profile_entry", lambda cid: {})
    monkeypatch.setattr(recipes, "what_moved", lambda ms, *a, **k: seen.extend(m.name for m in ms) or {"moves": [], "thin": []})
    got = {"measured": [FIGURE, READ], "period": ranges.range_block(_spec(REWRITES))}
    recipes.apply("c1", _spec(REWRITES), got, run_sql=lambda sql: ([], [], None), dialect="duckdb", domain_data={}, currency="USD", block=got["period"])
    assert seen == ["cost"]


# ── a metric's move and a watch ──────────────────────────────────────────────────────────

def test_a_chart_reading_a_table_still_moving_reports_no_move():
    from aughor.knowledge.metric_moves import compute_metric_moves
    trend = (["month", "gross_margin_pct"], [["Jan", 50.0], ["Mar", 49.0], ["May", 47.0], ["Sep", 49.0], ["Nov", 43.0], ["Dec", 34.0]])
    metrics = [SimpleNamespace(name="Margin", chart_sql="SELECT month, m FROM analytics.items", unit_or_range="%", definition="d")]
    run_sql = lambda sql: (*trend, None)  # noqa: E731
    assert compute_metric_moves(metrics, run_sql, "USD") != []
    assert compute_metric_moves(metrics, run_sql, "USD", still_moving=("items",)) == []
    assert compute_metric_moves(metrics, run_sql, "USD", still_moving=("sales",)) != []


def test_the_key_movements_door_passes_the_tables_of_a_source_never_seen_to_settle(source):
    from aughor.routers.exploration import _still_moving
    source(MIXED)
    assert _still_moving("c1") == ("items", "sales")           # the table only moving too, not only the rewriting one
    source(SETTLES)
    assert _still_moving("c1") == ()


@pytest.mark.parametrize("lag, says", [(REWRITES, True), (MOVING, True), (SETTLES, False), (UNKNOWN, False)])
def test_a_watch_keeps_firing_and_its_alert_says_what_is_true_of_its_source(source, monkeypatch, lag, says):
    from aughor.monitors import runner
    from aughor.monitors.models import Monitor
    monkeypatch.setattr(runner, "_last_alert_value", lambda mid: None)
    monkeypatch.setattr(runner, "_guard_caveats", lambda m, db: None)
    source(lag)
    floor = Monitor(conn_id="c1", name="Floor", custom_sql="SELECT SUM(price) FROM items", alert_on="threshold_cross",
                    threshold_direction="below", warning_threshold=900.0)
    run = runner.check_monitor(floor, SimpleNamespace(scalar=lambda sql, **k: 848.0), suppress=False)
    assert run.alert is not None and run.alert.severity == "warning"
    assert (answer_from(lag).about({"sql": "SELECT SUM(price) FROM items"}).says() in (run.alert.caveat or "")) is says


def test_a_watch_on_a_table_that_settled_does_not_carry_its_siblings_caveat(source, monkeypatch):
    from aughor.monitors import runner
    from aughor.monitors.models import Monitor
    monkeypatch.setattr(runner, "_last_alert_value", lambda mid: None)
    monkeypatch.setattr(runner, "_guard_caveats", lambda m, db: None)
    source(MOVING)
    floor = Monitor(conn_id="c1", name="Floor", custom_sql="SELECT SUM(price) FROM sales", alert_on="threshold_cross",
                    threshold_direction="below", warning_threshold=900.0)
    run = runner.check_monitor(floor, SimpleNamespace(scalar=lambda sql, **k: 848.0), suppress=False)
    assert run.alert is not None and not run.alert.caveat
    # a watch over a metric is narrowed by what the metric reads
    monkeypatch.setattr(runner, "_reading_sql", lambda m, db: ("SELECT 1", "duckdb"))
    watch = Monitor(conn_id="c1", name="Floor", metric_name="revenue", alert_on="threshold_cross",
                    threshold_direction="below", warning_threshold=900.0)
    for read, says in (("items", True), ("sales", False)):
        monkeypatch.setattr(runner, "_metric_of", lambda m, read=read: SimpleNamespace(tables=[read], sql="", time_column=f"{read}.sold_at"))
        run = runner.check_monitor(watch, SimpleNamespace(scalar=lambda sql, **k: 848.0), suppress=False)
        assert run.alert is not None and ("items was still changing" in (run.alert.caveat or "")) is says


def test_a_review_of_a_missed_day_recognises_both_words_for_too_new():
    from aughor.monitors.missed import MissReview, is_miss
    for verdict in ("Revenue read 160. That day is too new to score.", "Revenue read 160. That day is still settling."):
        assert is_miss(MissReview(connection_id="c", metric="r", day="2026-09-20", value=160.0, verdict=verdict)) is False


# ── a date that waits for it ─────────────────────────────────────────────────────────────

def test_a_decision_is_not_reviewed_on_a_settling_lag_it_does_not_have(source):
    from aughor.record.decisions import propose_review_on
    source(REWRITES)
    _on, why = propose_review_on("c1")
    assert "has not been seen to settle" in why and "learned settling lag" not in why
    source(SETTLES)
    _on, why = propose_review_on("c1")
    assert "the connection's learned settling lag of 3 days" in why


def test_an_inquiry_does_not_wait_for_days_to_settle_on_a_source_that_will_not():
    from aughor.record.inquiry import _settled_by
    gap = "September is still settling: 21 of 30 days"
    assert _settled_by(gap, 29, answer_from(REWRITES)) == "nothing will: this source rewrites its history at each refresh"
    assert _settled_by(gap, 15, answer_from(MOVING)).startswith("reading it again may not: items was still changing")
    assert _settled_by(gap, 3, answer_from(SETTLES)) == "the connection's settling lag: 3 days"
    assert _settled_by("no courier data", 29, answer_from(REWRITES)) == ""


def test_the_inquiry_a_moved_floor_opens_does_not_ask_about_a_settling_lag(monkeypatch):
    from aughor.record import inquiry, signals
    asked = []
    monkeypatch.setattr(inquiry, "open_inquiry", lambda question, **kw: asked.append(question) or SimpleNamespace(id="q1"))
    monkeypatch.setattr(signals, "_emit", lambda *a, **k: None)
    signals.on_settling_sampled("c1", MOVING, {**MOVING, "days": 29})
    assert "how far behind this source is read moved from 15 to 29 days" in asked[0] and "settling lag" not in asked[0]


def test_a_moved_floor_is_not_called_a_settling_lag():
    from aughor.record.signals import settling_signal
    sig = settling_signal(MOVING, {**MOVING, "days": 29})
    assert "how far behind this source is read moved from 15 to 29 days" in sig["text"] and "settling lag" not in sig["text"]
    assert "the settling lag moved from 3 to 7 days" in settling_signal(SETTLES, {**SETTLES, "days": 7})["text"]
