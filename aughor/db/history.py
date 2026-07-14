"""SQLite-backed investigation history store.

Investigation lifecycle:
  running   — created, agent loop in progress
  complete  — synthesize_report finished normally; indexed in Qdrant
  timed_out — wall-clock deadline exceeded; NOT indexed
  failed    — unexpected exception; NOT indexed

Only complete investigations are eligible for Qdrant indexing and cache hits.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from aughor.db.migrations import Migration, add_column_if_missing, run_migrations
from aughor.db.sqlite_util import resolve_db_path, tune
from aughor.org.context import DEFAULT_ORG_ID, current_org_id

logger = logging.getLogger(__name__)

_DB_PATH = resolve_db_path("AUGHOR_HISTORY_DB", Path(__file__).parent.parent.parent / "data" / "history.db")

InvStatus = Literal["running", "complete", "timed_out", "failed", "paused"]


# ── Kernel event spine (K2) — investigation lifecycle ─────────────────────────
# T3 kernel-leverage: investigations used to be invisible on the event spine (only
# the explorer emitted). Journaling each lifecycle transition HERE — at the single
# point every transition flows through — means every surface (ActivityLog, system
# panels, a second tab) sees an investigation start/finish/fail without polling,
# and reconciliation/supervision can build on a real event trail. Best-effort:
# the history row is the source of truth, so a failed emit never breaks the request.

def _inv_scope(c: sqlite3.Connection, inv_id: str) -> tuple[Optional[str], Optional[str]]:
    """(connection_id, canvas_id) for an investigation, so its events scope to the
    same connection/canvas the explorer's do."""
    try:
        row = c.execute(
            "SELECT connection_id, canvas_id FROM investigations WHERE id = ?", (inv_id,)
        ).fetchone()
        if row:
            return row["connection_id"], row["canvas_id"]
    except Exception:
        logger.debug("investigation scope lookup failed for %s", inv_id, exc_info=True)
    return None, None


def _emit_lifecycle(inv_id: str, kind: str, *, conn_id: Optional[str] = None,
                    canvas_id: Optional[str] = None, **payload: Any) -> None:
    """Append an `investigation.*` event to the kernel journal (best-effort)."""
    try:
        from aughor.kernel.ledger import Ledger
        from aughor.kernel.jobs import current_job_id
        Ledger.default().emit(
            kind, {"investigation_id": inv_id, **payload},
            conn_id=conn_id, canvas_id=canvas_id, job_id=current_job_id(),
        )
    except Exception:
        logger.debug("investigation lifecycle emit failed (%s)", kind, exc_info=True)


