"""Embedding-similarity dedup for explorer findings — catch PARAPHRASE duplicates that
the token (Jaccard) check can't.

Two findings can state the SAME thing with different wording AND different specifics —
"payment success is nearly uniform across methods (89.35%…)" vs "payment success is
remarkably consistent, ranging 89.23%–89.35%". Token overlap is low (~0.23) because the
numbers and phrasing differ, so `shape.is_semantically_redundant` keeps both. Their
embeddings, though, sit at cosine ~0.87 — clearly the same claim.

Calibrated on real briefing pairs: paraphrase dupes land 0.87–0.93, genuinely different
findings that merely share a word land ≤0.78, so a 0.85 threshold separates them cleanly.

Fail-OPEN: if the embed model (Ollama / nomic-embed-text) is unavailable, `embed_text`
returns None and the caller keeps the finding — never raises into the explorer.
"""
from __future__ import annotations

import logging

from aughor.ontology.dedup import cosine

logger = logging.getLogger(__name__)

# Paraphrase dupes ≥0.87, distinct-but-related ≤0.78 on real findings → 0.85 splits them.
DEFAULT_THRESHOLD = 0.85


def embed_text(text: str) -> list[float] | None:
    """One embedding for a finding, or None if embeddings are unavailable (fail-open)."""
    t = (text or "").strip()
    if not t:
        return None
    try:
        from aughor.semantic.embedder import embed_one
        return embed_one(t)
    except Exception as exc:
        logger.debug("finding embed unavailable (fail-open): %s", exc)
        return None


def max_cosine(vec: list[float] | None, vecs) -> float:
    """Highest cosine of `vec` against any non-None vector in `vecs`. 0.0 if `vec` is
    None or there are no comparable priors. Pure — trivially testable with hand vectors."""
    if not vec:
        return 0.0
    best = 0.0
    for v in vecs or ():
        if v:
            c = cosine(vec, v)
            if c > best:
                best = c
    return best


def is_paraphrase_duplicate(vec: list[float] | None, prior_vecs, threshold: float = DEFAULT_THRESHOLD) -> bool:
    """True when `vec` is within `threshold` cosine of any prior finding's vector — the
    same claim in different words. Fail-open: a None vec (embeddings down) is never a dup."""
    return max_cosine(vec, prior_vecs) >= threshold
