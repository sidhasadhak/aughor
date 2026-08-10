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


@pytest.mark.anyio
async def test_run_birth_mines_popularity(monkeypatch, tmp_path):
    monkeypatch.setenv("AUGHOR_POPULARITY_DB", str(tmp_path / "pop.db"))
    db = _FakeDB()
    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda cid: db)
    monkeypatch.setattr("aughor.sql.query_log_miner.collect_logged_sql",
                        lambda cid, limit=5000: ["SELECT brand FROM sales"])
    # Stub the task_history fallback source — under full-suite ordering the
    # hermetic ledger carries earlier tests' executed SQL (CI caught the leak).
    monkeypatch.setattr("aughor.sql.popularity._sqls_from_task_history",
                        lambda cid, limit: [])

    async def _fake_spawn(conn_id, **kw):
        return {"ok": True, "reason": None, "job_id": "j"}

    monkeypatch.setattr(_shared, "spawn_explorer", _fake_spawn)
    summary = await _shared.run_birth("connPop")
    assert _step(summary, "popularity") == ["started", "done"]

    from aughor.sql.popularity import load_popularity
    assert load_popularity("connPop")["table"] == {"sales": 1}


@pytest.mark.anyio
async def test_kickoff_elevates_to_birth(monkeypatch):
    calls = {"birth": 0, "explore": 0}

    async def _fake_birth(conn_id, **kw):
        calls["birth"] += 1
        return {"ok": True, "job_id": "b"}

    async def _fake_spawn(conn_id, **kw):
        calls["explore"] += 1
        return {"ok": True, "reason": None, "job_id": "e"}

    monkeypatch.setattr(_shared, "spawn_birth", _fake_birth)
    monkeypatch.setattr(_shared, "spawn_explorer", _fake_spawn)

    assert _shared.kickoff_exploration("conn-on") is True
    await asyncio.sleep(0)
    assert calls["birth"] == 1
    assert calls["explore"] == 0                  # exploration is birth's step 2, not a sibling


# ── canvas create wires the birth kickoff (flag-gated, best-effort) ──────────

def test_canvas_create_triggers_birth(client, monkeypatch):
    calls = []

    async def _fake_birth(conn_id, **kw):
        calls.append({"conn_id": conn_id, **kw})
        return {"ok": True, "job_id": "b"}

    monkeypatch.setattr(_shared, "spawn_birth", _fake_birth)

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




# ── the two prep steps run CONCURRENTLY (measured 7.6s + 8.9s when sequential) ──


@pytest.mark.anyio
async def test_intelligence_and_popularity_overlap(monkeypatch):
    """They are independent, so they must overlap — not merely both happen.

    Asserting "both ran" would pass just as happily on the sequential version this
    replaced, which is exactly the shape of test that lets a regression back in. The
    claim is about time, so the assertion is about time: each step records its own
    interval and the two must intersect.
    """
    marks: dict[str, tuple[float, float]] = {}

    class _SlowDB(_FakeDB):
        def build_intelligence(self):
            t0 = time.monotonic()
            time.sleep(0.30)
            marks["intelligence"] = (t0, time.monotonic())
            return super().build_intelligence()

    db = _SlowDB()
    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda cid: db)

    def _slow_popularity(conn_id):
        t0 = time.monotonic()
        time.sleep(0.30)
        marks["popularity"] = (t0, time.monotonic())
        class _Sig:
            n_queries = 7
            table_counts = {"orders": 7}
        return _Sig()

    monkeypatch.setattr("aughor.sql.popularity.refresh_popularity", _slow_popularity)

    async def _fake_spawn(conn_id, **kw):
        return {"ok": True, "reason": None, "job_id": "job-par"}

    monkeypatch.setattr(_shared, "spawn_explorer", _fake_spawn)

    wall_t0 = time.monotonic()
    summary = await _shared.run_birth("connPar")
    wall = time.monotonic() - wall_t0

    assert _step(summary, "intelligence") == ["started", "done"]
    assert _step(summary, "popularity") == ["started", "done"]

    (i0, i1), (p0, p1) = marks["intelligence"], marks["popularity"]
    overlap = min(i1, p1) - max(i0, p0)
    assert overlap > 0, (
        f"steps did not overlap — intelligence {i0:.3f}–{i1:.3f}, popularity {p0:.3f}–{p1:.3f}"
    )
    # Sequential would be ~0.60s; concurrent ~0.30s. The midpoint is a generous line
    # that still fails loudly if the gather is ever unwound back into two awaits.
    assert wall < 0.55, f"wall clock {wall:.3f}s suggests the steps ran in sequence"


@pytest.mark.anyio
async def test_popularity_failure_does_not_lose_the_intelligence_build(monkeypatch):
    """`gather`, not `TaskGroup`: a best-effort mining hiccup must not cancel its
    sibling. This is the specific regression the concurrency change could introduce."""
    db = _FakeDB()
    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda cid: db)

    def _boom(conn_id):
        raise RuntimeError("miner exploded")

    monkeypatch.setattr("aughor.sql.popularity.refresh_popularity", _boom)

    async def _fake_spawn(conn_id, **kw):
        return {"ok": True, "reason": None, "job_id": "job-x"}

    monkeypatch.setattr(_shared, "spawn_explorer", _fake_spawn)

    summary = await _shared.run_birth("connBoom")

    assert db.built, "a popularity failure cancelled the intelligence build"
    assert _step(summary, "intelligence") == ["started", "done"]
    assert _step(summary, "popularity") == ["started", "failed"]
