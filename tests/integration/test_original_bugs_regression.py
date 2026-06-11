"""Regression locks for the THREE originally-reported bugs.

These were the user-reported symptoms that opened the World-Class Hardening arc:
  WCH-1  Briefing/canvas "Investigate" → blank canvas (the question was discarded)
  WCH-2  table sample data goes missing intermittently (silent-empty on seed failure)
  WCH-DS temporal planning on short-history data (17 days framed as "last 12 months")

WCH-DS is already locked deterministically by tests/unit/test_coverage_clamp.py,
test_window_anchoring.py and test_temporal_guard.py — this module asserts that
coverage still EXISTS (so deleting it trips CI) rather than duplicating it.

WCH-2 is locked by a real backend contract test (the sample endpoint must surface
an `error`, never silent-empty).

WCH-1 is frontend-only and the suite has no JS runtime, but the bug REGRESSED
repeatedly — so its fix is locked by a source-contract tripwire (same pattern as
the K4 wiring contract in test_api_contract.py): structural assertions that fail
loudly if the specific fix is reverted. Brittle-by-design — a reversion SHOULD
trip it.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).parent.parent.parent
WEB = REPO / "web"


# ── WCH-1: Investigate → blank canvas (frontend wiring tripwire) ───────────────
#
# Two stacked bugs were fixed; both have recurred before, so both are pinned.

def _read(rel: str) -> str:
    p = WEB / rel
    assert p.exists(), f"expected frontend file missing: {rel}"
    return p.read_text()


def test_wch1a_canvas_onInvestigate_seeds_question_not_discards_it():
    """CanvasWorkspace.onInvestigate must SEED the question into chat state.
    The original bug was `onInvestigate={() => setWsTab('chat')}` — it threw away
    (q, mode) and the canvas opened blank."""
    src = _read("components/CanvasWorkspace.tsx")

    # The handler must capture the question into the seed state that ChatPanel reads.
    assert "setChatInitialQuestion(q)" in src, (
        "CanvasWorkspace.onInvestigate no longer seeds the question — the blank-canvas "
        "bug (q discarded before reaching ChatPanel) has regressed."
    )
    # …and that seed must actually be wired into ChatPanel as a prop.
    assert "initialQuestion={chatInitialQuestion}" in src, (
        "ChatPanel is no longer receiving the seeded initialQuestion prop."
    )

    # Guard against the exact regression shape: an onInvestigate that ignores its
    # args and only switches tabs.
    m = re.search(r"onInvestigate=\{\(\s*\)\s*=>\s*setWsTab", src)
    assert m is None, (
        "onInvestigate reverted to the arg-discarding `() => setWsTab(...)` form — "
        "the question is being dropped again."
    )


def test_wch1b_chatpanel_autosubmit_latches_inside_the_timer():
    """ChatPanel's auto-submit fired-latch must be set INSIDE the setTimeout callback.
    Latching eagerly (before the timer) made StrictMode's dev double-invoke bail on
    the second setup, so auto-submit never fired — the connection-level blank canvas."""
    src = _read("components/ChatPanel.tsx")

    # Isolate the auto-submit effect so we reason about ordering locally.
    start = src.find("Auto-submit a question injected")
    assert start != -1, "the auto-submit effect (with its explanatory comment) is gone"
    block = src[start:start + 1200]

    i_timer = block.find("setTimeout(")
    i_latch = block.find("initialFiredRef.current = true")
    i_ask = block.find("ask(initialQuestion")

    assert i_timer != -1, "auto-submit no longer defers via setTimeout"
    assert i_latch != -1, "the fired-latch assignment is gone"
    assert i_ask != -1, "auto-submit no longer calls ask(initialQuestion, ...)"

    # The latch MUST come after setTimeout( — i.e. inside the deferred callback,
    # not eagerly in the effect body where StrictMode would defeat it.
    assert i_timer < i_latch, (
        "initialFiredRef is latched BEFORE/outside the setTimeout — the StrictMode "
        "double-invoke bug that blanks the canvas has regressed."
    )
    # And the ask() must be inside the timer too (after the latch, before the closing).
    assert i_latch < i_ask, "ask() is no longer guarded by the in-timer latch"


# ── WCH-2: sample data missing → must SURFACE an error, never silent-empty ─────

def _first_table(client: TestClient, conn_id: str) -> str:
    """Discover a real table name via the lightweight query path (the /schema
    endpoint triggers slow vector indexing — avoid it here)."""
    r = client.post("/query/run", json={
        "conn_id": conn_id,
        "sql": "SELECT table_name FROM information_schema.tables ORDER BY 1 LIMIT 1",
        "limit": 1, "use_cache": False, "use_bulk": False,
    })
    assert r.status_code == 200, r.text
    rows = r.json().get("rows") or []
    assert rows, "fixture connection unexpectedly has no tables"
    return rows[0][0]


def test_wch2_sample_endpoint_always_returns_error_key(client: TestClient, builtin_conn_id: str) -> None:
    """Healthy sample read: rows present, error is falsy, but the `error` KEY is
    always part of the contract (SampleGrid's 3-state rendering depends on it)."""
    name = _first_table(client, builtin_conn_id)
    r = client.get(f"/connections/{builtin_conn_id}/tables/{name}/sample", params={"limit": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "error" in body, "sample response dropped the `error` key — 3-state UI can't distinguish error from empty"
    assert not body["error"], f"healthy table surfaced an error: {body['error']}"
    assert body.get("row_count", 0) > 0, "healthy sample returned zero rows"


def test_wch2_missing_table_surfaces_error_not_silent_empty(client: TestClient, builtin_conn_id: str) -> None:
    """A table that does not exist (the symptom a failed seed presents as) must
    return a POPULATED error, never an empty-but-clean result that reads as 'no data'."""
    r = client.get(f"/connections/{builtin_conn_id}/tables/__no_such_table__/sample", params={"limit": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("error"), f"missing table must surface an error, got: {body}"
    assert body.get("row_count", 0) == 0


def test_wch2_bad_connection_is_404(client: TestClient) -> None:
    r = client.get("/connections/__nope__/tables/whatever/sample")
    assert r.status_code == 404, r.text


# ── WCH-DS: temporal coverage — assert the deterministic locks still exist ─────

@pytest.mark.parametrize("locked", [
    "tests/unit/test_coverage_clamp.py",
    "tests/unit/test_window_anchoring.py",
    "tests/unit/test_temporal_guard.py",
])
def test_wch_ds_temporal_locks_present(locked: str) -> None:
    """WCH-DS is locked by these three suites. If one is deleted, this trips so the
    coverage can't silently vanish."""
    assert (REPO / locked).exists(), f"WCH-DS regression lock removed: {locked}"
