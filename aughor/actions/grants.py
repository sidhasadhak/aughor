"""Wave A4 — target-bound standing grants (program doc J2).

The graduated-approval gate blocks a HIGH-risk declared action until a human approves it. That is
right for a human-in-the-loop accept, but an *unattended* automation firing a governed write has no
human to click approve — and blanket "always allow ``refund_orders``" throws away the whole point of
the gate. A **standing grant** is the safe middle: a human pre-authorizes ONE action bound to ONE
exact target value.

The invariants, each load-bearing:

* **Target-bound, never blanket.** A grant is ``(action_id, target_arg, target_value)`` compared by
  **exact string equality** — "allow ``refund_orders`` → ``order_id=8821``", not "allow
  ``refund_orders``". A different value still hits the approval gate.
* **Eligible only for a single-target action.** If the action declares zero or 2+ parameters there is
  no unambiguous "the target", so no grant can be minted (:func:`mint_from_action` returns ``None``).
  This mirrors openworker's "a declared target argument," and it is a *deterministic* eligibility
  check, not a judgment call.
* **Bypasses APPROVAL only, never CRITERIA.** The executor runs submission criteria at step 2 and the
  approval gate at step 3; a grant is consulted at step 3, so ``amount <= 10000`` is still enforced
  even for a granted target. A grant can pre-approve *who may run*, never *what values pass*.
* **Owned by its minter; cited on every use.** A grant minted while accepting an automation's
  proposal is owned by that automation and dies with it (per-owner revocation). Every auto-allowed
  invocation records the grant id in the audit ledger and on the ``KineticResult`` — an unattended
  write is never anonymous.

Store idiom is the overlay ledger's (SQLite via ``resolve_db_path``; org+connection scoped;
forward-only migrations).
"""
from __future__ import annotations

import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from aughor.db.migrations import run_migrations
from aughor.db.sqlite_util import resolve_db_path
from aughor.db.backend import connect_store
from aughor.db.store_pool import ensure_once
from aughor.org.context import current_org_id
from aughor.util.time import now_iso_z

_LOCK = threading.Lock()
_DB_PATH = resolve_db_path(
    "AUGHOR_KINETIC_GRANTS_DB",
    Path(__file__).parent.parent.parent / "data" / "kinetic_grants.db",
)

