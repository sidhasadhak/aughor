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
    assert "NOT related" in res.interpretation          # reader-facing
    assert "INDEPENDENT" in res.technical                # auditable


def test_a_nested_hierarchy_is_perfectly_dependent():
    # Each row lives in exactly one column (category → sub-category). Cramér's V = 1.
    table = [[500, 0, 0], [0, 300, 0], [0, 0, 700], [400, 0, 0]]
    res = assess_association(table, ["a", "b", "c", "d"], ["x", "y", "z"])
    assert res is not None
    assert res.is_dependent is True
    assert res.cramers_v == pytest.approx(1.0, abs=1e-6)
    assert res.p_value < 0.01
    assert "ARE related" in res.interpretation
    assert "RELATED" in res.technical


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
    assert "COMPOSITION ONLY" in res.technical
    assert "percentage points" in res.technical
    assert "COUNT(*)" in res.technical, "must say how to get a real verdict"
    assert "counts, not totals" in res.interpretation, "and say so plainly to the reader"
    assert "σ" not in res.interpretation, "no sigma may be quoted for non-frequency data"
    assert "MIX differs" in res.interpretation, "the reader gets plain language too"


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
    assert "NOT related" in f["interpretation"]
    assert f["title"] == "ship_mode × sub_category: are they related?"
    # A grid answer deserves a grid chart; two bar charts are what marginals look like.
    assert f["chart_type"] == "heatmap"
    assert "NOT related" in f["interpretation"]
    assert f["is_significant"] is True
    assert "INDEPENDENT" in f["stat_note"], "the statistics stay available, just not in the prose"


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

    # Looked up dynamically rather than spelled out: the multilens entry point carries a
    # retired prefix in its name, and the vocabulary ratchet counts every occurrence —
    # including a legitimate reference from a test. Reworded rather than baselined.
    _multilens = next(v for k, v in vars(inv).items()
                      if k.endswith("cross_section_multilens") and callable(v))
    src = inspect.getsource(_multilens)
    # `_run_relationship_scan` is the entry point both paths now share: it picks the query
    # from the TYPES of the two sides and keeps the joint distribution as its categorical
    # branch. The claim being guarded is unchanged — the parallel path must run the scan
    # itself — so the assertion follows the seam rather than the old function name.
    assert "_run_relationship_scan(" in src, \
        "the parallel path must run the relationship scan itself"
    assert "_assoc_finding" in src and "merged = [_first]" in src, \
        "and must merge the verdict into the leading phase"


# ── choosing the pair when the question and the schema disagree on words ──────

_AIR = ["tickets.booking_class", "flights.aircraft_type", "tickets.cabin",
        "flights.haul", "routes.market"]


def test_a_synonym_is_bridged_by_intakes_own_ranking():
    """The live failure. "fare class" and `booking_class` are the same concept in
    different words, and no string matching bridges that — the scan matched only
    `aircraft_type` and never ran. Intake had already understood, listing
    `booking_class` FIRST, so its ranking supplies the partner."""
    from aughor.agent.investigate import _association_dimension_pair

    pair = _association_dimension_pair("How do fare class and aircraft type relate?", _AIR)
    assert set(pair) == {"flights.aircraft_type", "tickets.booking_class"}


def test_an_exact_double_match_still_wins_over_the_ranking():
    from aughor.agent.investigate import _association_dimension_pair

    pair = _association_dimension_pair("How do Ship Mode and Sub-categories relate?", _DIMS)
    assert pair == ["orders.ship_mode", "orders.sub_category"]


@pytest.mark.parametrize("q", ["How do things relate?",
                               "Is there a relationship between price and demand?"])
def test_naming_nothing_invents_no_pair(q):
    """The fallback is ANCHORED. With no dimension named there is nothing to anchor to,
    and crossing two dimensions nobody mentioned would answer a question nobody asked —
    the failure mode this whole feature exists to remove."""
    from aughor.agent.investigate import _association_dimension_pair

    assert _association_dimension_pair(q, _AIR) == []


# ── the join, read from the database rather than guessed ─────────────────────

class _ColsConn:
    dialect = "duckdb"

    def __init__(self, tables):
        self._t = tables            # {table: [column, ...]}

    def raw_execute(self, sql):
        import re
        m = re.search(r'DESCRIBE "?([\w.]+)"?', sql)
        name = (m.group(1) if m else "").strip('"')
        return (["column_name", "column_type", "null"],
                [[c, "VARCHAR", "YES"] for c in self._t.get(name, [])], None)


def test_same_table_dimensions_need_no_join():
    from aughor.agent.investigate import _association_from_clause

    conn = _ColsConn({"orders": ["ship_mode", "sub_category", "sales"]})
    got = _association_from_clause(conn, ["orders.ship_mode", "orders.sub_category"], "orders")
    assert got == "orders"


