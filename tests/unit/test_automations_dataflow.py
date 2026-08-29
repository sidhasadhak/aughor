"""VA-4a — one effect's output becomes another's input.

Before this, `engine.py` ran effects as a LIST COMPREHENSION: every effect received only
`(effect, automation, dispatch)`, `EffectOutcome` carried no data, and params were
literals. Three gaps, one missing idea — a chain. A workflow canvas built on that would
have drawn arrows the engine could not follow.

The properties locked here, each one something a plausible implementation gets wrong:

* **Merged-data, not just previous-step.** Step 3 can read step 1. A chain that only
  passes N→N+1 cannot express a fan-in, which is most of what people draw.
* **A step whose upstream failed is SKIPPED, never run with a hole.** These steps send
  messages and write to systems; a missing channel is not a value to default.
* **Only an EXECUTED step publishes.** A failed step contributing an empty dict would let
  a downstream binding resolve to nothing and run anyway — the silent hole, wearing a
  different hat.
* **An unsatisfiable chain is refused at CONSTRUCTION**, not discovered on a schedule.
* **A forward reference is a distinct error from an unknown step** — one is a typo, the
  other is an impossible order.
"""
from __future__ import annotations

import pytest

from aughor.automations.dataflow import (UnresolvedBinding, alias_for, collect_refs,
                                         is_binding, resolve)
from aughor.automations.models import Automation, Condition, Effect, EffectOutcome


def _effect(alias="", **config) -> Effect:
    base = {"bot_id": "sb_1", "channel": "C1"}
    base.update(config)
    return Effect(kind="slack_post", alias=alias, config=base)


def _automation(*effects) -> Automation:
    return Automation(
        name="chain", conn_id="conn-a",
        conditions=[Condition(kind="schedule", config={"cron": "0 9 * * 1"})],
        effects=list(effects),
        # `failed` is retriable, so without this a single failing step dispatches
        # several times and a count of dispatches reads as though the DEPENDENT step
        # had run. The retry policy has its own tests; these assert the chain.
        max_retries=0,
    )


# ── the binding marker ───────────────────────────────────────────────────────────

def test_only_a_lone_from_key_is_a_binding():
    assert is_binding({"$from": "step1.ts"})
    assert not is_binding({"$from": "step1.ts", "other": 1}), "not a lone marker"
    assert not is_binding("$from")
    assert not is_binding({"text": "mentions $from in prose"}), "a value, not a reference"


def test_refs_are_collected_at_any_depth():
    """The canvas and the engine must derive the SAME edges — two readers deriving the
    graph differently is how a picture and its run come to disagree."""
    params = {"a": {"$from": "step1.ts"},
              "b": [1, {"c": {"$from": "step2.channel"}}],
              "d": "literal"}
    assert sorted(collect_refs(params)) == ["step1.ts", "step2.channel"]


# ── resolution ───────────────────────────────────────────────────────────────────

def test_a_reference_resolves_to_the_upstream_value():
    ctx = {"step1": {"ts": "1788.0001", "channel": "C9"}}
    out = resolve({"thread_ts": {"$from": "step1.ts"}, "channel": "C1"}, ctx)
    assert out == {"thread_ts": "1788.0001", "channel": "C1"}


def test_merged_data_step_three_can_read_step_one():
    """Not just N→N+1. A chain that only passes the previous step cannot express a
    fan-in, which is most of what anyone actually draws."""
    ctx = {"step1": {"answer": "revenue fell"}, "step2": {"ts": "1788.0001"}}
    out = resolve({"text": {"$from": "step1.answer"},
                   "thread_ts": {"$from": "step2.ts"}}, ctx)
    assert out == {"text": "revenue fell", "thread_ts": "1788.0001"}


def test_nested_and_list_bindings_resolve():
    ctx = {"step1": {"ts": "T"}}
    assert resolve({"a": [{"b": {"$from": "step1.ts"}}]}, ctx) == {"a": [{"b": "T"}]}


def test_a_missing_step_raises_rather_than_defaulting():
    """Substituting a default would let a step run with a silently wrong value."""
    with pytest.raises(UnresolvedBinding, match="produced nothing"):
        resolve({"x": {"$from": "step9.ts"}}, {})


def test_a_missing_key_names_what_the_step_DID_produce():
    with pytest.raises(UnresolvedBinding, match="channel"):
        resolve({"x": {"$from": "step1.nope"}}, {"step1": {"ts": "T", "channel": "C"}})


