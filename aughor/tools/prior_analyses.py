"""Index and search past investigations via Qdrant semantic search.

Called in two places:
  - aughor.db.history.complete_investigation() — indexes each finished investigation
  - aughor.agent.nodes.decompose_question() — retrieves relevant past findings

Disable via: AUGHOR_PRIOR_ANALYSES=false
"""
from __future__ import annotations

import hashlib
import os
import re

INVESTIGATIONS_COLLECTION = "aughor_investigations"
SQL_EXAMPLES_COLLECTION   = "aughor_sql_examples"
_ENABLED = os.getenv("AUGHOR_PRIOR_ANALYSES", "true").lower() != "false"
_MIN_SCORE = 0.65       # minimum score for context injection
_CACHE_SCORE = 0.88     # minimum score to short-circuit and return prior result directly


# ── Temporal entity guard ─────────────────────────────────────────────────────
# Prevents returning a cached investigation about January when the user asked
# about February, or a Q3 investigation when the question concerns Q1.

_MONTH_RE = re.compile(
    r'\b(january|february|march|april|may|june|july|august|september|october|november|december'
    r'|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\b'
    r'[\s\-]?(\d{4})?',
    re.IGNORECASE,
)
_QUARTER_RE = re.compile(r'\b(q[1-4])\s*(\d{4})?\b', re.IGNORECASE)
_YEAR_RE    = re.compile(r'\b(20\d{2})\b')


def _temporal_tokens(text: str) -> set[str]:
    """Extract normalised temporal tokens (month abbreviations, quarters, years)."""
    tokens: set[str] = set()
    for m in _MONTH_RE.finditer(text):
        tokens.add(m.group(1).lower()[:3])          # "feb", "jan", …
        if m.group(2):
            tokens.add(m.group(2))                   # year alongside month
    for m in _QUARTER_RE.finditer(text):
        tokens.add(m.group(1).lower())               # "q1", "q3", …
        if m.group(2):
            tokens.add(m.group(2))
    for m in _YEAR_RE.finditer(text):
        tokens.add(m.group(1))
    return tokens


def _temporal_compatible(q_new: str, q_cached: str) -> bool:
    """
    Return False when both questions reference specific time periods that don't overlap.
    If either question has no temporal tokens, we assume compatible (conservative).
    """
    t_new    = _temporal_tokens(q_new)
    t_cached = _temporal_tokens(q_cached)
    if not t_new or not t_cached:
        return True
    return bool(t_new & t_cached)


# ── Indexing ──────────────────────────────────────────────────────────────────

def index_investigation(
    inv_id: str,
    question: str,
    headline: str,
    key_findings: list[str],
    connection_id: str = "",
) -> None:
    """Embed and upsert one completed investigation. Best-effort — never raises."""
    if not _ENABLED:
        return
    try:
        _index(inv_id, question, headline, key_findings, connection_id)
    except Exception:
        pass


def _index(inv_id: str, question: str, headline: str, key_findings: list[str], connection_id: str) -> None:
    from aughor.semantic.embedder import embed_one
    from aughor.semantic.vector_store import ensure_collection, upsert

    # Embed a rich summary so the search surface covers multiple angles
    text = "\n".join([question, headline] + key_findings[:5])
    vector = embed_one(text)

    ensure_collection(INVESTIGATIONS_COLLECTION)
    upsert(INVESTIGATIONS_COLLECTION, [{
        "id": inv_id,
        "vector": vector,
        "payload": {
            "inv_id": inv_id,
            "question": question,
            "headline": headline,
            "key_findings": key_findings[:5],
            "connection_id": connection_id,
        },
    }])


# ── Cache hit check ──────────────────────────────────────────────────────────

def find_similar_investigation(question: str, connection_id: str = "") -> tuple[str, float] | None:
    """
    Return (inv_id, score) if a past investigation is similar enough to short-circuit.
    Returns None if Qdrant is unavailable, disabled, or no hit above _CACHE_SCORE.
    Scoped to connection_id when provided — same question on a different DB won't match.
    """
    if not _ENABLED:
        return None
    try:
        return _find_similar(question, connection_id)
    except Exception:
        return None


def _find_similar(question: str, connection_id: str) -> tuple[str, float] | None:
    from aughor.semantic.embedder import embed_one
    from aughor.semantic.vector_store import search

    vector = embed_one(question)
    query_filter = _connection_filter(connection_id)
    # Fetch a few candidates so we can apply the temporal guard and still find a hit
    hits = search(INVESTIGATIONS_COLLECTION, vector, top_k=3, query_filter=query_filter)
    if not hits:
        return None
    for hit in hits:
        if hit["score"] < _CACHE_SCORE:
            break  # sorted descending — no point checking further
        cached_q = hit["payload"].get("question", "")
        if not _temporal_compatible(question, cached_q):
            continue  # period mismatch — skip this candidate
        return hit["payload"]["inv_id"], hit["score"]
    return None


# ── Search ────────────────────────────────────────────────────────────────────

