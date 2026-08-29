"""Wave A4 — the resolve-once proposal inbox (program doc J1).

Wave K4 produces proposals as a live-only dataclass (``kinetic/propose.py``): the model proposes a
declared action, the proposal is dry-run validated, and then it dies with the HTTP response — a human
never gets to accept it later, and a restart forgets it entirely. This module makes a proposal a
**durable, resolve-once** record:

* **Resolve exactly once.** Accept/reject is a single conditional ``UPDATE … WHERE status='pending'``.
  The first responder wins; a second accept sees ``status != 'pending'``, updates zero rows, and is a
  no-op — never a second dispatch. This is the property that makes the inbox safe to expose across
  surfaces (an HTTP accept and a Slack accept racing, a double-click, a ret/replay) without a lock.
* **Idempotent by ``(org, run_id, call_id)``.** Staging the same proposal twice — the same run
  replayed after a restart — returns the existing row instead of a duplicate. This is what lets a
  durable resume rebuild suspensions from a transcript and find already-staged items.
* **Accept IS the approval.** A human looking at a proposal and clicking accept is performing the
  graduated-approval act, so :func:`accept_proposal` runs the executor with ``approved=True`` — which
  bypasses the *approval gate only*. Submission criteria still run (they are step 2 of the executor,
  before approval at step 3), so an accept can never push a value the criteria reject. Unattended
  auto-allow is the standing-grant's job (``kinetic/grants.py``), not the inbox's.

* **Pending is bounded (RC-3).** A proposal freezes its *params* at stage time; it cannot freeze the
  world those params were reasoned about. An unbounded pending row is therefore an irreversible
  governed write waiting to fire on a justification that has since gone stale — the live inbox held
  one for three days before a human resolved it. Every proposal now carries an ``expires_at``, and
  an expired one can never be accepted: the check runs INSIDE the accept path, not only in a
  sweeper, because a sweeper alone leaves a window in which an expired proposal is still
  acceptable. Expiry withholds a side effect, so it fails CLOSED — an unreadable timestamp reads as
  expired, never as fresh.

Both outcomes are recorded with the actor, so a **rejected** proposal is auditable evidence, not a
gap. The store follows the overlay-ledger idiom exactly (SQLite via ``resolve_db_path`` so the suite
never touches live ``data/``; org+connection scoped; forward-only migrations).
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from aughor.db.migrations import Migration, add_column_if_missing, run_migrations
from aughor.db.sqlite_util import resolve_db_path
from aughor.db.backend import connect_store
from aughor.db.store_pool import ensure_once
from aughor.org.context import current_org_id
from aughor.util.time import age_hours, now_iso_z

_LOCK = threading.Lock()
_DB_PATH = resolve_db_path(
    "AUGHOR_KINETIC_INBOX_DB",
    Path(__file__).parent.parent.parent / "data" / "kinetic_inbox.db",
)

#: Forward-only. v2 adds `expires_at`; `add_column_if_missing` makes it a no-op on a fresh DB
#: (which already gets the column from the CREATE TABLE below) and an ALTER on a live one.
#: Numbered against the LIVE store's `PRAGMA user_version` (1 at time of writing), not the
#: source comment — a migration numbered at or below the deployed version never runs, and no
#: hermetic test can catch that.
_MIGRATIONS: list = [
    Migration(2, "proposal expiry",
              lambda c: add_column_if_missing(c, "staged_proposals", "expires_at", "TEXT")),
]

#: Terminal statuses — a proposal in any of these is resolved and cannot be re-resolved.
#: ``expired`` joins them: a lapsed proposal is resolved BY TIME, and re-opening it would
#: hand back the acceptance window the expiry exists to close.
_TERMINAL = {"accepted", "rejected", "executed", "failed", "approval_required", "expired"}

#: How long a staged proposal stays acceptable, in hours. Read per call, never frozen at
#: import, so a test (or an operator) can shorten it without reloading the module.
#:
#: The default is 7 days. It is not arbitrary: the only proposal the live inbox has ever held
#: sat pending for THREE days before a human resolved it, so anything near 24h would expire
#: real work before its approver reached it. Seven days bounds the window while leaving that
#: measured human latency more than double the room it actually used.
_DEFAULT_TTL_HOURS = 168.0


def ttl_hours() -> float:
    """The configured proposal lifetime. A non-numeric or non-positive override is ignored
    rather than obeyed — a TTL of 0 would expire every proposal at the instant it is staged,
    which is indistinguishable from the inbox being broken."""
    raw = os.getenv("AUGHOR_PROPOSAL_TTL_HOURS", "")
    try:
        v = float(raw)
        return v if v > 0 else _DEFAULT_TTL_HOURS
    except (TypeError, ValueError):
        return _DEFAULT_TTL_HOURS


def _new_id() -> str:
    return str(uuid.uuid4())


def _deadline_from(created_at: str) -> str:
    """`created_at` + the configured TTL, in the same `…Z` form every other timestamp uses.

    An unparseable `created_at` yields a deadline of NOW, so the proposal is born expired and
    cannot be accepted. Same direction as every other failure here: withhold the write."""
    try:
        dt = datetime.fromisoformat(created_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        dt = datetime.now(timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")
    return (dt + timedelta(hours=ttl_hours())).isoformat().replace("+00:00", "Z")


class StagedProposal(BaseModel):
    """One durable, resolve-once proposal — a declared action the agent proposed, awaiting a human."""
    id: str = Field(default_factory=_new_id)
    org_id: str = ""
    connection_id: str
    schema_name: str = ""
    action_id: str
    params: dict = Field(default_factory=dict)          # the coerced, criteria-passing params
    reasoning: str = ""
    proposer: str = "agent"                             # model/role that produced it
    source: str = "agent"                               # "agent" | "automation:<id>" | "investigation:<id>"
    # Idempotency key — a stage of the same (run, call) is a no-op returning the existing row, so a
    # replayed run after a restart cannot duplicate a proposal.
    run_id: str = ""
    call_id: str = ""
    status: str = "pending"                             # pending | accepted | rejected | executed | failed | approval_required
    status_message: str = ""                            # authored criterion / approval message, verbatim
    outcome: dict = Field(default_factory=dict)         # the KineticResult outcome, when executed
    created_at: str = Field(default_factory=now_iso_z)
    #: When this proposal stops being acceptable. Stamped at stage time and then FIXED — the
    #: terms a human was offered do not move because an operator later retuned the default.
    #: None only on rows staged before RC-3, which fall back to `created_at` + the current TTL.
    expires_at: Optional[str] = None
    resolved_at: Optional[str] = None
    resolved_by: str = ""

    @property
    def pending(self) -> bool:
        return self.status == "pending"

    @property
    def expired(self) -> bool:
        """True when the acceptance window has closed on a still-pending proposal.

        Reads through :func:`aughor.util.time.age_hours`, which returns a large sentinel for an
        unparseable value — so a corrupt timestamp reads as EXPIRED. That is the safe direction:
        the failure withholds a governed write rather than authorising one.

        Deliberately not a string comparison against "now". `now_iso_z` drops microseconds when
        they are exactly zero, so two of its own outputs are not always the same width, and
        lexical ordering silently inverts across that boundary.
        """
        if self.status != "pending":
            return False   # a resolved proposal is resolved; time no longer decides anything
        if self.expires_at:
            return age_hours(self.expires_at) >= 0.0   # the deadline is in the past
        return age_hours(self.created_at) >= ttl_hours()


# ── schema ─────────────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    c = connect_store(_DB_PATH)
    c.row_factory = sqlite3.Row
    ensure_once(c, _ensure_schema)
    return c


def _ensure_schema(c: sqlite3.Connection) -> None:
    c.execute("""
        CREATE TABLE IF NOT EXISTS staged_proposals (
            id             TEXT PRIMARY KEY,
            org_id         TEXT NOT NULL DEFAULT '',
            connection_id  TEXT NOT NULL,
            schema_name    TEXT NOT NULL DEFAULT '',
            action_id      TEXT NOT NULL,
            params         TEXT NOT NULL DEFAULT '{}',
            reasoning      TEXT NOT NULL DEFAULT '',
            proposer       TEXT NOT NULL DEFAULT 'agent',
            source         TEXT NOT NULL DEFAULT 'agent',
            run_id         TEXT NOT NULL DEFAULT '',
            call_id        TEXT NOT NULL DEFAULT '',
            status         TEXT NOT NULL DEFAULT 'pending',
            status_message TEXT NOT NULL DEFAULT '',
            outcome        TEXT NOT NULL DEFAULT '{}',
            created_at     TEXT NOT NULL,
            expires_at     TEXT,
            resolved_at    TEXT,
            resolved_by    TEXT NOT NULL DEFAULT ''
        )
    """)
    # The idempotency key. A partial-unique index (call_id non-empty) so proposals staged without a
    # key — an ad-hoc single proposal — are never collapsed into one another.
    c.execute("""CREATE UNIQUE INDEX IF NOT EXISTS ux_inbox_idem
                 ON staged_proposals (org_id, run_id, call_id)
                 WHERE call_id != ''""")
    c.execute("CREATE INDEX IF NOT EXISTS ix_inbox_conn ON staged_proposals (org_id, connection_id)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_inbox_status ON staged_proposals (connection_id, status)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_inbox_source ON staged_proposals (source)")
    run_migrations(c, _MIGRATIONS, store="kinetic_inbox")
    c.commit()


def _row(r: sqlite3.Row) -> StagedProposal:
    d = dict(r)
    d["params"] = json.loads(d["params"] or "{}")
    d["outcome"] = json.loads(d["outcome"] or "{}")
    return StagedProposal(**d)


# ── stage (idempotent) ───────────────────────────────────────────────────────────

def stage_proposal(p: StagedProposal) -> StagedProposal:
    """Persist a proposal. Idempotent by ``(org, run_id, call_id)`` when a call_id is set: staging
    the same (run, call) again returns the ALREADY-stored row unchanged — so a replayed run never
    duplicates, and never resurrects a proposal a human already resolved."""
    if not p.org_id:
        p.org_id = current_org_id()
    if not p.expires_at:
        p.expires_at = _deadline_from(p.created_at)
    with _LOCK:
        c = _conn()
        try:
            if p.call_id:
                existing = c.execute(
                    "SELECT * FROM staged_proposals WHERE org_id=? AND run_id=? AND call_id=?",
                    (p.org_id, p.run_id, p.call_id)).fetchone()
                if existing:
                    return _row(existing)
            c.execute("""
                INSERT INTO staged_proposals (
                    id, org_id, connection_id, schema_name, action_id, params, reasoning,
                    proposer, source, run_id, call_id, status, status_message, outcome, created_at,
                    expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (p.id, p.org_id, p.connection_id, p.schema_name, p.action_id,
                  json.dumps(p.params), p.reasoning, p.proposer, p.source, p.run_id, p.call_id,
                  p.status, p.status_message, json.dumps(p.outcome), p.created_at,
                  p.expires_at))
            c.commit()
            return p
        finally:
            c.close()


