"""VA-2 — the four stops that make unbounded delegation depth safe to ship.

The user chose "everything, unbounded depth" over the narrower options. That choice is
only defensible if the runtime stops runs the topology no longer stops, so each test here
corresponds to a way an unbounded tree fails. A weakened limit must fail these, not just
run slower.
"""
from __future__ import annotations

import pytest

from aughor.agent.delegation import (
    DelegationContext,
    DelegationLimits,
    DelegationRefused,
)


def _ctx(**kw) -> DelegationContext:
    return DelegationContext(limits=DelegationLimits(**kw))


# ── 1 · cycles ────────────────────────────────────────────────────────────────────

def test_an_agent_already_on_the_path_is_refused():
    ctx = DelegationContext(agent_path=("analyst", "curator"))
    with pytest.raises(DelegationRefused) as e:
        ctx.check("analyst")
    assert e.value.code == "DELEGATION_CYCLE"
    assert "analyst -> curator -> analyst" in e.value.message, (
        "the refusal must NAME the loop; an agent that cannot see the cycle retries it")


def test_a_cycle_refusal_is_a_result_the_model_can_read_not_a_crash():
    """A refusal reaching the model as an exception strands the supervisor mid-turn with
    nothing to reason about. It must arrive as a normal tool result."""
    ctx = DelegationContext(agent_path=("a",))
    try:
        ctx.check("a")
    except DelegationRefused as exc:
        row = exc.as_result(agent_name="a")
    assert row["refused"] is True and row["code"] == "DELEGATION_CYCLE"
    assert row["bailed"] is False and isinstance(row["response"], str) and row["response"]


def test_delegating_to_a_sibling_not_on_the_path_is_allowed():
    """Unbounded means unbounded: breadth is not a cycle."""
    DelegationContext(agent_path=("supervisor",)).check("analyst")


# ── 2 · steps, counted per RUN ────────────────────────────────────────────────────

def test_the_step_budget_is_the_whole_run_not_one_level():
    """THE decisive property. A per-level bound (10 x targets) composes to thousands three
    levels down while every level still looks well behaved."""
    ctx = _ctx(max_run_steps=10)
    ctx.spend(steps=10)
    deep = ctx.child("a").child("b").child("c")
    with pytest.raises(DelegationRefused) as e:
        deep.check("d")
    assert e.value.code == "RUN_STEP_BUDGET"


def test_a_child_inherits_spend_so_a_subtree_cannot_reset_the_budget():
    ctx = _ctx(max_run_steps=100)
    ctx.spend(steps=99)
    assert ctx.child("x").steps_used == 99, (
        "a child starting from zero is exactly how an unbounded tree escapes a run ceiling")


# ── 3 · cost ──────────────────────────────────────────────────────────────────────

def test_the_run_cost_cap_stops_a_tree_that_is_merely_expensive():
    ctx = _ctx(max_cost_usd=1.0)
    ctx.spend(usd=1.0)
    with pytest.raises(DelegationRefused) as e:
        ctx.check("anyone")
    assert e.value.code == "RUN_COST_CAP"
    assert "partial" in e.value.message, "a capped run must say its answer is partial"


def test_no_cost_cap_means_governed_elsewhere_not_unlimited_here():
    _ctx(max_cost_usd=None).check("anyone")  # deferred to govern.usage_caps


# ── 4 · wall clock and depth ──────────────────────────────────────────────────────

def test_the_deadline_stops_a_tree_that_neither_cycles_nor_overspends():
    ctx = _ctx(deadline_s=0.0)
    with pytest.raises(DelegationRefused) as e:
        ctx.check("anyone")
    assert e.value.code == "RUN_DEADLINE"


def test_depth_is_a_runaway_backstop_and_says_so():
    ctx = DelegationContext(limits=DelegationLimits(max_depth=3),
                            agent_path=("a", "b", "c"))
    with pytest.raises(DelegationRefused) as e:
        ctx.check("d")
    assert e.value.code == "MAX_DEPTH"
    assert "backstop" in e.value.message.lower(), (
        "depth is not a design limit under this decision; the message must not imply it is")


# ── ordering, identity, and the span contract ─────────────────────────────────────

def test_an_unknown_target_is_named_before_any_budget_is_blamed():
    """A message that blames a budget for what was really a typo sends the reader hunting
    the wrong thing."""
    ctx = _ctx(max_run_steps=0)
    with pytest.raises(DelegationRefused) as e:
        ctx.check("ghost", known_ids={"analyst"})
    assert e.value.code == "UNKNOWN_TARGET"


def test_every_hop_stamps_depth_and_path_for_the_trace_view():
    attrs = DelegationContext(agent_path=("a", "b")).span_attributes()
    assert attrs["aughor.delegation.depth"] == 2
    assert attrs["aughor.delegation.path"] == "a/b"
    assert "aughor.delegation.steps_used" in attrs and "aughor.delegation.cost_usd" in attrs


def test_the_guard_can_actually_fire():
    """Every limit off should permit; this proves the tests above are not passing because
    `check` refuses everything."""
    DelegationContext().check("anyone")
