"""Unit tests for the flag-gated parallel multi-lens cross-section (ada.parallel_lenses).

A cross-sectional "why" question runs independent lenses (segment/where ∥ mechanism/why)
concurrently via ContextThreadPoolExecutor, reusing the full ada_cross_section scan per lens,
then merges investigation_phases. These pin: dimension partitioning, parallel merge + determinism,
failure isolation, budget-abort, the single-group degrade, and the flag gate.
"""
from __future__ import annotations

import os
import time

import pytest

import aughor.agent.investigate as inv
from aughor.kernel.metering import BudgetExceeded


WOMENSWEAR_DIMS = [
    "luxexperience.order_items.brand",
    "luxexperience.order_items.brand_tier",
    "luxexperience.order_items.platform",
    "luxexperience.returns.reason",
    "luxexperience.return_logistics.condition",
    "luxexperience.return_logistics.carrier",
    "luxexperience.return_logistics.refund_method",
    "luxexperience.platforms.segment",
]


# ── _partition_dimensions ──────────────────────────────────────────────────────

def test_partition_splits_population_rate_vs_event_composition():
    lenses = inv._partition_dimensions(WOMENSWEAR_DIMS)
    assert [(name, kind) for name, _, _, kind in lenses] == [("segment", "rate"), ("mechanism", "composition")]
    seg = next(d for n, d, _, _ in lenses if n == "segment")
    mech = next(d for n, d, _, _ in lenses if n == "mechanism")
    # Population dims (on order_items/platforms) → the RATE scan (WHERE).
    assert set(inv._dim_column(d) for d in seg) == {"brand", "brand_tier", "platform", "segment"}
    # Event-only dims (on returns/return_logistics) → the COMPOSITION scan (WHY) — a rate would be 100%.
    assert set(inv._dim_column(d) for d in mech) == {"reason", "condition", "carrier", "refund_method"}
    assert next(m for n, _, m, _ in lenses if n == "segment")[0] == "cross_section"
    assert next(m for n, _, m, _ in lenses if n == "mechanism")[0] == "cross_section_mechanism"


def test_is_event_dim_classifies_by_table():
    # restocked was mis-routed by a name regex; classifying by TABLE catches it as event-only.
    assert inv._is_event_dim("db.return_logistics.restocked") is True
    assert inv._is_event_dim("db.returns.reason") is True
    assert inv._is_event_dim("db.order_items.brand") is False
    assert inv._is_event_dim("db.platforms.segment") is False


def test_partition_degrades_to_single_rate_when_all_population():
    # All population dims → single "all" RATE scan (byte-identical to the un-split behavior).
    p = inv._partition_dimensions(["db.order_items.brand", "db.order_items.platform"])
    assert [(n, k) for n, _, _, k in p] == [("all", "rate")]
    assert [(n, k) for n, _, _, k in inv._partition_dimensions(["db.order_items.brand"])] == [("all", "rate")]
    assert [(n, k) for n, _, _, k in inv._partition_dimensions([])] == [("all", "rate")]


def test_partition_pure_event_runs_as_composition():
    # A question whose only dims are event-only → a single COMPOSITION lens (never a tautological rate).
    p = inv._partition_dimensions(["db.returns.reason", "db.return_logistics.carrier"])
    assert [(n, k) for n, _, _, k in p] == [("mechanism", "composition")]


# ── ada_cross_section_multilens (the node) ─────────────────────────────────────

class _FakeConn:
    def __init__(self):
        self.readers = 0
    def make_reader(self):
        self.readers += 1
        return _FakeConn()


def _state(dims, base_phases=None):
    return {"_ada_intake": {"dimensions": dims},
            "investigation_phases": list(base_phases or [])}


