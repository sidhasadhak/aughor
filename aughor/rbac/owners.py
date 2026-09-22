"""CB-3 (2026-09-22) — owners the platform can reach.

An ``owner`` is free text on a metric, a process, a business rule and (now) a glossary term:
"Ana (logistics)", "Revenue team". Routing understands a PRINCIPAL spelling (``user:ana@corp``,
``group:finance``, ``agent:ua_x``) and leaves display text unrouted — honest, and the reason a
question for Ana had nowhere to go (ideas 17, 20 and 22 all end in "ask the owner").

This module is the link: a person links an owner text to a principal ONCE, here, and from then
on every owner field that reads the same text routes. The standing rule holds — **never by
matching a display name**: nothing here searches users for "Ana"; the principal is what a person
typed or picked. Until a text is linked it is UNRESOLVED, and the surfaces that would have asked
its owner say so instead of asking nobody silently.

Rows live in ``rbac.db`` beside groups (``AUGHOR_RBAC_DB`` keeps them hermetic under test), keyed
by ``(org_id, owner_key)`` where ``owner_key`` is the text casefolded with whitespace collapsed —
"Ana (logistics)" and "ana  (Logistics)" are one owner, "Ana" and "Ana (logistics)" are two.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional

from aughor.db.backend import connect_store
from aughor.db.store_pool import ensure_once
from aughor.metastore.models import principal_kind
from aughor.rbac.store import db_path
from aughor.util.time import now_iso as _now

ROUTABLE_KINDS = ("user", "group", "agent")


@dataclass(frozen=True)
class OwnerLink:
    org_id: str
    owner_key: str
    owner_text: str          # as first linked — the display text people wrote
    principal: str           # user:… / group:… / agent:…
    linked_by: str = ""
    linked_at: str = ""

    def to_dict(self) -> dict:
        return {"owner_text": self.owner_text, "owner_key": self.owner_key, "principal": self.principal,
                "linked_by": self.linked_by, "linked_at": self.linked_at}


def owner_key(owner_text: str) -> str:
    """The key an owner text links under: casefolded, whitespace collapsed. "" for nothing."""
    return " ".join(str(owner_text or "").split()).casefold()


def _conn() -> sqlite3.Connection:
    c = connect_store(db_path())
    c.row_factory = sqlite3.Row
    ensure_once(c, _ensure_schema)
    return c


def _ensure_schema(c: sqlite3.Connection) -> None:
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS owner_links (
            org_id      TEXT NOT NULL,
            owner_key   TEXT NOT NULL,
            owner_text  TEXT NOT NULL,
            principal   TEXT NOT NULL,
            linked_by   TEXT NOT NULL DEFAULT '',
            linked_at   TEXT NOT NULL,
            PRIMARY KEY (org_id, owner_key)
        )
        """
    )
    c.commit()


def _row(r: sqlite3.Row) -> OwnerLink:
    return OwnerLink(org_id=r["org_id"], owner_key=r["owner_key"], owner_text=r["owner_text"],
                     principal=r["principal"], linked_by=r["linked_by"], linked_at=r["linked_at"])


def link_owner(org_id: str, owner_text: str, principal: str, *, linked_by: str = "") -> OwnerLink:
    """Link ``owner_text`` to ``principal`` for this org — a person's act, recorded with who did it.
    Raises ``ValueError`` for an empty text or a principal that is not one the router can reach;
    a text that already reads as a principal needs no link and is refused too (link the display
    text, not the address)."""
    key = owner_key(owner_text)
    if not key:
        raise ValueError("an owner text is required")
    if principal_kind(owner_text.strip()) in ROUTABLE_KINDS:
        raise ValueError("that owner already reads as a principal; nothing to link")
    p = (principal or "").strip()
    if principal_kind(p) not in ROUTABLE_KINDS:
        raise ValueError("the principal must be user:…, group:… or agent:…")
    now = _now()
    c = _conn()
    try:
        c.execute(
            """INSERT INTO owner_links (org_id, owner_key, owner_text, principal, linked_by, linked_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(org_id, owner_key) DO UPDATE SET principal = excluded.principal,
                   linked_by = excluded.linked_by, linked_at = excluded.linked_at""",
            (org_id, key, " ".join(owner_text.split()), p, linked_by, now))
        c.commit()
        return _row(c.execute("SELECT * FROM owner_links WHERE org_id = ? AND owner_key = ?", (org_id, key)).fetchone())
    finally:
        c.close()


def unlink_owner(org_id: str, owner_text: str) -> bool:
    key = owner_key(owner_text)
    if not key:
        return False
    c = _conn()
    try:
        cur = c.execute("DELETE FROM owner_links WHERE org_id = ? AND owner_key = ?", (org_id, key))
        c.commit()
        return cur.rowcount > 0
    finally:
        c.close()


