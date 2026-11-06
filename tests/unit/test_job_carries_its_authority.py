"""Track C1 (docs/TENX_PROGRAM_2026-11-05.md §3): a job carries the authority it runs on.

Before 2026-11-06 a job row held its organisation and nothing else: whose authority a queued or resumed
job was spending, with which roles, under which rules, was nowhere. Now `submit` writes it once —
person, org, how the person was known, roles, the permission table's version, purpose — the ledger
refuses to rewrite it, and a run binds the person even when it starts off any request (boot recovery,
another process). C2 will re-check it at every effect; this is the record that check will read.
"""
from __future__ import annotations

import asyncio

import pytest

from aughor.kernel.jobs import JobKernel, JobState
from aughor.kernel.ledger import Ledger
from aughor.org.context import current_actor, reset_user_id, set_actor, set_user_id, using_org
from aughor.rbac.policy import policy_version
from aughor.security.authz import local_operator


@pytest.fixture()
def ledger(tmp_path):
    return Ledger(tmp_path / "system.db")


async def _submit_and_wait(k: JobKernel, kind: str, work) -> str:
    jid = await k.submit(kind, work)
    while jid in k._tasks:
        await asyncio.sleep(0.01)
    return jid


def test_sign_in_off_the_operator_is_the_authority(ledger, monkeypatch):
    monkeypatch.delenv("AUGHOR_REQUIRE_IDENTITY", raising=False)
    jid = asyncio.run(_submit_and_wait(JobKernel(ledger), "c1-probe", lambda: asyncio.sleep(0)))
    auth = ledger.job_get(jid)["auth"]
    assert auth, "the job row carries no authority"
    assert auth["person"] == local_operator() and auth["verified_by"] == "sign-in off"
    assert auth["roles"] == ["owner"] and auth["purpose"] == "c1-probe"
    assert auth["policy"] == policy_version() and len(auth["policy"]) == 12 and auth["at"]


def test_an_identified_caller_is_recorded_with_their_roles(ledger, monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")          # conftest declares the proxy
    monkeypatch.setenv("AUGHOR_RBAC_AUTO_BOOTSTRAP", "0")
    from aughor.rbac.store import assign_role
    assign_role("c1-org", "ana", "analyst")

    async def main():
        tok = set_user_id("ana")
        try:
            with using_org("c1-org"):
                return await _submit_and_wait(JobKernel(ledger), "c1-probe", lambda: asyncio.sleep(0))
        finally:
            reset_user_id(tok)

    auth = ledger.job_get(asyncio.run(main()))["auth"]
    assert auth == {**auth, "person": "ana", "org": "c1-org", "verified_by": "proxy", "roles": ["analyst"]}


def test_a_job_no_request_named_anyone_for_says_so(ledger, monkeypatch):
    """Identity enforced, no caller in context — a clock, the platform. Empty is said, never filled in."""
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    jid = asyncio.run(_submit_and_wait(JobKernel(ledger), "c1-clock", lambda: asyncio.sleep(0)))
    auth = ledger.job_get(jid)["auth"]
    assert auth["person"] == "" and auth["verified_by"] == "none" and auth["roles"] == []


def test_the_authority_is_written_once(ledger, monkeypatch):
    monkeypatch.delenv("AUGHOR_REQUIRE_IDENTITY", raising=False)
    jid = asyncio.run(_submit_and_wait(JobKernel(ledger), "c1-probe", lambda: asyncio.sleep(0)))
    before = ledger.job_get(jid)["auth"]
    with pytest.raises(ValueError, match="written once"):
        ledger.job_update(jid, auth={"person": "mallory"})
    ledger.job_update(jid, state=JobState.SUCCEEDED, error=None)          # every other field still moves
    assert ledger.job_get(jid)["auth"] == before


def test_a_run_off_any_request_acts_for_the_person_on_the_row(ledger):
    """The boot-recovery / second-process case: nothing bound an actor, the row names one."""
    ledger.job_insert({"id": "j-c1", "kind": "c1-probe", "org_id": "c1-org", "attempt": 1,
                       "state": JobState.PENDING, "created_at": "2026-11-06T00:00:00Z",
                       "auth": {"person": "ana", "org": "c1-org", "verified_by": "oidc", "roles": ["analyst"]}})
    seen = {}

    async def work():
        seen["actor"] = current_actor()

    tok = set_actor("")
    try:
        asyncio.run(JobKernel(ledger)._run("j-c1", work, None))
    finally:
        from aughor.org.context import reset_actor
        reset_actor(tok)
    assert seen["actor"] == "ana"


def test_a_row_written_before_c1_still_runs_and_reads_as_none(ledger, client):
    ledger.job_insert({"id": "j-old", "kind": "c1-probe", "org_id": "default", "attempt": 1,
                       "state": JobState.SUCCEEDED, "created_at": "2026-11-01T00:00:00Z"})
    assert ledger.job_get("j-old")["auth"] is None


def test_the_jobs_door_shows_it(client, monkeypatch):
    monkeypatch.delenv("AUGHOR_REQUIRE_IDENTITY", raising=False)
    from aughor.kernel.jobs import kernel
    led = Ledger.default()

    async def main():
        return await _submit_and_wait(kernel(), "c1-door", lambda: asyncio.sleep(0))

    jid = asyncio.run(main())
    body = client.get(f"/jobs/{jid}").json()
    assert body["auth"]["purpose"] == "c1-door" and body["auth"]["person"] == local_operator()
    assert led.job_get(jid)["auth"] == body["auth"]


def test_the_policy_version_moves_when_the_table_does(monkeypatch):
    from aughor.rbac import policy as P
    before = P.policy_version()
    monkeypatch.setitem(P.POLICY, ("GET", "/c1-probe"), P.P.ADMIN_MANAGE_ORG)
    assert P.policy_version() != before
