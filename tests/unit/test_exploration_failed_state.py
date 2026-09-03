"""A failed exploration must be able to say WHY, and must not disown its own facts.

Found by driving a real deployment 2026-09-03. theLook's status read:

    phase: "failed"   error: null   54 findings   58 facts discovered
    started_at:   2026-08-29T13:33   (the run that failed)
    completed_at: 2026-08-26T15:31   (an earlier run that succeeded)

A full, grounded briefing on screen, 54 findings, and a phase saying failed with no
explanation. The user's reasonable conclusion was "I may have to start afresh" — which
would have thrown away a working body of intelligence and paid for a full re-run.

Two separate defects sat behind that, and this file pins both.

**① The reason was never persisted.** `_save_state` mirrored the phase and five counters;
`error` was not among them. So a failure recorded the phase to disk and kept its
explanation in memory, where the next restart dropped it. `_restored_error` could only
derive a reason from per-schema failures, so a SINGLE-schema connection was structurally
incapable of ever reporting one. A terminal state nobody can explain is one people fix by
starting over.

**② A failed phase disowned facts that had been verified.** `render_exploration_annotations`
returned "" for the whole block when the phase was `pending` or `failed`, so 58 verified
facts — displayed in the briefing at that very moment — reached neither the deep-analysis
planner nor the ontology overlay. The facts are the same facts whatever a later run did; the user
decided (2026-09-03) that a failed run's verified facts still count.
"""
from __future__ import annotations

import json


# ── ① the reason survives a restart ──────────────────────────────────────────────

def _restored(state: dict):
    from aughor.routers.exploration import _restored_error
    return _restored_error(state)


def test_a_recorded_reason_is_what_the_status_reports():
    """The whole point of persisting it. Before this the answer was always None for any
    connection without per-schema runs — which is every single-schema one."""
    assert _restored({"error": "no profiler data for this connection"}) \
        == "no profiler data for this connection"


def test_the_recorded_reason_WINS_over_the_per_schema_derivation():
    """The derivation is a fallback for a partly-failed multi-schema run, not a competitor.
    A run that recorded why it failed knows better than a count of schema phases."""
    out = _restored({"error": "cancelled (budget exceeded or stopped) — progress saved",
                     "per_schema": {"public": "failed", "analytics": "complete"}})
    assert out.startswith("cancelled")


def test_the_per_schema_sentence_still_answers_when_nothing_was_recorded():
    """Unchanged behaviour for the case that reader was written for: a partly-failed run
    still reports COMPLETE, so this stays the only place its failures are said out loud."""
    out = _restored({"per_schema": {"public": "failed", "analytics": "complete"}})
    assert out is not None and "1 of 2 schemas failed" in out


def test_a_healthy_run_reports_NO_error():
    assert _restored({"per_schema": {"public": "complete"}}) is None
    assert _restored({}) is None


def test_a_blank_recorded_reason_does_not_masquerade_as_one():
    """An empty string is not an explanation. Falling through to the derivation (or to
    None) is honest; returning "" would render an error banner with nothing in it."""
    assert _restored({"error": "   "}) is None


def test_save_state_mirrors_the_reason_beside_the_phase():
    """Asserted on the source rather than by running an explorer, which needs a live
    connection, a profiler and an event loop. The claim is narrow and structural: the two
    fields that explain each other are written by the same function."""
    import inspect

    from aughor.explorer.agent import SchemaExplorer
    src = inspect.getsource(SchemaExplorer._save_state)
    assert '_state["phase"]' in src
    assert '_state["error"]' in src, (
        "the phase is persisted without its reason — a failure will survive a restart "
        "with its explanation erased, which is the defect this file exists for")
    assert '_state.pop("error", None)' in src, (
        "a stale reason must be CLEARED on a save with no error, or it outlives the "
        "failure it describes and reads as a diagnosis of a run that succeeded")


# ── ② a failed run's verified facts still reach the planner ──────────────────────

def _annotations(monkeypatch, state: dict) -> str:
    from aughor.explorer import store
    monkeypatch.setattr(store, "load_aggregate", lambda _cid: state)
    return store.render_exploration_annotations("c1")


_VERIFIED = {
    "null_meanings": {"orders.shipped_at": {"meaning": "not_yet_shipped",
                                            "confidence": "high"}},
}


def test_a_FAILED_run_still_contributes_what_it_verified(monkeypatch):
    """The user's call, 2026-09-03. These facts were each verified by a query that ran and
    returned rows; a later phase transition does not retract them."""
    out = _annotations(monkeypatch, {"phase": "failed", **_VERIFIED})
    assert "shipped_at" in out, "a failed run disowned facts it had verified"


def test_a_COMPLETE_run_is_unchanged(monkeypatch):
    assert "shipped_at" in _annotations(monkeypatch, {"phase": "complete", **_VERIFIED})


def test_a_PENDING_run_still_contributes_nothing(monkeypatch):
    """Not symmetry lost: a pending run has verified nothing yet, so the sections would be
    empty anyway — the guard just says so without walking them."""
    assert _annotations(monkeypatch, {"phase": "pending", **_VERIFIED}) == ""


def test_a_failed_run_with_NOTHING_verified_still_yields_nothing(monkeypatch):
    """Letting a failed run through must not turn an empty run into a block of headings."""
    assert _annotations(monkeypatch, {"phase": "failed"}) == ""


# ── the shape that produced the report ───────────────────────────────────────────

def test_the_live_shape_that_prompted_this(monkeypatch):
    """theLook, as measured: failed phase, 54 findings, verified facts present. Both
    defects visible in one state — the reason absent, and the facts withheld."""
    # The findings list is not needed by either assertion — the annotations read
    # `null_meanings` and the reason reads `error` — so it is described rather than
    # constructed, keeping this fixture about the two defects it pins.
    state = {"phase": "failed", **_VERIFIED}
    assert "shipped_at" in _annotations(monkeypatch, state), "facts withheld"
    # And with a reason recorded, the status can finally explain itself.
    assert _restored({**state, "error": "cancelled — progress saved"}) is not None
    # The state round-trips as JSON, which is how it is stored.
    assert json.loads(json.dumps(state))["phase"] == "failed"
