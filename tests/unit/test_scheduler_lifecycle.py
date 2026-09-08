"""The app's clocks: switchable off, and actually stopped when the app stops.

Both halves of one investigation. `test_store_pool` asserted `120 == 1` and
`test_slack_delivery` found jittered backoff in a list that had to equal `[7.0]` — two
flakes, one cause, traced by instrumenting `connect_store`:

    apscheduler/executors/base.py:131   run_job
    aughor/automations/scheduler.py:54  tick_once
    aughor/automations/store.py:281     list_automations
    aughor/db/backend.py:403            connect_store

The `client` fixture is session-scoped, so the app's lifespan runs once and its
APScheduler threads then tick for the entire session — ~5 store opens per 60-second
tick, landing in whatever a later test had patched onto a process-global seam.

Two things were wrong, and they are separate:

  * Nothing turned the clocks off for a process that only wants the routes. Now
    `AUGHOR_DISABLE_SCHEDULERS` does, and `conftest.py` sets it.
  * Nothing ever STOPPED them. Both scheduler modules have carried a `stop()` since
    they were written and no caller existed — the lifespan's shutdown reasoned about
    asyncio tasks, and these are daemon THREADS. In production the process exits and
    the threads die with it, which is why it stayed invisible.
"""
from __future__ import annotations

import threading

import pytest

from aughor import api


# ── the switch ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value,off", [
    ("1", True), ("true", True), ("TRUE", True), ("yes", True), (" 1 ", True),
    ("0", False), ("false", False), ("no", False), ("", False),
])
def test_the_switch_reads_the_obvious_spellings(monkeypatch, value, off):
    monkeypatch.setenv("AUGHOR_DISABLE_SCHEDULERS", value)
    assert api._schedulers_disabled() is off


def test_absence_means_clocks_run(monkeypatch):
    """The default has to be "on". A deployment that forgets this variable must get a
    working platform, not a silent one."""
    monkeypatch.delenv("AUGHOR_DISABLE_SCHEDULERS", raising=False)
    assert api._schedulers_disabled() is False


def test_the_switch_is_read_per_call_not_captured_at_import(monkeypatch):
    """`conftest` sets it before the app is constructed but after this module is
    imported. A value frozen at import would ignore that and the clocks would run."""
    monkeypatch.setenv("AUGHOR_DISABLE_SCHEDULERS", "0")
    assert api._schedulers_disabled() is False
    monkeypatch.setenv("AUGHOR_DISABLE_SCHEDULERS", "1")
    assert api._schedulers_disabled() is True


# ── stopping ──────────────────────────────────────────────────────────────────

def test_stopping_is_safe_when_nothing_was_started():
    """The shutdown path runs on every app teardown, including one where the clocks
    were switched off and there is nothing to stop."""
    api._stop_schedulers()
    api._stop_schedulers()          # idempotent


def test_a_scheduler_that_refuses_to_stop_does_not_block_shutdown(monkeypatch):
    """A stuck clock must not keep an app from exiting — and it must be reported
    rather than swallowed."""
    import aughor.automations.scheduler as autos

    def _refuse() -> None:
        raise RuntimeError("scheduler wedged")

    monkeypatch.setattr(autos, "stop", _refuse)
    api._stop_schedulers()          # must not raise


def test_both_schedulers_are_asked_to_stop(monkeypatch):
    """The bug was a `stop()` nobody called. Pin that BOTH are reached, because one of
    two is the shape this arrives in again."""
    import aughor.automations.scheduler as autos
    import aughor.monitors.scheduler as monitors

    called: list[str] = []
    monkeypatch.setattr(autos, "stop", lambda: called.append("automations"))
    monkeypatch.setattr(monitors, "stop", lambda: called.append("monitors"))

    api._stop_schedulers()

    assert sorted(called) == ["automations", "monitors"]


# ── the property that matters ─────────────────────────────────────────────────

def test_the_test_process_runs_no_clock(client):
    """The whole point, asserted end to end.

    `client` boots the real app. With the switch on, the automation heartbeat must
    report that no clock is running here — otherwise a 60-second tick is loose in the
    suite, opening stores on a background thread for the rest of the session.
    """
    from aughor.automations.scheduler import clock

    state, reason = clock()
    assert state != "heartbeat", (
        f"an in-process clock is ticking during the test suite ({state}: {reason}) — "
        f"background store opens will land in other tests' measurements")


def test_no_apscheduler_thread_outlives_the_app(client):
    """The leak in its most direct form. Before this, two APScheduler threads and a
    ThreadPoolExecutor were still alive at session end, which is also what hung
    interpreter teardown with `cannot schedule new futures after shutdown`."""
    client.get("/documents")        # force startup if it has not happened

    lingering = [t.name for t in threading.enumerate()
                 if "APScheduler" in t.name]
    assert lingering == [], f"scheduler threads are running in the test process: {lingering}"
