"""P1 — canonical-metric pinning at ADA intake.

A live audit run parsed "why is the Fragrance refund rate so high?" into a count-based rate
(``COUNT(DISTINCT refund_id) / COUNT(DISTINCT order_id) * 100``) the cross-section scan could not
decompose → the report degraded to "the cause remains unidentified", and the count-vs-value reading
varied run-to-run. When the connection GOVERNS the same metric, the intake now pins the governed
formula so the breakdown computes on a stable, decomposable definition. These tests pin:

  • the substitutability gate (only a bare aggregate expression can be inlined into the scan templates),
  • the distinctive-token matcher + its tie-breaks,
  • the orchestrator: flag gate, dry-run guard (fail-closed), no-op when already governed, and the
    in-place mutation of metric_sql / metric_is_ratio.
"""
from __future__ import annotations

import types

import aughor.agent.investigate as I
from aughor.agent.prompts_investigate import IntakeOutput
from aughor.semantic.canonical import CanonicalMetric


# ── Fixtures ────────────────────────────────────────────────────────────────────

def _intake(**over) -> IntakeOutput:
    base = dict(
        metric_label="Fragrance refund rate",
        metric_sql="COUNT(DISTINCT refund_id) / COUNT(DISTINCT order_id) * 100",
        observation_start="2024-01-01", observation_end="2024-12-31", observation_label="2024",
        comparison_start="2023-01-01", comparison_end="2023-12-31", comparison_label="2023",
        date_column="orders.order_ts", metric_table="shop.orders",
        dimensions=["shop.orders.category"], intake_notes="", cross_sectional=True,
    )
    base.update(over)
    return IntakeOutput(**base)


class _StubConn:
    """Minimal connection whose ``execute`` reports success/failure for the pin dry-run probe."""

    def __init__(self, ok: bool = True):
        self._ok = ok
        self.probed: list[str] = []

    def execute(self, tag, sql):
        self.probed.append(sql)
        return types.SimpleNamespace(error=None if self._ok else "column not found", rows=[[1]])


def _governed_refund_rate() -> CanonicalMetric:
    # A value-weighted rate — a bare aggregate the ratio-aware scan can parse + decompose.
    return CanonicalMetric(
        name="refund_rate", label="Refund Rate",
        sql="SUM(refund_amount) / NULLIF(SUM(order_total), 0) * 100",
        unit="%", source="catalog", verified=True,
    )


def _pin_on(monkeypatch, metrics):
    monkeypatch.setenv("AUGHOR_ADA_PIN_CANONICAL_METRIC", "1")
    monkeypatch.setattr(
        "aughor.semantic.canonical.resolve_canonical_metrics",
        lambda *a, **k: list(metrics),
    )


# ── Substitutability gate ─────────────────────────────────────────────────────────

def test_bare_aggregate_is_substitutable():
    assert I._is_substitutable_metric_sql("SUM(a)")
    assert I._is_substitutable_metric_sql("SUM(a) / NULLIF(SUM(b), 0) * 100")
    assert I._is_substitutable_metric_sql("COUNT(DISTINCT id)")


def test_full_query_is_not_substitutable():
    # A north-star value_sql is a full query — inlining it into CASE WHEN … THEN {sql} would break.
    assert not I._is_substitutable_metric_sql("SELECT SUM(x) FROM orders WHERE status='paid'")
    assert not I._is_substitutable_metric_sql("SUM(a) FROM orders")
    assert not I._is_substitutable_metric_sql("SUM(a);")
    assert not I._is_substitutable_metric_sql("")


# ── Distinctive-token matcher ─────────────────────────────────────────────────────

def test_matches_governed_metric_on_distinctive_tokens():
    m = I._match_canonical_metric(
        "Fragrance refund rate",
        "COUNT(DISTINCT refund_id) / COUNT(DISTINCT order_id) * 100",
        [_governed_refund_rate()],
    )
    assert m is not None and m.name == "refund_rate"


def test_no_match_when_label_lacks_the_metric_tokens():
    # "average order value" shares no distinctive token with a governed 'refund_rate'.
    assert I._match_canonical_metric("average order value", "AVG(order_total)",
                                     [_governed_refund_rate()]) is None


def test_generic_only_governed_name_never_matches():
    # 'total revenue' collapses to {} distinctive tokens → must not match everything.
    generic = CanonicalMetric(name="total_revenue", label="Total Revenue",
                              sql="SUM(revenue)", source="catalog")
    assert I._match_canonical_metric("net revenue", "SUM(revenue)", [generic]) is None


def test_ratio_alignment_breaks_ties():
    # Both share the {refund} token; the intake metric is a RATE, so the ratio metric must win.
    rate = _governed_refund_rate()
    amount = CanonicalMetric(name="refund_amount", label="Refund Amount",
                             sql="SUM(refund_amount)", source="catalog")
    m = I._match_canonical_metric("Fragrance refund rate",
                                  "COUNT(DISTINCT refund_id) / COUNT(DISTINCT order_id) * 100",
                                  [amount, rate])
    assert m.name == "refund_rate"


