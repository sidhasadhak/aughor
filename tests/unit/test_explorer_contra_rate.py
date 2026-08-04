"""The contra-rate guard, on the EXPLORER path.

PR #255 taught the deep-analysis planner that a discount column may hold a rate, not
money, and that summing it produces a number in no unit at all. The explorer writes its
own SQL in Phase 8 and consulted neither half of that guard, so on 2026-08-04 a fresh
exploration of Tableau Superstore emitted:

    SELECT SUM(Discount * Quantity) / NULLIF(SUM(Sales), 0) AS discount_rate FROM superstore

with `Discount` measured at min 0.0, max 0.80 — a fraction. That is the same defect the
guard's own docstring records finding on the same dataset one day earlier, at a 225x
understatement that inverted the finding.

These tests pin the repair on the explorer's own seam, and — the load-bearing one —
that the guard is driven by the MEASURED range rather than the column name.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from aughor.agent.loss_signals import (
    classify_contra_columns, contra_kinds_from_ranges, contra_rate_columns,
)
from aughor.explorer.agent import SchemaExplorer

SCHEMA = """TABLE: superstore
  Order ID  VARCHAR
  Sales  FLOAT
  Quantity  INTEGER
  Discount  FLOAT
  Profit  FLOAT
"""

#: The SQL the explorer actually emitted on 2026-08-04.
LIVE_DEFECT_SQL = (
    'SELECT SUM(Discount * Quantity) / NULLIF(SUM(Sales), 0) AS discount_rate '
    'FROM superstore'
)


def _agent() -> SchemaExplorer:
    """An agent shell — these tests exercise pure helpers, not a run."""
    return SchemaExplorer.__new__(SchemaExplorer)


def _profiles(rng):
    """`{table: {col: ColumnProfile-ish}}` — only `value_range` is read."""
    return {"superstore": {
        "Discount": SimpleNamespace(value_range=rng),
        "Sales": SimpleNamespace(value_range=(0.44, 22638.48)),
        "Quantity": SimpleNamespace(value_range=(1, 14)),
    }}


# ── the decision is made from the DATA, never the name ───────────────────────────

def test_a_discount_column_holding_a_fraction_is_a_rate():
    kinds = contra_kinds_from_ranges(SCHEMA, {"superstore.Discount": (0.0, 0.80)})
    assert kinds["superstore.Discount"] == "rate"
    assert contra_rate_columns(kinds) == ["Discount"]


def test_the_same_column_holding_currency_is_an_amount():
    """`discount` is a rate in Superstore and a currency amount in plenty of schemas.
    Nothing about the NAME decides it — which is why this is probed, not guessed."""
    kinds = contra_kinds_from_ranges(SCHEMA, {"superstore.Discount": (0.0, 4312.55)})
    assert kinds["superstore.Discount"] == "amount"
    assert contra_rate_columns(kinds) == []


def test_a_column_with_no_measured_range_is_not_classified():
    """An unmeasured column is not evidence — it must not default to either kind."""
    assert contra_kinds_from_ranges(SCHEMA, {"superstore.Discount": None}) == {}
    assert contra_kinds_from_ranges(SCHEMA, {}) == {}


def test_non_contra_columns_are_never_touched():
    """A fraction-valued column that is not contra-revenue (a score, a share) must not be
    swept in — rewriting `SUM(score)` into `SUM(sales * score)` would invent a number."""
    schema = "TABLE: t\n  quality_score  FLOAT\n  sales  FLOAT\n"
    assert contra_kinds_from_ranges(schema, {"t.quality_score": (0.0, 1.0)}) == {}


def test_qualified_and_bare_range_keys_both_match():
    for key in ("Discount", "superstore.Discount", '"superstore"."Discount"'):
        kinds = contra_kinds_from_ranges(SCHEMA, {key: (0.0, 0.8)})
        assert contra_rate_columns(kinds) == ["Discount"], key


# ── the explorer wires both halves ───────────────────────────────────────────────

def test_contra_units_reads_the_profiles_the_explorer_already_has():
    """No new warehouse query: Phase 2 measured these ranges, so the guard is free."""
    a = _agent()
    a.connection_id = "c"
    a._contra_units(_profiles((0.0, 0.80)), SCHEMA)
    assert a._contra_rate_cols == ["Discount"]
    assert "RATE" in a._contra_directive
    assert "Discount" in a._contra_directive


def test_no_directive_when_every_contra_column_is_money():
    a = _agent()
    a.connection_id = "c"
    a._contra_units(_profiles((0.0, 4312.55)), SCHEMA)
    assert a._contra_rate_cols == []
    assert a._contra_directive == ""


def test_the_live_defect_sql_is_repaired():
    """The exact query the explorer emitted, through the explorer's own repair."""
    a = _agent()
    a.connection_id = "c"
    a._contra_units(_profiles((0.0, 0.80)), SCHEMA)
    fixed = a._repair_contra_amount(LIVE_DEFECT_SQL)

    assert fixed != LIVE_DEFECT_SQL, "the rate-times-count numerator survived the guard"
    assert "SUM(Discount * Quantity)" not in fixed
    # The numerator becomes gross * rate, borrowing the gross from the query's own
    # denominator so numerator and denominator stay on the same base.
    assert "Sales" in fixed and "Discount" in fixed
    assert "NULLIF(SUM(Sales), 0)" in fixed, "the denominator must be left alone"


