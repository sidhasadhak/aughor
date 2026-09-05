"""The intake lane's staging store — `AUGHOR_INTAKE_DB`.

Bookkeeping, not a store of record (§3.10's law: import into the stores that exist).
A bundle row remembers what arrived, from where, hashed; a candidate row remembers one
typed object, the plan's verdict on it, and what a human decided. Provenance lives
here: an accepted object's `target_ref` walks back to its bundle hash and source.

Store hygiene, paid for repeatedly and applied in ONE commit: the env name lands in
`tests/conftest.py` AND `scripts/dump_openapi.py` alongside this file.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Optional

from aughor.db.backend import connect_store
from aughor.db.sqlite_util import resolve_db_path
from aughor.db.store_pool import ensure_once


def _db_path() -> Path:
    """Resolved PER CALL, not at import — the trusted-queries store's DS-12 lesson:
    a module-level resolution freezes whatever env the first import saw, which makes
    per-test isolation impossible and once let a suite write into live data/."""
    return resolve_db_path("AUGHOR_INTAKE_DB", Path("data/intake.db"))

#: The candidate kinds the lane stages — §3.10's object model. Each maps to the
#: existing store its accepted form lands in (`definition` = a prose metric
#: definition, landing as a connection-KB `metric` entry).
KINDS = ("metric", "synonym", "glossary", "rule", "join", "definition",
         "trusted_query")

#: A candidate's verdict from the plan, and its resolution status.
VERDICTS = ("new", "changed", "identical", "conflict")
STATUSES = ("pending", "accepted", "dismissed", "noop")


def _connect() -> sqlite3.Connection:
    c = connect_store(_db_path(), check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def _ensure_schema(c: sqlite3.Connection) -> None:
    c.executescript("""
        -- One uploaded bundle. `content_hash` is the dedupe key: the same bytes
        -- re-uploaded return the SAME row, which is half of the idempotence receipt.
        CREATE TABLE IF NOT EXISTS intake_bundle (
            id           TEXT NOT NULL PRIMARY KEY,
            content_hash TEXT NOT NULL,
            connection_id TEXT NOT NULL DEFAULT '',
            source       TEXT NOT NULL DEFAULT '',
            uploaded_by  TEXT NOT NULL DEFAULT '',
            uploaded_at  TEXT NOT NULL,
            org_id       TEXT NOT NULL DEFAULT 'default',
            raw          TEXT NOT NULL DEFAULT ''
        );
        CREATE UNIQUE INDEX IF NOT EXISTS intake_bundle_hash
            ON intake_bundle (org_id, content_hash);

        -- One typed candidate. `payload` is the object as proposed; `edited_payload`
        -- is what the human changed it to (an edit is a stronger verdict than an
        -- accept); `target_ref` is stamped at apply time and is the provenance key.
        CREATE TABLE IF NOT EXISTS intake_candidate (
            id               TEXT NOT NULL PRIMARY KEY,
            bundle_id        TEXT NOT NULL,
            kind             TEXT NOT NULL,
            verdict          TEXT NOT NULL,
            detail           TEXT NOT NULL DEFAULT '',
            payload          TEXT NOT NULL,
            status           TEXT NOT NULL DEFAULT 'pending',
            resolved_by      TEXT NOT NULL DEFAULT '',
            resolved_at      TEXT NOT NULL DEFAULT '',
            edited_payload   TEXT NOT NULL DEFAULT '',
            target_ref       TEXT NOT NULL DEFAULT '',
            apply_result     TEXT NOT NULL DEFAULT '',
            org_id           TEXT NOT NULL DEFAULT 'default'
        );
        CREATE INDEX IF NOT EXISTS intake_candidate_bundle
            ON intake_candidate (bundle_id, status);
        CREATE INDEX IF NOT EXISTS intake_candidate_target
            ON intake_candidate (target_ref);
        PRAGMA journal_mode=WAL;
    """)
    c.commit()


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def bundle_hash(bundle: dict) -> str:
    """The bundle's identity: sha256 over its canonical serialisation (sorted keys),
    so 'is this the same file' has one answer regardless of key order."""
    canon = json.dumps(bundle, sort_keys=True, default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def save_bundle(bundle: dict, *, source: str, actor: str,
                org_id: str = "default") -> tuple[dict, bool]:
    """Persist an uploaded bundle; dedupe by content hash within the org.

    Returns ``(row, created)`` — ``created`` False means the identical bundle was
    uploaded before and THAT row (with its candidates) is the answer.
    """
    h = bundle_hash(bundle)
    with _connect() as c:
        ensure_once(c, _ensure_schema)
        row = c.execute("SELECT * FROM intake_bundle WHERE org_id=? AND content_hash=?",
                        (org_id, h)).fetchone()
        if row is not None:
            return dict(row), False
        rec = {"id": f"ib_{uuid.uuid4().hex[:12]}", "content_hash": h,
               "connection_id": str(bundle.get("connection_id") or ""),
               "source": source, "uploaded_by": actor, "uploaded_at": _now(),
               "org_id": org_id, "raw": json.dumps(bundle, sort_keys=True, default=str)}
        c.execute("INSERT INTO intake_bundle (id, content_hash, connection_id, source, "
                  "uploaded_by, uploaded_at, org_id, raw) VALUES (?,?,?,?,?,?,?,?)",
                  (rec["id"], rec["content_hash"], rec["connection_id"], rec["source"],
                   rec["uploaded_by"], rec["uploaded_at"], rec["org_id"], rec["raw"]))
        c.commit()
        return rec, True


def add_candidates(bundle_id: str, candidates: list[dict], *,
                   org_id: str = "default") -> list[dict]:
    """Stage the plan's candidates. `identical` verdicts land as status `noop` —
    there is nothing to decide about an object the store already holds."""
    out: list[dict] = []
    with _connect() as c:
        ensure_once(c, _ensure_schema)
        for cand in candidates:
            rec = {"id": f"ic_{uuid.uuid4().hex[:12]}", "bundle_id": bundle_id,
                   "kind": cand["kind"], "verdict": cand["verdict"],
                   "detail": str(cand.get("detail") or ""),
                   "payload": json.dumps(cand["payload"], sort_keys=True, default=str),
                   "status": "noop" if cand["verdict"] == "identical" else "pending",
                   "org_id": org_id}
            c.execute("INSERT INTO intake_candidate (id, bundle_id, kind, verdict, "
                      "detail, payload, status, org_id) VALUES (?,?,?,?,?,?,?,?)",
                      (rec["id"], rec["bundle_id"], rec["kind"], rec["verdict"],
                       rec["detail"], rec["payload"], rec["status"], rec["org_id"]))
            out.append(rec)
        c.commit()
    return out


def _cand_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["payload"] = json.loads(d["payload"]) if d.get("payload") else {}
    for k in ("edited_payload", "apply_result"):
        d[k] = json.loads(d[k]) if d.get(k) else None
    return d


def get_bundle(bundle_id: str, *, org_id: str = "default") -> Optional[dict]:
    with _connect() as c:
        ensure_once(c, _ensure_schema)
        row = c.execute("SELECT * FROM intake_bundle WHERE id=? AND org_id=?",
                        (bundle_id, org_id)).fetchone()
        return dict(row) if row else None


def list_bundles(*, org_id: str = "default",
                 connection_id: str = "") -> list[dict]:
    with _connect() as c:
        ensure_once(c, _ensure_schema)
        q = "SELECT * FROM intake_bundle WHERE org_id=?"
        args: list = [org_id]
        if connection_id:
            q += " AND connection_id=?"
            args.append(connection_id)
        rows = c.execute(q + " ORDER BY uploaded_at DESC", args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d.pop("raw", None)   # listings stay light; the plan view carries content
            out.append(d)
        return out


def list_candidates(bundle_id: str, *, org_id: str = "default") -> list[dict]:
    with _connect() as c:
        ensure_once(c, _ensure_schema)
        rows = c.execute("SELECT * FROM intake_candidate WHERE bundle_id=? AND org_id=? "
                         "ORDER BY kind, id", (bundle_id, org_id)).fetchall()
        return [_cand_dict(r) for r in rows]


def get_candidate(cand_id: str, *, org_id: str = "default") -> Optional[dict]:
    with _connect() as c:
        ensure_once(c, _ensure_schema)
        row = c.execute("SELECT * FROM intake_candidate WHERE id=? AND org_id=?",
                        (cand_id, org_id)).fetchone()
        return _cand_dict(row) if row else None


def resolve_candidate(cand_id: str, *, status: str, actor: str,
                      edited_payload: Optional[dict] = None,
                      target_ref: str = "", apply_result: Optional[dict] = None,
                      org_id: str = "default") -> None:
    with _connect() as c:
        ensure_once(c, _ensure_schema)
        c.execute("UPDATE intake_candidate SET status=?, resolved_by=?, resolved_at=?, "
                  "edited_payload=?, target_ref=?, apply_result=? "
                  "WHERE id=? AND org_id=?",
                  (status, actor, _now(),
                   json.dumps(edited_payload, sort_keys=True, default=str) if edited_payload else "",
                   target_ref,
                   json.dumps(apply_result, sort_keys=True, default=str) if apply_result else "",
                   cand_id, org_id))
        c.commit()


def llm_mapper_stats(*, org_id: str = "default",
                     bundle_id: str = "") -> dict:
    """The arc's falsifier input, measured from the lane's own rows: the human
    edit-rate on LLM-extracted candidates (bundles whose source is `llm:*`). An
    accept WITH an edit is the signal — the human had to fix what the model wrote.
    Dismissals are counted separately: a wrong candidate a human threw away cost a
    click, not a correction. `edit_rate` is None until something is resolved."""
    with _connect() as c:
        ensure_once(c, _ensure_schema)
        q = ("SELECT ic.status, ic.edited_payload FROM intake_candidate ic "
             "JOIN intake_bundle ib ON ic.bundle_id = ib.id "
             "WHERE ib.org_id=? AND ib.source LIKE 'llm:%'")
        args: list = [org_id]
        if bundle_id:
            q += " AND ib.id=?"
            args.append(bundle_id)
        rows = c.execute(q, args).fetchall()
    counts = {"candidates": len(rows), "pending": 0, "dismissed": 0,
              "accepted_clean": 0, "accepted_edited": 0, "noop": 0}
    for r in rows:
        if r["status"] == "pending":
            counts["pending"] += 1
        elif r["status"] == "dismissed":
            counts["dismissed"] += 1
        elif r["status"] == "noop":
            counts["noop"] += 1
        elif r["status"] == "accepted":
            counts["accepted_edited" if r["edited_payload"] else "accepted_clean"] += 1
    accepted = counts["accepted_clean"] + counts["accepted_edited"]
    return {**counts,
            "edit_rate": (round(counts["accepted_edited"] / accepted, 3)
                          if accepted else None)}


def provenance(target_ref: str, *, org_id: str = "default") -> list[dict]:
    """Walk an accepted object back to its bundle: candidate rows + the bundle's
    hash, source and uploader — §3.10's stated receipt."""
    with _connect() as c:
        ensure_once(c, _ensure_schema)
        rows = c.execute(
            "SELECT ic.*, ib.content_hash, ib.source AS bundle_source, "
            "ib.uploaded_by, ib.uploaded_at "
            "FROM intake_candidate ic JOIN intake_bundle ib ON ic.bundle_id = ib.id "
            "WHERE ic.target_ref=? AND ic.org_id=? ORDER BY ic.resolved_at DESC",
            (target_ref, org_id)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d["payload"]) if d.get("payload") else {}
            for k in ("edited_payload", "apply_result"):
                d[k] = json.loads(d[k]) if d.get(k) else None
            out.append(d)
        return out
