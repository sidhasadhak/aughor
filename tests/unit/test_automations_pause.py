"""DS-8 — the durable pause: a chain that stops for a human, and picks itself back up.

Before this, an automation that reached an approval-gated write recorded
``approval_required`` on the run and **kept going**. Three things were wrong with that at
once, and each is locked below:

* There was no artefact to approve. The refusal was a status on a finished run; the only
  surface listing it linked to the automation, not to anything that could say yes.
* The chain ran on without it. Step 3 posted "the refund is issued" while step 2's refund
  sat refused — the failure mode a mid-chain approval exists to prevent.
* The run FINISHED. Nothing could ever continue it, because there was nothing left to
  continue: the accumulated context died with the tick.

The properties this file pins, each one something a plausible implementation gets wrong:

* **A parked run is not a finished run.** ``outcome="paused"``, and no ``finished_at`` —
  a run waiting two days on a person must not report a 40ms duration.
* **Prior steps never re-run.** The whole claim of the wave. Counted, not asserted about.
* **One run, with a human in its middle.** The resume lands in the SAME row, because the
  run id is the trace id and a second row would split one waterfall in two.
* **The pause never fires the fallback.** `approval_required` is not `executed`, so a
  chain whose only outward step parks satisfies "everything attempted failed" — and would
  page on-call to announce a human being asked a question. W1's lesson, one wave on.
* **Every resolution ends the wait.** Accept, reject AND expiry, because the run is
  blocked on the wait, not on the answer. A rejected write leaves its step `skipped` and
  the chain continues; a lapsed one must never strand the run at `paused` forever.
* **A run parked on two writes waits for both.** Resuming on the first answer would run
  the rest of the chain while a second governed write was still pending.
* **The gates do not strand a resume.** Pausing the automation after a human approved its
  pending write must not abandon the chain half-executed.
"""
from __future__ import annotations


from aughor.actions.inbox import _resolve_once, proposals_for_run, reject_proposal
from aughor.automations.engine import resume_run, run_automation
from aughor.routers import kinetic as actions_router
from aughor.automations.models import Automation, Condition, Effect, EffectOutcome
from aughor.automations.store import get_run, get_runs, upsert_automation


# ── fixtures ──────────────────────────────────────────────────────────────────

def _governed(alias="pay", action_id="issue_refund", **config) -> Effect:
    return Effect(kind="kinetic_action", alias=alias,
                  config={"action_id": action_id, "params": {"amount": 10}, **config})


def _post(alias="tell", **config) -> Effect:
    return Effect(kind="slack_post", alias=alias,
                  config={"bot_id": "sb_1", "channel": "C1", **config})


def _automation(*effects, fallback=None, scheduling="ordered", **kw) -> Automation:
    a = Automation(
        name="refund then tell", conn_id="conn-pause",
        conditions=[Condition(kind="schedule", config={"cron": "0 9 * * 1"})],
        effects=list(effects), fallback_effect=fallback, max_retries=0,
        scheduling=scheduling, **kw,
    )
    return upsert_automation(a)


class Dispatcher:
    """Records every dispatch, so "prior steps never re-run" is COUNTED, not asserted about.

    A mocked-out dispatcher is the only way to observe the property at all: an engine that
    quietly re-ran step 1 on resume would produce an identical-looking run row, and the
    only visible difference would be the second refund.
    """

    def __init__(self, approvals=("pay",), data=None):
        self.calls: list[str] = []
        self.approvals = set(approvals)
        self.data = data or {}

    def __call__(self, effect, automation) -> EffectOutcome:
        alias = effect.alias or effect.kind
        self.calls.append(alias)
        # `target` is the ACTION ID on a governed write, never the step alias — exactly what
        # `_dispatch_kinetic` records. This fixture used to set `target=alias`, and that one
        # convenience hid a real defect through a green suite: the resume republished the
        # approved step's output under its target, so `{"$from": "flag.id"}` on the next step
        # resolved nothing and the step skipped with "upstream data unavailable". A chain that
        # had just been approved, reported as a chain missing its input. Found by running the
        # product; the fixture agreed with the bug from both sides.
        target = effect.action_id if effect.kind == "kinetic_action" else alias
        if alias in self.approvals:
            return EffectOutcome(kind=effect.kind, target=target,
                                 status="approval_required",
                                 message="needs a human: refunds over $5")
        return EffectOutcome(kind=effect.kind, target=target, status="executed",
                             message="sent", data=self.data.get(alias, {"ts": "1.1"}))


