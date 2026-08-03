"""R6 — per-workspace compute isolation. Tests the lane envelope (PRAGMAs), the
concurrency gate, per-workspace config resolution + override, and fail-open. Hermetic:
the workspace store is stubbed; no real DB or event-loop saturation."""
from __future__ import annotations

import asyncio

import pytest

from aughor.db.lanes import LaneConfig, WorkspaceLane, lane_for_workspace, lane_for_connection, reset_lanes


@pytest.fixture(autouse=True)
def _clean_lanes(monkeypatch):
    # neutralise env so defaults are deterministic; clear the memoized registry
    for k in ("AUGHOR_LANE_MAX_CONCURRENCY", "AUGHOR_MAX_CONCURRENT_EXPLORERS",
              "AUGHOR_LANE_MEMORY_LIMIT", "AUGHOR_LANE_THREADS"):
        monkeypatch.delenv(k, raising=False)
    reset_lanes()
    yield
    reset_lanes()


# ── envelope / PRAGMAs ───────────────────────────────────────────────────────────

def test_default_envelope_is_a_noop():
    cfg = LaneConfig.default()
    assert cfg.pragmas() == []          # nothing emitted unless configured
    assert cfg.max_concurrency == 2


def test_configured_envelope_emits_pragmas(monkeypatch):
    monkeypatch.setenv("AUGHOR_LANE_MEMORY_LIMIT", "2GB")
    monkeypatch.setenv("AUGHOR_LANE_THREADS", "4")
    cfg = LaneConfig.default()
    assert cfg.pragmas() == ["SET memory_limit='2GB'", "SET threads=4"]


def test_override_merges_over_defaults():
    base = LaneConfig(max_concurrency=2, memory_limit="", threads=0)
    merged = base.merged_with({"memory_limit": "8GB", "max_concurrency": 5})
    assert merged.memory_limit == "8GB" and merged.max_concurrency == 5
    assert merged.threads == 0
    # an empty / None override leaves defaults intact
    assert base.merged_with(None) == base and base.merged_with({}) == base


def test_apply_envelope_runs_each_pragma_and_is_fail_open():
    applied = []

    class _Conn:
        def execute(self, sql):
            applied.append(sql)

    lane = WorkspaceLane("ws1", LaneConfig(memory_limit="1GB", threads=2))
    lane.apply_envelope(_Conn())
    assert applied == ["SET memory_limit='1GB'", "SET threads=2"]

    class _BoomConn:
        def execute(self, sql):
            raise RuntimeError("unsupported")

    lane.apply_envelope(_BoomConn())   # must NOT raise — fail-open


# ── concurrency gate ─────────────────────────────────────────────────────────────

def test_gate_bounds_concurrency():
    async def _run():
        lane = WorkspaceLane("ws1", LaneConfig(max_concurrency=2))
        live = {"n": 0, "peak": 0}

        async def worker():
            async with lane.gate():
                live["n"] += 1
                live["peak"] = max(live["peak"], live["n"])
                await asyncio.sleep(0.01)
                live["n"] -= 1

        await asyncio.gather(*(worker() for _ in range(6)))
        return live["peak"]

    assert asyncio.run(_run()) == 2   # never more than the lane's cap in flight


def test_a_memoized_lane_is_reusable_from_a_second_event_loop():
    """The regression that wedged the whole suite.

    Lanes are memoized process-wide, so one outlives any single event loop. When the
    lane held ONE semaphore, the second loop to reach `gate()` either raised "bound to a
    different event loop" or — if the first loop died still holding a slot — waited
    forever on a release that could never come. Here the first loop deliberately abandons
    the lane mid-gate by cancelling; the second must still be able to acquire.
    """
    lane = WorkspaceLane("ws-crossloop", LaneConfig(max_concurrency=1))

    async def _leave_the_slot_held():
        # Acquire the raw semaphore, NOT via gate(): gate's `finally: sem.release()` runs
        # even on cancellation, which frees the slot and lets a stale semaphore take
        # acquire()'s uncontended fast path — the bug would then hide. The real crash
        # reported `[locked, waiters:1]`, i.e. a slot still held when its loop died.
        await lane.semaphore().acquire()
        return lane.semaphore().locked()

    assert asyncio.run(_leave_the_slot_held()) is True

    async def _second_loop_is_not_blocked():
        # Must not hang: a new loop gets its own slot rather than inheriting a dead one.
        async with lane.gate():
            return True

    assert asyncio.run(asyncio.wait_for(_second_loop_is_not_blocked(), timeout=5)) is True


# ── registry + per-workspace resolution ──────────────────────────────────────────

def test_lane_is_memoized_per_workspace():
    a1 = lane_for_workspace("wsA")
    a2 = lane_for_workspace("wsA")
    b = lane_for_workspace("wsB")
    assert a1 is a2 and a1 is not b      # same workspace → same lane; different → distinct


def test_lane_for_connection_resolves_workspace_override(monkeypatch):
    # stub the workspace store: conn 'c1' → workspace 'wsHeavy' with a compute override
    class _WS:
        id = "wsHeavy"
        settings_override = {"compute": {"memory_limit": "16GB", "max_concurrency": 1}}

    monkeypatch.setattr("aughor.workspace.store.workspace_for_connection", lambda cid: _WS() if cid == "c1" else None)
    monkeypatch.setattr("aughor.workspace.store.get_workspace", lambda wid: _WS() if wid == "wsHeavy" else None)
    reset_lanes()
    lane = lane_for_connection("c1")
    assert lane.workspace_id == "wsHeavy"
    assert lane.config.memory_limit == "16GB" and lane.config.max_concurrency == 1


def test_lane_for_connection_is_fail_open_to_global(monkeypatch):
    def _boom(_cid):
        raise RuntimeError("store down")
    monkeypatch.setattr("aughor.workspace.store.workspace_for_connection", _boom)
    reset_lanes()
    lane = lane_for_connection("c1")
    assert lane.workspace_id == "__global__"   # never raises — global default lane
