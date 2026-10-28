"""The ineligible-turn contract of `/ask`'s converse door — what outlived `ask.converse`'s off path.

`_stream_converse` is a THIRD body behind `/ask`. The flag `ask.converse` (default-ON since SP-14,
made unconditional 2026-10-28, ROADMAP §3.65) is gone; its off path lives on as the ineligible-turn
fallback: a coder binding that cannot make a tool call (PENDING item 17) gets the pre-converse door.
What follows pins the ROUTE, not the predicate's input: with such a binding the converse body is
unreachable for any request shape, and with one that calls tools it is reached.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from aughor.agent import converse_tools as ct
from aughor.routers.investigations import _converse_eligible


def _req(**kw):
    """A request shaped like the /ask body, defaulting to the most converse-friendly case."""
    base = dict(escalate=False, insight_id=None, seed_sql=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _route(depth="quick", forced=None):
    return SimpleNamespace(depth=depth, forced=forced)


@pytest.fixture
def calls_tools(monkeypatch):
    """Whether the coder binding can make a tool call — read by the door at call time."""
    state = {"value": True}
    monkeypatch.setattr(ct, "binding_calls_tools", lambda: state["value"])
    return state


def test_a_binding_that_cannot_call_tools_makes_converse_unreachable(calls_tools):
    """The headline. The door cannot reach the conversation for ANY request shape."""
    calls_tools["value"] = False
    for req in (_req(), _req(escalate=True), _req(insight_id="i1"), _req(seed_sql="SELECT 1")):
        for depth in ("quick", "deep", "overview"):
            assert _converse_eligible(req, _route(depth)) is False, (
                f"converse was reachable with a binding that cannot call tools: depth={depth} req={req}")


def test_a_binding_that_calls_tools_actually_reaches_it(calls_tools):
    """The vacuity guard. If this fails, the test above proves nothing — a predicate that
    is always False would satisfy it while the feature is simply dead."""
    assert _converse_eligible(_req(), _route("quick")) is True


def test_the_binding_is_read_per_call_not_per_process(calls_tools):
    """A module-level read would fix the answer for the life of the process — a binding that
    refused a tool call on one turn must route the next one to the quick body."""
    assert _converse_eligible(_req(), _route("quick")) is True
    calls_tools["value"] = False
    assert _converse_eligible(_req(), _route("quick")) is False


def test_an_escalation_keeps_the_deterministic_body(calls_tools):
    """The explicit "investigate deeper" is a command, not a question — it keeps the
    investigation body. (The dossier-drill and seeded-SQL carve-outs dissolved in CI-4: those
    turns now hand their origin TO the conversation; that contract lives in
    test_ci4_depth_as_tool.py.)"""
    assert _converse_eligible(_req(escalate=True), _route("quick")) is False


def test_deep_still_belongs_to_the_investigation_path(calls_tools):
    """Converse is a quick-body peer. A router-chosen deep route has its own body and
    its own receipts — the dossier-forced case is the one exception (CI-4)."""
    assert _converse_eligible(_req(), _route("deep")) is False
