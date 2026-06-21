"""R7a — rank the governed metric catalog by relevance to the question, so the canonical
metric is promoted (and the tail trimmed at scale). Hermetic: embeddings are stubbed."""
from __future__ import annotations

import aughor.semantic.metric_retrieval as mr


class _M:
    def __init__(self, name, label, sql, caveats="", dimensions=None):
        self.name, self.label, self.sql = name, label, sql
        self.caveats, self.dimensions = caveats, dimensions or []


def _bm25_only(monkeypatch):
    # force the BM25 path (no Ollama dependency) for a deterministic test
    monkeypatch.setattr(mr, "_embed_question_and_metrics", lambda q, t: (None, None))


def test_promotes_the_lexically_relevant_metric(monkeypatch):
    _bm25_only(monkeypatch)
    metrics = [
        _M("aov", "Average Order Value", "AVG(order_value)"),
        _M("revenue", "Revenue", "SUM(order_value)"),
        _M("cac", "Customer Acquisition Cost", "SUM(spend)/COUNT(*)"),
    ]
    ranked, top = mr.rank_metrics_for_question("what is our total revenue?", metrics)
    assert top is True and ranked[0].name == "revenue"


def test_no_relevance_signal_keeps_catalog_order(monkeypatch):
    _bm25_only(monkeypatch)
    metrics = [_M("aov", "Average Order Value", "AVG(order_value)"),
               _M("revenue", "Revenue", "SUM(order_value)")]
    ranked, top = mr.rank_metrics_for_question("zzz qqq totally unrelated", metrics)
    assert top is False and [m.name for m in ranked] == ["aov", "revenue"]


def test_singleton_and_empty_question_are_noops(monkeypatch):
    _bm25_only(monkeypatch)
    one = [_M("revenue", "Revenue", "SUM(x)")]
    assert mr.rank_metrics_for_question("revenue", one) == (one, False)
    assert mr.rank_metrics_for_question("", one) == (one, False)


def test_trims_to_top_k_at_scale_keeping_the_relevant_one(monkeypatch):
    _bm25_only(monkeypatch)
    metrics = [_M(f"m{i}", f"Filler Metric {i}", f"SUM(col{i})") for i in range(12)]
    metrics.append(_M("revenue", "Revenue", "SUM(order_value)"))
    ranked, top = mr.rank_metrics_for_question("revenue", metrics, top_k=8)
    assert top and len(ranked) == 8 and ranked[0].name == "revenue"


def test_hybrid_uses_embeddings_for_a_semantic_match(monkeypatch):
    # "sell" has no lexical overlap with "revenue"; the embedding match must still win.
    metrics = [_M("revenue", "Revenue", "SUM(order_value)"),
               _M("aov", "Average Order Value", "AVG(order_value)")]

    def _fake(q, texts):
        return [1.0, 0.0], [[1.0, 0.0] if "Revenue" in t else [0.0, 1.0] for t in texts]

    monkeypatch.setattr(mr, "_embed_question_and_metrics", _fake)
    ranked, top = mr.rank_metrics_for_question("how much did we sell last quarter", metrics)
    assert top and ranked[0].name == "revenue"
