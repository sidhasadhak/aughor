"""Index and search past investigations — and the few-shot SQL memory — via semantic search.

Written from:
  - the ``investigation_index`` ingestion sink (agent/bootstrap.py) when a deep run completes;
  - :func:`index_answer` when a quick answer's envelope is filed (routers/investigations.py ``_fold_envelope``).
Read from:
  - aughor.agent.nodes — past findings for planning, examples for each hypothesis's SQL;
  - the quick path's ``_sqlex`` and the grounding receipt — examples for the question's SQL.

PENDING item 24 (the ML review's point 2, at answer time): this memory is the self-improving loop that exists without
training, and it learned from almost nothing — only deep runs wrote to it, never a quick answer or a chat turn; a
query a person rejected stayed an example forever; nothing checked the guards before a query was remembered; every
deep sub-query was filed under the top-level question although the SQL writer searches it by hypothesis; deleting
an investigation left its SQL examples behind; and a dead vector store or embedder was indistinguishable from "no
similar question was ever asked". Now every clean answer is remembered, the verdict store is the tombstone every
write and read checks (:func:`aughor.feedback.verdicts.overruled`), and an unreachable memory is said.

Disable via: AUGHOR_PRIOR_ANALYSES=false
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import time

logger = logging.getLogger(__name__)

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


# ── Saying so — an unreachable memory is never "nothing similar" ──────────────

_LAST_SAID: dict[str, float] = {}
_SAY_EVERY_S = 60.0


def _said(exc: BaseException, what: str, counter: str) -> str:
    """Count every time the memory could not be reached, log it (and journal it) at most once a minute per kind, and
    return the reason a reader can be shown. Once a minute because a dead embedder fails EVERY answer: a warning per
    answer would drown the log it is meant to be read in."""
    now = time.monotonic()
    if now - _LAST_SAID.get(counter, float("-inf")) >= _SAY_EVERY_S:
        _LAST_SAID[counter] = now
        from aughor.kernel.errors import tolerate
        tolerate(exc, f"few-shot memory: {what}", counter=counter)
    else:
        try:
            from aughor.stats import stats
            stats.inc(f"tolerated.{counter}")
        except Exception:  # noqa: BLE001 — counting must never cost the answer
            pass
    return str(exc) if isinstance(exc, _Unreachable) else f"the vector store did not answer ({type(exc).__name__})"


class _Unreachable(RuntimeError):
    """The memory could not be written or read: no backend, or it did not answer."""


def _backend_or_raise() -> None:
    from aughor.semantic.vector_store import available
    if not available():
        raise _Unreachable("no vector store is configured on this deployment")


def _embed(texts: list[str]) -> list[list[float]]:
    from aughor.semantic.embedder import embed
    try:
        return embed(texts)
    except Exception as exc:  # noqa: BLE001 — re-raised as what the reader needs to know
        raise _Unreachable(f"the embedding service did not answer: {type(exc).__name__}") from exc


# ── The tombstone ─────────────────────────────────────────────────────────────

def _overruled(connection_id: str = "") -> tuple[set[str], set[str]]:
    """The answers a person overruled and the SQL they ran (`verdicts.overruled`). Raises when the verdict store cannot
    be read: every caller fails CLOSED — memory that cannot be checked is not written or served."""
    from aughor.feedback.verdicts import overruled
    return overruled(connection_id)


def _sql_key(sql: str) -> str:
    from aughor.feedback.verdicts import sql_key
    return sql_key(sql)


def forget_answer(inv_id: str) -> int:
    """Evict one answer from memory — its investigation entry and every SQL example it taught. Called when a person
    rejects or corrects it and when it is deleted. Returns the points removed; never raises (the verdict is the
    authority either way — see :func:`aughor.feedback.verdicts.overruled`)."""
    if not inv_id:
        return 0
    try:
        from aughor.semantic.vector_store import available, delete_by_filter, match_filter
        if not available():
            return 0
        filt = match_filter("inv_id", inv_id)
        return sum(delete_by_filter(c, filt) or 0 for c in (INVESTIGATIONS_COLLECTION, SQL_EXAMPLES_COLLECTION))
    except Exception as exc:  # noqa: BLE001
        _said(exc, "an overruled answer could not be evicted; searches still refuse it",
              "prior_analyses.forget_failed")
        return 0


# ── Indexing ──────────────────────────────────────────────────────────────────

def index_investigation(
    inv_id: str,
    question: str,
    headline: str,
    key_findings: list[str],
    connection_id: str = "",
) -> None:
    """Embed and upsert one completed investigation. Best-effort — never raises; an overruled one is not written
    (the reindex endpoint and every backfill go through here, so an evicted investigation cannot come back)."""
    if not _ENABLED:
        return
    try:
        if inv_id in _overruled()[0]:
            return
        _index(inv_id, question, headline, key_findings, connection_id)
    except Exception as exc:  # noqa: BLE001
        _said(exc, "a finished investigation was not remembered", "prior_analyses.index_failed")


def _index(inv_id: str, question: str, headline: str, key_findings: list[str], connection_id: str) -> None:
    from aughor.semantic.vector_store import ensure_collection, upsert

    _backend_or_raise()
    # Embed a rich summary so the search surface covers multiple angles
    text = "\n".join([question, headline] + key_findings[:5])
    vector = _embed([text])[0]

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
    An investigation a person has since rejected or corrected is never served as a cached answer.
    """
    if not _ENABLED:
        return None
    try:
        return _find_similar(question, connection_id)
    except Exception as exc:  # noqa: BLE001 — a miss, said: the run investigates afresh
        _said(exc, "the investigation cache was not searched", "prior_analyses.search_failed")
        return None