def _install_stub(monkeypatch, *, sleep=0.0, raise_on=(), budget_on=()):
    """Stub the rate lens (ada_cross_section) AND the event composition lens so the parallel node runs
    without an LLM/DB. Each returns a phase tagged by its phase id."""
    def stub(state, conn, *, dims_override=None, phase_meta=None, period_directive=None,
             extra_dims=None, extra_schema=None, extra_directive=None, grain=None):
        pid, title, emoji = phase_meta or ("cross_section", "X", "🧭")
        if sleep:
            time.sleep(sleep)
        if pid in budget_on:
            raise BudgetExceeded("token budget (test)")
        if pid in raise_on:
            raise RuntimeError(f"boom {pid}")
        base = state.get("investigation_phases", [])
        phase = {"phase_id": pid, "title": title, "dims": list(dims_override or [])}
        return {"investigation_phases": base + [phase], "_cross_section_summary": f"summary::{pid}"}

    def comp_stub(state, conn, event_dims):
        if sleep:
            time.sleep(sleep)
        if "cross_section_mechanism" in budget_on:
            raise BudgetExceeded("token budget (test)")
        if "cross_section_mechanism" in raise_on:
            raise RuntimeError("boom composition")
        return {"phase_id": "cross_section_mechanism", "title": "Mechanism / Reason Scan — Why"}

    monkeypatch.setattr(inv, "ada_cross_section", stub)
    monkeypatch.setattr(inv, "_run_composition_lens", comp_stub)


def test_multilens_merges_both_lenses(monkeypatch):
    _install_stub(monkeypatch)
    base = [{"phase_id": "intake"}]
    out = inv.ada_cross_section_multilens(_state(WOMENSWEAR_DIMS, base), _FakeConn())
    ph = out["investigation_phases"]
    ids = [p["phase_id"] for p in ph]
    # base preserved once + both lens phases, primary first (deterministic).
    assert ids == ["intake", "cross_section", "cross_section_mechanism"]
    # primary lens summary is surfaced.
    assert out["_cross_section_summary"] == "summary::cross_section"


def test_multilens_routes_event_dims_to_composition(monkeypatch):
    # The event group must go through the COMPOSITION lens (share-of-returns), never the rate scan —
    # otherwise reason/condition/carrier come back as tautological 100%.
    comp_dims = {}
    def comp(state, conn, event_dims):
        comp_dims["dims"] = list(event_dims)
        return {"phase_id": "cross_section_mechanism"}
    monkeypatch.setattr(inv, "_run_composition_lens", comp)
    def xsec(state, conn, *, dims_override=None, phase_meta=None, period_directive=None,
             extra_dims=None, extra_schema=None, extra_directive=None, grain=None):
        pid = (phase_meta or ("cross_section", "X", "🧭"))[0]
        return {"investigation_phases": state.get("investigation_phases", []) + [{"phase_id": pid}],
                "_cross_section_summary": "s"}
    monkeypatch.setattr(inv, "ada_cross_section", xsec)
    monkeypatch.setattr(inv, "_resolve_temporal_axis", lambda s, c=None: None)
    out = inv.ada_cross_section_multilens(_state(WOMENSWEAR_DIMS), _FakeConn())
    ids = [p["phase_id"] for p in out["investigation_phases"]]
    assert ids == ["cross_section", "cross_section_mechanism"]
    assert set(inv._dim_column(d) for d in comp_dims["dims"]) == {"reason", "condition", "carrier", "refund_method"}


def test_multilens_runs_lenses_concurrently(monkeypatch):
    _install_stub(monkeypatch, sleep=0.3)
    t0 = time.time()
    out = inv.ada_cross_section_multilens(_state(WOMENSWEAR_DIMS), _FakeConn())
    dt = time.time() - t0
    assert len([p for p in out["investigation_phases"]]) == 2
    assert dt < 0.55, f"expected concurrent (~0.3s), got {dt:.2f}s — lenses serialized"


