"""P4 clarify_gate (backend detection + routing + graph wiring).

When a metric's GOVERNED reading and the LLM's parsed reading both run over the metric table but give
materially different numbers (the count-vs-value 'refund rate' class), the deep run should PAUSE and ask
rather than silently pin one. These tests pin the detector's fire/no-fire conditions, the intake router,
and the graph structure (the clarify_gate node + interrupt exist only when the flag is on).
"""
from __future__ import annotations

import types

import duckdb

import aughor.agent.investigate as I
from aughor.agent.prompts_investigate import IntakeOutput
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


_GOVERNED = CanonicalMetric(name="refund_rate", label="Refund Rate",
                            sql="SUM(refunded_value) / NULLIF(SUM(order_total), 0) * 100",
                            source="catalog", verified=True)


class _ProbeConn:
    """execute() returns a scalar chosen by a substring of the probed SQL (None-erroring otherwise)."""
    def __init__(self, mapping): self._m = mapping
    def execute(self, tag, sql):
        for sub, val in self._m.items():
            if sub in sql:
                return types.SimpleNamespace(error=None, rows=[[val]])
        return types.SimpleNamespace(error="column not found", rows=[])


def _on(monkeypatch, metrics=(_GOVERNED,)):
    monkeypatch.setenv("AUGHOR_CLARIFY_GATE", "1")
    monkeypatch.setattr("aughor.semantic.canonical.resolve_canonical_metrics",
                        lambda *a, **k: list(metrics))


# ── materiality ───────────────────────────────────────────────────────────────────

def test_material_divergence_threshold():
    assert I._metrics_materially_diverge(20.2, 18.8)      # 6.9% relative → material
    assert not I._metrics_materially_diverge(18.8, 18.9)  # 0.5% → not
    assert not I._metrics_materially_diverge(0.0, 0.0)


# ── detector fires on a genuine divergence ─────────────────────────────────────────

def test_detects_governed_vs_parsed_divergence(monkeypatch):
    _on(monkeypatch)
    conn = _ProbeConn({"refunded_value": 18.8, "refund_id": 20.2})   # governed 18.8, parsed 20.2
    payload = I._detect_metric_clarify(_intake(), "c1", "schema", conn, "why is the refund rate high?")
    assert payload is not None
    assert payload["subject"] == "definition of Fragrance refund rate"
    assert len(payload["options"]) == 2 and len(payload["readings"]) == 2
    assert any("refunded_value" in r["sql"] for r in payload["readings"])   # governed reading carried
    assert any("18.8%" in p or "18.8" in p for p in payload["previews"])


def test_strip_metric_alias():
    # The intake LLM sometimes emits metric_sql with its SELECT-list alias; the probe must strip it
    # (a live pass caught the clarify silently no-firing because `SELECT {sql} AS v` double-aliased).
    assert I._strip_metric_alias("SUM(x)/COUNT(*) AS item_return_rate") == "SUM(x)/COUNT(*)"
    assert I._strip_metric_alias("SUM(CASE WHEN r THEN 1 END)/NULLIF(COUNT(*),0) as rate") \
        == "SUM(CASE WHEN r THEN 1 END)/NULLIF(COUNT(*),0)"
    assert I._strip_metric_alias("SUM(x)") == "SUM(x)"          # no alias → unchanged
    assert I._strip_metric_alias("  SUM(x) AS v  ") == "SUM(x)"


# ── no-fire conditions (proceed silently) ──────────────────────────────────────────

def test_no_fire_when_flag_off(monkeypatch):
    monkeypatch.delenv("AUGHOR_CLARIFY_GATE", raising=False)
    monkeypatch.setattr("aughor.semantic.canonical.resolve_canonical_metrics", lambda *a, **k: [_GOVERNED])
    conn = _ProbeConn({"refunded_value": 18.8, "refund_id": 20.2})
    assert I._detect_metric_clarify(_intake(), "c1", "schema", conn, "q") is None


def test_no_fire_when_not_a_ratio(monkeypatch):
    _on(monkeypatch)
    conn = _ProbeConn({"total_amount": 100.0})
    it = _intake(metric_label="total revenue", metric_sql="SUM(total_amount)")
    assert I._detect_metric_clarify(it, "c1", "schema", conn, "q") is None


def test_no_fire_when_no_governed_match(monkeypatch):
    _on(monkeypatch, metrics=[])
    conn = _ProbeConn({"refund_id": 20.2})
    assert I._detect_metric_clarify(_intake(), "c1", "schema", conn, "q") is None