def _find_similar(question: str, connection_id: str) -> tuple[str, float] | None:
    from aughor.semantic.vector_store import search

    _backend_or_raise()
    vector = _embed([question])[0]
    query_filter = _connection_filter(connection_id)
    # Fetch a few candidates so we can apply the temporal guard and still find a hit
    hits = search(INVESTIGATIONS_COLLECTION, vector, top_k=3, query_filter=query_filter)
    if not hits:
        return None
    overruled = _overruled(connection_id)[0]
    for hit in hits:
        if hit["score"] < _CACHE_SCORE:
            break  # sorted descending — no point checking further
        if hit["payload"].get("inv_id") in overruled:
            continue  # a person said this one was wrong
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
    Returns an empty list if none found, score too low, or the memory is unreachable (said, and counted).
    """
    if not _ENABLED:
        return []
    try:
        return _search(question, connection_id, top_k)
    except Exception as exc:  # noqa: BLE001
        _said(exc, "past findings were not searched", "prior_analyses.search_failed")
        return []


def _search(question: str, connection_id: str, top_k: int) -> list[str]:
    from aughor.semantic.vector_store import search

    _backend_or_raise()
    vector = _embed([question])[0]
    query_filter = _connection_filter(connection_id)
    hits = search(INVESTIGATIONS_COLLECTION, vector, top_k=top_k * 3, query_filter=query_filter)
    overruled = _overruled(connection_id)[0]

    results: list[str] = []
    for hit in hits:
        if hit["score"] < _MIN_SCORE or hit["payload"].get("inv_id") in overruled:
            continue
        p = hit["payload"]
        findings_lines = "\n".join(f"  - {f}" for f in p.get("key_findings") or [])
        summary = f"Q: {p['question']}\nConclusion: {p['headline']}"
        if findings_lines:
            summary += f"\nKey findings:\n{findings_lines}"
        results.append(summary)
        if len(results) == top_k:
            break

    return results


# ── SQL examples — (question, SQL) pairs from successful past executions ──────

_SQL_EXAMPLES_MIN_SCORE = 0.70
_SQL_EXAMPLES_MIN_ROWS  = 1   # must have returned at least one row to be useful


def index_sql_examples(
    inv_id: str,
    question: str,
    query_history: list,
    connection_id: str = "",
    *,
    hypotheses: list | None = None,
) -> None:
    """Index every clean QueryResult from a run as a few-shot SQL example. Never raises.

    Clean means: no error, at least one row, and no guard caveat on the result (a query a guard flagged but could
    not repair is not an example to copy). Nothing is written for an answer a person has overruled, nor a query
    they overruled on this connection. A result that belongs to a hypothesis is filed under that hypothesis's text —
    the question its SQL answered, and what the SQL writer searches by — with the run's question kept beside it.
    """
    if not _ENABLED:
        return
    try:
        _index_sql_examples(inv_id, question, query_history, connection_id, hypotheses or [])
    except Exception as exc:  # noqa: BLE001
        _said(exc, "a run's SQL was not remembered as examples", "prior_analyses.index_failed")


def _field(obj, name: str, default=None):
    return getattr(obj, name, default) if not isinstance(obj, dict) else obj.get(name, default)


def _index_sql_examples(inv_id: str, question: str, query_history: list, connection_id: str,
                        hypotheses: list) -> int:
    """The examples written — 0 when none was clean, or the answer or its query was overruled."""
    from aughor.semantic.vector_store import ensure_collection, upsert

    answers, queries = _overruled(connection_id)
    if inv_id in answers:
        return 0
    by_hypothesis = {str(_field(h, "id", "")): str(_field(h, "description", "") or "")
                     for h in hypotheses if _field(h, "id")}

    examples: list[tuple[str, str, list, int]] = []
    for qr in query_history:
        error, sql = _field(qr, "error"), str(_field(qr, "sql", "") or "")
        row_count, columns = _field(qr, "row_count", 0) or 0, _field(qr, "columns", []) or []
        # Only clean, non-empty results — and none a guard flagged or a person overruled
        if (error or not sql.strip() or row_count < _SQL_EXAMPLES_MIN_ROWS or _field(qr, "caveats")
                or _sql_key(sql) in queries):
            continue
        asked = by_hypothesis.get(str(_field(qr, "hypothesis_id", "") or "")) or question
        examples.append((asked, sql, columns, row_count))
    if not examples:
        return 0

    _backend_or_raise()
    # Embed question + sql together so retrieval is sensitive to both intent and pattern
    vectors = _embed([f"{asked}\n{sql}" for asked, sql, _, _ in examples])
    ensure_collection(SQL_EXAMPLES_COLLECTION)
    upsert(SQL_EXAMPLES_COLLECTION, [{
        # Stable ID — same question+sql on the same connection always overwrites
        "id": hashlib.sha1(f"{connection_id}:{asked}:{sql}".encode()).hexdigest(),
        "vector": vector,
        "payload": {
            "inv_id": inv_id,
            "question": asked,
            "asked": question,
            "sql": sql,
            "columns": columns,
            "row_count": row_count,
            "connection_id": connection_id,
        },
    } for (asked, sql, columns, row_count), vector in zip(examples, vectors)])
    return len(examples)


def index_answer(inv_id: str) -> bool:
    """Remember a QUICK answer's SQL as a few-shot example, once its envelope is filed (PENDING item 24). True when
    it was remembered.

    Only deep runs fed this memory, so the answers most people get — the quick path's, the chat's — taught it nothing.
    An answer is remembered when it asked a question that stands alone (a follow-up such as "now break that down"
    does not), its query ran and returned rows, and its guards were clean (`answer.envelope.guards_clean` — the one
    definition the training corpus's bronze tier reads too). Examples only, never the investigation cache: a quick
    answer is not an investigation, and must not short-circuit one."""
    if not _ENABLED or not inv_id:
        return False
    try:
        from aughor.agent.followup import is_followup
        from aughor.answer.envelope import guards_clean
        from aughor.db.history import get_chat_answer
        answer = get_chat_answer(inv_id)
        if not answer:
            return False
        report = answer.get("report") or {}
        question, sql = str(answer.get("question") or "").strip(), str(report.get("sql") or "").strip()
        rows = report.get("rows") or []
        if not (question and sql and rows) or is_followup(question) or not guards_clean(report.get("envelope")):
            return False
        return _index_sql_examples(inv_id, question, [{"sql": sql, "row_count": len(rows),
                                                       "columns": report.get("columns") or []}],
                                   str(answer.get("connection_id") or ""), []) > 0
    except Exception as exc:  # noqa: BLE001
        _said(exc, "a quick answer was not remembered as an example", "prior_analyses.index_failed")
        return False


def search_sql_examples(
    question: str,
    connection_id: str = "",
    top_k: int = 3,
) -> str:
    """Return a formatted few-shot block of validated SQL examples for this question.

    Returns an empty string when the memory is disabled, unreachable, or has no match above the score threshold —
    safe to inject directly into any prompt. Unreachable is SAID, though never into the prompt: counted, logged, and
    shown on the grounding receipt (:func:`search_sql_examples_checked`)."""
    return search_sql_examples_checked(question, connection_id, top_k)[0]


def search_sql_examples_checked(question: str, connection_id: str = "", top_k: int = 3) -> tuple[str, str]:
    """``(block, note)``: the few-shot block, and — when the memory could not be searched — why, for a reader.

    ``note`` is "" when the search ran, hits or not: an empty block then means nothing similar was remembered, and
    only then."""
    if not _ENABLED:
        return "", "the few-shot memory is switched off (AUGHOR_PRIOR_ANALYSES=false)"
    try:
        return _search_sql_examples(question, connection_id, top_k), ""
    except Exception as exc:  # noqa: BLE001
        return "", "past SQL was not searched: " + _said(exc, "past SQL was not searched",
                                                         "prior_analyses.search_failed")


def _search_sql_examples(question: str, connection_id: str, top_k: int) -> str:
    from aughor.semantic.vector_store import search

    _backend_or_raise()
    vector = _embed([question])[0]
    query_filter = _connection_filter(connection_id)
    # Over-fetch: the tombstone below may refuse some of the nearest
    hits = search(SQL_EXAMPLES_COLLECTION, vector, top_k=max(top_k * 3, 9), query_filter=query_filter)
    answers, queries = _overruled(connection_id)

    examples: list[str] = []
    for hit in hits:
        p = hit["payload"]
        if (hit["score"] < _SQL_EXAMPLES_MIN_SCORE or p.get("inv_id") in answers
                or _sql_key(p.get("sql", "")) in queries):
            continue
        examples.append(
            f"Q: {p['question']}\nSQL:\n{p['sql']}"
        )
        if len(examples) == top_k:
            break

    if not examples:
        return ""

    lines = ["SCHEMA-SPECIFIC SQL EXAMPLES (previously validated on this database — follow their table/column naming and join style):"]
    for i, ex in enumerate(examples, 1):
        lines.append(f"\n-- Example {i}\n{ex}")
    lines.append("")
    return "\n".join(lines)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _connection_filter(connection_id: str):
    """A backend-neutral connection_id filter, or None if empty.

    Neutral (vector_store.match_filter) rather than a Qdrant model: the pgvector
    backend never installs qdrant_client, and the seam translates for whichever
    backend is active. None when no backend is available — the value is moot then:
    every caller checks the backend first (`_backend_or_raise`) and says so."""
    if not connection_id:
        return None
    from aughor.semantic.vector_store import available, match_filter
    if not available():
        return None
    return match_filter("connection_id", connection_id)
