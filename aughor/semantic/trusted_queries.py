"""Trusted query templates — curated, data-team-reviewed SQL patterns.

A "trusted assets" store (see docs/PALANTIR_FOUNDRY_STUDY_2026-07-22.md): a small set of
KNOWN-CORRECT queries for a connection. When a user's question matches one, the verified pattern
is injected AUTHORITATIVELY into the prompt ("reuse this exact join/aggregation
structure"), and the answer can be marked Verified. This bypasses model-reasoning
gaps that prompt rules can't fix — most importantly multi-fact FAN-OUT (the model
resists the "pre-aggregate then join" rule during generation but adapts a concrete
verified example correctly).

Distinct from `prior_analyses.search_sql_examples` (auto-collected soft few-shots):
these are deliberately curated, authoritative, and provenance-marked.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field

_DEFAULT_PATH = Path(__file__).parent.parent.parent / "data" / "trusted_queries.json"


def _path() -> Path:
    """The vetted-query file, honouring ``AUGHOR_TRUSTED_QUERIES_PATH``.

    DS-12 — added when the automations plane started READING this store, because until
    then it was the last authored file here with a hardcoded path: a test that saved a
    trusted query wrote to the live ``data/trusted_queries.json``. Same non-hermeticity
    class as the glossary and the metrics catalog, both of which this repo already fixed
    after a suite run destroyed real content. Resolved per call, like the metrics
    catalog, so it always reflects the current env rather than the one at import.
    """
    from aughor.db.sqlite_util import resolve_db_path
    return resolve_db_path("AUGHOR_TRUSTED_QUERIES_PATH", _DEFAULT_PATH)

# Generic words that shouldn't drive matching.
_STOP = frozenset({
    "the", "a", "an", "of", "for", "and", "or", "to", "in", "on", "by", "per",
    "each", "what", "which", "how", "many", "is", "are", "was", "were", "do",
    "does", "show", "list", "give", "me", "their", "its", "with", "that", "this",
})


class TrustedQuery(BaseModel):
    id: str
    connection_id: str
    question: str                       # canonical question / intent it answers
    sql: str                            # verified-correct DuckDB SQL
    tables: list[str] = Field(default_factory=list)
    note: str = ""                      # what pattern/pitfall it demonstrates
    tags: list[str] = Field(default_factory=list)
    # ── KI-0 (§3.10) — governance + provenance ──────────────────────────────────
    # Lifecycle rides the metric state machine (semantic/governance.py):
    # draft → proposed → approved (→ deprecated). ONLY `approved` reaches a prompt —
    # `list_trusted` filters by default, so every authoritative consumer fails closed.
    # A record with NO status key predates KI-0 and loads as approved (it was being
    # injected before statuses existed; grandfathering preserves that behaviour).
    status: str = "draft"
    version: int = 0                    # bumped by each approve
    source: str = ""                    # api | eval_promotion | divergence_review | legacy
    proposed_by: str = ""
    proposed_at: str = ""
    # The human (or eval suite) whose approval made this authoritative, and when —
    # the VERIFIED_AT/VERIFIED_BY the Snowflake study flagged this store as missing.
    verified_by: str = ""
    verified_at: str = ""
    last_executed_at: str = ""          # when verification last ran the SQL for real
    verification: dict = Field(default_factory=dict)  # last verification report


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9_]+", (text or "").lower())
            if t not in _STOP and len(t) > 2}


def _load_raw() -> list[dict]:
    if not _path().exists():
        return []
    try:
        return json.loads(_path().read_text()) or []
    except Exception:
        return []


def list_trusted(connection_id: str = "", *,
                 include_unapproved: bool = False) -> list[TrustedQuery]:
    """Trusted queries for a connection — APPROVED ONLY by default.

    KI-0: the default is the authoritative view, because every consumer that treats an
    entry as trusted (prompt injection, the MCP listing, the automations component)
    calls this and must fail closed against drafts. The two callers that genuinely
    need the whole store — the inspection endpoint and the eval-promotion dedupe —
    pass ``include_unapproved=True`` explicitly.
    """
    out = []
    for d in _load_raw():
        if "status" not in d:
            # Pre-KI-0 record: it was injected before statuses existed, so it loads
            # as approved rather than silently vanishing from every prompt.
            d = {**d, "status": "approved", "source": d.get("source") or "legacy"}
        try:
            tq = TrustedQuery(**d)
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "skip a malformed trusted-query record; the rest still load", counter="trusted_queries.parse")
            continue
        if not include_unapproved and tq.status != "approved":
            continue
        if not connection_id or tq.connection_id == connection_id:
            out.append(tq)
    return out


def get_trusted(tq_id: str) -> TrustedQuery | None:
    """One record by id, whatever its status — the write endpoints' lookup."""
    for tq in list_trusted(include_unapproved=True):
        if tq.id == tq_id:
            return tq
    return None


