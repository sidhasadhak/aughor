"""Hermetic coverage for the search.rrf retrieval-eval harness — the parts that need no
embedder (corpus load + honest query derivation). The measurement itself (which embeds via
local Ollama) is a manual eval, not a CI test; this only keeps the harness from rotting and
pins that search.rrf is settled OFF on the measured result.
"""
from __future__ import annotations

from aughor.evals import rrf_retrieval_eval as R


def test_corpus_loads_the_real_kb():
    entries = R.load_entries()
    assert len(entries) > 100, "the real data/kb corpus should carry the pattern library"
    # production-exact: each carries the embed_text production sends + the payload it reranks
    assert all(e.pattern_id and e.embed_text and isinstance(e.payload, dict) for e in entries)


def test_queries_are_derived_only_from_the_entrys_own_fields():
    """The honesty guarantee: a query is the entry's title / usage text — never authored,
    so the relevant document is definitional, not a hand-picked relevance judgment."""
    from types import SimpleNamespace
    entry = SimpleNamespace(title="Customer acquisition cost by channel",
                            payload={"when_to_use": ["compare spend efficiency across channels"]})
    qs = R.queries_for(entry)
    regimes = {r for r, _ in qs}
    assert regimes <= {"title", "usage"}
    for _regime, q in qs:
        assert q in (entry.title, " ".join(entry.payload["when_to_use"]))


def test_search_rrf_is_settled_off_on_the_measured_result():
    """The eval found α-blend beats RRF on the real KB, so the flag is intentionally OFF —
    not a graduation. Pin the disposition so a future flip has to re-open the measurement."""
    from aughor.kernel.flags import EXPERIMENT, FLAG_DEFAULT, INTENTIONALLY_OFF

    assert "search.rrf" in INTENTIONALLY_OFF
    assert "search.rrf" not in EXPERIMENT
    assert FLAG_DEFAULT.get("search.rrf") is not True