def linked_principal(org_id: str, owner_text: str) -> Optional[str]:
    """The principal a person linked this owner text to, or None. Exact key, never a search."""
    key = owner_key(owner_text)
    if not key:
        return None
    c = _conn()
    try:
        r = c.execute("SELECT principal FROM owner_links WHERE org_id = ? AND owner_key = ?", (org_id, key)).fetchone()
        return str(r["principal"]) if r else None
    finally:
        c.close()


def list_owner_links(org_id: str) -> list[OwnerLink]:
    c = _conn()
    try:
        return [_row(r) for r in c.execute("SELECT * FROM owner_links WHERE org_id = ? ORDER BY owner_key", (org_id,))]
    finally:
        c.close()


# ── the inventory: every owner in use, resolved or not ───────────────────────

def owner_inventory(org_id: str, *, connection_ids: Optional[list[str]] = None) -> list[dict]:
    """Every owner text the organisation's declarations carry, with where it is used and what it
    resolves to. Reads only (a read never builds): the metrics catalog, each connection's served
    ontology (processes and business rules), and the glossary's ``owner`` keys. Sorted so the
    unresolved come first, then by how much depends on them."""
    from aughor.rbac.routing import owner_principal
    uses: dict[str, dict] = {}

    def _use(text: str, kind: str, ref: str, connection_id: str = "") -> None:
        key = owner_key(text)
        if not key:
            return
        entry = uses.setdefault(key, {"owner_text": " ".join(str(text).split()), "uses": []})
        entry["uses"].append({"kind": kind, "id": ref, "connection_id": connection_id})

    try:
        from aughor.semantic.metrics import list_metrics
        for m in list_metrics():
            if getattr(m, "owner", None):
                _use(m.owner, "metric", m.name, getattr(m, "connection_id", "") or "")
    except Exception as exc:  # noqa: BLE001 — one source failing must not hide the others
        from aughor.kernel.errors import tolerate
        tolerate(exc, "owner inventory: the metrics catalog could not be read", counter="owners.inventory")
    conn_ids = connection_ids
    if conn_ids is None:
        try:
            from aughor.db.registry import list_connections
            conn_ids = [str(c.get("id") or "") for c in list_connections() if c.get("id")]
        except Exception as exc:  # noqa: BLE001
            from aughor.kernel.errors import tolerate
            tolerate(exc, "owner inventory: connections could not be listed", counter="owners.inventory")
            conn_ids = []
    for cid in conn_ids:
        try:
            from aughor.agent.framing import served_graph
            g = served_graph(cid, None)
        except Exception as exc:  # noqa: BLE001
            from aughor.kernel.errors import tolerate
            tolerate(exc, f"owner inventory: the ontology of {cid} could not be read", counter="owners.inventory")
            continue
        if g is None:
            continue
        for pid, proc in (getattr(g, "processes", None) or {}).items():
            if getattr(proc, "owner", ""):
                _use(proc.owner, "process", pid, cid)
        for rid, rule in (getattr(g, "rules", None) or {}).items():
            if getattr(rule, "owner", ""):
                _use(rule.owner, "rule", rid, cid)
    try:
        from aughor.semantic.glossary import load_glossary
        gl = load_glossary() or {}
        for table, meta in (gl.get("tables") or {}).items():
            if isinstance(meta, dict):
                if meta.get("owner"):
                    _use(meta["owner"], "glossary_table", str(table))
                for col, cmeta in (meta.get("columns") or {}).items():
                    if isinstance(cmeta, dict) and cmeta.get("owner"):
                        _use(cmeta["owner"], "glossary_column", f"{table}.{col}")
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "owner inventory: the glossary could not be read", counter="owners.inventory")
    links = {l.owner_key: l for l in list_owner_links(org_id)}
    out = []
    for key, entry in uses.items():
        principal = owner_principal(entry["owner_text"], org_id=org_id)
        link = links.get(key)
        out.append({**entry, "owner_key": key, "principal": principal, "resolved": principal is not None,
                    "how": ("principal" if principal and link is None else "linked" if link else "unresolved"),
                    "linked_by": link.linked_by if link else "", "linked_at": link.linked_at if link else ""})
    for key, link in links.items():          # a link whose text no declaration uses any more — shown, not hidden
        if key not in uses:
            out.append({"owner_text": link.owner_text, "owner_key": key, "uses": [], "principal": link.principal,
                        "resolved": True, "how": "linked", "linked_by": link.linked_by, "linked_at": link.linked_at})
    out.sort(key=lambda e: (e["resolved"], -len(e["uses"]), e["owner_key"]))
    return out
