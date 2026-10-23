"""A metric's move compares whole, settled periods — and is recorded with its derivation.

2026-10-11, luxexperience's standing Briefing led with "Web session conversion has fallen from 100% to 31%". The move
compared the series' first month — 39 sessions, all converted — with October, eleven days old; every whole month in
between read about 2% rising to 31%. GMV "−57%" and returns "26% → 1%" were October's part-month too. And the claim
opened onto no derivation: a move was never recorded the way an explorer finding is, so its Evidence was a stand-in
and "Open in Ask" started cold.
"""
from __future__ import annotations

from datetime import date

import duckdb
import pytest

from aughor.knowledge import metric_moves as MM

CONVERSION_SQL = ("SELECT date_trunc('month', session_start::date) AS month, "
                  "SUM(CASE WHEN converted THEN 1 ELSE 0 END)::numeric/NULLIF(COUNT(*),0) AS conversion_rate "
                  "FROM web_sessions GROUP BY 1 ORDER BY 1;")
METRIC = {"name": "Web Session Conversion Rate", "unit_or_range": "ratio 0-1", "chart_sql": CONVERSION_SQL,
          "definition": "Converted sessions divided by all sessions."}
DAY = date(2026, 10, 11)


@pytest.fixture
def sessions():
    """luxexperience's shape: a 39-session first month all converted, whole months at ~2% then ~31%, an October
    still open — big enough (200 of September's 300) that only its being open leaves it out."""
    con = duckdb.connect()
    con.execute("CREATE TABLE web_sessions (session_start TIMESTAMP, converted BOOLEAN)")
    for day, n, converted in (("2020-06-20", 39, 39), ("2020-07-10", 1000, 20), ("2020-08-10", 1000, 23),
                              ("2026-08-10", 400, 124), ("2026-09-10", 300, 94), ("2026-10-05", 200, 62)):
        con.execute(f"INSERT INTO web_sessions SELECT TIMESTAMP '{day} 10:00', i < {converted} FROM range({n}) t(i)")
    yield con
    con.close()


def _runner(con):
    def run(sql):
        cur = con.execute(sql)
        return [d[0] for d in cur.description], cur.fetchall(), None
    return run


def test_the_move_compares_the_first_and_last_whole_months_and_says_what_it_left_out(sessions):
    [move] = MM.compute_metric_moves([METRIC], _runner(sessions), "EUR", settled_through=DAY,
                                     scope="luxexperience", measured_at="2026-10-11T17:00:00+00:00")
    assert move["id"] == "metric-move::luxexperience.web_session_conversion_rate"
    assert move["finding"] == ("Web Session Conversion Rate has risen from 2.0% to 31.3% (+1467%) "
                               "between Jul 2020 and Sep 2026.")
    assert move["generated_at"] == "2026-10-11T17:00:00+00:00"
    d = move["dossier"]
    assert d["asked_by"] == "briefing" and d["sql"] == CONVERSION_SQL and d["finding"] == move["finding"]
    assert d["question"] == "How has Web Session Conversion Rate moved between its first and last whole months?"
    assert d["result_cells"].startswith("Jul 2020: 0.02 over 1,000 rows · Sep 2026: 0.313")
    assert d["result_cells"].endswith("over 300 rows")
    assert d["rationale"].startswith("Web Session Conversion Rate: Converted sessions divided by all sessions. ")
    assert "Left out: Oct 2026 — the month is not over yet; Jun 2020 — 39 rows, a part of a month." in d["rationale"]


def test_without_a_settled_edge_an_open_period_whole_by_its_rows_is_compared(sessions):
    [move] = MM.compute_metric_moves([METRIC], _runner(sessions), "EUR")
    assert move["finding"].endswith("between Jul 2020 and Oct 2026.")          # its 200 rows read as whole


def test_a_period_the_data_stopped_in_is_a_part_of_one_even_when_it_is_over():
    rows = [("2025-01-01", 10.0), ("2025-02-01", 12.0), ("2025-03-01", 14.0), ("2025-04-01", 3.0)]
    counts = {"2025-01-01": 900, "2025-02-01": 950, "2025-03-01": 1000, "2025-04-01": 120}
    mv = MM.series_move(["m", "v"], rows, counts=counts, open_from=DAY)
    assert (mv.start_label, mv.end_label, mv.start_rows, mv.end_rows) == ("Jan 2025", "Mar 2025", 900, 1000)
    assert mv.left_out == ("Apr 2025 — 120 rows, a part of a month",)
    # the engine may hand one statement's labels back as DATEs and its rewrite's as TIMESTAMPs: one period, one key
    dated = [(date.fromisoformat(d), v) for d, v in rows]
    keyed = {MM.period_key(f"{d} 00:00:00"): n for d, n in counts.items()}
    assert MM.series_move(["m", "v"], dated, counts=keyed, open_from=DAY).end_label == "Mar 2025"


