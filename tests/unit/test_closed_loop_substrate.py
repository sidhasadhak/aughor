"""Tests for the reusable closed-loop substrate (aughor/sql/closed_loop.py) and the
dialect-aware repair diagnosis (aughor/sql/writer._make_diagnosis).

This is the substrate lifted from the Spider2 eval harness into the product: a backend-agnostic
execute→observe→repair loop, evaluator-faithful CSV materialization, and a repair catalog that no
longer mis-corrects valid Snowflake SQL.
"""
from __future__ import annotations

import csv
from pathlib import Path

from aughor.sql.closed_loop import execute_with_repair, rows_to_csv, LoopResult
from aughor.sql.writer import _make_diagnosis


# ── execute_with_repair ───────────────────────────────────────────────────────

def test_good_sql_is_idempotent():
    """A query that executes and returns rows is returned unchanged, zero rounds."""
    def ex(sql):
        return True, [(1,), (2,)], ""
    r = execute_with_repair("SELECT 1", ex)
    assert isinstance(r, LoopResult)
    assert r.ok and r.sql == "SELECT 1" and r.rounds == 0
    assert r.row_count == 2 and not r.receipt["repaired"]


def test_repair_on_error_adopts_only_if_it_runs():
    """First SQL errors; repair_fn returns a fix that executes → adopted."""
    calls = {"n": 0}
    def ex(sql):
        if "BAD" in sql:
            return False, None, 'invalid identifier "BAD"'
        return True, [(1,)], ""
    def repair(bad, err):
        calls["n"] += 1
        return bad.replace("BAD", "GOOD")
    r = execute_with_repair("SELECT BAD", ex, repair)
    assert r.ok and r.sql == "SELECT GOOD" and r.receipt["repaired"]
    assert r.rounds == 1 and calls["n"] == 1


def test_repair_never_regresses_when_fix_also_fails():
    """If no repair executes, the loop reports failure but never crashes."""
    def ex(sql):
        return False, None, "boom"
    def repair(bad, err):
        return bad + " -- still bad"
    r = execute_with_repair("SELECT 1", ex, repair, max_rounds=2)
    assert not r.ok and r.rounds == 2 and not r.receipt["repaired"]


def test_repair_fn_returning_none_breaks_cleanly():
    def ex(sql):
        return False, None, "err"
    r = execute_with_repair("SELECT 1", ex, lambda b, e: None)
    assert not r.ok and r.rounds == 1


def test_empty_recovery_adopts_only_if_rows_returned():
    """0-row result + recover_fn that yields rows → adopted; receipt flags recovery."""
    def ex(sql):
        if "WHERE x='ITALY'" in sql:
            return True, [], ""           # wrong literal → empty
        return True, [("row",)], ""       # recovered
    def recover(sql):
        return sql.replace("ITALY", "Italy")
    r = execute_with_repair("SELECT * FROM t WHERE x='ITALY'", ex,
                            recover_empty_fn=recover)
    assert r.ok and r.receipt["recovered"] and r.row_count == 1


def test_empty_recovery_rejected_when_still_empty():
    def ex(sql):
        return True, [], ""
    r = execute_with_repair("SELECT 1", ex, recover_empty_fn=lambda s: s + " LIMIT 1")
    assert r.ok and not r.receipt["recovered"] and r.row_count == 0


def test_execute_fn_exception_is_swallowed():
    def ex(sql):
        raise RuntimeError("connection dropped")
    r = execute_with_repair("SELECT 1", ex)
    assert not r.ok  # treated as a failed attempt, not a crash


def test_blank_sql_short_circuits():
    r = execute_with_repair("   ", lambda s: (True, [(1,)], ""))
    assert not r.ok and r.rounds == 0


# ── rows_to_csv: the evaluator output contract ────────────────────────────────

def test_csv_writes_real_null_as_empty_not_literal_NULL(tmp_path: Path):
    """The bug this fixes: SnowflakeConnection wrote None → "NULL" (a string), which fails the
    evaluator's compare against pandas' empty cell. rows_to_csv must write an EMPTY cell."""
    p = tmp_path / "out.csv"
    rows_to_csv(["a", "b"], [[1, None], [None, "x"]], p)
    text = p.read_text()
    assert "NULL" not in text           # the core bug: never the literal string "NULL"
    parsed = list(csv.reader(p.open()))
    assert parsed[0] == ["a", "b"]
    # None → EMPTY cell (pandas may render the int col as 1.0 due to None-upcast; the evaluator
    # uses the same pd.DataFrame path, so pred and gold agree, and numeric compare is abs_tol=1e-2).
    assert parsed[1][1] == "" and float(parsed[1][0]) == 1.0   # [1, None]
    assert parsed[2][0] == "" and parsed[2][1] == "x"          # [None, "x"]


def test_csv_preserves_column_order_and_all_rows(tmp_path: Path):
    p = tmp_path / "out.csv"
    rows = [[i, i * 2] for i in range(5000)]   # well past the old MAX_ROWS=2000 cap
    rows_to_csv(["id", "double"], rows, p)
    parsed = list(csv.reader(p.open()))
    assert parsed[0] == ["id", "double"]
    assert len(parsed) == 5001                 # header + 5000 rows, no truncation
    assert parsed[-1][0] == "4999"


# ── dialect-aware diagnosis (intervention #2) ─────────────────────────────────

def test_timestampdiff_advice_fires_on_duckdb_only():
    err = 'Scalar Function with name "timestampdiff" does not exist!'
    duck = _make_diagnosis(err, "SELECT timestampdiff(...)", {}, dialect="duckdb")
    assert "datediff" in duck.lower()  # DuckDB gets the substitution advice

    # On Snowflake, TIMESTAMPDIFF is valid — we must NOT tell it to remove it.
    snow = _make_diagnosis(err, "SELECT timestampdiff(...)", {}, dialect="snowflake")
    assert "datediff" not in snow.lower()
    assert "remove" not in snow.lower()


def test_duckdb_strftime_advice_not_emitted_on_snowflake():
    err = 'Function "to_char" does not exist'
    snow = _make_diagnosis(err, "SELECT to_char(d,'YYYY')", {}, dialect="snowflake")
    assert "strftime" not in snow.lower()


def test_snowflake_invalid_identifier_branch():
    err = "SQL compilation error: invalid identifier 'ORDER_TS'"
    d = _make_diagnosis(err, "SELECT order_ts FROM t", {}, dialect="snowflake")
    assert "ORDER_TS" in d and "snowflake" in d.lower()


def test_dialect_agnostic_branches_still_fire_everywhere():
    """The binder/group-by branches are universal and must not be gated to one dialect."""
    err = 'column "region" must appear in the GROUP BY clause'
    for dia in ("duckdb", "snowflake", "bigquery"):
        d = _make_diagnosis(err, "SELECT region, SUM(x) FROM t", {}, dialect=dia)
        assert "GROUP BY" in d
