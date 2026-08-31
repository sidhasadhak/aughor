"""DS-6 — branch and join: route on a guard's verdict, and merge the branches back.

Their engine's documented, seven-release-old ceiling: branches that cannot rejoin,
because their router walks downstream persistently excluding everything it did not take.
Ours routes on ONE recorded verdict and joins by reading whichever arm actually ran —
tractable precisely because awaits, validation and both canvases already derive from the
one `effect_refs`.

The properties locked here, each one something a plausible implementation gets wrong:

* **The route reads the guard's VERDICT, never the arm's health.** A primary arm whose
  guard held and whose dispatch then failed still owned the decision — the otherwise arm
  is a route, not a fallback, and running it would send the "nothing to report" message
  on a morning something broke.
* **An undecided guard takes NEITHER arm.** Unevaluable ("n/a" > 5) and missing-upstream
  are not falsehood; routing to the otherwise arm would be a guess wearing a verdict.
  W1's skipped-never-guessed, extended to the route.
* **A join resolves the TAKEN branch.** `{"$from_any": [...]}` reads alternatives in
  authored order and skips honestly when none resolved — never runs with a hole.
* **Every alternative is dataflow.** Validated at save, awaited when it names an
  `investigate`, drawn by both canvases — all off the same `effect_refs`, so the join
  cannot become a second, invisible flow.
* **An untaken arm does not page on-call.** `skipped`, so the fallback's "everything
  that tried failed" cannot count a branch the route deliberately did not take.
"""
from __future__ import annotations

import pytest

from aughor.automations.dataflow import (
    BRANCH_SKIP, GUARD_SKIP, effect_refs, resolve, UnresolvedBinding,
)
from aughor.automations.models import Automation, Condition, Effect, EffectOutcome


def _post(alias="", when=None, else_of="", **config) -> Effect:
    base = {"bot_id": "sb_1", "channel": "C1"}
    base.update(config)
    return Effect(kind="slack_post", alias=alias, config=base,
                  when=when or [], else_of=else_of)


def _investigate(alias="report", **config) -> Effect:
    return Effect(kind="investigate", alias=alias,
                  config={"question": "how were sales?", **config})


def _automation(*effects, fallback=None) -> Automation:
    return Automation(
        name="routed", conn_id="conn-a",
        conditions=[Condition(kind="schedule", config={"cron": "0 9 * * 1"})],
        effects=list(effects), fallback_effect=fallback, max_retries=0,
    )


def _run(automation, dispatch, **kwargs):
    from aughor.automations.engine import run_automation
    return run_automation(automation, dispatch=dispatch, persist=False,
                          probe=lambda *a, **k: True,
                          sleeper=lambda _s: None, rng=lambda: 0.0, **kwargs)


def _publishes(**data):
    seen: list[dict] = []

    def _dispatch(effect, automation):
        seen.append(dict(effect.config))
        return EffectOutcome(kind=effect.kind, target="t", status="executed",
                             data=dict(data))
    return seen, _dispatch


#: A two-armed route over a literal guard, so no upstream is needed to decide it.
def _branch(op_holds: bool):
    guard = [{"left": "yes", "op": "eq", "right": "yes" if op_holds else "no"}]
    return (_post(alias="alerts", when=guard),
            _post(alias="daily", else_of="alerts"))


# ── the route ────────────────────────────────────────────────────────────────────

def test_guard_holds_primary_runs_and_the_otherwise_arm_is_not_taken():
    seen, dispatch = _publishes(ts="1.1")
    run = _run(_automation(*_branch(op_holds=True)), dispatch)
    assert [o.status for o in run.effects] == ["executed", "skipped"]
    assert run.effects[1].message == f"{BRANCH_SKIP}: 'alerts' met its condition"
    assert len(seen) == 1, "the untaken arm must never reach the dispatcher"


def test_guard_does_not_hold_and_the_otherwise_arm_runs():
    seen, dispatch = _publishes(ts="1.1")
    run = _run(_automation(*_branch(op_holds=False)), dispatch)
    assert [o.status for o in run.effects] == ["skipped", "executed"]
    assert GUARD_SKIP in run.effects[0].message
    assert len(seen) == 1


