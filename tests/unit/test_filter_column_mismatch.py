"""A filter literal that is a stored value of a SIBLING column is moved, not invented — CA-2.

Specimen: investigation 7774b792 (2026-08-19) and its receipt re-run. The coder wrote
`CHANNEL_LVL_0 = 'Direkteingabe' AND BROWSER_NAME = 'Chrome'`; 'Direkteingabe' is a real value
of the table — of CHANNEL_LVL_1, never CHANNEL_LVL_0 — so every query returned [] and the report
invented "Desktop and Windows represent the primary segments". The value-domain guard let it
through: 'Direkteingabe' has no close neighbour among CHANNEL_LVL_0's five values, and a value
with no neighbour was treated as "novel — never second-guess". For an enumerable column the
domain is complete, so absence is certain; the guard now looks for the value in the table's
other text columns and either MOVES the predicate (exactly one holder) or says plainly that the
value is nowhere (an honest absence, never a repair target for the model).
"""
from __future__ import annotations

from pathlib import Path

import duckdb

from aughor.db.connection import DuckDBConnection
from aughor.sql.executor import execute_guarded
from aughor.sql.join_guard import (
    FilterDomainWarning,
    check_filter_value_domains,
    repair_filter_literals,
)


def _conn(conn_id: str = "ca2-traffic") -> DuckDBConnection:
    conn = DuckDBConnection.__new__(DuckDBConnection)
    conn._path = Path(":memory:")
    conn._conn = duckdb.connect(":memory:")
    conn._connection_id = conn_id
    conn._schema_name = None
    conn._conn.execute(
        "CREATE TABLE traffic (CALENDAR_DATE DATE, CHANNEL_LVL_0 VARCHAR, CHANNEL_LVL_1 VARCHAR, "
        "BROWSER_NAME VARCHAR, TRAFFIC BIGINT)")
    conn._conn.execute(
        "INSERT INTO traffic VALUES "
        "('2026-07-01','Organic & Brand','Direkteingabe','Chrome',100),"
        "('2026-07-01','Organic & Brand','Direkteingabe','Mobile Safari',80),"
        "('2026-07-01','Performance','Affiliate','Chrome',40),"
        "('2026-07-02','CRM','Newsletter','Chrome',20)")
    return conn


SQL = ("SELECT BROWSER_NAME, SUM(TRAFFIC) FROM traffic "
       "WHERE CHANNEL_LVL_0 = 'Direkteingabe' AND BROWSER_NAME = 'Chrome' GROUP BY 1")


def test_value_in_a_sibling_column_yields_a_column_suggestion():
    w = check_filter_value_domains(_conn(), SQL)
    assert len(w) == 1, w
    assert (w[0].col, w[0].bad_value) == ("CHANNEL_LVL_0", "Direkteingabe")
    assert w[0].column_suggestion == "CHANNEL_LVL_1" and w[0].suggestion is None and not w[0].novel
    text = w[0].to_prompt_text()
    assert "IS a stored value of traffic.CHANNEL_LVL_1" in text and "keep the literal" in text


def test_repair_moves_the_predicate_and_keeps_the_literal():
    w = check_filter_value_domains(_conn(), SQL)
    fixed = repair_filter_literals(SQL, w)
    assert fixed and '"CHANNEL_LVL_1" = \'Direkteingabe\'' in fixed
    assert "CHANNEL_LVL_0 = 'Direkteingabe'" not in fixed
    assert "BROWSER_NAME = 'Chrome'" in fixed          # the other predicate is untouched


def test_execute_guarded_repairs_deterministically_without_a_model():
    res = execute_guarded(_conn(), SQL, query_id="ca2")       # no provider → deterministic only
    assert not res.error
    assert res.row_count == 1 and res.rows[0][0] == "Chrome" and int(res.rows[0][1]) == 100
    assert "CHANNEL_LVL_1" in res.sql and "CHANNEL_LVL_0 = 'Direkteingabe'" not in res.sql
    assert not any("filter guard" in c for c in res.caveats), res.caveats


def test_a_value_in_no_column_is_an_honest_absence_and_never_repaired():
    sql = "SELECT SUM(TRAFFIC) FROM traffic WHERE CHANNEL_LVL_0 = 'Direktzugang'"   # nowhere
    w = check_filter_value_domains(_conn(), sql)
    assert len(w) == 1 and w[0].novel and w[0].column_suggestion is None
    assert repair_filter_literals(sql, w) is None
    res = execute_guarded(_conn(), sql, query_id="ca2-novel")
    assert res.sql == sql                                       # untouched
    assert any("not a stored value" in c and "segment is absent" in c for c in res.caveats), res.caveats


def test_a_value_held_by_two_sibling_columns_is_left_alone():
    conn = _conn()
    conn._conn.execute("UPDATE traffic SET BROWSER_NAME = 'Direkteingabe' WHERE TRAFFIC = 20")
    w = check_filter_value_domains(conn, "SELECT COUNT(*) FROM traffic WHERE CHANNEL_LVL_0 = 'Direkteingabe'")
    assert w == []                                               # ambiguous → fail-open


def test_an_exact_stored_value_is_still_not_flagged():
    assert check_filter_value_domains(
        _conn(), "SELECT COUNT(*) FROM traffic WHERE CHANNEL_LVL_1 = 'Direkteingabe'") == []


def test_prompt_text_shapes():
    sw = FilterDomainWarning("t", "a", "x", ["p", "q"], None, "=", column_suggestion="b")
    nv = FilterDomainWarning("t", "a", "x", ["p", "q"], None, "=", novel=True)
    assert "FILTER COLUMN MISMATCH" in sw.to_prompt_text()
    assert "FILTER VALUE ABSENT" in nv.to_prompt_text()