def test_no_fire_when_readings_agree(monkeypatch):
    _on(monkeypatch)
    conn = _ProbeConn({"refunded_value": 18.8, "refund_id": 18.8})   # same value → no ambiguity
    assert I._detect_metric_clarify(_intake(), "c1", "schema", conn, "q") is None


def test_no_fire_when_parsed_reading_does_not_run(monkeypatch):
    _on(monkeypatch)
    conn = _ProbeConn({"refunded_value": 18.8})   # parsed (refund_id) errors → not a plausible alt
    assert I._detect_metric_clarify(_intake(), "c1", "schema", conn, "q") is None


def test_no_fire_when_already_resolved(monkeypatch):
    _on(monkeypatch)
    from aughor.org.context import current_org_id
    from aughor.semantic import ambiguity_ledger as L
    L.save_resolution(L.AmbiguityResolution(
        connection_id="c_resolved", org_id=current_org_id() or "",
        dim_kind="AmbiIntent", dim_facet="aggregation",
        subject="definition of Fragrance refund rate",
        resolved_reading="Governed: refund_rate", resolved_sql=_GOVERNED.sql, resolution_source="user"))
    conn = _ProbeConn({"refunded_value": 18.8, "refund_id": 20.2})
    assert I._detect_metric_clarify(_intake(), "c_resolved", "schema", conn, "q") is None


# ── intake router ──────────────────────────────────────────────────────────────────

def test_router_sends_pending_clarify_to_the_gate():
    st = {"_clarify_pending": {"subject": "x"}, "_ada_intake": {"cross_sectional": True}}
    assert I.route_after_intake_clarify(st) == "clarify_gate"


def test_router_is_transparent_without_a_pending_clarify():
    assert I.route_after_intake_clarify({"_ada_intake": {"cross_sectional": True}}) == "ada_cross_section"
    assert I.route_after_intake_clarify({"_ada_intake": {"cross_sectional": False}}) == "ada_baseline"


# ── graph structure ────────────────────────────────────────────────────────────────

def _mem_db():
    from aughor.db.connection import DuckDBConnection
    db = DuckDBConnection.__new__(DuckDBConnection)
    db._conn = duckdb.connect(":memory:")
    db._path = None
    db._connection_id = "t"
    return db


def test_clarify_gate_interrupt_armed_only_when_enabled():
    from aughor.agent.graph import build_graph_generic
    db = _mem_db()
    on = build_graph_generic(db, clarify_gate=True)
    off = build_graph_generic(db, clarify_gate=False)
    # The NODE is present in both (so a paused run can reconnect its checkpoint on resume — mirrors
    # plan_gate); only the INTERRUPT is armed when the flag is on, so the flag-off run never pauses.
    assert "clarify_gate" in set(on.get_graph().nodes.keys())
    assert "clarify_gate" in set(off.get_graph().nodes.keys())
    assert "clarify_gate" in on.interrupt_before_nodes
    assert "clarify_gate" not in off.interrupt_before_nodes


# ── resume: bind the chosen reading + crystallize (router side) ─────────────────────

def _pending_state():
    return {
        "_ada_intake": {"metric_sql": "COUNT(DISTINCT refund_id)/COUNT(DISTINCT order_id)*100",
                        "metric_is_ratio": True, "metric_label": "Fragrance refund rate"},
        "_clarify_pending": {
            "subject": "definition of Fragrance refund rate", "metric_label": "Fragrance refund rate",
            "options": ["Governed: refund_rate", "As I read the question"],
            "readings": [
                {"label": "Governed: refund_rate", "sql": _GOVERNED.sql, "is_ratio": True},
                {"label": "As I read the question",
                 "sql": "COUNT(DISTINCT refund_id)/COUNT(DISTINCT order_id)*100", "is_ratio": True},
            ],
        },
    }


def test_resume_binds_chosen_reading_and_clears_pending():
    from aughor.routers import investigations as R
    patch = R._apply_clarify_choice(_pending_state(), "Governed: refund_rate", "c_bind")
    assert patch["_clarify_pending"] is None
    assert patch["_ada_intake"]["metric_sql"] == _GOVERNED.sql
    assert patch["_ada_intake"]["metric_is_ratio"] is True


def test_resume_crystallizes_user_choice():
    from aughor.routers import investigations as R
    from aughor.semantic import ambiguity_ledger as L
    R._apply_clarify_choice(_pending_state(), "As I read the question", "c_cryst")
    res = L.list_resolutions("c_cryst")
    assert len(res) == 1
    assert res[0].resolution_source == "user"       # highest autonomous authority
    assert res[0].resolved_reading == "As I read the question"
    assert len(res[0].readings) == 2


