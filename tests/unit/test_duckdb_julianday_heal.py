"""SQLite's JULIANDAY written against DuckDB — healed once, after DuckDB refuses it.

Measured 2026-09-13: both ON-10 falsifier runs lost their lag question to the same refusal, in every arm that
wrote SQL — `Scalar Function with name julianday does not exist!` — with a compiled `DATE_DIFF` sitting in the
framed arm's prompt. The heal lives where every path that runs SQL on DuckDB converges: `DuckDBConnection`, and
`LocalUploadConnection`, which is DuckDB-backed but inherits none of the former's overrides. It is error-driven,
as the BigQuery connector's date-literal retry is: nothing is rewritten until DuckDB names the refusal.

The rewrite is held to SQLite itself — the standard library's sqlite3, on the same rows: the heal must give
SQLite's number, not a nearby one.
"""
from __future__ import annotations

import sqlite3

import duckdb
import pytest

from aughor.control_plane.contracts.execution import QueryResult
from aughor.db.connection import DuckDBConnection, heal_duckdb_refusal, is_julianday_refusal, rewrite_julianday

#: DuckDB's refusal, verbatim (duckdb 1.5).
_REFUSAL = 'Catalog Error: Scalar Function with name julianday does not exist!\nDid you mean "julian"?'

_ROWS = [("2024-01-01 06:00:00", "2024-01-03 18:30:00", "2024-01-01", "2024-01-04"),
         ("2024-02-28 23:00:00", "2024-03-01 01:00:00", "2024-02-28", "2024-03-01"),
         ("2024-05-05 12:00:00", None, "2024-05-05", None)]


# ── the matcher ────────────────────────────────────────────────────────────────────

def test_the_matcher_knows_the_refusal_and_nothing_else():
    assert is_julianday_refusal(_REFUSAL)
    assert not is_julianday_refusal("Catalog Error: Scalar Function with name timestampdiff does not exist!")
    assert not is_julianday_refusal("Catalog Error: Table with name orders does not exist!")
    assert not is_julianday_refusal("")


def test_the_refusal_is_the_engines_own_words():
    """Keyed to DuckDB's text: if the engine rewords the refusal, this fails before the heal goes quiet."""
    with pytest.raises(duckdb.CatalogException) as refused:
        duckdb.connect().execute("SELECT JULIANDAY(DATE '2024-01-01')")
    assert is_julianday_refusal(str(refused.value))


# ── the rewrite — SQLite's number, and nothing touched that should not be ──────────

@pytest.fixture()
def engines():
    duck, lite = duckdb.connect(), sqlite3.connect(":memory:")
    duck.execute("CREATE TABLE t (a TIMESTAMP, b TIMESTAMP, d1 DATE, d2 DATE)")
    lite.execute("CREATE TABLE t (a TEXT, b TEXT, d1 TEXT, d2 TEXT)")
    for row in _ROWS:
        duck.execute("INSERT INTO t VALUES (?, ?, ?, ?)", row)
        lite.execute("INSERT INTO t VALUES (?, ?, ?, ?)", row)
    yield duck, lite
    duck.close()
    lite.close()


@pytest.mark.parametrize("sql", [
    "SELECT ROUND(AVG(JULIANDAY(b) - JULIANDAY(a)), 4) FROM t",                        # fractional days, timestamps
    "SELECT ROUND(AVG(CAST(JULIANDAY(d2) - JULIANDAY(d1) AS REAL)), 4) FROM t",        # whole days, dates
    "SELECT ROUND(SUM(JULIANDAY(b) - JULIANDAY(a)) / COUNT(b), 4) FROM t WHERE b IS NOT NULL",
    "SELECT ROUND(JULIANDAY('2024-01-02') - JULIANDAY(d1), 4) FROM t ORDER BY d1 LIMIT 1",  # a string literal
    "SELECT JULIANDAY(a) FROM t ORDER BY a LIMIT 1",                                    # the day number itself
])
def test_the_rewrite_gives_sqlites_number(engines, sql):
    duck, lite = engines
    healed = rewrite_julianday(sql)
    assert healed and "julianday" not in healed.lower()
    assert duck.execute(healed).fetchall() == lite.execute(sql).fetchall()


