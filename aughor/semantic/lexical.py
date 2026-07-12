"""Lexical (BM25) scoring + hybrid vector⊕lexical reranking — R7 retrieval sharpening.

Pure-cosine top-k retrieval misses the candidate whose embedding is only *mediocre* but
whose TEXT carries the query's rare terms verbatim — an exact metric name, a column, a
dialect keyword. Embeddings smear those into their neighbourhood; lexical match nails them.

Hybrid retrieval over-fetches by vector, then reranks the pool by a blend of the vector
score and a BM25 lexical score, recovering the exact-term hits a dense retriever buries.
Dependency-free (no `rank_bm25`): BM25 stats are computed over the small over-fetched pool,
which is exactly the set we're reranking. Pure + deterministic → unit-testable.
"""
from __future__ import annotations

import math
import re
from typing import Any, Callable

_TOKEN = re.compile(r"[a-z0-9_]+")
# A tiny English stop list — drop the words that carry no retrieval signal so they don't
# dilute the BM25 length normalization. Domain/SQL terms are deliberately NOT stopped.
_STOP = frozenset(
    "the a an of to in on for and or is are was were be been being as at by it its this that "
    "with from into over per vs via we you they them their our".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall((text or "").lower()) if t not in _STOP and len(t) > 1]


def bm25_scores(query: str, docs: list[str], *, k1: float = 1.5, b: float = 0.75) -> list[float]:
    """BM25 of ``query`` against each doc, with IDF computed from the candidate pool itself
    (appropriate for reranking a small over-fetched set). One score per doc; 0 when nothing
    matches."""
    q_terms = tokenize(query)
    if not q_terms or not docs:
        return [0.0] * len(docs)
    tokenized = [tokenize(d) for d in docs]
    n = len(docs)
    avgdl = (sum(len(d) for d in tokenized) / n) or 1.0
    df: dict[str, int] = {}
    for d in tokenized:
        for term in set(d):
            df[term] = df.get(term, 0) + 1
    scores: list[float] = []
    for d in tokenized:
        dl = len(d) or 1
        tf: dict[str, int] = {}
        for term in d:
            tf[term] = tf.get(term, 0) + 1
        s = 0.0
        for term in q_terms:
            f = tf.get(term)
            if not f:
                continue
            nq = df.get(term, 0)
            idf = math.log(1 + (n - nq + 0.5) / (nq + 0.5))
            s += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / avgdl))
        scores.append(s)
    return scores


def _minmax(vals: list[float]) -> list[float]:
    if not vals:
        return []
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-9:
        return [0.0] * len(vals)   # no spread → this signal contributes nothing to the blend
    return [(v - lo) / (hi - lo) for v in vals]


def _alpha_blend_order(vec: list[float], lex: list[float], *, alpha: float) -> list[int]:
    """The original min-max α-blend ordering (default path — kept byte-identical). Both signals are
    min-max normalized over the pool, ordered by ``α·vec + (1-α)·lex`` with the *normalized* vector as
    the stable tiebreak, so a pool with no lexical signal preserves the vector order exactly."""
    v = _minmax(vec)
    l = _minmax(lex)
    return sorted(range(len(vec)), key=lambda i: (alpha * v[i] + (1.0 - alpha) * l[i], v[i]), reverse=True)


def _ranks(scores: list[float]) -> list[int]:
    """1-based positional ranks (highest score → rank 1). Ties keep pool order (Python's stable sort),
    so the ranking is deterministic."""
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    ranks = [0] * len(scores)
    for pos, i in enumerate(order):
        ranks[i] = pos + 1
    return ranks


def _rrf_order(vec: list[float], lex: list[float], *, alpha: float = 0.6, k: int = 60) -> list[int]:
    """Reciprocal Rank Fusion (Rec 6 / L5): fuse the vector and lexical RANKINGS, not their scores.

    Each signal contributes ``weight / (k + rank)`` with ``k=60``; the α knob carries over as the rank
    weights (``w_vec=α``, ``w_lex=1-α``). Because only ranks enter, the result is immune to the
    score-scale mismatch that min-max α-blending suffers — a tight Qdrant-cosine cluster stretched to
    [0,1] beside a lone dominant BM25 spike no longer distorts the fusion. A pool with no lexical signal
    falls back to pure vector rank (matching the α-blend's preserve-vector guarantee); the raw vector
    score breaks ties, stably."""
    n = len(vec)
    rv = _ranks(vec)
    w_vec, w_lex = alpha, 1.0 - alpha
    if any(x > 0 for x in lex):
        rl = _ranks(lex)
        fused = [w_vec / (k + rv[i]) + w_lex / (k + rl[i]) for i in range(n)]
    else:
        fused = [w_vec / (k + rv[i]) for i in range(n)]
    return sorted(range(n), key=lambda i: (fused[i], vec[i]), reverse=True)


def hybrid_rerank(
    query: str,
    candidates: list[dict],
    *,
    text_of: Callable[[dict], str],
    score_key: str = "score",
    alpha: float = 0.6,
) -> list[dict]:
    """Rerank vector-retrieved ``candidates`` by fusing the dense (vector) and lexical (BM25) signals,
    recovering the exact-term hits a dense retriever buries. ``alpha=0.6`` keeps the semantic vector in
    the lead while letting an exact lexical hit climb.

    Two fusion methods, selected by the ``search.rrf`` flag:
      • **off (default)** — min-max α-blend, byte-identical to the historical behaviour.
      • **on** — Reciprocal Rank Fusion (rank-based, k=60), robust to the cosine⊕BM25 score-scale
        mismatch that α-blending is sensitive to. See ``_rrf_order``.

    Both are stable (vector score breaks ties) and both preserve the pool's vector order when there is no
    lexical signal, so flipping the flag is a safe, evaluable change."""
    if len(candidates) <= 1:
        return list(candidates)
    vec = [float(c.get(score_key, 0.0) or 0.0) for c in candidates]
    lex = bm25_scores(query, [text_of(c) for c in candidates])
    from aughor.kernel.flags import flag_enabled
    order = (_rrf_order(vec, lex, alpha=alpha)
             if flag_enabled("search.rrf")
             else _alpha_blend_order(vec, lex, alpha=alpha))
    return [candidates[i] for i in order]


def payload_text(payload: Any) -> str:
    """Flatten a Qdrant payload to one searchable string — every string value (and string
    list element), so BM25 sees template SQL, descriptions, traps, names, etc."""
    parts: list[str] = []
    for v in (payload or {}).values() if isinstance(payload, dict) else []:
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, (list, tuple)):
            parts.extend(str(x) for x in v if isinstance(x, str))
    return " ".join(parts)
