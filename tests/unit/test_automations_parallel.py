"""DS-7 — parallel steps: the frontier, driven by the arrows.

`scheduling="parallel"` runs steps as their references allow — a step waits for every
step its params, guard, fan source or `else_of` name, and for nothing else. `ordered`
(the default) stays the strictly sequential walk every automation written before DS-7
performs, byte for byte — the whole existing suite is that assertion.

The properties locked here, each one a plausible frontier gets wrong:

* **Independent steps genuinely overlap.** Asserted on wall-clock, not on intent: a
  frontier that schedules ready steps one at a time passes every ordering test and
  parallelises nothing.
* **A dependent step waits for its producer** — and reads the value it published, not a
  snapshot from before it ran.
* **Outcomes stay in DECLARED order** whatever order the work finished in.
  `group_outcomes` and every reader of a run matches positions; a history shuffled by
  scheduling luck decorates the wrong cards.
* **The route and the join keep their laws under the frontier.** An otherwise arm is
  scheduled after its target and reads the recorded verdict; a join reads whichever arm
  ran.
* **A preview never goes parallel.** The inert dispatcher is instant, so parallelism
  would buy only nondeterministic ordering — a dry run that reads differently on every
  press answers no question anyone asked.
"""
from __future__ import annotations

import threading
import time as _time

from aughor.automations.dataflow import BRANCH_SKIP
from aughor.automations.models import Automation, Condition, Effect, EffectOutcome


def _post(alias="", when=None, else_of="", **config) -> Effect:
    base = {"bot_id": "sb_1", "channel": "C1"}
    base.update(config)
    return Effect(kind="slack_post", alias=alias, config=base,
                  when=when or [], else_of=else_of)


def _automation(*effects, scheduling="parallel", fallback=None, **kw) -> Automation:
    return Automation(
        name="frontier", conn_id="conn-a", scheduling=scheduling,
        conditions=[Condition(kind="schedule", config={"cron": "0 9 * * 1"})],
        effects=list(effects), fallback_effect=fallback,
        max_retries=kw.pop("max_retries", 0), **kw)


def _run(automation, dispatch, **kwargs):
    from aughor.automations.engine import run_automation
    return run_automation(automation, dispatch=dispatch, persist=False,
                          probe=lambda *a, **k: True,
                          sleeper=lambda _s: None, rng=lambda: 0.0, **kwargs)


def _timed_dispatch(seconds_by_alias: dict, data_by_alias: dict | None = None):
    """A dispatch that sleeps per step and records when each began and ended."""
    windows: dict[str, tuple[float, float]] = {}
    lock = threading.Lock()

    def _dispatch(effect, automation):
        t0 = _time.monotonic()
        _time.sleep(seconds_by_alias.get(effect.alias, 0.0))
        with lock:
            windows[effect.alias] = (t0, _time.monotonic())
        return EffectOutcome(kind=effect.kind, target=effect.alias, status="executed",
                             data=dict((data_by_alias or {}).get(effect.alias, {})))
    return windows, _dispatch


# ── the overlap, measured ────────────────────────────────────────────────────────

def test_independent_steps_overlap_on_the_clock():
    windows, dispatch = _timed_dispatch({"a": 0.4, "b": 0.4})
    t0 = _time.monotonic()
    run = _run(_automation(_post(alias="a"), _post(alias="b")), dispatch)
    elapsed = _time.monotonic() - t0
    assert [o.status for o in run.effects] == ["executed", "executed"]
    assert elapsed < 0.7, f"two independent 0.4s steps took {elapsed:.2f}s — no overlap"
    (a0, a1), (b0, b1) = windows["a"], windows["b"]
    assert a0 < b1 and b0 < a1, "the two dispatch windows never overlapped"


def test_ordered_stays_strictly_sequential():
    """The default is the pre-DS-7 walk, and the clock can tell."""
    _windows, dispatch = _timed_dispatch({"a": 0.2, "b": 0.2})
    t0 = _time.monotonic()
    _run(_automation(_post(alias="a"), _post(alias="b"), scheduling="ordered"), dispatch)
    assert _time.monotonic() - t0 >= 0.4


def test_a_dependent_step_waits_and_reads_the_published_value():
    seen: list[dict] = []
    lock = threading.Lock()
    windows: dict[str, tuple[float, float]] = {}

    def _dispatch(effect, automation):
        t0 = _time.monotonic()
        if effect.alias == "opener":
            _time.sleep(0.2)
        with lock:
            seen.append({"alias": effect.alias, **dict(effect.config)})
            windows[effect.alias] = (t0, _time.monotonic())
        return EffectOutcome(kind=effect.kind, target=effect.alias, status="executed",
                             data={"ts": "9.9", "channel": "C-op"})

    run = _run(_automation(
        _post(alias="opener"),
        _post(alias="reply", thread_ts={"$from": "opener.ts"})), _dispatch)
    assert [o.status for o in run.effects] == ["executed", "executed"]
    reply = next(s for s in seen if s["alias"] == "reply")
    assert reply["thread_ts"] == "9.9", "the consumer must read what its producer made"
    assert windows["reply"][0] >= windows["opener"][1], \
        "the consumer dispatched before its producer finished"


