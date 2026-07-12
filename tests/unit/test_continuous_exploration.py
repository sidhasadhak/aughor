"""WP-6 — continuous exploration: re-arm the Scout on schema change / staleness.

The headline "never stops learning" claim was aspirational — a finished exploration was a
dead end until a manual POST. These tests pin the re-arm DECISION (pure), the planner, the
tick's spawn + receipt, the governance-skip surface (6c), and that the default is off.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import aughor.explorer.continuous as cont
from aughor.explorer.models import ExplorationPhase

_COMPLETE = ExplorationPhase.COMPLETE.value
_NOW = datetime(2026, 7, 12, tzinfo=timezone.utc)


def _complete(fp="abc", completed_at="2026-07-12T00:00:00+00:00") -> dict:
    return {"phase": _COMPLETE, "schema_fingerprint": fp, "completed_at": completed_at}


# ── Pure decision ─────────────────────────────────────────────────────────────

def test_skip_when_fingerprint_unchanged():
    assert cont.reexplore_decision(_complete("abc"), "abc", now=_NOW, refresh_secs=0) == cont.SKIP


def test_schema_change_rearms():
    assert cont.reexplore_decision(_complete("abc"), "xyz", now=_NOW, refresh_secs=0) == cont.SCHEMA_CHANGED


def test_none_stored_fingerprint_never_false_triggers():
    # A run that predates fingerprint-stamping has None stored; None != current must NOT read
    # as "changed" (else every connection re-explores once on first enable).
    assert cont.reexplore_decision(_complete(None), "xyz", now=_NOW, refresh_secs=0) == cont.SKIP


def test_none_current_fingerprint_never_false_triggers():
    assert cont.reexplore_decision(_complete("abc"), None, now=_NOW, refresh_secs=0) == cont.SKIP


def test_stale_run_refreshes():
    old = _complete("abc", (_NOW - timedelta(days=10)).isoformat())
    assert cont.reexplore_decision(old, "abc", now=_NOW, refresh_secs=7 * 86400) == cont.STALE


def test_recent_run_is_not_stale():
    recent = _complete("abc", (_NOW - timedelta(days=2)).isoformat())
    assert cont.reexplore_decision(recent, "abc", now=_NOW, refresh_secs=7 * 86400) == cont.SKIP


def test_refresh_disabled_ignores_staleness():
    old = _complete("abc", (_NOW - timedelta(days=999)).isoformat())
    assert cont.reexplore_decision(old, "abc", now=_NOW, refresh_secs=0) == cont.SKIP


def test_running_exploration_is_never_touched():
    assert cont.reexplore_decision({"phase": "domain_intel"}, "xyz", now=_NOW, refresh_secs=0) == cont.SKIP
    assert cont.reexplore_decision({"phase": "failed"}, "xyz", now=_NOW, refresh_secs=0) == cont.SKIP


def test_schema_change_wins_over_freshness():
    # A changed schema re-arms even if the run is recent.
    recent_changed = _complete("abc", (_NOW - timedelta(minutes=5)).isoformat())
    assert cont.reexplore_decision(recent_changed, "xyz", now=_NOW, refresh_secs=7 * 86400) == cont.SCHEMA_CHANGED


# ── Planner (sync, executor-safe) ─────────────────────────────────────────────

def test_plan_reexplorations_selects_changed_connections(monkeypatch):
    monkeypatch.setattr("aughor.db.registry.list_connections",
                        lambda *a, **k: [{"id": "c_changed"}, {"id": "c_fresh"}, {"id": "c_running"}])
    monkeypatch.setattr("aughor.explorer.store.schema_run_keys", lambda cid: [])
    state_by_conn = {
        "c_changed": _complete("old_fp"),
        "c_fresh": _complete("cur_fp"),
        "c_running": {"phase": "distribution"},
    }
    monkeypatch.setattr("aughor.explorer.store.load", lambda cid: state_by_conn[cid])
    monkeypatch.setattr(cont, "connection_schema_fingerprint", lambda cid: "cur_fp")
    monkeypatch.setattr(cont, "refresh_seconds", lambda: 0.0)

    plans = cont.plan_reexplorations()
    assert plans == [("c_changed", cont.SCHEMA_CHANGED)]   # only the changed one; fresh + running skipped


# ── Tick (async): spawn + receipt ─────────────────────────────────────────────

def test_run_continuous_tick_spawns_and_emits(monkeypatch):
    monkeypatch.setattr(cont, "plan_reexplorations", lambda: [("c1", cont.SCHEMA_CHANGED)])
    calls: list = []
    monkeypatch.setattr("aughor.routers._shared.kickoff_exploration",
                        lambda cid, auto=False: (calls.append((cid, auto)) or True))
    emits: list = []
    monkeypatch.setattr(cont, "_emit", lambda kind, payload, conn_id: emits.append((kind, payload)))

    n = asyncio.run(cont.run_continuous_tick())
    assert n == 1
    assert calls == [("c1", True)]                          # re-kicked as an AUTO run
    assert any(k == "exploration.rearmed" for k, _ in emits)


def test_run_continuous_tick_no_emit_when_declined(monkeypatch):
    monkeypatch.setattr(cont, "plan_reexplorations", lambda: [("c1", cont.STALE)])
    monkeypatch.setattr("aughor.routers._shared.kickoff_exploration", lambda cid, auto=False: False)
    emits: list = []
    monkeypatch.setattr(cont, "_emit", lambda kind, payload, conn_id: emits.append((kind, payload)))

    n = asyncio.run(cont.run_continuous_tick())
    assert n == 0
    assert not any(k == "exploration.rearmed" for k, _ in emits)   # kickoff owns the skip event


# ── 6c: the governance skip is surfaced, not silent ───────────────────────────

def test_kickoff_auto_skip_emits_ledger_event(monkeypatch):
    from aughor.routers import _shared

    monkeypatch.setattr("aughor.kernel.agents.is_enabled", lambda agent, ws: False)
    monkeypatch.setattr("aughor.workspace.store.workspace_for_connection", lambda cid: "ws1")
    emits: list = []

    class _L:
        def emit(self, kind, payload, **kw):
            emits.append((kind, payload))

    monkeypatch.setattr("aughor.kernel.ledger.Ledger.default", classmethod(lambda cls: _L()))

    assert _shared.kickoff_exploration("c1", auto=True) is False
    assert any(k == "exploration.skipped" and p.get("reason") == "scout_disabled" for k, p in emits)


# ── Default-off invariant ─────────────────────────────────────────────────────

def test_continuous_is_default_off():
    from aughor.kernel.flags import FLAG_DEFAULT, FLAG_ENV
    assert "explorer.continuous" in FLAG_ENV
    assert FLAG_DEFAULT.get("explorer.continuous", False) is False