# ── resolve-once primitive ───────────────────────────────────────────────────────

def _resolve_once(proposal_id: str, to_status: str, actor: str) -> bool:
    """Flip a PENDING proposal to ``to_status``. Returns True iff THIS call was the one that
    resolved it (rowcount == 1). A second call finds ``status != 'pending'`` and updates zero rows,
    so exactly one caller ever proceeds to a side effect — the first-responder-wins guarantee."""
    with _LOCK:
        c = _conn()
        try:
            cur = c.execute(
                "UPDATE staged_proposals SET status=?, resolved_by=?, resolved_at=? "
                "WHERE id=? AND status='pending'",
                (to_status, actor, now_iso_z(), proposal_id))
            c.commit()
            return cur.rowcount == 1
        finally:
            c.close()


def _record_outcome(proposal_id: str, status: str, message: str, outcome: dict) -> None:
    """Write the terminal execution result onto an already-accepted proposal."""
    with _LOCK:
        c = _conn()
        try:
            c.execute(
                "UPDATE staged_proposals SET status=?, status_message=?, outcome=? WHERE id=?",
                (status, message, json.dumps(outcome or {}), proposal_id))
            c.commit()
        finally:
            c.close()


# ── queries ──────────────────────────────────────────────────────────────────────

def get_proposal(proposal_id: str) -> Optional[StagedProposal]:
    with _LOCK:
        c = _conn()
        try:
            r = c.execute("SELECT * FROM staged_proposals WHERE id=?", (proposal_id,)).fetchone()
            return _row(r) if r else None
        finally:
            c.close()


