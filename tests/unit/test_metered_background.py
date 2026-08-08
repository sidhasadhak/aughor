"""WP-7 — background monitor/brief ticks metered through the job kernel.

The scheduled monitor/brief cron ran the runner DIRECTLY on the APScheduler thread, so
its warehouse SQL never joined the run metering (invisible in Fleet, uncancellable). Under
`ops.metered_monitors` the tick is submitted as a supervised Watcher/Briefer job, so its SQL
is metered + budget-enforced. These tests pin: the charters are wired (non-reserved, with
budgets), the routing decision follows the flag, the no-loop fallback runs inline, and a tick
routed through the kernel actually records its query in the job's flushed metrics.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time

from aughor.kernel import jobs as jobs_mod
from aughor.kernel import metering
from aughor.kernel.agents import charter_for_kind
from aughor.kernel.concurrency import ContextThreadPoolExecutor
from aughor.kernel.jobs import JobKernel, submit_background_tick


def test_watcher_briefer_charters_are_wired_with_budgets():
    """The monitor/brief kinds map to non-reserved agents with real per-run budgets."""
    w = charter_for_kind("monitor")
    b = charter_for_kind("brief")
    assert w.id == "watcher" and not w.reserved
    assert b.id == "briefer" and not b.reserved
    # A tick must carry a finite budget so the heartbeat can cancel a runaway run.
    assert w.default_budget.time_budget_s and w.default_budget.token_budget
    assert b.default_budget.time_budget_s and b.default_budget.token_budget


def test_submit_background_tick_no_loop_returns_none(monkeypatch):
    """With no captured main loop (a unit test / pre-startup), the bridge declines so the
    caller runs the work inline — never a crash, never a silent drop."""
    monkeypatch.setattr(jobs_mod, "_main_loop", None)
    ran = {"n": 0}
    out = submit_background_tick("monitor", lambda: ran.__setitem__("n", 1), conn_id="c1")
    assert out is None
    # The caller (not this helper) runs work_fn on the None path — helper did not run it.
    assert ran["n"] == 0


def test_monitor_tick_routes_through_the_kernel_with_inline_fallback(monkeypatch):
    """A background monitor tick offers itself to the kernel first; only a DECLINED
    submit (no captured loop → None) runs the same closure inline.

    The vehicle moved (flag endgame Wave 4, 2026-08-06): the legacy cron `_job` that
    carried this property was deleted with the legacy scheduler, and a monitor now
    ticks through the automation engine — `automations.scheduler._run_one` over the
    monitor read as a virtual automation. Same claim, current loop."""
    from aughor.automations.adopt import monitor_as_automation
    from aughor.automations import scheduler as auto_sched

    class _M:
        id, name, conn_id, enabled = "m1", "M", "c1", True
        check_cron = "* * * * *"

    monkeypatch.setattr("aughor.db.registry.get_connection_org", lambda cid: "default", raising=False)
    calls = {"submit": 0, "run": 0}
    monkeypatch.setattr("aughor.automations.engine.run_automation",
                        lambda a, **k: calls.__setitem__("run", calls["run"] + 1), raising=False)
    monkeypatch.setattr(jobs_mod, "submit_background_tick",
                        lambda *a, **k: (calls.__setitem__("submit", calls["submit"] + 1), "job1")[1])

    automation = monitor_as_automation(_M())

    # Metered is permanent (flag endgame Wave 2, 2026-08-06): every tick offers
    # itself to the kernel first…
    auto_sched._run_one(automation)
    assert calls["submit"] == 1 and calls["run"] == 0   # routed through the kernel

    # …and only a DECLINED submit (no captured loop → None) runs the same closure
    # inline — the no-loop fallback, not an env opt-out.
    monkeypatch.setattr(jobs_mod, "submit_background_tick",
                        lambda *a, **k: (calls.__setitem__("submit", calls["submit"] + 1), None)[1])
    auto_sched._run_one(automation)
    assert calls["submit"] == 2 and calls["run"] == 1   # declined → ran inline


class _FakeDB:
    dialect = "duckdb"

    def close(self):
        pass


def test_metered_tick_records_query_in_job_metrics(monkeypatch):
    """End-to-end: a tick submitted from a (simulated scheduler) thread runs as a kernel job
    whose metering accumulator captures the query the work issues — so it surfaces in the job
    row's metrics (Fleet/metering). Uses a real loop in a background thread with the
    context-propagating executor, exactly as production installs it."""
    loop = asyncio.new_event_loop()
    loop.set_default_executor(ContextThreadPoolExecutor(thread_name_prefix="test-exec"))
    # A fresh kernel bound to the (hermetic) default ledger; its concurrency semaphore is
    # created on THIS loop when the job runs.
    monkeypatch.setattr(jobs_mod, "_kernel", JobKernel())
    monkeypatch.setattr(jobs_mod, "_main_loop", loop)

    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    for _ in range(200):                       # wait for the loop to actually be running
        if loop.is_running():
            break
        time.sleep(0.01)
    try:
        def _work():
            # Stand in for a monitor's warehouse query — the metering chokepoint the real
            # db.execute hits (security_post → record_query).
            metering.record_query(rows=3, ms=2.0)

        job_id = submit_background_tick("monitor", _work, conn_id="c1", org_id="default")
        assert job_id, "the tick should have been submitted"

        # Wait for the supervised job to reach a terminal state.
        row = None
        for _ in range(100):
            row = jobs_mod.kernel().ledger.job_get(job_id)
            if row and row["state"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
                break
            time.sleep(0.05)
        assert row and row["state"] == "SUCCEEDED", row
        _m = row.get("metrics")
        metrics = _m if isinstance(_m, dict) else (json.loads(_m) if _m else {})
        assert metrics.get("query_count", 0) >= 1, metrics   # the tick was metered
        assert row.get("org_id") == "default"                # tenant stamped from submit
    finally:
        loop.call_soon_threadsafe(loop.stop)
        t.join(timeout=5)
        loop.close()
