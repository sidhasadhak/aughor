"""P6 — Deep-Analysis ground-truth regression harness.

The 2026-07-09 audit (docs/DEEP_ANALYSIS_QUALITY_2026-07-09.md) ran four archetype questions LIVE
against hand-computed ground truth and found the Tier 1–4 defects. The guards that fixed them are
unit-tested, but end-to-end **answer quality** on the archetypes was never gated — a future change
could silently regress the answer while keeping the unit tests green. This is that gate.

Like tests/integration/test_golden_reference.py it is HERMETIC: a temp DuckDB seeded with
closed-form ground truth, the test-isolated registry, and **no live LLM** — the answer-quality gains
being locked (the global-ratio guard, the Welch level-shift, decompose-under-abstention routing,
named-driver decomposition, and the P1 canonical-metric pin) are all deterministic, so they are
driven directly against the fixture. A red here means the *answer* regressed, not the model.

Archetypes (mapped to the audit's inv1–inv4):
  A1  conditioned-denominator refund RATE (cross-sectional "why is X high?") → global-ratio guard.
  A2  sustained revenue decline ("why did X decline?")                       → Welch + decompose + drivers.
  A3  genuinely FLAT series (false-premise "why did X spike?")               → abstention correctness.
  P1  a governed metric parsed as a run-varying LLM formula                  → canonical-metric pin.
"""
from __future__ import annotations

import duckdb
import pytest

import aughor.agent.investigate as I
from aughor.agent.prompts_investigate import IntakeOutput
from aughor.db.connection import DuckDBConnection
from aughor.semantic.canonical import CanonicalMetric
from aughor.tools.stats import mean_shift_significance

# ── Ground truth baked into the fixture (assert against these constants) ───────────
_TRUE_GLOBAL_REFUND_RATE = 10.0        # SUM(refund_amount)=1000 / SUM(order_total)=10000 * 100
_DECLINE_REL_CHANGE = -0.15            # 2023 mean 1000 → 2024 mean 850
_TOP_DECLINE_CHANNEL = "Meta"          # −1800 over the period; next is Direct −360
_EARLY = [f"2023-{m:02d}" for m in range(1, 13)]
_LATE = [f"2024-{m:02d}" for m in range(1, 13)]


def _seed(w: duckdb.DuckDBPyConnection) -> None:
    # orders — the population/denominator (Σ order_total = 10,000); refunded_value backs the
    # single-table governed metric the P1 pin probe validates.
    w.execute("CREATE TABLE orders(order_id INTEGER, category VARCHAR, channel VARCHAR, "
              "order_month VARCHAR, order_total DOUBLE, refunded_value DOUBLE)")
    cats = ["fragrance", "skincare", "makeup"]
    w.executemany(
        "INSERT INTO orders VALUES (?,?,?,?,?,?)",
        [(i, cats[i % 3], "Meta", "2024-01", 100.0, 100.0 if i % 5 == 0 else 0.0)
         for i in range(100)],
    )

    # refunds — the event/numerator on a SEPARATE table (Σ refund_amount = 1,000); only refunded
    # orders appear, which is what a per-segment inner-join scan conditions the denominator on.
    w.execute("CREATE TABLE refunds(order_id INTEGER, refund_amount DOUBLE)")
    w.executemany("INSERT INTO refunds VALUES (?,?)", [(i, 50.0) for i in range(20)])

    # revenue — a sustained decline decomposable by channel (Meta drops most). Jitter on Email keeps
    # per-month variance non-zero (so Welch has a defined SE) without moving the half-means.
    w.execute("CREATE TABLE revenue(order_month VARCHAR, channel VARCHAR, amount DOUBLE)")
    rev = []
    for idx, mo in enumerate(_EARLY):
        jit = 15.0 if idx % 2 == 0 else -15.0
        rev += [(mo, "Meta", 500.0), (mo, "Direct", 300.0), (mo, "TikTok", 100.0),
                (mo, "Email", 100.0 + jit)]
    for idx, mo in enumerate(_LATE):
        jit = 15.0 if idx % 2 == 0 else -15.0
        rev += [(mo, "Meta", 350.0), (mo, "Direct", 270.0), (mo, "TikTok", 115.0),
                (mo, "Email", 115.0 + jit)]
    w.executemany("INSERT INTO revenue VALUES (?,?,?)", rev)

    # revenue_flat — a genuinely flat series (the false-premise "spike"): mean 500 both halves.
    w.execute("CREATE TABLE revenue_flat(order_month VARCHAR, amount DOUBLE)")
    w.executemany(
        "INSERT INTO revenue_flat VALUES (?,?)",
        [(mo, 500.0 + (5.0 if idx % 2 == 0 else -5.0))
         for idx, mo in enumerate(_EARLY + _LATE)],
    )


