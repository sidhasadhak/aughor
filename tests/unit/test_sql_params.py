"""SE-4 H — the parameter scanner, and the two renderings.

This is the security-sensitive file of the wave, so the tests are written against the
ways it could be WRONG rather than the way it is meant to work: a `:name` that is not a
parameter (a string, a cast, a comment), a value that must not be able to change the
statement, and a parameter that cannot be rendered at all.
"""
from __future__ import annotations

import pytest

from aughor.sql.params import (
    ParamRenderError, find_params, render_for_engine, render_for_guards,
)


# ── What counts as a parameter ────────────────────────────────────────────────

@pytest.mark.parametrize("sql,expected", [
    ("SELECT * FROM t WHERE a = :region", ["region"]),
    ("SELECT :a, :b, :a", ["a", "b"]),                       # de-duped, first-seen order
    ("SELECT * FROM t", []),
    # `::` is a CAST. Rewriting it yields a parameter named `int` and a baffling error.
    ("SELECT x::int FROM t", []),
    ("SELECT x::int FROM t WHERE a = :v", ["v"]),
    # A colon inside DATA is data.
    ("SELECT 'hello :world' AS greeting", []),
    ("SELECT 'it''s :not a param' AS s", []),
    ('SELECT "weird:col" FROM t', []),
    # …and inside prose is prose.
    ("SELECT 1 -- :nope\n, 2", []),
    ("SELECT /* :nope */ 1", []),
    ("SELECT 1 -- :nope\n, :yes", ["yes"]),
    # A bare colon is not a parameter.
    ("SELECT a : b", []),
])
def test_find_params_only_matches_parameter_positions(sql, expected):
    assert find_params(sql) == expected


# ── The executable rendering ──────────────────────────────────────────────────

def test_render_for_engine_duckdb_uses_dollar_names():
    # Measured: DuckDB rejects `:name` outright, so translation is not cosmetic.
    assert render_for_engine("SELECT * FROM t WHERE a = :region", "duckdb") \
        == "SELECT * FROM t WHERE a = $region"


def test_render_for_engine_pyformat_is_what_postgres_and_mysql_drivers_take():
    assert render_for_engine("SELECT * FROM t WHERE a = :region", "pyformat") \
        == "SELECT * FROM t WHERE a = %(region)s"


def test_the_map_is_keyed_on_the_DRIVER_style_not_the_sql_dialect():
    """`ExasolConnection` declares `dialect = "postgres"` because Postgres is the closest
    transpile target for Exasol's SQL — and pyexasol accepts no Postgres placeholder syntax
    at all. Keyed on dialect, that connector would have been handed `%(name)s` silently."""
    from aughor.connectors.warehouse.exasol import ExasolConnection

    assert ExasolConnection.dialect == "postgres"
    assert ExasolConnection.param_style is None
    with pytest.raises(ParamRenderError):
        render_for_engine("SELECT :a", ExasolConnection.dialect)


def test_named_is_the_identity_rendering():
    """sqlite3's own named style IS `:name`. An identity rewrite is still a rewrite — it
    has to be declared, or the driver falls through to the refusal."""
    assert render_for_engine("SELECT :a", "named") == "SELECT :a"


def test_render_for_engine_leaves_casts_and_strings_alone():
    sql = "SELECT x::int, 'a :b' FROM t WHERE c = :v -- :skip"
    out = render_for_engine(sql, "duckdb")
    assert "x::int" in out
    assert "'a :b'" in out
    assert "-- :skip" in out
    assert "= $v" in out


def test_render_for_engine_refuses_an_unknown_style():
    """A driver we cannot spell a placeholder for must REFUSE, never silently run the
    query with `:name` left in it (or, worse, with values interpolated).

    This used to name "bigquery" as the unspellable example. BigQuery binds now (`@name`),
    and a test whose example became supported would have kept passing while asserting
    nothing — the token just has to be unknown, so it says so."""
    with pytest.raises(ParamRenderError):
        render_for_engine("SELECT :a", "no-such-driver-style")


# ── The guard rendering (analysis only) ───────────────────────────────────────

def test_render_for_guards_substitutes_values():
    assert render_for_guards("SELECT * FROM t WHERE a = :region", {"region": "EMEA"}) \
        == "SELECT * FROM t WHERE a = 'EMEA'"


@pytest.mark.parametrize("value,expected", [
    ("EMEA", "'EMEA'"),
    ("it's", "'it''s'"),          # the quote is doubled, not escaped with a backslash
    (42, "42"),
    (3.5, "3.5"),
    (True, "TRUE"),
    (False, "FALSE"),
    (None, "NULL"),
])
def test_guard_literals_are_rendered_per_type(value, expected):
    assert render_for_guards("SELECT :v", {"v": value}) == f"SELECT {expected}"


def test_guard_rendering_neutralises_a_quote_break_attempt():
    """Even though this string is never executed, it must not be able to change the
    SHAPE of what the guards parse — a mangled AST is a wrong verdict."""
    out = render_for_guards("SELECT * FROM t WHERE a = :v", {"v": "x' OR 1=1 --"})
    assert out == "SELECT * FROM t WHERE a = 'x'' OR 1=1 --'"
    # One string literal, still one predicate: the injected quote was doubled.
    assert out.count("'") == 4


@pytest.mark.parametrize("params", [{}, {"other": 1}])
def test_missing_value_raises_so_the_caller_can_say_not_checked(params):
    """The honest-fallback contract: no value ⇒ no verdict, never a clean one."""
    with pytest.raises(ParamRenderError):
        render_for_guards("SELECT :v", params)


def test_unrenderable_type_raises_rather_than_guessing():
    with pytest.raises(ParamRenderError):
        render_for_guards("SELECT :v", {"v": {"a": 1}})


def test_guard_and_engine_renderings_agree_on_what_is_a_parameter():
    """The two renderings share one scanner on purpose. If they ever disagreed, a
    query could be guarded on one shape and executed as another — which is the exact
    failure this design exists to prevent."""
    sql = "SELECT x::int, 'lit :a' FROM t WHERE a = :a AND b = :b /* :c */"
    names = find_params(sql)
    assert names == ["a", "b"]
    engine = render_for_engine(sql, "duckdb")
    guards = render_for_guards(sql, {"a": 1, "b": "z"})
    for name in names:
        assert f"${name}" in engine
    assert "$c" not in engine and "'c'" not in guards
    assert "x::int" in engine and "x::int" in guards