def save_trusted(tq: TrustedQuery) -> None:
    raw = [d for d in _load_raw() if d.get("id") != tq.id]
    raw.append(tq.model_dump())
    _path().parent.mkdir(parents=True, exist_ok=True)
    tmp = _path().with_suffix(".tmp")
    tmp.write_text(json.dumps(raw, indent=2))
    tmp.replace(_path())


def delete_trusted(tq_id: str) -> bool:
    raw = _load_raw()
    kept = [d for d in raw if d.get("id") != tq_id]
    if len(kept) == len(raw):
        return False
    _path().write_text(json.dumps(kept, indent=2))
    return True


def retrieve_trusted(question: str, connection_id: str, top_k: int = 2,
                     min_score: float = 0.18) -> list[tuple[TrustedQuery, float]]:
    """Top trusted queries whose question overlaps the user's, by token-overlap
    score (intersection / query-token count). Conservative threshold so an
    unrelated question injects nothing."""
    qtok = _tokens(question)
    if not qtok:
        return []
    scored = []
    for tq in list_trusted(connection_id):
        ttok = _tokens(tq.question) | {t for tag in tq.tags for t in _tokens(tag)}
        if not ttok:
            continue
        score = len(qtok & ttok) / len(qtok)
        if score >= min_score:
            scored.append((tq, round(score, 3)))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def build_trusted_block(matches: list[tuple[TrustedQuery, float]]) -> str:
    """Authoritative prompt section. Stronger than soft examples: the model is
    told these are verified and to reuse the exact structure.

    The header states the WEAKEST warrant present, not the strongest. Entries minted
    from eval runs (Wave L5) are *consistency*-verified — they reproduce an answer this
    connection already gave — which is real evidence and is not the same as a human
    having checked the result is true. Claiming "KNOWN-CORRECT" over a set that
    contains one of those would launder the weaker warrant into the stronger one, in a
    prompt whose entire job is to be believed.
    """
    if not matches:
        return ""
    from aughor.evals.promote_trusted import SOURCE_TAG

    any_eval_sourced = any(SOURCE_TAG in (tq.tags or []) for tq, _ in matches)
    warrant = (
        "reviewed or eval-verified; the per-pattern note says which"
        if any_eval_sourced else "data-team reviewed, KNOWN-CORRECT for this database"
    )
    lines = [
        f"VERIFIED QUERY PATTERNS ({warrant}). "
        "When the user's question matches one of these, REUSE its exact join and aggregation "
        "structure — adapt only the filters, columns, or grouping the question actually changes. "
        "These patterns avoid common errors (fan-out row multiplication, wrong grain):",
    ]
    for i, (tq, _score) in enumerate(matches, 1):
        lines.append(f"\n-- Verified pattern {i}" + (f" — {tq.note}" if tq.note else ""))
        lines.append(f"Q: {tq.question}\nSQL:\n{tq.sql.strip()}")
    lines.append("")
    return "\n".join(lines)
