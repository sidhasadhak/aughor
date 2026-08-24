"""KB-4 · embeddings join the provider ladder, and Ollama stays the default.

Embeddings were one hardcoded call to a LOCAL Ollama, which made the whole knowledge plane
a laptop feature: on a deployment without it nothing indexes and every search returns empty.
The chat path solved this long ago — keys, base URLs, an org overlay — and `grep embed`
across `aughor/llm/` found nothing at all.

Two properties matter more than the switch itself:

* **Nothing changes until someone changes it.** Ollama and `nomic-embed-text` remain the
  default, because that is what the existing corpus was embedded with.
* **A switch cannot corrupt the index quietly.** `ensure_collection` no-ops on an existing
  collection whatever its width, so a changed model used to fail at UPSERT with a driver
  error and at SEARCH with an empty list — `search_documents` swallows exceptions. Indexing
  now refuses first, and says what to do.
"""
from __future__ import annotations

import pytest

from aughor.knowledge import indexer
from aughor.semantic import embedder


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("AUGHOR_EMBED_BACKEND", raising=False)
    monkeypatch.delenv("AUGHOR_EMBED_MODEL", raising=False)
    embedder._DIM_CACHE.clear()


# ── the default is unchanged ─────────────────────────────────────────────────────

def test_ollama_is_the_default_and_keeps_its_model():
    """The corpus was embedded with this. A moved default would silently make old vectors
    and new ones incomparable."""
    assert embedder.embed_backend() == "ollama"
    assert embedder.embed_model() == "nomic-embed-text"


def test_an_unknown_backend_is_refused_by_name():
    with pytest.raises(embedder.EmbeddingConfigError, match="unknown embedding backend"):
        import os
        os.environ["AUGHOR_EMBED_BACKEND"] = "wishful"
        try:
            embedder.embed_backend()
        finally:
            os.environ.pop("AUGHOR_EMBED_BACKEND", None)


# ── no hosted backend ships a model id ───────────────────────────────────────────

def test_a_hosted_backend_without_a_configured_model_refuses(monkeypatch):
    """The standing directive, and the chat ladder already obeys it: a shipped id is this
    repo's opinion about another vendor's catalogue, and those go stale silently."""
    monkeypatch.setenv("AUGHOR_EMBED_BACKEND", "gemini")

    with pytest.raises(embedder.EmbeddingConfigError) as exc:
        embedder.embed_model()

    assert "AUGHOR_EMBED_MODEL" in str(exc.value)
    assert "/llm/models" in str(exc.value), "the refusal must name where to find real ids"


def test_a_configured_model_is_used_for_any_backend(monkeypatch):
    monkeypatch.setenv("AUGHOR_EMBED_BACKEND", "gemini")
    monkeypatch.setenv("AUGHOR_EMBED_MODEL", "models/some-embedding-model")

    assert embedder.embed_model() == "models/some-embedding-model"


