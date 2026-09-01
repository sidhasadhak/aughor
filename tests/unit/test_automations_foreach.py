"""W2 — `for_each`: a step runs once per item of a list.

The engine ran a strictly sequential list — one step, one dispatch — so "post a summary
per region" was written as three near-identical steps or was not automated. W2 binds one
step to a list and fans it out.

Measured before writing it, and it moved the scope: **nothing in this plane publishes a
list.** `investigate` publishes two strings, `slack_post` two strings, and
`notify`/`brief`/`monitor`/`agent_alert` publish nothing at all — only the declared-action
kind has an OPEN outcome shape. So a fan-out source is a literal list or a binding onto
that open kind, and fanning over a closed-set producer is refused at SAVE rather than
discovered as "cannot iterate a str" on the morning it runs.

The properties locked here, each one something a plausible implementation gets wrong:

* **A string is not a list.** `for_each: "EMEA"` would send four messages, one per
  character. Refused, and refused as `invalid_params` — the step's own config is wrong,
  which is a different thing from an upstream that is absent.
* **The cap REFUSES, it does not truncate.** Posting the first 50 of 500 and dropping the
  rest silently is the failure a cap exists to prevent.
* **The guard runs PER ITEM.** A guard evaluated once would make "post the regions that
  moved" all-or-nothing, which is the opposite of a filter.
* **A fan source is dataflow.** The same `effect_refs` feeds validation, the engine's
  await and the canvas, so a step feeding a fan-out is *waited for* — the subtlest bug
  available here, and the one W1 already paid for once with its guard.
* **A fanned step publishes only `count`.** There are N per-item values and
  `{"$from": "step2.ts"}` could only mean one of them; refusing at save beats silently
  picking the last.
* **An empty list is a SKIP, and a skip does not fire the fallback.** A quiet morning is
  the automation working, not the automation broken.
* **The iteration is STRUCTURED, never a message prefix.** `graph.py` decides a step was
  held by matching `message` against `GUARD_SKIP`; a "[2/3] " prefix would have made every
  guarded iteration read as an ordinary skip — a guard going blind because its matching
  key stopped matching.
"""
from __future__ import annotations

import pytest

from aughor.automations.dataflow import (
    FAN_EMPTY_SKIP, GUARD_SKIP, MAX_FAN_OUT, effect_refs, validate_chain,
)
from aughor.automations.models import (
    Automation, Condition, Effect, EffectOutcome, ForEach,
)

AWAIT_KEY = "_await_result"


def _post(alias="", source=None, when=None, **config) -> Effect:
    base = {"bot_id": "sb_1", "channel": "C1"}
    base.update(config)
    return Effect(kind="slack_post", alias=alias, config=base,
                  for_each=ForEach(source=source) if source is not None else None,
                  when=when or [])


def _action(alias="rows") -> Effect:
    """An upstream whose published shape is OPEN — the only kind a fan-out may bind to
    today, because it is the only one whose outcome keys this module cannot enumerate."""
    return Effect(kind="kinetic_action", alias=alias, config={"action_id": "a1"})


def _automation(*effects, fallback=None) -> Automation:
    return Automation(
        name="fanned", conn_id="conn-a",
        conditions=[Condition(kind="schedule", config={"cron": "0 9 * * 1"})],
        effects=list(effects), fallback_effect=fallback, max_retries=0,
    )


def _run(automation, dispatch=None, **kw):
    from aughor.automations.engine import run_automation
    return run_automation(automation, dispatch=dispatch, persist=False,
                          probe=lambda *a, **k: True,
                          sleeper=lambda _s: None, rng=lambda: 0.0, **kw)


def _records(**data):
    """A dispatch that records each config it was handed and publishes `data`."""
    seen: list[dict] = []

    def _dispatch(effect, automation):
        seen.append(dict(effect.config))
        return EffectOutcome(kind=effect.kind, target="t", status="executed", data=dict(data))
    return seen, _dispatch


# ── one step, N dispatches ───────────────────────────────────────────────────────

