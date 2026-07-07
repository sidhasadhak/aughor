"""The Ambiguity Ledger — resolution that COMPOUNDS (SOMA improvisation I1).

SOMA re-pays its full probe pipeline every time any user asks an ambiguous question; the
resolution evaporates after the answer. Aughor has what a paper harness cannot — a persistent
per-connection substrate — so a resolved ambiguity can be **crystallized once and reused
forever**. When a disagreement is settled (by a B1 probe, by a user's clarify choice, or by a
human verdict), we write a first-class `AmbiguityResolution`; the read path consults the ledger
FIRST, so a question that matches a resolved dimension injects the resolution as an authoritative
prior and skips candidates + probes entirely.

The consequence: SOMA's cost curve is flat per question; Aughor's **burns down monotonically per
connection** — the ambiguity space of a deployed schema shrinks with use. Design:
docs/SOMA_LEVERAGE_AND_AMBIGUITY_LEDGER_2026-07-06.md §3/I1; the mechanical version of the
"living context graph that compounds" (memory: context-graph-closed-loop-gap).

House store idiom (mirrors `verify/verdicts.py`): `resolve_db_path` env override so the suite
NEVER touches live `data/` (the registry-wipe scar), `tune()` PRAGMAs, `run_migrations` for
forward-only schema evolution. Matching is deterministic lexical token-overlap (the
`trusted_queries` idiom via `semantic/lexical.tokenize`) — no embedding dependency, reproducible
in tests, and the whole record is receipt-ready evidence.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from aughor.db.migrations import run_migrations
from aughor.db.sqlite_util import resolve_db_path, tune
from aughor.semantic.lexical import tokenize

_LOCK = threading.Lock()
_DB_PATH = resolve_db_path(
    "AUGHOR_AMBIGUITY_LEDGER_DB",
    Path(__file__).parent.parent.parent / "data" / "ambiguity_ledger.db",
)

# Resolution authority — override-wins (the ontology idiom): a human verdict beats a user
# clarify, which beats an autonomous probe. A re-resolution only overwrites the reading when it
# arrives with >= authority, so machinery can never clobber a human decision.
_SOURCE_RANK = {"probe": 1, "user": 2, "verdict": 3}

_MIGRATIONS: list = []  # forward-only; append Migration(2, ...) when the schema evolves


class Reading(BaseModel):
    """One candidate interpretation of an ambiguous dimension."""
    label: str                      # human-facing ("per-match totals", "career totals")
    sql_evidence: str = ""          # the differing SQL fragment that embodies this reading


class AmbiguityResolution(BaseModel):
    """A crystallized, reusable resolution of one ambiguity dimension on one connection."""
    connection_id: str
    org_id: str = ""
    schema_scope: str = ""                          # table/schema the dimension lives in
    dim_kind: str                                   # AmbiValue | AmbiIntent | AmbiSchema
    dim_facet: str                                  # literal|grain|aggregation|window|column
    subject: str                                    # what's ambiguous ("total runs by strikers")
    readings: list[Reading] = Field(default_factory=list)
    resolved_reading: str                           # the chosen reading's label
    resolved_sql: str = ""                          # canonical fragment/answer, when known
    resolution_source: str                          # probe | user | verdict
    evidence: str = ""                              # probe finding | user utterance | verdict id
    id: str = ""                                    # deterministic natural-key hash (auto)
    subject_fingerprint: str = ""                   # token signature (auto)
    created_at: str = ""
    last_used_at: Optional[str] = None
    use_count: int = 0

    def natural_key(self) -> str:
        """Same dimension on same connection ⇒ same row (idempotent burn-down)."""
        fp = self.subject_fingerprint or _fingerprint(self.subject)
        raw = f"{self.org_id}|{self.connection_id}|{self.dim_facet}|{fp}"
        return hashlib.sha1(raw.encode()).hexdigest()[:20]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fingerprint(text: str) -> str:
    """Order-insensitive content-token signature — the matching + dedup key."""
    return " ".join(sorted(set(tokenize(text or ""))))


def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = tune(sqlite3.connect(str(_DB_PATH)))
    c.row_factory = sqlite3.Row
    _ensure_schema(c)
    return c


def _ensure_schema(c: sqlite3.Connection) -> None:
    c.execute("""
        CREATE TABLE IF NOT EXISTS ambiguity_resolutions (
            id                   TEXT PRIMARY KEY,
            org_id               TEXT NOT NULL DEFAULT '',
            connection_id        TEXT NOT NULL,
            schema_scope         TEXT NOT NULL DEFAULT '',
            dim_kind             TEXT NOT NULL,
            dim_facet            TEXT NOT NULL,
            subject              TEXT NOT NULL,
            subject_fingerprint  TEXT NOT NULL DEFAULT '',
            readings             TEXT NOT NULL DEFAULT '[]',
            resolved_reading     TEXT NOT NULL,
            resolved_sql         TEXT NOT NULL DEFAULT '',
            resolution_source    TEXT NOT NULL,
            evidence             TEXT NOT NULL DEFAULT '',
            created_at           TEXT NOT NULL,
            last_used_at         TEXT,
            use_count            INTEGER NOT NULL DEFAULT 0
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS ix_ar_conn "
              "ON ambiguity_resolutions (org_id, connection_id)")
    run_migrations(c, _MIGRATIONS, store="ambiguity_ledger")
    c.commit()


