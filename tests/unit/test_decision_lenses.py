"""R15 — decision-grade output lenses (flag `lens.decision_grade`).

(1) Opportunity-cost/benchmark: gap-to-best-peer × volume as one hedged key
number, computed deterministically from a cross-section finding's own rows.
(2) Named-outlier-entity: the overview tour names the single entity BY ID that
towers over its top-10 peers, with a hedged "potential causes" and drill SQL.

Hermetic: pure-function grids for (1); in-memory DuckDB + duck-typed column
profiles for (2).
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import duckdb

from aughor.agent.opportunity import annotate_opportunity, compute_opportunity
from aughor.db.connection import DuckDBConnection
from aughor.overview.build import _lens_named_outlier


# ── (1) the opportunity computation ──────────────────────────────────────────

_COLS = ["segment", "metric_total", "n"]
_ROWS = [
    ["long_haul", 74_500.0, 1000],     # avg 74.5 — the weak one, plenty of volume
    ["short_haul", 154_400.0, 2000],   # avg 77.2 — the benchmark
    ["regional", 76_000.0, 1000],      # avg 76.0
    ["charter", 990.0, 10],            # avg 99 — immaterial (n below the floor)
]


# The utilization lens's real grid shape: `100.0 * SUM(sold) / SUM(capacity)` — a
# PERCENT-scaled rate whose `n` is the rate's own denominator (the capacity).
_PCT_COLS = ["haul", "metric_total", "n"]
_PCT_ROWS = [
    ["long_haul", 77.7, 66_764],       # the emptiest — 77.7% of 66,764 seats
    ["short_haul", 79.4, 120_000],     # the benchmark
    ["regional", 78.9, 40_000],
]


def test_percent_scaled_rate_is_normalised_before_gap_times_volume():
    """The 100x guard. A percent-scaled grid (77.7) must become a fraction before
    gap x volume, or 1.7 percentage-points x 66,764 seats reads as 113,499 seats."""
    gap = compute_opportunity(_PCT_COLS, _PCT_ROWS, is_ratio=True, is_percent=True,
                              volume_is_denominator=True)
    assert gap is not None
    # (79.4 - 77.7) / 100 * 66,764 = ~1,135 empty seats — the ground-truth number.
    assert abs(gap["opportunity"] - 1_135.0) < 2.0
    assert gap["worst_segment"] == "long_haul" and gap["best_segment"] == "short_haul"


def test_fraction_scaled_rate_is_left_alone():
    """Below the 1.5 threshold the grid is already a fraction — never rescale it."""
    rows = [["long", 0.777, 66_764], ["short", 0.794, 120_000], ["reg", 0.789, 40_000]]
    gap = compute_opportunity(_PCT_COLS, rows, is_ratio=True, is_percent=True,
                              volume_is_denominator=True)
    assert gap is not None and abs(gap["opportunity"] - 1_135.0) < 2.0


def test_real_capacity_gap_survives_the_flat_rate_floor():
    """The regression this wiring exists for: 77.7 vs 79.4 is a 2.1% relative gap —
    UNDER _MIN_RELATIVE_GAP — but it is 1,135 seats measured over 66,764. A flat floor
    silences it; its own sampling error (~8 sigma) does not."""
    assert compute_opportunity(_PCT_COLS, _PCT_ROWS, is_ratio=True,
                               is_percent=True) is None          # flat floor: silent
    assert compute_opportunity(_PCT_COLS, _PCT_ROWS, is_ratio=True, is_percent=True,
                               volume_is_denominator=True) is not None


# A fleet grid shaped like the real one: the laggard is 1,292 seats behind its
# benchmark, which is 0.47% of the seats SOLD but 1.8% of the seats left EMPTY.
_FLEET_COLS = ["aircraft", "metric_total", "n"]
_FLEET_ROWS = [
    ["A350-900", 73.1, 17_000],                                   # the laggard
    ["A320neo", 79.0, 20_000], ["A321", 79.0, 25_000],
    ["B777-300", 79.0, 30_000], ["A220", 79.0, 40_000],
    ["B737", 79.0, 60_000], ["E190", 79.0, 70_000],
    ["A330-300", 80.7, 84_334],                                   # the benchmark
]


def test_opportunity_is_material_against_what_it_would_move():
    """The addressable base. Measured against seats SOLD, 1,292 seats reads as 0.47%
    and dies under the floor; against the empty seats it would actually fill it is
    1.8%. The pie for a capacity gap is the gap, not the business."""
    gap = compute_opportunity(_FLEET_COLS, _FLEET_ROWS, is_ratio=True, is_percent=True,
                              volume_is_denominator=True)
    assert gap is not None
    assert gap["worst_segment"] == "A350-900" and gap["best_segment"] == "A330-300"
    assert abs(gap["opportunity"] - 1_292.0) < 5.0


def test_significant_but_trivial_gap_is_still_silent():
    """Significance is not materiality. 0.1pp over 5M seats is ~40 sigma — the z-test
    waves it through — and it is still only 5,000 seats against 3M empty. The
    addressable floor is what has to stop it, and does."""
    rows = [["a", 79.9, 5_000_000], ["b", 80.0, 5_000_000], ["c", 80.0, 5_000_000]]
    assert compute_opportunity(_FLEET_COLS, rows, is_ratio=True, is_percent=True,
                               volume_is_denominator=True) is None


def test_fine_grained_grid_stays_readable():
    """A share-of-TOTAL floor is scale-dependent: across 40 routes no segment can hold
    3% of the total, so the grid the story lives in goes silent (all 84 real routes
    did). Measured against the typical segment, the rule holds at any grain."""
    rows = [[f"route_{i}", 80.0, 1_000] for i in range(40)]
    rows[0] = ["route_worst", 70.0, 1_000]
    gap = compute_opportunity(_FLEET_COLS, rows, is_ratio=True, is_percent=True,
                              volume_is_denominator=True)
    assert gap is not None and gap["worst_segment"] == "route_worst"


def test_boutique_segment_still_cannot_anchor_the_benchmark():
    """The floor's original job survives the rewrite: a 12-seat charter at 99% is not
    the benchmark long-haul should be measured against."""
    rows = [["long", 77.7, 66_764], ["short", 79.4, 120_000], ["charter", 99.0, 12]]
    gap = compute_opportunity(_FLEET_COLS, rows, is_ratio=True, is_percent=True,
                              volume_is_denominator=True)
    assert gap is not None and gap["best_segment"] == "short"


def test_same_gap_over_tiny_volume_is_noise():
    """The floor still has to bite: the identical 1.7pp gap over ~200 seats is noise."""
    rows = [["long", 77.7, 200], ["short", 79.4, 300], ["reg", 78.9, 250]]
    assert compute_opportunity(_PCT_COLS, rows, is_ratio=True, is_percent=True,
                               volume_is_denominator=True) is None


def test_cost_like_metric_benchmarks_downward_not_upward():
    """A leakage rate's laggard is the HIGHEST segment. Benchmarking it upward would
    name the worst leaker as the target and invert the claim."""
    rows = [["first", 3.56, 20_000], ["economy", 1.20, 90_000], ["corp", 3.41, 30_000]]
    gap = compute_opportunity(_PCT_COLS, rows, is_ratio=True, is_percent=True,
                              lower_is_better=True)
    assert gap is not None
    assert gap["worst_segment"] == "first"      # highest leak = the one to fix
    assert gap["best_segment"] == "economy"     # lowest leak = the benchmark
    # Left at the default the read inverts — economy would become the "worst".
    naive = compute_opportunity(_PCT_COLS, rows, is_ratio=True, is_percent=True)
    assert naive["worst_segment"] == "economy"


def test_direction_and_volume_reach_the_annotated_key_number():
    f = {"columns": _PCT_COLS, "rows": _PCT_ROWS, "key_numbers": [], "stat_note": None}
    assert annotate_opportunity(f, metric_label="utilization", is_ratio=True,
                                is_percent=True, volume_label="seats",
                                volume_is_denominator=True) is True
    kn = f["key_numbers"][-1]
    assert "77.7%" in kn["context"] and "79.4%" in kn["context"]
    assert "seats" in kn["context"] and "below benchmark" in kn["delta"]
    assert "1,135 seats" in kn["context"]        # the unit is the volume's, not "utilization"


def test_truncated_grid_never_benchmarks_against_the_survivors():
    """A finding carries 50 rows. The live utilization lens scanned 84 routes ORDER BY
    ASC, so the true best peer was cut — benchmarking against the 50th-worst would be a
    confident wrong number. row_count > len(rows) ⇒ silence."""
    f = {"columns": _PCT_COLS, "rows": _PCT_ROWS, "row_count": 84,
         "key_numbers": [], "stat_note": None}
    assert annotate_opportunity(f, metric_label="utilization", is_ratio=True,
                                is_percent=True, volume_label="seats",
                                volume_is_denominator=True) is False
    assert f["key_numbers"] == []
    # The same grid, whole, still annotates.
    f2 = dict(f, row_count=len(_PCT_ROWS), key_numbers=[])
    assert annotate_opportunity(f2, metric_label="utilization", is_ratio=True,
                                is_percent=True, volume_label="seats",
                                volume_is_denominator=True) is True


def test_cost_like_annotation_reads_above_benchmark():
    rows = [["first", 3.56, 20_000], ["economy", 1.20, 90_000], ["corp", 3.41, 30_000]]
    f = {"columns": _PCT_COLS, "rows": rows, "key_numbers": [], "stat_note": None}
    assert annotate_opportunity(f, metric_label="leakage rate", is_ratio=True,
                                is_percent=True, lower_is_better=True) is True
    assert "above benchmark" in f["key_numbers"][-1]["delta"]


# The leakage grid: the rate is contra/gross, so its volume is the GROSS — money, not a
# count of anything. Shaped like the real one (cabin, CHF).
_LEAK_COLS = ["cabin", "metric_total", "n"]
_LEAK_ROWS = [
    ["business", 3.22, 38_013_111],        # the laggard
    ["premium_economy", 2.78, 20_000_000],
    ["economy", 2.22, 25_000_000],         # the cleanest material peer
]


def test_money_volume_yields_money_and_reads_compact():
    """gap x gross = the CHF that stops walking out. Both the volume and the opportunity
    read compact — "38.0M CHF" / "381K CHF", never "38,013,111"."""
    f = {"columns": _LEAK_COLS, "rows": _LEAK_ROWS, "row_count": 3,
         "key_numbers": [], "stat_note": None}
    assert annotate_opportunity(f, metric_label="leakage rate", is_ratio=True,
                                is_percent=True, lower_is_better=True, volume_label="CHF",
                                volume_is_denominator=True, volume_is_money=True) is True
    ctx = f["key_numbers"][-1]["context"]
    assert "38.01M CHF" in ctx and "38,013,111" not in ctx
    assert "380.1K CHF" in ctx            # (3.22-2.22)/100 * 38,013,111
    assert "business runs 3.2% vs economy's 2.2%" in ctx


def test_money_volume_never_uses_the_binomial_significance_test():
    """sqrt(p(1-p)/n) counts Bernoulli trials, and 38M CHF is not 38M trials — it would
    claim absurd precision and wave a trivial gap through. Money uses the flat floor: a
    2% relative gap is silent as money, where the same shape passes as counted units."""
    rows = [["a", 3.00, 38_000_000], ["b", 2.94, 25_000_000], ["c", 2.96, 20_000_000]]
    assert compute_opportunity(_LEAK_COLS, rows, is_ratio=True, is_percent=True,
                               lower_is_better=True, volume_is_denominator=True,
                               volume_is_money=True) is None
    # Same numbers as unit COUNTS: the sampling error says this is real signal.
    assert compute_opportunity(_LEAK_COLS, rows, is_ratio=True, is_percent=True,
                               lower_is_better=True,
                               volume_is_denominator=True) is not None


def test_gap_times_volume_against_best_material_peer():
    gap = compute_opportunity(_COLS, _ROWS)
    assert gap is not None
    assert gap["worst_segment"] == "long_haul"
    assert gap["best_segment"] == "short_haul"          # charter's 99 avg is immaterial
    assert gap["opportunity"] == (77.2 - 74.5) * 1000   # gap × the weak segment's volume
    assert 0.03 < gap["relative_gap"] < 0.04


def test_immaterial_segments_never_anchor():
    # charter (n=10) has both the highest avg and too little volume — silence beats
    # a benchmark computed from a boutique segment... unless the gap clears the floor.
    gap = compute_opportunity(_COLS, _ROWS)
    assert gap and gap["best_segment"] != "charter"


def test_silent_on_trivial_gap_small_grids_and_alien_shapes():
    # <3% relative gap between material peers is measurement noise → silence
    flat = [["a", 1000.0, 100], ["b", 1015.0, 100], ["c", 1008.0, 100]]
    assert compute_opportunity(_COLS, flat) is None
    # fewer than 3 segments → silence
    assert compute_opportunity(_COLS, _ROWS[:2]) is None
    # no count column → silence
    assert compute_opportunity(["segment", "metric_total"], [["a", 1], ["b", 2], ["c", 3]]) is None
    assert compute_opportunity([], []) is None


def test_ratio_metric_reads_rate_directly():
    cols = ["haul", "metric_total", "n"]
    rows = [["long", 0.745, 258], ["short", 0.772, 900], ["mid", 0.760, 400]]
    gap = compute_opportunity(cols, rows, is_ratio=True)
    assert gap is not None
    assert gap["worst_rate"] == 0.745 and gap["best_rate"] == 0.772
    # (0.772 − 0.745) × 258 flights ≈ 7 seats-per-flight-equivalents — the Databricks move
    assert abs(gap["opportunity"] - 0.027 * 258) < 1e-9


def _wide_gap_finding():
    return {
        "columns": ["segment", "metric_total", "n"],
        "rows": [["weak", 50_000.0, 1000], ["strong", 100_000.0, 1000],
                 ["mid", 80_000.0, 1000]],
        "key_numbers": [],
        "stat_note": None,
    }


def test_annotate_appends_hedged_key_number():
    f = _wide_gap_finding()
    assert annotate_opportunity(f, metric_label="revenue") is True
    kn = f["key_numbers"][-1]
    assert "weak" in kn["label"] and "strong" in kn["label"]
    assert "ceiling" in kn["context"]                   # the hedge always ships
    assert "ceiling" in f["stat_note"]


def test_annotate_leaves_unreadable_findings_untouched():
    f = {"columns": ["a"], "rows": [[1]], "key_numbers": [], "stat_note": None}
    assert annotate_opportunity(f) is False
    assert f["key_numbers"] == [] and f["stat_note"] is None


def test_percent_formatting_in_context():
    f = {
        "columns": ["haul", "metric_total", "n"],
        "rows": [["long", 0.745, 258], ["short", 0.772, 900], ["mid", 0.760, 400]],
        "key_numbers": [], "stat_note": None,
    }
    assert annotate_opportunity(f, metric_label="load factor",
                                is_ratio=True, is_percent=True)
    assert "74.5%" in f["stat_note"] and "77.2%" in f["stat_note"]


# ── (2) the named-outlier-entity lens ────────────────────────────────────────

def _duck(setup: list[str]):
    c = DuckDBConnection.__new__(DuckDBConnection)
    c._path = Path(":memory:")
    c._conn = duckdb.connect(":memory:")
    c._connection_id = "test"
    c._schema_name = None
    for s in setup:
        c._conn.execute(s)
    return c


def _col(name, *, st="dimension", dc=0, dtype="VARCHAR", vr=None):
    return SimpleNamespace(table="tickets", column=name, semantic_type=st,
                           distinct_count=dc, dtype=dtype, value_range=vr,
                           is_fk=(st == "key"), value_interpretation="", unit="",
                           mean=None, p50=None)


def test_named_outlier_surfaces_the_whale_by_id():
    c = _duck(["CREATE TABLE tickets (customer_id VARCHAR, amount DOUBLE)"])
    # 99 normal customers × 10 tickets of 100 each; one whale with 400 tickets
    c._conn.execute(
        "INSERT INTO tickets "
        "SELECT 'CU' || LPAD(CAST(i % 99 AS VARCHAR), 4, '0'), 100.0 "
        "FROM range(990) t(i)"
    )
    c._conn.execute(
        "INSERT INTO tickets SELECT 'CU_WHALE', 100.0 FROM range(400)"
    )
    cols = [
        _col("customer_id", st="key", dc=100),
        _col("amount", st="measure", dtype="DOUBLE", vr=(100.0, 100.0)),
    ]
    tp = SimpleNamespace(table="tickets", row_count=1390)
    facts = _lens_named_outlier(c, "tickets", cols, tp)
    assert facts, "the whale must surface"
    f = facts[0]
    assert f.lens == "outlier"                          # reuses the existing card styling
    assert "CU_WHALE" in f.headline                     # named BY ID
    assert "Potential causes" in f.why                  # the hedge, verbatim habit
    assert "drill" in f.why
    assert f.sql and f.rows                             # drill provenance attached


def test_named_outlier_silent_without_dominance():
    c = _duck(["CREATE TABLE tickets (customer_id VARCHAR, amount DOUBLE)"])
    c._conn.execute(
        "INSERT INTO tickets "
        "SELECT 'CU' || LPAD(CAST(i % 99 AS VARCHAR), 4, '0'), 100.0 "
        "FROM range(990) t(i)"
    )                                                    # everyone ~equal
    cols = [
        _col("customer_id", st="key", dc=99),
        _col("amount", st="measure", dtype="DOUBLE", vr=(100.0, 100.0)),
    ]
    tp = SimpleNamespace(table="tickets", row_count=990)
    assert _lens_named_outlier(c, "tickets", cols, tp) == []


def test_named_outlier_skips_row_unique_ids_and_small_tables():
    c = _duck(["CREATE TABLE tickets (ticket_id VARCHAR, amount DOUBLE)"])
    c._conn.execute(
        "INSERT INTO tickets SELECT 'T' || CAST(i AS VARCHAR), 100.0 FROM range(500) t(i)"
    )
    # ticket_id is row-unique (dc == row_count) → no entity column → no fact
    cols = [
        _col("ticket_id", st="key", dc=500),
        _col("amount", st="measure", dtype="DOUBLE", vr=(100.0, 100.0)),
    ]
    assert _lens_named_outlier(c, "tickets", cols,
                               SimpleNamespace(table="tickets", row_count=500)) == []
    # tiny tables never probe
    assert _lens_named_outlier(c, "tickets", cols,
                               SimpleNamespace(table="tickets", row_count=50)) == []


# ── the alias-humanizer must not relabel a lens's own measure ─────────────────

def test_lens_findings_keep_their_own_measure_label():
    """The soak shipped a load-factor chart whose axis read "refund leakage rate": the
    terminal alias pass stamps the INTAKE's metric onto every phase, and a forward-chained
    lens measures something else. Each lens records its own label; only phases that ran the
    primary metric may take the primary label."""
    from aughor.agent.investigate import _lens_phase_from_run
    from types import SimpleNamespace
    run = SimpleNamespace(
        ok=True,
        results=[(SimpleNamespace(title="q", chart_type="bar_horizontal"),
                  SimpleNamespace(sql="SELECT 1", columns=["segment", "metric_total", "n"],
                                  rows=[["long", 77.7, 65_639], ["short", 79.4, 280_695]],
                                  row_count=2, error=None))],
        interpretation=None, error_phase=None)
    ph = _lens_phase_from_run(run, "loss_utilization", "Capacity Utilization", "🪑",
                              "utilization", "utilization", "computed.")
    assert ph["metric_label"] == "utilization"      # not the run's primary metric