def test_an_unevaluable_guard_takes_NEITHER_arm():
    """"n/a" > 5 is not a verdict. Routing the otherwise arm on it would be a guess
    wearing one — the branch skips BOTH ways and says the decision was never made."""
    seen, dispatch = _publishes()
    run = _run(_automation(
        _post(alias="alerts", when=[{"left": "n/a", "op": "gt", "right": 5}]),
        _post(alias="daily", else_of="alerts")), dispatch)
    assert [o.status for o in run.effects] == ["skipped", "skipped"]
    assert "cannot compare" in run.effects[0].message
    assert run.effects[1].message == f"{BRANCH_SKIP}: 'alerts' was not decided"
    assert len(seen) == 0


def test_a_guard_whose_upstream_is_missing_takes_neither_arm():
    """Absence is not falsehood, one construct over: the deciding step's guard read a
    step that produced nothing, so there is no verdict to route on."""
    def _dispatch(effect, automation):
        return EffectOutcome(kind=effect.kind, target="t", status="failed")

    run = _run(_automation(
        _investigate(),
        _post(alias="alerts",
              when=[{"left": {"$from": "report.answer"}, "op": "truthy"}]),
        _post(alias="daily", else_of="alerts")), _dispatch)
    assert [o.status for o in run.effects] == ["failed", "skipped", "skipped"]
    assert "upstream data unavailable" in run.effects[1].message
    assert run.effects[2].message == f"{BRANCH_SKIP}: 'alerts' was not decided"


def test_the_route_reads_the_verdict_not_the_arms_health():
    """The primary arm's guard HELD; its dispatch then failed. The decision still went
    its way — the otherwise arm is a route, not error handling, and running it would
    post "all quiet" on the morning something broke."""
    calls: list[str] = []

    def _dispatch(effect, automation):
        calls.append(effect.alias)
        return EffectOutcome(kind=effect.kind, target="t", status="failed")

    run = _run(_automation(*_branch(op_holds=True)), _dispatch)
    assert [o.status for o in run.effects] == ["failed", "skipped"]
    assert run.effects[1].message == f"{BRANCH_SKIP}: 'alerts' met its condition"
    assert calls == ["alerts"]


def test_a_held_step_never_resolves_its_own_params():
    """DS-6 moved the guard ahead of the params resolve: a step held by its guard reads
    as GUARD_SKIP even when its own params are also unresolvable — the guard decided
    first, and that is the fix the reader should be sent to."""
    seen, dispatch = _publishes()   # `opener` executes but publishes NOTHING,
    run = _run(_automation(         # so `opener.ts` would raise if it were resolved
        _post(alias="opener"),
        _post(alias="held",
              when=[{"left": "no", "op": "eq", "right": "yes"}],
              thread_ts={"$from": "opener.ts"})), dispatch)
    assert run.effects[1].status == "skipped"
    assert GUARD_SKIP in run.effects[1].message
    assert "upstream data unavailable" not in run.effects[1].message


def test_the_otherwise_arm_may_carry_its_own_only_if():
    """"Else, only if" composes: the arm is taken by the route, then held or run by its
    own guard — two separate facts, reported separately."""
    seen, dispatch = _publishes(ts="1.1")
    run = _run(_automation(
        *_branch(op_holds=False)[:1],
        _post(alias="daily", else_of="alerts",
              when=[{"left": "no", "op": "eq", "right": "yes"}])), dispatch)
    assert [o.status for o in run.effects] == ["skipped", "skipped"]
    assert GUARD_SKIP in run.effects[1].message, "taken by the route, held by its guard"


def test_an_elif_chain_routes_to_the_last_arm():
    """`else_of` onto a step that is itself an otherwise arm: s3 runs only when s2's
    branch was taken AND s2's guard did not hold — an elif, for free, off the same one
    verdict rule."""
    seen, dispatch = _publishes(ts="1.1")
    run = _run(_automation(
        _post(alias="a", when=[{"left": "no", "op": "eq", "right": "yes"}]),
        _post(alias="b", else_of="a",
              when=[{"left": "no", "op": "eq", "right": "yes"}]),
        _post(alias="c", else_of="b")), dispatch)
    assert [o.status for o in run.effects] == ["skipped", "skipped", "executed"]
    assert len(seen) == 1


def test_an_untaken_arm_does_not_fire_the_fallback():
    """W1's lesson, one construct over: the fallback needs a step that TRIED and did
    not succeed, and a branch the route did not take never tried."""
    seen, dispatch = _publishes(ts="1.1")
    fallback = Effect(kind="notify", config={"trigger_id": "page-me"})
    run = _run(_automation(*_branch(op_holds=True), fallback=fallback), dispatch)
    assert run.fallback_used is False


# ── the join ─────────────────────────────────────────────────────────────────────

