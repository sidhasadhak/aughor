"""Hermetic unit tests for the overview fact builder (``aughor.overview.build``).

No real DB and no LLM: a fake connection returns canned, STRINGIFIED query results
(exactly as DuckDB/Postgres emit them) keyed by SQL substring. The fixture is a small
2-table airline-ish schema designed so several lenses fire, so we can assert the
selection stays a DIVERSE tour and the deterministic headlines/percentages are correct.
"""
from __future__ import annotations

import re

import pytest

from aughor.overview.build import OverviewFact, _select, build_overview

# The exact key set every OverviewFact.to_dict() must expose (frontend contract).
FACT_KEYS = {
    "lens", "headline", "stat", "stat_label", "why", "notability", "table",
    "measure", "dimension", "sql", "columns", "rows", "chart_type", "chart_config",
}


# ── fake connection ───────────────────────────────────────────────────────────

class FakeResult:
    """A QueryResult stand-in: stringified cells, an ``.error`` sentinel."""

    def __init__(self, columns, rows, error=None):
        self.columns = list(columns)
        self.rows = [list(r) for r in rows]
        self.error = error


# SUMMARIZE returns these columns, in this order (real DuckDB shape).
_SUMMARIZE_COLS = [
    "column_name", "column_type", "min", "max", "approx_unique",
    "avg", "std", "q25", "q50", "q75", "count", "null_percentage",
]


def _srow(name, ctype, mn, mx, approx, avg, q50, count, nullpct="0.0"):
    """One SUMMARIZE row (every cell stringified, NULLs as the literal 'NULL')."""
    return [name, ctype, str(mn), str(mx), str(approx), str(avg),
            "NULL", "NULL", str(q50), "NULL", str(count), str(nullpct)]


# s.tickets — a wide fact table. fare_chf is a non-negative measure; net_miles is a
# SIGNED measure (min −5000) that must NOT be picked as the concentration measure.
_TICKETS_SUMMARIZE = FakeResult(_SUMMARIZE_COLS, [
    _srow("fare_chf", "DOUBLE", 6, 19719, 8213, 313.0, 97, 273878),
    _srow("cabin", "VARCHAR", "Business", "Premium", 4, "NULL", "NULL", 273878),
    _srow("refundable", "BOOLEAN", "false", "true", 2, "NULL", "NULL", 273878),
    _srow("segment_status", "VARCHAR", "cancelled", "no_show", 3, "NULL", "NULL", 273878),
    _srow("currency", "VARCHAR", "CHF", "CHF", 1, "NULL", "NULL", 273878),
    _srow("net_miles", "DOUBLE", -5000, 8000, 9000, 1500.0, 1400, 273878),
])

# s.baggage — a big table of only ids: no material dimension, so it stays UNTOUCHED
# by the group-by lenses and surfaces as a coverage ("sizable, no metric touched") fact.
_BAGGAGE_SUMMARIZE = FakeResult(_SUMMARIZE_COLS, [
    _srow("baggage_id", "BIGINT", 1, 261610, 261610, "NULL", "NULL", 261610),
    _srow("ticket_id", "BIGINT", 1, 273878, 270000, "NULL", "NULL", 261610),
    _srow("passenger_id", "BIGINT", 1, 90000, 90000, "NULL", "NULL", 261610),
])

# cabin group-by (ordered by SUM(fare) DESC): skewed enough for a concentration fact,
# with a large first-vs-economy per-record ratio (a "relationship" driver fact).
_CABIN_GROUPS = FakeResult(["grp", "n", "val"], [
    ["Business", "50000", "20000000.0"],   # ~400 / record
    ["Economy", "200000", "18000000.0"],   # ~90  / record
    ["First", "3000", "13800000.0"],       # ~4600 / record
    ["Premium", "20878", "3131700.0"],     # ~150 / record
])

# segment_status group-by: dominated by 'flown' (a 95.3% share → clean concentration),
# per-record held constant so no spurious outlier/relationship fires.
_SEGMENT_GROUPS = FakeResult(["grp", "n", "val"], [
    ["flown", "95300", "953000.0"],
    ["cancelled", "3000", "30000.0"],
    ["no_show", "1700", "17000.0"],
])

# the single-value probe for currency
_CURRENCY_ONE = FakeResult(["currency"], [["CHF"]])


