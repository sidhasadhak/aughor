"""Boot recovery resumes UNFINISHED explorations — not every one it can find.

Measured 2026-08-30, on a live instance: restarting the API re-explored two canvases
whose explorations had already reached `complete` and `failed`. Nothing was recovering;
they were fresh explorations nobody asked for, each spending model tokens, on every
single restart.

Two facts made it invisible:

* **Having state is not having unfinished work.** `_boot_canvas_explorers` looped over
  `canvas_ids_with_state()` and checked only that the state existed.
* **`spawn_explorer`'s guard does not cover this.** It refuses an exploration that is
  *currently running* — on a fresh boot nothing is, so it waves every saved canvas
  through. A guard that reads a different question than the caller assumes is worse than
  no guard, because the caller stops asking.

The connection path had already been fixed for exactly this ("recovery kept re-spawning
explorers for explorations that had already completed"). The canvas path never got the
same check, in either of the two places that resume one. Both read one predicate now, so
they cannot drift apart again.
"""
from __future__ import annotations

import asyncio

import pytest

from aughor.explorer.models import ExplorationPhase
from aughor.explorer.store import TERMINAL_PHASES, is_unfinished


# ── the rule ─────────────────────────────────────────────────────────────────────

def test_terminal_phases_are_DERIVED_from_the_enum():
    """Spelled out, a renamed member stops matching silently — and a boot check that
    quietly stops matching re-runs every exploration on every restart."""
    assert TERMINAL_PHASES == (ExplorationPhase.COMPLETE.value, ExplorationPhase.FAILED.value)


@pytest.mark.parametrize("phase", [p.value for p in ExplorationPhase])
def test_every_phase_is_classified_one_way_or_the_other(phase):
    """No phase may fall through the check as an accident of spelling."""
    assert is_unfinished({"phase": phase}) is (phase not in TERMINAL_PHASES)


def test_a_missing_phase_counts_as_UNFINISHED():
    """The safe direction: resuming something already done costs a re-run, skipping
    something that was not loses the work outright."""
    assert is_unfinished({}) is True
    assert is_unfinished(None) is True


# ── the boot loop ────────────────────────────────────────────────────────────────

class _Canvas:
    def __init__(self, conn_id="conn-1"):
        self.scopes = [type("S", (), {"connection_id": conn_id, "tables": None})()]


def _boot(monkeypatch, phases: dict[str, str], canvases: dict | None = None) -> list[str]:
    """Run the real boot loop over `phases`, returning the canvas ids it spawned."""
    from aughor.explorer import store as expl_store
    from aughor.canvas import store as canvas_store
    from aughor.routers import _shared

    spawned: list[str] = []

    async def _spawn(conn_id, canvas_id=None, tables_filter=None, **kw):
        spawned.append(canvas_id)
        return {"ok": True, "reason": None, "job_id": "job-1"}

    monkeypatch.setattr(expl_store, "canvas_ids_with_state", lambda: list(phases))
    monkeypatch.setattr(expl_store, "has_state", lambda key: True)
    monkeypatch.setattr(expl_store, "load_canvas",
                        lambda cid: {"phase": phases[cid]} if phases[cid] else {})
    monkeypatch.setattr(canvas_store, "get_canvas",
                        lambda cid: (canvases or {}).get(cid, _Canvas()))
    monkeypatch.setattr(_shared, "spawn_explorer", _spawn)

    from aughor.api import _boot_canvas_explorers
    asyncio.run(_boot_canvas_explorers())
    return spawned


def test_a_COMPLETE_canvas_is_not_re_explored(monkeypatch):
    """The measured defect. It is not recovery — the exploration finished."""
    assert _boot(monkeypatch, {"done": "complete"}) == []


def test_a_FAILED_canvas_is_not_retried_forever(monkeypatch):
    """A failed exploration is restartable on demand. What it must not be is retried
    with no backoff and no cap by the act of restarting the server."""
    assert _boot(monkeypatch, {"broken": "failed"}) == []


def test_an_INTERRUPTED_canvas_IS_resumed(monkeypatch):
    """The case boot recovery exists for: a process died mid-run, so the saved phase is
    still one of the working ones. Skipping this would lose the work."""
    assert _boot(monkeypatch, {"midrun": ExplorationPhase.DISTRIBUTION.value}) == ["midrun"]


def test_a_canvas_with_no_recorded_phase_is_still_resumed(monkeypatch):
    assert _boot(monkeypatch, {"legacy": ""}) == ["legacy"]


def test_the_finished_ones_do_not_block_the_unfinished_one(monkeypatch):
    """One skip must not end the loop — the whole point is that a restart resumes what
    it should while leaving the rest alone."""
    spawned = _boot(monkeypatch, {
        "done": "complete",
        "midrun": ExplorationPhase.SYNTHESIS.value,
        "broken": "failed",
    })
    assert spawned == ["midrun"]


def test_a_canvas_with_no_scopes_is_skipped_as_before(monkeypatch):
    """Unchanged behaviour: an unfinished canvas that names no connection cannot be
    spawned against anything."""
    empty = type("C", (), {"scopes": []})()
    spawned = _boot(monkeypatch, {"scopeless": ExplorationPhase.CROSS_TABLE.value},
                    canvases={"scopeless": empty})
    assert spawned == []
