"""
Knowledge base retriever — indexes SQL pattern and domain knowledge JSONs into
a dedicated Qdrant collection and exposes two search functions used by agent nodes.

Usage:
  At FIX_SQL time:     retrieve_for_fix_sql(error, failed_sql)  → dialect traps + correct examples
  At PLAN_QUERIES time: retrieve_for_planning(hypothesis)        → SQL + domain patterns

Graceful degradation: all failures (Qdrant down, KB path unset, embedding error)
silently return empty strings so agent nodes are never blocked.

Configure via:
  AUGHOR_KB_PATH  — absolute path to the SQL KB JSONs folder (required to activate)
  AUGHOR_KB_ENABLED — set to "false" to disable entirely (default: "true")
"""
from __future__ import annotations

import os
from pathlib import Path

# Load .env so AUGHOR_KB_PATH is available when running standalone scripts
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env")
except ImportError as exc:
    from aughor.kernel.errors import tolerate
    tolerate(exc, "python-dotenv is optional; env vars from the real environment are used when it is absent", counter="kb_retriever.dotenv")

KB_COLLECTION = "sql_knowledge_base"
KB_PATH = os.getenv("AUGHOR_KB_PATH", "")
KB_ENABLED = os.getenv("AUGHOR_KB_ENABLED", "true").lower() != "false"


# ── Index building ────────────────────────────────────────────────────────────

def build_kb_index() -> int:
    """
    Embed all KB entries and upsert to Qdrant.
    Idempotent — safe to call multiple times (upsert by stable ID).
    Returns number of points indexed, 0 on any failure.
    """
    if not KB_ENABLED or not KB_PATH:
        return 0
    try:
        return _build()
    except Exception:
        return 0


def _build() -> int:
    from aughor.semantic.kb_loader import load_kb_entries
    from aughor.semantic.embedder import embed
    from aughor.semantic.vector_store import ensure_collection, upsert

    entries = load_kb_entries(KB_PATH)
    if not entries:
        return 0

    ensure_collection(KB_COLLECTION)

    # Batch embed in chunks of 64 to stay within Ollama memory limits
    BATCH = 64
    total = 0
    for i in range(0, len(entries), BATCH):
        batch = entries[i: i + BATCH]
        texts = [e.embed_text for e in batch]
        vectors = embed(texts)
        points = [
            {
                "id": f"kb::{e.source_file}::{e.pattern_id}",
                "vector": v,
                "payload": e.payload,
            }
            for e, v in zip(batch, vectors)
        ]
        upsert(KB_COLLECTION, points)
        total += len(points)

    return total


def _ensure_indexed() -> bool:
    """Build index lazily on first use. Returns True if collection is ready."""
    try:
        from aughor.semantic.vector_store import collection_count
        if collection_count(KB_COLLECTION) == 0:
            build_kb_index()
        return True
    except Exception:
        return False


# ── Retrieval helpers ─────────────────────────────────────────────────────────

def _search(query: str, top_k: int, tier_filter: int | None = None) -> list[dict]:
    """Raw search — returns list of payload dicts. Over-fetches by vector, then HYBRID-reranks
    the pool by vector⊕BM25 (R7) so an exact-term match buried mid-pool by pure cosine is
    recovered, before filtering by tier and truncating to top_k."""
    from aughor.semantic.embedder import embed_one
    from aughor.semantic.vector_store import search
    from aughor.semantic.lexical import hybrid_rerank, payload_text
    vector = embed_one(query)
    hits = search(KB_COLLECTION, vector, top_k=top_k * 3)
    hits = hybrid_rerank(query, hits, text_of=lambda h: payload_text(h.get("payload", {})))
    results = []
    for h in hits:
        p = h["payload"]
        if tier_filter is not None and p.get("tier") != tier_filter:
            continue
        results.append(p)
        if len(results) >= top_k:
            break
    return results


# ── Public API ────────────────────────────────────────────────────────────────

