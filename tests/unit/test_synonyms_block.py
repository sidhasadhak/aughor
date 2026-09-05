"""Human-curated synonyms are RENDERED to the model, not just used for retrieval.

The Snowflake-study lever this store was missing: `ontology/vocabulary.py` synonyms
widened schema-linker retrieval from day one and never reached a prompt — a person
could record "'sales value' means orders.amount" and the SQL writer never learned it.
The KI lane now IMPORTS synonyms, which made the gap urgent: a lane accepting objects
into a prompt-invisible destination is the built-and-inert shape.

These tests pin the whole chain: only the HUMAN tier renders (Snowflake's own caveat —
auto-generated synonyms reduce accuracy — is why mined/model tiers keep widening
retrieval and stay out of the prompt), the block lands in the assembled grounding
context, and the quick-answer path prepends it.
"""
from __future__ import annotations

import inspect

import pytest

from aughor.agent import grounding as G
from aughor.ontology import vocabulary as V


@pytest.fixture
def vocab(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_VOCABULARY_ROOT", str(tmp_path / "vocab"))
    return tmp_path


CONN = "syn_conn"


def test_no_synonyms_means_an_empty_block(vocab):
    """The byte-identical guarantee: a connection with no curation adds nothing."""
    assert V.build_synonyms_block(CONN) == ""
    assert G.vocabulary_synonyms(CONN) == ""


def test_only_the_human_tier_renders(vocab):
    V.add_synonym(CONN, "column", "orders.amount", "sales value", source="human",
                  note="finance's term")
    V.add_synonym(CONN, "metric", "net_revenue", "turnover", source="human")
    V.add_synonym(CONN, "column", "orders.amount", "the money one", source="mined")
    V.add_synonym(CONN, "table", "orders", "order book", source="llm_candidate")

    block = V.build_synonyms_block(CONN)
    assert '"sales value" means column orders.amount — finance\'s term' in block
    assert '"turnover" means metric net_revenue' in block
    assert "the money one" not in block and "order book" not in block
    assert block.startswith("BUSINESS SYNONYMS (human-curated")


def test_a_promoted_candidate_starts_rendering(vocab):
    """The governance story end to end: a model proposal stays invisible until a
    human confirms it — and `add_synonym`'s re-add-as-human IS that promotion."""
    V.add_synonym(CONN, "column", "orders.amount", "sales value",
                  source="llm_candidate")
    assert V.build_synonyms_block(CONN) == ""
    V.add_synonym(CONN, "column", "orders.amount", "sales value", source="human")
    assert '"sales value"' in V.build_synonyms_block(CONN)


def test_the_cap_bounds_a_degenerate_store(vocab):
    for i in range(40):
        V.add_synonym(CONN, "column", f"t.c{i:02d}", f"alias {i:02d}", source="human")
    block = V.build_synonyms_block(CONN)
    assert block.count("means column") == 24


def test_block_lands_in_the_assembled_grounding_context(vocab):
    V.add_synonym(CONN, "column", "orders.amount", "sales value", source="human")
    ctx = G.build_grounding_context("total sales value by region", CONN)
    by_key = {b.key: b for b in ctx.blocks}
    assert "synonyms" in by_key
    assert by_key["synonyms"].present
    assert '"sales value" means column orders.amount' in by_key["synonyms"].content


def test_block_absent_from_the_context_when_nothing_curated(vocab):
    ctx = G.build_grounding_context("anything", CONN)
    by_key = {b.key: b for b in ctx.blocks}
    assert "synonyms" in by_key and not by_key["synonyms"].present


# ── the answer path consumes the producer ─────────────────────────────────────


def test_quick_answer_path_prepends_the_synonyms_block():
    """Wiring guard (the instructions-block idiom): the gap this closes was a store
    nothing prompt-side consumed, so pin the consumption site itself."""
    from aughor.routers.investigations import _answer_core
    src = inspect.getsource(_answer_core)
    assert "vocabulary_synonyms" in src
    assert 'prompt = _syn_sec + "\\n" + prompt' in src
