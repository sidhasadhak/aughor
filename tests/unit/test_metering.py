"""Per-run compute metering (R1) — the accumulator, its no-op-when-idle contract,
fail-open recording, cross-executor context propagation, the job-row flush, and
the normalized `cost` on the Trust Receipt.

No pytest-asyncio in the env — async cases drive the loop inside asyncio.run.
"""
import asyncio
import json

import pytest

from aughor.kernel import metering
from aughor.kernel.concurrency import ContextThreadPoolExecutor
from aughor.kernel.jobs import JobKernel, JobState
from aughor.kernel.ledger import Ledger


@pytest.fixture()
def ledger(tmp_path):
    return Ledger(tmp_path / "system.db")


def run(coro):
    return asyncio.run(coro)


class TestAccumulator:
    def test_noop_outside_a_run(self):
        # The whole point: un-metered code is unaffected — records vanish, no crash.
        metering.record_llm(10, 20, 5.0)
        metering.record_query(100, 1.0)
        assert metering.snapshot() is None

    def test_metered_accumulates_and_resets(self):
        with metering.metered():
            metering.record_llm(10, 20, 5.0)
            metering.record_llm(1, 2, 1.0)
            metering.record_query(100, 12.0)
            snap = metering.snapshot()
        assert snap["llm_calls"] == 2
        assert snap["prompt_tokens"] == 11 and snap["completion_tokens"] == 22
        assert snap["total_tokens"] == 33
        assert snap["query_count"] == 1 and snap["rows_returned"] == 100
        assert snap["llm_ms"] == 6.0 and snap["query_ms"] == 12.0
        assert metering.snapshot() is None  # context restored on exit

    def test_record_is_fail_open(self):
        # A bad token value must never raise into the caller (it's a hot path).
        with metering.metered():
            metering.record_llm(object(), 5, 1.0)  # int(object()) raises → swallowed
            snap = metering.snapshot()
        assert snap is not None  # nothing propagated


class TestExecutorPropagation:
    def test_contextvar_crosses_run_in_executor(self):
        # The mechanism the whole design hinges on: the accumulator set on the loop
        # must be visible inside the worker thread where LLM/SQL actually run.
        async def main():
            loop = asyncio.get_event_loop()
            loop.set_default_executor(ContextThreadPoolExecutor())
            with metering.metered():
                def work():  # runs in a worker thread
                    seen = metering.current() is not None
                    metering.record_llm(5, 5, 1.0)
                    return seen
                seen = await loop.run_in_executor(None, work)
                return seen, metering.snapshot()

        seen, snap = run(main())
        assert seen is True
        assert snap["total_tokens"] == 10 and snap["llm_calls"] == 1

    def test_parallel_submits_accumulate_without_loss(self):
        # Parallel leaf calls share one RunMetrics object; the lock keeps the
        # read-modify-write from dropping increments.
        async def main():
            loop = asyncio.get_event_loop()
            loop.set_default_executor(ContextThreadPoolExecutor(max_workers=8))
            with metering.metered():
                def work(_):
                    metering.record_query(1, 1.0)
                await asyncio.gather(*(loop.run_in_executor(None, work, i) for i in range(50)))
                return metering.snapshot()

        snap = run(main())
        assert snap["query_count"] == 50 and snap["rows_returned"] == 50


