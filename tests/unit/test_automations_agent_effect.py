"""Wave H1 — the schedule joint: an ``investigate`` effect that runs AS a user-agent.

The properties that carry the weight:

* **No ``agent_id`` ⇒ byte-identical.** The pre-H1 automation builds the same request and the
  same idempotency key, so an existing stored automation cannot change behaviour.
* **The persona reaches the ONE ask path**, not a second answer path — asserted by reading the
  ``AskRequest`` the work actually drains.
* **A refused binding is a ``dispatch_error`` carrying the authored sentence verbatim, and the
  work never runs.** The K2 property: a run that could not answer as the agent must say so in the
  run history rather than silently answering as nobody. This is the case a submitted background
  job would otherwise swallow — the tick would have already reported ``executed``.
* **The agent is part of the work's identity** — two personas asking one question are two
  investigations and must not deduplicate onto one idempotency key.

Hermetic: the kernel submit seam and ``build_ask_stream`` are both faked, so no investigation,
no LLM and no warehouse are touched.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aughor.automations.engine import _dispatch_investigate
from aughor.automations.models import Automation, Condition, Effect
from aughor.custom_agents import create_agent, delete_agent, list_agents, update_agent

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clean_agents():
    yield
    for a in list_agents():
        delete_agent(a.id)


@pytest.fixture(autouse=True)
def _agents_flag_on(monkeypatch):
    """H1 rides `agents.user_defined`; the flag-off case is asserted explicitly below."""
    import aughor.kernel.flags as flags
    monkeypatch.setattr(flags, "flag_enabled",
                        lambda name: True if name == "agents.user_defined" else False)


def _automation(**kw) -> Automation:
    base = dict(
        conn_id="conn-h1", name="Nightly analyst",
        conditions=[Condition(kind="schedule", config={"cron": "0 9 * * *"})],
        effects=[Effect(kind="notify", config={"trigger_id": "t1"})],
    )
    base.update(kw)
    return Automation(**base)


def _capture_submit(monkeypatch, *, job_id="job-1"):
    """Capture the work callable instead of running it; returns the holder list."""
    captured: list = []

    def fake_submit(kind, work, *, conn_id="", idempotency_key="", **kw):
        captured.append({"kind": kind, "work": work, "conn_id": conn_id, "idem": idempotency_key})
        return job_id

    monkeypatch.setattr("aughor.kernel.jobs.submit_background_tick", fake_submit)
    return captured


def _capture_ask(monkeypatch):
    """Fake the ask path; returns the list the drained AskRequest lands in."""
    seen: list = []

    def fake_stream(req, request):
        seen.append(req)

        async def _gen():
            return
            yield  # pragma: no cover - never reached; makes this an async generator

        return _gen()

    monkeypatch.setattr("aughor.routers.investigations.build_ask_stream", fake_stream)
    return seen


# ── the unbound path is untouched ────────────────────────────────────────────────

def test_an_investigate_effect_without_an_agent_is_byte_identical(monkeypatch):
    submitted = _capture_submit(monkeypatch)
    seen = _capture_ask(monkeypatch)
    a = _automation()
    effect = Effect(kind="investigate", config={"question": "why did refunds spike?"})

    outcome = _dispatch_investigate(effect, a)
    submitted[0]["work"]()

    assert outcome.status == "executed"
    assert outcome.message == "job job-1"          # no " as agent …" suffix
    assert submitted[0]["idem"] == f"automation:{a.id}:investigate"
    assert seen[0].agent_id is None
    assert seen[0].depth == "deep"


# ── the joint: the persona reaches the one ask path ──────────────────────────────

def test_a_bound_agent_reaches_the_ask_path_and_is_named_in_the_run_history(monkeypatch):
    agent = create_agent(name="Customer Analyst", instructions="Segment by cohort first.")
    submitted = _capture_submit(monkeypatch)
    seen = _capture_ask(monkeypatch)
    a = _automation()
    effect = Effect(kind="investigate",
                    config={"question": "why did churn move?", "agent_id": agent.id})

    outcome = _dispatch_investigate(effect, a)
    submitted[0]["work"]()

    assert outcome.status == "executed"
    assert agent.id in outcome.message, "the run history does not say which agent answered"
    # The persona is a PARAMETER on the one door — not a second answer path.
    assert seen[0].agent_id == agent.id
    assert seen[0].connection_id == "conn-h1"
    assert seen[0].depth == "deep"


def test_the_agent_is_part_of_the_works_identity(monkeypatch):
    """Two personas asking one question are two investigations — they must not dedupe."""
    one = create_agent(name="Analyst A")
    two = create_agent(name="Analyst B")
    submitted = _capture_submit(monkeypatch)
    _capture_ask(monkeypatch)
    a = _automation()
    q = {"question": "why did churn move?"}

    _dispatch_investigate(Effect(kind="investigate", config={**q, "agent_id": one.id}), a)
    _dispatch_investigate(Effect(kind="investigate", config={**q, "agent_id": two.id}), a)

    assert submitted[0]["idem"] != submitted[1]["idem"]
    assert one.id in submitted[0]["idem"] and two.id in submitted[1]["idem"]


# ── fail-closed: a refused binding is reported, never silently unbound ───────────

def test_a_conflicting_connection_binding_refuses_with_the_authored_sentence(monkeypatch):
    """The agent is bound to another connection: the automation must NOT answer as nobody."""
    agent = create_agent(name="Finance Analyst", connection_id="conn-other")
    submitted = _capture_submit(monkeypatch)
    a = _automation(conn_id="conn-h1")
    effect = Effect(kind="investigate",
                    config={"question": "why did margin drop?", "agent_id": agent.id})

    outcome = _dispatch_investigate(effect, a)

    assert outcome.status == "dispatch_error"
    assert "conn-other" in outcome.message and "conn-h1" in outcome.message
    assert submitted == [], "a refused binding still submitted the work"


def _disabled_agent():
    agent = create_agent(name="Retired")
    return update_agent(agent.id, enabled=False)


@pytest.mark.parametrize("make,expected", [
    (_disabled_agent, "disabled"),
    (lambda: None, "No such agent"),
])
def test_an_unrunnable_agent_is_a_dispatch_error_not_a_quiet_unbound_run(monkeypatch, make,
                                                                        expected):
    agent = make()
    submitted = _capture_submit(monkeypatch)
    effect = Effect(kind="investigate",
                    config={"question": "q", "agent_id": agent.id if agent else "ghost"})

    outcome = _dispatch_investigate(effect, _automation())

    assert outcome.status == "dispatch_error"
    assert expected in outcome.message
    assert submitted == []


def test_the_flag_being_off_refuses_the_run_rather_than_dropping_the_persona(monkeypatch):
    """Fail-closed on the flag too: an agent-bound automation with `agents.user_defined` off
    must not degrade into an anonymous investigation that looks like it worked."""
    agent = create_agent(name="Customer Analyst")
    import aughor.kernel.flags as flags
    monkeypatch.setattr(flags, "flag_enabled", lambda name: False)
    submitted = _capture_submit(monkeypatch)
    effect = Effect(kind="investigate", config={"question": "q", "agent_id": agent.id})

    outcome = _dispatch_investigate(effect, _automation())

    assert outcome.status == "dispatch_error"
    assert "agents.user_defined" in outcome.message
    assert submitted == []
