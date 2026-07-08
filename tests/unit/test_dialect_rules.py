"""Per-dialect SQL-writer rules, selected by execution mode.

Native-execution warehouses (BigQuery/Snowflake/MySQL/Exasol) run the LLM's SQL
verbatim, so they must get correct NATIVE dialect rules; transpile-from-DuckDB
connections (DuckDB, Postgres) get DuckDB rules. Before this, non-DuckDB got only
a bare "Target dialect: X." See aughor/db/dialects.py.
"""
from aughor.db.dialects import DUCKDB_RULES, rules_for_dialect, writer_rules


class _DB:
    def __init__(self, dialect, native):
        self.dialect = dialect
        self.writes_native_sql = native


def test_duckdb_gets_duckdb_rules_no_note():
    r = writer_rules(_DB("duckdb", False))
    assert "DUCKDB DIALECT RULES" in r
    assert "automatically translated" not in r


def test_postgres_transpile_path_gets_duckdb_rules_plus_note():
    # Postgres execute() transpiles read=duckdb → postgres, so the LLM writes DuckDB.
    r = writer_rules(_DB("postgres", False))
    assert "DUCKDB DIALECT RULES" in r
    assert "automatically translated" in r


def test_writer_rules_native_includes_capability_avoid_line():
    # Rec 6: native dialects get the machine-checked "don't use these" directive appended.
    r = writer_rules(_DB("snowflake", True))
    assert "AVOID on snowflake" in r and "SAFE_DIVIDE" in r
    assert "ILIKE" in writer_rules(_DB("bigquery", True))


def test_writer_rules_transpile_path_has_no_avoid_line():
    # Transpile connections write DuckDB (permissive) → no avoid line.
    assert "AVOID on" not in writer_rules(_DB("duckdb", False))
    assert "AVOID on" not in writer_rules(_DB("postgres", False))


def test_bigquery_native_rules():
    r = writer_rules(_DB("bigquery", True))
    assert "DUCKDB DIALECT RULES" not in r
    assert "TIMESTAMP_TRUNC" in r
    assert "SAFE_DIVIDE" in r


def test_snowflake_native_rules():
    r = writer_rules(_DB("snowflake", True))
    assert "LISTAGG" in r
    assert "DIV0" in r


def test_mysql_native_rules():
    r = writer_rules(_DB("mysql", True))
    assert "GROUP_CONCAT" in r
    assert "DATE_FORMAT" in r  # MySQL has no date_trunc
    assert "date_trunc" not in r.lower() or "NO date_trunc" in r


def test_unknown_dialect_ansi_fallback():
    r = rules_for_dialect("clickhouse")
    assert "ANSI" in r
    assert "NULLIF" in r


def test_missing_flag_defaults_to_transpile_path():
    class _Bare:
        dialect = "postgres"  # no writes_native_sql attribute
    r = writer_rules(_Bare())
    assert "DUCKDB DIALECT RULES" in r  # getattr default False → safe transpile path


def test_base_connection_default_is_not_native():
    from aughor.db.connection import DatabaseConnection
    assert DatabaseConnection.writes_native_sql is False


def test_duckdb_rules_constant_is_nonempty():
    assert "GROUP BY" in DUCKDB_RULES