def test_no_gemini_model_id_is_written_anywhere_in_the_package():
    """A rot-guard on the directive. The moment someone adds a convenient default here, the
    picker stops being the source of truth for what exists."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "aughor"
    pattern = re.compile(r"models/gemini-[\w.-]*embedding|gemini-embedding-\d")
    offenders = [str(p.relative_to(root)) for p in root.rglob("*.py")
                 if pattern.search(p.read_text(errors="ignore"))]

    assert not offenders, f"a hosted embedding model id is hardcoded in: {offenders}"


# ── the key comes from the ladder, not a second copy of it ───────────────────────

def test_a_hosted_backend_resolves_its_key_through_the_provider(monkeypatch):
    """One precedence — org overlay, then config, then env — so a key set once in Settings
    works for chat and for embeddings rather than for one of them."""
    monkeypatch.setenv("AUGHOR_EMBED_BACKEND", "gemini")
    monkeypatch.setenv("AUGHOR_EMBED_MODEL", "models/some-embedding-model")
    monkeypatch.setattr("aughor.llm.provider.endpoint_for",
                        lambda b: ("https://example.invalid/v1/", "KEY-FROM-LADDER"))

    base_url, key = embedder.endpoint()

    assert base_url == "https://example.invalid/v1/" and key == "KEY-FROM-LADDER"


def test_a_hosted_backend_with_no_key_says_so(monkeypatch):
    monkeypatch.setenv("AUGHOR_EMBED_BACKEND", "gemini")
    monkeypatch.setenv("AUGHOR_EMBED_MODEL", "models/some-embedding-model")
    monkeypatch.setattr("aughor.llm.provider.endpoint_for",
                        lambda b: ("https://example.invalid/v1/", ""))

    with pytest.raises(embedder.EmbeddingConfigError, match="no API key"):
        embedder.endpoint()


# ── a partial batch is refused rather than indexed ───────────────────────────────

def test_a_short_batch_is_an_error_not_a_document_with_holes(monkeypatch):
    class _Resp:
        data = [type("D", (), {"embedding": [0.0] * 4})()]

    monkeypatch.setattr(embedder, "endpoint", lambda: ("http://x/v1", ""))
    monkeypatch.setattr("openai.OpenAI", lambda **_k: type("C", (), {
        "embeddings": type("E", (), {"create": staticmethod(lambda **_kw: _Resp())})()})())

    with pytest.raises(RuntimeError, match="holes in it"):
        embedder.embed(["one", "two", "three"])


# ── the dimension guard ──────────────────────────────────────────────────────────

def test_the_dimension_is_probed_once_not_declared(monkeypatch):
    """A model→dimension table is a second opinion about someone else's catalogue, and it
    is wrong exactly when a provider ships a variable-width model."""
    calls = []
    monkeypatch.setattr(embedder, "embed",
                        lambda texts: calls.append(1) or [[0.0] * 1536 for _ in texts])

    assert embedder.embedding_dim() == 1536
    assert embedder.embedding_dim() == 1536
    assert len(calls) == 1, "the probe must be cached per (backend, model)"


def test_indexing_refuses_when_the_width_does_not_match_the_index(monkeypatch):
    """The failure this guard exists for: without it, upsert raises a driver error and
    SEARCH returns an empty list, because `search_documents` swallows exceptions. An empty
    knowledge base that is actually a misconfiguration is the worst of the four."""
    monkeypatch.setattr("aughor.semantic.embedder.embedding_dim", lambda: 3072)
    monkeypatch.setattr("aughor.semantic.vector_store.collection_dim", lambda _c: 768)

    with pytest.raises(indexer.EmbeddingDimensionMismatch) as exc:
        indexer._ensure_collection()

    assert "768" in str(exc.value) and "3072" in str(exc.value)
    assert "re-embedded" in str(exc.value), "the refusal must say what to do"
    assert "Nothing was written" in str(exc.value)


def test_a_matching_width_proceeds(monkeypatch):
    ensured = {}
    monkeypatch.setattr("aughor.semantic.embedder.embedding_dim", lambda: 768)
    monkeypatch.setattr("aughor.semantic.vector_store.collection_dim", lambda _c: 768)
    monkeypatch.setattr("aughor.semantic.vector_store.ensure_collection",
                        lambda coll, dim=None: ensured.update(coll=coll, dim=dim))

    indexer._ensure_collection()

    assert ensured["dim"] == 768


def test_a_fresh_index_is_created_at_the_active_width(monkeypatch):
    """No existing collection means no constraint — the new corpus defines the width."""
    ensured = {}
    monkeypatch.setattr("aughor.semantic.embedder.embedding_dim", lambda: 3072)
    monkeypatch.setattr("aughor.semantic.vector_store.collection_dim", lambda _c: None)
    monkeypatch.setattr("aughor.semantic.vector_store.ensure_collection",
                        lambda coll, dim=None: ensured.update(dim=dim))

    indexer._ensure_collection()

    assert ensured["dim"] == 3072