# ── naming ───────────────────────────────────────────────────────────────────────

def test_steps_are_positional_by_default_so_old_automations_gain_references():
    assert alias_for(_effect(), 0) == "step1"
    assert alias_for(_effect(), 2) == "step3"
    assert alias_for(_effect(alias="post"), 0) == "post"


# ── construction-time validation ─────────────────────────────────────────────────

def test_a_sound_chain_is_accepted():
    a = _automation(_effect(), _effect(thread_ts={"$from": "step1.ts"}))
    assert len(a.effects) == 2


def test_an_unknown_step_is_refused_when_the_automation_is_SAVED():
    with pytest.raises(ValueError, match="unknown step"):
        _automation(_effect(), _effect(thread_ts={"$from": "nope.ts"}))


def test_a_forward_reference_is_a_DIFFERENT_error_from_an_unknown_step():
    """One is a typo; the other is an impossible order. Saying which is the difference
    between fixing a name and fixing a mental model."""
    with pytest.raises(ValueError, match="runs AFTER it"):
        _automation(_effect(thread_ts={"$from": "step2.ts"}), _effect())


def test_a_self_reference_is_refused():
    with pytest.raises(ValueError, match="refers to itself"):
        _automation(_effect(thread_ts={"$from": "step1.ts"}))


def test_a_named_step_can_be_referenced_by_name():
    a = _automation(_effect(alias="open"), _effect(thread_ts={"$from": "open.ts"}))
    assert a.effects[1].config["thread_ts"] == {"$from": "open.ts"}


# ── the engine chain ─────────────────────────────────────────────────────────────

def _run(automation, dispatch):
    """Drive the REAL engine, with the clock stubbed.

    `sleeper` is injected because a `failed` outcome is retriable and the backoff sleeps
    for real — this suite spent 89 seconds waiting before that was passed in. The retry
    policy is exercised by its own tests; what these assert is the chain.
    """
    from aughor.automations.engine import run_automation
    return run_automation(automation, dispatch=dispatch, persist=False,
                          probe=lambda *a, **k: True,
                          sleeper=lambda _s: None, rng=lambda: 0.0)


def test_a_downstream_step_receives_the_upstream_value(monkeypatch):
    seen: list[dict] = []

    def _dispatch(effect, automation):
        seen.append(dict(effect.config))
        return EffectOutcome(kind=effect.kind, target="t", status="executed",
                             data={"ts": "1788.0001"})

    _run(_automation(_effect(), _effect(thread_ts={"$from": "step1.ts"})), _dispatch)
    assert seen[1]["thread_ts"] == "1788.0001", "step 2 must receive step 1's output"


def test_a_step_whose_upstream_FAILED_is_skipped_not_run_with_a_hole():
    ran: list[str] = []

    def _dispatch(effect, automation):
        ran.append(effect.config.get("channel"))
        return EffectOutcome(kind=effect.kind, target="t", status="failed")

    run = _run(_automation(_effect(channel="first"),
                           _effect(channel="second", thread_ts={"$from": "step1.ts"})),
               _dispatch)
    assert ran == ["first"], "the dependent step must NOT be dispatched"
    assert run.effects[1].status == "skipped"
    assert "upstream data unavailable" in run.effects[1].message


def test_only_an_executed_step_publishes():
    """A failed step contributing an empty dict would let a downstream binding resolve to
    nothing and run anyway — the silent hole wearing a different hat."""
    def _dispatch(effect, automation):
        return EffectOutcome(kind=effect.kind, target="t", status="uncertain",
                             data={"ts": "should-not-be-published"})

    run = _run(_automation(_effect(), _effect(thread_ts={"$from": "step1.ts"})), _dispatch)
    assert run.effects[1].status == "skipped"


def test_an_independent_step_still_runs_after_a_failure():
    """Skipping is for DEPENDENTS only. An unrelated step must not be collateral."""
    ran: list[str] = []

    def _dispatch(effect, automation):
        ran.append(effect.config.get("channel", ""))
        return EffectOutcome(kind=effect.kind, target="t",
                             status="failed" if effect.config.get("channel") == "C1"
                             else "executed")

    _run(_automation(_effect(channel="C1"), _effect(channel="C2")), _dispatch)
    assert ran == ["C1", "C2"], "an independent step is not collateral damage"
