"""Arc OC-6 — the outbox: a declared action's calls to other systems, kept as rows and delivered under a lease.

Before it, a press dispatched every call once, inline: one that got no answer was reported as "may have been
delivered" and left there — nothing tried again, nothing checked, and a person who pressed again could do the thing
twice. Here (behind `actions.outbox`) each call an action makes AFTER its edits is a row. It is sent at once, in the
press, and whatever it did not finish a worker finishes: it claims a row by compare-and-set with a lease (one
statement, on SQLite as on Postgres, so two workers never hold one row), and what it does next depends on why the
last attempt failed —

* **not delivered** (the connection was refused, the far end answered 5xx or 429): sent again later, with a growing
  pause, up to `MAX_ATTEMPTS`;
* **unknown** (it went out and no answer came back, or a worker stopped mid-send): never sent blind. The action's own
  verification read runs first — the change is visible, so it is DELIVERED and nothing is sent again; it is not, so it
  is sent again; the read cannot say, so a person decides;
* **refused** (the far end answered 4xx, or a setting refuses it): never sent again by itself.

A call that cannot be delivered waits for a person — Actions ▸ Sends lists it with Retry and Dismiss. When every call
of an execution has landed, the action's verification runs and is booked on the execution's ledger entry, which said
"pending" until then — a call still in the outbox never demotes an action it has not yet been checked against.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from aughor.db.backend import connect_store
from aughor.db.sqlite_util import resolve_db_path
from aughor.db.store_pool import ensure_once

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_DB_PATH = resolve_db_path("AUGHOR_ACTION_OUTBOX_DB",
                           Path(__file__).parent.parent.parent / "data" / "action_outbox.db")

#: The most times one call is sent before it waits for a person.
MAX_ATTEMPTS = 5
#: How long a worker holds a row it claimed; one that stops holding it mid-send leaves the call's fate unknown.
LEASE_S = 90
#: The pause before each next attempt of a call that was not delivered, by how many attempts were made.
BACKOFF_S = (30, 120, 600, 1800)
#: The pause before an unknown call is checked.
CHECK_AFTER_S = 20

STATUSES = ("queued", "sending", "delivered", "unknown", "dead", "dismissed")


class Send(BaseModel):
    """One call a declared action makes, as the outbox keeps it."""
    id: str
    org_id: str = ""
    connection_id: str
    schema_name: str = ""
    action_id: str
    #: The declaration that ran (a retry sends exactly what was pressed, never a later edit of it).
    action: dict = Field(default_factory=dict)
    effect_index: int = 0
    params: dict = Field(default_factory=dict)
    status: str = "queued"
    attempts: int = 0
    next_at: str = ""
    lease_until: str = ""
    leased_by: str = ""
    #: Why the last attempt did not land: not_delivered · unknown · refused · rate_limited · server_error.
    cause: str = ""
    last_error: str = ""
    outcome: dict = Field(default_factory=dict)
    #: How an unknown call was settled — by its check, or by a person.
    reconciled: str = ""
    #: The execution's Action ledger entry.
    entry: str = ""
    created_at: str = ""
    updated_at: str = ""
    resolved_by: str = ""
    note: str = ""

    def declared(self):
        """The declared action this call was made by, as it was when it was pressed."""
        from aughor.ontology.models import KineticAction
        return KineticAction.model_validate(self.action)

    def effect(self) -> dict:
        effects = list((self.action or {}).get("side_effects") or [])
        return effects[self.effect_index] if 0 <= self.effect_index < len(effects) else {}


def enabled() -> bool:
    from aughor.kernel.flags import flag_enabled
    return flag_enabled("actions.outbox")


def _now(at: Optional[datetime] = None) -> str:
    return (at or datetime.now(timezone.utc)).isoformat(timespec="seconds")


def _later(seconds: float, at: Optional[datetime] = None) -> str:
    return _now((at or datetime.now(timezone.utc)) + timedelta(seconds=seconds))


def _conn() -> sqlite3.Connection:
    c = connect_store(_DB_PATH)
    c.row_factory = sqlite3.Row
    ensure_once(c, _ensure_schema)
    return c


def _ensure_schema(c: sqlite3.Connection) -> None:
    c.execute("""
        CREATE TABLE IF NOT EXISTS action_outbox (
            id             TEXT PRIMARY KEY,
            org_id         TEXT NOT NULL DEFAULT '',
            connection_id  TEXT NOT NULL,
            schema_name    TEXT NOT NULL DEFAULT '',
            action_id      TEXT NOT NULL,
            action         TEXT NOT NULL DEFAULT '{}',
            effect_index   INTEGER NOT NULL DEFAULT 0,
            params         TEXT NOT NULL DEFAULT '{}',
            status         TEXT NOT NULL DEFAULT 'queued',
            attempts       INTEGER NOT NULL DEFAULT 0,
            next_at        TEXT NOT NULL DEFAULT '',
            lease_until    TEXT NOT NULL DEFAULT '',
            leased_by      TEXT NOT NULL DEFAULT '',
            cause          TEXT NOT NULL DEFAULT '',
            last_error     TEXT NOT NULL DEFAULT '',
            outcome        TEXT NOT NULL DEFAULT '{}',
            reconciled     TEXT NOT NULL DEFAULT '',
            entry          TEXT NOT NULL DEFAULT '',
            created_at     TEXT NOT NULL,
            updated_at     TEXT NOT NULL,
            resolved_by    TEXT NOT NULL DEFAULT '',
            note           TEXT NOT NULL DEFAULT ''
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS ix_outbox_due ON action_outbox (status, next_at)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_outbox_conn ON action_outbox (org_id, connection_id)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_outbox_entry ON action_outbox (entry)")
    c.commit()


def _row(r: sqlite3.Row) -> Send:
    d = dict(r)
    for k in ("action", "params", "outcome"):
        d[k] = json.loads(d.get(k) or "{}")
    return Send(**d)


def _update(c: sqlite3.Connection, send_id: str, **fields: Any) -> None:
    fields["updated_at"] = _now()
    for k in ("action", "params", "outcome"):
        if k in fields:
            fields[k] = json.dumps(fields[k], default=str)
    cols = ", ".join(f"{k} = ?" for k in fields)
    c.execute(f"UPDATE action_outbox SET {cols} WHERE id = ?", (*fields.values(), send_id))


# ── writing ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def enqueue(action: Any, effect_index: int, params: dict, connection_id: str, schema_name: str = "") -> Send:
    """Keep one call of ``action`` (its side effect at ``effect_index``) to be delivered now."""
    from aughor.org.context import current_org_id
    now = _now()
    send = Send(id=uuid.uuid4().hex, org_id=current_org_id() or "", connection_id=connection_id,
                schema_name=schema_name or "", action_id=action.id, action=action.model_dump(mode="json"),
                effect_index=effect_index, params={k: (v if isinstance(v, (str, int, float, bool)) or v is None else str(v))
                                                   for k, v in (params or {}).items()},
                next_at=now, created_at=now, updated_at=now)
    with _LOCK:
        c = _conn()
        try:
            c.execute("""
                INSERT INTO action_outbox (id, org_id, connection_id, schema_name, action_id, action, effect_index,
                                           params, status, attempts, next_at, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (send.id, send.org_id, send.connection_id, send.schema_name, send.action_id,
                  json.dumps(send.action, default=str), send.effect_index, json.dumps(send.params, default=str),
                  "queued", 0, send.next_at, send.created_at, send.updated_at))
            c.commit()
        finally:
            c.close()
    return send


def link_entry(send_ids: list[str], entry: str) -> None:
    """Name the execution's ledger entry on its calls — what their verification is booked on once they land."""
    if not send_ids or not entry:
        return
    with _LOCK:
        c = _conn()
        try:
            for sid in send_ids:
                _update(c, sid, entry=entry)
            c.commit()
        finally:
            c.close()


def get(send_id: str) -> Optional[Send]:
    with _LOCK:
        c = _conn()
        try:
            r = c.execute("SELECT * FROM action_outbox WHERE id = ?", (send_id,)).fetchone()
            return _row(r) if r else None
        finally:
            c.close()


def list_sends(connection_id: str = "", statuses: Optional[list[str]] = None, *, entry: str = "",
               limit: int = 200) -> list[Send]:
    sql, args = "SELECT * FROM action_outbox WHERE 1 = 1", []
    if connection_id:
        sql += " AND connection_id = ?"
        args.append(connection_id)
    if entry:
        sql += " AND entry = ?"
        args.append(entry)
    if statuses:
        sql += f" AND status IN ({','.join('?' * len(statuses))})"
        args += list(statuses)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    args.append(int(limit))
    with _LOCK:
        c = _conn()
        try:
            return [_row(r) for r in c.execute(sql, args).fetchall()]
        finally:
            c.close()


# ── the claim ───────────────────────────────────────────────────────────────────────────────────────────────────────

def _claim(send_id: str, worker: str, now: Optional[datetime] = None) -> Optional[tuple[Send, str]]:
    """Take ``send_id`` for ``worker`` — ``(send, the status it was claimed from)`` — or None when another worker holds
    it or it is not due. ONE compare-and-set statement: whichever worker's update matches first holds it."""
    at = now or datetime.now(timezone.utc)
    stamp = _now(at)
    with _LOCK:
        c = _conn()
        try:
            r = c.execute("SELECT status FROM action_outbox WHERE id = ?", (send_id,)).fetchone()
            if r is None:
                return None
            was = str(r["status"])
            n = c.execute("""
                UPDATE action_outbox SET status = 'sending', leased_by = ?, lease_until = ?, attempts = attempts + ?,
                                         updated_at = ?
                WHERE id = ? AND status = ? AND status IN ('queued', 'unknown') AND next_at <= ?
            """, (worker, _later(LEASE_S, at), 1 if was == "queued" else 0, stamp, send_id, was, stamp)).rowcount
            c.commit()
            if n != 1:
                return None
            return _row(c.execute("SELECT * FROM action_outbox WHERE id = ?", (send_id,)).fetchone()), was
        finally:
            c.close()


def _sweep_stopped(now: Optional[datetime] = None) -> int:
    """A row whose worker's lease ran out while it was sending: the call may have gone out. It is unknown — checked
    before anything is sent again, never resent blind."""
    stamp = _now(now)
    with _LOCK:
        c = _conn()
        try:
            n = c.execute("""
                UPDATE action_outbox SET status = 'unknown', cause = 'unknown', lease_until = '', leased_by = '',
                    last_error = 'the worker sending it stopped before an answer was recorded — it may have gone out',
                    updated_at = ?
                WHERE status = 'sending' AND lease_until != '' AND lease_until < ?
            """, (stamp, stamp)).rowcount
            c.commit()
            return n
        finally:
            c.close()


# ── delivery ────────────────────────────────────────────────────────────────────────────────────────────────────────

def _settle(send: Send, status: str, **fields: Any) -> Send:
    with _LOCK:
        c = _conn()
        try:
            _update(c, send.id, status=status, lease_until="", leased_by="", **fields)
            c.commit()
            return _row(c.execute("SELECT * FROM action_outbox WHERE id = ?", (send.id,)).fetchone())
        finally:
            c.close()


def _again(send: Send, cause: str, error: str, *, at_least: float = 0) -> Send:
    """Send it again later — or, out of attempts, leave it for a person."""
    if send.attempts >= MAX_ATTEMPTS:
        return _settle(send, "dead", cause=cause, last_error=f"{error} — not delivered after {send.attempts} attempts")
    pause = max(BACKOFF_S[min(send.attempts, len(BACKOFF_S)) - 1] if send.attempts else BACKOFF_S[0], at_least)
    return _settle(send, "queued", cause=cause, last_error=error, next_at=_later(pause))


def _check(send: Send) -> str:
    """The action's own verification read, for a call whose fate is unknown: passed · failed · cannot_say."""
    from aughor.actions.authority import verify
    try:
        verdict = verify(send.declared(), dict(send.params), send.connection_id)
    except Exception as exc:  # noqa: BLE001 — a check that cannot run cannot say
        logger.debug("outbox check failed for %s: %s", send.id, exc)
        return "cannot_say"
    status = str(verdict.get("status") or "")
    return status if status in ("passed", "failed") else "cannot_say"


def deliver(send: Send, was: str) -> Send:
    """Deliver one claimed call — first checking, when its fate was unknown, whether it already landed."""
    from aughor.actions.executor import KineticDispatchError, dispatch_effect
    from aughor.ontology.models import SideEffect
    if was == "unknown":
        found = _check(send)
        if found == "passed":
            send = _settle(send, "delivered", reconciled="its check found the change — it had landed; nothing was "
                                                         "sent again")
            _finish(send)
            return send
        if found == "cannot_say":
            return _settle(send, "dead", cause="unknown",
                           last_error="no answer came back, and the action's check cannot say whether it landed — a "
                                      "person decides: Retry sends it again, Dismiss leaves it")
        send = send.model_copy(update={"attempts": send.attempts + 1})        # not visible: sent again, counted
        with _LOCK:
            c = _conn()
            try:
                _update(c, send.id, attempts=send.attempts, reconciled="its check did not find the change — sent again")
                c.commit()
            finally:
                c.close()
    action = send.declared()
    try:
        result = dispatch_effect(SideEffect.model_validate(send.effect()), action, dict(send.params), send.connection_id)
    except KineticDispatchError as exc:
        cause = getattr(exc, "cause", "") or "refused"
        if cause == "not_delivered":
            return _again(send, cause, str(exc)[:500])
        if cause == "unknown":
            return _settle(send, "unknown", cause="unknown", last_error=str(exc)[:500], next_at=_later(CHECK_AFTER_S))
        return _settle(send, "dead", cause="refused", last_error=str(exc)[:500])
    code = result.get("http_status") if isinstance(result, dict) else None
    if isinstance(code, int) and not result.get("ok", True):
        if code == 429:
            return _again(send, "rate_limited", "the far end asked to slow down (HTTP 429)", at_least=60)
        if code >= 500:
            return _again(send, "server_error", f"the far end failed (HTTP {code})")
        return _settle(send, "dead", cause="refused", outcome=result,
                       last_error=f"the far end refused it (HTTP {code}) — sending it again changes nothing")
    send = _settle(send, "delivered", cause="", last_error="", outcome=result if isinstance(result, dict) else {})
    _finish(send)
    return send


def finish_entry(entry: str) -> None:
    """Book an execution's verification once every one of its calls has landed (a no-op until then)."""
    sends = list_sends(entry=entry) if entry else []
    if sends:
        _finish(sends[0])


def _finish(send: Send) -> None:
    """When every call of an execution has landed, its verification runs and is booked on its ledger entry."""
    if not send.entry:
        return
    pending = [s for s in list_sends(entry=send.entry) if s.status != "delivered"]
    if pending:
        return
    try:
        from aughor.actions.authority import restate_verification, verify
        delivered = list_sends(entry=send.entry)
        outcome = {"side_effects": [s.outcome for s in sorted(delivered, key=lambda s: s.effect_index)]}
        verdict = verify(send.declared(), dict(send.params), send.connection_id, outcome=outcome)
        restate_verification(send.entry, verdict, scope=send.connection_id)
    except Exception as exc:  # noqa: BLE001 — the calls landed; the booking is best-effort, and counted
        from aughor.kernel.errors import tolerate
        tolerate(exc, "an execution's calls landed; its verification could not be booked", counter="outbox.finish",
                 conn_id=send.connection_id or None)


def send_now(send_id: str, worker: str = "inline") -> Optional[Send]:
    """Claim and deliver one call now — the press's own first attempt."""
    claimed = _claim(send_id, worker)
    return deliver(*claimed) if claimed is not None else get(send_id)


def work_once(worker: str, *, limit: int = 20, now: Optional[datetime] = None) -> list[Send]:
    """One pass of the worker: what stopped mid-send is made unknown, then each due call is claimed and delivered."""
    _sweep_stopped(now)
    stamp = _now(now)
    with _LOCK:
        c = _conn()
        try:
            due = [r["id"] for r in c.execute("""
                SELECT id FROM action_outbox WHERE status IN ('queued', 'unknown') AND next_at <= ?
                ORDER BY next_at LIMIT ?
            """, (stamp, int(limit))).fetchall()]
        finally:
            c.close()
    out = []
    for send_id in due:
        claimed = _claim(send_id, worker, now)
        if claimed is not None:
            try:
                out.append(deliver(*claimed))
            except Exception as exc:  # noqa: BLE001 — one call's crash must not stop the pass; it is unknown now
                logger.warning("outbox delivery crashed for %s: %s", send_id, exc)
                out.append(_settle(claimed[0], "unknown", cause="unknown", next_at=_later(CHECK_AFTER_S),
                                   last_error=f"the delivery crashed: {type(exc).__name__}: {str(exc)[:200]}"))
    return out


# ── a person's hand ─────────────────────────────────────────────────────────────────────────────────────────────────

def retry(send_id: str, *, by: str) -> Optional[Send]:
    """A person sends a call that waits for them again, now — a call whose fate was unknown is sent without a check:
    the person decided."""
    send = get(send_id)
    if send is None or send.status not in ("dead", "unknown"):
        return send
    with _LOCK:
        c = _conn()
        try:
            _update(c, send_id, status="queued", next_at=_now(), resolved_by=by,
                    reconciled=(f"sent again by {by}" if send.status == "dead" else f"sent again by {by}, unchecked"))
            c.commit()
        finally:
            c.close()
    return send_now(send_id, worker=f"person:{by}")


def dismiss(send_id: str, *, by: str, note: str = "") -> Optional[Send]:
    """A person leaves a call that waits for them undelivered, with why — it is never sent."""
    send = get(send_id)
    if send is None or send.status not in ("dead", "unknown"):
        return send
    return _settle(send, "dismissed", resolved_by=by, note=(note or "")[:500],
                   reconciled=f"left undelivered by {by}")


def purge_connections(connection_ids: list[str]) -> int:
    """Catalog-delete cascade."""
    if not connection_ids:
        return 0
    with _LOCK:
        c = _conn()
        try:
            n = c.execute(f"DELETE FROM action_outbox WHERE connection_id IN ({','.join('?' * len(connection_ids))})",
                          list(connection_ids)).rowcount
            c.commit()
            return n
        finally:
            c.close()