def _conn() -> sqlite3.Connection:
    c = tune(sqlite3.connect(_DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def _migrate_v2(c: sqlite3.Connection) -> None:
    """Additive columns + one-time backfills accumulated through 2026-07 (formerly a
    swallowed ALTER loop run on every init). Idempotent — safe on any DB state."""
    add_column_if_missing(c, "investigations", "status", "TEXT DEFAULT 'running'")
    add_column_if_missing(c, "investigations", "kind", "TEXT DEFAULT 'investigation'")
    add_column_if_missing(c, "investigations", "session_id", "TEXT")
    add_column_if_missing(c, "investigations", "canvas_id", "TEXT")             # launched-via-Canvas
    add_column_if_missing(c, "investigations", "origin_insight_id", "TEXT")     # drilled-finding provenance
    add_column_if_missing(c, "investigations", "org_id", f"TEXT NOT NULL DEFAULT '{DEFAULT_ORG_ID}'")  # DATA-06
    # Backfills for rows written before those columns existed (no-ops on fresh DBs).
    c.execute("UPDATE investigations SET status = 'complete' "
              "WHERE status = 'running' AND completed_at IS NOT NULL")
    c.execute("UPDATE investigations SET session_id = id "
              "WHERE kind = 'chat' AND (session_id IS NULL OR session_id = '')")


def _migrate_v3(c: sqlite3.Connection) -> None:
    """Persist the active user-agent on the run row so per-agent run history is
    joinable (E1/E5 of the 2026-07-11 Databricks-OSS study — ``agent_id`` lived
    only in the LangGraph checkpoint before, invisible to the history store).
    Additive + idempotent; existing rows default to '' (no agent)."""
    add_column_if_missing(c, "investigations", "agent_id", "TEXT NOT NULL DEFAULT ''")


_MIGRATIONS = [
    Migration(2, "additive columns + backfills (through 2026-07)", _migrate_v2),
    Migration(3, "add agent_id (per-agent run history)", _migrate_v3),
]


def _ensure_schema(c: sqlite3.Connection) -> None:
    c.execute("""
        CREATE TABLE IF NOT EXISTS investigations (
            id TEXT PRIMARY KEY,
            question TEXT NOT NULL,
            connection_id TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT DEFAULT 'running',
            hypothesis_count INTEGER DEFAULT 0,
            query_count INTEGER DEFAULT 0,
            headline TEXT,
            report_json TEXT,
            hypotheses_json TEXT,
            query_history_json TEXT,
            kind TEXT DEFAULT 'investigation',
            session_id TEXT
        )
    """)
    run_migrations(c, _MIGRATIONS, store="history")


def create_investigation(
    question: str,
    connection_id: str,
    canvas_id: Optional[str] = None,
    agent_id: str = "",
) -> str:
    """Insert a new in-progress row and return its ID.

    ``agent_id`` records the active user-agent (persona) the run executed under
    ('' when none), so the Agent Workspace can join run history per agent.
    """
    inv_id = uuid.uuid4().hex[:8]
    c = _conn()
    _ensure_schema(c)
    c.execute(
        "INSERT INTO investigations (id, question, connection_id, canvas_id, started_at, status, org_id, agent_id) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (inv_id, question, connection_id, canvas_id, _now(), "running", current_org_id(), agent_id),
    )
    c.commit()
    c.close()
    _emit_lifecycle(inv_id, "investigation.created", conn_id=connection_id,
                    canvas_id=canvas_id, question=question[:200])
    return inv_id


def complete_investigation(
    inv_id: str,
    report: Any,
    hypotheses: list,
    query_history: list,
    question: str = "",
    connection_id: str = "",
    skip_index: bool = False,
    origin_insight_id: Optional[str] = None,
) -> None:
    """Persist the final state and optionally index in Qdrant. Only called on clean completion.

    ``origin_insight_id`` records the briefing finding this investigation drilled, so the
    chain finding → investigation → report is queryable lineage (None for a cold start)."""
    report_dict = report.model_dump() if hasattr(report, "model_dump") else report
    hypotheses_list = [h.model_dump() if hasattr(h, "model_dump") else h for h in hypotheses]
    queries_list = [q.model_dump() if hasattr(q, "model_dump") else q for q in query_history]
    headline = report_dict.get("headline", "") if report_dict else ""

    c = _conn()
    _ensure_schema(c)
    c.execute(
        """UPDATE investigations SET
            completed_at = ?,
            status = 'complete',
            headline = ?,
            hypothesis_count = ?,
            query_count = ?,
            report_json = ?,
            hypotheses_json = ?,
            query_history_json = ?,
            origin_insight_id = COALESCE(?, origin_insight_id)
        WHERE id = ?""",
        (
            _now(), headline,
            len(hypotheses_list), len(queries_list),
            json.dumps(report_dict),
            json.dumps(hypotheses_list),
            json.dumps(queries_list),
            origin_insight_id,
            inv_id,
        ),
    )
    c.commit()
    _conn_scope, _canvas_scope = _inv_scope(c, inv_id)
    c.close()
    _emit_lifecycle(inv_id, "investigation.completed",
                    conn_id=connection_id or _conn_scope, canvas_id=_canvas_scope,
                    headline=(headline or "")[:200],
                    query_count=len(queries_list))

    # Index in the agent's RAG — only for investigate-mode completions (not direct
    # queries). Emitted via the platform ingestion seam so this module (platform db)
    # never imports the agent; the agent registers the "investigation_index" sink.
    if report_dict and not skip_index:
        key_findings = [f.get("claim", "") for f in (report_dict.get("key_findings") or [])]
        from aughor.kernel.registries.ingestion import ingest
        ingest("investigation_index", inv_id=inv_id, question=question, headline=headline,
               key_findings=key_findings, connection_id=connection_id, query_history=query_history)


def pause_investigation(inv_id: str) -> None:
    """Mark an investigation as paused, awaiting human feedback."""
    c = _conn()
    _ensure_schema(c)
    c.execute(
        "UPDATE investigations SET status = 'paused' WHERE id = ?",
        (inv_id,),
    )
    c.commit()
    _conn_scope, _canvas_scope = _inv_scope(c, inv_id)
    c.close()
    _emit_lifecycle(inv_id, "investigation.paused", conn_id=_conn_scope, canvas_id=_canvas_scope)


def fail_investigation(inv_id: str, status: InvStatus = "timed_out") -> None:
    """
    Mark an investigation as timed_out or failed.
    Deliberately does NOT index — partial results must not pollute the cache.
    """
    c = _conn()
    _ensure_schema(c)
    c.execute(
        "UPDATE investigations SET completed_at = ?, status = ? WHERE id = ?",
        (_now(), status, inv_id),
    )
    c.commit()
    _conn_scope, _canvas_scope = _inv_scope(c, inv_id)
    c.close()
    _emit_lifecycle(inv_id, "investigation.failed", conn_id=_conn_scope,
                    canvas_id=_canvas_scope, status=status)


def save_chat_turn(
    question: str,
    connection_id: str,
    headline: str,
    sql: str,
    session_id: str = "",
    columns: list | None = None,
    rows: list | None = None,
    chart_type: str = "auto",
    tables_used: list | None = None,
    intent: str = "",
    approach: list | None = None,
    canvas_id: str | None = None,
    insight: dict | None = None,
    overview_report: dict | None = None,
) -> str:
    """Persist a completed chat turn as a history row, linked to a session and
    (when run inside a Canvas) tagged with its canvas_id so Canvas history can
    scope to the specific Canvas rather than the whole connection."""
    inv_id = uuid.uuid4().hex[:8]
    sid = session_id or uuid.uuid4().hex[:12]
    now = _now()
    c = _conn()
    _ensure_schema(c)
    report = {
        "headline": headline,
        "sql": sql,
        "columns": columns or [],
        "rows": (rows or [])[:1000],   # cap stored rows at 1 000
        "chart_type": chart_type,
        "tables_used": tables_used or [],
        "intent":      intent or "",
        "approach":    approach or [],
        "insight":     insight or None,
        "overview_report": overview_report or None,   # the interesting-facts tour, when this was one
    }
    c.execute(
        """INSERT INTO investigations
           (id, question, connection_id, canvas_id, started_at, completed_at,
            status, hypothesis_count, query_count, headline,
            report_json, kind, session_id, org_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (inv_id, question, connection_id, canvas_id, now, now,
         "complete", 0, 1, headline,
         json.dumps(report),
         "chat", sid, current_org_id()),
    )
    c.commit()
    c.close()
    return inv_id


def update_chat_turn_insight(inv_id: str, insight: dict | None) -> bool:
    """Merge an insight dict into an existing chat turn's report_json."""
    if not insight:
        return False
    c = _conn()
    _ensure_schema(c)
    row = c.execute(
        "SELECT report_json FROM investigations WHERE id = ? AND kind = 'chat'",
        (inv_id,),
    ).fetchone()
    if not row:
        c.close()
        return False
    report = json.loads(row["report_json"] or "{}")
    report["insight"] = insight
    c.execute(
        "UPDATE investigations SET report_json = ? WHERE id = ?",
        (json.dumps(report), inv_id),
    )
    c.commit()
    c.close()
    return True

def last_activity_by_canvas() -> dict[str, str]:
    """Return {canvas_id: most-recent investigation started_at} for ranking
    Canvases by their latest activity."""
    c = _conn()
    _ensure_schema(c)
    rows = c.execute(
        """SELECT canvas_id, MAX(started_at) AS last
           FROM investigations
           WHERE canvas_id IS NOT NULL AND canvas_id != ''
           GROUP BY canvas_id""",
    ).fetchall()
    c.close()
    return {r["canvas_id"]: r["last"] for r in rows if r["last"]}


def sweep_stale_running(max_age_minutes: int = 60) -> int:
    """Mark investigations stuck in 'running' past max_age_minutes as 'failed'.
    These are orphaned by interrupted streams / restarts and otherwise clutter
    history with un-openable items. Returns the count updated.

    Each swept row journals an `investigation.failed` event: this is a terminal
    transition like any other, so the event spine must reflect it (otherwise a
    panel keeps showing the row as 'running' until its next poll, and the DB and
    journal disagree — the exact inconsistency T3 closes)."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)).isoformat()
    c = _conn()
    _ensure_schema(c)
    rows = c.execute(
        "SELECT id, connection_id, canvas_id FROM investigations "
        "WHERE status = 'running' AND started_at < ?",
        (cutoff,),
    ).fetchall()
    if not rows:
        c.close()
        return 0
    c.execute(
        "UPDATE investigations SET status = 'failed', completed_at = ? "
        "WHERE status = 'running' AND started_at < ?",
        (_now(), cutoff),
    )
    c.commit()
    c.close()
    for r in rows:
        _emit_lifecycle(r["id"], "investigation.failed", conn_id=r["connection_id"],
                        canvas_id=r["canvas_id"], status="failed", reason="stale sweep (orphaned)")
    return len(rows)


def list_orphaned_running_investigations() -> list[dict]:
    """Investigations still 'running' at boot — orphaned by the prior process (a
    fresh process has nothing genuinely running). Each carries what crash-recovery
    needs; `id` is also the LangGraph checkpoint thread_id."""
    c = _conn()
    _ensure_schema(c)
    rows = c.execute(
        "SELECT id, connection_id, canvas_id, question FROM investigations WHERE status = 'running'"
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def reconcile_orphaned_investigations() -> int:
    """Boot-time reconciliation: a freshly-started process has nothing genuinely
    running, so EVERY 'running' row is an orphan from the prior process. Fail all
    of them (regardless of age — unlike the periodic 60-min sweep) and journal an
    `investigation.failed` event for each, so the event spine narrates the
    recovery the same way the kernel narrates orphaned jobs. Returns the count."""
    c = _conn()
    _ensure_schema(c)
    rows = c.execute(
        "SELECT id, connection_id, canvas_id FROM investigations WHERE status = 'running'"
    ).fetchall()
    if not rows:
        c.close()
        return 0
    c.execute(
        "UPDATE investigations SET status = 'failed', completed_at = ? WHERE status = 'running'",
        (_now(),),
    )
    c.commit()
    c.close()
    for r in rows:
        _emit_lifecycle(r["id"], "investigation.failed", conn_id=r["connection_id"],
                        canvas_id=r["canvas_id"], status="failed", reason="server restart (orphaned)")
    return len(rows)


def get_session_turns(session_id: str) -> list[dict]:
    """Return all chat turns for a session, oldest first.
    Falls back to looking up by row id for single-turn legacy sessions."""
    c = _conn()
    _ensure_schema(c)
    rows = c.execute(
        """SELECT id, question, headline, report_json, started_at
           FROM investigations
           WHERE session_id = ? AND kind = 'chat'
           ORDER BY started_at ASC""",
        (session_id,),
    ).fetchall()
    # Fallback: maybe the caller passed a row id directly (old single-turn items)
    if not rows:
        rows = c.execute(
            """SELECT id, question, headline, report_json, started_at
               FROM investigations
               WHERE id = ? AND kind = 'chat'""",
            (session_id,),
        ).fetchall()
    c.close()
    result = []
    for r in rows:
        d = dict(r)
        report = json.loads(d.pop("report_json") or "{}")
        d["sql"]         = report.get("sql", "")
        d["columns"]     = report.get("columns", [])
        d["rows"]        = report.get("rows", [])
        d["chart_type"]  = report.get("chart_type", "auto")
        d["tables_used"] = report.get("tables_used", [])
        d["intent"]      = report.get("intent", "")
        d["approach"]    = report.get("approach", [])
        d["insight"]     = report.get("insight", None)
        d["overview_report"] = report.get("overview_report", None)
        result.append(d)
    return result


def delete_investigation(inv_id: str) -> bool:
    """Delete a history line item. Matches either a single investigation row by
    its ``id`` OR a whole chat session by ``session_id`` (history collapses chat
    turns into one item keyed by session_id). Returns True if anything deleted."""
    c = _conn()
    _ensure_schema(c)
    cursor = c.execute(
        "DELETE FROM investigations WHERE id = ? OR session_id = ?",
        (inv_id, inv_id),
    )
    deleted = cursor.rowcount > 0
    c.commit()
    c.close()
    return deleted


def purge_connection(connection_id: str) -> int:
    """Delete every investigation/chat row for a connection (catalog delete
    cascade). Returns the number of rows removed."""
    c = _conn()
    _ensure_schema(c)
    n = c.execute("DELETE FROM investigations WHERE connection_id = ?",
                  (connection_id,)).rowcount
    c.commit()
    c.close()
    return n


def purge_schema(connection_id: str, schema: str,
                 canvas_ids: Optional[list[str]] = None) -> list[str]:
    """Delete investigations/chat tied to a removed schema and return their ids (so the
    caller can purge the evidence claims). A row matches if it ran in one of ``canvas_ids``
    OR its stored SQL/report references the schema-qualified ``schema.`` (the form aughor
    emits, since it pins search_path and qualifies tables)."""
    c = _conn()
    _ensure_schema(c)
    like = f"%{schema}.%"
    ids = {
        r["id"] for r in c.execute(
            "SELECT id FROM investigations WHERE connection_id=? AND "
            "(query_history_json LIKE ? OR report_json LIKE ?)",
            (connection_id, like, like),
        ).fetchall()
    }
    if canvas_ids:
        ph = ",".join("?" for _ in canvas_ids)
        ids.update(r["id"] for r in c.execute(
            f"SELECT id FROM investigations WHERE canvas_id IN ({ph})", canvas_ids
        ).fetchall())
    if ids:
        ph = ",".join("?" for _ in ids)
        c.execute(f"DELETE FROM investigations WHERE id IN ({ph})", list(ids))
        c.commit()
    c.close()
    return list(ids)


def list_investigation_ids(connection_id: str, canvas_id: Optional[str] = None,
                           limit: int = 500) -> list[str]:
    """Return investigation IDs in a scope, newest-first. Used to scope the evidence
    ledger (which keys only by investigation_id) to a connection / canvas."""
    c = _conn()
    _ensure_schema(c)
    if canvas_id:
        rows = c.execute(
            "SELECT id FROM investigations WHERE connection_id = ? AND canvas_id = ? "
            "ORDER BY started_at DESC LIMIT ?",
            (connection_id, canvas_id, limit),
        ).fetchall()
    else:
        rows = c.execute(
            "SELECT id FROM investigations WHERE connection_id = ? "
            "ORDER BY started_at DESC LIMIT ?",
            (connection_id, limit),
        ).fetchall()
    return [r["id"] for r in rows]


def all_investigation_ids(connection_ids: Optional[list[str]] = None) -> list[str]:
    """Every investigation row id, optionally restricted to a set of connections.
    ``connection_ids=None`` means platform-wide; an empty list means none. Used by
    the bulk-clear cascade to resolve evidence/vector cleanup before deleting rows."""
    c = _conn()
    _ensure_schema(c)
    if connection_ids is None:
        rows = c.execute("SELECT id FROM investigations").fetchall()
    elif not connection_ids:
        rows = []
    else:
        ph = ",".join("?" for _ in connection_ids)
        rows = c.execute(
            f"SELECT id FROM investigations WHERE connection_id IN ({ph})",
            connection_ids,
        ).fetchall()
    c.close()
    return [r["id"] for r in rows]


def investigation_connection_ids(connection_ids: Optional[list[str]] = None) -> list[str]:
    """Distinct, non-empty connection ids that have investigations (optionally within
    a given set) — lets the bulk-clear cascade purge vector points by connection."""
    c = _conn()
    _ensure_schema(c)
    if connection_ids is None:
        rows = c.execute(
            "SELECT DISTINCT connection_id FROM investigations "
            "WHERE connection_id IS NOT NULL AND connection_id != ''"
        ).fetchall()
    elif not connection_ids:
        rows = []
    else:
        ph = ",".join("?" for _ in connection_ids)
        rows = c.execute(
            f"SELECT DISTINCT connection_id FROM investigations "
            f"WHERE connection_id IN ({ph}) AND connection_id IS NOT NULL AND connection_id != ''",
            connection_ids,
        ).fetchall()
    c.close()
    return [r["connection_id"] for r in rows]


def purge_ids(inv_ids: list[str]) -> int:
    """Delete the given investigation rows by id. Returns rows removed."""
    if not inv_ids:
        return 0
    c = _conn()
    _ensure_schema(c)
    ph = ",".join("?" for _ in inv_ids)
    n = c.execute(f"DELETE FROM investigations WHERE id IN ({ph})", inv_ids).rowcount
    c.commit()
    c.close()
    return n


def list_investigations(limit: int = 50) -> list[dict]:
    """Return summary rows newest-first, collapsing chat turns into one item per session."""
    c = _conn()
    _ensure_schema(c)

    # DATA-06: when identity is enforced, a caller sees only their own org's history.
    # current_org_id() is reliable here — _OrgContextMiddleware binds it for the
    # request. No-op (empty clause) in localhost mode.
    from aughor.security.authz import require_identity_enabled
    _org, _op = (" AND org_id = ?", [current_org_id()]) if require_identity_enabled() else ("", [])

    # Non-chat rows (investigations)
    inv_rows = c.execute(
        f"""SELECT id, question, connection_id, canvas_id, started_at, completed_at,
                  status, hypothesis_count, query_count, headline,
                  COALESCE(kind, 'investigation') as kind,
                  NULL as session_id, COALESCE(agent_id, '') as agent_id
           FROM investigations
           WHERE (kind IS NULL OR kind = 'investigation'){_org}
           ORDER BY started_at DESC
           LIMIT ?""",
        (*_op, limit),
    ).fetchall()

    # Chat turns grouped by session_id
    session_rows = c.execute(
        f"""SELECT
               session_id as id,
               MIN(question) as question,
               connection_id,
               MIN(started_at) as started_at,
               MAX(completed_at) as completed_at,
               'complete' as status,
               0 as hypothesis_count,
               COUNT(*) as query_count,
               MAX(headline) as headline,
               'chat' as kind,
               session_id,
               MAX(canvas_id) as canvas_id,
               COALESCE(MAX(agent_id), '') as agent_id
           FROM investigations
           WHERE kind = 'chat' AND session_id IS NOT NULL AND session_id != ''{_org}
           GROUP BY session_id, connection_id
           ORDER BY started_at DESC""",
        (*_op,),
    ).fetchall()

    # Also pick up legacy chat rows without a session_id (treat each as own session)
    legacy_rows = c.execute(
        f"""SELECT id, question, connection_id, started_at, completed_at,
                  'complete' as status, 0 as hypothesis_count, 1 as query_count,
                  headline, 'chat' as kind, id as session_id, canvas_id,
                  COALESCE(agent_id, '') as agent_id
           FROM investigations
           WHERE kind = 'chat' AND (session_id IS NULL OR session_id = ''){_org}
           ORDER BY started_at DESC""",
        (*_op,),
    ).fetchall()

    c.close()

    combined = [dict(r) for r in list(inv_rows) + list(session_rows) + list(legacy_rows)]
    combined.sort(key=lambda r: r.get("started_at", ""), reverse=True)
    return combined[:limit]


def list_investigations_for_agent(agent_id: str, limit: int = 50) -> list[dict]:
    """Run history for a single user-agent (deep runs stamped with ``agent_id``),
    newest-first and org-scoped exactly like :func:`list_investigations`. Powers
    the Agent Workspace overview; '' agent_id yields no rows (unbound runs are not
    a persona's history)."""
    if not agent_id:
        return []
    c = _conn()
    _ensure_schema(c)
    from aughor.security.authz import require_identity_enabled
    _org, _op = (" AND org_id = ?", [current_org_id()]) if require_identity_enabled() else ("", [])
    rows = c.execute(
        f"""SELECT id, question, connection_id, canvas_id, started_at, completed_at,
                  status, hypothesis_count, query_count, headline,
                  COALESCE(kind, 'investigation') as kind, agent_id
           FROM investigations
           WHERE agent_id = ? AND (kind IS NULL OR kind = 'investigation'){_org}
           ORDER BY started_at DESC
           LIMIT ?""",
        (agent_id, *_op, limit),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_investigation(inv_id: str) -> Optional[dict]:
    """Return the full investigation record including parsed JSON fields."""
    c = _conn()
    _ensure_schema(c)
    row = c.execute(
        "SELECT * FROM investigations WHERE id = ?", (inv_id,)
    ).fetchone()
    c.close()
    if not row:
        return None
    d = dict(row)
    for field in ("report_json", "hypotheses_json", "query_history_json"):
        raw = d.pop(field, None)
        key = field.replace("_json", "")
        d[key] = json.loads(raw) if raw else None
    return d


from aughor.util.time import now_iso as _now
