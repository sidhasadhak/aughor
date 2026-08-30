"""W1 — `when`: a step runs only if its guard holds.

Before this, the engine could skip a step for exactly one reason: an ABSENCE, a binding
that would not resolve. "Post the report only if there is something worth posting" was
not expressible, so a daily chain either sent an empty message every morning or was not
automated at all.

The properties locked here, each one something a plausible implementation gets wrong:

* **A guard is evaluated BEFORE the dispatch.** A step held back costs nothing — no
  request, no token, no send. A guard that filtered the *outcome* would have paid for
  the work it was written to avoid.
* **A guard's references are dataflow.** The same `effect_refs` feeds validation, the
  engine's await, and the canvas — so an `investigate` consumed only by a downstream
  guard is *waited for*. Missing that is the subtlest bug available here: the step would
  hand the guard the job id it returns when nobody waits, a non-empty string, and
  `is set` would hold every single morning.
* **An unevaluable comparison HOLDS the step and says so.** `"n/a" > 5` is neither true
  nor false; treating it as false stops a chain silently and as true runs the step the
  guard exists to prevent.
* **A guarded-off run does not fire the fallback.** "Nothing was meant to run" is not
  "everything failed" — the fallback pages a human to say the automation itself broke.
* **The skip message names the CLAUSE, never the value it read.** A guard may read a
  message body or a thread id, and this string is written into run history and drawn on
  the canvas.
"""
from __future__ import annotations

import pytest

from aughor.automations.dataflow import GUARD_SKIP, effect_refs, evaluate_guard
from aughor.automations.models import Automation, Condition, Effect, EffectOutcome


def _effect(alias="", when=None, logic="all", **config) -> Effect:
    base = {"bot_id": "sb_1", "channel": "C1"}
    base.update(config)
    return Effect(kind="slack_post", alias=alias, config=base,
                  when=when or [], when_logic=logic)


def _investigate(alias="report") -> Effect:
    """An upstream that PUBLISHES `answer` — `slack_post` publishes `ts`/`channel`, and
    B1's key check refuses a guard onto a key its producer cannot publish (which is how
    this fixture was caught the first time it lied)."""
    return Effect(kind="investigate", alias=alias, config={"question": "how were sales?"})


def _automation(*effects, fallback=None) -> Automation:
    return Automation(
        name="guarded", conn_id="conn-a",
        conditions=[Condition(kind="schedule", config={"cron": "0 9 * * 1"})],
        effects=list(effects), fallback_effect=fallback, max_retries=0,
    )


def _run(automation, dispatch):
    from aughor.automations.engine import run_automation
    return run_automation(automation, dispatch=dispatch, persist=False,
                          probe=lambda *a, **k: True,
                          sleeper=lambda _s: None, rng=lambda: 0.0)


def _publishes(**data):
    """A dispatch that records what it was asked to run and publishes `data`."""
    seen: list[dict] = []

    def _dispatch(effect, automation):
        seen.append(dict(effect.config))
        return EffectOutcome(kind=effect.kind, target="t", status="executed", data=dict(data))
    return seen, _dispatch


# ── the guard decides whether the step runs at all ───────────────────────────────

def test_no_guard_runs_exactly_as_before():
    """Every automation written before W1 is byte-identical: an empty guard is silent."""
    seen, dispatch = _publishes()
    run = _run(_automation(_effect()), dispatch)
    assert len(seen) == 1 and run.effects[0].status == "executed"


def test_a_guard_that_holds_lets_the_step_run():
    seen, dispatch = _publishes(answer="Sales fell 12%")
    run = _run(_automation(
        _investigate(),
        _effect(when=[{"left": {"$from": "report.answer"}, "op": "truthy"}])), dispatch)
    assert len(seen) == 2, "the guard held; the step must run"
    assert run.effects[1].status == "executed"


