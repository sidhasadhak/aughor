"""Interrupted work gets its own terminal status (Wave 4 / Layer 4.1b).

"It broke" and "we do not know how far it got" are different facts. A job the
process died holding was being recorded as FAILED, which claims a failure nobody
observed and charges an infrastructure event to the agent's error rate.

This also fixes a guard that had gone blind: the fleet tiles split orphans out of the
error rate by matching a job's error against a constant that is the INVESTIGATIONS
wording ("server restart (orphaned)"), while an orphaned job says "lease lapsed
(orphaned)". The two never matched, so the tile that exists to say "an orphaned
restart is not an agent error" was counting every one of them as an agent error. A key
that has to equal a whole sentence is how a guard goes blind; the status is the
authority now. That half is covered beside the fleet tiles, in their own route tests.
"""
from __future__ import annotations

from aughor.kernel.jobs import JobState


# ── the state machine ────────────────────────────────────────────────────────

def test_interrupted_is_terminal():
    assert JobState.INTERRUPTED in JobState.TERMINAL
    assert JobState.INTERRUPTED not in JobState.ACTIVE


def test_interrupted_is_distinct_from_failed():
    assert JobState.INTERRUPTED != JobState.FAILED


def test_every_active_state_can_be_interrupted():
    """A process can die holding a job in any live state — pending in a queue,
    running, or paused mid-work."""
    from aughor.kernel.jobs import _LEGAL

    for state in JobState.ACTIVE:
        assert JobState.INTERRUPTED in _LEGAL[state], f"{state} cannot be interrupted"


def test_interrupted_is_final():
    """Terminal means terminal — an interrupted job is not resumed in place."""
    from aughor.kernel.jobs import _LEGAL

    assert _LEGAL[JobState.INTERRUPTED] == set()


def test_every_terminal_state_has_a_legal_entry():
    """A state missing from the table would raise on transition, turning an orphan
    sweep into an exception during boot recovery."""
    from aughor.kernel.jobs import _LEGAL

    for state in JobState.TERMINAL + JobState.ACTIVE:
        assert state in _LEGAL


# ── the orphan paths use it ──────────────────────────────────────────────────

def test_boot_recovery_marks_interrupted_not_failed():
    import inspect

    from aughor.kernel import jobs

    src = inspect.getsource(jobs)
    assert "self._transition(job[\"id\"], JobState.INTERRUPTED," in src
    assert "JobState.FAILED,\n                             error=f\"lease lapsed" not in src


def test_the_orphan_errors_still_carry_the_shared_sentence():
    """The status says WHAT happened; the sentence says what it means for the reader.
    Both, and the sentence stays the one shared wording."""
    import inspect

    from aughor.kernel import jobs

    src = inspect.getsource(jobs)
    assert "lease lapsed (orphaned) — {UNCERTAIN_RESULT}" in src
    assert "orphaned (stale heartbeat, no live task) — {UNCERTAIN_RESULT}" in src