class FakeConn:
    """Routes ``execute(label, sql)`` to a canned FakeResult by SQL substring."""

    def __init__(self):
        self.seen: list[str] = []
        self._routes = [
            (["SUMMARIZE", "s.tickets"], _TICKETS_SUMMARIZE),
            (["SUMMARIZE", "s.baggage"], _BAGGAGE_SUMMARIZE),
            (["SELECT currency FROM s.tickets", "LIMIT 1"], _CURRENCY_ONE),
            (["cabin AS grp"], _CABIN_GROUPS),
            (["segment_status AS grp"], _SEGMENT_GROUPS),
        ]

    def execute(self, label, sql):
        self.seen.append(sql)
        for needles, result in self._routes:
            if all(n in sql for n in needles):
                return result
        # Any SQL we didn't anticipate surfaces as an error (→ _probe yields no rows),
        # never a silent wrong answer.
        return FakeResult([], [], error=f"no canned response for: {sql}")


@pytest.fixture
def report():
    return build_overview(FakeConn(), "c", ["tickets", "baggage"], schema="s", limit=8)


# ── the tour is diverse ───────────────────────────────────────────────────────

def test_tour_has_at_least_five_distinct_lenses(report):
    lenses = {f.lens for f in report.facts}
    assert len(lenses) >= 5, f"tour not diverse enough: {sorted(lenses)}"


def test_no_lens_appears_more_than_twice(report):
    from collections import Counter
    counts = Counter(f.lens for f in report.facts)
    assert max(counts.values()) <= 2, dict(counts)


def test_no_table_dimension_cut_appears_more_than_twice(report):
    from collections import Counter
    cuts = Counter((f.table, f.dimension) for f in report.facts if f.dimension)
    if cuts:
        assert max(cuts.values()) <= 2, dict(cuts)


def test_tour_is_non_trivially_sized(report):
    # limit=8 with six lenses available → a full, multi-fact tour
    assert 5 <= len(report.facts) <= 8


# ── the boolean flag is never a concentration group ───────────────────────────

def test_boolean_dimension_not_used_as_a_group(report):
    assert all(f.dimension != "refundable" for f in report.facts)
    # and no headline names True/False as a group label
    for f in report.facts:
        assert not re.search(r"\b(true|false)\b", f.headline, re.I), f.headline


# ── single-value + untouched-table coverage facts ─────────────────────────────

def test_single_value_currency_yields_coverage_fact(report):
    cov = [f for f in report.facts if f.lens == "coverage" and f.measure == "currency"]
    assert cov, "expected a coverage fact for the single-value currency column"
    f = cov[0]
    assert f.stat == "100%"
    assert "every row" in f.headline.lower()
    assert "CHF" in f.headline               # the resolved single value, from the LIMIT 1 probe


def test_untouched_large_baggage_yields_coverage_fact(report):
    cov = [f for f in report.facts if f.lens == "coverage" and "baggage" in f.headline.lower()]
    assert cov, "expected a coverage fact naming the untouched baggage table"
    assert cov[0].table == "s.baggage"


# ── to_dict() contract + notability bounds ────────────────────────────────────

def test_every_fact_dict_has_full_key_set_and_bounded_notability(report):
    assert report.facts, "fixture should produce facts"
    for f in report.facts:
        d = f.to_dict()
        assert set(d) == FACT_KEYS, set(d).symmetric_difference(FACT_KEYS)
        assert 0.0 <= d["notability"] <= 1.0


def test_report_to_dict_shape(report):
    d = report.to_dict()
    assert set(d) == {"facts", "summary", "tables_seen", "tables_total", "generated_at"}
    assert d["tables_total"] == 2
    assert isinstance(d["facts"], list) and d["facts"]


# ── percentages are fractions rendered as percents (the _fmt('pct') fix) ──────

def test_concentration_percentage_reads_as_percent_not_fraction(report):
    seg = [f for f in report.facts
           if f.lens == "concentration" and f.dimension == "segment_status"]
    assert seg, "expected a concentration fact for the flown-dominated segment_status"
    f = seg[0]
    # 0.953 share must render '95.3%', never '0.95%'
    assert f.stat == "95.3%"
    assert "95.3%" in f.headline
    assert "0.95%" not in f.headline


# ── a signed measure is never the concentration measure ───────────────────────

def test_signed_measure_not_chosen_as_measure(report):
    # net_miles (min −5000) must fall back to the non-negative fare_chf (or count)
    assert all(f.measure != "net_miles" for f in report.facts)
    money_lenses = {"concentration", "composition", "relationship", "outlier"}
    for f in report.facts:
        if f.lens in money_lenses and f.measure is not None:
            assert f.measure == "fare_chf"


