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
