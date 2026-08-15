"""Two categorical dimensions, and whether they relate — the primitive and the plan.

Built 2026-08-15 from a real report. Asked *"How do Ship Mode and Sub-categories
relate?"*, the platform produced two separate rankings — sub-category totals, then ship
mode totals — and called it the answer. Those are MARGINALS: they are true whatever the
relationship is, so they cannot describe one. The joint distribution was never computed,
and no test existed that could have judged it.

Measured on the actual Superstore data, the answer is a clean null: χ²(48)=49.7, p=0.41,
Cramér's V=0.04 — ship mode is chosen independently of what is in the cart. That is a
decision ("do not segment shipping strategy by product category"), and the platform could
not reach it because *no relationship* was not an answer it could produce.

Two halves, both covered here:
  * `stats.assess_association` — χ², Cramér's V, standardised residuals, and the gate
    that refuses to run a frequency test on money;
  * the plan — detect the question shape, cross the two dimensions the question NAMED,
    and lead the phase with the verdict.
"""
from __future__ import annotations

import numpy as np
import pytest

from aughor.agent.investigate import (
    _association_finding,
    _dimensions_named_in_question,
    _question_asks_association,
)
from aughor.tools.stats import analyze_query_result, assess_association

_MODES = ["First Class", "Same Day", "Second Class", "Standard Class"]


def _independent_table(rows: int = 6, n_per: int = 400) -> list[list[float]]:
    """Rows with an identical column mix — independence by construction, with the row
    TOTALS varying wildly, because that is the case the old report got wrong: it saw
    different totals and called them a relationship."""
    mix = np.array([0.15, 0.05, 0.20, 0.60])
    return [(mix * n_per * (i + 1)).round().tolist() for i in range(rows)]


# ── the primitive ─────────────────────────────────────────────────────────────

def test_identical_mixes_are_independent():
    res = assess_association(_independent_table(), [f"r{i}" for i in range(6)], _MODES)
    assert res is not None
    assert res.is_dependent is False
    assert res.cramers_v < 0.05
    assert res.p_value > 0.05
    assert "INDEPENDENT" in res.interpretation
    # The directive matters as much as the verdict — this is the sentence that stops a
    # narrator reporting the biggest group as though it were the relationship.
    assert "do NOT report a driver" in res.interpretation


def test_a_nested_hierarchy_is_perfectly_dependent():
    # Each row lives in exactly one column (category → sub-category). Cramér's V = 1.
    table = [[500, 0, 0], [0, 300, 0], [0, 0, 700], [400, 0, 0]]
    res = assess_association(table, ["a", "b", "c", "d"], ["x", "y", "z"])
    assert res is not None
    assert res.is_dependent is True
    assert res.cramers_v == pytest.approx(1.0, abs=1e-6)
    assert res.p_value < 0.01
    assert "RELATED" in res.interpretation


def test_a_sparse_grid_is_not_rejected_for_being_sparse():
    """The first cut required half the grid to be filled and so rejected `region × state`
    — where each state sits in exactly one region. That sparsity IS the dependence: the
    most strongly related pairs are the emptiest grids."""
    table = np.zeros((4, 20))
    for j in range(20):
        table[j % 4][j] = 100 + j          # every column belongs to exactly one row
    res = assess_association(table, [f"reg{i}" for i in range(4)], [f"st{j}" for j in range(20)])
    assert res is not None and res.is_dependent is True


def test_a_significant_but_trivial_association_is_reported_independent():
    """On a big table a negligible dependence clears p<0.05. "Significant" and "matters"
    are different claims, and reporting the first as the second is how a null result
    becomes a driver story."""
    base = np.array([0.15, 0.05, 0.20, 0.60])
    table = [(base * 50_000).tolist() for _ in range(5)]
    table[0][0] += 1500                    # a real skew — and utterly immaterial at n=250k
    table[0][3] -= 1500
    res = assess_association(table, [f"r{i}" for i in range(5)], _MODES)
    assert res is not None
    assert res.p_value < 1e-10, "the test detects it overwhelmingly…"
    assert res.cramers_v < 0.10, "…but the effect size is negligible"
    assert res.is_dependent is False, "so the verdict must be independent"


