"""RC-3 — a pending proposal's acceptance window is bounded, and closes CLOSED.

A proposal freezes its params at stage time; it cannot freeze the world those params were
reasoned about. An unbounded pending row is therefore an irreversible governed write waiting to
fire on stale justification — the live inbox held one for three days before a human resolved it.

The properties locked here, each of which a plausible implementation gets wrong:

* **Enforced in the accept path, not only in a sweeper.** A sweeper runs on a timer, so between
  lapse and sweep there is a window in which an expired proposal is still acceptable. These tests
  never call the sweeper before accepting, so they fail if enforcement lives only there.
* **Expiry withholds the side effect.** The dispatcher must not be reached — an expired accept
  that still dispatched would be the whole defect, dressed as a 410.
* **Resolve-once survives the clock.** An expired proposal is terminal: it cannot later be
  accepted, and re-accepting it does not re-run anything.
* **Fails CLOSED.** An unparseable timestamp reads as expired, never as fresh.
* **Legacy rows are covered.** Rows staged before RC-3 carry no `expires_at`; they must fall back
  to `created_at` + TTL rather than becoming immortal — the plane that records from creation is
  otherwise unreachable for everything that already exists.

Hermetic: the conftest temp DB, the real store, the real resolve-once UPDATE.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aughor.actions import inbox
from aughor.ontology.models import ActionParameter, KineticAction


def _action(**kw) -> KineticAction:
    base = dict(id="refund", kind="side_effect",
                params=[ActionParameter(name="order_id", data_type="VARCHAR", required=True)],
                submission_criteria=[], side_effects=[], risk="high")
    base.update(kw)
    return KineticAction(**base)


@pytest.fixture
def graph_of(monkeypatch):
    """Patch the ontology load so accept_proposal resolves the declared action."""
    def _install(action):
        class _G:
            kinetic_actions = {action.id: action}
        monkeypatch.setattr("aughor.ontology.store.load_latest_ontology",
                            lambda cid, schema=None: _G())
    return _install


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _ago(**kw) -> str:
    return _iso(datetime.now(timezone.utc) - timedelta(**kw))


def _proposal(**kw) -> inbox.StagedProposal:
    base = dict(connection_id="conn-a", action_id="refund", params={"order_id": "8821"})
    base.update(kw)
    return inbox.StagedProposal(**base)


# ── the deadline is stamped, and fixed ───────────────────────────────────────────

def test_stage_stamps_a_deadline():
    p = inbox.stage_proposal(_proposal(run_id="r1", call_id="c1"))
    assert p.expires_at, "a staged proposal must carry its own acceptance window"
    assert not p.expired
    assert inbox.get_proposal(p.id).expires_at == p.expires_at


def test_deadline_is_fixed_at_stage_time_not_recomputed(monkeypatch):
    """The terms a human was offered do not move because an operator retuned the default."""
    monkeypatch.setenv("AUGHOR_PROPOSAL_TTL_HOURS", "100")
    p = inbox.stage_proposal(_proposal(run_id="r2", call_id="c2"))
    stamped = p.expires_at
    monkeypatch.setenv("AUGHOR_PROPOSAL_TTL_HOURS", "1")
    assert inbox.get_proposal(p.id).expires_at == stamped


# ── the predicate ────────────────────────────────────────────────────────────────

def test_lapsed_deadline_is_expired():
    assert _proposal(expires_at=_ago(hours=1)).expired


def test_future_deadline_is_not_expired():
    assert not _proposal(expires_at=_iso(datetime.now(timezone.utc) + timedelta(hours=1))).expired


def test_resolved_proposal_is_never_expired():
    """Time stops deciding once a human has. A rejected row is rejected, not 'expired'."""
    assert not _proposal(expires_at=_ago(hours=99), status="rejected").expired


def test_unparseable_timestamp_fails_closed():
    """The failure must withhold a governed write, never authorise one."""
    assert _proposal(expires_at="not-a-timestamp").expired
    assert _proposal(created_at="not-a-timestamp").expired


def test_legacy_row_without_a_deadline_falls_back_to_created_at(monkeypatch):
    """Rows staged before RC-3 have expires_at=None and must NOT be immortal."""
    monkeypatch.setenv("AUGHOR_PROPOSAL_TTL_HOURS", "24")
    assert _proposal(expires_at=None, created_at=_ago(hours=48)).expired
    assert not _proposal(expires_at=None, created_at=_ago(hours=1)).expired


def test_zero_or_junk_ttl_is_ignored(monkeypatch):
    """A TTL of 0 would expire every proposal the instant it is staged — indistinguishable
    from the inbox being broken. The override is refused, not obeyed."""
    for bad in ("0", "-5", "", "abc"):
        monkeypatch.setenv("AUGHOR_PROPOSAL_TTL_HOURS", bad)
        assert inbox.ttl_hours() == 168.0, f"TTL override {bad!r} should be ignored"


# ── enforcement: the accept path, with no sweeper run first ──────────────────────

def test_expired_accept_is_refused_and_never_dispatches(monkeypatch, graph_of):
    # graph_of is load-bearing: without a resolvable action the accept path stops at
    # "declared action no longer exists" and never reaches the dispatcher ANYWAY, which
    # would make the `dispatched == []` assertion below true for the wrong reason.
    graph_of(_action())
    p = inbox.stage_proposal(_proposal(run_id="r3", call_id="c3", expires_at=_ago(hours=1)))

    dispatched: list = []
    monkeypatch.setattr("aughor.actions.executor.execute_kinetic_action",
                        lambda *a, **k: dispatched.append(a) or None)

    result, grant = inbox.accept_proposal(p.id, actor="analyst@example.com")

    assert result.status == "expired"
    assert result.ok is False
    assert result.http_status() == 410, "410 Gone — the caller was late, not wrong"
    assert dispatched == [], "an expired accept must NOT reach the dispatcher"
    assert grant == ""
    assert inbox.get_proposal(p.id).status == "expired"


def test_expired_is_terminal_and_cannot_be_accepted_later(monkeypatch, graph_of):
    graph_of(_action())   # see above — makes the no-dispatch assertion mean something
    p = inbox.stage_proposal(_proposal(run_id="r4", call_id="c4", expires_at=_ago(hours=1)))
    dispatched: list = []
    monkeypatch.setattr("aughor.actions.executor.execute_kinetic_action",
                        lambda *a, **k: dispatched.append(a) or None)

    inbox.accept_proposal(p.id, actor="first")
    second, _ = inbox.accept_proposal(p.id, actor="second")

    assert second.status in {"expired", "already_resolved"}
    assert dispatched == []
    assert inbox.get_proposal(p.id).resolved_by == "first"


def test_a_fresh_proposal_reaches_the_dispatcher(monkeypatch, graph_of):
    """The contrast case, and the reason the negative above means anything.

    Asserted as "the dispatcher WAS called", not "the status was not expired" — this test
    first passed while returning `dispatch_error` ("declared action no longer exists"),
    which is to say it passed without the proposal ever reaching execution. A guard test
    whose positive case never exercises the guarded path proves only that nothing crashed.
    """
    graph_of(_action())
    p = inbox.stage_proposal(_proposal(run_id="r5", call_id="c5"))
    assert not inbox.get_proposal(p.id).expired

    dispatched: list = []

    def _fake(*a, **k):
        dispatched.append(a)
        from aughor.actions.executor import KineticResult
        return KineticResult("executed", True, "refund")

    monkeypatch.setattr("aughor.actions.executor.execute_kinetic_action", _fake)
    result, _ = inbox.accept_proposal(p.id, actor="analyst")

    assert dispatched, "a fresh proposal MUST reach the dispatcher"
    assert result.status == "executed"


# ── the sweeper is hygiene, never the authority ──────────────────────────────────

def test_sweeper_moves_lapsed_pending_rows_only():
    fresh = inbox.stage_proposal(_proposal(run_id="r6", call_id="c6"))
    lapsed = inbox.stage_proposal(_proposal(run_id="r7", call_id="c7", expires_at=_ago(hours=1)))

    moved = inbox.expire_stale()

    assert moved >= 1
    assert inbox.get_proposal(lapsed.id).status == "expired"
    assert inbox.get_proposal(fresh.id).status == "pending"


def test_sweeper_is_idempotent():
    inbox.stage_proposal(_proposal(run_id="r8", call_id="c8", expires_at=_ago(hours=1)))
    inbox.expire_stale()
    assert inbox.expire_stale() == 0, "a second sweep must move nothing"


# ── the seam: the queue must not advertise work that cannot be done ──────────────

def test_needs_human_hides_a_lapsed_proposal(client):
    """Drives the REAL /control-room/needs-human route, so it fails if the sweep is
    unwired — not merely if the expiry predicate is wrong.

    The strip is a "needs a human" queue: every row is a claim that someone can still act.
    A lapsed proposal is one the accept path now refuses with 410, so listing it would ask
    a human to do something the platform has already decided against.
    """
    fresh = inbox.stage_proposal(_proposal(run_id="cr1", call_id="cr1"))
    lapsed = inbox.stage_proposal(_proposal(run_id="cr2", call_id="cr2", expires_at=_ago(hours=1)))

    body = client.get("/control-room/needs-human").json()
    ids = {r["id"] for r in body.get("rows", []) if r.get("source") == "kinetic_inbox"}

    assert fresh.id in ids, "a live proposal must still reach the queue"
    assert lapsed.id not in ids, "a lapsed proposal must not be offered as actionable"
    assert inbox.get_proposal(lapsed.id).status == "expired"
