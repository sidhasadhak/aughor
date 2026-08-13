"""SE-3 G — EXPLAIN / DESCRIBE / SHOW from the workbench, and nowhere else.

Measured before building, and the measurement moved the scope: `DESCRIBE` and `SHOW`
already worked, *because* of the `SELECT * FROM (…) __q LIMIT n` wrap — wrapped, they
parse as a Select and DuckDB accepts them as a subquery source. `EXPLAIN` cannot be a
subquery source, so the wrap is what killed it. So this wave is two narrow changes, not
a new execution path: let the statement past the SELECT-root check, and skip the wrap.

The safety property that makes that acceptable is pinned here: the relaxation applies
to the statement-KIND rule only, never to the mutation scan, and only for the
workbench's own label.
"""
from __future__ import annotations

import pytest

from aughor.db.connection import _validate, is_metadata_statement

_METADATA = ["EXPLAIN SELECT 1", "DESCRIBE brands", "DESC brands", "SHOW TABLES"]


@pytest.mark.parametrize("sql", _METADATA)
def test_metadata_is_rejected_for_the_agent_path(sql):
    """Unchanged for every caller that did not ask for it — the agent still gets
    "Only SELECT", exactly as before this wave."""
    ok, _ = _validate(sql, "duckdb")
    assert ok is False


@pytest.mark.parametrize("sql", _METADATA)
def test_metadata_is_allowed_for_the_workbench(sql):
    ok, reason = _validate(sql, "duckdb", allow_metadata=True)
    assert ok is True, reason


@pytest.mark.parametrize("sql", [
    "EXPLAIN DELETE FROM brands",
    "EXPLAIN INSERT INTO brands VALUES (1)",
    "DESCRIBE (DROP TABLE brands)",
])
def test_the_mutation_guard_is_not_relaxed_with_the_kind_rule(sql):
    """The load-bearing one. The metadata allowance sits AFTER the forbidden-keyword
    scan on purpose: a mutation wearing an EXPLAIN prefix must still be refused, or
    "let EXPLAIN through" would have quietly become "let anything through"."""
    for allow in (False, True):
        ok, reason = _validate(sql, "duckdb", allow_metadata=allow)
        assert ok is False, f"allow_metadata={allow} admitted {sql!r}"
        assert "Only SELECT statements are permitted" in reason


def test_plain_select_is_untouched():
    assert _validate("SELECT 1", "duckdb")[0] is True
    assert _validate("SELECT 1", "duckdb", allow_metadata=True)[0] is True


@pytest.mark.parametrize("sql,expected", [
    ("EXPLAIN SELECT 1", True),
    ("  explain select 1", True),
    ("SHOW TABLES", True),
    ("DESCRIBE t", True),
    ("SELECT 1", False),
    ("SELECT 'EXPLAIN' AS x", False),          # the word as DATA, not as a statement
    ("", False),
])
def test_detector_matches_statement_position_only(sql, expected):
    assert is_metadata_statement(sql) is expected


def test_only_the_workbench_label_carries_the_capability():
    """The gate is the statement LABEL, the same routing `_is_internal_query` uses —
    so a caller cannot obtain the capability by choosing a different `source`, because
    `source` is a closed allow-list on the request model."""
    from aughor.db.connection import _METADATA_LABELS
    assert _METADATA_LABELS == {"query_workbench"}
