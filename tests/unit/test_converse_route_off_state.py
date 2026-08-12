"""The off-state contract for `ask.converse` — the claim that protects every current user.

`_stream_converse` is a THIRD body behind `/ask`. The flag is an EXPERIMENT and default off,
so the only promise that matters to anyone not opted in is that the door behaves exactly as
it did before this branch existed.

The pre-existing `test_converse_is_off_by_default` checks that `converse_available()` returns
False. That is the flag, not the door — it would keep passing if the route branched on
something else entirely. What follows pins the ROUTE: with the flag off, the converse body is
not merely unlikely, it is unreachable, and no argument the client can send reaches it.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from aughor.routers.investigations import _converse_eligible


def _req(**kw):
    """A request shaped like the /ask body, defaulting to the most converse-friendly case."""
    base = dict(escalate=False, insight_id=None, seed_sql=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _route(depth="quick", forced=None):
    return SimpleNamespace(depth=depth, forced=forced)


@pytest.fixture(autouse=True)
def _flag_off(monkeypatch):
    monkeypatch.delenv("AUGHOR_ASK_CONVERSE", raising=False)


def test_the_flag_off_makes_converse_unreachable(monkeypatch):
    """The headline. Off means the door cannot reach the new body — for ANY request shape."""
    for req in (_req(), _req(escalate=True), _req(insight_id="i1"), _req(seed_sql="SELECT 1")):
        for depth in ("quick", "deep", "overview"):
            assert _converse_eligible(req, _route(depth)) is False, (
                f"converse was reachable with the flag OFF: depth={depth} req={req}")


def test_the_flag_on_actually_reaches_it(monkeypatch):
    """The vacuity guard. If this fails, the test above proves nothing — a predicate that
    is always False would satisfy it while the feature is simply dead."""
    monkeypatch.setenv("AUGHOR_ASK_CONVERSE", "1")

    assert _converse_eligible(_req(), _route("quick")) is True


def test_the_flag_is_read_per_call_not_per_process(monkeypatch):
    """A module-level flag read makes the experiment unflippable in a running process and
    turns `monkeypatch.setenv` into a no-op — the trap that once had this suite spending the
    real LLM budget. Flipping it twice in one process is the only way to prove otherwise."""
    monkeypatch.setenv("AUGHOR_ASK_CONVERSE", "1")
    assert _converse_eligible(_req(), _route("quick")) is True

    monkeypatch.delenv("AUGHOR_ASK_CONVERSE")
    assert _converse_eligible(_req(), _route("quick")) is False


def test_an_escalation_keeps_the_deterministic_body(monkeypatch):
    """Even flag-ON, the explicit "investigate deeper" is a command, not a question —
    it keeps the investigation body. (The dossier-drill and seeded-SQL carve-outs
    dissolved in CI-4: those turns now hand their origin TO the conversation; their
    flag-ON contract lives in test_ci4_depth_as_tool.py.)"""
    monkeypatch.setenv("AUGHOR_ASK_CONVERSE", "1")

    assert _converse_eligible(_req(escalate=True), _route("quick")) is False


def test_deep_still_belongs_to_the_investigation_path(monkeypatch):
    """Converse is a quick-body peer. A router-chosen deep route has its own body and
    its own receipts — the dossier-forced case is the one exception (CI-4)."""
    monkeypatch.setenv("AUGHOR_ASK_CONVERSE", "1")

    assert _converse_eligible(_req(), _route("deep")) is False