def _run(automation, dispatch, **kw):
    return run_automation(automation, dispatch=dispatch, persist=True,
                          probe=lambda *a, **k: True,
                          sleeper=lambda _s: None, rng=lambda: 0.0, **kw)


def _resume(run_id, dispatch):
    return resume_run(run_id, dispatch=dispatch, sleeper=lambda _s: None, rng=lambda: 0.0)


def _resolve(proposal_id: str, status: str, *, outcome=None):
    """Resolve a proposal the way the inbox would, without standing up an ontology and a
    live executor. The accept path's own machinery is proven in the inbox's own suite;
    what DS-8 owns is what happens to the RUN once a proposal reaches a terminal state."""
    assert _resolve_once(proposal_id, status, "person:amit")
    if outcome is not None:
        from aughor.actions.inbox import _record_outcome
        _record_outcome(proposal_id, status, "approved", outcome)


# ── the pause ─────────────────────────────────────────────────────────────────

def test_a_governed_write_parks_the_run_and_stages_one_proposal():
    a = _automation(_governed(), _post())
    d = Dispatcher()
    run = _run(a, d)

    assert run.outcome == "paused"
    # The step after the approval did NOT run. This is the whole point: before DS-8 it did.
    assert d.calls == ["pay"]
    assert [o.status for o in run.effects] == ["approval_required"]

    props = proposals_for_run(run.id)
    assert len(props) == 1
    assert props[0].source == f"automation:{a.id}"
    assert props[0].call_id == "pay"
    assert props[0].status == "pending"
    # The resolved params, not the binding — a human weighs a value, not a reference.
    assert props[0].params == {"amount": 10}
    # And the run points back at the proposal, so the canvas can link the parked step to
    # the thing that resolves it.
    assert run.effects[0].data["proposal_id"] == props[0].id


def test_a_paused_run_has_not_finished():
    run = _run(_automation(_governed(), _post()), Dispatcher())
    assert run.finished_at is None
    # Round-trips: the checkpoint is worthless if it does not survive the process that
    # wrote it, and a store that silently drops an unmapped column is this repo's own
    # twice-learned failure (VA-9b's `agent_id`).
    stored = get_run(run.id)
    assert stored is not None and stored.finished_at is None
    assert stored.outcome == "paused"
    assert stored.checkpoint["next_index"] == 1
    assert stored.checkpoint["step_alias"] == "pay"
    assert stored.checkpoint["context"] == {}


def test_the_pause_does_not_fire_the_fallback():
    """W1's lesson, one wave on: `approval_required` is not `executed`, so a chain whose
    only outward step parks trivially satisfies "everything that tried, failed"."""
    a = _automation(_governed(), fallback=_post(alias="oncall"))
    d = Dispatcher()
    run = _run(a, d)

    assert run.outcome == "paused"
    assert run.fallback_used is False
    assert "oncall" not in d.calls


# ── the resume ────────────────────────────────────────────────────────────────

def test_accepting_resumes_the_same_run_and_never_re_runs_a_prior_step():
    a = _automation(_governed(), _post())
    d = Dispatcher()
    parked = _run(a, d)
    prop = proposals_for_run(parked.id)[0]

    _resolve(prop.id, "executed", outcome={"refund_id": "rf_9"})
    done = _resume(parked.id, d)

    assert done is not None
    assert done.id == parked.id                     # ONE run, with a human in its middle
    assert done.outcome == "fired"
    assert done.finished_at is not None
    # The governed step was NOT dispatched a second time; only the step after it ran.
    assert d.calls == ["pay", "tell"]
    assert [o.status for o in done.effects] == ["executed", "executed"]
    # And the record is one run, not two.
    assert len([r for r in get_runs(automation_id=a.id, limit=10)]) == 1