def list_proposals(connection_id: Optional[str] = None, status: Optional[str] = None,
                   limit: int = 100) -> list[StagedProposal]:
    org = current_org_id()
    clauses, params = ["org_id=?"], [org]
    if connection_id:
        clauses.append("connection_id=?"); params.append(connection_id)
    if status:
        clauses.append("status=?"); params.append(status)
    with _LOCK:
        c = _conn()
        try:
            rows = c.execute(
                f"SELECT * FROM staged_proposals WHERE {' AND '.join(clauses)} "
                f"ORDER BY created_at DESC LIMIT ?", [*params, limit]).fetchall()
            return [_row(r) for r in rows]
        finally:
            c.close()


def expire_stale(connection_id: Optional[str] = None) -> int:
    """Flip every lapsed pending proposal to ``expired``. Returns how many moved.

    Hygiene, not enforcement: :func:`accept_proposal` refuses a lapsed proposal whether or not
    this has run, so a missed sweep can never let one through. This exists so a listing shows
    `expired` instead of a `pending` row nothing will ever accept — a queue that displays work
    which cannot be done reads as a broken queue.

    Filtering happens in Python, not SQL: the deadline comparison has to go through the same
    `expired` predicate the accept path uses, or the two could disagree about which rows are
    past their window — and a guard that disagrees with the thing it guards is not a guard.
    """
    moved = 0
    for prop in list_proposals(connection_id=connection_id, status="pending", limit=1000):
        if prop.expired and _resolve_once(prop.id, "expired", "system:expiry"):
            moved += 1
    return moved