def test_money_gets_no_p_value():
    """A chi-square test of independence is defined on COUNTS. Run it on summed revenue
    and the p-value is arithmetic without a meaning — dollars are not independent trials,
    and the number would change with the units. The first version did exactly that and
    reported a confident '+207σ' on Superstore sales."""
    table = [[10_000.0, 2_000.0, 500.0], [900.0, 30_000.0, 40.0], [77.0, 12.0, 60_000.0]]
    res = assess_association(table, ["a", "b", "c"], ["x", "y", "z"], is_frequency=False)
    assert res is not None
    assert res.p_value is None
    assert res.chi2 is None
    assert res.is_dependent is False, "no dependence may be CLAIMED without a valid test"
    assert "COMPOSITION ONLY" in res.interpretation
    assert "percentage points" in res.interpretation
    assert "COUNT(*)" in res.interpretation, "must say how to get a real verdict"
    assert "σ" not in res.interpretation, "no sigma may be quoted for non-frequency data"


@pytest.mark.parametrize("table", [
    [[1.0, 2.0]],                       # one row — no second dimension
    [[1.0], [2.0]],                     # one column
    [[0.0, 0.0], [0.0, 0.0]],           # empty
    [[1.0, 2.0], [-3.0, 4.0]],          # negative counts are not frequencies
])
def test_degenerate_tables_return_nothing(table):
    assert assess_association(table, ["a", "b"], ["x", "y"]) is None


# ── auto-attachment: it fires wherever a cross-tab is computed ────────────────

def _long_form(table, rows_labels, col_labels, measure="n_records"):
    cols = ["dim_a", "dim_b", measure]
    rows = [[r, c, table[i][j]]
            for i, r in enumerate(rows_labels) for j, c in enumerate(col_labels)]
    return cols, rows


def test_a_cross_tab_result_gets_the_verdict_attached():
    cols, rows = _long_form(_independent_table(), [f"r{i}" for i in range(6)], _MODES)
    stats = [s for s in analyze_query_result(cols, rows) if s.type == "association"]
    assert len(stats) == 1
    assert "INDEPENDENT" in stats[0].interpretation
    # Marked significant on purpose: a null result is the finding that stops the report
    # inventing a driver, so it must reach the narrator.
    assert stats[0].is_significant is True


def test_row_level_data_is_not_mistaken_for_a_cross_tab():
    """A GROUP BY a, b emits each pair exactly once. Duplicates mean these are raw rows,
    and summing them into a grid would test something nobody computed."""
    cols = ["dim_a", "dim_b", "amount"]
    rows = [["a", "x", 1.0], ["a", "x", 2.0], ["b", "y", 3.0], ["b", "y", 4.0],
            ["a", "y", 5.0], ["b", "x", 6.0]]
    assert not [s for s in analyze_query_result(cols, rows) if s.type == "association"]


def test_a_single_dimension_result_is_left_alone():
    cols = ["sub_category", "gross_sales"]
    rows = [["Fasteners", 3024.0], ["Labels", 12500.0], ["Envelopes", 16500.0],
            ["Storage", 223800.0], ["Tables", 207000.0]]
    assert not [s for s in analyze_query_result(cols, rows) if s.type == "association"]


# ── the plan: recognising the question ────────────────────────────────────────

@pytest.mark.parametrize("q", [
    "How do Ship Mode and Sub-categories relate?",
    "What is the relationship between region and profit?",
    "Is there any correlation between discount and returns?",
    "Does segment affect shipping speed?",
    "How are category and region related?",
    "ship mode vs sub-category",
    "Does profit vary by region?",
])
def test_relationship_questions_are_recognised(q):
    assert _question_asks_association(q) is True