def test_non_substitutable_candidate_skipped():
    northstar = CanonicalMetric(
        name="refund_rate", label="Refund Rate",
        sql="SELECT SUM(refund_amount) / SUM(order_total) FROM refunds",  # full query
        source="profile_governed",
    )
    assert I._match_canonical_metric("refund rate", "AVG(is_refund)", [northstar]) is None


# ── Orchestrator: _pin_canonical_metric ───────────────────────────────────────────

def test_pin_replaces_llm_formula_when_governed_and_runs(monkeypatch):
    _pin_on(monkeypatch, [_governed_refund_rate()])
    intake = _intake()
    conn = _StubConn(ok=True)
    note = I._pin_canonical_metric(intake, "conn1", "TABLE: shop.orders", conn)
    assert note and "refund_rate" in note
    assert intake.metric_sql == "SUM(refund_amount) / NULLIF(SUM(order_total), 0) * 100"
    assert intake.metric_is_ratio is True          # governed formula is a *100 ratio
    assert conn.probed, "the pin must dry-run the governed formula before applying it"


def test_pin_fails_closed_when_probe_errors(monkeypatch):
    _pin_on(monkeypatch, [_governed_refund_rate()])
    intake = _intake()
    original = intake.metric_sql
    note = I._pin_canonical_metric(intake, "conn1", "TABLE: shop.orders", _StubConn(ok=False))
    assert note is None
    assert intake.metric_sql == original           # unchanged — never make a run worse


def test_pin_noop_when_flag_off(monkeypatch):
    monkeypatch.delenv("AUGHOR_ADA_PIN_CANONICAL_METRIC", raising=False)
    monkeypatch.setattr("aughor.semantic.canonical.resolve_canonical_metrics",
                        lambda *a, **k: [_governed_refund_rate()])
    intake = _intake()
    original = intake.metric_sql
    assert I._pin_canonical_metric(intake, "conn1", "schema", _StubConn(ok=True)) is None
    assert intake.metric_sql == original


def test_pin_noop_when_already_governed(monkeypatch):
    # LLM already emitted the governed formula (modulo whitespace) → nothing to pin, no note.
    _pin_on(monkeypatch, [_governed_refund_rate()])
    intake = _intake(metric_sql="SUM(refund_amount)/NULLIF(SUM(order_total),0)*100")
    assert I._pin_canonical_metric(intake, "conn1", "schema", _StubConn(ok=True)) is None


def test_pin_noop_when_no_governed_metric_matches(monkeypatch):
    _pin_on(monkeypatch, [])
    intake = _intake()
    original = intake.metric_sql
    assert I._pin_canonical_metric(intake, "conn1", "schema", _StubConn(ok=True)) is None
    assert intake.metric_sql == original


# ── Wiring: the pin fires inside ada_intake on the real node path ──────────────────

_SCHEMA = (
    "TABLE: shop.orders\n  order_id BIGINT\n  order_total DOUBLE\n  refund_amount DOUBLE\n"
    "  refund_id BIGINT\n  category VARCHAR\n  order_ts TIMESTAMP\n"
)


class _FakeProvider:
    def __init__(self, intake): self._intake = intake
    def complete(self, **kw): return self._intake


def test_ada_intake_pins_governed_metric_end_to_end(monkeypatch):
    # Drive the real node: the coder returns the count-based rate; with a governed refund_rate and
    # the flag on, the emitted spec must carry the pinned formula + a transparency note.
    _pin_on(monkeypatch, [_governed_refund_rate()])
    monkeypatch.setattr(I, "_provider", lambda role: _FakeProvider(_intake()))
    import aughor.agent.explore as ex
    monkeypatch.setattr(ex, "build_analysis_ledger", lambda state: "")

    st = {"question": "Why is the Fragrance refund rate so high?", "schema_context": _SCHEMA,
          "scan_context": "", "connection_id": "", "scope_schema": "shop"}
    out = I.ada_intake(st, conn=_StubConn(ok=True))
    spec = out["_ada_intake"]

    assert spec["metric_sql"] == "SUM(refund_amount) / NULLIF(SUM(order_total), 0) * 100"
    assert spec["metric_is_ratio"] is True
    assert "governed definition of refund_rate" in (spec.get("metric_safety_note") or "")


def test_ada_intake_leaves_metric_untouched_when_flag_off(monkeypatch):
    # Byte-identical default: no governed pin without the flag.
    monkeypatch.delenv("AUGHOR_ADA_PIN_CANONICAL_METRIC", raising=False)
    monkeypatch.setattr(I, "_provider", lambda role: _FakeProvider(_intake()))
    import aughor.agent.explore as ex
    monkeypatch.setattr(ex, "build_analysis_ledger", lambda state: "")

    st = {"question": "Why is the Fragrance refund rate so high?", "schema_context": _SCHEMA,
          "scan_context": "", "connection_id": "", "scope_schema": "shop"}
    out = I.ada_intake(st, conn=_StubConn(ok=True))
    assert out["_ada_intake"]["metric_sql"] == \
        "COUNT(DISTINCT refund_id) / COUNT(DISTINCT order_id) * 100"