def test_multilens_uses_a_reader_per_lens(monkeypatch):
    _install_stub(monkeypatch)
    conn = _FakeConn()
    inv.ada_cross_section_multilens(_state(WOMENSWEAR_DIMS), conn)
    assert conn.readers == 2  # one make_reader() clone per lens


def test_multilens_isolates_a_failing_lens(monkeypatch):
    _install_stub(monkeypatch, raise_on={"cross_section_mechanism"})
    out = inv.ada_cross_section_multilens(_state(WOMENSWEAR_DIMS), _FakeConn())
    ids = [p["phase_id"] for p in out["investigation_phases"]]
    # The segment lens survives; the failing mechanism lens is skipped, never aborts the run.
    assert ids == ["cross_section"]


def test_multilens_budget_exceeded_aborts(monkeypatch):
    _install_stub(monkeypatch, budget_on={"cross_section_mechanism"})
    with pytest.raises(BudgetExceeded):
        inv.ada_cross_section_multilens(_state(WOMENSWEAR_DIMS), _FakeConn())


def test_multilens_single_group_degrades_to_single_scan(monkeypatch):
    calls = []
    def stub(state, conn, *, dims_override=None, phase_meta=None, period_directive=None,
             extra_dims=None, extra_schema=None, extra_directive=None, grain=None):
        calls.append(phase_meta)
        return {"investigation_phases": state.get("investigation_phases", []) + [{"phase_id": "cross_section"}],
                "_cross_section_summary": "s"}
    monkeypatch.setattr(inv, "ada_cross_section", stub)
    out = inv.ada_cross_section_multilens(_state(["t.brand", "t.platform"]), _FakeConn())
    # Only one lens group → ada_cross_section called once with default meta (single scan).
    assert len(calls) == 1
    assert calls[0] is None or calls[0][0] == "cross_section"
    assert [p["phase_id"] for p in out["investigation_phases"]] == ["cross_section"]


# ── #4: discriminating population-attribute discovery ──────────────────────────

class _DiscoverConn:
    """Fake conn for _discover_population_dims: answers the uniqueness + cardinality probes by table."""
    def __init__(self, rows_by_table, distinct_by_col):
        self.rows_by_table = rows_by_table          # table -> (total_rows, distinct_join_key)
        self.distinct_by_col = distinct_by_col       # "table.col" -> distinct count

    def execute(self, _id, sql):
        import re as _re
        from types import SimpleNamespace
        m = _re.search(r"FROM\s+([\w.]+)", sql)
        t = m.group(1) if m else ""
        if "COUNT(DISTINCT" in sql and "COUNT(*)" in sql:      # uniqueness probe
            tot, dist = self.rows_by_table.get(t, (100, 100))
            return SimpleNamespace(rows=[[tot, dist]], error=None)
        if "COUNT(DISTINCT" in sql:                            # cardinality probe
            cm = _re.search(r"COUNT\(DISTINCT\s+(\w+)\)", sql)
            col = cm.group(1) if cm else ""
            return SimpleNamespace(rows=[[self.distinct_by_col.get(f"{t}.{col}", 999)]], error=None)
        return SimpleNamespace(rows=[[0]], error=None)


