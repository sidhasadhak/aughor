"""Wave H3 — an agent's run view counts everything it did, and says what it cannot measure.

The pre-check found the per-agent view was undercounting for two independent reasons, and
fixing either alone would still have undercounted:

* :func:`save_chat_turn` never wrote ``agent_id`` at all — the column existed and defaulted
  to ``''`` — so a quick answer was attributable to nobody.
* :func:`list_investigations_for_agent` filtered ``kind = 'investigation'``, so even a
  correctly stamped chat turn was excluded from the list.

Together they meant an agent asked twenty quick questions reported one run, or none. A page
that states a small number confidently is worse than one that says it cannot tell — which is
also why ``spend`` reports ``measured: False`` rather than zeros when the session log is off.
"""
from __future__ import annotations

import uuid

import pytest

from aughor.db.history import (
    create_investigation, list_investigations_for_agent, save_chat_turn,
)
from aughor.custom_agents.context import activate_agent, release_agent
from aughor.custom_agents.models import UserAgent


@pytest.fixture
def persona():
    """A fresh persona id per test: the history store is shared across the session, so
    isolation comes from the key rather than from deleting another test's rows."""
    agent = UserAgent(id=f"ua_h3_{uuid.uuid4().hex[:8]}", name="Run View Agent")
    token = activate_agent(agent)
    try:
        yield agent
    finally:
        release_agent(token)


def _chat(question: str, session_id: str = "s1") -> str:
    return save_chat_turn(question=question, connection_id="conn-h3", headline=f"h:{question}",
                          sql="SELECT 1", session_id=session_id)


# ── the write half ──────────────────────────────────────────────────────────────────

def test_a_quick_answer_records_the_persona_that_gave_it(persona):
    """The column was never written on a chat row before H3, so every quick answer an
    agent gave was attributable to nobody."""
    _chat("how many customers?")
    runs = list_investigations_for_agent(persona.id)
    assert [r["question"] for r in runs] == ["how many customers?"]


def test_an_unbound_quick_answer_stays_unattributed():
    """No persona active: crediting it to anyone would invent history."""
    unused = f"ua_never_{uuid.uuid4().hex[:8]}"
    _chat("anonymous question", session_id=f"s-anon-{uuid.uuid4().hex[:6]}")
    assert list_investigations_for_agent(unused) == []


# ── the read half ───────────────────────────────────────────────────────────────────

def test_the_run_list_counts_quick_answers_and_deep_runs_together(persona):
    """The failure this wave exists to fix: a page that shows 1 run for an agent that
    answered many is worse than one that says it cannot tell."""
    create_investigation("deep question", "conn-h3", agent_id=persona.id)
    _chat("quick one", session_id="s-a")
    _chat("quick two", session_id="s-b")

    runs = list_investigations_for_agent(persona.id)
    kinds = sorted(r["kind"] for r in runs)
    assert kinds == ["chat", "chat", "investigation"]


def test_a_conversation_is_one_run_not_one_per_turn(persona):
    """Chat turns roll up to their session, exactly as the main history page does — a
    twenty-turn conversation is one run the user had."""
    for i in range(3):
        _chat(f"turn {i}", session_id="s-same")

    runs = list_investigations_for_agent(persona.id)
    assert len(runs) == 1
    assert runs[0]["query_count"] == 3


def test_another_agents_runs_are_not_this_agents_history(persona):
    _chat("mine", session_id="s-mine")
    other = UserAgent(id=f"ua_other_{uuid.uuid4().hex[:8]}", name="Other")
    token = activate_agent(other)
    try:
        _chat("theirs", session_id="s-theirs")
    finally:
        release_agent(token)

    assert [r["question"] for r in list_investigations_for_agent(persona.id)] == ["mine"]
    assert [r["question"] for r in list_investigations_for_agent(other.id)] == ["theirs"]


def test_runs_are_newest_first(persona):
    create_investigation("older deep", "conn-h3", agent_id=persona.id)
    _chat("newer quick", session_id="s-new")
    runs = list_investigations_for_agent(persona.id)
    assert [r.get("started_at") for r in runs] == sorted(
        [r.get("started_at") for r in runs], reverse=True)


# ── spend: unmeasured is not zero ───────────────────────────────────────────────────

def test_spend_reads_the_agent_axis(monkeypatch):
    import aughor.obs.usage as usage
    monkeypatch.setattr(usage, "usage_report", lambda **kw: _FakeReport())
    from aughor.routers.agents import _agent_spend

    spend = _agent_spend("ua_h3")
    assert spend == {"measured": True, "calls": 4, "total_tokens": 900, "cost_usd": 0.02,
                     "cost_is_complete": True, "failure_rate": 0.0}


def test_an_agent_with_no_recorded_calls_is_zero_not_missing(monkeypatch):
    """Recording is permanent, so an empty slice is a confident zero — not an
    unmeasured one. That distinction used to need a flag; now it is structural."""
    import aughor.obs.usage as usage
    monkeypatch.setattr(usage, "usage_report", lambda **kw: _FakeReport())
    from aughor.routers.agents import _agent_spend

    spend = _agent_spend("ua_never_ran")
    assert spend["measured"] is True and spend["calls"] == 0


class _FakeReport:
    def to_dict(self) -> dict:
        return {"rows": [{"agent_id": "ua_h3", "calls": 4, "total_tokens": 900,
                          "cost_usd": 0.02, "cost_is_complete": True, "failure_rate": 0.0}]}