def test_the_resumed_chain_reads_the_approved_step_s_output():
    """The accept ran the write through the executor; its result has to reach the steps
    that bind to it, or the resume is only half a chain."""
    a = _automation(_governed(), _post(message={"$from": "pay.refund_id"}))
    d = Dispatcher()
    parked = _run(a, d)
    _resolve(proposals_for_run(parked.id)[0].id, "executed", outcome={"refund_id": "rf_9"})

    done = _resume(parked.id, d)
    assert [o.status for o in done.effects] == ["executed", "executed"]
    stored = get_run(done.id)
    assert stored.outcome == "fired"


def test_rejecting_through_the_door_ends_the_wait():
    """The DOOR. Driven through the route a surface actually presses, because that is where
    the two planes are allowed to meet — and because "the router remembered to call it" is
    the claim, not "the function exists". Asserts only that the run left `paused`: this path
    resumes through the production dispatcher, so what the second step does is another
    test's job."""
    from fastapi.testclient import TestClient

    from aughor.api import app

    a = _automation(_governed(), _post())
    parked = _run(a, Dispatcher())
    prop = proposals_for_run(parked.id)[0]

    r = TestClient(app).post(f"/kinetic-actions/inbox/{prop.id}/reject",
                             json={"actor": "person:amit"})
    assert r.status_code == 200 and r.json()["rejected"] is True

    done = get_run(parked.id)
    assert done.outcome != "paused"
    # A refusal is not a failure of the step: `skipped` is the engine's own word for
    # "did not run, and that is not this step's fault".
    assert done.effects[0].status == "skipped"


def test_the_resumed_context_is_keyed_by_the_step_alias_not_the_dispatch_target():
    """The defect the live run found. A dispatcher names `target` after the thing it
    dispatched — for a governed write that is the action id (`issue_refund`), not the step
    alias (`pay`) — so a resume that republished the approved result under `target` put it
    somewhere no binding could reach. The step waiting on it skipped for want of an upstream
    that had in fact just succeeded."""
    a = _automation(_governed(alias="pay"), _post(message={"$from": "pay.refund_id"}))
    d = Dispatcher()
    parked = _run(a, d)
    assert parked.effects[0].target == "issue_refund"       # the dispatcher's word
    _resolve(proposals_for_run(parked.id)[0].id, "executed", outcome={"refund_id": "rf_9"})

    done = _resume(parked.id, d)
    assert [o.status for o in done.effects] == ["executed", "executed"]
    assert d.calls == ["pay", "tell"]
    stored = get_run(done.id)
    assert stored.outcome == "fired"


def test_a_rejected_write_skips_its_step_and_the_chain_carries_on():
    a = _automation(_governed(), _post())
    d = Dispatcher()
    parked = _run(a, d)
    _resolve(proposals_for_run(parked.id)[0].id, "rejected")

    done = _resume(parked.id, d)
    assert done.outcome == "fired"
    assert [o.status for o in done.effects] == ["skipped", "executed"]
    assert d.calls == ["pay", "tell"]


def test_a_rejected_write_s_dependents_skip_rather_than_run_with_a_hole():
    a = _automation(_governed(), _post(message={"$from": "pay.refund_id"}))
    d = Dispatcher()
    parked = _run(a, d)
    assert reject_proposal(proposals_for_run(parked.id)[0].id, actor="person:amit") is True

    done = _resume(parked.id, d)
    assert done.outcome == "fired"
    assert [o.status for o in done.effects] == ["skipped", "skipped"]
    assert "upstream data unavailable" in done.effects[1].message


def test_an_expired_approval_never_leaves_the_run_paused():
    a = _automation(_governed(), _post())
    d = Dispatcher()
    parked = _run(a, d)
    prop = proposals_for_run(parked.id)[0]

    _resolve(prop.id, "expired")
    _resume(parked.id, d)

    done = get_run(parked.id)
    assert done.outcome == "fired"
    assert done.effects[0].status == "skipped"


