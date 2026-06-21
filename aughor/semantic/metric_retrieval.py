"""R7a — retrieve the canonical governed metric for a question.

``unified_metric_grounding`` injects the governed metric catalog so the model uses the audited
formula instead of re-deriving it. As the catalog grows, injecting ALL metrics buries the one
that matters. This ranks the catalog by relevance to the QUESTION (hybrid embedding⊕BM25 — the
R7 reranker), so the most-relevant governed metric is PROMOTED to the top (and, at scale, the
long tail is trimmed) — *retrieve the canonical metric before re-deriving*.

Fail-open and conservative: any failure (or no relevance signal at all) leaves the catalog
order untouched, and below the trim threshold nothing is ever omitted — a small catalog is
cheap to inject whole, so we never risk dropping a relevant metric.
"""
from __future__ import annotations

import hashlib
import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

# At or below this many metrics, ranking only REORDERS + flags the top (never trims).
_TRIM_ABOVE = 8
_ALPHA = 0.6                       # weight on the (semantic) embedding vs BM25
_EMBED_CACHE: dict = {}            # content-hash -> vector, so metric embeddings are computed once


def _metric_text(m: Any) -> str:
    parts = [
        getattr(m, "name", "") or "", getattr(m, "label", "") or "", getattr(m, "sql", "") or "",
        getattr(m, "caveats", "") or "", " ".join(getattr(m, "dimensions", None) or []),
    ]
    return " ".join(p for p in parts if p)


def _norm(vals: list) -> list:
    if not vals:
        return []
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-9:
        return [0.0] * len(vals)
    return [(v - lo) / (hi - lo) for v in vals]


def _cosine(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def _embed_question_and_metrics(question: str, texts: list):
    """Return (q_vec, [metric_vecs]) or (None, None) when embeddings are unavailable. Metric
    vectors are cached by content hash, so only the question is embedded per call."""
    try:
        from aughor.semantic.embedder import embed, embed_one
        qv = embed_one(question)
        mvs: list = [None] * len(texts)
        to_embed, idxs = [], []
        for i, t in enumerate(texts):
            h = hashlib.md5(t.encode()).hexdigest()
            if h in _EMBED_CACHE:
                mvs[i] = _EMBED_CACHE[h]
            else:
                to_embed.append(t)
                idxs.append((i, h))
        for (i, h), v in zip(idxs, embed(to_embed) if to_embed else []):
            _EMBED_CACHE[h] = v
            mvs[i] = v
        return qv, mvs
    except Exception as exc:
        logger.debug("metric_retrieval: embeddings unavailable, BM25-only (%s)", exc)
        return None, None


def rank_metrics_for_question(question: str, metrics: list, *, top_k: int = _TRIM_ABOVE) -> tuple:
    """Reorder ``metrics`` most-relevant-first for ``question`` (hybrid embedding⊕BM25, BM25-only
    when embeddings are unavailable); trim to ``top_k`` only when the catalog exceeds it. Returns
    ``(ranked, top_is_relevant)``. Returns the input order — never reordered — when there is no
    relevance signal, so it can't hurt a question the catalog doesn't cover."""
    if not question or len(metrics) <= 1:
        return metrics, False
    try:
        from aughor.semantic.lexical import bm25_scores
        texts = [_metric_text(m) for m in metrics]
        lex = bm25_scores(question, texts)
        qv, mvs = _embed_question_and_metrics(question, texts)
        if qv and mvs and all(v is not None for v in mvs):
            cos = [_cosine(qv, v) for v in mvs]
            score = [_ALPHA * c + (1 - _ALPHA) * l for c, l in zip(_norm(cos), _norm(lex))]
        else:
            score = _norm(lex)
        if max(score, default=0.0) <= 0.0:
            return metrics, False
        order = sorted(range(len(metrics)), key=lambda i: score[i], reverse=True)
        ranked = [metrics[i] for i in order]
        return (ranked[:top_k] if len(ranked) > top_k else ranked), True
    except Exception as exc:
        logger.warning("metric_retrieval: ranking failed, keeping catalog order (%s)", exc)
        return metrics, False
