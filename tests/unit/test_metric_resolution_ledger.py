"""P4 — metric-definition RESOLUTION crystallized to the Ambiguity Ledger.

When P1 pins a metric to its GOVERNED definition over a materially-different parsed reading, the
resolution is recorded in the Ambiguity Ledger (source=probe) so the definition burns down per
connection and is read back as a plan-time prior on every path (chat + future ADA) — the "resolution
that compounds" half of the deeper SOMA loop. These tests pin the write, the no-op, and fail-safety.
The ledger DB is test-isolated (AUGHOR_AMBIGUITY_LEDGER_DB in conftest), so writes don't leak.
"""
from __future__ import annotations

import types

import aughor.agent.investigate as I
from aughor.agent.prompts_investigate import IntakeOutput
from aughor.semantic import ambiguity_ledger as L
from aughor.semantic.canonical import CanonicalMetric


def _intake(**over) -> IntakeOutput:
    base = dict(
        metric_label="Fragrance refund rate",
        metric_sql="COUNT(DISTINCT refund_id) / COUNT(DISTINCT order_id) * 100",
        observation_start="2024-01-01", observation_end="2024-12-31", observation_label="2024",
        comparison_start="2023-01-01", comparison_end="2023-12-31", comparison_label="2023",
        date_column="orders.order_month", metric_table="orders",
        dimensions=["orders.category"], intake_notes="", cross_sectional=True,
    )
    base.update(over)
    return IntakeOutput(**base)


class _StubConn:
    def __init__(self, ok=True): self._ok = ok
    def execute(self, tag, sql):
        return types.SimpleNamespace(error=None if self._ok else "boom", rows=[[1]])


def _governed():
    return CanonicalMetric(name="refund_rate", label="Refund Rate",
                           sql="SUM(refunded_value) / NULLIF(SUM(order_total), 0) * 100",
                           source="catalog", verified=True)


def _pin_on(monkeypatch, metrics):
    monkeypatch.setenv("AUGHOR_ADA_PIN_CANONICAL_METRIC", "1")
    monkeypatch.setattr("aughor.semantic.canonical.resolve_canonical_metrics",
                        lambda *a, **k: list(metrics))


def test_pin_crystallizes_resolution_to_ledger(monkeypatch):
    _pin_on(monkeypatch, [_governed()])
    conn_id = "p4_ledger_write"
    note = I._pin_canonical_metric(_intake(), conn_id, "schema", _StubConn(ok=True))
    assert note   # pin happened

    res = L.list_resolutions(conn_id)
    assert len(res) == 1
    r = res[0]
    assert r.resolution_source == "probe"
    assert r.dim_kind == "AmbiIntent" and r.dim_facet == "aggregation"
    assert "refund rate" in r.subject.lower()
    assert r.resolved_sql == "SUM(refunded_value) / NULLIF(SUM(order_total), 0) * 100"
    assert len(r.readings) == 2 and any("parsed" in rd.label for rd in r.readings)


def test_no_pin_means_no_ledger_write(monkeypatch):
    _pin_on(monkeypatch, [])   # no governed metric matches
    conn_id = "p4_no_write"
    assert I._pin_canonical_metric(_intake(), conn_id, "schema", _StubConn(ok=True)) is None
    assert L.list_resolutions(conn_id) == []


def test_failed_probe_does_not_write(monkeypatch):
    # The pin fails closed on a probe error → no metric change AND no ledger entry.
    _pin_on(monkeypatch, [_governed()])
    conn_id = "p4_probe_fail"
    assert I._pin_canonical_metric(_intake(), conn_id, "schema", _StubConn(ok=False)) is None
    assert L.list_resolutions(conn_id) == []


def test_crystallize_is_fail_safe(monkeypatch):
    # A ledger write error must never break the pin — the metric is still pinned.
    _pin_on(monkeypatch, [_governed()])
    monkeypatch.setattr("aughor.semantic.ambiguity_ledger.save_resolution",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("ledger down")))
    intake = _intake()
    note = I._pin_canonical_metric(intake, "p4_failsafe", "schema", _StubConn(ok=True))
    assert note and intake.metric_sql == "SUM(refunded_value) / NULLIF(SUM(order_total), 0) * 100"


def test_probe_resolution_does_not_clobber_a_user_choice(monkeypatch):
    # Override-wins: a prior user resolution outranks the probe write (same subject/connection/org).
    from aughor.org.context import current_org_id
    org = current_org_id() or ""
    conn_id = "p4_override"
    L.save_resolution(L.AmbiguityResolution(
        connection_id=conn_id, org_id=org, schema_scope="orders",
        dim_kind="AmbiIntent", dim_facet="aggregation",
        subject="definition of Fragrance refund rate",
        resolved_reading="user's value-weighted", resolved_sql="SUM(a)/SUM(b)",
        resolution_source="user"))
    _pin_on(monkeypatch, [_governed()])
    I._pin_canonical_metric(_intake(), conn_id, "schema", _StubConn(ok=True))

    res = [r for r in L.list_resolutions(conn_id, org_id=org) if r.subject_fingerprint
           == L._fingerprint("definition of Fragrance refund rate")]
    assert len(res) == 1                             # merged onto the same natural key, not a 2nd row
    assert res[0].resolution_source == "user"        # probe did not downgrade the human choice
    assert res[0].resolved_sql == "SUM(a)/SUM(b)"