def test_discover_prefers_product_price_and_excludes_satellites(monkeypatch):
    typed = {
        "db.order_items": [("order_item_id", "VARCHAR"), ("order_id", "VARCHAR"),
                           ("product_id", "VARCHAR"), ("brand", "VARCHAR"), ("returned", "BOOLEAN")],
        "db.products": [("product_id", "VARCHAR"), ("season", "VARCHAR"),
                        ("category", "VARCHAR"), ("retail_price_eur", "DOUBLE"), ("cost_eur", "DOUBLE")],
        "db.customer_service": [("order_id", "VARCHAR"), ("channel", "VARCHAR")],  # sparse satellite
        "db.returns": [("return_id", "VARCHAR"), ("order_id", "VARCHAR"), ("reason", "VARCHAR")],  # event
    }
    monkeypatch.setattr(inv, "_db_typed_columns", lambda c, s: typed)
    conn = _DiscoverConn(
        rows_by_table={"db.products": (5000, 5000),          # product_id unique → safe join
                       "db.customer_service": (8000, 3000)},  # order_id repeats → fan-out → skipped
        distinct_by_col={"db.products.season": 12, "db.products.category": 10, "db.customer_service.channel": 4},
    )
    state = {"scope_schema": "db", "_ada_intake": {
        "metric_table": "db.order_items", "metric_label": "return rate",
        "dimensions": ["db.order_items.brand"]}}
    aug = inv._discover_population_dims(state, conn)
    # picks the ITEM price on products (not an order total), joined by the unique product_id
    assert aug["price_col"] == "db.products.retail_price_eur"
    assert aug["join_table"] == "db.products" and aug["join_key"] == "product_id"
    # season is surfaced; category (subject filter) + the sparse customer_service satellite are excluded
    assert "db.products.season" in aug["extra_dims"]
    assert not any("customer_service" in d for d in aug["extra_dims"])
    assert not any("category" in d for d in aug["extra_dims"])


def test_discover_none_when_no_joinable_dim_table(monkeypatch):
    monkeypatch.setattr(inv, "_db_typed_columns", lambda c, s: {
        "db.order_items": [("order_item_id", "VARCHAR"), ("returned", "BOOLEAN")]})  # no FK ids
    state = {"scope_schema": "db", "_ada_intake": {"metric_table": "db.order_items", "dimensions": []}}
    assert inv._discover_population_dims(state, _DiscoverConn({}, {})) == {}


def test_multilens_passes_population_augmentation_to_rate_lens(monkeypatch):
    seen = {}
    def xsec(state, conn, *, dims_override=None, phase_meta=None, period_directive=None,
             extra_dims=None, extra_schema=None, extra_directive=None, grain=None):
        seen["extra_dims"] = extra_dims
        seen["extra_directive"] = extra_directive
        return {"investigation_phases": state.get("investigation_phases", []) + [{"phase_id": "cross_section"}],
                "_cross_section_summary": "s"}
    monkeypatch.setattr(inv, "ada_cross_section", xsec)
    monkeypatch.setattr(inv, "_run_composition_lens", lambda s, c, d: {"phase_id": "cross_section_mechanism"})
    monkeypatch.setattr(inv, "_resolve_temporal_axis", lambda s, c=None: None)
    monkeypatch.setattr(inv, "_discover_population_dims", lambda s, c: {
        "extra_dims": ["db.products.season"], "price_col": "db.products.retail_price_eur",
        "join_table": "db.products", "join_key": "product_id", "metric_table": "db.order_items"})
    inv.ada_cross_section_multilens(_state(WOMENSWEAR_DIMS), _FakeConn())
    assert seen["extra_dims"] == ["db.products.season"]
    assert "PRICE BAND" in (seen["extra_directive"] or "")


# ── #2: saturation detector ─────────────────────────────────────────────────────

def test_is_saturated_flags_tautology_not_uniformity():
    cols = ["reason", "metric_total", "n"]
    # tautology: every group pinned at 0/100% (an event-only rate) → saturated
    assert inv._is_saturated(cols, [["NULL", 0.0, 100], ["late", 1.0, 50], ["quality", 1.0, 40]]) is True
    assert inv._is_saturated(cols, [["a", 100, 5], ["b", 100, 5]]) is True
    # legitimate uniformity (32.4 / 32.8) is a REAL flat finding — never saturated
    assert inv._is_saturated(cols, [["ultra", 32.4, 100], ["luxury", 32.8, 100]]) is False
    # a real spread is obviously not saturated
    assert inv._is_saturated(cols, [["YOOX", 26.9, 100], ["NAP", 40.1, 100]]) is False
    # too few groups → not called
    assert inv._is_saturated(cols, [["only", 100, 5]]) is False


