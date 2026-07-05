"""Auto-drill WHERE→WHY + metric-aware dimension priority (flag AUGHOR_CAUSAL_DRILL).

For an outcome question ("why is X so high/low") the cross-section scan should (1) float causal
dimensions to the front so they survive the per-phase query cap, and (2) after localising WHERE,
auto-drill the event-only dims to WHY via a composition/share-of-returns lens instead of stopping and
merely recommending it. Additive + fail-off; byte-identical to before when the flag is off.
"""
from __future__ import annotations

import aughor.agent.investigate as inv


# ── item 1: causal-aware dimension priority (pure) ─────────────────────────────

_DIMS = [
    "shop.customers.customer_segment", "shop.orders.channel", "shop.orders.region",
    "shop.order_items.condition", "shop.order_items.return_reason", "shop.brands.brand_tier",
]


def test_default_priority_buries_causal_dims():
    # Without the flag the descriptive taxonomy (customer→channel→category→geo) runs unchanged and the
    # causal dims fall to "other" — reproducing the gap this fixes.
    out = inv._prioritize_dimensions(_DIMS)
    assert out == inv._prioritize_dimensions(_DIMS)  # deterministic
    causal = {"shop.order_items.condition", "shop.order_items.return_reason"}
    assert not (causal & set(out[:2]))  # buried, not up front


def test_causal_first_floats_causal_dims_to_front():
    out = inv._prioritize_dimensions(_DIMS, causal_first=True)
    assert set(out[:2]) == {"shop.order_items.condition", "shop.order_items.return_reason"}
    # the non-causal tail keeps its original relative order (stable, minimal disturbance)
    tail = [d for d in out if d not in out[:2]]
    assert tail == [d for d in inv._prioritize_dimensions(_DIMS) if d not in out[:2]]


def test_causal_split_holds_event_dims_for_composition():
    pop, event = inv._causal_split(
        ["db.returns.reason", "db.orders.channel", "db.refunds.method", "db.customers.segment"])
    # event-TABLE dims (returns/refunds) → the WHY composition; population dims → the WHERE rate scan
    assert event == ["db.returns.reason", "db.refunds.method"]
    assert pop == ["db.orders.channel", "db.customers.segment"]


def test_flag_gating(monkeypatch):
    monkeypatch.delenv("AUGHOR_CAUSAL_DRILL", raising=False)
    assert inv._causal_drill_enabled() is False
    monkeypatch.setenv("AUGHOR_CAUSAL_DRILL", "1")
    assert inv._causal_drill_enabled() is True
    monkeypatch.setenv("AUGHOR_CAUSAL_DRILL", "off")
    assert inv._causal_drill_enabled() is False


# ── multilens improvement #1: causal-relevance in the WHY composition ───────────

def test_select_why_dims_drops_operational_noise():
    # the real womenswear event dims: reason (cause), condition (cause), carrier + refund_method (ops)
    dims = ["lux.returns.reason", "lux.return_logistics.carrier",
            "lux.return_logistics.condition", "lux.return_logistics.refund_method"]
    # leads with the causes; drops the logistics/ops metadata that diluted the WHY (4 pies → 2)
    assert inv._select_why_dims(dims) == ["lux.returns.reason", "lux.return_logistics.condition"]


def test_select_why_dims_keeps_neutral_as_context():
    # a dim in neither vocabulary is kept (after the causes) — never silently dropped
    dims = ["db.returns.reason", "db.returns.segment_at_return", "db.return_logistics.carrier"]
    assert inv._select_why_dims(dims) == ["db.returns.reason", "db.returns.segment_at_return"]


def test_select_why_dims_fallback_keeps_all_when_nothing_causal():
    # no recognisably-causal column → keep every dim unchanged (don't drop to zero on odd schemas)
    dims = ["db.returns.disposition", "db.return_logistics.carrier"]
    assert inv._select_why_dims(dims) == dims


def test_composition_lens_composes_only_the_selected_why_dims(monkeypatch):
    # the lens must hand run_analysis_phase ONLY the causal dims — proving the ops noise is gone
    seen = {}
    def rate_stub(conn, **kw):
        seen["plan_user"] = kw.get("plan_user", "")
        return inv._PhaseRun(ok=True, results=[])
    monkeypatch.setattr(inv, "run_analysis_phase", rate_stub)
    state = {"question": "Why are womenswear returns so high?",
             "schema_context": "lux.returns(reason)", "connection_id": "t",
             "_ada_intake": {"metric_label": "return rate", "filtered_schema": "lux.returns(reason)"}}
    inv._run_composition_lens(state, object(), [
        "lux.returns.reason", "lux.return_logistics.carrier",
        "lux.return_logistics.condition", "lux.return_logistics.refund_method"])
    pu = seen["plan_user"]
    assert "returns.reason" in pu and "return_logistics.condition" in pu
    assert "carrier" not in pu and "refund_method" not in pu


