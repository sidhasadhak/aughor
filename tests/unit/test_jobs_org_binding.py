"""Background jobs re-bind their own org at execution (DATA-06 under identity).

The org is captured on the job row at submit; the kernel must RE-BIND it when the
job runs, so a job re-run by boot-recovery (no request context, ambient org =
'default') still operates in its own tenant — not 'default'.
"""
from __future__ import annotations

import asyncio

import pytest

from aughor.kernel.jobs import JobKernel, JobState
from aughor.kernel.ledger import Ledger
from aughor.org.context import DEFAULT_ORG_ID, current_org_id, using_org


@pytest.fixture()
def ledger(tmp_path):
    return Ledger(tmp_path / "system.db")


def _run(coro):
    return asyncio.run(coro)


def test_run_binds_the_row_org_without_ambient_context(ledger):
    # Ambient org is the default — this is the boot-recovery / scheduler scenario
    # where nothing bound an org before the job runs.
    assert current_org_id() == DEFAULT_ORG_ID

    k = JobKernel(ledger)
    ledger.job_insert({
        "id": "j-acme", "kind": "test", "org_id": "acme", "attempt": 1,
        "state": JobState.PENDING, "created_at": "2026-07-03T00:00:00Z",
    })

    seen = {}

    async def work():
        seen["org"] = current_org_id()

    _run(k._run("j-acme", work, None))

    assert seen["org"] == "acme"                 # bound from the row, NOT the default ambient
    assert current_org_id() == DEFAULT_ORG_ID     # and reset afterwards


def test_submitted_job_carries_the_submitters_org(ledger):
    async def main():
        k = JobKernel(ledger)
        seen = {}

        async def work():
            seen["org"] = current_org_id()

        with using_org("beta-org"):
            jid = await k.submit("test", work, conn_id="c1")
        while jid in k._tasks:
            await asyncio.sleep(0.01)
        return jid, seen

    jid, seen = _run(main())
    # The row captured the submitter's org, and the run bound it.
    assert ledger.job_get(jid)["org_id"] == "beta-org"
    assert seen["org"] == "beta-org"