def test_a_run_parked_on_two_writes_waits_for_both():
    a = _automation(_governed(alias="pay1"), _governed(alias="pay2"), _post())
    d = Dispatcher(approvals=("pay1", "pay2"))
    parked = _run(a, d)

    # The ordered walk stops at the FIRST approval, so only one proposal exists yet.
    assert parked.outcome == "paused"
    props = proposals_for_run(parked.id)
    assert len(props) == 1

    _resolve(props[0].id, "executed", outcome={"refund_id": "rf_1"})
    again = _resume(parked.id, d)
    # It parked again, at the second governed write — still one run.
    assert again.id == parked.id
    assert again.outcome == "paused"
    assert len(proposals_for_run(parked.id)) == 2

    pending = [p for p in proposals_for_run(parked.id) if p.status == "pending"]
    _resolve(pending[0].id, "executed", outcome={"refund_id": "rf_2"})
    done = _resume(parked.id, d)
    assert done.outcome == "fired"
    assert d.calls == ["pay1", "pay2", "tell"]


def test_resume_is_a_no_op_while_a_proposal_is_still_pending():
    a = _automation(_governed(), _post())
    d = Dispatcher()
    parked = _run(a, d)

    assert _resume(parked.id, d) is None
    assert get_run(parked.id).outcome == "paused"
    assert d.calls == ["pay"]                       # nothing ran on a premature wake


def test_a_second_resume_cannot_run_the_chain_twice():
    """The inbox resolves once; the run must move once. Two accepts landing together (an
    HTTP click and a Slack tap) both wake the run, and only one may continue it."""
    a = _automation(_governed(), _post())
    d = Dispatcher()
    parked = _run(a, d)
    _resolve(proposals_for_run(parked.id)[0].id, "executed", outcome={"refund_id": "rf_9"})

    first = _resume(parked.id, d)
    second = _resume(parked.id, d)

    assert first.outcome == "fired"
    assert second is None                           # not paused any more — nothing to resume
    assert d.calls == ["pay", "tell"]               # the post went out ONCE


def test_pausing_the_automation_does_not_strand_an_approved_write():
    """A resume is not gated. The human already said yes to a write this chain committed;
    abandoning the rest would leave a half-executed chain, which is worse than either
    finishing it or never having started."""
    a = _automation(_governed(), _post())
    d = Dispatcher()
    parked = _run(a, d)
    _resolve(proposals_for_run(parked.id)[0].id, "executed", outcome={"refund_id": "rf_9"})

    from aughor.automations.store import set_automation_enabled
    set_automation_enabled(a.id, False)

    done = _resume(parked.id, d)
    assert done.outcome == "fired"
    assert d.calls == ["pay", "tell"]


def test_deleting_an_automation_strands_neither_a_parked_run_nor_a_pending_proposal():
    """DS-8 is the first thing that ever makes an automation stage a proposal, so it is the
    first thing that could leave one behind: a pending approval for a chain that no longer
    exists, which a human could accept into a governed write nothing would ever consume.

    The cascade already existed at the delete ROUTE (A4's owner cascade) and this pins that
    it covers the new producer — the store drops the run, `purge_source` drops the proposal.
    Driven through the router, because the cascade lives there by design: the automations
    store must never import the actions plane."""
    from fastapi.testclient import TestClient

    from aughor.api import app

    a = _automation(_governed(), _post())
    parked = _run(a, Dispatcher())
    assert parked.outcome == "paused"
    assert len(proposals_for_run(parked.id)) == 1

    assert TestClient(app).delete(f"/automations/{a.id}").status_code == 200

    assert get_run(parked.id) is None
    assert proposals_for_run(parked.id) == []


def test_a_run_whose_automation_vanished_does_not_stay_paused_forever():
    """The backstop under the cascade above. `paused` is a claim that somebody can still act
    on this run; a run that can never continue must not keep making it."""
    a = _automation(_governed(), _post())
    d = Dispatcher()
    parked = _run(a, d)
    _resolve(proposals_for_run(parked.id)[0].id, "executed", outcome={})

    # Drop the automation row WITHOUT the store's own run cascade, which is the only way
    # this state is reachable — a torn delete, a restored backup, a hand-edited row.
    from aughor.automations import store as astore
    conn = astore._connect()
    conn.execute("DELETE FROM automations WHERE id = ?", (a.id,))
    conn.commit()
    conn.close()

    done = _resume(parked.id, d)
    assert done.outcome == "error"
    assert "deleted" in done.reason
    assert get_run(parked.id).outcome == "error"
    assert d.calls == ["pay"]