# ── The flag gate (graph wiring) ────────────────────────────────────────────────

def _ada_nodes(flag):
    import duckdb
    from aughor.db.connection import DuckDBConnection
    from aughor.agent.graph import build_graph_generic
    if flag:
        os.environ["AUGHOR_ADA_PARALLEL_LENSES"] = flag
    else:
        os.environ.pop("AUGHOR_ADA_PARALLEL_LENSES", None)
    try:
        db = DuckDBConnection.__new__(DuckDBConnection)
        db._conn = duckdb.connect(":memory:")
        db._path = None
        db._connection_id = "t"
        return set(build_graph_generic(db).get_graph().nodes.keys())
    finally:
        os.environ.pop("AUGHOR_ADA_PARALLEL_LENSES", None)


def test_flag_off_has_no_multilens_node():
    nodes = _ada_nodes(None)
    assert "ada_cross_section_multilens" not in nodes
    assert "ada_cross_section" in nodes


def test_flag_on_registers_multilens_node():
    nodes = _ada_nodes("1")
    assert "ada_cross_section_multilens" in nodes


# ── WHY×WHERE interaction lens (flag ada.why_where_interaction) ─────────────────

def _install_interaction_stubs(monkeypatch, *, why_findings=True, interaction_phase=True):
    """Stub the rate + composition lenses (composition carries findings — the interaction gate needs
    it) and the interaction lens (sentinel). No temporal axis. Returns the captured interaction args."""
    def xsec(state, conn, *, dims_override=None, phase_meta=None, period_directive=None,
             extra_dims=None, extra_schema=None, extra_directive=None, grain=None):
        pid = (phase_meta or ("cross_section", "X", "🧭"))[0]
        return {"investigation_phases": state.get("investigation_phases", []) + [{"phase_id": pid}],
                "_cross_section_summary": f"WHERE::{pid}"}
    def comp(state, conn, event_dims):
        ph = {"phase_id": "cross_section_mechanism", "summary": "size/fit 42%"}
        ph["findings"] = [{"title": "by reason"}] if why_findings else []
        return ph
    captured = {}
    def interact(state, conn, where_summary, why_summary):
        captured["where"], captured["why"] = where_summary, why_summary
        return {"phase_id": "cross_section_interaction", "summary": "concentrates in luxury"} \
            if interaction_phase else None
    monkeypatch.setattr(inv, "ada_cross_section", xsec)
    monkeypatch.setattr(inv, "_run_composition_lens", comp)
    monkeypatch.setattr(inv, "_run_interaction_lens", interact)
    monkeypatch.setattr(inv, "_resolve_temporal_axis", lambda s, c=None: None)
    return captured


def test_interaction_appends_and_gets_both_summaries_when_flag_on(monkeypatch):
    captured = _install_interaction_stubs(monkeypatch)
    monkeypatch.setenv("AUGHOR_ADA_WHY_WHERE_INTERACTION", "1")
    out = inv.ada_cross_section_multilens(_state(WOMENSWEAR_DIMS), _FakeConn())
    ids = [p["phase_id"] for p in out["investigation_phases"]]
    assert ids[-1] == "cross_section_interaction"           # forward-chained last
    assert captured["why"] == "size/fit 42%" and "WHERE::" in captured["where"]


def test_interaction_off_by_default(monkeypatch):
    _install_interaction_stubs(monkeypatch)
    monkeypatch.delenv("AUGHOR_ADA_WHY_WHERE_INTERACTION", raising=False)
    out = inv.ada_cross_section_multilens(_state(WOMENSWEAR_DIMS), _FakeConn())
    assert "cross_section_interaction" not in [p["phase_id"] for p in out["investigation_phases"]]


