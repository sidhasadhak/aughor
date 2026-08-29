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


# ── the route reports a bad chain as something the caller can fix ────────────────

def test_a_bad_chain_is_a_422_with_a_readable_message_not_a_500(client):
    """Found live, not by a test: `exc.errors()` embeds the ORIGINAL exception object
    under `ctx` for a value_error — which is exactly what a `model_validator` raising
    ValueError produces. Starlette could not JSON-encode the 422 body, so the response
    became a 500 and a mistake the user could fix arrived as 'the server broke'.

    Also a check on the message itself: naming which step and which direction is the
    difference between fixing a name and fixing a mental model.
    """
    r = client.post("/automations", json={
        "name": "bad chain", "conn_id": "workspace",
        "conditions": [{"kind": "schedule", "config": {"cron": "* * * * *"}}],
        "effects": [
            {"kind": "slack_post", "alias": "a",
             "config": {"bot_id": "b", "channel": "C", "thread_ts": {"$from": "b.ts"}}},
            {"kind": "slack_post", "alias": "b", "config": {"bot_id": "b", "channel": "C"}},
        ],
    })
    assert r.status_code == 422, r.text
    assert "runs AFTER it" in r.text
    r.json()   # the body must be JSON — this is the assertion the 500 failed


def test_an_unknown_step_is_also_a_422(client):
    r = client.post("/automations", json={
        "name": "typo", "conn_id": "workspace",
        "conditions": [{"kind": "schedule", "config": {"cron": "* * * * *"}}],
        "effects": [{"kind": "slack_post", "alias": "a",
                     "config": {"bot_id": "b", "channel": "C",
                                "thread_ts": {"$from": "nope.ts"}}}],
    })
    assert r.status_code == 422 and "unknown step" in r.text


# ── VA-9b: an automation is an agent operating, not a cron with side effects ─────

def _agentic(*effects, agent="ag-analyst"):
    from aughor.automations.models import Automation, Condition
    return Automation(name="agentic", conn_id="conn-a", agent_id=agent, max_retries=0,
                      conditions=[Condition(kind="schedule", config={"cron": "* * * * *"})],
                      effects=list(effects))


def test_every_effect_inherits_the_automations_agent():
    """Measured before this wave: only `investigate` consulted an agent, so every other
    step ran as nobody. An automation that is one agent's work must act as that agent
    throughout, or 'agentic' is a label on the surface and not a property of the run."""
    from aughor.automations.engine import acting_agent
    a = _agentic(_effect(), _effect())
    assert [acting_agent(e, a) for e in a.effects] == ["ag-analyst", "ag-analyst"]


def test_a_step_may_delegate_to_its_own_agent():
    from aughor.automations.engine import acting_agent
    a = _agentic(_effect(), _effect(agent_id="ag-reviewer"))
    assert [acting_agent(e, a) for e in a.effects] == ["ag-analyst", "ag-reviewer"]


def test_a_governed_action_is_attributed_to_the_AGENT_not_the_mechanism():
    """`automation:<id>` names a cron. `agent:<id>` names an actor with a charter,
    instructions, bound documents and an owner — and parses as a principal ref, so RC-4's
    identity plane resolves it like any other."""
    from aughor.automations.engine import acting_agent_ref
    from aughor.identity import parse_ref
    a = _agentic(_effect())
    ref = acting_agent_ref(a.effects[0], a)
    assert ref == "agent:ag-analyst"
    ident = parse_ref(ref)
    assert ident is not None and ident.provider == "agent" and ident.external_id == "ag-analyst"


def test_an_unattributed_automation_still_records_the_mechanism():
    """Every automation written before this field has agent_id="" and must keep the
    attribution it already has — nothing already stored changes meaning."""
    from aughor.automations.engine import acting_agent_ref
    a = _automation(_effect())          # no agent
    assert acting_agent_ref(a.effects[0], a).startswith("automation:")


def test_the_run_and_every_outcome_record_who_acted():
    def _dispatch(effect, automation):
        return EffectOutcome(kind=effect.kind, target="t", status="executed", data={"ts": "1"})

    run = _run(_agentic(_effect(), _effect(agent_id="ag-reviewer")), _dispatch)
    assert run.agent_id == "ag-analyst", "the run says whose work it was"
    assert [o.agent_id for o in run.effects] == ["ag-analyst", "ag-reviewer"], \
        "per STEP, because a chain may delegate and a run-level field could not say which"


def test_a_gated_run_still_records_the_agent():
    """A run that did nothing still did nothing on someone's behalf; an agent's history
    is incomplete if it holds only the ticks that acted."""
    from aughor.automations.engine import run_automation
    a = _agentic(_effect())
    a = a.model_copy(update={"enabled": False})
    run = run_automation(a, persist=False, dispatch=lambda e, au: None,
                         sleeper=lambda _s: None, rng=lambda: 0.0)
    assert run.outcome == "gated" and run.agent_id == "ag-analyst"


def test_the_graph_says_which_agent_acts_and_which_step_delegates():
    from aughor.automations.graph import build_graph
    g = build_graph(_agentic(_effect(), _effect(agent_id="ag-reviewer")))
    steps = [n for n in g["nodes"] if n["type"] == "effect"]
    assert g["agent_id"] == "ag-analyst"
    assert steps[0]["agent_id"] == "ag-analyst" and steps[0]["delegated"] is False
    assert steps[1]["agent_id"] == "ag-reviewer" and steps[1]["delegated"] is True
