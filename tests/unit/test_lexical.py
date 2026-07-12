"""R7 — hybrid lexical⊕vector reranking. Pure + hermetic (no Qdrant, no embeddings)."""
from __future__ import annotations

from aughor.semantic.lexical import (
    _alpha_blend_order,
    _ranks,
    _rrf_order,
    bm25_scores,
    hybrid_rerank,
    payload_text,
    tokenize,
)


def test_tokenize_drops_stopwords_keeps_domain_terms():
    toks = tokenize("the total revenue by marketing_channel")
    assert "the" not in toks and "by" not in toks
    assert {"total", "revenue", "marketing_channel"} <= set(toks)


def test_bm25_ranks_matching_docs_higher():
    docs = [
        "gross margin formula revenue minus cost",
        "average order value aov per order",
        "unrelated shipping logistics freight",
    ]
    scores = bm25_scores("gross margin revenue", docs)
    assert scores[0] == max(scores) and scores[0] > 0
    assert scores[2] == 0.0           # no query-term overlap


def test_bm25_empty_inputs():
    assert bm25_scores("", ["a b c"]) == [0.0]
    assert bm25_scores("x", []) == []


def test_hybrid_lifts_a_buried_exact_match_into_topk():
    # C is last by vector but contains the exact query terms; at alpha=0.6 the vector still
    # leads (A stays #1), but C climbs above B — i.e. it enters a top-2 cut it was excluded
    # from by pure cosine. That recovery is the whole point of hybrid retrieval.
    query = "repeat purchase rate"
    cands = [
        {"id": "A", "score": 0.85, "text": "customer lifetime value cohorts retention"},
        {"id": "B", "score": 0.80, "text": "shipping logistics freight carriers"},
        {"id": "C", "score": 0.78, "text": "repeat purchase rate share of returning customers"},
    ]
    out = [c["id"] for c in hybrid_rerank(query, cands, text_of=lambda c: c["text"])]
    assert out[0] == "A"                 # the semantic vector still leads
    assert out.index("C") < out.index("B")   # the buried exact match climbs above B
    assert "C" in out[:2]                # …into the top-2


def test_hybrid_stable_with_no_lexical_signal():
    # nothing matches lexically → the vector order is preserved exactly (no regressions).
    cands = [{"id": "A", "score": 0.9, "text": "alpha"}, {"id": "B", "score": 0.5, "text": "beta"}]
    out = hybrid_rerank("zzz qqq", cands, text_of=lambda c: c["text"])
    assert [c["id"] for c in out] == ["A", "B"]


def test_hybrid_singleton_passthrough():
    cands = [{"id": "A", "score": 0.5, "text": "x"}]
    assert hybrid_rerank("q", cands, text_of=lambda c: c["text"]) == cands


def test_payload_text_flattens_strings_and_lists():
    p = {"template": "SELECT x FROM t", "traps": ["no fanout", "cast int"], "n": 5, "ok": True}
    t = payload_text(p)
    assert "SELECT x" in t and "no fanout" in t and "cast int" in t
    assert "5" not in t and "True" not in t   # non-strings are skipped


# ── Rec 6 / L5: Reciprocal Rank Fusion (flag search.rrf) ──────────────────────

def test_ranks_are_positional_and_stable():
    assert _ranks([0.9, 0.5, 0.7]) == [1, 3, 2]
    assert _ranks([1.0, 1.0, 0.0]) == [1, 2, 3]      # ties keep pool order (stable sort)


def test_rrf_is_scale_invariant_where_alpha_blend_is_not():
    # Two vector-score vectors with the SAME ranking (A>B>C) but different spreads, plus one exact
    # lexical hit on the buried C. This is the cosine⊕BM25 scale-mismatch Rec 6 targets.
    vec1 = [0.90, 0.89, 0.10]
    vec2 = [0.99, 0.11, 0.10]                          # same ranking, compressed middle
    lex = [0.0, 0.0, 8.0]
    # RRF depends only on RANKS → identical order for both spreads, and it lifts C above B (recovers the
    # buried exact match) — the whole point of hybrid retrieval.
    assert _rrf_order(vec1, lex, alpha=0.6) == _rrf_order(vec2, lex, alpha=0.6) == [0, 2, 1]
    # The α-blend is score-scale SENSITIVE: the same ranking yields DIFFERENT orders — the failure mode.
    assert _alpha_blend_order(vec1, lex, alpha=0.6) == [0, 1, 2]
    assert _alpha_blend_order(vec2, lex, alpha=0.6) == [0, 2, 1]


def test_rrf_preserves_vector_order_without_lexical_signal():
    # No lexical signal → pure vector rank, matching the α-blend's preserve-vector guarantee.
    assert _rrf_order([0.9, 0.5, 0.3], [0.0, 0.0, 0.0], alpha=0.6) == [0, 1, 2]


def test_hybrid_rerank_dispatches_on_flag(monkeypatch):
    query = "repeat purchase rate"
    cands = [
        {"id": "A", "score": 0.85, "text": "customer lifetime value cohorts retention"},
        {"id": "B", "score": 0.80, "text": "shipping logistics freight carriers"},
        {"id": "C", "score": 0.78, "text": "repeat purchase rate share of returning customers"},
    ]
    vec = [c["score"] for c in cands]
    lex = bm25_scores(query, [c["text"] for c in cands])

    monkeypatch.delenv("AUGHOR_SEARCH_RRF", raising=False)     # off → α-blend, byte-identical to today
    off = [c["id"] for c in hybrid_rerank(query, cands, text_of=lambda c: c["text"])]
    assert off == [cands[i]["id"] for i in _alpha_blend_order(vec, lex, alpha=0.6)]

    monkeypatch.setenv("AUGHOR_SEARCH_RRF", "1")               # on → RRF
    on = [c["id"] for c in hybrid_rerank(query, cands, text_of=lambda c: c["text"])]
    assert on == [cands[i]["id"] for i in _rrf_order(vec, lex, alpha=0.6)]
    # Either method honours the hybrid contract: the semantic leader stays #1 and the exact match beats B.
    assert on[0] == "A" and on.index("C") < on.index("B")