@pytest.mark.parametrize("q", [
    "Which sub-category is weakest?",          # the weakness scan is right for this
    "Why did revenue drop in Q3?",
    "Show me gross sales by ship mode",
    "What are the top 10 products?",
    "Where are we losing money?",
])
def test_ranking_questions_are_left_to_the_weakness_scan(q):
    assert _question_asks_association(q) is False


_DIMS = ["orders.ship_mode", "orders.sub_category", "orders.category",
         "orders.region", "orders.segment"]


def test_the_named_dimensions_are_the_ones_crossed():
    named = _dimensions_named_in_question("How do Ship Mode and Sub-categories relate?", _DIMS)
    assert named[:2] == ["orders.ship_mode", "orders.sub_category"]


def test_the_more_specific_dimension_wins():
    """"Sub-categories" matches both `sub_category` and `category`; crossing the loose
    one answers a different question."""
    named = _dimensions_named_in_question("relate sub-categories to ship mode", _DIMS)
    assert "orders.sub_category" in named
    assert "orders.category" not in named


def test_order_follows_the_question_not_the_schema():
    named = _dimensions_named_in_question("how do regions and segments relate", _DIMS)
    assert named == ["orders.region", "orders.segment"]


def test_an_unnamed_pair_is_not_invented():
    assert _dimensions_named_in_question("how do things relate", _DIMS) == []


# ── the finding ───────────────────────────────────────────────────────────────

class _FakeResult:
    """Shaped like what `_execute_safe` ACTUALLY returns — crucially, with `stats`
    EMPTY. The first version of this fixture pre-computed `analyze_query_result` into
    `self.stats`, fabricating the one precondition production does not satisfy: the
    investigate path never attaches stats (only the explore path calls `_attach_stats`).
    So the finding was silently dropped on the first live run while this test passed."""

    def __init__(self, cols, rows, sql="SELECT 1", stats=None):
        self.sql, self.columns, self.rows = sql, cols, rows
        self.row_count, self.error = len(rows), None
        self.stats = stats or []


def test_the_finding_is_built_from_a_result_with_no_stats_attached():
    """The live failure, pinned: `_execute_safe` returns a result whose `stats` is empty,
    so the finding must compute the verdict itself instead of assuming an upstream step
    ran the analyser."""
    cols, rows = _long_form(_independent_table(), [f"r{i}" for i in range(6)], _MODES)
    result = _FakeResult(cols, rows)
    assert result.stats == [], "the fixture must mirror _execute_safe, which attaches nothing"
    f = _association_finding(result, "ship_mode", "sub_category")
    assert f is not None
    assert f["title"] == "ship_mode × sub_category: are they related?"
    # A grid answer deserves a grid chart; two bar charts are what marginals look like.
    assert f["chart_type"] == "heatmap"
    assert "INDEPENDENT" in f["interpretation"]
    assert f["is_significant"] is True
    assert f["stat_note"] == f["interpretation"]


def test_no_finding_without_a_verdict():
    """A result that is not a cross-tab produces no association stat, and therefore no
    finding — rather than an empty card claiming to have tested something."""
    f = _association_finding(_FakeResult(["a", "b"], [["x", 1.0], ["y", 2.0]]), "a", "b")
    assert f is None


# ── the parallel path must not silently skip it ───────────────────────────────

def test_the_multilens_path_runs_the_scan_too(monkeypatch):
    """Every lens is invoked with `dims_override` set — which is the very guard the scan
    uses to avoid running once per lens. So on a transport that allows concurrent lenses
    the scan would never run at all, and a relationship question would quietly go back to
    being answered by marginal rankings. Caught by reading the code, not by a test run:
    the local binding is serial, so no suite here would have exercised it."""
    import inspect

    from aughor.agent import investigate as inv

    src = inspect.getsource(inv.ada_cross_section_multilens)
    assert "_run_association_scan(" in src, \
        "the parallel path must run the association scan itself"
    assert "_assoc_finding" in src and "merged = [_first]" in src, \
        "and must merge the verdict into the leading phase"
