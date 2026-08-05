"""Lease-based job ownership across two kernel instances on ONE shared database.

The kernel's boot recovery assumed "a restart implies every non-terminal job died" —
its own docstring said so — which is only true while exactly one process ever runs.
These tests share a real Postgres between two Ledger/JobKernel instances (the
deployment §2 of docs/VERCEL_PLATFORM_DESIGN_2026-08-05.md asks for) and pin the
lease contract: a heartbeating job survives a peer's boot; a lapsed one is recovered
by WHICHEVER instance boots first. Skips when no live Postgres is reachable — the
whole point is two instances against one real shared database.
"""
from __future__ import annotations

import os

import pytest

from aughor.db import backend as B
from aughor.kernel.jobs import JobKernel, JobState
from aughor.kernel.ledger import Ledger

PG_URL = os.environ.get("AUGHOR_PG_TEST_URL", "postgres://postgres:aughor@localhost:5544/aughor")


def _pg_available() -> bool:
    try:
        import psycopg2
        psycopg2.connect(PG_URL, connect_timeout=2).close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _pg_available(), reason="needs a live shared Postgres")


@pytest.fixture()
def shared_ledgers(tmp_path, monkeypatch):
    """Two Ledger instances resolving the SAME path → the same Postgres schema:
    two processes' view of one shared database."""
    monkeypatch.setenv(B.DB_URL_ENV, PG_URL)
    path = tmp_path / "system.db"     # unique per test → its own schema, both share it
    yield Ledger(path), Ledger(path)


def _insert_running(ledger, job_id: str, *, hb_iso: str) -> None:
    ledger.job_insert({
        "id": job_id, "kind": "exploration", "conn_id": "c1", "canvas_id": None,
        "state": JobState.RUNNING, "payload": None, "idempotency_key": None,
        "attempt": 1, "created_at": hb_iso, "started_at": hb_iso, "heartbeat_at": hb_iso,
    })


def test_peer_boot_leaves_the_other_instances_running_job(shared_ledgers):
    """Instance A heartbeats a job; instance B boots against the same database.
    B must leave A's job RUNNING — under the old blanket rule it would have been
    failed and (being an exploration) respawned: a double-run."""
    from datetime import datetime, timezone
    a, b = shared_ledgers
    now = datetime.now(timezone.utc).isoformat()
    _insert_running(a, "job-owned-by-a", hb_iso=now)     # A's live heartbeat

    resumable = JobKernel(b).boot_recovery()             # B boots

    assert a.job_get("job-owned-by-a")["state"] == JobState.RUNNING
    assert resumable == []
    assert [e["job_id"] for e in b.events(kind="job.foreign")] == ["job-owned-by-a"]


def test_peer_boot_recovers_a_job_whose_owner_died(shared_ledgers):
    """The same two instances, but A's heartbeat lapsed (its process died): B's
    boot must recover it — orphan recovery is now a property of the LEASE, not of
    which process happens to restart."""
    from datetime import datetime, timedelta, timezone
    a, b = shared_ledgers
    stale = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
    _insert_running(a, "job-of-dead-a", hb_iso=stale)

    resumable = JobKernel(b).boot_recovery()

    row = b.job_get("job-of-dead-a")
    assert row["state"] == JobState.FAILED and "lease lapsed" in row["error"]
    assert [j["id"] for j in resumable] == ["job-of-dead-a"]   # respawnable exploration


def test_both_instances_see_one_anothers_writes_live(shared_ledgers):
    """The substrate check the two tests above rest on: a row written through A is
    immediately visible through B — one database, not two files."""
    from datetime import datetime, timezone
    a, b = shared_ledgers
    now = datetime.now(timezone.utc).isoformat()
    _insert_running(a, "job-visible", hb_iso=now)
    assert b.job_get("job-visible") is not None
    b.job_update("job-visible", error="stamped by b")
    assert a.job_get("job-visible")["error"] == "stamped by b"


# ── slice claims: the unit-of-work lease sliced execution runs on ────────────

def test_claim_contention_one_winner(shared_ledgers):
    """Two workers race one scope through separate instances: exactly one wins —
    the spike's HTTP-409 semantics as a kernel primitive."""
    a, b = shared_ledgers
    assert a.try_claim("explore:c1:angle7", "worker-a", lease_s=60) is True
    assert b.try_claim("explore:c1:angle7", "worker-b", lease_s=60) is False


def test_lapsed_claim_is_stolen_and_old_owner_cannot_renew(shared_ledgers):
    a, b = shared_ledgers
    assert a.try_claim("explore:c1:angle8", "worker-a", lease_s=-1)   # already lapsed
    assert b.try_claim("explore:c1:angle8", "worker-b", lease_s=60) is True
    # the previous owner must learn it lost the work — renew refuses
    assert a.renew_claim("explore:c1:angle8", "worker-a", lease_s=60) is False
    assert a.release_claim("explore:c1:angle8", "worker-a") is False   # not yours


def test_reclaim_by_same_owner_and_release_frees_the_scope(shared_ledgers):
    a, b = shared_ledgers
    assert a.try_claim("explore:c1:angle9", "worker-a", lease_s=60) is True
    assert a.try_claim("explore:c1:angle9", "worker-a", lease_s=60) is True   # re-entrant
    assert a.renew_claim("explore:c1:angle9", "worker-a", lease_s=60) is True
    assert a.release_claim("explore:c1:angle9", "worker-a") is True
    assert b.try_claim("explore:c1:angle9", "worker-b", lease_s=60) is True   # freed