def _joined(op_holds: bool) -> Automation:
    """alerts / daily, and ONE summary that threads onto whichever posted — the
    roadmap's own receipt shape."""
    return _automation(
        *_branch(op_holds),
        _post(alias="summary",
              thread_ts={"$from_any": ["alerts.ts", "daily.ts"]},
              channel={"$from_any": ["alerts.channel", "daily.channel"]}))


def test_the_join_reads_the_taken_arm_first_alternative():
    seen, dispatch = _publishes(ts="9.9", channel="C-alerts")
    run = _run(_joined(op_holds=True), dispatch)
    assert [o.status for o in run.effects] == ["executed", "skipped", "executed"]
    assert seen[-1]["thread_ts"] == "9.9"


def test_the_join_reads_the_taken_arm_second_alternative():
    seen, dispatch = _publishes(ts="7.7", channel="C-daily")
    run = _run(_joined(op_holds=False), dispatch)
    assert [o.status for o in run.effects] == ["skipped", "executed", "executed"]
    assert seen[-1]["thread_ts"] == "7.7"


def test_the_join_skips_honestly_when_no_branch_was_taken():
    seen, dispatch = _publishes(ts="1.1", channel="C1")
    run = _run(_automation(
        _post(alias="alerts", when=[{"left": "n/a", "op": "gt", "right": 5}]),
        _post(alias="daily", else_of="alerts"),
        _post(alias="summary",
              thread_ts={"$from_any": ["alerts.ts", "daily.ts"]})), dispatch)
    assert [o.status for o in run.effects] == ["skipped", "skipped", "skipped"]
    assert "none of alerts.ts, daily.ts" in run.effects[2].message
    assert len(seen) == 0


def test_resolve_prefers_the_first_alternative_in_authored_order():
    """Outside a route both may resolve; the authored order is the preference order,
    deterministically — never whichever a dict happened to yield."""
    value = resolve({"$from_any": ["a.ts", "b.ts"]},
                    {"a": {"ts": "first"}, "b": {"ts": "second"}})
    assert value == "first"


def test_resolve_skips_an_alternative_missing_its_key():
    """An arm that executed but did not publish the asked key is not the value — the
    next alternative is tried rather than the step running with a hole."""
    value = resolve({"$from_any": ["a.ts", "b.ts"]},
                    {"a": {"channel": "C1"}, "b": {"ts": "second"}})
    assert value == "second"


def test_a_malformed_join_is_refused_by_resolve():
    with pytest.raises(UnresolvedBinding, match="non-empty list"):
        resolve({"$from_any": "alerts.ts"}, {"alerts": {"ts": "1"}})


def test_every_alternative_is_in_effect_refs():
    """The one-seam rule: validation, the await and both canvases read `effect_refs`,
    so a join that hid an alternative from any of them would disagree with the run."""
    e = _post(thread_ts={"$from_any": ["alerts.ts", "daily.ts"]})
    assert effect_refs(e) == ["alerts.ts", "daily.ts"]


def test_an_investigate_arm_consumed_by_a_join_is_awaited():
    """W1's subtlest bug, one construct over: an arm nobody waited for would hand the
    join a job id. The await derives from the same refs the join reads."""
    from aughor.automations.engine import AWAIT_KEY
    seen: list[dict] = []

    def _dispatch(effect, automation):
        seen.append(dict(effect.config))
        return EffectOutcome(kind=effect.kind, target="t", status="executed",
                             data={"answer": "fell 12%", "ts": "1.1", "channel": "C1"})

    _run(_automation(
        Effect(kind="investigate", alias="alerts",
               config={"question": "how were sales?"},
               when=[{"left": "yes", "op": "eq", "right": "yes"}]),
        _post(alias="daily", else_of="alerts"),
        _post(alias="summary",
              message={"$from_any": ["alerts.answer", "daily.ts"]})), _dispatch)
    assert seen[0].get(AWAIT_KEY) is True


# ── refused at save ──────────────────────────────────────────────────────────────

def test_otherwise_of_an_unknown_step_is_refused():
    with pytest.raises(ValueError, match="otherwise of unknown step 'nope'"):
        _automation(_post(alias="a", when=[{"left": "x", "op": "truthy"}]),
                    _post(else_of="nope"))


def test_otherwise_of_a_later_step_is_refused():
    with pytest.raises(ValueError, match="runs AFTER it"):
        _automation(_post(else_of="later"),
                    _post(alias="later", when=[{"left": "x", "op": "truthy"}]))