# ── item 2: the WHERE→WHY drill wiring in ada_cross_section ─────────────────────

_MIXED_DIMS = [
    "lux.order_items.brand", "lux.order_items.brand_tier", "lux.platforms.segment",
    "lux.returns.reason", "lux.return_logistics.condition",
]


class _FakeConn:
    _connection_id = "t"
    dialect = "duckdb"
    def make_reader(self):
        return self


def _state(dims):
    return {
        "question": "Why are womenswear returns so high?",
        "schema_context": "lux.order_items(brand, brand_tier, returned)\nlux.returns(reason)",
        "connection_id": "t",
        "investigation_phases": [],
        "_ada_intake": {
            "dimensions": list(dims),
            "metric_label": "return rate", "metric_sql": "AVG(returned)",
            "metric_table": "lux.order_items", "filtered_schema": "lux.order_items(brand)",
        },
    }


def _install(monkeypatch):
    """Stub the rate scan (run_analysis_phase) + the WHY composition lens so the node runs without an
    LLM/DB. Capture what each received."""
    cap = {}
    def rate_stub(conn, **kw):
        cap["plan_user"] = kw.get("plan_user", "")
        return inv._PhaseRun(ok=True, results=[])
    def comp_stub(state, conn, event_dims):
        cap["event_dims"] = list(event_dims)
        return {"phase_id": "cross_section_mechanism", "phase_name": "Mechanism / Reason Scan — Why",
                "status": "complete", "summary": "size_fit = 42% of returns", "findings": []}
    monkeypatch.setattr(inv, "run_analysis_phase", rate_stub)
    monkeypatch.setattr(inv, "_run_composition_lens", comp_stub)
    return cap


def _phase_ids(out):
    return [p["phase_id"] for p in out["investigation_phases"]]


def test_drill_appends_why_phase_and_scans_only_population(monkeypatch):
    cap = _install(monkeypatch)
    monkeypatch.setenv("AUGHOR_CAUSAL_DRILL", "1")
    out = inv.ada_cross_section(_state(_MIXED_DIMS), _FakeConn())
    ids = _phase_ids(out)
    # the WHERE rate phase, then the auto-drilled WHY composition phase
    assert "cross_section" in ids and ids[-1] == "cross_section_mechanism"
    # composition got exactly the event-only dims (the WHY), never a tautological rate of them
    assert cap["event_dims"] == ["lux.returns.reason", "lux.return_logistics.condition"]
    # the rate scan's prompt lists the population dims but NOT the event-only ones
    assert "order_items.brand" in cap["plan_user"] and "platforms.segment" in cap["plan_user"]
    assert "returns.reason" not in cap["plan_user"] and "return_logistics.condition" not in cap["plan_user"]


def test_flag_off_is_byte_identical_single_scan(monkeypatch):
    cap = _install(monkeypatch)
    monkeypatch.delenv("AUGHOR_CAUSAL_DRILL", raising=False)
    out = inv.ada_cross_section(_state(_MIXED_DIMS), _FakeConn())
    assert _phase_ids(out) == ["cross_section"]           # no WHY phase
    assert "event_dims" not in cap                          # composition lens never called
    assert "returns.reason" in cap["plan_user"]            # event dims still in the (unsplit) rate scan


def test_sub_lens_invocation_never_drills(monkeypatch):
    # dims_override set = a themed sub-lens call from the multilens node, which owns its own
    # partition/composition — the serial drill must not fire and double-count.
    cap = _install(monkeypatch)
    monkeypatch.setenv("AUGHOR_CAUSAL_DRILL", "1")
    out = inv.ada_cross_section(_state(_MIXED_DIMS), _FakeConn(), dims_override=_MIXED_DIMS)
    assert _phase_ids(out) == ["cross_section"]
    assert "event_dims" not in cap


def test_no_event_dims_means_no_drill(monkeypatch):
    cap = _install(monkeypatch)
    monkeypatch.setenv("AUGHOR_CAUSAL_DRILL", "1")
    out = inv.ada_cross_section(_state(["lux.order_items.brand", "lux.platforms.segment"]), _FakeConn())
    assert _phase_ids(out) == ["cross_section"]            # nothing event-only to drill
    assert "event_dims" not in cap