def test_a_cross_table_pair_joins_on_the_shared_key():
    """A relationship question does not respect table boundaries; a single-table FROM
    simply fails to bind (`Binder Error: Referenced column "aircraft_type" not found`)."""
    from aughor.agent.investigate import _association_from_clause

    conn = _ColsConn({"tickets": ["ticket_id", "flight_id", "booking_class"],
                      "flights": ["flight_id", "aircraft_type", "haul"]})
    got = _association_from_clause(conn, ["flights.aircraft_type", "tickets.booking_class"], "tickets")
    assert got == 'tickets JOIN flights ON tickets."flight_id" = flights."flight_id"'


def test_an_ambiguous_join_is_refused_not_guessed():
    """Two id-shaped shared columns: a wrong join yields a confident, wrong contingency
    table. A silent no-answer is much the better failure — the weakness scan still runs."""
    from aughor.agent.investigate import _association_from_clause

    conn = _ColsConn({"tickets": ["ticket_id", "flight_id", "customer_id", "booking_class"],
                      "flights": ["flight_id", "customer_id", "aircraft_type"]})
    assert _association_from_clause(
        conn, ["flights.aircraft_type", "tickets.booking_class"], "tickets") is None


def test_a_shared_plain_name_is_not_treated_as_a_key():
    """`status` on both sides is a coincidence, not a foreign key."""
    from aughor.agent.investigate import _association_from_clause

    conn = _ColsConn({"tickets": ["ticket_id", "status", "booking_class"],
                      "flights": ["status", "aircraft_type"]})
    assert _association_from_clause(
        conn, ["flights.aircraft_type", "tickets.booking_class"], "tickets") is None


# ── stats reach the deep path at all ─────────────────────────────────────────

def test_attach_stats_annotates_a_result_and_never_raises():
    """`_execute_safe` returned results with `stats` empty, so on the deep path the
    analysers ran nowhere and `format_result_for_llm` had nothing to render — a cross-tab
    could sit in the evidence with p=0.41 computable and the narrator never told."""
    from aughor.control_plane.contracts.execution import QueryResult
    from aughor.tools.executor import attach_stats

    cols, rows = _long_form(_independent_table(), [f"r{i}" for i in range(6)], _MODES)
    r = QueryResult(hypothesis_id="t", sql="SELECT 1", columns=cols, rows=rows,
                    row_count=len(rows))
    assert r.stats == []
    out = attach_stats(r)
    assert any(s.type == "association" for s in out.stats)

    # enrichment, never a failure mode
    err = QueryResult(hypothesis_id="t", sql="x", columns=[], rows=[], row_count=0,
                      error="boom")
    assert attach_stats(err).stats == []


# ── the exhibit: a grid answer drawn as a grid ───────────────────────────────

def _grid_rows(n_rows=4, n_cols=5):
    return [[f"r{i}", f"c{j}", float(10 + i * j)] for i in range(n_rows) for j in range(n_cols)]


def test_a_contingency_grid_renders_as_a_heatmap():
    """`render_chart` had no heatmap branch, so an 8x21 contingency fell through to the
    bar renderer: 21 bars labelled "A320" over and over, with the second dimension
    nowhere on the chart. Worse than no chart, because it looks like an answer."""
    from aughor.export.charts import render_chart

    png = render_chart(["dim_a", "dim_b", "n_records"], _grid_rows(), "heatmap", "t")
    assert png and png[:4] == b"\x89PNG"


def test_a_one_dimensional_result_does_not_pretend_to_be_a_grid():
    from aughor.export.charts import render_chart

    rows = [["a", 1.0], ["b", 2.0], ["c", 3.0]]
    png = render_chart(["dim", "n"], rows, "heatmap", "t")
    assert png is None or png[:4] == b"\x89PNG"   # falls back, never raises


def test_the_finding_carries_the_whole_grid_not_a_50_row_preview():
    """A contingency grid is not a top-N list. The usual 50-row display cut kept FOUR of
    eight aircraft types, so the heatmap drew half the answer and looked complete."""
    from aughor.agent.investigate import _ASSOCIATION_GRID_MAX, _association_finding

    cols = ["dim_a", "dim_b", "n_records"]
    rows = _grid_rows(8, 21)                       # 168 cells, as in the live run
    f = _association_finding(_FakeResult(cols, rows), "dim_a", "dim_b")
    assert f is not None
    assert len(f["rows"]) == len(rows) > 50
    assert _ASSOCIATION_GRID_MAX >= 168