# ── robustness: a failing connection never raises, yields no facts ────────────

class _BoomConn:
    def execute(self, label, sql):
        raise RuntimeError("connection is down")


class _ErrConn:
    def execute(self, label, sql):
        return FakeResult([], [], error="permission denied")


def test_build_overview_on_raising_connection_returns_empty_never_raises():
    rep = build_overview(_BoomConn(), "c", ["tickets", "baggage"], schema="s", limit=8)
    assert rep.facts == []
    assert rep.to_dict()["facts"] == []


def test_build_overview_on_error_returning_connection_returns_empty():
    rep = build_overview(_ErrConn(), "c", ["tickets"], schema="s", limit=8)
    assert rep.facts == []


# ── source-diversity caps: no one table / schema monopolises the tour ─────────

def _mk(lens, table, nb, dim=None):
    """A minimal OverviewFact for exercising _select's diversity caps directly."""
    return OverviewFact(lens=lens, headline=f"{lens} on {table}", stat="1",
                        stat_label="x", why="", notability=nb, table=table, dimension=dim)


def test_select_caps_facts_per_table_when_many_tables_available():
    # s.t1 alone could supply four distinct-lens facts; the per-table cap (2) must spread
    # the tour across other tables instead of letting one table take half the cards.
    facts = [
        _mk("concentration", "s.t1", 0.95, "t1_a"), _mk("outlier", "s.t1", 0.94, "t1_b"),
        _mk("distribution", "s.t1", 0.93), _mk("composition", "s.t1", 0.92, "t1_c"),
        _mk("relationship", "s.t2", 0.85, "t2_a"), _mk("coverage", "s.t2", 0.84),
        _mk("concentration", "s.t3", 0.80, "t3_a"), _mk("outlier", "s.t3", 0.79, "t3_b"),
        _mk("distribution", "s.t4", 0.75), _mk("composition", "s.t4", 0.74, "t4_a"),
        _mk("relationship", "s.t5", 0.70, "t5_a"), _mk("coverage", "s.t5", 0.69),
    ]
    from collections import Counter
    per_table = Counter(f.table for f in _select(facts, limit=8))
    assert sum(per_table.values()) == 8                 # the tour still fills
    assert max(per_table.values()) <= 2, dict(per_table)  # …but no table monopolises
    assert len(per_table) >= 4                           # spread across ≥4 tables


def test_select_caps_facts_per_schema_when_pool_spans_two_schemas():
    # schema 'a' could supply all eight cards; the per-schema cap must reserve slots so the
    # minority schema 'b' still appears — the full-connection, multi-schema overview case.
    facts = [
        _mk("concentration", "a.a1", 0.95, "a1_a"), _mk("outlier", "a.a1", 0.94, "a1_b"),
        _mk("distribution", "a.a2", 0.93), _mk("composition", "a.a2", 0.92, "a2_a"),
        _mk("relationship", "a.a3", 0.91, "a3_a"), _mk("coverage", "a.a3", 0.90),
        _mk("concentration", "a.a4", 0.89, "a4_a"), _mk("outlier", "a.a4", 0.88, "a4_b"),
        _mk("distribution", "b.b1", 0.70), _mk("composition", "b.b1", 0.69, "b1_a"),
        _mk("relationship", "b.b2", 0.68, "b2_a"), _mk("coverage", "b.b2", 0.67),
    ]
    from collections import Counter
    per_schema = Counter(f.table.split(".")[0] for f in _select(facts, limit=8))
    assert sum(per_schema.values()) == 8
    assert per_schema["a"] <= 6                          # dominant schema can't take all 8
    assert per_schema["b"] >= 2                          # …minority schema is represented


def test_select_narrow_schema_still_fills_via_relaxed_source_cap():
    # Only two tables, one productive: the per-table cap would cap the tour at 3 — but the
    # fill pass relaxes the SOURCE cap (keeping the semantic lens cap) so it still reaches 8.
    facts = [_mk(lens, "s.hot", 0.9 - i * 0.02, f"d{i}")
             for i, lens in enumerate(
                 ["concentration", "concentration", "outlier", "outlier", "distribution",
                  "distribution", "composition", "composition", "relationship"])]
    facts.append(_mk("coverage", "s.cold", 0.5))
    chosen = _select(facts, limit=8)
    from collections import Counter
    assert len(chosen) == 8                              # fills despite only 2 tables
    assert max(Counter(f.lens for f in chosen).values()) <= 2  # semantic cap still holds