def test_outcomes_keep_declared_order_when_completion_inverts():
    """Step 1 is slow, step 2 is instant — the run history still reads 1 then 2."""
    _windows, dispatch = _timed_dispatch({"slow": 0.3, "fast": 0.0})
    run = _run(_automation(_post(alias="slow"), _post(alias="fast")), dispatch)
    assert [o.target for o in run.effects] == ["slow", "fast"]


def test_the_frontier_caps_concurrency_but_completes_everything():
    from aughor.automations.engine import MAX_PARALLEL_STEPS
    live = {"now": 0, "peak": 0}
    lock = threading.Lock()

    def _dispatch(effect, automation):
        with lock:
            live["now"] += 1
            live["peak"] = max(live["peak"], live["now"])
        _time.sleep(0.05)
        with lock:
            live["now"] -= 1
        return EffectOutcome(kind=effect.kind, target=effect.alias, status="executed")

    steps = [_post(alias=f"s{n}") for n in range(MAX_PARALLEL_STEPS + 3)]
    run = _run(_automation(*steps), _dispatch)
    assert len(run.effects) == MAX_PARALLEL_STEPS + 3
    assert all(o.status == "executed" for o in run.effects)
    assert live["peak"] <= MAX_PARALLEL_STEPS


# ── the route and the join, under the frontier ───────────────────────────────────

def test_the_route_holds_under_parallel_scheduling():
    """The otherwise arm is scheduled after its target and reads the verdict — a
    frontier that ran both arms at once would have no verdict to read."""
    windows, dispatch = _timed_dispatch({"alerts": 0.2})
    run = _run(_automation(
        _post(alias="alerts", when=[{"left": "yes", "op": "eq", "right": "yes"}]),
        _post(alias="daily", else_of="alerts")), dispatch)
    assert [o.status for o in run.effects] == ["executed", "skipped"]
    assert run.effects[1].message == f"{BRANCH_SKIP}: 'alerts' met its condition"
    assert "daily" not in windows, "the untaken arm must never reach the dispatcher"


def test_the_join_reads_the_taken_arm_under_parallel_scheduling():
    seen: list[dict] = []
    lock = threading.Lock()

    def _dispatch(effect, automation):
        with lock:
            seen.append({"alias": effect.alias, **dict(effect.config)})
        return EffectOutcome(kind=effect.kind, target=effect.alias, status="executed",
                             data={"ts": f"{effect.alias}-ts", "channel": "C1"})

    run = _run(_automation(
        _post(alias="alerts", when=[{"left": "no", "op": "eq", "right": "yes"}]),
        _post(alias="daily", else_of="alerts"),
        _post(alias="summary",
              thread_ts={"$from_any": ["alerts.ts", "daily.ts"]})), _dispatch)
    assert [o.status for o in run.effects] == ["skipped", "executed", "executed"]
    summary = next(s for s in seen if s["alias"] == "summary")
    assert summary["thread_ts"] == "daily-ts"


def test_the_fallback_still_fires_once_when_every_attempt_failed():
    def _dispatch(effect, automation):
        return EffectOutcome(kind=effect.kind, target=effect.alias or "fb",
                             status="failed")

    fallback = Effect(kind="notify", config={"trigger_id": "page-me"})
    run = _run(_automation(_post(alias="a"), _post(alias="b"), fallback=fallback),
               _dispatch)
    assert run.fallback_used is True
    assert len(run.effects) == 3      # a, b, and exactly one fallback outcome


def test_a_fanned_step_publishes_its_count_under_the_frontier():
    def _dispatch(effect, automation):
        return EffectOutcome(kind=effect.kind, target=effect.alias, status="executed",
                             data={"ts": "1.1", "channel": "C1"})

    run = _run(_automation(
        Effect(kind="slack_post", alias="fan",
               config={"bot_id": "b", "channel": {"$from": "item.value"},
                       "message": "hi"},
               for_each={"source": ["#a", "#b", "#c"]}),
        _post(alias="after",
              when=[{"left": {"$from": "fan.count"}, "op": "gte", "right": 3}])),
        _dispatch)
    statuses = [o.status for o in run.effects]
    assert statuses == ["executed"] * 4, statuses


# ── R5's plane, joined ───────────────────────────────────────────────────────────

