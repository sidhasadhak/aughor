"""MI-2 — retention actually happens, and a graded run survives it.

Two halves, and the first is a defect the second depended on. `session_events` carried a
stated 14-day retention that was not being enforced: the amortised prune fired on an
in-process counter that resets to zero on every boot, so an install restarting before 500
session-event writes in one process lifetime never pruned. Measured on the live deployment
2026-09-03: 4,186 of 10,788 rows past the cutoff (39% of the table), the oldest 19 days.
The first count of that was 1,766 — my own probe compared `at` against
`datetime('now','-14 days')`, whose SPACE separator sorts below the stored `T`, dropping
every boundary-day row. The code was comparing correctly the whole time.

That made MI-2's own receipt unprovable — "a graded run survives the sweep, its ungraded
neighbour does not" says nothing when the sweep never runs on either.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aughor.kernel.ledger import Ledger
from aughor.obs import session_log


def _tel():
    import aughor.telemetry as tel
    return tel


def _emit(trace: str, n: int = 1) -> None:
    with _tel().bind_trace(trace):
        for _ in range(n):
            session_log.emit(session_log.TOOL_CALL, name="x")


def _age_events(led: Ledger, trace: str, days: int) -> None:
    """Backdate a trace's rows. The sweep reads `at`, so this is what 'old' means."""
    old = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with led._lock, led._conn:
        led._conn.execute("UPDATE session_events SET at = ? WHERE trace_id = ?",
                          (old, trace))


# ── half one: retention happens at all ───────────────────────────────────────────────

def test_opening_the_ledger_prunes_when_the_last_prune_is_stale():
    """The restart case, which the counter alone could never cover: a fresh process has
    `_session_event_writes == 0` and may never reach 500 before it exits again."""
    led = Ledger.default()
    led.session_events_clear()
    _emit("t-stale-old")
    _age_events(led, "t-stale-old", days=30)

    led.kv_put("session_log", "last_pruned_at",
               (datetime.now(timezone.utc) - timedelta(days=3)).isoformat())

    led._prune_if_overdue_at_open()        # exactly what a restart runs
    assert led.session_events(limit=100, trace_id="t-stale-old") == []


def test_a_backdated_row_is_not_deleted_by_the_sweep_its_own_arrival_triggers():
    """Why the check lives at OPEN and not on the first write. `session_event_insert`
    prunes AFTER inserting, so a first write that is itself old — a back-fill, an import,
    a test fixture — would be swept away by the pass its own arrival set off. Two existing
    suites caught this the first time it was written that way."""
    led = Ledger.default()
    led.session_events_clear()
    led.kv_put("session_log", "last_pruned_at", "not-a-timestamp")   # maximally overdue
    led._session_event_writes = 0

    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    led.session_event_insert({"trace_id": "t-backfill", "kind": "llm_call", "at": old})
    assert len(led.session_events(limit=10, trace_id="t-backfill")) == 1


def test_a_recent_prune_is_not_repeated_on_every_restart():
    """The durable clock has to work in both directions, or a restart loop becomes a
    delete loop over the same table."""
    led = Ledger.default()
    led.session_events_clear()
    _emit("t-fresh-old")
    _age_events(led, "t-fresh-old", days=30)

    led.kv_put("session_log", "last_pruned_at", datetime.now(timezone.utc).isoformat())

    led._prune_if_overdue_at_open()
    assert len(led.session_events(limit=100, trace_id="t-fresh-old")) == 1, \
        "a prune ran despite the durable clock saying one just did"


def test_an_unreadable_clock_fails_toward_pruning():
    """An unparseable timestamp must not become the reason retention stops — that is the
    failure this whole seam exists to end, arriving by a different door."""
    led = Ledger.default()
    led.session_events_clear()
    _emit("t-junk-old")
    _age_events(led, "t-junk-old", days=30)

    led.kv_put("session_log", "last_pruned_at", "not-a-timestamp")

    led._prune_if_overdue_at_open()
    assert led.session_events(limit=100, trace_id="t-junk-old") == []


# ── half two: MI-2's receipt ─────────────────────────────────────────────────────────

def test_a_graded_run_survives_the_sweep_and_its_ungraded_neighbour_does_not():
    """MI-2's stated receipt, both halves in one test because either alone is misleading:
    survival proves nothing if nothing is being swept."""
    led = Ledger.default()
    led.session_events_clear()

    _emit("t-graded", n=2)
    _emit("t-ungraded", n=2)
    _age_events(led, "t-graded", days=15)
    _age_events(led, "t-ungraded", days=15)

    assert led.pin_session_events(trace_id="t-graded") == 2

    led.session_events_prune(keep_days=14, max_rows=0)

    assert len(led.session_events(limit=100, trace_id="t-graded")) == 2, \
        "a graded run was swept — retention must follow grading"
    assert led.session_events(limit=100, trace_id="t-ungraded") == [], \
        "the ungraded neighbour survived — the sweep is not actually running"


def test_pinning_is_idempotent_so_regrading_keeps_the_original_timestamp():
    led = Ledger.default()
    led.session_events_clear()
    _emit("t-twice", n=2)

    assert led.pin_session_events(trace_id="t-twice") == 2
    first = {r["pinned_at"] for r in led.session_events(limit=10, trace_id="t-twice")}
    assert led.pin_session_events(trace_id="t-twice") == 0, "re-pinned an already-pinned row"
    assert {r["pinned_at"] for r in led.session_events(limit=10, trace_id="t-twice")} == first


def test_an_unfiltered_pin_is_refused():
    """A pin with no selector matches every row — a retention policy turned into a no-op
    from the other direction."""
    import pytest
    with pytest.raises(ValueError, match="trace_id or an investigation_id"):
        Ledger.default().pin_session_events()


def test_pinned_rows_do_not_consume_the_row_cap():
    """A graded run is evidence, not budget. If pins counted toward `max_rows`, grading
    enough runs would quietly starve the log of everything else."""
    led = Ledger.default()
    led.session_events_clear()
    _emit("t-cap-pinned", n=3)
    assert led.pin_session_events(trace_id="t-cap-pinned") == 3
    _emit("t-cap-fresh", n=3)

    led.session_events_prune(keep_days=0, max_rows=2)

    assert len(led.session_events(limit=100, trace_id="t-cap-pinned")) == 3
    assert len(led.session_events(limit=100, trace_id="t-cap-fresh")) == 2


def test_the_verdict_door_pins_its_run():
    """The wiring, not just the primitive: recording a verdict must be what pins."""
    from aughor.feedback.verdicts import record_verdict

    led = Ledger.default()
    led.session_events_clear()
    with _tel().bind_trace("t-verdict"):
        session_log.emit(session_log.TOOL_CALL, name="x", investigation_id="inv-mi2")

    record_verdict("conn-1", "inv-mi2", "accept", note="right answer")

    pinned = [r["pinned_at"] for r in led.session_events(limit=10, trace_id="t-verdict")]
    assert pinned and all(p for p in pinned), "the verdict door did not pin its evidence"
