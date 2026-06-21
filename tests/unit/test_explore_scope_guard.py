"""Explore schema-escape guard (eval 2026-06-21, critical #3).

The deep "explore" decomposition leaked to a sibling demo schema: a missimi (beauty)
investigation returned Apparel/Electronics/"Mechanical Keyboard" rows. Root cause —
the deep path left scope_schema=None for a table-list-scoped canvas, so the connection
wasn't search_path-pinned AND the linker's full-schema FK expansion surfaced cross-schema
tables the planner copied verbatim. _rescope_sql_to_schema re-points any out-of-scope
table to the canvas schema (or the caller drops the query). See aughor/agent/explore.py.
"""
from aughor.agent.explore import _rescope_sql_to_schema


class FakeConn:
    """Minimal connection: dialect + a dry_run that reports bind success/failure."""
    dialect = "duckdb"

    def __init__(self, binds=True):
        self._binds = binds

    def dry_run(self, sql):
        return (self._binds, "" if self._binds else "no such table")


def test_cross_schema_ref_is_rescoped_when_it_binds():
    out = _rescope_sql_to_schema(
        "SELECT * FROM netflix.products p JOIN missimi.orders o ON p.id = o.pid",
        "missimi", FakeConn(binds=True))
    assert out is not None
    assert "missimi.products" in out
    assert "netflix" not in out


def test_in_scope_sql_is_left_unchanged():
    # Nothing to rescope → None (the caller keeps the original SQL).
    assert _rescope_sql_to_schema("SELECT * FROM missimi.orders", "missimi", FakeConn()) is None


def test_cross_schema_that_cannot_bind_returns_none():
    # missimi has no such table → can't safely rescope → None (caller DROPS the query).
    assert _rescope_sql_to_schema(
        "SELECT * FROM netflix.subscriptions", "missimi", FakeConn(binds=False)) is None


def test_cte_alias_is_not_treated_as_a_schema():
    # A CTE named like a schema must not be rewritten.
    assert _rescope_sql_to_schema(
        "WITH netflix AS (SELECT 1 AS x) SELECT * FROM netflix", "missimi", FakeConn()) is None


def test_system_schemas_are_not_rescoped():
    assert _rescope_sql_to_schema(
        "SELECT * FROM information_schema.tables", "missimi", FakeConn()) is None


def test_unscoped_run_is_a_noop():
    # No allowed schema → never rewrites.
    assert _rescope_sql_to_schema("SELECT * FROM netflix.products", "", FakeConn()) is None
