"""Regression tests for the two explorer observability fixes.

F-phase-sync: _save_state() mirrors the LIVE self._status.phase into the persisted
  state on every save, so the exploration JSON reflects mid-run progress (it used to
  stay 'pending' until the terminal COMPLETE/FAILED write).
F-concurrency: explore() is a thin concurrency-bounded wrapper over _explore_run(),
  gated by a shared semaphore sized from AUGHOR_MAX_CONCURRENT_EXPLORERS.
"""
import asyncio

from aughor.explorer import agent as agent_mod
from aughor.explorer.agent import SchemaExplorer, _get_explorer_semaphore
from aughor.explorer.models import ExplorationPhase


def _bare_explorer():
    """A SchemaExplorer with just the attributes _save_state touches (no DB)."""
    ex = SchemaExplorer.__new__(SchemaExplorer)
    ex.canvas_id = None
    ex.connection_id = "testconn"
    ex._state = {"phase": "pending"}

    class _Status:
        phase = ExplorationPhase.DISTRIBUTION

    ex._status = _Status()
    return ex


def test_save_state_mirrors_live_phase(monkeypatch):
    ex = _bare_explorer()
    captured = {}
    monkeypatch.setattr(agent_mod._store, "save",
                        lambda cid, state: captured.update(cid=cid, state=dict(state)))
    ex._save_state()
    assert captured["cid"] == "testconn"
    # disk phase now tracks the live status phase, not the stale 'pending'
    assert captured["state"]["phase"] == ExplorationPhase.DISTRIBUTION.value


def test_save_state_accepts_plain_string_phase(monkeypatch):
    ex = _bare_explorer()
    ex._status.phase = "domain_intel"  # already a string (defensive)
    captured = {}
    monkeypatch.setattr(agent_mod._store, "save",
                        lambda cid, state: captured.update(state=dict(state)))
    ex._save_state()
    assert captured["state"]["phase"] == "domain_intel"


def test_explorer_semaphore_sized_from_env(monkeypatch):
    monkeypatch.setattr(agent_mod, "_MAX_CONCURRENT_EXPLORERS", 2)
    monkeypatch.setattr(agent_mod, "_explorer_semaphore", None)
    sem = _get_explorer_semaphore()
    assert isinstance(sem, asyncio.Semaphore)
    assert sem._value == 2
    # same instance reused on subsequent calls (shared cap, not per-explorer)
    assert _get_explorer_semaphore() is sem


def test_explore_wrapper_runs_under_semaphore(monkeypatch):
    """explore() must acquire the shared slot and delegate to _explore_run."""
    monkeypatch.setattr(agent_mod, "_explorer_semaphore", None)
    monkeypatch.setattr(agent_mod, "_MAX_CONCURRENT_EXPLORERS", 1)
    ex = SchemaExplorer.__new__(SchemaExplorer)
    ex.connection_id = "c"
    seen = {}

    async def fake_run(domain_intel_only=False):
        sem = _get_explorer_semaphore()
        seen["held_during_run"] = sem.locked()      # slot taken while running
        seen["domain_intel_only"] = domain_intel_only

    ex._explore_run = fake_run
    asyncio.run(ex.explore(domain_intel_only=True))
    assert seen["held_during_run"] is True
    assert seen["domain_intel_only"] is True
    # slot released after the run completes
    assert _get_explorer_semaphore().locked() is False