def test_a_guard_that_does_not_hold_skips_BEFORE_the_dispatch():
    """The whole point: a held-back step costs nothing — no request, no token, no send."""
    seen, dispatch = _publishes(answer="")
    run = _run(_automation(
        _investigate(),
        _effect(when=[{"left": {"$from": "report.answer"}, "op": "truthy"}])), dispatch)
    assert len(seen) == 1, "the guarded step must never reach the dispatcher"
    assert run.effects[1].status == "skipped"
    assert run.effects[1].message == f"{GUARD_SKIP}: report.answer is set"


def test_the_skip_message_names_the_clause_and_never_the_value():
    """A guard may read a message body or a credential-shaped value, and this string is
    written into run history and drawn on the canvas."""
    seen, dispatch = _publishes(answer="a-credential-shaped-answer")
    run = _run(_automation(
        _investigate(),
        _effect(when=[{"left": {"$from": "report.answer"}, "op": "falsy"}])), dispatch)
    assert run.effects[1].status == "skipped"
    assert "a-credential-shaped-answer" not in run.effects[1].message


# ── a guard is dataflow, and every reader must agree ─────────────────────────────

def test_effect_refs_sees_both_params_and_the_guard():
    e = _effect(thread_ts={"$from": "step1.ts"},
                when=[{"left": {"$from": "step2.answer"}, "op": "truthy"}])
    assert effect_refs(e) == ["step1.ts", "step2.answer"]


def test_a_step_consumed_ONLY_by_a_downstream_guard_is_still_awaited():
    """The subtlest bug in this wave. `investigate` returns a JOB ID when nobody waits
    for it — a non-empty string — so `is set` would hold every morning and the guard
    would be decorative. The await is derived from the same refs the guard reads."""
    from aughor.automations.engine import AWAIT_KEY
    seen: list[dict] = []

    def _dispatch(effect, automation):
        seen.append(dict(effect.config))
        return EffectOutcome(kind=effect.kind, target="t", status="executed",
                             data={"answer": "found something"})

    _run(_automation(
        _investigate(),
        _effect(when=[{"left": {"$from": "report.answer"}, "op": "truthy"}])), _dispatch)
    assert seen[0].get(AWAIT_KEY) is True, "the guarded-on step must be waited FOR"


def test_a_guard_onto_an_unknown_step_is_refused_at_save():
    with pytest.raises(ValueError, match="unknown step 'nope'"):
        _automation(_effect(alias="a"),
                    _effect(when=[{"left": {"$from": "nope.answer"}, "op": "truthy"}]))


def test_a_guard_onto_an_unknown_KEY_is_refused_at_save():
    """B1's key check reaches through the guard path too — an unknown key used to
    surface at 09:00 as a skipped step, which is what B1 exists to stop."""
    with pytest.raises(ValueError, match="has no 'reveune'"):
        _automation(_investigate(),
                    _effect(when=[{"left": {"$from": "report.reveune"}, "op": "truthy"}]))


def test_a_guard_that_refers_forward_is_refused_at_save():
    with pytest.raises(ValueError, match="runs AFTER it"):
        _automation(_effect(when=[{"left": {"$from": "later.ts"}, "op": "truthy"}]),
                    _effect(alias="later"))


# ── absence is not falsehood ─────────────────────────────────────────────────────

def test_a_guard_whose_upstream_produced_NOTHING_skips_as_missing_data():
    """Not silently false. The upstream broke; saying "condition not met" would send a
    reader looking at the guard instead of at the step that failed."""
    def _dispatch(effect, automation):
        return EffectOutcome(kind=effect.kind, target="t", status="failed")

    run = _run(_automation(
        _effect(alias="report"),
        _effect(when=[{"left": {"$from": "report.ts"}, "op": "truthy"}])), _dispatch)
    assert run.effects[1].status == "skipped"
    assert "upstream data unavailable" in run.effects[1].message
    assert GUARD_SKIP not in run.effects[1].message


def test_a_step_held_by_its_guard_publishes_nothing_downstream():
    """The cascade: a guarded-off step produced no output, so a step binding to it is
    skipped in turn rather than run with a hole."""
    seen, dispatch = _publishes(ts="1788.1")
    run = _run(_automation(
        _effect(alias="opener"),
        _effect(alias="middle", when=[{"left": {"$from": "opener.ts"},
                                       "op": "eq", "right": "never"}]),
        _effect(thread_ts={"$from": "middle.ts"})), dispatch)
    assert [o.status for o in run.effects] == ["executed", "skipped", "skipped"]
    assert GUARD_SKIP in run.effects[1].message
    assert "upstream data unavailable" in run.effects[2].message
    assert len(seen) == 1