# ── accept / reject (the resolve-once public API) ─────────────────────────────────

def reject_proposal(proposal_id: str, *, actor: str) -> bool:
    """Reject a pending proposal — resolved with the actor, NO side effect. Returns False if it was
    already resolved (a no-op, not an error), so a double-reject is harmless."""
    resolved = _resolve_once(proposal_id, "rejected", actor)
    if resolved:
        from aughor.govern import actions as govern
        p = get_proposal(proposal_id)
        if p:
            govern.audit(f"kinetic.{p.action_id}", p.connection_id, "proposal_rejected",
                         actor=actor, detail=f"proposal {proposal_id}")
    return resolved


def accept_proposal(proposal_id: str, *, actor: str, mint_grant: bool = False):
    """Accept a pending proposal and execute it — EXACTLY once.

    The accept is the human's approval act, so the executor runs with ``approved=True`` (bypassing
    the approval gate, never the criteria). A second accept resolves zero rows and returns a
    ``KineticResult('already_resolved', ...)`` — never a second dispatch. When ``mint_grant`` and the
    action is single-target eligible, a target-bound standing grant is minted so future UNATTENDED
    executions of this exact target auto-allow (``kinetic/grants.py``).

    Returns ``(KineticResult, grant_id_or_empty)``.
    """
    from aughor.actions.executor import KineticResult, execute_kinetic_action

    p = get_proposal(proposal_id)
    if p is None:
        return KineticResult("not_found", False, message="no such proposal"), ""
    # RC-3 — the acceptance window, enforced HERE rather than only in a sweeper. A sweeper runs
    # on a timer, so between lapse and sweep there is a window in which an expired proposal is
    # still acceptable; this check has no such window. Resolving it to `expired` in the same
    # first-responder-wins UPDATE keeps the invariant intact: exactly one caller ever moves a
    # pending row, whether the mover is a human or the clock.
    if p.expired:
        if _resolve_once(proposal_id, "expired", actor or "system:expiry"):
            from aughor.govern import actions as govern
            govern.audit(f"kinetic.{p.action_id}", p.connection_id, "proposal_expired",
                         actor=actor or "system:expiry",
                         detail=f"proposal {proposal_id} lapsed at {p.expires_at or '(legacy row)'}")
        return KineticResult("expired", False, p.action_id,
                             message=("This proposal's approval window closed — it was staged "
                                      "against data that has since moved. Re-propose to act on it."),
                             detail={"expires_at": p.expires_at or "", "created_at": p.created_at}), ""
    if not _resolve_once(proposal_id, "accepted", actor):
        return KineticResult("already_resolved", False, p.action_id,
                             message=f"proposal already {get_proposal(proposal_id).status}"), ""

    action = _load_action(p.connection_id, p.schema_name, p.action_id)
    if action is None:
        _record_outcome(proposal_id, "failed", "declared action not found", {})
        return KineticResult("dispatch_error", False, p.action_id,
                             message="declared action no longer exists"), ""

    result = execute_kinetic_action(action, p.params, actor=actor, scope=p.connection_id,
                                    approved=True)
    _record_outcome(proposal_id, result.status if result.ok else result.status,
                    result.message, result.outcome)

    grant_id = ""
    if mint_grant and result.ok:
        from aughor.actions import grants
        from aughor.actions.executor import coerce_params
        # Mint from the COERCED params, not the raw proposal params: the executor's grant match
        # (grants.matching_grant) compares against coerced values, so a NUMERIC 500 must be bound as
        # "500.0" (coerced), never "500" (raw) — else the grant it just minted would never match.
        # coerce cannot raise here (it already succeeded inside a result.ok execution).
        coerced = coerce_params(action, p.params)
        owner_kind, owner_id = _owner_of(p.source)
        grant = grants.mint_from_action(action, coerced, connection_id=p.connection_id,
                                        owner_kind=owner_kind, owner_id=owner_id, created_by=actor)
        grant_id = grant.id if grant else ""
    return result, grant_id