class TestJobFlush:
    def test_metrics_flushed_to_job_row(self, ledger):
        async def main():
            k = JobKernel(ledger)

            async def work():  # runs in the job task → sees _run's accumulator
                metering.record_llm(100, 50, 10.0)
                metering.record_query(7, 2.0)

            jid = await k.submit("investigation", work, conn_id="c1")
            while jid in k._tasks:
                await asyncio.sleep(0.01)
            return jid

        jid = run(main())
        job = ledger.job_get(jid)
        assert job["state"] == JobState.SUCCEEDED
        assert isinstance(job["metrics"], dict)
        assert job["metrics"]["total_tokens"] == 150
        assert job["metrics"]["query_count"] == 1 and job["metrics"]["rows_returned"] == 7

    def test_failed_run_still_records_spend(self, ledger):
        async def main():
            k = JobKernel(ledger)

            async def work():
                metering.record_llm(10, 0, 1.0)
                raise RuntimeError("boom after spending")

            jid = await k.submit("investigation", work, conn_id="c1")
            while jid in k._tasks:
                await asyncio.sleep(0.01)
            return jid

        jid = run(main())
        job = ledger.job_get(jid)
        assert job["state"] == JobState.FAILED
        assert job["metrics"]["prompt_tokens"] == 10  # spend recorded despite failure


class TestReceiptCost:
    def test_cost_from_job_metrics(self, ledger):
        ledger.job_insert({"id": "j1", "kind": "investigation", "state": "SUCCEEDED",
                           "attempt": 1, "created_at": "2026-01-01T00:00:00Z"})
        ledger.job_update("j1", metrics=json.dumps({"total_tokens": 42, "query_count": 3}))
        ledger.artifact_write("ada_report", "ada:c1:i1", {"headline": "x"},
                              conn_id="c1", created_by_job="j1")
        rec = ledger.receipt("ada:c1:i1")
        assert rec["cost"]["total_tokens"] == 42 and rec["cost"]["query_count"] == 3
        assert rec["job"]["metrics"]["total_tokens"] == 42

    def test_cost_from_artifact_when_no_job(self, ledger):
        # the synchronous chat path: no job, cost stamped into the artifact payload
        ledger.artifact_write("chat_turn", "chat:c1:t1",
                              {"headline": "x", "cost": {"total_tokens": 9, "llm_calls": 1}},
                              conn_id="c1")
        rec = ledger.receipt("chat:c1:t1")
        assert rec["job"] is None
        assert rec["cost"]["total_tokens"] == 9

    def test_cost_absent_is_none(self, ledger):
        ledger.artifact_write("chat_turn", "chat:c1:t2", {"headline": "x"}, conn_id="c1")
        rec = ledger.receipt("chat:c1:t2")
        assert rec["cost"] is None  # graceful: older/unmetered answers


class TestInContextBudget:
    def test_budget_exceeded_is_base_exception(self):
        # The crux: it must unwind past the answer path's `except Exception`.
        assert issubclass(metering.BudgetExceeded, BaseException)
        assert not issubclass(metering.BudgetExceeded, Exception)

    def test_check_budget_noop_without_armed_budget(self):
        with metering.metered():
            metering.record_llm(10_000, 0, 1.0)
            metering.check_budget()   # no budget armed → never raises (job paths)

    def test_check_budget_raises_over_token_budget(self):
        with metering.metered():
            tok = metering.set_budget(100, None)
            try:
                metering.record_llm(50, 0, 1.0)
                metering.check_budget()                    # 50 ≤ 100 → ok
                metering.record_llm(80, 0, 1.0)            # now 130 > 100
                with pytest.raises(metering.BudgetExceeded) as ei:
                    metering.check_budget()
                assert "token budget" in str(ei.value)
            finally:
                metering.clear_budget(tok)

    def test_check_budget_safe_outside_a_run(self):
        metering.check_budget()   # no run, no budget → no crash


def test_idempotent_metrics_migration(tmp_path):
    # constructing the ledger twice on the same path must not raise (the ALTER guard)
    p = tmp_path / "system.db"
    Ledger(p)
    l2 = Ledger(p)  # second construct → column already present → no-op
    l2.job_insert({"id": "j", "kind": "x", "state": "PENDING",
                   "attempt": 1, "created_at": "2026-01-01T00:00:00Z"})
    l2.job_update("j", metrics=json.dumps({"total_tokens": 1}))
    assert l2.job_get("j")["metrics"]["total_tokens"] == 1