# ── the parallel frontier ─────────────────────────────────────────────────────

def test_a_parallel_frontier_stops_advancing_when_a_step_parks():
    a = _automation(_governed(), _post(alias="tell", message={"$from": "pay.refund_id"}),
                    scheduling="parallel")
    d = Dispatcher()
    parked = _run(a, d)

    assert parked.outcome == "paused"
    assert d.calls == ["pay"]
    assert parked.checkpoint["scheduling"] == "parallel"
    assert parked.checkpoint["done_aliases"] == ["pay"]

    _resolve(proposals_for_run(parked.id)[0].id, "executed", outcome={"refund_id": "rf_9"})
    done = _resume(parked.id, d)
    assert done.outcome == "fired"
    assert d.calls == ["pay", "tell"]
    assert [o.status for o in done.effects] == ["executed", "executed"]


def test_the_resumed_run_reassembles_its_effects_in_declared_order():
    """Every reader of a run's effects matches POSITIONS (DS-7). A resume that appended the
    new outcomes after the old ones would decorate the wrong cards on the canvas."""
    a = _automation(_post(alias="first"), _governed(alias="pay"), _post(alias="last"))
    d = Dispatcher()
    parked = _run(a, d)
    _resolve(proposals_for_run(parked.id)[0].id, "executed", outcome={"refund_id": "rf_9"})
    done = _resume(parked.id, d)

    # `pay` reports its ACTION ID, the other two their aliases — the real shapes.
    assert [o.target for o in done.effects] == ["first", "issue_refund", "last"]
    assert [o.status for o in done.effects] == ["executed", "executed", "executed"]


# ── the hooks ─────────────────────────────────────────────────────────────────

def test_the_heartbeat_resumes_a_run_no_surface_remembered_to_wake():
    """The completeness net. The routers resume immediately, but "whoever resolved it
    remembered" is a promise broken by ordinary things — a process that dies between the
    resolve and the resume, a proposal that lapses with nobody clicking. The heartbeat that
    already visits every automation checks for parked runs too, which is what makes the
    resume a property of the system rather than of a code path."""
    from aughor.automations.engine import resume_parked_runs

    a = _automation(_governed(), _post())
    parked = _run(a, Dispatcher())
    _resolve(proposals_for_run(parked.id)[0].id, "executed", outcome={"refund_id": "rf_9"})

    # Nobody called resume_run. The run is still parked.
    assert get_run(parked.id).outcome == "paused"
    assert resume_parked_runs() >= 1
    assert get_run(parked.id).outcome == "fired"


def test_the_sweep_leaves_a_run_that_is_still_waiting_alone():
    from aughor.automations.engine import resume_parked_runs

    a = _automation(_governed(), _post())
    parked = _run(a, Dispatcher())
    resume_parked_runs()
    assert get_run(parked.id).outcome == "paused"


def test_the_heartbeat_reports_what_it_resumed():
    """`tick_once` returns per-family counts so a caller holding an external clock can tell a
    tick that did something from one that found nothing. A resume is something."""
    from aughor.automations.scheduler import tick_once

    a = _automation(_governed(), _post())
    parked = _run(a, Dispatcher())
    _resolve(proposals_for_run(parked.id)[0].id, "executed", outcome={"refund_id": "rf_9"})

    counts = tick_once()
    assert counts["resumed"] >= 1
    assert get_run(parked.id).outcome == "fired"


def test_the_inbox_never_imports_the_automation_engine():
    """A depends on K; K reaching back closes the cycle H5 exists to keep open. There is a
    package-wide ratchet on this in the runners suite — this is the
    same law stated where DS-8's author will read it, because DS-8 is the wave that most
    wants to break it: the obvious place to resume a parked run is the accept that unblocked
    it, and that is precisely the import that must not exist.
    """
    import ast
    from pathlib import Path

    src = Path("aughor/actions/inbox.py").read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(n.name for n in node.names)
    assert not {m for m in imported if m.startswith("aughor.automations")}