def _owner_of(source: str) -> tuple[str, str]:
    """Map a proposal's ``source`` label to a grant owner. ``automation:<id>`` → the automation
    owns the grant (revoked with it); anything else is a manual grant owned by no lifecycle."""
    if source.startswith("automation:"):
        return "automation", source.split(":", 1)[1]
    return "manual", ""


def _load_action(connection_id: str, schema_name: str, action_id: str):
    from aughor.ontology.store import load_latest_ontology
    graph = load_latest_ontology(connection_id, schema_name or None)
    if graph is None and schema_name:
        graph = load_latest_ontology(connection_id, None)
    actions = getattr(graph, "kinetic_actions", None) or {}
    return actions.get(action_id)


# ── purge (catalog-delete + owner cascades) ───────────────────────────────────────

def purge_connection(connection_id: str) -> int:
    """Delete every staged proposal for a connection (catalog-delete cascade)."""
    with _LOCK:
        c = _conn()
        try:
            n = c.execute("DELETE FROM staged_proposals WHERE connection_id=?",
                          (connection_id,)).rowcount
            c.commit()
            return n
        finally:
            c.close()


def purge_source(source: str) -> int:
    """Delete proposals staged by a given source (e.g. a deleted automation's ``automation:<id>``)."""
    with _LOCK:
        c = _conn()
        try:
            n = c.execute("DELETE FROM staged_proposals WHERE source=?", (source,)).rowcount
            c.commit()
            return n
        finally:
            c.close()