def test_now_is_the_current_moment():
    healed = rewrite_julianday("SELECT JULIANDAY('now') - JULIANDAY(DATE '2024-01-01')")
    assert "CURRENT_TIMESTAMP" in healed.upper() and "'now'" not in healed.lower()
    assert duckdb.connect().execute(healed).fetchone()[0] > 365


@pytest.mark.parametrize("sql", [
    "SELECT JULIANDAY(a, '+1 day') FROM t",   # SQLite's modifiers have no reading here
    "SELECT date_diff('day', a, b) FROM t",   # nothing to heal
    "SELEC JULIANDAY(a) FROM",                # a query that will not parse is not touched
])
def test_nothing_is_rewritten_that_should_not_be(sql):
    assert rewrite_julianday(sql) == ""


# ── the retry — once, and only after the refusal ─────────────────────────────────────

def _result(sql: str, error: str | None = None, rows=None) -> QueryResult:
    return QueryResult(hypothesis_id="h", sql=sql, columns=["d"] if rows else [], rows=rows or [],
                       row_count=len(rows or []), error=error)


def test_the_heal_runs_the_rewrite_once_and_only_after_the_refusal():
    ran: list[str] = []

    def attempt(statement: str) -> QueryResult:
        ran.append(statement)
        return _result(statement, rows=[["1.0"]])

    refused = _result("SELECT JULIANDAY(a) FROM t", error=_REFUSAL)
    healed = heal_duckdb_refusal(refused, refused.sql, attempt)
    assert len(ran) == 1 and healed.rows == [["1.0"]] and healed.sql == ran[0] and "julian(" in healed.sql.lower()

    other = _result("SELECT JULIANDAY(a) FROM t", error="Binder Error: Referenced column a not found")
    assert heal_duckdb_refusal(other, other.sql, attempt) is other
    fine = _result("SELECT 1", rows=[["1"]])
    assert heal_duckdb_refusal(fine, fine.sql, attempt) is fine
    assert len(ran) == 1


def test_a_retry_that_fails_leaves_the_original_refusal():
    refused = _result("SELECT JULIANDAY(a) FROM t", error=_REFUSAL)
    assert heal_duckdb_refusal(refused, refused.sql, lambda s: _result(s, error="Conversion Error: bad")) is refused


# ── the connections — the statements the falsifier runs lost now answer ─────────────

#: The four statements the ON-10 falsifier runs lost to the refusal, verbatim from the committed results
#: (evals/ablation_on10_olist_business_results.json ob06, evals/ablation_on10_luxexperience_business_results.json
#: lb13), with the value each gives on the rows below.
_LOST = {
    "ob06 raw": ("SELECT ROUND(AVG(JULIANDAY(order_delivered_carrier_date) - JULIANDAY(order_approved_at)), 2) AS "
                 "average_dispatch_lag_days FROM ecommerce.orders WHERE order_approved_at IS NOT NULL AND "
                 "order_delivered_carrier_date IS NOT NULL", "1.5"),
    "ob06 framed": ("SELECT ROUND(AVG(CAST(JULIANDAY(order_delivered_carrier_date) - JULIANDAY(order_approved_at) AS "
                    "FLOAT)), 2) AS avg_dispatch_lag_days FROM ecommerce.orders WHERE order_approved_at IS NOT NULL "
                    "AND order_delivered_carrier_date IS NOT NULL", "1.5"),
    "lb13 raw": ("SELECT ROUND(AVG(CAST(JULIANDAY(rl.refund_completed_date) - JULIANDAY(r.return_date) AS REAL)), 2) "
                 "AS average_refund_lag_days FROM luxexperience.return_logistics rl JOIN luxexperience.returns r ON "
                 "rl.return_id = r.return_id WHERE rl.refund_completed_date IS NOT NULL AND r.return_date IS NOT NULL",
                 "12.0"),
    "lb13 framed": ("SELECT ROUND(AVG(CAST(JULIANDAY(j1.refund_completed_date) - JULIANDAY(j1.received_date) AS REAL)), "
                    "2) AS avg_refund_lag_days FROM luxexperience.returns AS t0 LEFT JOIN luxexperience.return_logistics "
                    "AS j1 ON t0.return_id = j1.return_id", "7.5"),
}