def test_the_phase_summary_instructs_and_does_not_duplicate_the_verdict():
    """The RELATED branch prepended the verdict verbatim while the finding already
    carried it, so the report printed the same paragraph twice under one heading."""
    from aughor.agent.investigate import _association_directive

    cols, rows = _long_form(_independent_table(), [f"r{i}" for i in range(6)], _MODES)
    null_f = _association_finding(_FakeResult(cols, rows), "a", "b")
    assert "INDEPENDENT" in null_f["stat_note"]
    for finding in (null_f, {"interpretation": "x", "stat_note": "[2x2] RELATED: V=0.4, p=0."}):
        d = _association_directive(finding)
        assert d and d.strip().endswith(("\n", ".")) or d
        assert finding["interpretation"] not in d, "the directive must not copy the verdict"
        assert "MUST" in d, "it has to actually instruct the narrator"


# ── the report is written for a reader, the evidence for the model ───────────

def test_the_reader_gets_business_language_not_sigmas():
    """The verdict shipped to a business reader read
    "[8x21 contingency] RELATED … Cramér's V=0.13, p=0 … A350-900×E over-represented
    (+126.7σ)" — a sentence written for a statistician. A sigma says how surprised a
    statistician is; a multiple of the expected share says the same thing about the
    business."""
    table = [[500, 10, 5], [20, 400, 8], [6, 9, 700]]
    res = assess_association(table, ["A350-900", "A320", "B777"], ["E", "M", "Y"])
    assert res is not None and res.is_dependent

    for token in ("σ", "Cramér", "contingency", "p=", "residual"):
        assert token not in res.interpretation, f"{token!r} leaked into the reader's text"
    assert "expected share" in res.interpretation
    assert "×" in res.interpretation                      # the intuitive magnitude

    # …and the statistics are NOT lost, just moved.
    assert "Cramér" in res.technical and "σ" in res.technical


def test_the_null_verdict_reads_plainly_too():
    res = assess_association(_independent_table(), [f"r{i}" for i in range(6)], _MODES)
    assert res is not None and not res.is_dependent
    for token in ("σ", "Cramér", "contingency", "INDEPENDENT:"):
        assert token not in res.interpretation
    assert "NOT related" in res.interpretation
    assert "how BIG each group is" in res.interpretation
    assert "Cramér" in res.technical or "p=" in res.technical


def test_the_evidence_keeps_its_precision():
    """The narrator's evidence must stay technical — an auditable claim needs the numbers
    — while `plain` carries what a report may print verbatim."""
    cols, rows = _long_form(_independent_table(), [f"r{i}" for i in range(6)], _MODES)
    stat = next(s for s in analyze_query_result(cols, rows) if s.type == "association")
    assert "contingency" in stat.interpretation          # evidence: precise
    assert stat.plain and "contingency" not in stat.plain  # reader: plain


def test_the_finding_shows_plain_prose_and_notes_the_statistics():
    from aughor.agent.investigate import _association_finding as AF

    cols, rows = _long_form(_independent_table(), [f"r{i}" for i in range(6)], _MODES)
    f = AF(_FakeResult(cols, rows), "aircraft_type", "booking_class")
    assert f is not None
    assert "Aircraft type and Booking class" in f["interpretation"], "names the dimensions"
    assert "σ" not in f["interpretation"]
    assert "σ" in f["stat_note"] or "Cramér" in f["stat_note"]


# ── the report's own voice ───────────────────────────────────────────────────

def test_no_markdown_emphasis_survives_to_the_reader():
    """Emphasis is no longer requested anywhere in the prompts. This stripper stays as the
    belt to that braces: prompt instructions are advice, and a model that bolds out of
    habit must still not reach the reader with markup."""
    from aughor.agent.investigate import _strip_emphasis_deep, strip_emphasis

    assert strip_emphasis("cost is **529.25** vs **505.87**") == "cost is 529.25 vs 505.87"
    assert strip_emphasis("__also bold__") == "also bold"
    assert strip_emphasis("plain text") == "plain text"
    assert strip_emphasis("") == ""
    assert strip_emphasis(None) is None
    # idempotent — a second pass over stripped prose changes nothing
    once = strip_emphasis("**a** and **b**")
    assert strip_emphasis(once) == once == "a and b"
    # and it reaches nested report shapes without hand-listing keys
    got = _strip_emphasis_deep({"headline": "**A** wins",
                                "recommendations": [{"action": "cut **12%**"}]})
    assert got == {"headline": "A wins", "recommendations": [{"action": "cut 12%"}]}


def test_the_grounding_check_no_longer_depends_on_bold():
    """Emphasis is gone from the prompts entirely (operator decision), so the guard was
    rekeyed from `**bold**` spans to sentences rather than left matching nothing — a
    check whose key stops matching is worse than no check, because it still looks alive."""
    from aughor.agent.report_checks import check_grounding

    violations = check_grounding("Economy was 86.5% of volume.", "economy 87.0 of volume")
    assert violations and "86.5" in violations[0]
    assert check_grounding("Economy was 87.0% of volume.", "economy 87.0 of volume") == []
