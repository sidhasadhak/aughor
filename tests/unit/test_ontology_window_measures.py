"""Wave O5 — declared window and semiadditive measures.

The carrying test is :func:`test_a_semiadditive_measure_cannot_compile_to_a_sum` — an
inventory level or account balance summed across time produces a number with no meaning
and nothing about the result looks wrong. Declaring the measure makes that answer
inexpressible rather than merely caught after the fact.

Second is :func:`test_last_value_gets_an_explicit_frame`: the SQL default frame makes
LAST_VALUE return the CURRENT row, which is the most common window-function bug and yields
a plausible wrong number.
"""
from __future__ import annotations

import pytest

from aughor.ontology.window_measures import (
    RANGES,
    SEMIADDITIVE,
    MeasureDeclarationError,
    WindowMeasure,
    compile_measure,
    describe,
    from_declaration,
    period_over_period,
)


def _m(**kw) -> WindowMeasure:
    base = {"expression": "SUM(gmv_eur)", "order_by": "order_date"}
    return WindowMeasure(**{**base, **kw})


# ── frames ──────────────────────────────────────────────────────────────────────────

def test_current_with_no_partition_stays_plain_sql():
    """No frame is needed, and adding one would obscure a simple aggregate."""
    assert compile_measure(_m(range="current")) == "SUM(gmv_eur)"


def test_trailing_counts_the_current_period():
    """'Trailing 7 days' means 7 days, not 8 — an off-by-one here is a wrong number
    that looks entirely reasonable."""
    sql = compile_measure(_m(range="trailing", window=7))
    assert "ROWS BETWEEN 6 PRECEDING AND CURRENT ROW" in sql


def test_leading_counts_the_current_period_too():
    assert "CURRENT ROW AND 2 FOLLOWING" in compile_measure(_m(range="leading", window=3))


def test_cumulative_runs_from_the_start():
    assert "UNBOUNDED PRECEDING AND CURRENT ROW" in compile_measure(_m(range="cumulative"))


def test_all_spans_the_whole_partition():
    sql = compile_measure(_m(range="all", order_by=""))
    assert "UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING" in sql


def test_partition_by_is_emitted():
    sql = compile_measure(_m(range="cumulative", partition_by=("platform",)))
    assert "PARTITION BY platform" in sql and "ORDER BY order_date" in sql


# ── semiadditive: the one that silently corrupts ────────────────────────────────────

def test_a_semiadditive_measure_cannot_compile_to_a_sum():
    """An inventory level summed across December's days is meaningless and looks fine.
    The declaration makes that answer inexpressible, not merely catchable."""
    sql = compile_measure(_m(expression="SUM(balance)", semiadditive="last"))
    assert "SUM(" not in sql
    assert sql.startswith("LAST_VALUE(balance)")


def test_first_and_last_pick_the_right_end():
    assert compile_measure(_m(expression="SUM(x)", semiadditive="first")).startswith(
        "FIRST_VALUE(")
    assert compile_measure(_m(expression="SUM(x)", semiadditive="last")).startswith(
        "LAST_VALUE(")


def test_last_value_gets_an_explicit_frame():
    """The SQL default (RANGE UNBOUNDED PRECEDING) makes LAST_VALUE return the CURRENT
    row — the most common window-function bug, and it yields a plausible wrong number."""
    sql = compile_measure(_m(expression="SUM(balance)", semiadditive="last"))
    assert "UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING" in sql


def test_the_description_says_it_is_not_summable():
    text = describe(_m(expression="SUM(balance)", semiadditive="last"))
    assert "NOT summable across time" in text


# ── the aggregate strip ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("expr,inner", [
    ("SUM(balance)", "balance"), ("avg(x)", "x"), ("MAX(qty)", "qty"),
    ("COUNT(id)", "id"),
])
def test_a_recognised_aggregate_is_stripped(expr, inner):
    """FIRST_VALUE takes a VALUE, not an aggregate; nesting one is a SQL error at best
    and a wrong grain at worst."""
    assert compile_measure(_m(expression=expr, semiadditive="last")).startswith(
        f"LAST_VALUE({inner})")


