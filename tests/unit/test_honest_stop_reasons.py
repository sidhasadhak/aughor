"""A run that ends without an answer says why, briefly, and then what to do.

The 09-16 morning run, as its history read: "the investigation ended failed after 0 queries,
with no answer — the SSE stream ended with the run still 'running' — the client disconnected
as agent ua_6d903822bb54". Every clause but "failed" was false. The kernel had cancelled it
at the Analyst's 900s time budget after 54 model calls; nobody disconnected; the zero came
from a meter nothing wrote to, because `_metered_stream` started its own accumulator inside
the job and shadowed the job's.

Hermetic: the kernel runs on a temp ledger, the history store is the conftest-isolated one,
and no model is called — spend is recorded straight onto the meter.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from aughor.kernel import jobs as J
from aughor.kernel import metering
from aughor.kernel.jobs import JobKernel, JobState, stop_sentence
from aughor.kernel.ledger import Ledger


@pytest.fixture()
def ledger(tmp_path):
    return Ledger(tmp_path / "system.db")


def _gov(**kw):
    return SimpleNamespace(token_budget=kw.get("token_budget"),
                           time_budget_s=kw.get("time_budget_s"), model=None)


async def _wait_terminal(k: JobKernel, ledger: Ledger, jid: str) -> dict:
    for _ in range(500):
        row = ledger.job_get(jid) or {}
        if row.get("state") in JobState.TERMINAL and jid not in k._tasks:
            return row
        await asyncio.sleep(0.01)
    pytest.fail(f"job {jid} never finished")


# ── the meter ─────────────────────────────────────────────────────────────────

def test_an_answer_stream_inside_a_job_meters_into_the_job(ledger, monkeypatch):
    """THE regression: every analyst-body job flushed zero spend, 09-10 through 09-16."""
    from aughor.routers.investigations import _metered_stream

    monkeypatch.setattr(JobKernel, "_resolve_governance", lambda self, jid: (_gov(), "analyst"))

    async def body():
        metering.record_llm(prompt_tokens=700, completion_tokens=300)
        metering.record_query(rows=5, ms=1.0, sql="SELECT 1")
        yield "data: {}\n\n"

    async def main():
        k = JobKernel(ledger)

        async def work():
            async for _ in _metered_stream(body(), budget=None):
                pass

        jid = await k.submit("investigation", work, conn_id="c1")
        return await _wait_terminal(k, ledger, jid)

    row = asyncio.run(main())
    assert row["state"] == JobState.SUCCEEDED
    assert row["metrics"]["llm_calls"] == 1 and row["metrics"]["total_tokens"] == 1_000
    assert row["metrics"]["query_count"] == 1


@pytest.mark.anyio
async def test_outside_a_job_the_answer_stream_still_meters_itself():
    from aughor.routers.investigations import _metered_stream

    seen: dict = {}

    async def body():
        metering.record_llm(prompt_tokens=10, completion_tokens=5)
        seen["m"] = metering.current()
        yield "data: {}\n\n"

    assert metering.current() is None
    _ = [c async for c in _metered_stream(body(), budget=None)]
    assert seen["m"] is not None and seen["m"].total_tokens == 15
    assert metering.current() is None, "the stream's own accumulator is released after it"


# ── the reason ────────────────────────────────────────────────────────────────

def test_a_budget_kill_names_the_budget_the_spend_and_the_fix(ledger, monkeypatch):
    """Through the REAL heartbeat: the reason is what the kernel knew when it cancelled."""
    monkeypatch.setattr(J, "_HEARTBEAT_SECONDS", 0.05)
    monkeypatch.setattr(JobKernel, "_resolve_governance",
                        lambda self, jid: (_gov(time_budget_s=900), "analyst"))
    monkeypatch.setattr(JobKernel, "_over_budget",
                        lambda self, jid, gov, elapsed: "time budget (900s)")
    said: dict = {}

    async def main():
        k = JobKernel(ledger)

        async def work():
            for _ in range(54):
                metering.record_llm(prompt_tokens=100, completion_tokens=10)
            for _ in range(12):
                metering.record_query(rows=1, ms=1.0)
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError as exc:
                said["reason"] = J.describe_stop(exc)
                raise

        jid = await k.submit("investigation", work, conn_id="c1")
        await _wait_terminal(k, ledger, jid)
        return jid

    jid = asyncio.run(main())
    assert said["reason"] == (
        "Stopped at the Analyst's 900s time budget before answering (54 model calls, "
        "12 queries). Bind a faster model in Settings → Models, or raise time_budget_s "
        "with PATCH /agents/analyst.")
    assert jid not in J._stop_reasons, "a finished job's reason must not linger"


def test_a_person_cancel_is_named_as_one(ledger, monkeypatch):
    monkeypatch.setattr(JobKernel, "_resolve_governance", lambda self, jid: (_gov(), "analyst"))
    said: dict = {}

    async def main():
        k = JobKernel(ledger)
        started = asyncio.Event()

        async def work():
            started.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError as exc:
                said["reason"] = J.describe_stop(exc)
                raise

        jid = await k.submit("investigation", work, conn_id="c1")
        await started.wait()
        k.cancel(jid, reason="a person cancelled it")
        await _wait_terminal(k, ledger, jid)

    asyncio.run(main())
    assert said["reason"] == ("Stopped before answering (0 model calls, 0 queries) — "
                              "a person cancelled it.")


@pytest.mark.parametrize("kw,expected", [
    (dict(reason="budget exceeded: token budget (500,000 tokens)", in_job=True, cancelled=True,
          agent_id="analyst", agent="Analyst", llm_calls=80, queries=30),
     "Stopped at the Analyst's 500,000-token budget before answering (80 model calls, "
     "30 queries). Ask a narrower question, or raise token_budget with PATCH /agents/analyst."),
    (dict(reason="", in_job=True, cancelled=True, llm_calls=1, queries=1),
     "Cancelled before answering (1 model call, 1 query), with no recorded reason (an API "
     "restart does this). Run it again."),
    (dict(reason="", in_job=False, cancelled=True),
     "Stopped before answering — the request streaming it ended (a closed page or an API "
     "restart). Ask again."),
    # A cause nobody classified gets no invented advice.
    (dict(reason="", in_job=True, cancelled=False, error="warehouse unreachable"),
     "Stopped before answering: warehouse unreachable"),
])
def test_each_cause_reads_as_itself(kw, expected):
    assert stop_sentence(**kw) == expected


# ── the record, and the run history that quotes it ────────────────────────────

@pytest.mark.anyio
async def test_the_bridge_records_the_budget_not_a_disconnect(monkeypatch):
    """End to end through `_job_streamed_body` on the process kernel: the row a budget-killed
    analyst run leaves behind carries the budget sentence."""
    from aughor.db import history
    from aughor.routers import investigations as inv

    monkeypatch.setattr(J, "_HEARTBEAT_SECONDS", 0.05)
    monkeypatch.setattr(JobKernel, "_resolve_governance",
                        lambda self, jid: (_gov(time_budget_s=0.2), "analyst"))
    inv_id = history.create_investigation("anomalies yesterday?", "conn-hsr")

    async def body():
        yield f'data: {json.dumps({"type": "start", "investigation_id": inv_id})}\n\n'
        metering.record_llm(prompt_tokens=50, completion_tokens=5)
        await asyncio.sleep(30)                       # the slow model; the budget ends it
        yield "data: {}\n\n"                          # pragma: no cover

    _ = [f async for f in inv._job_streamed_body(lambda: body(), session_id="",
                                                 conn_id="conn-hsr")]
    for _ in range(200):
        row = history.get_investigation(inv_id)
        if row["status"] != "running":
            break
        await asyncio.sleep(0.01)
    assert row["status"] == "failed"
    assert row["error"].startswith("Stopped at the Analyst's 0.2s time budget before answering "
                                   "(1 model call, 0 queries).")
    assert "disconnect" not in row["error"]


def test_a_failed_step_ends_on_its_advice(monkeypatch):
    """The agent rides the outcome's own `agent_id`; appending it after the advice buried
    the one sentence the reader acts on."""
    from aughor.automations.engine import _dispatch_investigate
    from aughor.automations.models import Automation, Condition, Effect
    from aughor.runners import InvestigationRun

    reason = ("Stopped at the Analyst's 900s time budget before answering (54 model calls, "
              "12 queries). Bind a faster model in Settings → Models, or raise time_budget_s "
              "with PATCH /agents/analyst.")
    monkeypatch.setattr("aughor.runners.run_investigation",
                        lambda req, **kw: InvestigationRun("failed", reason, basis="inline"))
    automation = Automation(conn_id="conn-h1", name="Anomalies to Slack",
                            conditions=[Condition(kind="schedule", config={"cron": "0 9 * * *"})],
                            effects=[Effect(kind="notify", config={"trigger_id": "t1"})])
    effect = Effect(kind="investigate",
                    config={"question": "anomalies?", "agent_id": "ua_6d903822bb54"})

    outcome = _dispatch_investigate(effect, automation)
    assert outcome.status == "failed" and outcome.message == reason
