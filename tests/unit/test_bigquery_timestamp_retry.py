"""BigQuery TIMESTAMP-vs-DATE literal clash — the error-driven deterministic retry.

Measured live 2026-09-06: an agent golden suite lost 4 of 5 questions to the same
engine refusal — generated SQL compared a TIMESTAMP column against a bare
'YYYY-MM-DD' literal, which BigQuery types as DATE and refuses to coerce. The fix
lives at the connector (every generation path converges there), and it is
error-driven: nothing is rewritten until the engine itself names the clash, so a
date literal legitimately compared to a DATE column is never touched.

No live BigQuery here (the cancel suite's precedent): the rewrite is pure and the
retry wiring is driven against a stubbed job runner. What these cannot prove — that
Google accepts the rewritten SQL — the live re-run of the golden suite proves.
"""
from __future__ import annotations

from aughor.connectors.warehouse.bigquery import (
    BigQueryConnection,
    _is_timestamp_date_clash,
    _retype_date_literals,
)
from aughor.control_plane.contracts.execution import QueryResult

#: The live error, verbatim shape (job ids trimmed).
_LIVE_ERROR = (
    "400 No matching signature for operator >= for argument types: TIMESTAMP, DATE\n"
    "  Signature: T1 >= T1\n"
    "    Unable to find common supertype for templated argument <T1>\n"
    "      Input types for <T1>: {DATE, TIMESTAMP} at [1:50]"
)


# ── the matcher ────────────────────────────────────────────────────────────────────

def test_matcher_recognises_the_live_error_and_nothing_else():
    assert _is_timestamp_date_clash(_LIVE_ERROR)
    assert not _is_timestamp_date_clash("400 Syntax error: Unexpected keyword FRM")
    assert not _is_timestamp_date_clash(
        "No matching signature for operator + for argument types: STRING, INT64")
    assert not _is_timestamp_date_clash("")


# ── the rewrite — pure, surgical, honest about not changing anything ──────────────

def test_bare_date_literals_in_comparisons_are_cast_to_timestamp():
    out = _retype_date_literals(
        "SELECT COUNT(*) FROM thelook.orders "
        "WHERE created_at >= '2026-08-01' AND created_at < '2026-09-01'")
    assert "CAST('2026-08-01' AS TIMESTAMP)" in out
    assert "CAST('2026-09-01' AS TIMESTAMP)" in out


def test_between_is_handled():
    out = _retype_date_literals(
        "SELECT 1 FROM t WHERE ts BETWEEN '2026-08-01' AND '2026-08-31'")
    assert out.count("AS TIMESTAMP") == 2


def test_non_date_strings_and_datetime_strings_stay_untouched():
    assert _retype_date_literals(
        "SELECT 1 FROM t WHERE status = 'Returned'") == ""
    # A literal with a time part already types as TIMESTAMP-comparable — not ours.
    assert _retype_date_literals(
        "SELECT 1 FROM t WHERE ts >= '2026-08-01 00:00:00'") == ""


def test_date_typed_literals_are_rewritten_too():
    """The live re-drive (2026-09-06, second eval run) showed the model's OTHER
    habit: `created_at >= DATE '2026-08-01'` — typed, and still the clash. Once
    the engine names the error, the typed form is rewritten like the bare one."""
    out = _retype_date_literals(
        "SELECT COUNT(*) FROM orders WHERE created_at >= DATE '2026-08-01' "
        "AND created_at < DATE '2026-09-01'")
    assert out.count("AS TIMESTAMP") == 2 and "AS DATE" not in out


def test_timestamp_literals_column_casts_and_function_args_stay_untouched():
    assert _retype_date_literals(
        "SELECT 1 FROM t WHERE ts >= TIMESTAMP '2026-08-01'") == ""
    # A cast of a COLUMN is a legitimate fix direction, never rewritten.
    assert _retype_date_literals(
        "SELECT 1 FROM t WHERE CAST(ts AS DATE) >= CURRENT_DATE()") == ""
    # The literal sits inside a function call, not directly in the comparison.
    assert _retype_date_literals(
        "SELECT 1 FROM t WHERE ts >= TIMESTAMP('2026-08-01')") == ""


def test_unparseable_sql_is_never_touched():
    assert _retype_date_literals("SELEC nonsense FRM") == ""


# ── the retry wiring — once, only on the named clash, receipts truthful ───────────

def _conn():
    c = BigQueryConnection.__new__(BigQueryConnection)
    c._connection_id = "bq-retry-test"
    c._project, c._dataset = "p", "d"
    return c


def _result(sql, error=""):
    return QueryResult(hypothesis_id="h", sql=sql, columns=[] if error else ["n"],
                       rows=[] if error else [["1"]], row_count=0 if error else 1,
                       error=error or None)


def test_clash_error_triggers_one_rewritten_retry_and_sql_reports_what_ran(monkeypatch):
    conn = _conn()
    calls = []

    def fake_run(hypothesis_id, sql):
        calls.append(sql)
        if "CAST" not in sql:
            return _result(sql, error=_LIVE_ERROR)
        return _result(sql)

    monkeypatch.setattr(conn, "_run_job", fake_run)
    out = conn.execute("h", "SELECT COUNT(*) FROM t WHERE ts >= '2026-08-01'")
    assert out.error is None
    assert len(calls) == 2
    assert "CAST('2026-08-01' AS TIMESTAMP)" in out.sql   # the receipt names what ran


def test_a_failed_retry_leaves_the_original_error_standing(monkeypatch):
    conn = _conn()

    monkeypatch.setattr(conn, "_run_job",
                        lambda h, sql: _result(sql, error=_LIVE_ERROR))
    out = conn.execute("h", "SELECT 1 FROM t WHERE ts >= '2026-08-01'")
    assert out.error and "No matching signature" in out.error


def test_other_errors_never_retry(monkeypatch):
    conn = _conn()
    calls = []

    def fake_run(hypothesis_id, sql):
        calls.append(sql)
        return _result(sql, error="400 Syntax error: Unexpected identifier")

    monkeypatch.setattr(conn, "_run_job", fake_run)
    out = conn.execute("h", "SELECT 1 FROM t WHERE ts >= '2026-08-01'")
    assert len(calls) == 1 and out.error


def test_clash_with_nothing_rewritable_does_not_retry(monkeypatch):
    conn = _conn()
    calls = []

    def fake_run(hypothesis_id, sql):
        calls.append(sql)
        return _result(sql, error=_LIVE_ERROR)

    monkeypatch.setattr(conn, "_run_job", fake_run)
    # The clash came from something this rewrite does not cover (e.g. a CURRENT_DATE
    # comparison) — no bare literal to retype, so no second job is spent.
    out = conn.execute("h", "SELECT 1 FROM t WHERE ts >= CURRENT_DATE()")
    assert len(calls) == 1 and out.error
