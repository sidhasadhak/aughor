"""Follow-up B — the temporal-feasibility fix wired into ada_intake itself.

Previously only the parallel multi-lens WHEN lens recovered a join-reachable population date, so
the DEFAULT (single-scan) path stayed temporally blind: when the metric sits on an event/child
table with no date of its own, the intake declared `date_column=NONE`, which (a) mislabelled the
displayed spec and (b) forced a temporal-CHANGE question onto the cross-sectional fallback (the
period-over-period override is gated on `not no_time`). These tests pin the recovery + its routing
consequences on the default path, plus the guard that nothing changes when no axis is reachable.
"""
from __future__ import annotations

import pytest

import aughor.agent.investigate as I
from aughor.agent.prompts_investigate import IntakeOutput


# ── Fixtures / fakes ────────────────────────────────────────────────────────────

_SCHEMA = (
    "TABLE: shop.order_items\n  order_id BIGINT\n  product_id BIGINT\n  is_returned BOOLEAN\n"
    "TABLE: shop.returns\n  return_id BIGINT\n  order_id BIGINT\n  return_date DATE\n  reason VARCHAR\n"
    "TABLE: shop.orders\n  order_id BIGINT\n  order_date DATE\n  channel VARCHAR\n"
)


def _intake(**over) -> IntakeOutput:
    base = dict(
        metric_label="return rate", metric_sql="AVG(is_returned)*100",
        observation_start="2025-01-01", observation_end="2025-12-31", observation_label="2025",
        comparison_start="2024-01-01", comparison_end="2024-12-31", comparison_label="2024",
        date_column="NONE", metric_table="shop.order_items",
        dimensions=["shop.order_items.product_id"], intake_notes="",
        cross_sectional=True,
    )
    base.update(over)
    return IntakeOutput(**base)


class _FakeProvider:
    def __init__(self, intake): self._intake = intake
    def complete(self, **kw):
        # ada_intake only ever asks the coder for an IntakeOutput here.
        return self._intake


def _prep(monkeypatch, intake, axis):
    """Wire ada_intake to a controlled intake spec + a controlled temporal-axis result, and
    neutralise the (best-effort, networked) analysis-ledger call so the test is hermetic."""
    monkeypatch.setattr(I, "_provider", lambda role: _FakeProvider(intake))
    calls = {}

    def fake_axis(state, conn=None, intake_data=None):
        calls["conn"] = conn
        calls["intake_data"] = intake_data
        return axis

    monkeypatch.setattr(I, "_resolve_temporal_axis", fake_axis)
    import aughor.agent.explore as ex
    monkeypatch.setattr(ex, "build_analysis_ledger", lambda state: "")
    return calls


def _state():
    return {"question": "", "schema_context": _SCHEMA, "scan_context": "",
            "connection_id": "", "scope_schema": "shop"}


# ── Recovery + routing ───────────────────────────────────────────────────────────

def test_temporal_change_question_recovers_axis_and_routes_temporal(monkeypatch):
    # The intake LLM mislabelled a "what drove the change" question as cross_sectional. With the
    # date declared NONE, the temporal-change override used to be skipped → misrouted. Recovering
    # the join-reachable order date flips it back to the period-over-period route.
    intake = _intake(cross_sectional=True)
    _prep(monkeypatch, intake, axis={"date_column": "shop.orders.order_date"})
    st = _state()
    st["question"] = "What drove the increase in womenswear returns last year?"

    out = I.ada_intake(st, conn=object())
    spec = out["_ada_intake"]
    assert spec["date_column"] == "shop.orders.order_date"      # axis recovered
    assert spec["cross_sectional"] is False                     # temporal route restored
    assert "TEMPORAL AXIS RECOVERED" in spec["intake_notes"]


def test_diagnostic_question_keeps_cross_sectional_but_spec_is_truthful(monkeypatch):
    # A non-temporal "why is X high" run stays cross-sectional (nothing asks for a period-over-
    # period), but the recovered date makes the displayed spec truthful instead of "NONE".
    intake = _intake(cross_sectional=True)
    _prep(monkeypatch, intake, axis={"date_column": "shop.orders.order_date"})
    st = _state()
    st["question"] = "Why are womenswear returns so high?"

    out = I.ada_intake(st, conn=object())
    spec = out["_ada_intake"]
    assert spec["date_column"] == "shop.orders.order_date"
    assert spec["cross_sectional"] is True                      # no temporal-change premise → unchanged
    assert "TEMPORAL AXIS RECOVERED" in spec["intake_notes"]


def test_no_reachable_axis_leaves_everything_unchanged(monkeypatch):
    # The guard: when nothing is join-reachable, date stays NONE, the temporal-change override
    # stays gated off, and no recovery note is added (no false-positive temporal routing).
    intake = _intake(cross_sectional=True)
    _prep(monkeypatch, intake, axis=None)
    st = _state()
    st["question"] = "What drove the increase in womenswear returns last year?"

    out = I.ada_intake(st, conn=object())
    spec = out["_ada_intake"]
    assert (spec["date_column"] or "").upper() == "NONE"
    assert spec["cross_sectional"] is True                      # no_time still forces cross-sectional
    assert "TEMPORAL AXIS RECOVERED" not in (spec["intake_notes"] or "")


def test_recovery_skipped_when_intake_already_has_a_date(monkeypatch):
    # When the intake already declares a real date, the recovery must not run (the resolver is not
    # even consulted for the NONE case) — the existing _resolve_date_column path owns that.
    intake = _intake(date_column="shop.orders.order_date", cross_sectional=False)
    calls = _prep(monkeypatch, intake, axis={"date_column": "shop.other.bogus"})
    st = _state()
    st["question"] = "How did returns trend over the year?"

    out = I.ada_intake(st, conn=object())
    spec = out["_ada_intake"]
    assert spec["date_column"] == "shop.orders.order_date"      # untouched by recovery
    assert "conn" not in calls                                  # resolver never called
    assert "TEMPORAL AXIS RECOVERED" not in (spec["intake_notes"] or "")


def test_resolver_receives_the_bound_conn_and_intake_spec(monkeypatch):
    intake = _intake()
    calls = _prep(monkeypatch, intake, axis={"date_column": "shop.orders.order_date"})
    sentinel = object()
    st = _state()
    st["question"] = "Why are returns so high?"

    I.ada_intake(st, conn=sentinel)
    assert calls["conn"] is sentinel
    assert calls["intake_data"]["metric_table"] == "shop.order_items"


def test_ada_intake_without_conn_is_back_compatible(monkeypatch):
    # conn defaults to None (the resolver fails open to the schema-string parse) — the old
    # single-arg call site keeps working.
    intake = _intake()
    calls = _prep(monkeypatch, intake, axis={"date_column": "shop.orders.order_date"})
    st = _state()
    st["question"] = "Why are returns so high?"

    out = I.ada_intake(st)               # no conn
    assert calls["conn"] is None
    assert out["_ada_intake"]["date_column"] == "shop.orders.order_date"