def test_rows_that_cannot_be_counted_leave_out_the_period_the_data_begins_in_and_say_so():
    rows = [("Jun 2020", 1.0), ("Jul 2020", 0.02), ("Aug 2020", 0.023), ("Sep 2020", 0.025)]
    mv = MM.series_move(["m", "v"], rows, uncounted_start=True)
    assert (mv.start, mv.start_label) == (0.02, "Jul 2020")
    assert mv.left_out == ("Jun 2020 — the month the data begins in; its rows could not be counted",)


def test_a_move_only_part_periods_could_make_is_not_called():
    rows = [("2025-01-01", 1.0), ("2025-02-01", 2.0), ("2025-03-01", 3.0)]
    assert MM.series_move(["m", "v"], rows, counts={"2025-01-01": 5, "2025-02-01": 900, "2025-03-01": 950}) is None


def test_a_series_without_dates_or_counts_compares_its_ends_as_before():
    rows = [("Jan 2022", 50.0), ("Mar 2022", 49.0), ("Dec 2022", 34.0)]
    mv = MM.series_move(["m", "v"], rows)
    assert (mv.start, mv.end, mv.left_out) == (50.0, 34.0, ())


def test_the_rows_behind_each_period_are_counted_by_the_charts_own_statement(sessions):
    sql = MM.period_rows_sql(CONVERSION_SQL)
    assert "COUNT(*) AS period_rows" in sql and "GROUP BY" in sql and "conversion_rate" not in sql
    counts = MM.period_rows(CONVERSION_SQL, _runner(sessions))
    assert counts == {"2020-06-01": 39, "2020-07-01": 1000, "2020-08-01": 1000, "2026-08-01": 400,
                      "2026-09-01": 300, "2026-10-01": 200}
    assert MM.period_rows_sql("SELECT 1 UNION ALL SELECT 2") is None
    assert MM.period_rows_sql("SELECT COUNT(*) FROM web_sessions") is None      # one figure, no periods
    summed = ("WITH m AS (SELECT date_trunc('month', session_start) AS month, COUNT(*) AS n FROM web_sessions "
              "GROUP BY 1) SELECT month, SUM(n) FROM m GROUP BY 1 ORDER BY 1")
    assert MM.period_rows(summed, _runner(sessions)) is None                    # one row a period says nothing


def test_a_recorded_move_opens_onto_its_derivation_and_the_joins_its_table_stands_on(sessions):
    from aughor.explorer.dossier import _key, record_measured, update_dossier
    from aughor.kernel.ledger import Ledger

    [move] = MM.compute_metric_moves([METRIC], _runner(sessions), "EUR", settled_through=DAY, scope="lux")
    dossier = move.pop("dossier")
    state = {"join_verifications": [{"from_table": "web_sessions", "to_table": "customers", "cardinality": "N:1",
                                     "verified": True, "orphan_count": 0},
                                    {"from_table": "orders", "to_table": "customers", "cardinality": "N:1",
                                     "verified": True, "orphan_count": 0}]}
    record_measured("conn-moves", move, dossier, state=state)
    rec = Ledger.default().receipt(_key("conn-moves", move["id"]))
    got = rec["artifact"]["payload"]
    assert got["finding"] == move["finding"] and got["sql"] == CONVERSION_SQL
    assert got["dossier"]["question"] == dossier["question"]
    assert [j["to_table"] for j in got["dossier"]["structural_ctx"]["joins"]] == ["customers"]   # its table only
    # the Briefing's sentence about it then joins the record, as an explorer finding's does
    assert update_dossier("conn-moves", move["id"], merge={"narrative": "Conversion rose."}) is not None
    assert Ledger.default().receipt(_key("conn-moves", move["id"]))["artifact"]["payload"]["dossier"][
        "narrative"] == "Conversion rose."


def test_the_briefing_records_each_moves_derivation_and_keeps_the_candidate_lean(monkeypatch):
    from aughor.routers import exploration as R

    recorded = []
    monkeypatch.setattr("aughor.explorer.dossier.record_measured",
                        lambda conn, finding, dossier, *, state: recorded.append((conn, finding["id"], dossier)))
    monkeypatch.setattr(R, "_load_state", lambda conn, schema: {"schema": schema})
    moves = [{"id": "metric-move::lux.gmv", "sql": "SELECT 1", "dossier": {"question": "q"}}]
    R._record_moves("c1", "lux", moves)
    assert recorded == [("c1", "metric-move::lux.gmv", {"question": "q"})]
    assert "dossier" not in moves[0]
