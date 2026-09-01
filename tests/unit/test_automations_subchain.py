"""DS-9 — a chain as a step: composition, and the four ways it could quietly lie.

"Post it, and if that fails tell on-call" is a shape every chain in a library wants, and
before this the only way to have it twice was to author it twice — which is also how it
comes to be authored *differently* in each place. A subchain step makes one shape callable.

The properties pinned here, each one something a plausible implementation gets wrong:

* **The child does not re-ask its own conditions.** A chain that invokes another is stating
  when it should happen; a shared subchain triggered "every Monday 09:00" that answers "not
  due" to every caller on every other day is not shared, it is broken.
* **But its lifecycle gates still apply.** `enabled=False` is a person saying "this must not
  run", and being called is not an exemption from that.
* **Cycles are refused at SAVE, and a diamond is not a cycle.** Two steps calling the same
  subchain is the entire point of the wave; refusing that would refuse the feature.
* **One trace, two run rows.** The child writes its steps under the PARENT's trace so a
  nested chain reads as one waterfall — and still keeps its own run row, because a shared
  subchain's history is the one place you can see every caller that used it.
* **A child that pauses parks the parent** (DS-8 met DS-9). A parent that walked on would
  run the steps after a governed write that has not happened yet — the exact failure a
  mid-chain approval exists to prevent, one level up.
* **A child that declines is `skipped`, not `failed`.** Folding a disabled subchain into
  failure would let it fire the parent's fallback and page on-call about a switch someone
  deliberately flipped.
"""
from __future__ import annotations

import pytest