def search_prior_investigations(question: str, connection_id: str = "", top_k: int = 3) -> list[str]:
    """
    Return formatted summaries of past investigations relevant to the current question.
    Scoped to connection_id when provided.
    Returns an empty list if none found, score too low, or Qdrant is unavailable.
    """
    if not _ENABLED:
        return []
    try:
        return _search(question, connection_id, top_k)
    except Exception:
        return []


def _search(question: str, connection_id: str, top_k: int) -> list[str]:
    from aughor.semantic.embedder import embed_one
    from aughor.semantic.vector_store import search

    vector = embed_one(question)
    query_filter = _connection_filter(connection_id)
    hits = search(INVESTIGATIONS_COLLECTION, vector, top_k=top_k, query_filter=query_filter)

    results: list[str] = []
    for hit in hits:
        if hit["score"] < _MIN_SCORE:
            continue
        p = hit["payload"]
        findings_lines = "\n".join(f"  - {f}" for f in p.get("key_findings") or [])
        summary = f"Q: {p['question']}\nConclusion: {p['headline']}"
        if findings_lines:
            summary += f"\nKey findings:\n{findings_lines}"
        results.append(summary)

    return results


# ── SQL examples — (question, SQL) pairs from successful past executions ──────

_SQL_EXAMPLES_MIN_SCORE = 0.70
_SQL_EXAMPLES_MIN_ROWS  = 1   # must have returned at least one row to be useful


def index_sql_examples(
    inv_id: str,
    question: str,
    query_history: list,
    connection_id: str = "",
) -> None:
    """Index every successful QueryResult from an investigation as a few-shot SQL example.

    Only rows where error is None/empty AND row_count >= 1 are indexed — the
    caller's guarantee that these executed cleanly and returned real data.
    """
    if not _ENABLED:
        return
    try:
        _index_sql_examples(inv_id, question, query_history, connection_id)
    except Exception:
        pass


def _index_sql_examples(inv_id: str, question: str, query_history: list, connection_id: str) -> None:
    from aughor.semantic.embedder import embed_one
    from aughor.semantic.vector_store import ensure_collection, upsert

    ensure_collection(SQL_EXAMPLES_COLLECTION)

    points: list[dict] = []
    for qr in query_history:
        # Support both QueryResult objects and plain dicts (from JSON-deserialised history)
        if hasattr(qr, "error"):
            error    = qr.error
            sql      = qr.sql
            row_count = qr.row_count
            columns  = qr.columns
        else:
            error    = qr.get("error")
            sql      = qr.get("sql", "")
            row_count = qr.get("row_count", 0)
            columns  = qr.get("columns", [])

        # Only index clean, non-empty results
        if error or not sql or (row_count or 0) < _SQL_EXAMPLES_MIN_ROWS:
            continue

        # Stable ID — same question+sql on the same connection always overwrites
        uid = hashlib.sha1(
            f"{connection_id}:{question}:{sql}".encode()
        ).hexdigest()

        # Embed question + sql together so retrieval is sensitive to both intent and pattern
        vector = embed_one(f"{question}\n{sql}")

        points.append({
            "id": uid,
            "vector": vector,
            "payload": {
                "inv_id": inv_id,
                "question": question,
                "sql": sql,
                "columns": columns,
                "row_count": row_count,
                "connection_id": connection_id,
            },
        })

    if points:
        upsert(SQL_EXAMPLES_COLLECTION, points)


def search_sql_examples(
    question: str,
    connection_id: str = "",
    top_k: int = 3,
) -> str:
    """Return a formatted few-shot block of validated SQL examples for this question.

    Returns an empty string when Qdrant is unavailable, disabled, or no match
    above the score threshold — safe to inject directly into any prompt.
    """
    if not _ENABLED:
        return ""
    try:
        return _search_sql_examples(question, connection_id, top_k)
    except Exception:
        return ""


def _search_sql_examples(question: str, connection_id: str, top_k: int) -> str:
    from aughor.semantic.embedder import embed_one
    from aughor.semantic.vector_store import search

    vector = embed_one(question)
    query_filter = _connection_filter(connection_id)
    hits = search(SQL_EXAMPLES_COLLECTION, vector, top_k=top_k, query_filter=query_filter)

    examples: list[str] = []
    for hit in hits:
        if hit["score"] < _SQL_EXAMPLES_MIN_SCORE:
            continue
        p = hit["payload"]
        examples.append(
            f"Q: {p['question']}\nSQL:\n{p['sql']}"
        )

    if not examples:
        return ""

    lines = ["SCHEMA-SPECIFIC SQL EXAMPLES (previously validated on this database — follow their table/column naming and join style):"]
    for i, ex in enumerate(examples, 1):
        lines.append(f"\n-- Example {i}\n{ex}")
    lines.append("")
    return "\n".join(lines)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _connection_filter(connection_id: str):
    """Build a Qdrant FieldCondition filter for connection_id, or None if empty."""
    if not connection_id:
        return None
    from qdrant_client.models import Filter, FieldCondition, MatchValue
    return Filter(
        must=[FieldCondition(key="connection_id", match=MatchValue(value=connection_id))]
    )