def test_fans_out_once_per_item_in_order():
    seen, dispatch = _records()
    run = _run(_automation(_post(source=["EMEA", "NA", "APAC"],
                                 message={"$from": "item.value"})), dispatch)
    assert [c["message"] for c in seen] == ["EMEA", "NA", "APAC"]
    assert len(run.effects) == 3
    assert all(o.status == "executed" for o in run.effects)


def test_a_dict_item_is_read_field_wise():
    seen, dispatch = _records()
    _run(_automation(_post(source=[{"region": "EMEA", "room": "C-emea"},
                                   {"region": "NA", "room": "C-na"}],
                           channel={"$from": "item.room"},
                           message={"$from": "item.region"})), dispatch)
    assert [(c["channel"], c["message"]) for c in seen] == [("C-emea", "EMEA"), ("C-na", "NA")]


def test_each_iteration_numbers_itself_structurally():
    """`fan_index`/`fan_count` are fields, not a message prefix — see the module docstring."""
    _seen, dispatch = _records()
    run = _run(_automation(_post(source=["a", "b"], message={"$from": "item.value"})), dispatch)
    assert [(o.fan_index, o.fan_count) for o in run.effects] == [(1, 2), (2, 2)]


def test_an_unfanned_step_is_unchanged():
    """The single dispatch every automation written before W2 performs, byte for byte."""
    seen, dispatch = _records()
    run = _run(_automation(_post(message="hello")), dispatch)
    assert [c["message"] for c in seen] == ["hello"]
    assert [(o.fan_index, o.fan_count) for o in run.effects] == [(0, 0)]


# ── what a fan-out refuses ───────────────────────────────────────────────────────

def test_a_string_source_is_refused_not_iterated_per_character():
    with pytest.raises(ValueError, match="per character"):
        ForEach(source="EMEA")


def test_a_string_that_arrives_at_RUN_time_is_refused_too():
    """The literal is refused at save; a BOUND source is only known when it resolves, and
    every producer in this plane publishes strings. `invalid_params`, not `skipped`: the
    upstream was there, the step's use of it is wrong."""
    def _dispatch(effect, automation):
        return EffectOutcome(kind=effect.kind, target="t", status="executed",
                             data={"rows": "EMEA"})
    run = _run(_automation(_action(), _post(source={"$from": "rows.rows"},
                                            message={"$from": "item.value"})), _dispatch)
    fanned = run.effects[-1]
    assert fanned.status == "invalid_params"
    assert "per character" in fanned.message


def test_over_the_cap_is_refused_never_truncated():
    with pytest.raises(ValueError, match=f"{MAX_FAN_OUT}-item cap"):
        ForEach(source=[str(n) for n in range(MAX_FAN_OUT + 1)])


def test_a_runtime_list_over_the_cap_refuses_the_step_and_sends_nothing():
    seen, inner = _records()

    def _dispatch(effect, automation):
        if effect.kind == "kinetic_action":
            return EffectOutcome(kind=effect.kind, target="t", status="executed",
                                 data={"rows": list(range(MAX_FAN_OUT + 1))})
        return inner(effect, automation)

    run = _run(_automation(_action(), _post(source={"$from": "rows.rows"},
                                            message={"$from": "item.value"})), _dispatch)
    assert run.effects[-1].status == "invalid_params"
    assert seen == []          # nothing was sent, not even the first MAX_FAN_OUT of them


def test_an_unresolvable_source_skips_the_step():
    """Same reading as an unresolvable param: the upstream this step needs is not there."""
    def _dispatch(effect, automation):
        return EffectOutcome(kind=effect.kind, target="t", status="failed", message="no")
    run = _run(_automation(_action(), _post(source={"$from": "rows.rows"},
                                            message={"$from": "item.value"})), _dispatch)
    assert run.effects[-1].status == "skipped"
    assert "upstream data unavailable" in run.effects[-1].message


# ── the empty list ───────────────────────────────────────────────────────────────