def _row_to_res(row: sqlite3.Row) -> AmbiguityResolution:
    d = dict(row)
    d["readings"] = [Reading(**r) for r in json.loads(d.get("readings") or "[]")]
    return AmbiguityResolution(**d)


# ── write path (I1) ───────────────────────────────────────────────────────────
def save_resolution(res: AmbiguityResolution) -> AmbiguityResolution:
    """Crystallize a resolution (idempotent by natural key). A re-resolution of the same
    dimension updates the same row and **only overwrites the reading if it arrives with >=
    authority** (override-wins: verdict > user > probe) — so a probe never clobbers a human
    decision. created_at + use_count are preserved across updates."""
    res.subject_fingerprint = res.subject_fingerprint or _fingerprint(res.subject)
    res.id = res.id or res.natural_key()
    res.created_at = res.created_at or _now()
    with _LOCK:
        c = _conn()
        try:
            existing = c.execute(
                "SELECT resolution_source, created_at, use_count FROM ambiguity_resolutions WHERE id=?",
                (res.id,)).fetchone()
            if existing is not None:
                old_rank = _SOURCE_RANK.get(existing["resolution_source"], 0)
                new_rank = _SOURCE_RANK.get(res.resolution_source, 0)
                if new_rank < old_rank:
                    # lower-authority re-resolution: keep the record as-is (don't downgrade)
                    return _row_to_res(c.execute(
                        "SELECT * FROM ambiguity_resolutions WHERE id=?", (res.id,)).fetchone())
                res.created_at = existing["created_at"]
                res.use_count = existing["use_count"]
            c.execute(
                """INSERT OR REPLACE INTO ambiguity_resolutions
                   (id, org_id, connection_id, schema_scope, dim_kind, dim_facet, subject,
                    subject_fingerprint, readings, resolved_reading, resolved_sql,
                    resolution_source, evidence, created_at, last_used_at, use_count)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (res.id, res.org_id, res.connection_id, res.schema_scope, res.dim_kind,
                 res.dim_facet, res.subject, res.subject_fingerprint,
                 json.dumps([r.model_dump() for r in res.readings]), res.resolved_reading,
                 res.resolved_sql, res.resolution_source, res.evidence, res.created_at,
                 res.last_used_at, res.use_count),
            )
            c.commit()
        finally:
            c.close()
    _bump(f"ambiguity_ledger.resolved.{res.resolution_source}")
    return res


def crystallize_user_choice(connection_id: str, subject: str, reading: str, *,
                            org_id: str = "", clarify_source: str = "", resolved_sql: str = "",
                            readings: Optional[list] = None) -> Optional[AmbiguityResolution]:
    """I4 — the user answered a clarify by choosing a reading; crystallize it (source=user, the
    highest autonomous authority — only a reviewer verdict outranks it). The chosen reading is a
    valuable authoritative prior even without SQL, so `resolved_sql` is optional. Returns None on
    empty input (no-op). `clarify_source` maps the clarify kind to the taxonomy so a term choice
    ('urgent' → a status) records as AmbiValue and an interpretation choice as AmbiIntent."""
    if not (connection_id and (subject or "").strip() and (reading or "").strip()):
        return None
    kind, facet = (("AmbiValue", "literal") if clarify_source == "ambiguous_term"
                   else ("AmbiIntent", "grain"))
    return save_resolution(AmbiguityResolution(
        connection_id=connection_id, org_id=org_id, dim_kind=kind, dim_facet=facet,
        subject=subject, readings=readings or [], resolved_reading=reading,
        resolved_sql=resolved_sql, resolution_source="user",
        evidence="the user chose this reading when asked to clarify"))


def crystallize_verdict(connection_id: str, subject: str, *, org_id: str = "",
                        corrected_sql: str = "", note: str = "") -> Optional[AmbiguityResolution]:
    """A reviewer's verdict is the HIGHEST authority — it overrides any probe/user resolution on
    the same dimension (override-wins) and outsorts them in retrieval. Crystallizes the reviewer's
    correction as the settled reading for the judged question. Returns None on empty input."""
    if not (connection_id and (subject or "").strip()):
        return None
    return save_resolution(AmbiguityResolution(
        connection_id=connection_id, org_id=org_id, dim_kind="AmbiIntent", dim_facet="grain",
        subject=subject, resolved_reading=((note or "").strip() or "reviewer-corrected reading"),
        resolved_sql=corrected_sql, resolution_source="verdict",
        evidence=((note or "").strip() or "a reviewer corrected an earlier answer")))


# ── read path (I1) ────────────────────────────────────────────────────────────
def retrieve_resolutions(question: str, connection_id: str, *, org_id: str = "",
                         top_k: int = 2, min_score: float = 0.34
                         ) -> list[tuple[AmbiguityResolution, float]]:
    """Resolutions on this connection whose subject overlaps the question, by token overlap
    (intersection / question-token count — the `trusted_queries` idiom). Conservative threshold
    so an unrelated question injects nothing. Newer/more-authoritative wins ties."""
    qtok = set(tokenize(question or ""))
    if not qtok:
        return []
    scored: list[tuple[AmbiguityResolution, float]] = []
    for res in list_resolutions(connection_id, org_id=org_id):
        stok = set((res.subject_fingerprint or _fingerprint(res.subject)).split())
        if not stok:
            continue
        score = len(qtok & stok) / len(qtok)
        if score >= min_score:
            scored.append((res, round(score, 3)))
    scored.sort(key=lambda x: (x[1], _SOURCE_RANK.get(x[0].resolution_source, 0),
                               x[0].created_at), reverse=True)
    return scored[:top_k]


def build_resolution_block(matches: list[tuple[AmbiguityResolution, float]]) -> str:
    """Authoritative prompt section: this connection already RESOLVED this ambiguity — follow the
    resolved reading. Stronger than an example; it is a prior recorded from probe/user/verdict."""
    if not matches:
        return ""
    lines = [
        "RESOLVED AMBIGUITIES (settled earlier on THIS database — treat as authoritative; do NOT "
        "re-interpret these, apply the resolved reading exactly):",
    ]
    for res, _score in matches:
        src = {"probe": "a live probe", "user": "the user", "verdict": "a reviewer"}.get(
            res.resolution_source, res.resolution_source)
        lines.append(f'\n-- "{res.subject}" → {res.resolved_reading}  (resolved by {src})')
        if res.resolved_sql:
            lines.append(f"   canonical: {res.resolved_sql.strip()}")
        if res.evidence:
            lines.append(f"   because: {res.evidence.strip()[:200]}")
    lines.append("")
    return "\n".join(lines)


def record_hit(res_id: str) -> None:
    """Count a ledger-served resolution (the burn-down metric's numerator)."""
    with _LOCK:
        c = _conn()
        try:
            c.execute("UPDATE ambiguity_resolutions SET use_count = use_count + 1, "
                      "last_used_at = ? WHERE id = ?", (_now(), res_id))
            c.commit()
        finally:
            c.close()
    _bump("ambiguity_ledger.served")


# ── introspection / lifecycle ─────────────────────────────────────────────────
def list_resolutions(connection_id: str = "", org_id: str = "") -> list[AmbiguityResolution]:
    with _LOCK:
        c = _conn()
        try:
            q = "SELECT * FROM ambiguity_resolutions"
            args: tuple = ()
            clauses = []
            if connection_id:
                clauses.append("connection_id = ?"); args += (connection_id,)
            if org_id:
                clauses.append("org_id = ?"); args += (org_id,)
            if clauses:
                q += " WHERE " + " AND ".join(clauses)
            q += " ORDER BY created_at DESC"
            return [_row_to_res(r) for r in c.execute(q, args).fetchall()]
        finally:
            c.close()


def ledger_stats(connection_id: str = "", org_id: str = "") -> dict:
    """The moat metric: per connection, resolutions crystallized by source + total times served
    from the ledger. Served should grow while fresh probes/asks shrink — ambiguity burn-down."""
    rows = list_resolutions(connection_id, org_id=org_id)
    by_source: dict[str, int] = {}
    for r in rows:
        by_source[r.resolution_source] = by_source.get(r.resolution_source, 0) + 1
    return {
        "resolutions": len(rows),
        "by_source": by_source,
        "served_total": sum(r.use_count for r in rows),
    }


def purge_connections(connection_ids: list[str], org_id: Optional[str] = None) -> int:
    """Catalog-delete cascade — drop every resolution for the given connections. Returns the
    rows removed (observable, per the purge-hook contract)."""
    if not connection_ids:
        return 0
    placeholders = ",".join("?" for _ in connection_ids)
    with _LOCK:
        c = _conn()
        try:
            sql = f"DELETE FROM ambiguity_resolutions WHERE connection_id IN ({placeholders})"
            args = list(connection_ids)
            if org_id is not None:
                sql += " AND org_id = ?"; args.append(org_id)
            n = c.execute(sql, args).rowcount
            c.commit()
            return n
        finally:
            c.close()


def _bump(counter: str) -> None:
    try:
        from aughor.stats import stats
        stats.inc(counter)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "ledger telemetry bump is best-effort", counter="ambiguity_ledger.bump_fail")