def _m2_phase4(c: sqlite3.Connection) -> None:
    """Phase 4 of the 2027 study — a grant is bound to a target, a scope, limits and an expiry, and a
    grant the ladder widened cites its graduation receipt. Additive."""
    from aughor.db.migrations import add_column_if_missing
    add_column_if_missing(c, "standing_grants", "graduation_receipt", "TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(c, "standing_grants", "expires_at", "TEXT")
    add_column_if_missing(c, "standing_grants", "max_uses", "INTEGER NOT NULL DEFAULT 0")


from aughor.db.migrations import Migration as _Migration  # noqa: E402

_MIGRATIONS: list = [_Migration(2, "phase 4: graduation receipt, expiry and use cap on a grant", _m2_phase4)]


def _new_id() -> str:
    return str(uuid.uuid4())


class StandingGrant(BaseModel):
    """A human pre-authorization of one action bound to one exact target value."""
    id: str = Field(default_factory=_new_id)
    org_id: str = ""
    connection_id: str
    action_id: str
    target_arg: str                                 # the single declared parameter name
    target_value: str                               # the exact value the grant is bound to (string)
    owner_kind: str = "manual"                      # "manual" | "automation" | "subscription"
    owner_id: str = ""                              # the owning lifecycle's id ('' for manual)
    created_by: str = ""
    created_at: str = Field(default_factory=now_iso_z)
    last_used_at: Optional[str] = None
    use_count: int = 0
    #: Phase 4 — a grant the ladder widened cites the graduation receipt that licensed it; a grant
    #: bound by policy carries its expiry and a cap on uses (0 = no cap). A person's own accept-time
    #: grant carries none of these, as before.
    graduation_receipt: str = ""
    expires_at: Optional[str] = None
    max_uses: int = 0

    def spent(self, now: Optional[str] = None) -> str:
        """Why this grant no longer allows anything, or "" while it does."""
        now = now or now_iso_z()
        if self.expires_at and str(self.expires_at) <= now:
            return f"expired {str(self.expires_at)[:10]}"
        if self.max_uses and self.use_count >= self.max_uses:
            return f"its {self.max_uses} uses are spent"
        return ""


# ── schema ─────────────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    c = connect_store(_DB_PATH)
    c.row_factory = sqlite3.Row
    ensure_once(c, _ensure_schema)
    return c


def _ensure_schema(c: sqlite3.Connection) -> None:
    c.execute("""
        CREATE TABLE IF NOT EXISTS standing_grants (
            id            TEXT PRIMARY KEY,
            org_id        TEXT NOT NULL DEFAULT '',
            connection_id TEXT NOT NULL,
            action_id     TEXT NOT NULL,
            target_arg    TEXT NOT NULL,
            target_value  TEXT NOT NULL,
            owner_kind    TEXT NOT NULL DEFAULT 'manual',
            owner_id      TEXT NOT NULL DEFAULT '',
            created_by    TEXT NOT NULL DEFAULT '',
            created_at    TEXT NOT NULL,
            last_used_at  TEXT,
            use_count     INTEGER NOT NULL DEFAULT 0
        )
    """)
    # One grant per (org, conn, action, target value) — re-minting the same binding is idempotent.
    c.execute("""CREATE UNIQUE INDEX IF NOT EXISTS ux_grant_target
                 ON standing_grants (org_id, connection_id, action_id, target_arg, target_value)""")
    c.execute("CREATE INDEX IF NOT EXISTS ix_grant_conn ON standing_grants (org_id, connection_id)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_grant_owner ON standing_grants (owner_kind, owner_id)")
    run_migrations(c, _MIGRATIONS, store="kinetic_grants")
    c.commit()


def _row(r: sqlite3.Row) -> StandingGrant:
    return StandingGrant(**dict(r))


# ── eligibility + minting ─────────────────────────────────────────────────────────

def single_target_arg(action) -> Optional[str]:
    """The name of the action's ONE parameter, or ``None`` when it declares zero or 2+ — in which
    case there is no unambiguous target to bind and no grant may be minted. Deterministic."""
    params = list(getattr(action, "params", []) or [])
    return params[0].name if len(params) == 1 else None


def mint_from_action(action, coerced_params: dict, *, connection_id: str,
                     owner_kind: str = "manual", owner_id: str = "",
                     created_by: str = "") -> Optional[StandingGrant]:
    """Mint a target-bound grant from a declared action + the params it was accepted with.

    Returns ``None`` when the action is not single-target eligible (zero or 2+ params) — the caller
    treats that as "this action cannot carry a standing grant," never an error. Idempotent: re-minting
    the same binding returns the existing grant."""
    arg = single_target_arg(action)
    if arg is None or arg not in coerced_params:
        return None
    return mint_grant(StandingGrant(
        connection_id=connection_id, action_id=action.id,
        target_arg=arg, target_value=str(coerced_params[arg]),
        owner_kind=owner_kind, owner_id=owner_id, created_by=created_by))


def mint_grant(grant: StandingGrant) -> StandingGrant:
    """Persist a grant, idempotent by its (org, conn, action, target) binding."""
    if not grant.org_id:
        grant.org_id = current_org_id()
    with _LOCK:
        c = _conn()
        try:
            existing = c.execute(
                "SELECT * FROM standing_grants WHERE org_id=? AND connection_id=? AND action_id=? "
                "AND target_arg=? AND target_value=?",
                (grant.org_id, grant.connection_id, grant.action_id,
                 grant.target_arg, grant.target_value)).fetchone()
            if existing:
                return _row(existing)
            c.execute("""
                INSERT INTO standing_grants (
                    id, org_id, connection_id, action_id, target_arg, target_value,
                    owner_kind, owner_id, created_by, created_at,
                    graduation_receipt, expires_at, max_uses
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (grant.id, grant.org_id, grant.connection_id, grant.action_id,
                  grant.target_arg, grant.target_value, grant.owner_kind, grant.owner_id,
                  grant.created_by, grant.created_at,
                  grant.graduation_receipt or "", grant.expires_at, int(grant.max_uses or 0)))
            c.commit()
            return grant
        finally:
            c.close()


# ── the executor's consultation point ─────────────────────────────────────────────

def matching_grant(action_id: str, coerced_params: dict, *, connection_id: str) -> Optional[StandingGrant]:
    """The grant that pre-authorizes running ``action_id`` with these exact params, or ``None``.

    Exact string equality on the bound target value: a grant for ``order_id=8821`` does not authorize
    ``order_id=8822``. Scoped to the current org + the connection."""
    org = current_org_id()
    with _LOCK:
        c = _conn()
        try:
            rows = c.execute(
                "SELECT * FROM standing_grants WHERE org_id=? AND connection_id=? AND action_id=?",
                (org, connection_id, action_id)).fetchall()
        finally:
            c.close()
    for r in rows:
        g = _row(r)
        if g.target_arg in coerced_params and str(coerced_params[g.target_arg]) == g.target_value:
            if g.spent():                       # phase 4: an expired or exhausted grant allows nothing
                continue
            return g
    return None


def revoke_for_action(action_id: str, connection_id: str) -> int:
    """Phase 4 — a demotion WITHDRAWS every standing grant of (action, scope). Returns how many."""
    org = current_org_id()
    with _LOCK:
        c = _conn()
        try:
            n = c.execute("DELETE FROM standing_grants WHERE org_id=? AND connection_id=? AND action_id=?",
                          (org, connection_id, action_id)).rowcount
            c.commit()
            return int(n or 0)
        finally:
            c.close()


def bump_use(grant_id: str) -> None:
    with _LOCK:
        c = _conn()
        try:
            c.execute(
                "UPDATE standing_grants SET use_count = use_count + 1, last_used_at = ? WHERE id = ?",
                (now_iso_z(), grant_id))
            c.commit()
        finally:
            c.close()


def standing_grant_id(action, coerced_params: dict, connection_id: str) -> str:
    """The executor's one-call hook: the id of a matching grant (and bump its use), or ``''``.

    Returns ``''`` when no grant matches, so the executor is byte-identical for every
    install that has never minted one."""
    g = matching_grant(action.id, coerced_params, connection_id=connection_id)
    if g is None:
        return ""
    bump_use(g.id)
    return g.id


# ── queries + purge ────────────────────────────────────────────────────────────

def list_grants(connection_id: Optional[str] = None) -> list[StandingGrant]:
    org = current_org_id()
    clauses, params = ["org_id=?"], [org]
    if connection_id:
        clauses.append("connection_id=?"); params.append(connection_id)
    with _LOCK:
        c = _conn()
        try:
            rows = c.execute(
                f"SELECT * FROM standing_grants WHERE {' AND '.join(clauses)} "
                f"ORDER BY created_at DESC", params).fetchall()
            return [_row(r) for r in rows]
        finally:
            c.close()


def get_grant(grant_id: str) -> Optional[StandingGrant]:
    with _LOCK:
        c = _conn()
        try:
            r = c.execute("SELECT * FROM standing_grants WHERE id=?", (grant_id,)).fetchone()
            return _row(r) if r else None
        finally:
            c.close()


def revoke_grant(grant_id: str) -> bool:
    with _LOCK:
        c = _conn()
        try:
            n = c.execute("DELETE FROM standing_grants WHERE id=?", (grant_id,)).rowcount
            c.commit()
            return n > 0
        finally:
            c.close()


def purge_owner(owner_kind: str, owner_id: str) -> int:
    """Delete every grant owned by a lifecycle (e.g. a deleted automation) — per-owner revocation."""
    with _LOCK:
        c = _conn()
        try:
            n = c.execute("DELETE FROM standing_grants WHERE owner_kind=? AND owner_id=?",
                          (owner_kind, owner_id)).rowcount
            c.commit()
            return n
        finally:
            c.close()


def purge_connection(connection_id: str) -> int:
    """Delete every grant on a connection (catalog-delete cascade)."""
    with _LOCK:
        c = _conn()
        try:
            n = c.execute("DELETE FROM standing_grants WHERE connection_id=?",
                          (connection_id,)).rowcount
            c.commit()
            return n
        finally:
            c.close()


# ── SP-12b · the outbound-send grant ──────────────────────────────────────────────
#
# A drafted chain's Slack post holds for a person on its first run (SP-7's law, widened
# from warehouse writes to outbound sends). "Always allow" mints ONE of these so later
# runs of THAT chain to THAT channel go unattended — the first-send-only shape the user
# asked for. It reuses this store rather than a new one: an outbound send is a
# target-bound standing permission exactly like a declared write's, and it revokes with
# the automation through the same owner cascade. The synthetic action id namespaces it
# off any real declared action, and the bound target is the channel.

def send_grant_action_id(automation_id: str) -> str:
    return f"slack_post:{automation_id}"


def matching_send_grant(automation_id: str, channel: str, *, connection_id: str):
    """The grant that lets this chain post to this channel unattended, or ``None``."""
    return matching_grant(send_grant_action_id(automation_id),
                          {"channel": str(channel)}, connection_id=connection_id)


def mint_send_grant(automation_id: str, channel: str, *, connection_id: str,
                    created_by: str) -> StandingGrant:
    """Record that this automation may post to this channel unattended from now on —
    owned by the automation, so a delete of the chain revokes it via the owner cascade."""
    return mint_grant(StandingGrant(
        connection_id=connection_id,
        action_id=send_grant_action_id(automation_id),
        target_arg="channel", target_value=str(channel),
        owner_kind="automation", owner_id=automation_id, created_by=created_by))


# HB-3 — the same shape for an Action Hub trigger (the ticket leg: a proposed notify —
# a Jira ticket, a webhook — is approved once, and "always allow" lets the chain fire
# that trigger unattended from then on). Same store, same owner cascade; only the
# namespace prefix and the bound target differ, which is all that was Slack-shaped.

def notify_grant_action_id(automation_id: str) -> str:
    return f"notify:{automation_id}"


def matching_notify_grant(automation_id: str, trigger_id: str, *, connection_id: str):
    """The grant that lets this chain fire this trigger unattended, or ``None``."""
    return matching_grant(notify_grant_action_id(automation_id),
                          {"trigger_id": str(trigger_id)}, connection_id=connection_id)


def mint_notify_grant(automation_id: str, trigger_id: str, *, connection_id: str,
                      created_by: str) -> StandingGrant:
    """This automation may fire this Action Hub trigger unattended from now on."""
    return mint_grant(StandingGrant(
        connection_id=connection_id,
        action_id=notify_grant_action_id(automation_id),
        target_arg="trigger_id", target_value=str(trigger_id),
        owner_kind="automation", owner_id=automation_id, created_by=created_by))