def test_an_empty_list_skips_the_step():
    seen, dispatch = _records()
    run = _run(_automation(_post(source=[], message={"$from": "item.value"})), dispatch)
    assert seen == []
    assert [(o.status, o.message) for o in run.effects] == [("skipped", FAN_EMPTY_SKIP)]


def test_an_empty_fan_out_does_not_fire_the_fallback():
    """W1's lesson, carried forward: "nothing was meant to run" is not "everything failed",
    and the fallback exists to page a human that the automation itself is broken."""
    seen, dispatch = _records()
    run = _run(_automation(_post(source=[], message={"$from": "item.value"}),
                           fallback=_post(alias="fb", message="broken")), dispatch)
    assert run.fallback_used is False
    assert seen == []


# ── the guard runs per item ──────────────────────────────────────────────────────

def test_the_guard_filters_the_list_item_by_item():
    seen, dispatch = _records()
    run = _run(_automation(_post(
        source=[{"region": "EMEA", "moved": True},
                {"region": "NA", "moved": False},
                {"region": "APAC", "moved": True}],
        message={"$from": "item.region"},
        when=[{"left": {"$from": "item.moved"}, "op": "truthy"}])), dispatch)
    assert [c["message"] for c in seen] == ["EMEA", "APAC"]
    held = [o for o in run.effects if o.status == "skipped"]
    assert len(held) == 1
    assert held[0].fan_index == 2


def test_a_held_iteration_still_reads_as_held():
    """`graph.py` matches `message` against GUARD_SKIP to draw a step as held. An
    iteration marker in the message would have blinded exactly that reader."""
    _seen, dispatch = _records()
    run = _run(_automation(_post(source=[{"v": ""}], message="x",
                                 when=[{"left": {"$from": "item.v"}, "op": "truthy"}])), dispatch)
    assert run.effects[0].message.startswith(GUARD_SKIP)


# ── the fan source is dataflow ───────────────────────────────────────────────────

def test_the_source_is_a_chain_reference_like_any_other():
    assert effect_refs(_post(source={"$from": "rows.items"})) == ["rows.items"]


def test_the_item_is_not_a_chain_reference():
    """`item.*` is resolved per iteration against the item, so it must not read as a step
    — three readers walk `effect_refs`, and the one that saw `item` would report an
    unknown step nobody wrote."""
    assert effect_refs(_post(source=["a"], message={"$from": "item.value"})) == []


def test_a_step_feeding_a_fan_out_is_awaited():
    """VA-13's rule, one field over: only a step somebody waits on should be waited FOR,
    and a fan-out source is somebody waiting."""
    seen: list[dict] = []

    def _dispatch(effect, automation):
        seen.append(dict(effect.config))
        return EffectOutcome(kind=effect.kind, target="t", status="executed",
                             data={"items": ["a"]})
    _run(_automation(_action(), _post(source={"$from": "rows.items"},
                                      message={"$from": "item.value"})), _dispatch)
    assert seen[0].get(AWAIT_KEY) is True


# ── what a fanned step publishes ─────────────────────────────────────────────────

def test_a_fanned_step_publishes_its_count():
    published: list[str] = []

    def _dispatch(effect, automation):
        if effect.kind == "notify":
            published.append(effect.config["message"])
            return EffectOutcome(kind=effect.kind, target="t", status="executed")
        return EffectOutcome(kind=effect.kind, target="t", status="executed", data={"ts": "1"})

    _run(_automation(
        _post(alias="posts", source=["a", "b"], message={"$from": "item.value"}),
        Effect(kind="notify", alias="tell", config={"trigger_id": "t1",
                                                    "message": {"$from": "posts.count"}}),
    ), _dispatch)
    assert published == [2]


def test_only_executed_iterations_are_counted():
    def _dispatch(effect, automation):
        if effect.kind == "notify":
            return EffectOutcome(kind=effect.kind, target=str(effect.config["message"]),
                                 status="executed")
        ok = effect.config["message"] == "a"
        return EffectOutcome(kind=effect.kind, target="t",
                             status="executed" if ok else "failed", data={"ts": "1"})

    run = _run(_automation(
        _post(alias="posts", source=["a", "b"], message={"$from": "item.value"}),
        Effect(kind="notify", alias="tell", config={"trigger_id": "t1",
                                                    "message": {"$from": "posts.count"}}),
    ), _dispatch)
    assert run.effects[-1].target == "1"