def test_interaction_skipped_without_why_findings(monkeypatch):
    # composition ran but produced no findings → nothing to cross → no interaction (even flag-on)
    _install_interaction_stubs(monkeypatch, why_findings=False)
    monkeypatch.setenv("AUGHOR_ADA_WHY_WHERE_INTERACTION", "1")
    out = inv.ada_cross_section_multilens(_state(WOMENSWEAR_DIMS), _FakeConn())
    assert "cross_section_interaction" not in [p["phase_id"] for p in out["investigation_phases"]]


def test_run_interaction_lens_crosses_reason_and_segment(monkeypatch):
    # the lens hands run_analysis_phase a cross query with BOTH lens summaries as context
    seen = {}
    def rate_stub(conn, **kw):
        seen["plan_user"], seen["phase_id"] = kw.get("plan_user", ""), kw.get("phase_id")
        return inv._PhaseRun(ok=True, results=[])
    monkeypatch.setattr(inv, "run_analysis_phase", rate_stub)
    state = {"question": "Why are womenswear returns so high?", "connection_id": "t",
             "schema_context": "lux.returns(reason)",
             "_ada_intake": {"metric_label": "return rate", "filtered_schema": "lux.returns(reason)"}}
    ph = inv._run_interaction_lens(state, object(), "luxury 40.5% vs off-price 27%", "size/fit 42% of returns")
    assert seen["phase_id"] == "cross_section_interaction"
    assert "luxury 40.5%" in seen["plan_user"] and "size/fit 42%" in seen["plan_user"]
    assert ph["phase_id"] == "cross_section_interaction"


# ── Temporal WHEN lens: axis resolver ──────────────────────────────────────────

_TYPED = {
    "db.order_items": [("order_item_id", "VARCHAR"), ("brand", "VARCHAR"), ("returned", "BOOLEAN")],
    "db.orders": [("order_id", "VARCHAR"), ("order_date", "DATE"), ("gmv_eur", "DOUBLE")],
    "db.returns": [("return_id", "VARCHAR"), ("return_date", "DATE"), ("reason", "VARCHAR")],
}


def test_resolver_prefers_population_date_over_event_date(monkeypatch):
    monkeypatch.setattr(inv, "_typed_columns", lambda s: _TYPED)
    state = {"schema_context": "x", "_ada_intake": {
        "metric_table": "db.order_items",
        "metric_sql": "AVG(CASE WHEN returned THEN 1 ELSE 0 END)",
        "metric_label": "womenswear return rate",
        "dimensions": ["db.order_items.brand", "db.returns.reason"]}}
    axis = inv._resolve_temporal_axis(state)
    # An event-RATE metric must trend on the ORDER/population date, never the event (returns) date.
    assert axis is not None
    assert axis["date_column"] == "db.orders.order_date"


def test_resolver_none_when_no_date(monkeypatch):
    monkeypatch.setattr(inv, "_typed_columns", lambda s: {
        "db.order_items": [("order_item_id", "VARCHAR"), ("returned", "BOOLEAN")]})
    state = {"schema_context": "x", "_ada_intake": {
        "metric_table": "db.order_items", "metric_sql": "AVG(returned)",
        "metric_label": "return rate", "dimensions": []}}
    assert inv._resolve_temporal_axis(state) is None


# ── Temporal WHEN lens: anomaly detection ──────────────────────────────────────

def test_detect_anomaly_flat_returns_none():
    cols = ["period", "metric_value", "n"]
    flat = [["2021", 32.8, 16198], ["2022", 32.4, 18340], ["2023", 32.8, 17855],
            ["2024", 32.8, 16682], ["2025", 32.3, 14949]]
    assert inv._detect_anomalous_period(cols, flat) is None


def test_detect_anomaly_flags_material_spike():
    cols = ["period", "metric_value", "n"]
    spike = [["2021", 30.0, 16000], ["2022", 31.0, 18000], ["2023", 58.0, 17000],
             ["2024", 30.5, 16000], ["2025", 30.0, 15000]]
    a = inv._detect_anomalous_period(cols, spike)
    assert a is not None and a["period"] == "2023"