@pytest.fixture()
def warehouse(tmp_path):
    path = tmp_path / "w.duckdb"
    seed = duckdb.connect(str(path))
    seed.execute("CREATE SCHEMA ecommerce")
    seed.execute("CREATE TABLE ecommerce.orders (order_approved_at TIMESTAMP, order_delivered_carrier_date TIMESTAMP)")
    seed.execute("INSERT INTO ecommerce.orders VALUES ('2024-01-01 06:00:00', '2024-01-03 18:00:00'), "
                 "('2024-01-02 00:00:00', '2024-01-02 12:00:00'), (NULL, '2024-01-05 00:00:00')")
    seed.execute("CREATE SCHEMA luxexperience")
    seed.execute("CREATE TABLE luxexperience.returns (return_id VARCHAR, return_date DATE)")
    seed.execute("CREATE TABLE luxexperience.return_logistics "
                 "(return_id VARCHAR, received_date DATE, refund_completed_date DATE)")
    seed.execute("INSERT INTO luxexperience.returns VALUES ('r1', '2024-03-01'), ('r2', '2024-03-05')")
    seed.execute("INSERT INTO luxexperience.return_logistics VALUES "
                 "('r1', '2024-03-06', '2024-03-10'), ('r2', '2024-03-09', '2024-03-20')")
    seed.close()
    conn = DuckDBConnection(path, connection_id="julianday-heal")
    yield conn
    conn.close()


@pytest.mark.parametrize("label", sorted(_LOST))
def test_the_statements_the_falsifier_runs_lost_now_answer(warehouse, label):
    sql, expected = _LOST[label]
    result = warehouse.execute("h", sql)
    assert not result.error, result.error
    assert result.rows == [[expected]]
    assert "julianday" not in result.sql.lower() and "julian(" in result.sql.lower()


def test_a_connection_keeps_an_honest_refusal_it_cannot_heal(warehouse):
    result = warehouse.execute("h", "SELECT JULIANDAY('not a moment')")
    assert is_julianday_refusal(result.error)
    assert "julianday" in result.sql.lower()


def test_the_workspace_connection_heals_too(tmp_path, monkeypatch):
    """`LocalUploadConnection` is DuckDB-backed but is not a `DuckDBConnection` — the asymmetry that has already
    cost this codebase three capabilities that landed on one class only."""
    from aughor.connectors.file.local_upload import LocalUploadConnection
    from aughor.control_plane import vending

    monkeypatch.setattr(vending, "STORAGE_ROOT", tmp_path / "uploads")
    conn = LocalUploadConnection(connection_id="ws")
    try:
        result = conn.execute("h", "SELECT ROUND(JULIANDAY(TIMESTAMP '2024-01-01 18:00:00') - "
                                   "JULIANDAY(TIMESTAMP '2024-01-01 06:00:00'), 2) AS d")
        assert not result.error, result.error
        assert result.rows == [["0.5"]]
        assert "julian(" in result.sql.lower()
    finally:
        getattr(conn, "close", lambda: None)()


# ── the receipts — what scores the statement, and what records it ────────────────────

def test_the_eval_scorer_scores_what_the_connection_runs(warehouse):
    """`_safe_exec` runs SQL on the raw cursor to skip the connection's validation — but not its heal: every product
    path runs the healed statement, so an eval that scored the refusal would score an error no user sees."""
    from evals.sql_accuracy import _safe_exec

    ok, _columns, rows, error = _safe_exec(warehouse, _LOST["lb13 framed"][0])
    assert ok and error is None and rows == [["7.5"]]
    ok, _columns, _rows, error = _safe_exec(warehouse, "SELECT JULIANDAY('not a moment')")
    assert not ok and is_julianday_refusal(error)


def test_the_audit_log_records_the_statement_that_ran(warehouse):
    from aughor.security.audit import AuditLogger

    result = warehouse.execute("h", _LOST["ob06 raw"][0])
    assert not result.error, result.error
    latest = AuditLogger.recent(50, connection_id="julianday-heal")[0]["sql_full"].lower()
    assert "julian(" in latest and "julianday" not in latest