def test_otherwise_of_itself_is_refused():
    with pytest.raises(ValueError, match="otherwise of itself"):
        _automation(_post(alias="a", else_of="a", when=[{"left": "x", "op": "truthy"}]))


def test_otherwise_of_an_unguarded_step_is_refused():
    """The target always runs, so the arm could never — an automation that cannot do
    what it draws is refused, not stored."""
    with pytest.raises(ValueError, match="has no 'Only if'"):
        _automation(_post(alias="a"), _post(else_of="a"))


def test_otherwise_of_a_fanned_step_is_refused():
    """A fanned step's guard is N per-item verdicts — many filters, not one route."""
    with pytest.raises(ValueError, match="once per item"):
        _automation(
            Effect(kind="slack_post", alias="a",
                   config={"bot_id": "sb_1", "channel": "C1"},
                   when=[{"left": {"$from": "item.value"}, "op": "truthy"}],
                   for_each={"source": ["EMEA", "NA"]}),
            _post(else_of="a"))


def test_a_join_alternative_onto_an_unknown_step_is_refused():
    with pytest.raises(ValueError, match="unknown step 'nope'"):
        _automation(_post(alias="a"),
                    _post(thread_ts={"$from_any": ["a.ts", "nope.ts"]}))


def test_a_join_alternative_onto_an_unknown_KEY_is_refused():
    """B1's key check reaches through every alternative — a join may only offer keys
    its producers could publish."""
    with pytest.raises(ValueError, match="has no 'answer'"):
        _automation(_post(alias="a"),
                    _post(thread_ts={"$from_any": ["a.answer"]}))


@pytest.mark.parametrize("bad", [
    {"$from_any": "a.ts"},          # a string is one ref, not a list of them
    {"$from_any": []},              # an empty join can never resolve
    {"$from_any": ["a.ts", 3]},     # every alternative is a reference string
    {"$from_any": [""]},            # an empty string names nothing
])
def test_a_malformed_join_is_refused_at_save(bad):
    with pytest.raises(ValueError, match="non-empty list"):
        _automation(_post(alias="a"), _post(thread_ts=bad))


def test_a_malformed_join_in_a_guard_side_is_refused_at_save():
    with pytest.raises(ValueError, match="non-empty list"):
        _automation(_post(alias="a"),
                    _post(when=[{"left": {"$from_any": []}, "op": "truthy"}]))


# ── the graph ────────────────────────────────────────────────────────────────────

def test_the_route_draws_as_its_own_edge_kind():
    from aughor.automations.graph import build_graph
    graph = build_graph(_automation(*_branch(op_holds=True)))
    route = [e for e in graph["edges"] if e["type"] == "route"]
    assert route == [{"from": "alerts", "to": "daily", "type": "route",
                      "label": "otherwise"}]
    daily = next(n for n in graph["nodes"] if n["id"] == "daily")
    assert daily["else_of"] == "alerts"


def test_an_untaken_arm_decorates_as_not_taken_never_guarded():
    """Two different facts a reader needs told apart: "held · condition not met" is a
    step whose own guard said no; "not taken" is the other path of a decision."""
    from aughor.automations.graph import build_graph
    seen, dispatch = _publishes(ts="1.1")
    run = _run(_automation(*_branch(op_holds=True)), dispatch)
    graph = build_graph(_automation(*_branch(op_holds=True)), run)
    daily = next(n for n in graph["nodes"] if n["id"] == "daily")
    assert daily["not_taken"] is True and daily["guarded"] is False


def test_a_join_draws_one_data_edge_per_alternative():
    from aughor.automations.graph import build_graph, data_edges_only
    graph = build_graph(_joined(op_holds=True))
    into_summary = [e for e in data_edges_only(graph) if e["to"] == "summary"]
    assert {(e["from"], e["label"]) for e in into_summary} == {
        ("alerts", "ts"), ("daily", "ts"), ("alerts", "channel"), ("daily", "channel")}


# ── the preview ──────────────────────────────────────────────────────────────────

def test_a_dry_run_walks_both_arms_and_reports_the_route():
    """A sample cannot say which way tomorrow's guard goes, so a preview shows BOTH
    arms as would-run — each naming whose otherwise it is — and the join resolves
    samples rather than reporting a sound design as missing upstream."""
    run = _run(_joined(op_holds=True), None, dry_run=True)
    assert [o.status for o in run.effects] == ["executed"] * 3
    assert "otherwise of alerts — decided when it runs" in run.effects[1].message
    assert "upstream data unavailable" not in run.effects[2].message