# ── save-time refusals ───────────────────────────────────────────────────────────

def test_item_on_an_unfanned_step_is_refused_at_save():
    err = validate_chain([_post(message={"$from": "item.value"})])
    assert err and "does not run for each item" in err


def test_fanning_over_a_closed_producer_is_refused_at_save():
    """`slack_post` publishes two strings. Neither is a list, and that is knowable now.

    DS-11 and DS-12 both taught this check that a closed set may CONTAIN a list, from
    opposite sides — per operation and per kind. The sentence is unchanged for a producer
    that publishes none: `slack_post` publishes two strings, so "none of it is a list"
    remains exactly right, and the refusal still names the step and the reference.
    """
    err = validate_chain([_post(alias="first"),
                          _post(alias="second", source={"$from": "first.ts"})])
    assert err
    assert "none of it is a list" in err
    assert "second" in err and "first.ts" in err


def test_fanning_over_a_DECLARED_list_is_accepted(monkeypatch):
    """DS-12 — §3.2's honest limit, closed.

    "Nothing in this plane publishes a list" was an inventory, not a policy, and
    `validate_chain` encoded it by refusing every closed published set as a fan source.
    A trusted query publishes rows, so the list-ness is declared beside the keys and the
    refusal consults it — without reopening the set, which would have given up the
    save-time check on unknown keys to gain one list.
    """
    q = Effect(kind="trusted_query", alias="accounts", config={"query_id": "tq_1"})
    fan = _post(alias="tell", source={"$from": "accounts.rows"},
                message={"$from": "item.name"})
    assert validate_chain([q, fan]) is None


def test_fanning_over_a_NON_list_key_of_the_same_step_is_still_refused():
    """The declaration is per KEY, not per kind — `count` sits beside `rows` in the same
    published set and iterating it would send one message per digit. The refusal points
    at the key that would have worked, which is the whole reason to name it."""
    q = Effect(kind="trusted_query", alias="accounts", config={"query_id": "tq_1"})
    err = validate_chain([q, _post(alias="tell", source={"$from": "accounts.count"})])
    assert err and "fans out over 'accounts.count'" in err
    # The message names the key that WOULD have worked — unhelpful advice otherwise, to
    # someone one key away from the right answer.
    assert "only rows is a list" in err


def test_binding_to_a_fanned_step_per_item_value_is_refused_at_save():
    err = validate_chain([
        _post(alias="posts", source=["a"], message={"$from": "item.value"}),
        Effect(kind="notify", alias="tell",
               config={"trigger_id": "t1", "message": {"$from": "posts.ts"}}),
    ])
    assert err and "once per item" in err


def test_binding_to_a_fanned_step_count_is_sound():
    assert validate_chain([
        _post(alias="posts", source=["a"], message={"$from": "item.value"}),
        Effect(kind="notify", alias="tell",
               config={"trigger_id": "t1", "message": {"$from": "posts.count"}}),
    ]) is None


def test_an_unknown_step_in_a_fan_source_is_still_refused():
    err = validate_chain([_post(source={"$from": "nowhere.rows"})])
    assert err and "unknown step 'nowhere'" in err


# ── the preview (B2) ─────────────────────────────────────────────────────────────

def test_a_dry_run_walks_a_literal_list_for_real():
    """The items are known now, so "would post 3 messages" is the answer a preview exists
    to give — and nothing is dispatched."""
    seen, dispatch = _records()
    run = _run(_automation(_post(source=["EMEA", "NA", "APAC"],
                                 message={"$from": "item.value"})),
               dispatch, dry_run=True)
    assert seen == []                      # `dispatch` is overridden by the preview
    assert len(run.effects) == 3
    assert all(o.status == "executed" for o in run.effects)


