"""A job's budget must reach the threads its run dispatches into (2026-09-22).

The kernel enforced budgets from the heartbeat alone: `_over_budget` → `task.cancel()`.
A cancel raises CancelledError at the coroutine's next await — but a synchronous loop
the run handed to an executor thread (the birth job's intelligence step: one model call
per table under `run_in_executor`) never awaits. The thread ran to completion with its
spend METERED and never ENFORCED; the job row said CANCELLED while the calls kept
going. The provider already calls `metering.check_budget()` after every call and the
context executor already carries contextvars into threads — what was missing was the
kernel arming the job's own governance as the run's in-context budget. Now the call
that crosses the line is the last one, in any thread.

No pytest-asyncio in the env — each test drives the kernel inside asyncio.run, the
way test_budget_enforcement_scope does.
"""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from aughor.kernel import jobs as J
from aughor.kernel import metering
from aughor.kernel.jobs import JobKernel, JobState
from aughor.kernel.ledger import Ledger


@pytest.fixture()
def ledger(tmp_path):
    return Ledger(tmp_path / "system.db")


def _gov(token_budget=None, time_budget_s=None):
    return SimpleNamespace(token_budget=token_budget, time_budget_s=time_budget_s, model=None)


def _thread_loop(calls: list, *, n: int = 10, tokens: int = 60, sleep_s: float = 0.0):
    """The autoseed shape: one metered call per table inside a fail-open try/except —
    the exact loop a cancel could not stop. `metering.check_budget()` after the record
    is what the LLM funnel does after every real call."""
    def run():
        for i in range(n):
            try:
                if sleep_s:
                    time.sleep(sleep_s)
                metering.record_llm(prompt_tokens=tokens - 10, completion_tokens=10)
                calls.append(i)
                metering.check_budget()
            except Exception:          # the loop's own fail-open branch — must NOT catch it
                continue
    return run


def _drive(ledger, work, *, install_context_executor: bool = True) -> tuple[str, dict]:
    async def main():
        loop = asyncio.get_running_loop()
        if install_context_executor:
            from aughor.kernel.concurrency import ContextThreadPoolExecutor
            loop.set_default_executor(ContextThreadPoolExecutor(thread_name_prefix="test-exec"))
        k = JobKernel(ledger)
        jid = await k.submit("profile", lambda: work(loop), conn_id="c1")
        while jid in k._tasks:
            await asyncio.sleep(0.01)
        return jid
    jid = asyncio.run(main())
    return jid, (ledger.job_get(jid) or {})


# ── the defect, closed ──────────────────────────────────────────────────────────────

def test_a_thread_loop_stops_on_the_jobs_token_budget_without_the_heartbeat(ledger, monkeypatch):
    """Budget 100, 60 tokens a call: the 2nd call crosses (120 > 100) and is the LAST —
    the loop's `except Exception` cannot swallow it, the run ends CANCELLED with the
    heartbeat's own reason string, and the heartbeat itself never got a turn."""
    monkeypatch.setattr(J, "_HEARTBEAT_SECONDS", 3600)
    monkeypatch.setattr(JobKernel, "_resolve_governance",
                        lambda self, jid: (_gov(token_budget=100), "curator"))
    calls: list = []

    async def work(loop):
        await loop.run_in_executor(None, _thread_loop(calls))

    jid, row = _drive(ledger, work)
    assert calls == [0, 1], calls
    assert row["state"] == JobState.CANCELLED
    assert row["error"] == "budget exceeded: token budget (100 tokens)"
    assert row["metrics"]["total_tokens"] == 120          # what was spent is still flushed
    events = [e for e in ledger.events(kind="budget.exceeded") if e.get("job_id") == jid]
    assert events and events[0]["payload"]["agent"] == "curator"


