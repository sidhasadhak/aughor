"""P3 editable plan gate — graph wiring + plan-edit filtering (no LLM)."""
from __future__ import annotations

import pytest

from aughor.routers.investigations import _filter_kept_subquestions


def test_filter_keeps_selected_indices_in_order():
    subqs = ["Q0", "Q1", "Q2", "Q3"]
    assert _filter_kept_subquestions(subqs, [0, 2]) == ["Q0", "Q2"]
    assert _filter_kept_subquestions(subqs, [3, 1]) == ["Q1", "Q3"]  # order preserved, not selection order


def test_filter_ignores_out_of_range_indices():
    assert _filter_kept_subquestions(["Q0", "Q1"], [0, 9]) == ["Q0"]


def test_filter_empty_selection_yields_empty():
    # caller treats empty as "no valid edit" and won't wipe the plan
    assert _filter_kept_subquestions(["Q0", "Q1"], []) == []


def _graph(**kw):
    from aughor.db.connection import open_connection_for
    from aughor.agent.graph import build_graph_generic
    try:
        db = open_connection_for("samples")
    except Exception as e:  # pragma: no cover
        pytest.skip(f"samples connection unavailable: {e}")
    try:
        return build_graph_generic(db, **kw)
    finally:
        db.close()


def _interrupts(g) -> list:
    return list(getattr(g, "interrupt_before_nodes", getattr(g, "interrupt_before", [])) or [])


def test_plan_gate_node_always_present():
    g = _graph(plan_gate=False)
    assert "plan_gate" in set(g.get_graph().nodes.keys())


def test_plan_gate_arms_interrupt_only_when_on():
    assert "plan_gate" in _interrupts(_graph(plan_gate=True))
    assert "plan_gate" not in _interrupts(_graph(plan_gate=False))


def test_plan_gate_coexists_with_hitl():
    ints = _interrupts(_graph(hitl=True, plan_gate=True))
    assert "plan_gate" in ints and "ada_synthesize" in ints