def retrieve_for_fix_sql(error: str, failed_sql: str, top_k: int = 2) -> str:
    """
    Search KB for patterns relevant to a SQL error and failed query.
    Returns a formatted string ready to inject into FIX_SQL_PROMPT.
    Empty string on any failure.
    """
    if not KB_ENABLED or not KB_PATH:
        return ""
    try:
        if not _ensure_indexed():
            return ""
        # Query combines error message + a short SQL snippet for context
        query = f"{error} {failed_sql[:300]}"
        hits = _search(query, top_k=top_k)
        if not hits:
            return ""
        return _format_for_fix(hits)
    except Exception:
        return ""


def retrieve_for_planning(hypothesis: str, top_k: int = 3) -> str:
    """
    Search KB for SQL and domain patterns relevant to a hypothesis.
    Returns a formatted string ready to inject into PLAN_QUERIES_PROMPT.
    Empty string on any failure.
    """
    if not KB_ENABLED or not KB_PATH:
        return ""
    try:
        if not _ensure_indexed():
            return ""
        hits = _search(hypothesis, top_k=top_k)
        if not hits:
            return ""
        return _format_for_planning(hits)
    except Exception:
        return ""


def retrieve_for_decompose(question: str, top_k: int = 2) -> str:
    """
    Search domain knowledge patterns relevant to a business question.
    Returns a formatted string ready to inject into DECOMPOSE_PROMPT.
    Empty string on any failure.
    """
    if not KB_ENABLED or not KB_PATH:
        return ""
    try:
        if not _ensure_indexed():
            return ""
        hits = _search(question, top_k=top_k, tier_filter=2)
        if not hits:
            return ""
        return _format_for_decompose(hits)
    except Exception:
        return ""


# ── Formatters ────────────────────────────────────────────────────────────────

def _format_for_fix(hits: list[dict]) -> str:
    parts: list[str] = ["RELEVANT SQL KNOWLEDGE BASE PATTERNS (use to guide your fix):"]
    for h in hits:
        parts.append(f"\n── {h['title']} ──")
        tier = h.get("tier", 3)

        if tier == 1:
            for dt in h.get("dialect_traps", [])[:2]:
                parts.append(f"Dialect trap ({dt.get('construct', '')}):")
                pg = dt.get("postgres_behavior", "")
                alt = dt.get("safe_alternative", "")
                if pg:
                    parts.append(f"  Postgres: {pg}")
                if alt:
                    parts.append(f"  Fix: {alt}")
            for mp in h.get("mistake_patterns", [])[:2]:
                if mp.get("good_sql"):
                    symptom = mp.get("symptom", "")
                    parts.append(f"Symptom: {symptom}" if symptom else "")
                    parts.append(f"Correct approach:\n{mp['good_sql']}")
        else:
            tmpl = h.get("template", "")
            if tmpl:
                parts.append(f"Pattern:\n{tmpl}")
            for ap in h.get("anti_patterns", [])[:2]:
                parts.append(f"Avoid: {ap}")

    return "\n".join(p for p in parts if p is not None)