def test_mutation_no_budget_lets_the_same_loop_run_to_completion(ledger, monkeypatch):
    """Proves the previous test stopped BECAUSE of the armed budget: unbounded
    governance, same loop, every call runs and the job succeeds."""
    monkeypatch.setattr(J, "_HEARTBEAT_SECONDS", 3600)
    monkeypatch.setattr(JobKernel, "_resolve_governance", lambda self, jid: (_gov(), "curator"))
    calls: list = []

    async def work(loop):
        await loop.run_in_executor(None, _thread_loop(calls))

    _, row = _drive(ledger, work)
    assert calls == list(range(10))
    assert row["state"] == JobState.SUCCEEDED and row["metrics"]["total_tokens"] == 600


def test_the_stdlib_executor_would_still_lose_it_which_is_why_the_api_installs_the_context_one(
        ledger, monkeypatch):
    """The other half of the mechanism, kept loud: without the context executor the
    thread sees no budget and no accumulator — the loop runs to the end and the job
    even flushes ZERO spend. `test_metering_crosses_executor` pins that the API
    lifespan installs the executor; this pins why the budget needs it too."""
    monkeypatch.setattr(J, "_HEARTBEAT_SECONDS", 3600)
    monkeypatch.setattr(JobKernel, "_resolve_governance",
                        lambda self, jid: (_gov(token_budget=100), "curator"))
    calls: list = []

    async def work(loop):
        await loop.run_in_executor(None, _thread_loop(calls))

    _, row = _drive(ledger, work, install_context_executor=False)
    assert calls == list(range(10))
    assert row["state"] == JobState.SUCCEEDED and row["metrics"]["total_tokens"] == 0


def test_the_time_budget_fires_in_context_too(ledger, monkeypatch):
    monkeypatch.setattr(J, "_HEARTBEAT_SECONDS", 3600)
    monkeypatch.setattr(JobKernel, "_resolve_governance",
                        lambda self, jid: (_gov(time_budget_s=1), "curator"))
    calls: list = []

    async def work(loop):
        await loop.run_in_executor(None, _thread_loop(calls, n=3, sleep_s=0.6))

    _, row = _drive(ledger, work)
    assert calls == [0, 1]                      # 1.2 s elapsed at the 2nd check > 1 s
    assert row["state"] == JobState.CANCELLED
    assert row["error"] == "budget exceeded: time budget (1s)"


def test_a_job_runs_under_its_own_budget_not_the_asks_it_was_submitted_from(ledger, monkeypatch):
    """A deep /ask submits its investigation job from inside the ask's metered stream,
    so the job's context copy carries the Responder's budget. Inside the job the job's
    governance is the law: 500 tokens against the ask's 10-token cap must SUCCEED under
    the job's 1,000 — and the ask's own budget is untouched afterwards."""
    monkeypatch.setattr(J, "_HEARTBEAT_SECONDS", 3600)
    monkeypatch.setattr(JobKernel, "_resolve_governance",
                        lambda self, jid: (_gov(token_budget=1_000), "analyst"))

    async def main():
        ask_token = metering.set_budget(10, None)          # the ask's cap, armed first
        try:
            k = JobKernel(ledger)

            async def work():
                metering.record_llm(prompt_tokens=400, completion_tokens=100)
                metering.check_budget()

            jid = await k.submit("investigation", work, conn_id="c1")
            while jid in k._tasks:
                await asyncio.sleep(0.01)
            assert metering.current_budget() == (10, None)   # the ask's budget survived
            return jid
        finally:
            metering.clear_budget(ask_token)

    jid = asyncio.run(main())
    assert ledger.job_get(jid)["state"] == JobState.SUCCEEDED


def test_the_heartbeat_path_is_unchanged_and_agrees_on_the_reason(ledger, monkeypatch):
    """Both guards write the same sentence — reconcile's `_BUDGET_STOP` must parse the
    in-context one exactly as it parses the heartbeat's."""
    assert J._BUDGET_STOP.match("budget exceeded: token budget (100 tokens)")
    assert J._BUDGET_STOP.match("budget exceeded: time budget (1s)")
