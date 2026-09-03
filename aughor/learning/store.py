"""The dataset store — `AUGHOR_LEARNING_DB`, plus `AUGHOR_DATASETS_DIR` for the bytes.

Two locations because they hold two different kinds of thing. The DATABASE holds small,
queryable, permanent facts (which dataset, which version, what fed it). The DIRECTORY
holds snapshot payloads, which are large, immutable and deletable — a privacy purge or a
disk-space sweep removes bytes without touching provenance.

Store hygiene, paid for repeatedly and applied here in ONE commit: the env names land in
`tests/conftest.py` AND `scripts/dump_openapi.py` alongside this file, and the directory
family is registered too (a dir-keyed store needs all three — paid again 2026-09-02).
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Optional

from aughor.db.backend import connect_store
from aughor.db.sqlite_util import resolve_db_path
from aughor.db.store_pool import ensure_once

_DB_PATH = resolve_db_path("AUGHOR_LEARNING_DB", Path("data/learning.db"))

#: The kinds a dataset node can be. `golden` is held out and NEVER trained on — it is the
#: ratchet's measuring stick, and a corpus that trains on its own benchmark cannot be
#: measured by it.
KINDS = ("sft", "dpo", "golden")


def datasets_dir() -> Path:
    """Where snapshot bytes live: `AUGHOR_DATASETS_DIR`, else `<state dir>/datasets`.

    Rides `state_dir()` rather than a literal `data/` so a whole-deployment move — and the
    suite's temp `AUGHOR_STATE_DIR` — carries the snapshots with it, the property every
    store-hermeticity guard exists to keep."""
    p = os.getenv("AUGHOR_DATASETS_DIR", "")
    if p:
        return Path(p)
    from aughor.db.paths import state_dir
    return state_dir() / "datasets"


def _connect() -> sqlite3.Connection:
    c = connect_store(_DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def _ensure_schema(c: sqlite3.Connection) -> None:
    c.executescript("""
        -- Content-addressed bytes. `uri` points into the datasets directory; `deleted_at`
        -- records a purge WITHOUT removing the row, so a node whose payload is gone still
        -- says what it was and what fed it. Provenance outlives the payload.
        CREATE TABLE IF NOT EXISTS dataset_data (
            hash       TEXT NOT NULL PRIMARY KEY,
            size       INTEGER NOT NULL DEFAULT 0,
            uri        TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            deleted_at TEXT NOT NULL DEFAULT ''
        );

        -- A named, versioned dataset. `data_id` is the content hash, so two versions with
        -- identical bytes share one blob. `parent_id` records a clone — a filtered or
        -- re-graded corpus says what it came FROM instead of pretending to be new.
        CREATE TABLE IF NOT EXISTS dataset_node (
            id         TEXT NOT NULL PRIMARY KEY,
            name       TEXT NOT NULL,
            version    INTEGER NOT NULL DEFAULT 1,
            task       TEXT NOT NULL DEFAULT '',
            kind       TEXT NOT NULL,
            data_id    TEXT NOT NULL DEFAULT '',
            parent_id  TEXT NOT NULL DEFAULT '',
            row_count  INTEGER NOT NULL DEFAULT 0,
            org_id     TEXT NOT NULL DEFAULT 'default',
            created_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS dataset_node_version
            ON dataset_node (org_id, name, version);
        CREATE INDEX IF NOT EXISTS dataset_node_kind ON dataset_node (kind, created_at);

        -- What fed a dataset. `source_kind` names the surface (finding_verdict,
        -- guard_verdict, audit_log, session_event) and `source_id` the row. This is the
        -- question MI-4 must answer about any adapter it promotes: which human judgements
        -- and which executions are inside these weights.
        CREATE TABLE IF NOT EXISTS dataset_lineage (
            dataset_id  TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            source_id   TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            PRIMARY KEY (dataset_id, source_kind, source_id)
        );
        CREATE INDEX IF NOT EXISTS dataset_lineage_source
            ON dataset_lineage (source_kind, source_id);
        PRAGMA journal_mode=WAL;
    """)
    c.commit()


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def content_hash(rows: list[dict]) -> str:
    """The identity of a corpus: sha256 over its canonical serialisation.

    Canonical means sorted keys and a stable row order, because the hash has to answer
    "are these the same examples", not "were they written in the same order". Two exports
    of an unchanged corpus MUST agree — that determinism is what makes a dataset citable
    from an adapter's provenance, and it is MI-3's stated receipt.
    """
    canon = "\n".join(sorted(json.dumps(r, sort_keys=True, default=str) for r in rows))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def write_snapshot(rows: list[dict]) -> tuple[str, Path, int]:
    """Write rows as JSONL under the datasets dir, keyed by content hash.

    Idempotent by construction: the same rows produce the same hash and therefore the same
    path, so re-exporting an unchanged corpus rewrites nothing and costs no new bytes."""
    h = content_hash(rows)
    d = datasets_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{h}.jsonl"
    if not path.exists():
        body = "".join(json.dumps(r, sort_keys=True, default=str) + "\n" for r in rows)
        tmp = path.with_suffix(".jsonl.tmp")
        tmp.write_text(body, encoding="utf-8")
        tmp.replace(path)          # atomic: a reader never sees a half-written snapshot
    return h, path, path.stat().st_size


def register(name: str, kind: str, rows: list[dict], *, task: str = "",
             parent_id: str = "", org_id: Optional[str] = None,
             lineage: Optional[list[tuple[str, str]]] = None) -> dict:
    """Snapshot `rows` and register them as the next version of `name`. Returns the node.

    Versioning is per (org, name) and monotonic. Re-registering IDENTICAL content is not
    an error and does not create a version — it returns the existing node, because a
    dataset's version means "the content changed", not "somebody ran the exporter again".
    An exporter on a schedule would otherwise mint a new version every night over an
    unchanged corpus and make the lineage unreadable.
    """
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
    from aughor.org.context import current_org_id
    org = org_id or current_org_id() or "default"
    h, path, size = write_snapshot(rows)

    c = _connect()
    try:
        ensure_once(c, _ensure_schema)
        existing = c.execute(
            "SELECT * FROM dataset_node WHERE org_id=? AND name=? AND data_id=? "
            "ORDER BY version DESC LIMIT 1", (org, name, h)).fetchone()
        if existing is not None:
            return dict(existing)

        c.execute(
            "INSERT OR IGNORE INTO dataset_data (hash, size, uri, created_at) "
            "VALUES (?,?,?,?)", (h, size, str(path), _now()))
        row = c.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM dataset_node WHERE org_id=? AND name=?",
            (org, name)).fetchone()
        version = int(row[0])
        node_id = uuid.uuid4().hex
        c.execute(
            "INSERT INTO dataset_node "
            "(id, name, version, task, kind, data_id, parent_id, row_count, org_id, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (node_id, name, version, task, kind, h, parent_id, len(rows), org, _now()))
        for source_kind, source_id in (lineage or []):
            c.execute(
                "INSERT OR IGNORE INTO dataset_lineage "
                "(dataset_id, source_kind, source_id, created_at) VALUES (?,?,?,?)",
                (node_id, source_kind, str(source_id), _now()))
        c.commit()
        return dict(c.execute("SELECT * FROM dataset_node WHERE id=?", (node_id,)).fetchone())
    finally:
        c.close()


def get(name: str, version: Optional[int] = None,
        org_id: Optional[str] = None) -> Optional[dict]:
    """One dataset node — the newest version of `name`, or a specific one."""
    from aughor.org.context import current_org_id
    org = org_id or current_org_id() or "default"
    c = _connect()
    try:
        ensure_once(c, _ensure_schema)
        if version is None:
            row = c.execute(
                "SELECT * FROM dataset_node WHERE org_id=? AND name=? "
                "ORDER BY version DESC LIMIT 1", (org, name)).fetchone()
        else:
            row = c.execute(
                "SELECT * FROM dataset_node WHERE org_id=? AND name=? AND version=?",
                (org, name, version)).fetchone()
        return dict(row) if row else None
    finally:
        c.close()


def rows_of(node: dict) -> list[dict]:
    """Read a node's examples back. Empty when the bytes have been purged — the node and
    its lineage survive a purge on purpose, so this returning [] is a legitimate state and
    not an error to raise on."""
    c = _connect()
    try:
        ensure_once(c, _ensure_schema)
        blob = c.execute("SELECT uri, deleted_at FROM dataset_data WHERE hash=?",
                         (node.get("data_id") or "",)).fetchone()
    finally:
        c.close()
    if blob is None or blob["deleted_at"]:
        return []
    p = Path(blob["uri"])
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line]


def lineage_of(dataset_id: str) -> list[dict]:
    """Every source row that fed a dataset — the provenance walk MI-4 owes any adapter."""
    c = _connect()
    try:
        ensure_once(c, _ensure_schema)
        return [dict(r) for r in c.execute(
            "SELECT * FROM dataset_lineage WHERE dataset_id=? ORDER BY source_kind, source_id",
            (dataset_id,)).fetchall()]
    finally:
        c.close()


def purge_bytes(hash_: str) -> bool:
    """Delete a snapshot's PAYLOAD, keeping its row and every node that cites it.

    The privacy act §6.7's annex implies: a corpus can be withdrawn without erasing the
    record that it existed and what it was built from. Returns True when bytes were
    removed."""
    c = _connect()
    try:
        ensure_once(c, _ensure_schema)
        row = c.execute("SELECT uri, deleted_at FROM dataset_data WHERE hash=?",
                        (hash_,)).fetchone()
        if row is None or row["deleted_at"]:
            return False
        p = Path(row["uri"])
        if p.exists():
            p.unlink()
        c.execute("UPDATE dataset_data SET deleted_at=? WHERE hash=?", (_now(), hash_))
        c.commit()
        return True
    finally:
        c.close()


def stats(org_id: Optional[str] = None) -> dict[str, Any]:
    """Per-kind dataset and example counts — what MI-4's entry gates are measured against."""
    from aughor.org.context import current_org_id
    org = org_id or current_org_id() or "default"
    c = _connect()
    try:
        ensure_once(c, _ensure_schema)
        out: dict[str, Any] = {}
        for kind in KINDS:
            row = c.execute(
                "SELECT COUNT(*) AS datasets, COALESCE(SUM(row_count), 0) AS examples "
                "FROM dataset_node WHERE org_id=? AND kind=?", (org, kind)).fetchone()
            out[kind] = {"datasets": int(row["datasets"]), "examples": int(row["examples"])}
        return out
    finally:
        c.close()