def test_detect_anomaly_ignores_small_sample_blip():
    cols = ["period", "metric_value", "n"]
    blip = [["2021", 30.0, 16000], ["2022", 31.0, 18000], ["2023", 90.0, 9],
            ["2024", 30.5, 16000], ["2025", 30.0, 15000]]
    assert inv._detect_anomalous_period(cols, blip) is None


def test_detect_anomaly_needs_min_periods():
    cols = ["period", "metric_value", "n"]
    assert inv._detect_anomalous_period(cols, [["2023", 40.0, 100], ["2024", 30.0, 100]]) is None


# ── Multilens integration: WHEN lens runs in parallel + drill forward-chains ────

def _stub_xsec_and_time(monkeypatch, *, axis, temporal_return):
    """Stub the rate lens (records period_directive), the composition lens, + the temporal seam."""
    calls = []
    def xsec(state, conn, *, dims_override=None, phase_meta=None, period_directive=None,
             extra_dims=None, extra_schema=None, extra_directive=None, grain=None):
        pid = (phase_meta or ("cross_section", "X", "🧭"))[0]
        calls.append((pid, period_directive))
        base = state.get("investigation_phases", [])
        return {"investigation_phases": base + [{"phase_id": pid}], "_cross_section_summary": f"s::{pid}"}
    monkeypatch.setattr(inv, "ada_cross_section", xsec)
    monkeypatch.setattr(inv, "_run_composition_lens",
                        lambda s, c, dims: {"phase_id": "cross_section_mechanism"})
    monkeypatch.setattr(inv, "_resolve_temporal_axis", lambda s, c=None: axis)
    monkeypatch.setattr(inv, "_run_temporal_lens", lambda s, c, a, grain=None: temporal_return)
    return calls


def test_multilens_adds_when_lens_and_no_drill_when_flat(monkeypatch):
    axis = {"date_column": "db.orders.order_date", "date_table": "db.orders", "metric_table": "db.order_items"}
    when_phase = {"phase_id": "temporal_when"}
    calls = _stub_xsec_and_time(monkeypatch, axis=axis, temporal_return=(when_phase, None))  # flat → no anomaly
    out = inv.ada_cross_section_multilens(_state(WOMENSWEAR_DIMS), _FakeConn())
    ids = [p["phase_id"] for p in out["investigation_phases"]]
    # segment + mechanism + temporal WHEN, in order; NO period drill (trend was flat).
    assert ids == ["cross_section", "cross_section_mechanism", "temporal_when"]
    assert not any(pd for _, pd in calls)  # no period_directive → drill never ran


def test_multilens_forward_chains_drill_on_anomaly(monkeypatch):
    axis = {"date_column": "db.orders.order_date", "date_table": "db.orders", "metric_table": "db.order_items"}
    when_phase = {"phase_id": "temporal_when"}
    anomaly = {"period": "2023-Q3", "value": 58.0, "baseline": 33.0, "n": 5000}
    calls = _stub_xsec_and_time(monkeypatch, axis=axis, temporal_return=(when_phase, anomaly))
    out = inv.ada_cross_section_multilens(_state(WOMENSWEAR_DIMS), _FakeConn())
    ids = [p["phase_id"] for p in out["investigation_phases"]]
    # parallel lenses + WHEN, THEN a period-scoped drill of the POPULATION (rate) group only —
    # a rate drill of event-only dims would re-introduce the tautology, so composition isn't drilled.
    assert "temporal_when" in ids
    assert "period_drill_segment" in ids
    assert "period_drill_mechanism" not in ids
    # the drill call carries a period_directive naming the flagged period.
    drill_calls = [pd for pid, pd in calls if pid.startswith("period_drill")]
    assert drill_calls and all("2023-Q3" in (pd or "") for pd in drill_calls)