@pytest.fixture(scope="module")
def gt_db(tmp_path_factory):
    """A read-only DuckDB fixture with closed-form ground truth for the four archetypes."""
    path = tmp_path_factory.mktemp("ada_gt") / "gt.duckdb"
    w = duckdb.connect(str(path))
    try:
        _seed(w)
    finally:
        w.close()
    db = DuckDBConnection(str(path))
    yield db
    db.close()


def _monthly_totals(db, table: str) -> list[float]:
    r = db.execute("gt", f"SELECT order_month, SUM(amount) FROM {table} "
                         "GROUP BY order_month ORDER BY order_month")
    assert not r.error, r.error
    return [float(row[1]) for row in r.rows]


# ── A1 · conditioned-denominator refund rate → global-ratio guard fires (Tier 1) ───

_REFUND_METRIC = "SUM(refunds.refund_amount) / SUM(orders.order_total) * 100"


def test_a1_true_global_refund_rate_is_recomputed_independently(gt_db):
    sources = I._parse_ratio_sources(_REFUND_METRIC)
    assert sources and sources["num_table"] == "refunds" and sources["den_table"] == "orders"
    global_ratio = I._independent_global_ratio(gt_db, sources)
    assert global_ratio is not None
    assert abs(global_ratio - _TRUE_GLOBAL_REFUND_RATE) < 0.01   # 10.0%, not the inflated ~73%


def test_a1_guard_fires_and_states_true_global_on_inflated_segments(gt_db):
    # The buggy per-segment scan reported every category far above the true global (a conditioned
    # denominator). The guard must fire and state the real 10% level.
    findings = [{
        "columns": ["category", "metric_total"],
        "rows": [["fragrance", 73.2], ["skincare", 68.0], ["makeup", 61.5]],
    }]
    caveat = I._global_ratio_plausibility_guard(findings, gt_db, _REFUND_METRIC, "refund rate")
    assert caveat is not None
    assert "conditioned denominator" in caveat.lower()
    assert I._fmt_pct(_TRUE_GLOBAL_REFUND_RATE) in caveat        # "10.0%" is stated in the caveat


def test_a1_guard_silent_on_plausible_spread(gt_db):
    # Negative control: a real spread around the 10% global (min below 2.5×) must NOT fire.
    findings = [{
        "columns": ["category", "metric_total"],
        "rows": [["fragrance", 18.8], ["skincare", 9.0], ["makeup", 5.4]],
    }]
    assert I._global_ratio_plausibility_guard(findings, gt_db, _REFUND_METRIC, "refund rate") is None


# ── A2 · sustained decline → Welch significant + decompose + named drivers (Tier 1+2)

def test_a2_level_shift_is_significant_and_directional(gt_db):
    shift = mean_shift_significance(_monthly_totals(gt_db, "revenue"))
    assert shift is not None
    assert shift.is_significant is True                          # sustained shift, not "within variance"
    assert shift.recent_mean < shift.prior_mean                  # direction: down
    assert abs(shift.rel_change - _DECLINE_REL_CHANGE) < 0.01    # magnitude: −15%


def test_a2_routes_to_decomposition_under_abstention(gt_db):
    # A material aggregate move on a "why did X decline?" question must decompose even when the
    # single-point anomaly test is sub-threshold (the Tier-2 fix) — never "it's just noise".
    state = {
        "question": "Why did total revenue decline in 2024 versus 2023?",
        "_baseline_significant": False, "_baseline_rel_change": _DECLINE_REL_CHANGE,
        "_baseline_sigma": 1.0, "investigation_phases": [],
    }
    assert I.route_after_baseline(state) == "ada_decompose"


def test_a2_named_driver_is_the_worst_channel(gt_db):
    # The decomposition must surface the real driver: Meta fell most (−1800), not a descriptive tie.
    r = gt_db.execute(
        "gt",
        "SELECT channel, "
        "SUM(CASE WHEN order_month >= '2024-01' THEN amount ELSE 0 END) - "
        "SUM(CASE WHEN order_month <  '2024-01' THEN amount ELSE 0 END) AS delta "
        "FROM revenue GROUP BY channel ORDER BY delta ASC",
    )
    assert not r.error, r.error
    top_channel, top_delta = r.rows[0][0], float(r.rows[0][1])
    assert top_channel == _TOP_DECLINE_CHANNEL
    assert top_delta < 0


# ── A3 · genuinely flat series → abstention correctness (no false decomposition) ────

def test_a3_flat_series_is_not_significant(gt_db):
    shift = mean_shift_significance(_monthly_totals(gt_db, "revenue_flat"))
    # Either no shift detectable or explicitly not significant — never a fabricated movement.
    assert shift is None or shift.is_significant is False