# ── the comparisons ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("op,left,right,holds", [
    ("truthy", "text", None, True), ("truthy", "", None, False),
    ("falsy", "", None, True), ("falsy", 0, None, True),
    ("eq", "a", "a", True), ("ne", "a", "b", True),
    ("gt", 12, 5, True), ("gt", 5, 12, False),
    ("gte", 5, 5, True), ("lt", 1, 2, True), ("lte", 2, 2, True),
    # A warehouse column arrives as a string often enough that refusing this would
    # make the guard useless on real data.
    ("gt", "12", 5, True),
    ("contains", "revenue fell", "fell", True),
    ("contains", ["a", "b"], "b", True),
])
def test_each_operator(op, left, right, holds):
    clause = {"left": left, "op": op, "right": right}
    assert evaluate_guard(_effect(when=[clause]), {})[0] is holds


def test_a_bool_is_not_a_number():
    """`True > 0` is an accident of Python, never a comparison anyone wrote."""
    passed, why = evaluate_guard(_effect(when=[{"left": True, "op": "gt", "right": 0}]), {})
    assert passed is False and "cannot compare" in why


def test_an_unevaluable_comparison_holds_the_step_and_says_why():
    """Neither true nor false. Silently false stops a chain; silently true runs the step
    the guard exists to prevent — and both look like a guard that simply did not match."""
    passed, why = evaluate_guard(
        _effect(when=[{"left": "n/a", "op": "gt", "right": 5}]), {})
    assert passed is False
    assert "cannot compare" in why and "needs two numbers" in why


# ── all / any ────────────────────────────────────────────────────────────────────

def test_all_requires_every_clause_and_names_the_ones_that_failed():
    passed, why = evaluate_guard(_effect(when=[
        {"left": 10, "op": "gt", "right": 5},
        {"left": "", "op": "truthy"},
    ]), {})
    assert passed is False and why == " is set"


def test_any_needs_only_one():
    assert evaluate_guard(_effect(logic="any", when=[
        {"left": 1, "op": "gt", "right": 5},
        {"left": "here", "op": "truthy"},
    ]), {})[0] is True


def test_any_that_matches_nothing_reports_every_clause():
    passed, why = evaluate_guard(_effect(logic="any", when=[
        {"left": 1, "op": "gt", "right": 5},
        {"left": "", "op": "truthy"},
    ]), {})
    assert passed is False and " or " in why


# ── the fallback ─────────────────────────────────────────────────────────────────

def test_a_run_guarded_off_entirely_does_NOT_fire_the_fallback():
    """"Nothing was meant to run" is not "everything failed". The fallback exists to page
    a human that the automation itself broke; a quiet morning is not that."""
    seen, dispatch = _publishes()
    run = _run(_automation(
        _effect(when=[{"left": "", "op": "truthy"}]),
        fallback=Effect(kind="notify", config={"trigger_id": "oncall"})), dispatch)
    assert run.effects[0].status == "skipped"
    assert run.fallback_used is False, "a guarded-off run must not page on-call"
    assert seen == []


def test_a_real_failure_still_fires_the_fallback_with_a_guarded_step_beside_it():
    """The guard must not become an escape hatch that suppresses the alarm."""
    def _dispatch(effect, automation):
        if effect.kind == "notify":
            return EffectOutcome(kind=effect.kind, target="t", status="executed")
        return EffectOutcome(kind=effect.kind, target="t", status="failed")

    run = _run(_automation(
        _effect(alias="tries"),
        _effect(when=[{"left": "", "op": "truthy"}]),
        fallback=Effect(kind="notify", config={"trigger_id": "oncall"})), _dispatch)
    assert [o.status for o in run.effects[:2]] == ["failed", "skipped"]
    assert run.fallback_used is True
