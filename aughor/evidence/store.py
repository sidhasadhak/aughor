"""Evidence Ledger store — append-only SQLite backend.

All writes are append-only (no UPDATE on claim rows, only on feedback fields).
This preserves a complete audit trail of every claim Aughor has ever made.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from aughor.evidence.models import EvidenceClaim

_LOCK = threading.Lock()
_DB_PATH = Path(__file__).parent.parent.parent / "data" / "evidence_ledger.db"


def _get_conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS evidence_claims (
            id                          TEXT PRIMARY KEY,
            investigation_id            TEXT NOT NULL,
            hypothesis_id               TEXT,
            claim_text                  TEXT NOT NULL,
            sql_source                  TEXT,
            metric_used                 TEXT,
            data_freshness              TEXT,
            confidence                  REAL NOT NULL,
            created_at                  TEXT NOT NULL,
            owner_feedback              TEXT,
            feedback_note               TEXT,
            downstream_recommendations  TEXT NOT NULL DEFAULT '[]',
            outcome_status              TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_ec_inv  ON evidence_claims(investigation_id);
        CREATE INDEX IF NOT EXISTS idx_ec_met  ON evidence_claims(metric_used);
    """)
    conn.commit()


def _row_to_claim(row: sqlite3.Row) -> EvidenceClaim:
    d = dict(row)
    d["downstream_recommendations"] = json.loads(d.get("downstream_recommendations") or "[]")
    return EvidenceClaim(**d)


# ── Public API ────────────────────────────────────────────────────────────────

def append_claim(claim: EvidenceClaim) -> None:
    """Insert a new claim. Idempotent — silently ignores duplicate IDs."""
    with _LOCK:
        conn = _get_conn()
        try:
            _init_schema(conn)
            conn.execute(
                """INSERT OR IGNORE INTO evidence_claims
                   (id, investigation_id, hypothesis_id, claim_text, sql_source,
                    metric_used, data_freshness, confidence, created_at,
                    owner_feedback, feedback_note, downstream_recommendations, outcome_status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    claim.id,
                    claim.investigation_id,
                    claim.hypothesis_id,
                    claim.claim_text,
                    claim.sql_source,
                    claim.metric_used,
                    claim.data_freshness,
                    claim.confidence,
                    claim.created_at,
                    claim.owner_feedback,
                    claim.feedback_note,
                    json.dumps(claim.downstream_recommendations),
                    claim.outcome_status,
                ),
            )
            conn.commit()
        finally:
            conn.close()


def get_claims_for_investigation(investigation_id: str) -> list[EvidenceClaim]:
    """Return all claims for a given investigation, ordered by confidence desc."""
    with _LOCK:
        conn = _get_conn()
        try:
            _init_schema(conn)
            rows = conn.execute(
                "SELECT * FROM evidence_claims WHERE investigation_id = ? ORDER BY confidence DESC",
                (investigation_id,),
            ).fetchall()
            return [_row_to_claim(r) for r in rows]
        finally:
            conn.close()


def get_recent_claims_for_investigations(
    investigation_ids: list[str], limit: int = 50,
) -> list[EvidenceClaim]:
    """Return the most recent claims across a set of investigations (newest-first).

    Powers the scope-level Evidence layer: the caller resolves a connection/canvas to
    its investigation IDs (the ledger keys only by investigation_id) and passes them in.
    """
    if not investigation_ids:
        return []
    with _LOCK:
        conn = _get_conn()
        try:
            _init_schema(conn)
            placeholders = ",".join("?" * len(investigation_ids))
            rows = conn.execute(
                f"SELECT * FROM evidence_claims WHERE investigation_id IN ({placeholders}) "
                f"ORDER BY created_at DESC LIMIT ?",
                (*investigation_ids, limit),
            ).fetchall()
            return [_row_to_claim(r) for r in rows]
        finally:
            conn.close()


def get_claims_for_metric(metric_name: str) -> list[EvidenceClaim]:
    """Return all claims that reference a particular metric."""
    with _LOCK:
        conn = _get_conn()
        try:
            _init_schema(conn)
            rows = conn.execute(
                "SELECT * FROM evidence_claims WHERE metric_used = ? ORDER BY created_at DESC",
                (metric_name,),
            ).fetchall()
            return [_row_to_claim(r) for r in rows]
        finally:
            conn.close()


def update_feedback(
    claim_id: str,
    feedback: Optional[str],
    note: Optional[str] = None,
) -> Optional[EvidenceClaim]:
    """Set owner_feedback on an existing claim. Returns updated claim or None."""
    with _LOCK:
        conn = _get_conn()
        try:
            _init_schema(conn)
            conn.execute(
                "UPDATE evidence_claims SET owner_feedback = ?, feedback_note = ? WHERE id = ?",
                (feedback, note, claim_id),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM evidence_claims WHERE id = ?", (claim_id,)
            ).fetchone()
            return _row_to_claim(row) if row else None
        finally:
            conn.close()


def update_outcome(claim_id: str, outcome: str) -> Optional[EvidenceClaim]:
    """Set outcome_status on a claim."""
    with _LOCK:
        conn = _get_conn()
        try:
            _init_schema(conn)
            conn.execute(
                "UPDATE evidence_claims SET outcome_status = ? WHERE id = ?",
                (outcome, claim_id),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM evidence_claims WHERE id = ?", (claim_id,)
            ).fetchone()
            return _row_to_claim(row) if row else None
        finally:
            conn.close()
