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
    ex.schema_name = None
    ex._store_key = "testconn"   # connection-level run keys state by the bare connection id
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


def test_schema_scoped_run_keys_state_by_conn_and_schema(monkeypatch):
    # A per-schema run must persist state under {conn}__{schema} so each schema of a
    # multi-schema connection gets its OWN exploration state (the missimi=0 fix).
    ex = SchemaExplorer.__new__(SchemaExplorer)
    ex.canvas_id = None
    ex.connection_id = "workspace"
    ex.schema_name = "missimi"
    ex._store_key = "workspace__missimi"

    class _Status:
        phase = ExplorationPhase.DOMAIN_INTEL

    ex._status = _Status()
    ex._state = {"phase": "pending"}
    captured = {}
    monkeypatch.setattr(agent_mod._store, "save",
                        lambda cid, state: captured.update(cid=cid))
    ex._save_state()
    assert captured["cid"] == "workspace__missimi"


def test_leaks_schema_drops_cross_schema_sql():
    # A schema-scoped run must reject SQL that escapes its schema (the scoped DuckDB can
    # still execute another schema's tables).
    ex = SchemaExplorer.__new__(SchemaExplorer)
    ex.schema_name = "bakehouse"
    assert ex._leaks_schema("SELECT * FROM missimi.orders") is True
    assert ex._leaks_schema("SELECT * FROM bakehouse.sales_transactions b JOIN bakehouse.suppliers s ON 1=1") is False
    ex.schema_name = None   # connection-level run never restricts
    assert ex._leaks_schema("SELECT * FROM missimi.orders") is False


def test_save_state_accepts_plain_string_phase(monkeypatch):
    ex = _bare_explorer()
    ex._status.phase = "domain_intel"  # already a string (defensive)
    captured = {}
    monkeypatch.setattr(agent_mod._store, "save",
                        lambda cid, state: captured.update(state=dict(state)))
    ex._save_state()
    assert captured["state"]["phase"] == "domain_intel"


def test_cancelled_run_marks_status_terminal(monkeypatch):
    """Tier-0 #1 (the budget-cancel WEDGE): a CancelledError mid-run must leave the in-memory
    status TERMINAL (FAILED), not stuck at domain_intel — otherwise the next start/spawn sees a
    stale 'still running' explorer and refuses. Drive a cancel in Phase 8 and assert the handler
    marks it terminal."""
    import pytest

    ex = SchemaExplorer.__new__(SchemaExplorer)
    ex.connection_id = "c"
    ex.schema_name = None
    ex._store_key = "c"
    ex._state = {}
    ex._rate_seconds = 0

    class _Status:
        phase = ExplorationPhase.PENDING
        error = None
        domain_intel_skipped = False
        domain_intel_note = None
        tables_total = columns_total = joins_total = 0

    ex._status = _Status()
    monkeypatch.setattr(ex, "_load_profiler_data", lambda: ({"t": object()}, {}, {"joins": []}))
    monkeypatch.setattr(ex, "_compute_time_window", lambda *a, **k: None)
    monkeypatch.setattr(ex, "_compute_macro_context", lambda *a, **k: None)
    monkeypatch.setattr(ex, "_save_state", lambda: None)
    monkeypatch.setattr(ex, "_journal", lambda *a, **k: None)

    async def _cancel(*a, **k):
        raise asyncio.CancelledError()

    monkeypatch.setattr(ex, "_phase8_domain_intelligence", _cancel)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(ex._explore_run(domain_intel_only=True))   # skips 3-7, cancels in Phase 8

    assert ex._status.phase == ExplorationPhase.FAILED          # terminal, not stuck at domain_intel
    assert "cancelled" in (ex._status.error or "").lower()


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