def test_the_accept_route_resumes_the_parked_run(monkeypatch):
    """The router is where the two planes are allowed to meet. Proven at the door rather
    than by reading the code, because the whole point of moving the call here was that the
    door is what a surface actually presses."""
    woke: list[str] = []
    monkeypatch.setattr("aughor.automations.engine.resume_run",
                        lambda rid, **kw: woke.append(rid))

    a = _automation(_governed(), _post())
    parked = _run(a, Dispatcher())
    actions_router._resume_parked_run(proposals_for_run(parked.id)[0].id)
    assert woke == [parked.id]


def test_only_automation_sourced_proposals_reach_the_engine(monkeypatch):
    """An agent's proposal and an HTTP proposal have no run to resume; the door must not
    reach into the automations plane on every accept in the deployment."""
    from aughor.actions.inbox import stage_proposal, StagedProposal
    woke: list[str] = []
    monkeypatch.setattr("aughor.automations.engine.resume_run",
                        lambda rid, **kw: woke.append(rid))

    agent_prop = stage_proposal(StagedProposal(
        connection_id="conn-pause", action_id="issue_refund", params={},
        source="agent", run_id="", call_id="c1"))
    actions_router._resume_parked_run(agent_prop.id)
    actions_router._resume_parked_run("no-such-proposal")
    assert woke == []


def test_a_failing_resume_never_breaks_the_accept(monkeypatch):
    """By the time the door calls it, the governed write has already happened. Raising here
    would report a completed write as a failed one and invite a retry of it."""
    def _boom(_rid, **_kw):
        raise RuntimeError("store is down")

    monkeypatch.setattr("aughor.automations.engine.resume_run", _boom)
    a = _automation(_governed(), _post())
    parked = _run(a, Dispatcher())
    prop = proposals_for_run(parked.id)[0]
    actions_router._resume_parked_run(prop.id)      # must not raise
    assert get_run(parked.id).outcome == "paused"


# ── the queue ─────────────────────────────────────────────────────────────────

def test_one_approval_is_one_row_in_the_needs_human_queue():
    """DS-8 is the first wave in which an automation stages a proposal, so it is the first
    in which the attention strip's two independent sources can describe the SAME decision:
    Source A lists it as a pending proposal, Source C as a parked run. Listing both made one
    approval read as two items waiting — and the accept sat on only one of the two cards.

    The parked-run row is the one that survives: it names the automation, the chain and the
    step, and resolving it goes through the very same proposal Source A would have offered.
    """
    from fastapi.testclient import TestClient

    from aughor.api import app

    a = _automation(_governed(), _post())
    parked = _run(a, Dispatcher())
    prop = proposals_for_run(parked.id)[0]

    body = TestClient(app).get("/control-room/needs-human").json()
    mine = [r for r in body["rows"]
            if r.get("resolve", {}).get("proposal_id") == prop.id or r["id"] == prop.id]
    assert len(mine) == 1, [r["source"] for r in mine]
    assert mine[0]["source"] == "automation_approval"
    # …and it carries what makes the decision answerable, plus the id that resolves it.
    assert mine[0]["resolve"]["automation_id"] == a.id
    assert mine[0]["resolve"]["run_id"] == parked.id
    assert mine[0]["resolve"]["proposal_id"] == prop.id


def test_an_agent_s_proposal_still_gets_its_own_row():
    """The dedup must key on "a parked run speaks for this proposal", never on "the proposal
    came from an automation" — an automation-sourced proposal whose run has already finished
    has nothing else listing it, and dropping it would hide a real decision."""
    from fastapi.testclient import TestClient

    from aughor.actions.inbox import StagedProposal, stage_proposal
    from aughor.api import app

    loose = stage_proposal(StagedProposal(
        connection_id="conn-pause", action_id="issue_refund", params={},
        reasoning="staged by an agent, no run behind it", source="agent"))

    body = TestClient(app).get("/control-room/needs-human").json()
    assert [r for r in body["rows"] if r["id"] == loose.id and r["source"] == "kinetic_inbox"]
