"""Tell people when an answer goes stale (IDEAS.md 5, PENDING.md item 8, ROADMAP §3.28).

"On Tuesday we told you 1,744. With the rows that arrived since, it is now 1,902." What these
hold: the answer's own query is re-run and compared row by row on its own labels; a move
inside the noise band is not news; a stored table that is not that query's result is not
compared, and says so; late rows are told apart from a restatement only when the platform has
LEARNED the source's lag; the re-check is recorded on the answer, appended; a Slack answer is
told in its own thread through the departure gate; nothing is told twice; off means nothing.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import duckdb
import pytest

from aughor.answer import recheck
from aughor.db.history import get_chat_answer, save_chat_turn

FLAG_ENV = "AUGHOR_ANSWERS_RECHECK"
ANSWERED = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 9, 23, 6, 0, tzinfo=timezone.utc)
DAILY = ("SELECT CAST(created_at AS DATE) AS day, COUNT(*) AS orders FROM orders "
         "WHERE created_at >= TIMESTAMP '2026-09-15' GROUP BY 1 ORDER BY 1")


@pytest.fixture
def con():
    c = duckdb.connect()
    # 1,744 orders on each day 15..20 Sep, as the source held them when the answer was given
    c.execute("""CREATE TABLE orders AS SELECT DATE '2026-09-15' + (i % 6)::INT
                 + INTERVAL 12 HOUR AS created_at FROM range(0, 6 * 1744) t(i)""")
    yield c
    c.close()


def run_on(con):
    def run_sql(sql):
        cur = con.execute(sql)
        return [d[0] for d in cur.description], [list(r) for r in cur.fetchall()], None
    return run_sql


def answer_from(con, *, session_id="web-session-1", sql=DAILY) -> dict:
    cols, rows, _ = run_on(con)(sql)
    rows = [[str(r[0]), r[1]] for r in rows]
    inv = save_chat_turn(question="How many orders did we get each day last week?",
                         connection_id="conn1", headline="1,744 orders a day",
                         sql=sql, session_id=session_id, columns=cols, rows=rows)
    answer = get_chat_answer(inv if isinstance(inv, str) else inv["id"])
    answer["completed_at"] = ANSWERED.isoformat()
    return answer


@pytest.fixture
def lag(monkeypatch):
    import aughor.settling.store as settling
    state = {"lag": 3}
    monkeypatch.setattr(settling, "learned_lag_days", lambda conn_id: state["lag"])
    return state


# ── comparing ───────────────────────────────────────────────────────────────────────────────

def test_a_change_past_the_noise_band_is_found_on_its_own_row():
    old = [["2026-09-19", 1744], ["2026-09-20", 1744], ["2026-09-18", 1000]]
    new = [["2026-09-19", 1760], ["2026-09-20", 1902], ["2026-09-21", 50]]
    d = recheck.diff_results(["day", "orders"], old, ["day", "orders"], new)
    assert d["comparable"] and d["compared"] == 2
    assert [(c["label"], c["old"], c["new"], c["day"]) for c in d["changes"]] == [
        ({"day": "2026-09-20"}, 1744.0, 1902.0, "2026-09-20")]        # +0.9% on the 19th is noise
    assert (d["missing_rows"], d["new_rows"]) == (1, 1)


def test_a_table_that_is_not_the_querys_result_is_not_compared():
    d = recheck.diff_results(["Region", "Revenue ($)"], [["EU", "1,200"]],
                             ["region", "revenue"], [["EU", 1300]])
    assert not d["comparable"] and "not this query's result" in d["reason"]


def test_a_single_number_is_compared_and_unlabelled_rows_are_refused():
    one = recheck.diff_results(["total"], [[100]], ["total"], [[130]])
    assert one["comparable"] and one["changes"][0]["rel"] == pytest.approx(0.30)
    many = recheck.diff_results(["total"], [[1], [2]], ["total"], [[1], [3]])
    assert not many["comparable"] and "no label" in many["reason"]


def test_late_rows_restatement_and_unknown_are_told_apart():
    answered_on = date(2026, 9, 21)
    late = [{"day": "2026-09-20"}]
    assert recheck.classify(late, answered_on, 3) == "late_rows"          # 20th > 21st - 3
    settled = [{"day": "2026-09-10"}]
    assert recheck.classify(settled, answered_on, 3) == "restated"
    assert recheck.classify([{"day": "2026-09-20"}], answered_on, None) == "unknown"
    assert recheck.classify([{"day": None}], answered_on, 3) == "unknown"


# ── end to end ──────────────────────────────────────────────────────────────────────────────

def test_late_rows_on_a_web_answer_are_recorded_on_it_and_shown(con, lag):
    answer = answer_from(con)
    con.execute("INSERT INTO orders SELECT TIMESTAMP '2026-09-20 23:00' FROM range(0, 158)")
    entry = recheck.recheck_and_tell(answer, run_sql=run_on(con), now=LATER)
    assert entry["status"] == "changed" and entry["cause"] == "late_rows" and entry["lag_days"] == 3
    assert [(c["label"]["day"], c["old"], c["new"]) for c in entry["changes"]] == [
        ("2026-09-20", 1744.0, 1902.0)]
    assert entry["told"] == {"door": "web", "status": "shown",
                             "note": "shown on the answer; the web keeps no inbox to push it to"}
    stored = get_chat_answer(answer["id"])["report"]
    assert stored["rows"][-1] == ["2026-09-20", 1744]            # what was said stays as said
    assert stored["rechecks"][-1]["changes"][0]["new"] == 1902.0
    text = recheck.correction_text(answer, entry)
    assert "We told you orders for 2026-09-20 was 1,744; it is now 1,902 (+9.1%)." in text
    assert "These are late rows: this source's numbers settle after 3 days" in text
    # the same change is news once
    again = recheck.recheck_and_tell(get_chat_answer(answer["id"]) | {"completed_at": ANSWERED.isoformat()},
                                     run_sql=run_on(con), now=LATER)
    assert again["told"] == {"status": "already_told"}


def test_an_unchanged_answer_records_that_it_was_checked(con, lag):
    answer = answer_from(con)
    entry = recheck.recheck_and_tell(answer, run_sql=run_on(con), now=LATER)
    assert entry["status"] == "unchanged" and entry["compared"] == 6 and "told" not in entry


def test_without_a_learned_lag_the_cause_is_not_guessed(con, lag):
    lag["lag"] = None
    answer = answer_from(con)
    con.execute("INSERT INTO orders SELECT TIMESTAMP '2026-09-16 09:00' FROM range(0, 400)")
    entry = recheck.measure_answer(answer, run_sql=run_on(con), now=LATER)
    assert entry["cause"] == "unknown"
    assert "cannot say whether these are late rows or a restatement" in recheck.correction_text(answer, entry)


def test_a_slack_answer_is_told_in_its_own_thread_through_the_gate(con, lag, monkeypatch):
    from types import SimpleNamespace

    import aughor.slackbots.post as post
    import aughor.slackbots.store as bots
    bot = SimpleNamespace(id="b1", enabled=True, bot_token="xoxb-test", name="Aughor")
    monkeypatch.setattr(bots, "bots_for_agent", lambda agent_id: [])
    monkeypatch.setattr(bots, "list_bots", lambda include_disabled=True: [bot])
    monkeypatch.setattr(bots, "get_bot_decrypted", lambda bot_id: bot)
    sent = []
    monkeypatch.setattr(post, "post_as_bot", lambda token, channel, text, thread_ts=None:
                        (sent.append((channel, thread_ts, text)) or True, {"ts": "1726.9"}))
    answer = answer_from(con, session_id="slack:C0TEAM:1726000000.000100")
    con.execute("INSERT INTO orders SELECT TIMESTAMP '2026-09-20 23:00' FROM range(0, 158)")
    entry = recheck.recheck_and_tell(answer, run_sql=run_on(con), now=LATER)
    told = entry["told"]
    assert told["door"] == "slack" and told["status"] == "sent", told
    assert told["departure_id"]                                   # the gate recorded it
    channel, thread_ts, text = sent[0]
    assert (channel, thread_ts) == ("C0TEAM", "1726000000.000100")
    assert text.startswith("On 2026-09-21 you asked:") and "it is now 1,902" in text
    from aughor.govern.departure_store import get_departure
    row = get_departure(told["departure_id"])
    assert row["kind"] == "answer_correction" and row["investigation_id"] == answer["id"]


def test_two_bots_and_no_binding_means_no_reply_and_says_why(con, lag, monkeypatch):
    from types import SimpleNamespace

    import aughor.slackbots.store as bots
    monkeypatch.setattr(bots, "bots_for_agent", lambda agent_id: [])
    monkeypatch.setattr(bots, "list_bots", lambda include_disabled=True: [
        SimpleNamespace(id="b1", enabled=True), SimpleNamespace(id="b2", enabled=True)])
    answer = answer_from(con, session_id="slack:C0TEAM:1726000000.000100")
    con.execute("INSERT INTO orders SELECT TIMESTAMP '2026-09-20 23:00' FROM range(0, 158)")
    entry = recheck.recheck_and_tell(answer, run_sql=run_on(con), now=LATER)
    assert entry["told"] == {"door": "slack", "status": "not_sent",
                             "note": "more than one Slack bot, and none is bound to the agent that answered"}


def test_a_query_that_fails_now_is_recorded_as_unchecked(con, lag):
    answer = answer_from(con)
    con.execute("DROP TABLE orders")
    entry = recheck.recheck_and_tell(answer, run_sql=lambda sql: ([], [], "Table orders does not exist"),
                                     now=LATER)
    assert entry["status"] == "unchecked" and entry["reason"].startswith("re-running its query failed")


# ── the daily pass and the doors ────────────────────────────────────────────────────────────

def test_off_by_default_nothing_runs(monkeypatch):
    monkeypatch.delenv(FLAG_ENV, raising=False)
    assert recheck.enabled() is False
    assert recheck.run_rechecks_daily(force=True) == {"skipped": "off"}


def test_the_daily_pass_runs_once_a_day_and_skips_fresh_rechecks(con, lag, monkeypatch):
    monkeypatch.setenv(FLAG_ENV, "1")
    monkeypatch.setattr(recheck, "_last_run_day", None)
    from aughor.db import history
    answer = answer_from(con)
    real = history.recent_chat_answers
    monkeypatch.setattr(history, "recent_chat_answers",
                        lambda since, limit=200: [a | {"completed_at": ANSWERED.isoformat()}
                                                  for a in real("2000-01-01", limit=limit)
                                                  if a["id"] == answer["id"]])
    first = recheck.run_rechecks_daily(now=LATER, runner=lambda conn: run_on(con))
    assert first == {"checked": 1, "changed": 0, "told": 0}
    assert recheck.run_rechecks_daily(now=LATER, runner=lambda conn: run_on(con)) == {
        "skipped": "already ran today"}
    forced = recheck.run_rechecks_daily(now=LATER, force=True, runner=lambda conn: run_on(con))
    assert forced == {"checked": 0, "changed": 0, "told": 0}      # re-checked < 20h ago


def test_the_recheck_door_is_refused_while_off(monkeypatch):
    from fastapi import HTTPException

    from aughor.routers.investigations import recheck_investigation
    monkeypatch.delenv(FLAG_ENV, raising=False)
    with pytest.raises(HTTPException) as off:
        recheck_investigation("x", principal=None)
    assert off.value.status_code == 404 and "answers.recheck" in off.value.detail


def test_a_slack_session_id_names_its_thread():
    assert recheck.slack_thread("slack:C0TEAM:1726000000.000100") == ("C0TEAM", "1726000000.000100")
    assert recheck.slack_thread("web-session-1") is None


def test_a_restored_turn_carries_the_recheck_only_once_one_found_a_change(con, lag):
    from aughor.db.history import get_session_turns
    from aughor.routers.investigations import _turn_to_ui_messages
    answer = answer_from(con, session_id="web-restore-1")

    def parts():
        turn = get_session_turns("web-restore-1")[0]
        return turn, [p["type"] for m in _turn_to_ui_messages(turn) for p in m["parts"]]

    turn, kinds = parts()
    assert "latest_recheck" not in turn and "data-recheck" not in kinds      # as before
    recheck.recheck_and_tell(answer, run_sql=run_on(con), now=LATER)          # unchanged
    assert "data-recheck" not in parts()[1]
    con.execute("INSERT INTO orders SELECT TIMESTAMP '2026-09-20 23:00' FROM range(0, 158)")
    recheck.recheck_and_tell(answer, run_sql=run_on(con), now=LATER)
    turn, kinds = parts()
    assert "data-recheck" in kinds and turn["latest_recheck"]["changes"][0]["new"] == 1902.0


# ── what the review of this branch found (2026-09-24), each fixed at its cause ───────────────

def test_a_query_relative_to_today_is_not_rechecked(con, lag):
    """"Revenue yesterday" re-run tomorrow measures another day; telling the difference as a
    correction would be false."""
    answer = answer_from(con, sql="SELECT CAST(created_at AS DATE) AS day, COUNT(*) AS orders FROM orders "
                                  "WHERE created_at >= CURRENT_DATE - INTERVAL 30 DAY GROUP BY 1")
    entry = recheck.measure_answer(answer, run_sql=run_on(con), now=LATER)
    assert entry["status"] == "unchecked" and "relative to today" in entry["reason"]


def test_a_monthly_bucket_changed_by_late_rows_is_late_rows():
    """A September total labelled 2026-09-01 changed by rows on the 22nd, answered on the 23rd with
    a one-day lag: the bucket held unsettled days, so late rows — not a restatement."""
    d = recheck.diff_results(["month", "orders"], [["2026-08-01", 5000], ["2026-09-01", 4000]],
                             ["month", "orders"], [["2026-08-01", 5000], ["2026-09-01", 4400]])
    assert d["changes"][0]["span_days"] == 31
    assert recheck.classify(d["changes"], date(2026, 9, 23), 1) == "late_rows"
    august = recheck.diff_results(["month", "orders"], [["2026-08-01", 5000], ["2026-09-01", 4000]],
                                  ["month", "orders"], [["2026-08-01", 5600], ["2026-09-01", 4000]])
    assert recheck.classify(august["changes"], date(2026, 9, 23), 1) == "restated"


def test_a_row_that_vanished_is_a_change_and_is_said(con, lag):
    answer = answer_from(con)
    con.execute("DELETE FROM orders WHERE CAST(created_at AS DATE) = DATE '2026-09-15'")
    entry = recheck.measure_answer(answer, run_sql=run_on(con), now=LATER)
    assert entry["status"] == "changed" and entry["missing_rows"] == 1 and entry["changes"] == []
    assert "1 row the answer gave is no longer returned (such as 2026-09-15)." in recheck.correction_text(answer, entry)


def test_a_move_from_zero_states_no_percentage():
    d = recheck.diff_results(["total"], [[0]], ["total"], [[12]])
    assert d["changes"][0]["rel"] is None
    text = recheck.correction_text({"completed_at": "2026-09-21", "question": "How many?"},
                                   {"changes": d["changes"], "cause": "unknown", "lag_days": None})
    assert "We told you total was 0; it is now 12." in text and "%" not in text


def test_the_daily_pass_reaches_the_answer_checked_longest_ago_first(con, lag, monkeypatch):
    monkeypatch.setenv(FLAG_ENV, "1")
    monkeypatch.setattr(recheck, "_last_run_day", None)
    monkeypatch.setattr(recheck, "PER_RUN", 1)
    from aughor.db import history
    old, new = answer_from(con, session_id="s-old"), answer_from(con, session_id="s-new")
    history.append_recheck(new["id"], {"checked_at": "2026-09-20T06:00:00Z", "status": "unchanged"})
    history.append_recheck(old["id"], {"checked_at": "2026-09-10T06:00:00Z", "status": "unchanged"})
    real = history.recent_chat_answers
    monkeypatch.setattr(history, "recent_chat_answers",
                        lambda since, limit=200: [a for a in real("2000-01-01", limit=limit)
                                                  if a["id"] in (old["id"], new["id"])])
    recheck.run_rechecks_daily(now=LATER, runner=lambda conn: run_on(con))
    assert get_chat_answer(old["id"])["report"]["rechecks"][-1]["checked_at"].startswith("2026-09-23")
    assert get_chat_answer(new["id"])["report"]["rechecks"][-1]["checked_at"].startswith("2026-09-20")


def test_the_banner_comes_down_when_a_later_recheck_finds_the_answer_as_said(con, lag):
    from aughor.db.history import get_session_turns
    answer = answer_from(con, session_id="web-banner")
    con.execute("INSERT INTO orders SELECT TIMESTAMP '2026-09-20 23:00' FROM range(0, 158)")
    recheck.recheck_and_tell(answer, run_sql=run_on(con), now=LATER)
    assert "latest_recheck" in get_session_turns("web-banner")[0]
    con.execute("DELETE FROM orders WHERE created_at = TIMESTAMP '2026-09-20 23:00'")
    recheck.recheck_and_tell(answer, run_sql=run_on(con), now=LATER)
    assert "latest_recheck" not in get_session_turns("web-banner")[0]