def _format_for_planning(hits: list[dict]) -> str:
    parts: list[str] = ["RELEVANT SQL AND DOMAIN PATTERNS (apply when writing queries):"]
    for h in hits:
        parts.append(f"\n── {h['title']} ({h.get('difficulty', '')}) ──")
        tier = h.get("tier", 3)

        if tier == 1:
            what = h.get("what_it_does", "")
            if what:
                parts.append(what)
            tmpl = h.get("template", "")
            if tmpl:
                parts.append(f"SQL pattern:\n{tmpl}")
            for dt in h.get("dialect_traps", [])[:1]:
                alt = dt.get("safe_alternative", "")
                if alt:
                    parts.append(f"Dialect note: {alt}")

        elif tier == 2:
            defn = h.get("business_definition", "")
            if defn:
                parts.append(f"Business context: {defn}")
            mn = h.get("metric_nature", {})
            if isinstance(mn, dict) and mn.get("common_misconception"):
                parts.append(f"⚠ Misconception: {mn['common_misconception']}")
            dqs = h.get("diagnostic_questions", [])[:2]
            if dqs:
                parts.append("Key questions to answer: " + " | ".join(dqs))
            inf = h.get("inflation_causes", [])[:1]
            for ic in inf:
                if isinstance(ic, dict):
                    parts.append(f"Watch for inflation: {ic.get('cause', '')} — {ic.get('how_it_inflates', '')}")
            sql_ex = h.get("sql_example", "")
            if sql_ex:
                parts.append(f"Reference SQL:\n{sql_ex}")

        else:
            tmpl = h.get("template", "")
            when = h.get("when_to_use", [])
            if when:
                parts.append("Use when: " + when[0] if when else "")
            if tmpl:
                parts.append(f"Pattern: {tmpl}")
            for ap in h.get("anti_patterns", [])[:1]:
                parts.append(f"Avoid: {ap}")

    return "\n".join(p for p in parts if p is not None)


def _format_for_decompose(hits: list[dict]) -> str:
    parts: list[str] = ["DOMAIN KNOWLEDGE (use to form precise hypotheses):"]
    for h in hits:
        parts.append(f"\n── {h['title']} ──")

        defn = h.get("business_definition", "")
        if defn:
            parts.append(defn)

        dqs = h.get("diagnostic_questions", [])[:3]
        if dqs:
            parts.append("Diagnostic questions:\n" + "\n".join(f"  - {q}" for q in dqs))

        # Structured causal chains — two shapes:
        #   Aughor: {symptom, check_in_order, detection_sql}
        #   Talonsight: {if, then}
        causal = h.get("causal_relationships", [])[:4]
        if causal:
            parts.append("Causal signals:")
            for cr in causal:
                if isinstance(cr, dict):
                    symptom = cr.get("symptom") or cr.get("if", "")
                    then = cr.get("then", "")
                    checks = cr.get("check_in_order", [])
                    sql = cr.get("detection_sql", "")
                    if symptom:
                        parts.append(f"  If: {symptom}")
                    if then:
                        parts.append(f"    → {then}")
                    if checks:
                        parts.append(f"    → Check in order: {' → '.join(checks)}")
                    if sql:
                        parts.append(f"    Detection SQL: {sql}")
                else:
                    parts.append(f"  - {cr}")

        cross = h.get("cross_metric_signals", [])[:2]
        if cross:
            parts.append("Cross-metric signals:")
            for cs in cross:
                if isinstance(cs, dict):
                    parts.append(f"  If {cs.get('if', '')} → {cs.get('then', '')}")
                else:
                    parts.append(f"  {cs}")

        inf = h.get("inflation_causes", [])[:2]
        if inf:
            parts.append("Metric inflation causes:")
            for ic in inf:
                cause = ic.get("cause", str(ic)) if isinstance(ic, dict) else str(ic)
                parts.append(f"  ⚠ {cause}")

        defl = h.get("deflation_causes", [])[:2]
        if defl:
            parts.append("Metric deflation causes:")
            for dc in defl:
                cause = dc.get("cause", str(dc)) if isinstance(dc, dict) else str(dc)
                parts.append(f"  ⚠ {cause}")

        related = h.get("related_patterns", [])
        if related:
            parts.append(f"  Related metrics to cross-check: {', '.join(related)}")

    return "\n".join(p for p in parts if p is not None)

def has_strong_kb_match(query: str, threshold: float = 0.75, top_k: int = 3) -> bool:
    """Return True if the KB contains a match with score >= threshold."""
    if not KB_ENABLED or not KB_PATH:
        return False
    try:
        if not _ensure_indexed():
            return False
        from aughor.semantic.embedder import embed_one
        from aughor.semantic.vector_store import search
        vector = embed_one(query)
        hits = search(KB_COLLECTION, vector, top_k=top_k)
        for h in hits:
            if h["score"] >= threshold:
                return True
        return False
    except Exception:
        return False

