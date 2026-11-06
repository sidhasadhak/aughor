"""Track C2 (docs/TENX_PROGRAM_2026-11-05.md §3): an effect re-checks the job's authority as it leaves.

The program's exit, as written: revoke a grant while a job is paused, resume it, and the effect is
refused and says so. Effects already leave through one gate (`govern/departure.gate_departure`, held
to every transport by `test_departure_every_exit_gated`), so the check is a law there — `authority` —
reading the authority C1 wrote on the job row and the person's roles NOW. The paused job here is a
real kernel job waiting on an event; the revocation is the real role store; the send is the real gate.
"""
from __future__ import annotations

import asyncio

import pytest

from aughor.govern import departure as D
from aughor.govern.departure_store import get_departure
from aughor.kernel.jobs import JobKernel
from aughor.kernel.ledger import Ledger
from aughor.org.context import reset_user_id, set_user_id, using_org
from aughor.rbac.store import assign_role, revoke_role

TEXT = "The weekly review is ready to read."          # no numbers: only the authority law can hold it


def _send(org: str) -> D.DepartureVerdict:
    return D.gate_departure(kind="slack_post", org_id=org, conn_id="", text=TEXT, target="#c2",
                            automation_id="auto-c2", automation_name="C2 probe")


def _paused_job(ledger: Ledger, org: str, person: str, between) -> D.DepartureVerdict:
    """Submit as ``person``; the job waits on a gate (the pause), ``between()`` runs, then it sends."""
    async def main():
        k, resume, out = JobKernel(ledger), asyncio.Event(), {}

        async def work():
            await resume.wait()
            out["verdict"] = _send(org)

        tok = set_user_id(person)
        try:
            with using_org(org):
                jid = await k.submit("automation", work)
        finally:
            reset_user_id(tok)
        await asyncio.sleep(0.05)               # the job is running, waiting
        between()
        resume.set()
        while jid in k._tasks:
            await asyncio.sleep(0.01)
        return out["verdict"]
    return asyncio.run(main())


@pytest.fixture
def signed_in(monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")        # the suite declares the proxy (conftest)
    monkeypatch.setenv("AUGHOR_RBAC_AUTO_BOOTSTRAP", "0")
    # The gate reads the job row through the default ledger; the kernel writes through this one.
    return Ledger.default()


def test_a_role_revoked_while_the_job_waited_holds_the_send_and_says_why(signed_in):
    org = "c2-revoke"
    assign_role(org, "ana", "analyst")
    v = _paused_job(signed_in, org, "ana", between=lambda: revoke_role(org, "ana", "analyst"))
    assert v.state == D.HELD and v.guards["authority"] == D.HOLDS
    assert any("no longer holds resource.export" in r and "held analyst when the job was submitted" in r
               for r in v.reasons), v.reasons
    row = get_departure(v.record_id)
    assert row and row["state"] == D.HELD                                       # the hold is a ledger row


def test_the_same_job_with_the_role_kept_departs(signed_in):
    org = "c2-kept"
    assign_role(org, "ben", "analyst")
    v = _paused_job(signed_in, org, "ben", between=lambda: None)
    assert v.guards["authority"] == D.PASSED and v.state == D.DEPARTED, (v.state, v.reasons)


def test_a_viewer_never_had_it(signed_in):
    org = "c2-viewer"
    assign_role(org, "vic", "viewer")
    v = _paused_job(signed_in, org, "vic", between=lambda: None)
    assert v.guards["authority"] == D.HOLDS and v.state == D.HELD


def test_outside_a_job_the_door_already_checked():
    v = _send("c2-door")
    assert v.guards["authority"] == D.NOT_APPLICABLE


def test_sign_in_off_is_exempt_and_says_so(monkeypatch):
    monkeypatch.delenv("AUGHOR_REQUIRE_IDENTITY", raising=False)
    v = _paused_job(Ledger.default(), "default", "", between=lambda: None)
    assert v.guards["authority"] == D.EXEMPT and "one operator" in v.checks["authority"]


def test_a_clocks_job_has_no_person_to_recheck(signed_in):
    v = _paused_job(signed_in, "c2-clock", "", between=lambda: None)
    assert v.guards["authority"] == D.NOT_APPLICABLE and "started by no person" in v.checks["authority"]


def test_an_unreadable_authority_holds_under_sign_in(signed_in, monkeypatch):
    """Fail closed: unlike an accuracy guard's hiccup, a sender who cannot be established does not send."""
    org = "c2-broken"
    assign_role(org, "dee", "analyst")

    def broken(_p):
        raise RuntimeError("role store unreachable")

    v = _paused_job(signed_in, org, "dee",
                    between=lambda: monkeypatch.setattr("aughor.rbac.resolver.resolve_roles", broken))
    assert v.guards["authority"] == D.HOLDS and any("could not be re-checked" in r for r in v.reasons)