def test_resume_defaults_to_first_reading_when_choice_unmatched():
    from aughor.routers import investigations as R
    patch = R._apply_clarify_choice(_pending_state(), "nonsense", "c_default")
    assert patch["_ada_intake"]["metric_sql"] == _GOVERNED.sql   # governed is first → the safe default


def test_resume_noop_without_pending_clarify():
    from aughor.routers import investigations as R
    assert R._apply_clarify_choice({"_ada_intake": {}}, "x", "c_none") == {}


# ── burn-down: a resolved reading is hard-bound on subsequent runs ──────────────────

def test_burndown_hard_binds_the_resolved_reading(monkeypatch):
    # After a prior clarify resolved to the parsed reading, a later run must BIND it and skip the ask.
    monkeypatch.setenv("AUGHOR_CLARIFY_GATE", "1")
    from aughor.org.context import current_org_id
    from aughor.semantic import ambiguity_ledger as L
    parsed = "COUNT(DISTINCT refund_id) / COUNT(DISTINCT order_id) * 100"
    L.save_resolution(L.AmbiguityResolution(
        connection_id="c_burndown", org_id=current_org_id() or "",
        dim_kind="AmbiIntent", dim_facet="aggregation",
        subject="definition of Fragrance refund rate",
        resolved_reading="As I read the question", resolved_sql=parsed, resolution_source="user"))

    it = _intake(metric_sql=_GOVERNED.sql)   # a later run happened to parse it the governed way
    conn = _ProbeConn({"refund_id": 20.2, "refunded_value": 18.8})
    note = I._apply_resolved_metric_reading(it, "c_burndown", conn)
    assert note and "previously-chosen" in note
    assert it.metric_sql == parsed           # hard-bound to the user's earlier choice, not governed


def test_burndown_noop_when_unresolved(monkeypatch):
    monkeypatch.setenv("AUGHOR_CLARIFY_GATE", "1")
    it = _intake()
    conn = _ProbeConn({"refund_id": 20.2})
    assert I._apply_resolved_metric_reading(it, "c_fresh_nothing", conn) is None


def test_burndown_noop_when_flag_off(monkeypatch):
    monkeypatch.delenv("AUGHOR_CLARIFY_GATE", raising=False)
    it = _intake()
    assert I._apply_resolved_metric_reading(it, "c_burndown", _ProbeConn({})) is None


# ── the interrupt/resume round-trip (the core contract) ────────────────────────────

def test_clarify_gate_interrupt_and_resume_roundtrip():
    # Prove the pause→resume mechanics with the REAL routing functions: a pending clarify routes to
    # the gate, the interrupt fires there, and after the choice is applied (pending cleared) the
    # passthrough resumes and route_after_intake picks the real branch. No LLM, in-memory checkpointer.
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, StateGraph

    g = StateGraph(dict)   # plain last-write channels; avoids runtime hint resolution
    g.add_node("ada_intake", lambda s: {"_clarify_pending": {"subject": "x"},
                                        "_ada_intake": {"cross_sectional": True}})
    g.add_node("clarify_gate", lambda s: {})
    g.add_node("ada_cross_section", lambda s: {"reached": "cross_section"})
    g.add_node("ada_baseline", lambda s: {"reached": "baseline"})
    g.add_edge(START, "ada_intake")
    g.add_conditional_edges("ada_intake", I.route_after_intake_clarify,
        {"clarify_gate": "clarify_gate", "ada_cross_section": "ada_cross_section",
         "ada_baseline": "ada_baseline"})
    g.add_conditional_edges("clarify_gate", I.route_after_intake,
        {"ada_cross_section": "ada_cross_section", "ada_baseline": "ada_baseline"})
    g.add_edge("ada_cross_section", END)
    g.add_edge("ada_baseline", END)
    app = g.compile(checkpointer=MemorySaver(), interrupt_before=["clarify_gate"])
    cfg = {"configurable": {"thread_id": "t1"}}

    ran_before = [k for ev in app.stream({}, config=cfg) for k in ev]
    assert app.get_state(cfg).next == ("clarify_gate",)      # paused AT the gate, before the fan-out
    assert "ada_cross_section" not in ran_before and "ada_baseline" not in ran_before   # scan not run

    app.update_state(cfg, {"_clarify_pending": None})        # the user's choice clears the pending clarify
    ran_after = [k for ev in app.stream(None, config=cfg) for k in ev]
    assert "ada_cross_section" in ran_after                  # resumed through the passthrough to the branch
    assert app.get_state(cfg).next == ()                     # and the run completed
