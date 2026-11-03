"""Platform SQL on the engines sqlglot alone leaves unrunnable or wrong. Each statement here failed or answered wrongly on
a real server first (`tests/integration/test_connectors_on_real_servers.py` runs them there); this holds the rendering where CI
has no servers."""
from __future__ import annotations

import sqlglot

from aughor.connectors.warehouse.dbapi import limit_as_engine_caps
from aughor.connectors.warehouse.oracle import OracleConnection
from aughor.connectors.warehouse.wire import PostgresWireConnection
from aughor.db.dialects import native_sql
from aughor.sql.engine_fit import translate_for

MONTHS = "SELECT DATE_TRUNC('month', at) AS m, SUM(x) AS s FROM t GROUP BY 1 ORDER BY 1 LIMIT 2"
CAPPED_QUALIFY = "SELECT id, ROW_NUMBER() OVER (PARTITION BY r ORDER BY at) AS rn FROM t QUALIFY rn <= 2 ORDER BY id DESC LIMIT 1"


def test_sql_server_groups_by_what_it_names_and_needs_no_2022_function():
    out = translate_for(MONTHS, "tsql")
    assert "DATETRUNC" not in out
    assert "GROUP BY DATEADD(MONTH, DATEDIFF(MONTH, 0, at), 0)" in out
    assert out.startswith("SELECT TOP 2 ")


def test_sql_server_week_starts_on_monday_in_whole_weeks():
    out = translate_for("SELECT DATE_TRUNC('week', at) FROM t", "tsql")
    assert "DATEADD(DAY, DATEDIFF(DAY, 0, at) / 7 * 7, 0)" in out


def test_sql_server_has_no_ilike():
    assert "LOWER(r) LIKE LOWER('A%')" in translate_for("SELECT 1 AS n FROM t WHERE r ILIKE 'A%'", "tsql")


def test_oracle_day_is_a_day_and_week_is_iso():
    """TRUNC(x, 'DAY') is the start of the week there: the wrong answer, with no error."""
    assert "TRUNC(at, 'DD')" in translate_for("SELECT DATE_TRUNC('day', at) FROM t", "oracle")
    assert "TRUNC(at, 'IW')" in translate_for("SELECT DATE_TRUNC('week', at) FROM t", "oracle")


def test_oracle_reads_what_it_otherwise_refuses():
    out = translate_for('SELECT MIN(a)::VARCHAR AS "_lo_a", MAX(a) AS _hi_a FROM t', "oracle")
    assert "VARCHAR2(4000)" in out and '"_lo_a"' in out and '"_hi_a"' in out


def test_a_cap_stays_outside_the_subquery_qualify_becomes():
    """sqlglot alone moves it inside, so the cap runs before the filter: the wrong rows, with no error."""
    for dialect, cap in (("tsql", None), ("oracle", "FETCH FIRST 1 ROWS ONLY"), ("mysql", "LIMIT 1"), ("postgres", "LIMIT 1")):
        out = translate_for(CAPPED_QUALIFY, dialect)
        inner_ends = out.rindex(")")
        if cap:
            assert out.endswith(cap), out
        assert "ORDER BY" in out[inner_ends:], out
        assert "TOP 1" not in out[out.index("("):], out
        assert sqlglot.transpile(CAPPED_QUALIFY, read="duckdb", write=dialect)[0] != out


def test_mysql_month_does_not_count_from_year_zero():
    """On TiDB that date is NULL, so every row landed in one bucket."""
    out = translate_for(MONTHS, "mysql")
    assert "0000" not in out
    assert "DATE_FORMAT(at, '%Y-%m-01')" in out


def test_filter_is_written_out_where_an_engine_refuses_it():
    sql = "SELECT COUNT(*) FILTER (WHERE r = 'a') AS n, SUM(x) FILTER (WHERE r = 'b') AS s FROM t"
    for dialect in ("tsql", "oracle", "mysql", "clickhouse"):
        out = translate_for(sql, dialect)
        assert "FILTER" not in out.upper(), out
        assert "CASE WHEN" in out, out


def test_postgres_is_rendered_as_it_was_when_there_is_no_qualify():
    for sql in (MONTHS, "SELECT COUNT(*) FILTER (WHERE r = 'a') AS n FROM t", "SELECT x / y AS r FROM t"):
        assert translate_for(sql, "postgres") == sqlglot.transpile(sql, read="duckdb", write="postgres")[0]


def test_an_engine_not_fitted_takes_sqlglots_rendering():
    class BigQuery:
        dialect = "bigquery"
        writes_native_sql = True

    assert native_sql(BigQuery(), MONTHS) == sqlglot.transpile(MONTHS, read="duckdb", write="bigquery")[0]


def test_a_limit_on_a_statement_written_for_the_engine_becomes_its_own_cap():
    assert limit_as_engine_caps('SELECT * FROM "t" LIMIT 5', "tsql") == "SELECT TOP 5 * FROM [t]"
    assert limit_as_engine_caps('SELECT * FROM "T" LIMIT 5', "oracle") == 'SELECT * FROM "T" FETCH FIRST 5 ROWS ONLY'
    assert limit_as_engine_caps("SELECT TOP 5 * FROM t", "tsql") == "SELECT TOP 5 * FROM t"
    assert limit_as_engine_caps("not sql at all ( LIMIT", "tsql") == "not sql at all ( LIMIT"


def test_oracle_answers_information_schema_from_its_own_views():
    conn = OracleConnection.__new__(OracleConnection)
    out = conn._spelled_for_engine("SELECT column_name, data_type FROM INFORMATION_SCHEMA.COLUMNS WHERE table_name = 'T' ORDER BY ordinal_position")
    assert "all_tab_columns" in out.lower() and "information_schema" not in out.lower()
    assert "oracle_maintained" in out.lower()


def test_a_ratio_on_the_postgres_wire_casts_both_sides():
    """CockroachDB has no float divided by an int."""
    conn = PostgresWireConnection.__new__(PostgresWireConnection)
    out = conn.translate("SELECT SUM(x) / COUNT(*) AS r FROM t")
    assert out.count("AS DOUBLE PRECISION") == 2, out
    assert conn.translate("SELECT a FROM t") == "SELECT a FROM t"