def test_a_dry_run_of_a_bound_source_previews_one_iteration():
    """A preview's context holds sample strings, never tomorrow's list — resolving the
    binding would report a sound fan-out as `invalid_params`."""
    run = _run(_automation(_action(), _post(source={"$from": "rows.items"},
                                            message={"$from": "item.value"})),
               dry_run=True)
    fanned = [o for o in run.effects if o.fan_count]
    assert len(fanned) == 1
    assert "once per item at run time" in fanned[0].message


# ── the canvas ───────────────────────────────────────────────────────────────────

def test_a_step_after_a_fan_out_shows_its_own_status():
    """The bug this grouping exists to prevent. `build_graph` read `outcomes[i]` because
    the engine appended exactly one outcome per effect — W2 appends one per ITEM, so
    without grouping every node after a fan-out shows another step's status. A picture
    that is WRONG is worse than one that is missing."""
    from aughor.automations.graph import build_graph

    def _dispatch(effect, automation):
        ok = effect.kind != "notify"
        return EffectOutcome(kind=effect.kind, target="t",
                             status="executed" if ok else "failed",
                             message="" if ok else "the last step broke",
                             data={"ts": "1"})

    run = _run(_automation(
        _post(alias="posts", source=["a", "b", "c"], message={"$from": "item.value"}),
        Effect(kind="notify", alias="tell", config={"trigger_id": "t1", "message": "done"}),
    ), _dispatch)
    nodes = {n["id"]: n for n in build_graph(_automation(
        _post(alias="posts", source=["a", "b", "c"], message={"$from": "item.value"}),
        Effect(kind="notify", alias="tell", config={"trigger_id": "t1", "message": "done"}),
    ), run)["nodes"] if n["type"] == "effect"}
    assert nodes["posts"]["status"] == "executed"
    assert nodes["tell"]["status"] == "failed"
    assert nodes["tell"]["message"] == "the last step broke"


def test_the_structure_graph_says_a_step_runs_per_item():
    from aughor.automations.graph import build_graph
    graph = build_graph(_automation(_post(source=["EMEA", "NA"],
                                          message={"$from": "item.value"})))
    node = [n for n in graph["nodes"] if n["type"] == "effect"][0]
    assert node["for_each"] == "EMEA, NA"


def test_a_bound_fan_out_is_labelled_by_its_reference():
    from aughor.automations.graph import build_graph
    graph = build_graph(_automation(_action(), _post(source={"$from": "rows.items"},
                                                     message={"$from": "item.value"})))
    node = [n for n in graph["nodes"] if n["id"] == "step2"][0]
    assert node["for_each"] == "rows.items"


def test_a_partly_held_fan_out_reads_as_how_many_ran():
    from aughor.automations.graph import build_graph
    _seen, dispatch = _records(ts="1")
    effects = [_post(alias="posts",
                     source=[{"v": "a"}, {"v": ""}, {"v": "c"}],
                     message={"$from": "item.v"},
                     when=[{"left": {"$from": "item.v"}, "op": "truthy"}])]
    run = _run(_automation(*effects), dispatch)
    node = [n for n in build_graph(_automation(*effects), run)["nodes"]
            if n["id"] == "posts"][0]
    assert node["fan"] == {"count": 3, "executed": 2, "skipped": 1}
    assert node["message"].startswith("2 of 3 ran")
    assert node["produced"] == ["count"]


def test_one_failed_iteration_makes_the_step_read_as_failed():
    """"2 of 3 posted" under a green node is how a partial send reads as a whole one."""
    from aughor.automations.graph import build_graph

    def _dispatch(effect, automation):
        ok = effect.config["message"] != "b"
        return EffectOutcome(kind=effect.kind, target="t",
                             status="executed" if ok else "failed", data={"ts": "1"})
    effects = [_post(alias="posts", source=["a", "b", "c"],
                     message={"$from": "item.value"})]
    run = _run(_automation(*effects), _dispatch)
    node = [n for n in build_graph(_automation(*effects), run)["nodes"]
            if n["id"] == "posts"][0]
    assert node["status"] == "failed"
    assert node["produced"] == []
