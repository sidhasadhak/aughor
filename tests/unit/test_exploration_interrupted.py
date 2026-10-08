"""A run a restart killed says it was interrupted — never that it is running (2026-10-07).

theLook's exploration stopped at `synthesis` on 2026-09-28: the restart came inside its job's lease,
boot recovery read the job as another process's and skipped it, the supervisor then swept it as stale
without resuming it — and the badge pulsed "Synthesis" for ten days over a run nothing was running.
Each dataset of the workspace sat the same way. Automatic re-runs wait for the exploration
principles (`docs/EXPLORATION_PRINCIPLES_2026-10-07.md`); what this holds is the honest status and a
person's Continue, which resumes each interrupted dataset from its saved progress.
"""
from __future__ import annotations

import asyncio

import pytest

from aughor.explorer import store as expl_store
from aughor.routers import exploration as X


@pytest.fixture
def stuck(monkeypatch):
    """`wh` ran per dataset: `sales` stopped mid-run, `ops` finished. Nothing is running either."""
    expl_store.save("wh__sales", {**expl_store._empty(), "phase": "synthesis"})
    expl_store.save("wh__ops", {**expl_store._empty(), "phase": "complete"})
    monkeypatch.setattr(X, "_exploration_jobs", lambda conn, active: [] if active else [
        {"state": "INTERRUPTED", "ended_at": "2026-09-28T01:23:43+00:00"}])
    yield "wh"
    for k in ("wh__sales", "wh__ops"):
        expl_store._family().purge_entries(exact=[k])


def test_a_run_nothing_is_running_reads_as_interrupted_with_when_and_where(stuck):
    assert X.interrupted_runs(stuck) == ["wh__sales"]
    status = X.get_exploration_status(stuck)
    assert status["interrupted"] is True and status["interrupted_schemas"] == ["sales"]
    assert "2026-09-28" in status["interrupted_note"] and "Continue" in status["interrupted_note"]
    assert X.get_exploration_status(stuck, schema="ops")["interrupted"] is False


def test_a_run_another_process_holds_is_never_called_interrupted(stuck, monkeypatch):
    monkeypatch.setattr(X, "_exploration_jobs", lambda conn, active: [{"state": "RUNNING"}])
    assert X.interrupted_runs(stuck) == []
    assert X.get_exploration_status(stuck)["interrupted"] is False


def test_continue_resumes_each_interrupted_dataset_by_its_own_key(stuck, monkeypatch):
    calls = []

    async def spawn(conn_id, **kw):
        calls.append((conn_id, kw.get("schema_name")))
        return {"ok": True, "reason": None, "job_id": "j1"}

    monkeypatch.setattr(X, "spawn_explorer", spawn)
    out = asyncio.run(X.resume_exploration(stuck))
    assert out == {"ok": True, "resumed": 1}
    assert calls == [("wh", "sales")], "a connection-level resume would start a fresh connection-wide run"


def test_a_restart_resumes_a_datasets_run_by_its_own_key(stuck, monkeypatch):
    """Boot recovery respawned the BARE connection key — a fresh connection-wide run — so the
    dataset's own run stayed mid-phase for good. The job now carries its dataset."""
    from types import SimpleNamespace

    import aughor.api as api
    calls = []

    async def spawn(conn_id, **kw):
        calls.append((conn_id, kw.get("schema_name")))
        return {"ok": True, "reason": None, "job_id": "j2"}

    async def no_investigations():
        return None

    monkeypatch.setattr("aughor.routers._shared.spawn_explorer", spawn)
    monkeypatch.setattr("aughor.kernel.jobs.kernel", lambda: SimpleNamespace(boot_recovery=lambda: [
        {"conn_id": "wh", "canvas_id": None, "payload": {"schema_name": "sales"}},
        {"conn_id": "wh", "canvas_id": None, "payload": {"schema_name": "ops"}}]))
    monkeypatch.setattr(api, "_recover_orphaned_investigations", no_investigations)
    asyncio.run(api._kernel_boot_recovery())
    assert calls == [("wh", "sales")], "ops finished; sales resumes on its own key"