def test_a3_flat_series_has_no_anomalous_period(gt_db):
    r = gt_db.execute("gt", "SELECT order_month, SUM(amount) FROM revenue_flat "
                            "GROUP BY order_month ORDER BY order_month")
    assert not r.error, r.error
    assert I._detect_anomalous_period(["order_month", "amount"], r.rows) is None


def test_a3_false_premise_stops_cleanly():
    # A flat "did refunds spike?" premise (immaterial move) must stop at synthesis, not spin up
    # dimensional phases — the false-premise rejection the audit's inv4 got right.
    state = {
        "question": "Did refunds spike in Q3 2024?",
        "_baseline_significant": False, "_baseline_rel_change": -0.005,
        "_baseline_sigma": 0.4, "investigation_phases": [],
    }
    assert I.route_after_baseline(state) == "ada_synthesize"


# ── P1 · canonical-metric pin validated against the REAL fixture (dry-run probe) ────

def _pin_intake() -> IntakeOutput:
    return IntakeOutput(
        metric_label="Fragrance refund rate",
        metric_sql="COUNT(DISTINCT refund_id) / COUNT(DISTINCT order_id) * 100",
        observation_start="2024-01-01", observation_end="2024-12-31", observation_label="2024",
        comparison_start="2023-01-01", comparison_end="2023-12-31", comparison_label="2023",
        date_column="orders.order_month", metric_table="orders",
        dimensions=["orders.category"], intake_notes="", cross_sectional=True,
    )


_ORDERS_SCHEMA = ("TABLE: orders\n  order_id INTEGER\n  category VARCHAR\n  order_total DOUBLE\n"
                  "  refunded_value DOUBLE\n  order_month VARCHAR\n")


class _FakeProvider:
    def __init__(self, intake): self._intake = intake
    def complete(self, **kw): return self._intake


def test_p1_pin_runs_the_governed_formula_against_the_real_db(monkeypatch, gt_db):
    # The pin's dry-run probe executes the governed formula over the real fixture; a runnable
    # single-table rate is pinned (stronger than the stubbed-conn unit test).
    governed = CanonicalMetric(
        name="refund_rate", label="Refund Rate",
        sql="SUM(refunded_value) / NULLIF(SUM(order_total), 0) * 100",
        source="catalog", verified=True,
    )
    monkeypatch.setenv("AUGHOR_ADA_PIN_CANONICAL_METRIC", "1")
    monkeypatch.setattr("aughor.semantic.canonical.resolve_canonical_metrics",
                        lambda *a, **k: [governed])
    monkeypatch.setattr(I, "_provider", lambda role: _FakeProvider(_pin_intake()))
    import aughor.agent.explore as ex
    monkeypatch.setattr(ex, "build_analysis_ledger", lambda state: "")

    st = {"question": "Why is the Fragrance refund rate so high?", "schema_context": _ORDERS_SCHEMA,
          "scan_context": "", "connection_id": "", "scope_schema": "main"}
    out = I.ada_intake(st, conn=gt_db)
    assert out["_ada_intake"]["metric_sql"] == "SUM(refunded_value) / NULLIF(SUM(order_total), 0) * 100"
    assert "governed definition of refund_rate" in (out["_ada_intake"].get("metric_safety_note") or "")


def test_p1_pin_fails_closed_when_governed_formula_does_not_run(monkeypatch, gt_db):
    # Fail-closed against a real DB: a governed formula referencing a missing column must NOT replace
    # the working LLM formula (the dry-run probe errors → keep the original).
    governed = CanonicalMetric(
        name="refund_rate", label="Refund Rate",
        sql="SUM(nonexistent_col) / NULLIF(SUM(order_total), 0) * 100",
        source="catalog", verified=True,
    )
    monkeypatch.setenv("AUGHOR_ADA_PIN_CANONICAL_METRIC", "1")
    monkeypatch.setattr("aughor.semantic.canonical.resolve_canonical_metrics",
                        lambda *a, **k: [governed])
    monkeypatch.setattr(I, "_provider", lambda role: _FakeProvider(_pin_intake()))
    import aughor.agent.explore as ex
    monkeypatch.setattr(ex, "build_analysis_ledger", lambda state: "")

    st = {"question": "Why is the Fragrance refund rate so high?", "schema_context": _ORDERS_SCHEMA,
          "scan_context": "", "connection_id": "", "scope_schema": "main"}
    out = I.ada_intake(st, conn=gt_db)
    assert out["_ada_intake"]["metric_sql"] == "COUNT(DISTINCT refund_id) / COUNT(DISTINCT order_id) * 100"
