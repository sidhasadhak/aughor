"""R12 — connection/canvas birth as ONE observable kernel job (flag `birth.job`).

The knowledge/start-mining analog: eager intelligence (profiles → ontology →
doc tree → column config) first, then the exploration handoff — each step a
`birth.step` event on the K2 spine, the whole rite one supervised "profile"
job under the Curator charter. Off by default: kicks stay exploration-only.

Hermetic: fake connections + recorder coroutines; the ledger is the per-session
temp system.db from conftest.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from aughor.routers import _shared


class _FakeDB:
    def __init__(self, ok: bool = True, raise_on_build: bool = False):
        self._ok = ok
        self._raise = raise_on_build
        self.built = False
        self.closed = False
        self.last_build = None

    def build_intelligence(self):
        if self._raise:
            raise RuntimeError("boom")
        self.built = True
        self.last_build = {"ok": self._ok, "stage": None if self._ok else "ontology",
                           "error": None if self._ok else "too sparse"}
        return "SCHEMA"

    def close(self):
        self.closed = True


def _step(summary: dict, step: str) -> list[str]:
    return [s["status"] for s in summary["steps"] if s["step"] == step]


@pytest.mark.anyio
async def test_run_birth_happy_path(monkeypatch):
    db = _FakeDB()
    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda cid: db)
    spawned = {}

    async def _fake_spawn(conn_id, **kw):
        spawned.update({"conn_id": conn_id, **kw})
        return {"ok": True, "reason": None, "job_id": "job-123"}

    monkeypatch.setattr(_shared, "spawn_explorer", _fake_spawn)

    summary = await _shared.run_birth("connA")

    assert db.built and db.closed
    assert _step(summary, "intelligence") == ["started", "done"]
    assert _step(summary, "exploration") == ["started", "done"]
    assert spawned["conn_id"] == "connA"

    # The rite is journaled on the K2 spine — steps + the terminal summary.
    from aughor.kernel.ledger import Ledger
    kinds = [e["kind"] for e in Ledger.default().events(conn_id="connA", limit=20)]
    assert "birth.step" in kinds
    assert "birth.done" in kinds


@pytest.mark.anyio
async def test_run_birth_intelligence_failure_still_explores(monkeypatch):
    db = _FakeDB(raise_on_build=True)
    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda cid: db)

    async def _fake_spawn(conn_id, **kw):
        return {"ok": True, "reason": None, "job_id": "job-9"}

    monkeypatch.setattr(_shared, "spawn_explorer", _fake_spawn)

    summary = await _shared.run_birth("connB")   # must not raise
    assert _step(summary, "intelligence") == ["started", "failed"]
    assert _step(summary, "exploration") == ["started", "done"]
    assert db.closed                              # the connection is released on failure too


@pytest.mark.anyio
async def test_run_birth_raises_only_when_nothing_accomplished(monkeypatch):
    db = _FakeDB(raise_on_build=True)
    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda cid: db)

    async def _fake_spawn(conn_id, **kw):
        raise RuntimeError("spawn down")

    monkeypatch.setattr(_shared, "spawn_explorer", _fake_spawn)
    with pytest.raises(RuntimeError):
        await _shared.run_birth("connC")


@pytest.mark.anyio
async def test_run_birth_schema_scoped_open(monkeypatch):
    db = _FakeDB()
    opened = {}

    def _open_with_schema(cid, schema):
        opened["schema"] = schema
        return db

    monkeypatch.setattr("aughor.db.connection.open_connection_for_with_schema", _open_with_schema)

    async def _fake_spawn(conn_id, **kw):
        return {"ok": True, "reason": None, "job_id": "j"}

    monkeypatch.setattr(_shared, "spawn_explorer", _fake_spawn)
    await _shared.run_birth("connD", schema_name="sales_schema")
    assert opened["schema"] == "sales_schema"


# ── kickoff elevation: flag off → explorer, flag on → birth ──────────────────

@pytest.mark.anyio
async def test_kickoff_spawns_explorer_when_flag_off(monkeypatch):
    calls = {"birth": 0, "explore": 0}

    async def _fake_birth(conn_id, **kw):
        calls["birth"] += 1
        return {"ok": True, "job_id": "b"}

    async def _fake_spawn(conn_id, **kw):
        calls["explore"] += 1
        return {"ok": True, "reason": None, "job_id": "e"}

    monkeypatch.setattr(_shared, "spawn_birth", _fake_birth)
    monkeypatch.setattr(_shared, "spawn_explorer", _fake_spawn)
    monkeypatch.delenv("AUGHOR_BIRTH_JOB", raising=False)

    assert _shared.kickoff_exploration("conn-off") is True
    await asyncio.sleep(0)                        # let the created task run
    assert calls == {"birth": 0, "explore": 1}


@pytest.mark.anyio
async def test_kickoff_elevates_to_birth_when_flag_on(monkeypatch):
    calls = {"birth": 0, "explore": 0}

    async def _fake_birth(conn_id, **kw):
        calls["birth"] += 1
        return {"ok": True, "job_id": "b"}

    async def _fake_spawn(conn_id, **kw):
        calls["explore"] += 1
        return {"ok": True, "reason": None, "job_id": "e"}

    monkeypatch.setattr(_shared, "spawn_birth", _fake_birth)
    monkeypatch.setattr(_shared, "spawn_explorer", _fake_spawn)
    monkeypatch.setenv("AUGHOR_BIRTH_JOB", "1")

    assert _shared.kickoff_exploration("conn-on") is True
    await asyncio.sleep(0)
    assert calls["birth"] == 1
    assert calls["explore"] == 0                  # exploration is birth's step 2, not a sibling


# ── canvas create wires the birth kickoff (flag-gated, best-effort) ──────────

def test_canvas_create_triggers_birth_when_flag_on(client, monkeypatch):
    calls = []

    async def _fake_birth(conn_id, **kw):
        calls.append({"conn_id": conn_id, **kw})
        return {"ok": True, "job_id": "b"}

    monkeypatch.setattr(_shared, "spawn_birth", _fake_birth)
    monkeypatch.setenv("AUGHOR_BIRTH_JOB", "1")

    r = client.post("/canvases", json={"name": "Birth Canvas", "connection_id": "fixture",
                                       "tables": ["kpi_daily"]})
    assert r.status_code == 201
    canvas_id = r.json()["id"]

    # The kickoff is bridged onto the app loop from the sync endpoint — give it a beat.
    for _ in range(50):
        if calls:
            break
        time.sleep(0.05)
    assert calls, "canvas create did not schedule the birth job"
    assert calls[0]["conn_id"] == "fixture"
    assert calls[0]["canvas_id"] == canvas_id
    assert calls[0]["tables_filter"] == ["kpi_daily"]


def test_canvas_create_unchanged_when_flag_off(client, monkeypatch):
    calls = []

    async def _fake_birth(conn_id, **kw):
        calls.append(conn_id)
        return {"ok": True, "job_id": "b"}

    monkeypatch.setattr(_shared, "spawn_birth", _fake_birth)
    monkeypatch.delenv("AUGHOR_BIRTH_JOB", raising=False)

    r = client.post("/canvases", json={"name": "Plain Canvas", "connection_id": "fixture"})
    assert r.status_code == 201
    time.sleep(0.2)
    assert calls == []
