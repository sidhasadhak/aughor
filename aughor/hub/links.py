"""HB-3 — the manifest's first links: a ticket, a thread or a webhook call FILED on the
object it is about, with the outcome column.

§3.18's fifth law made a store: *everything lands on the map — a message, a ticket, a
decision or an answer that passed through is filed against the object it is about.* A
link is a REFERENCE (kind + ref + url), never a copy; the object side is a securable
string (``promise:order_to_delivery.dispatch``, ``process:…``, ``finding:…``,
``entity:…``) — the same vocabulary grants and routing already speak, so the thing a
ticket is filed on is the thing a breach routes by.

The OUTCOME column is the wave's second half: a filed link is ``open`` until a person
closes it, and the close records what happened (ticket resolved, number recovered) plus
a snapshot of the object's stamped measures at filing and at close — which is what lets
the Briefing say "breach rate before and after, with the chain" without a second
measurement machinery. On a frozen dataset the two snapshots are honestly equal: the
mechanism is proven, the recovery is the world's to deliver.

Registered hermetically in the SAME commit (`AUGHOR_HUB_LINKS_DB` in tests/conftest.py
and scripts/dump_openapi.py).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Optional

from aughor.db.backend import connect_store
from aughor.db.sqlite_util import resolve_db_path
from aughor.util.time import now_iso_z

_DEFAULT_PATH = Path(__file__).parent.parent.parent / "data" / "hub_links.db"


def _db_path() -> Path:
    return resolve_db_path("AUGHOR_HUB_LINKS_DB", _DEFAULT_PATH)


_LOCK = threading.RLock()

_DDL = """
CREATE TABLE IF NOT EXISTS object_links (
    id                TEXT PRIMARY KEY,
    ts                TEXT NOT NULL DEFAULT '',
    org_id            TEXT NOT NULL DEFAULT '',
    object_ref        TEXT NOT NULL DEFAULT '',   -- securable string: promise:… process:… finding:…
    kind              TEXT NOT NULL DEFAULT '',   -- ticket | thread | webhook | doc
    ref               TEXT NOT NULL DEFAULT '',   -- OPS-123 · channel:ts · caller's ref
    url               TEXT NOT NULL DEFAULT '',
    title             TEXT NOT NULL DEFAULT '',
    source            TEXT NOT NULL DEFAULT '',   -- automation:<id> · user:<id> · agent:<id>
    status            TEXT NOT NULL DEFAULT 'open',   -- open | closed
    outcome           TEXT NOT NULL DEFAULT '',
    number_recovered  TEXT NOT NULL DEFAULT '',
    metrics_at_filing TEXT NOT NULL DEFAULT '{}',
    metrics_at_close  TEXT NOT NULL DEFAULT '{}',
    closed_at         TEXT NOT NULL DEFAULT '',
    closed_by         TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_links_object ON object_links (object_ref);
CREATE INDEX IF NOT EXISTS idx_links_status ON object_links (status);
CREATE INDEX IF NOT EXISTS idx_links_ts     ON object_links (ts DESC);
"""


def _connect() -> sqlite3.Connection:
    conn = connect_store(_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_DDL)
    return conn


def _row(r) -> dict:
    d = dict(r)
    for k in ("metrics_at_filing", "metrics_at_close"):
        try:
            d[k] = json.loads(d.get(k) or "{}")
        except Exception:
            d[k] = {}
    return d


def file_link(*, object_ref: str, kind: str, ref: str = "", url: str = "",
              title: str = "", source: str = "", org_id: str = "default") -> dict:
    """File one external artifact on an object. Snapshots the object's stamped
    measures at filing (best-effort — a promise's breach rate; anything else files
    with an empty snapshot)."""
    row = {
        "id": uuid.uuid4().hex[:12], "ts": now_iso_z(), "org_id": org_id,
        "object_ref": str(object_ref), "kind": str(kind), "ref": str(ref),
        "url": str(url), "title": str(title)[:300], "source": str(source),
        "status": "open", "outcome": "", "number_recovered": "",
        "metrics_at_filing": json.dumps(stamped_measures(object_ref)),
        "metrics_at_close": "{}", "closed_at": "", "closed_by": "",
    }
    cols = ", ".join(row)
    binds = ", ".join(f":{c}" for c in row)
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(f"INSERT INTO object_links ({cols}) VALUES ({binds})", row)
            conn.commit()
        finally:
            conn.close()
    return get_link(row["id"]) or row


def get_link(link_id: str) -> Optional[dict]:
    with _LOCK:
        conn = _connect()
        try:
            r = conn.execute("SELECT * FROM object_links WHERE id = ?",
                             (link_id,)).fetchone()
            return _row(r) if r else None
        finally:
            conn.close()


def list_links(object_ref: Optional[str] = None, status: Optional[str] = None,
               kind: Optional[str] = None, limit: int = 100) -> list[dict]:
    clauses, params = [], []
    if object_ref:
        clauses.append("object_ref = ?"); params.append(object_ref)
    if status:
        clauses.append("status = ?"); params.append(status)
    if kind:
        clauses.append("kind = ?"); params.append(kind)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                f"SELECT * FROM object_links {where} ORDER BY ts DESC LIMIT ?",
                [*params, max(1, min(int(limit), 500))]).fetchall()
            return [_row(r) for r in rows]
        finally:
            conn.close()


def close_link(link_id: str, *, outcome: str, number_recovered: str = "",
               closed_by: str = "") -> Optional[dict]:
    """Record the outcome — the wave's column. Re-snapshots the object's stamped
    measures so before/after is two recorded facts, not a memory."""
    existing = get_link(link_id)
    if existing is None:
        return None
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                "UPDATE object_links SET status = 'closed', outcome = ?, "
                "number_recovered = ?, metrics_at_close = ?, closed_at = ?, closed_by = ? "
                "WHERE id = ?",
                (str(outcome)[:500], str(number_recovered)[:120],
                 json.dumps(stamped_measures(existing["object_ref"])),
                 now_iso_z(), str(closed_by), link_id))
            conn.commit()
        finally:
            conn.close()
    return get_link(link_id)


def stamped_measures(object_ref: str) -> dict:
    """The object's CURRENT stamped numbers, for the filing/close snapshots — a read of
    the cached ontology (a read never builds), covering the promise kind today.
    Object refs carry no connection, so the promise's home is found by scanning the
    cached graphs of connections that declared it — best-effort, {} when unknown."""
    ref = str(object_ref or "")
    if not ref.startswith("promise:"):
        return {}
    try:
        pid = ref.split(":", 1)[1]
        process_id, _, promise_name = pid.partition(".")
        from aughor.ontology.store import cached_ontology_scopes, load_latest_ontology
        for conn_id, schema in cached_ontology_scopes():
            graph = load_latest_ontology(conn_id, schema)
            process = (getattr(graph, "processes", None) or {}).get(process_id) if graph else None
            if process is None:
                continue
            from aughor.ontology.processes import describe_process
            for stage in describe_process(graph, process).get("stages", []):
                p = stage.get("promise")
                if p and p.get("name") == promise_name:
                    return {"breached": p.get("breached"), "reached": p.get("reached"),
                            "breach_rate": p.get("breach_rate"), "as_of": p.get("as_of"),
                            "connection_id": conn_id}
    except Exception:
        return {}
    return {}
