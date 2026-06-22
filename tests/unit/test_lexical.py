"""R7 — hybrid lexical⊕vector reranking. Pure + hermetic (no Qdrant, no embeddings)."""
from __future__ import annotations

from aughor.semantic.lexical import bm25_scores, hybrid_rerank, payload_text, tokenize


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