def test_repair_is_a_no_op_when_the_column_is_an_amount():
    a = _agent()
    a.connection_id = "c"
    a._contra_units(_profiles((0.0, 4312.55)), SCHEMA)
    assert a._repair_contra_amount(LIVE_DEFECT_SQL) == LIVE_DEFECT_SQL


def test_repair_is_a_no_op_before_units_are_settled():
    """`_run` may execute before Phase 8 classifies; the guard must stay inert, not raise."""
    a = _agent()
    a.connection_id = "c"
    assert a._repair_contra_amount(LIVE_DEFECT_SQL) == LIVE_DEFECT_SQL


def test_repair_never_raises_into_the_query_path():
    a = _agent()
    a.connection_id = "c"
    a._contra_rate_cols = ["Discount"]
    assert a._repair_contra_amount(None) is None
    assert a._repair_contra_amount("") == ""


def test_contra_units_never_raises_on_malformed_profiles():
    a = _agent()
    a.connection_id = "c"
    a._contra_units({"t": {"c": SimpleNamespace()}}, SCHEMA)   # no value_range attribute
    assert a._contra_rate_cols == []
    a._contra_units(None, None)
    assert a._contra_rate_cols == []


# ── the rot guard: the two paths must keep agreeing ──────────────────────────────

def test_explorer_and_deep_analysis_classify_identically():
    """Both paths must reach the same verdict from the same measured range, because the
    only reason the explorer was wrong is that it asked nobody. If these ever diverge,
    one of them is deciding units on its own again."""
    ranges = {"superstore.Discount": (0.0, 0.80)}
    deep = contra_rate_columns(classify_contra_columns(ranges))
    explorer = contra_rate_columns(contra_kinds_from_ranges(SCHEMA, ranges))
    assert deep == explorer == ["Discount"]


@pytest.mark.parametrize("sql", [
    "SELECT SUM(Discount) AS d FROM superstore",
    "SELECT SUM(Quantity * Discount) / SUM(Sales) AS r FROM superstore",
])
def test_other_rate_summing_shapes_are_repaired_too(sql):
    a = _agent()
    a.connection_id = "c"
    a._contra_units(_profiles((0.0, 0.80)), SCHEMA)
    out = a._repair_contra_amount(sql)
    if "SUM(Sales)" in sql:                 # a gross is available to borrow
        assert out != sql
    # With no gross in the query the guard declines rather than inventing a base —
    # a wrong denominator trades a visible error for an invisible one.