def test_an_unrecognised_expression_passes_through_untouched():
    """Guessing at a complex expression's inner value is how a formula silently changes
    meaning, so the strip is deliberately conservative."""
    expr = "SUM(a) / NULLIF(SUM(b), 0)"
    assert f"LAST_VALUE({expr})" in compile_measure(
        _m(expression=expr, semiadditive="last"))


# ── period over period ──────────────────────────────────────────────────────────────

def test_offset_compiles_to_a_lag():
    assert compile_measure(_m(offset=1)).startswith("LAG(gmv_eur, 1)")


def test_period_over_period_returns_a_pair_not_a_growth_formula():
    """The division is where the interesting decisions live — zero denominators, percent
    vs ratio, absolute vs relative — and baking one in would hide them."""
    current, prior = period_over_period("SUM(gmv_eur)", "fiscal_year", offset=1)
    assert current == "SUM(gmv_eur)"
    assert prior.startswith("LAG(gmv_eur, 1)")
    assert "/" not in current and "/" not in prior


# ── declarations that must be refused ───────────────────────────────────────────────

def test_a_frame_without_an_ordering_column_is_refused():
    """'Trailing 7' of an unordered set is not a question."""
    with pytest.raises(MeasureDeclarationError, match="order_by"):
        compile_measure(_m(range="trailing", window=7, order_by=""))


@pytest.mark.parametrize("kw,match", [
    ({"range": "trailing"}, "needs a positive `window`"),
    ({"range": "leading", "window": 0}, "needs a positive `window`"),
    ({"range": "sideways"}, "unknown range"),
    ({"semiadditive": "middle"}, "unknown semiadditive"),
    ({"offset": -1}, "cannot be negative"),
    ({"expression": "  "}, "needs an expression"),
])
def test_malformed_declarations_raise_with_the_reason(kw, match):
    with pytest.raises(MeasureDeclarationError, match=match):
        compile_measure(_m(**kw))


def test_a_bad_declaration_never_falls_back_to_free_form():
    """A declared measure that quietly becomes free-form generation is indistinguishable
    from never having declared it, which defeats the point of declaring."""
    with pytest.raises(MeasureDeclarationError):
        from_declaration({"expression": "SUM(x)", "range": "trailing"})


def test_from_declaration_round_trips():
    m = from_declaration({"expression": "SUM(gmv)", "order_by": "d", "range": "trailing",
                          "window": 7})
    assert m.window == 7 and compile_measure(m)
    assert m.to_dict()["range"] == "trailing"


def test_the_vocabularies_are_stated():
    assert RANGES == ("current", "cumulative", "trailing", "leading", "all")
    assert SEMIADDITIVE == ("first", "last")


@pytest.mark.parametrize("expr", [
    "SUM(a) / NULLIF(SUM(b), 0)",          # starts with sum( AND ends with ) — the trap
    "SUM(a) + SUM(b)",
    "COUNT(x) - COUNT(y)",
])
def test_a_compound_expression_is_never_half_stripped(expr):
    """Regression. `SUM(a) / NULLIF(SUM(b), 0)` starts with 'sum(' and ends with ')', so a
    prefix+suffix strip turned it into `a) / NULLIF(SUM(b), 0` — which nests into RUNNABLE
    SQL computing something else entirely. The closing paren must be the one the aggregate
    opened."""
    sql = compile_measure(_m(expression=expr, semiadditive="last"))
    assert f"LAST_VALUE({expr})" in sql


def test_a_nested_aggregate_call_still_strips():
    """The paren scan must not be so strict it refuses legitimate nesting."""
    sql = compile_measure(_m(expression="SUM(COALESCE(x, 0))", semiadditive="last"))
    assert sql.startswith("LAST_VALUE(COALESCE(x, 0))")