def test_the_frontier_declares_its_fanout_region():
    """The worker threads run inside `automations.parallel_steps` — which is what lets
    `assert_dispatchable` in the governed executor refuse a declared action that is not
    parallel-safe. An undeclared fan-out is invisible to that checkpoint, and invisible
    is exactly the failure mode Wave R5 exists to remove. The ordered walk declares
    nothing: serial is the pre-DS-7 state, byte for byte."""
    from aughor.kernel.parallel_safety import current_fanout
    regions: dict[str, str] = {}
    lock = threading.Lock()

    def _dispatch(effect, automation):
        with lock:
            regions[effect.alias] = current_fanout()
        return EffectOutcome(kind=effect.kind, target=effect.alias, status="executed")

    _run(_automation(_post(alias="a"), _post(alias="b")), _dispatch)
    assert regions == {"a": "automations.parallel_steps",
                       "b": "automations.parallel_steps"}

    regions.clear()
    _run(_automation(_post(alias="a"), scheduling="ordered"), _dispatch)
    assert regions == {"a": ""}


def test_parallel_refused_is_a_verdict_never_retried(monkeypatch):
    """R5's refusal maps to the terminal `dispatch_error`, not the retriable `failed`:
    the same inputs refuse identically next attempt, and retrying a refusal is another
    request against whatever just refused (the #200 lesson). First reachable from an
    automation now that steps can run concurrently."""
    import aughor.actions.executor as kexec
    import aughor.ontology.store as ostore

    class _Result:
        status = "parallel_refused"
        message = ("refund_orders is not declared parallel-safe and was "
                   "dispatched inside automations.parallel_steps")
        outcome = None

    class _Graph:
        schema_name = ""
        kinetic_actions = {"refund_orders": object()}

    calls = {"n": 0}

    def _refuse(*a, **k):
        calls["n"] += 1
        return _Result()

    monkeypatch.setattr(kexec, "execute_kinetic_action", _refuse)
    monkeypatch.setattr(ostore, "load_latest_ontology", lambda *a, **k: _Graph())

    from aughor.automations.engine import run_automation
    run = run_automation(_automation(
        Effect(kind="kinetic_action", alias="refund",
               config={"action_id": "refund_orders"}),
        scheduling="parallel", max_retries=3),
        persist=False, probe=lambda *a, **k: True,
        sleeper=lambda _s: None, rng=lambda: 0.0)
    assert run.effects[0].status == "dispatch_error"
    assert "parallel-safe" in run.effects[0].message
    assert calls["n"] == 1, "a refusal must never be retried"


# ── the preview ──────────────────────────────────────────────────────────────────

def test_a_dry_run_on_a_parallel_automation_walks_in_declared_order():
    """A preview stays sequential and deterministic — parallelism over an inert
    dispatcher buys only sample-order shuffle. The published samples prove the walk:
    each carries its own step's alias, in declared order."""
    run = _run(_automation(_post(alias="a"), _post(alias="b"), _post(alias="c")),
               None, dry_run=True)
    assert [o.status for o in run.effects] == ["executed"] * 3
    assert "nothing was sent" in run.reason
    published = [next(iter(o.data.values()), "") for o in run.effects]
    assert published == ["«a.channel»", "«b.channel»", "«c.channel»"]


# ── the store and the graph ──────────────────────────────────────────────────────

def test_scheduling_round_trips_through_the_store():
    from aughor.automations.store import get_automation, upsert_automation
    a = _automation(_post(alias="a"), scheduling="parallel")
    upsert_automation(a)
    stored = get_automation(a.id)
    assert stored is not None and stored.scheduling == "parallel"
    # And the default reads back as the default — the VA-9b family check: a field the
    # INSERT quietly ignored would echo on the response and read "" from the row.
    b = _automation(_post(alias="a"), scheduling="ordered")
    upsert_automation(b)
    assert get_automation(b.id).scheduling == "ordered"


def test_the_parallel_graph_draws_trigger_to_roots_and_no_false_spine():
    from aughor.automations.graph import build_graph
    graph = build_graph(_automation(
        _post(alias="a"),
        _post(alias="b"),
        _post(alias="c", thread_ts={"$from": "a.ts"})))
    seq = [(e["from"], e["to"]) for e in graph["edges"] if e["type"] == "sequence"]
    assert ("trigger", "a") in seq and ("trigger", "b") in seq
    assert ("a", "b") not in seq, "independent steps must not wear an order arrow"
    assert ("b", "c") not in seq
    assert ("trigger", "c") not in seq, "a fed step's order claim is its data edge"
    assert graph["scheduling"] == "parallel"


def test_the_ordered_graph_keeps_its_chain_spine_exactly():
    from aughor.automations.graph import build_graph
    graph = build_graph(_automation(
        _post(alias="a"), _post(alias="b"), scheduling="ordered"))
    seq = [(e["from"], e["to"]) for e in graph["edges"] if e["type"] == "sequence"]
    assert seq == [("trigger", "a"), ("a", "b")]
    assert graph["scheduling"] == "ordered"