from aughor.automations.engine import (
    MAX_SUBCHAIN_DEPTH, _CHAIN, _dispatch_subchain, resume_run, run_automation,
)
from aughor.automations.models import Automation, Condition, Effect, EffectOutcome
from aughor.automations.store import (
    cycle_problem, get_run, get_runs, set_automation_enabled, upsert_automation,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def _post(alias="tell", **config) -> Effect:
    return Effect(kind="slack_post", alias=alias,
                  config={"bot_id": "sb_1", "channel": "C1", **config})


def _sub(child_id: str, alias="sub", **config) -> Effect:
    return Effect(kind="subchain", alias=alias,
                  config={"automation_id": child_id, **config})


def _governed(alias="pay", action_id="issue_refund") -> Effect:
    return Effect(kind="kinetic_action", alias=alias,
                  config={"action_id": action_id, "params": {"amount": 10}})


def _automation(*effects, name="chain", cron="0 9 * * 1", fallback=None, **kw) -> Automation:
    return upsert_automation(Automation(
        name=name, conn_id="conn-sub",
        conditions=[Condition(kind="schedule", config={"cron": cron})],
        effects=list(effects), fallback_effect=fallback, max_retries=0, **kw))


class Dispatcher:
    """Stubs the leaf effects and delegates `subchain` to the REAL dispatcher.

    An injected dispatcher replaces the whole table, so a fixture that answered `subchain`
    itself would exercise nothing this wave wrote. Delegating keeps the nesting, the depth
    guard, the trace inheritance and the outcome mapping under test while the leaves stay
    inert — the same split B2's dry-run harness makes.
    """

    def __init__(self, approvals=(), fail=()):
        self.calls: list[str] = []
        self.traces: list[tuple[str, str]] = []      # (step alias, trace it ran under)
        self.approvals, self.fail = set(approvals), set(fail)

    def __call__(self, effect, automation) -> EffectOutcome:
        alias = effect.alias or effect.kind
        if effect.kind == "subchain":
            return _dispatch_subchain(effect, automation)
        self.calls.append(alias)
        self.traces.append((alias, _CHAIN.get().trace_id))
        if alias in self.approvals:
            return EffectOutcome(kind=effect.kind, target=alias, status="approval_required",
                                 message="needs a human")
        if alias in self.fail:
            return EffectOutcome(kind=effect.kind, target=alias, status="failed",
                                 message="nope")
        return EffectOutcome(kind=effect.kind, target=alias, status="executed",
                             message="sent", data={"ts": "1.1"})


def _run(automation, dispatch, **kw):
    return run_automation(automation, dispatch=dispatch, persist=True,
                          probe=lambda *a, **k: True,
                          sleeper=lambda _s: None, rng=lambda: 0.0, **kw)


# ── invoking ──────────────────────────────────────────────────────────────────

def test_a_chain_runs_another_chain_as_one_step():
    child = _automation(_post(alias="shared"), name="post with fallback")
    parent = _automation(_sub(child.id), _post(alias="after"), name="caller")
    d = Dispatcher()

    run = _run(parent, d)

    assert run.outcome == "fired"
    assert d.calls == ["shared", "after"]
    assert [o.status for o in run.effects] == ["executed", "executed"]
    # What the step publishes: facts ABOUT the nested run, for the steps that follow.
    sub = run.effects[0]
    assert sub.data["outcome"] == "fired"
    assert sub.data["executed"] == 1
    assert sub.data["run_id"] and sub.data["run_id"] != run.id


def test_the_child_does_not_re_ask_its_own_conditions():
    """The child's trigger is a Monday cron. A caller on any other day must still get it —
    a shared subchain that works one day a week is not shared."""
    child = _automation(_post(alias="shared"), name="mondays", cron="0 9 * * 1")
    parent = _automation(_sub(child.id), name="caller")
    d = Dispatcher()

    # No probe override on the child: it runs `manual`, so the cron is never consulted.
    run = run_automation(parent, dispatch=d, persist=True, probe=lambda *a, **k: True,
                         sleeper=lambda _s: None, rng=lambda: 0.0)
    assert run.effects[0].status == "executed"
    assert d.calls == ["shared"]


def test_a_disabled_child_is_skipped_not_failed():
    """`enabled=False` is a person saying this must not run. Being called is not an
    exemption — and reporting it as a FAILURE would fire the caller's fallback."""
    child = _automation(_post(alias="shared"), name="switched off")
    set_automation_enabled(child.id, False)
    parent = _automation(_sub(child.id), name="caller", fallback=_post(alias="oncall"))
    d = Dispatcher()

    run = _run(parent, d)
    assert run.effects[0].status == "skipped"
    assert "did not run" in run.effects[0].message
    assert run.fallback_used is False
    assert "oncall" not in d.calls


def test_a_failing_child_is_a_failing_step():
    child = _automation(_post(alias="shared"), name="broken")
    parent = _automation(_sub(child.id), name="caller")
    d = Dispatcher(fail=("shared",))

    run = _run(parent, d)
    # The child FIRED (its step failed, the chain did not), so the parent's step reports the
    # child ran and executed nothing — not a crash, and not a lie about success.
    assert run.effects[0].data["executed"] == 0


def test_a_dangling_reference_is_a_dispatch_error_not_a_crash():
    parent = _automation(_sub("no-such-automation"), name="caller")
    run = _run(parent, Dispatcher())
    assert run.effects[0].status == "dispatch_error"
    assert "may have been deleted" in run.effects[0].message


def test_a_step_after_a_subchain_can_guard_on_what_it_did():
    """`executed` exists so a caller can say "post the summary only if the shared chain
    actually did something"."""
    from aughor.automations.models import GuardClause

    child = _automation(_post(alias="shared"), name="quiet")
    parent = _automation(
        _sub(child.id),
        Effect(kind="slack_post", alias="after",
               config={"bot_id": "sb_1", "channel": "C1"},
               when=[GuardClause(left={"$from": "sub.executed"}, op="gt", right=0)]),
        name="caller")
    d = Dispatcher()

    run = _run(parent, d)
    assert [o.status for o in run.effects] == ["executed", "executed"]
    assert d.calls == ["shared", "after"]


# ── the receipt ───────────────────────────────────────────────────────────────

def test_two_chains_share_one_subchain():
    """The wave's receipt. One authored shape, two callers, and the shared chain's own run
    history shows both — which is the thing a copied-and-pasted shape can never show."""
    shared = _automation(_post(alias="shared"), name="post with fallback")
    morning = _automation(_sub(shared.id), name="morning report")
    evening = _automation(_sub(shared.id), _post(alias="extra"), name="evening report")
    d = Dispatcher()

    a = _run(morning, d)
    b = _run(evening, d)

    assert a.effects[0].status == "executed"
    assert b.effects[0].status == "executed"
    assert a.effects[0].data["run_id"] != b.effects[0].data["run_id"]
    # Two callers, two runs, one shared chain — visible in the SHARED chain's own history.
    shared_runs = get_runs(automation_id=shared.id, limit=10)
    assert len(shared_runs) == 2
    assert all(r.outcome == "fired" for r in shared_runs)


def test_one_trace_two_run_rows():
    """"Child outcomes fold into the parent trace" — the child's steps are written under the
    PARENT's trace id, so a nested chain is one waterfall. The run ROW stays its own."""
    child = _automation(_post(alias="shared"), name="shared")
    parent = _automation(_sub(child.id), _post(alias="after"), name="caller")
    d = Dispatcher()

    run = _run(parent, d)

    traces = dict(d.traces)
    assert traces["shared"] == run.id, "the child's step did not run under the parent's trace"
    assert traces["after"] == run.id
    # …and the child still has a row of its own, under a different id.
    child_run_id = run.effects[0].data["run_id"]
    assert child_run_id != run.id
    assert get_run(child_run_id) is not None


# ── cycles ────────────────────────────────────────────────────────────────────

def test_a_chain_cannot_be_its_own_subchain():
    a = _automation(_post(), name="loop")
    a = a.model_copy(update={"effects": [_sub(a.id)]})
    with pytest.raises(ValueError, match="would run itself"):
        upsert_automation(a)


def test_a_two_step_cycle_is_refused_at_save():
    b = _automation(_post(alias="b1"), name="B")
    a = _automation(_sub(b.id), name="A")
    # B is now edited to call A back — the edge that closes the loop is the one refused.
    closing = b.model_copy(update={"effects": [_sub(a.id)]})
    assert cycle_problem(closing) is not None
    with pytest.raises(ValueError, match="would run itself"):
        upsert_automation(closing)


def test_a_deeper_cycle_is_refused_too():
    c = _automation(_post(alias="c1"), name="C")
    b = _automation(_sub(c.id), name="B")
    a = _automation(_sub(b.id), name="A")
    with pytest.raises(ValueError):
        upsert_automation(c.model_copy(update={"effects": [_sub(a.id)]}))


def test_a_diamond_is_not_a_cycle():
    """Two steps calling the same subchain is the whole point of the wave. A cycle check
    that walked without a `seen` set would refuse it as a repeat visit."""
    shared = _automation(_post(alias="shared"), name="shared")
    mid_a = _automation(_sub(shared.id), name="A")
    mid_b = _automation(_sub(shared.id), name="B")
    top = Automation(name="top", conn_id="conn-sub",
                     conditions=[Condition(kind="schedule", config={"cron": "0 9 * * 1"})],
                     effects=[_sub(mid_a.id, alias="a"), _sub(mid_b.id, alias="b")])
    assert cycle_problem(top) is None
    upsert_automation(top)          # must not raise


def test_the_save_route_answers_a_cycle_with_422_not_500():
    """A refusal the author can act on must not arrive as "the server broke" — the same
    lesson `_validation_detail` was written for, one release later."""
    from fastapi.testclient import TestClient

    from aughor.api import app

    client = TestClient(app)
    b = _automation(_post(alias="b1"), name="B-route")
    a = _automation(_sub(b.id), name="A-route")

    r = client.put(f"/automations/{b.id}", json={
        "conn_id": "conn-sub", "name": "B-route",
        "conditions": [{"kind": "schedule", "config": {"cron": "0 9 * * 1"}}],
        "effects": [{"kind": "subchain", "alias": "back", "config": {"automation_id": a.id}}],
    })
    assert r.status_code == 422
    assert "would run itself" in str(r.json()["detail"])


def test_nesting_deeper_than_the_cap_is_refused_at_run_time():
    """Not the cycle guard — cycles are refused at save. This is the shape a cycle check
    cannot see: a legal tree built one honest edge at a time."""
    leaf = _automation(_post(alias="leaf"), name="leaf")
    current = leaf
    for i in range(MAX_SUBCHAIN_DEPTH + 2):
        current = _automation(_sub(current.id), name=f"level{i}")
    d = Dispatcher()

    _run(current, d)
    # It ran as deep as the cap allows and refused below it, rather than recursing away.
    assert d.calls == []
    deepest = [r for r in get_runs(limit=200) if any(
        o.status == "dispatch_error" and "nested deeper" in o.message for o in r.effects)]
    assert deepest, "nothing reported the depth refusal"


# ── DS-8 met DS-9 ─────────────────────────────────────────────────────────────

def test_a_child_that_pauses_parks_its_parent():
    child = _automation(_governed(), _post(alias="child_after"), name="needs a human")
    parent = _automation(_sub(child.id), _post(alias="parent_after"), name="caller")
    d = Dispatcher(approvals=("pay",))

    run = _run(parent, d)

    assert run.outcome == "paused"
    assert run.effects[0].status == "approval_required"
    assert "waiting on a human" in run.effects[0].message
    # The parent stopped: its own next step did NOT run.
    assert "parent_after" not in d.calls
    child_run_id = run.effects[0].data["child_run_id"]
    assert get_run(child_run_id).outcome == "paused"
    assert run.checkpoint["child_runs"] == [child_run_id]
    # …and the parent stages NO proposal of its own. The human is being asked by the CHILD;
    # a second row here would be a phantom approval for a step with no action to approve —
    # and, because nothing would ever resolve it, a parent that could never resume.
    from aughor.actions.inbox import proposals_for_run
    assert proposals_for_run(run.id) == []
    assert run.checkpoint["proposal_ids"] == []


def test_resolving_the_child_resumes_the_parent():
    from aughor.actions.inbox import _resolve_once, proposals_for_run

    child = _automation(_governed(), _post(alias="child_after"), name="needs a human")
    parent = _automation(_sub(child.id), _post(alias="parent_after"), name="caller")
    d = Dispatcher(approvals=("pay",))
    parked = _run(parent, d)
    child_run_id = parked.effects[0].data["child_run_id"]

    prop = proposals_for_run(child_run_id)[0]
    assert _resolve_once(prop.id, "executed", "person:amit")

    # Resuming the CHILD wakes the parent — nothing else knows the two are related.
    resume_run(child_run_id, dispatch=d, sleeper=lambda _s: None, rng=lambda: 0.0)

    done = get_run(parked.id)
    assert done.outcome == "fired"
    assert done.effects[0].status == "executed"
    assert "parent_after" in d.calls
    assert get_run(child_run_id).outcome == "fired"


def test_the_parent_stays_parked_while_its_child_still_waits():
    child = _automation(_governed(), name="needs a human")
    parent = _automation(_sub(child.id), _post(alias="parent_after"), name="caller")
    d = Dispatcher(approvals=("pay",))
    parked = _run(parent, d)

    assert resume_run(parked.id, dispatch=d, sleeper=lambda _s: None, rng=lambda: 0.0) is None
    assert get_run(parked.id).outcome == "paused"
    assert "parent_after" not in d.calls


def test_the_heartbeat_sweep_resolves_a_whole_nested_tower():
    """The sweep takes passes, not one walk: finishing a nested chain makes its PARENT
    resumable, and the parent may already have been visited and correctly skipped earlier in
    the same list."""
    from aughor.actions.inbox import _resolve_once, proposals_for_run
    from aughor.automations.engine import resume_parked_runs

    leaf = _automation(_governed(), _post(alias="leaf_after"), name="leaf")
    mid = _automation(_sub(leaf.id, alias="m"), name="mid")
    top = _automation(_sub(mid.id, alias="t"), _post(alias="top_after"), name="top")
    d = Dispatcher(approvals=("pay",))

    parked = _run(top, d)
    assert parked.outcome == "paused"

    leaf_run_id = get_run(parked.effects[0].data["child_run_id"]).effects[0].data["child_run_id"]
    _resolve_once(proposals_for_run(leaf_run_id)[0].id, "executed", "person:amit")

    # The sweep is the PRODUCTION path, so it resumes with the real dispatcher — the test
    # double is not in play here, and asserting on it would be asserting on the wrong thing.
    # What matters is that every level of the tower came unstuck on one sweep.
    assert resume_parked_runs() >= 1
    mid_run_id = parked.effects[0].data["child_run_id"]
    assert get_run(leaf_run_id).outcome == "fired"
    assert get_run(mid_run_id).outcome == "fired"
    top_run = get_run(parked.id)
    assert top_run.outcome == "fired"
    assert top_run.effects[0].status == "executed"
    # …and the step after the subchain was reached at last, whatever the real dispatcher
    # then made of it (there is no Slack bot in a unit test).
    assert len(top_run.effects) == 2
