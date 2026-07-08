"""Unit tests for the connector-capability contract (Rec 6) — deterministic AST diagnostics, fail-open."""
from __future__ import annotations

from aughor.db.capabilities import DialectCapabilities, for_dialect
from aughor.sql.capability_check import capability_diagnostics


def test_for_dialect_lookups():
    assert "SAFE_DIVIDE" in for_dialect("snowflake").unsupported_functions
    assert "qualify" in for_dialect("mysql").unsupported_features
    # transpile-from-DuckDB / unknown dialects are permissive
    assert for_dialect("duckdb").unsupported_functions == frozenset()
    assert for_dialect("sqlite").unsupported_features == frozenset()
    assert isinstance(for_dialect("nonesuch"), DialectCapabilities)


def test_qualify_flagged_on_postgres():
    sql = "SELECT * FROM t QUALIFY ROW_NUMBER() OVER (PARTITION BY a ORDER BY b) = 1"
    diags = capability_diagnostics(sql, "postgres")
    assert any("QUALIFY" in d for d in diags)


def test_ilike_flagged_on_bigquery():
    diags = capability_diagnostics("SELECT * FROM t WHERE name ILIKE '%acme%'", "bigquery")
    assert any("ILIKE" in d for d in diags)


def test_unsupported_function_flagged():
    # SAFE_DIVIDE is BigQuery-only → errors on Snowflake
    assert any("SAFE_DIVIDE" in d for d in capability_diagnostics("SELECT SAFE_DIVIDE(a, b) FROM t", "snowflake"))
    # DIV0 is Snowflake-only → errors on Postgres
    assert any("DIV0" in d for d in capability_diagnostics("SELECT DIV0(a, b) FROM t", "postgres"))
    # MySQL has no DATE_TRUNC
    assert any("DATE_TRUNC" in d for d in capability_diagnostics("SELECT DATE_TRUNC('month', ts) FROM t", "mysql"))


def test_supported_construct_is_clean():
    # QUALIFY + ILIKE are both fine on Snowflake; a plain aggregate is fine everywhere
    assert capability_diagnostics(
        "SELECT a FROM t QUALIFY ROW_NUMBER() OVER (ORDER BY b) = 1", "snowflake") == []
    assert capability_diagnostics("SELECT name FROM t WHERE name ILIKE '%x%'", "snowflake") == []
    assert capability_diagnostics("SELECT SUM(amount) FROM t GROUP BY region", "bigquery") == []


def test_transpile_dialect_is_permissive():
    # DuckDB-form SQL checked against duckdb (the transpile base) → never flagged
    assert capability_diagnostics("SELECT SAFE_DIVIDE(a, b) FROM t QUALIFY 1=1", "duckdb") == []


def test_unparseable_sql_fails_open():
    assert capability_diagnostics("SELECT ((( FROM", "mysql") == []
    assert capability_diagnostics("", "mysql") == []


def test_avoid_line_for_native_and_permissive_dialects():
    from aughor.db.capabilities import avoid_line
    sf = avoid_line("snowflake")
    assert sf.startswith("AVOID on snowflake") and "SAFE_DIVIDE" in sf
    assert "ILIKE" in avoid_line("bigquery")
    assert "QUALIFY" in avoid_line("mysql")
    assert avoid_line("duckdb") == "" and avoid_line("sqlite") == ""   # permissive → no directive
