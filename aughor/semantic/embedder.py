"""Text embeddings — Ollama by default, any OpenAI-compatible backend by configuration.

This was one hardcoded call to a LOCAL Ollama, and that made the whole knowledge plane a
laptop feature: on a deployment without Ollama nothing indexes and every search returns
empty. The chat path had solved the same problem long ago — the provider ladder holds keys,
base URLs and an org overlay — and embeddings simply were not part of it. `grep embed`
across `aughor/llm/` found nothing.

So the backend is now a switch over the SAME ladder: `AUGHOR_EMBED_BACKEND`, defaulting to
`ollama`, resolving its URL and key through `provider.endpoint_for`. A key set once in
Settings works for chat and for embeddings, rather than for one of them.

**No hosted backend ships a model id.** That is the standing directive and the chat ladder
already obeys it — a guessed id is this repo's opinion about another vendor's catalogue, and
those guesses went stale silently. Ollama keeps `nomic-embed-text` because it is local, it
is what indexed the existing corpus, and changing it would be a migration rather than a
default. Any other backend must be told its model, and says so when it has not been.

⚠️ **Changing backend or model requires a re-index, always.** A different model is a
different vector space, so old vectors and new ones are not comparable even at an identical
width — and if the width differs, the collection itself must be rebuilt. Nothing here does
that silently: `embedding_dim()` exists so the caller can compare against what the store
already holds and refuse.
"""
from __future__ import annotations

import contextvars
import os
from contextlib import contextmanager
from typing import Iterator, Optional

#: Backends this lane can drive. All are reached over the OpenAI-compatible `/embeddings`
#: shape; a backend that does not serve one fails at the call, visibly, rather than here.
EMBED_BACKENDS: tuple[str, ...] = ("ollama", "lmstudio", "gemini", "openrouter", "together")

#: The backends that run on a machine the deployment runs; every other one is a hosted provider, which may charge.
LOCAL_BACKENDS: tuple[str, ...] = ("ollama", "lmstudio")

#: Arc FA, FA-7 — a read that must SAY whether it called the embedder (a hosted one may charge at its provider)
#: installs a tally with :func:`tally_calls`; :func:`embed` counts each request it sends and each call that failed.
#: None by default: nothing is counted, and an embedding is made exactly as it was.
_TALLY: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar("aughor_embed_tally", default=None)


@contextmanager
def tally_calls() -> Iterator[dict]:
    """Count the embedder's requests inside the block: ``{"requests", "texts", "failed"}``. The count rides a
    contextvar, so a worker that copies the context counts into the same tally."""
    tally = {"requests": 0, "texts": 0, "failed": 0}
    token = _TALLY.set(tally)
    try:
        yield tally
    finally:
        _TALLY.reset(token)


def current_tally() -> Optional[dict]:
    """The tally a surrounding :func:`tally_calls` installed, or None — so a reader can tell which of its steps the
    embedder failed in (a retriever that swallows the failure returns an empty result that is not a true empty)."""
    return _TALLY.get()


#: The local default, unchanged: it is what the existing corpus was embedded with.
_OLLAMA_DEFAULT_MODEL = "nomic-embed-text"

_BATCH_SIZE = 64

#: (backend, model) → dimension, learned by one probe. Not cached across processes: a
#: dimension is cheap to re-learn and a stale one is the kind of fact that corrupts a
#: collection quietly.
_DIM_CACHE: dict[tuple[str, str], int] = {}


class EmbeddingConfigError(RuntimeError):
    """The embedding lane is not configured well enough to run."""


def embed_backend() -> str:
    """Which backend embeds. `AUGHOR_EMBED_BACKEND`, else Ollama.

    Deliberately its own variable rather than following the chat backend: a person running
    a local model for privacy and a hosted one for chat is the normal case, not an exotic
    one, and the reverse is just as reasonable.
    """
    chosen = (os.getenv("AUGHOR_EMBED_BACKEND") or "ollama").strip().lower()
    if chosen not in EMBED_BACKENDS:
        raise EmbeddingConfigError(
            f"unknown embedding backend {chosen!r} — one of {', '.join(EMBED_BACKENDS)}")
    return chosen


def embed_model(backend: str | None = None) -> str:
    """The model id to embed with. Explicit config wins; only Ollama has a default."""
    backend = backend or embed_backend()
    configured = (os.getenv("AUGHOR_EMBED_MODEL") or "").strip()
    if configured:
        return configured
    if backend in ("ollama", "lmstudio"):
        return _OLLAMA_DEFAULT_MODEL
    raise EmbeddingConfigError(
        f"no embedding model configured for backend {backend!r} — set AUGHOR_EMBED_MODEL. "
        f"This project ships no id for a hosted provider on purpose: a guessed model name "
        f"is an opinion about someone else's catalogue, and those go stale silently. "
        f"`GET /llm/models?backend={backend}` lists what your account can actually see.")


def describe_backend() -> dict:
    """Which embedder this deployment would call — ``{"backend", "model", "hosted"}`` — or, with ``unconfigured``, why
    it could not. Makes no call and never raises: a reader that reports the embedder must not fail on its config."""
    try:
        backend = embed_backend()
    except EmbeddingConfigError as exc:
        return {"backend": "", "model": "", "hosted": None, "unconfigured": str(exc)}
    hosted = backend not in LOCAL_BACKENDS
    try:
        return {"backend": backend, "model": embed_model(backend), "hosted": hosted}
    except EmbeddingConfigError as exc:
        return {"backend": backend, "model": "", "hosted": hosted, "unconfigured": str(exc)}


# Kept as module attributes because callers and tests read them for display. They are the
# CURRENT values, resolved at import; `embed_backend()`/`embed_model()` are the live truth.
EMBED_MODEL = os.getenv("AUGHOR_EMBED_MODEL", _OLLAMA_DEFAULT_MODEL)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")


def endpoint() -> tuple[str, str]:
    """`(base_url, api_key)` for the embedding backend, through the provider ladder."""
    backend = embed_backend()
    if backend == "ollama" and os.getenv("OLLAMA_BASE_URL"):
        return os.getenv("OLLAMA_BASE_URL", "").strip(), ""
    from aughor.llm.provider import endpoint_for

    base_url, key = endpoint_for(backend)
    if not base_url:
        raise EmbeddingConfigError(f"no base URL for embedding backend {backend!r}")
    from aughor.llm.provider import NEEDS_KEY
    if backend in NEEDS_KEY and not key:
        raise EmbeddingConfigError(
            f"no API key for embedding backend {backend!r} — set it in Settings → "
            f"Inference, or in the environment")
    return base_url, key


def embed(texts: list[str]) -> list[list[float]]:
    """One embedding per text, batched. Raises rather than degrading: a caller that gets a
    short list back would upsert a document missing chunks and never know."""
    tally = _TALLY.get()
    if tally is None:
        return _embed(texts, None)
    try:
        return _embed(texts, tally)
    except Exception:
        tally["failed"] += 1
        raise


def _embed(texts: list[str], tally: Optional[dict]) -> list[list[float]]:
    from openai import OpenAI

    base_url, key = endpoint()
    model = embed_model()
    client = OpenAI(base_url=base_url, api_key=key or "ollama")

    results: list[list[float]] = []
    for i in range(0, len(texts), _BATCH_SIZE):
        batch = texts[i: i + _BATCH_SIZE]
        if tally is not None:
            tally["requests"] += 1
            tally["texts"] += len(batch)
        resp = client.embeddings.create(model=model, input=batch)
        results.extend(item.embedding for item in resp.data)
    if len(results) != len(texts):
        raise RuntimeError(
            f"embedder returned {len(results)} vectors for {len(texts)} texts — refusing to "
            f"index a document with holes in it")
    return results


def embed_one(text: str) -> list[float]:
    return embed([text])[0]


def embedding_dim() -> int:
    """How wide this backend's vectors are, learned by embedding one short string.

    Probed rather than declared. A table of "model → dimension" is a second opinion about
    someone else's catalogue — the same thing the no-default-model rule exists to prevent —
    and it would be wrong exactly when a provider adds a variable-width model.
    """
    key = (embed_backend(), embed_model())
    if key not in _DIM_CACHE:
        _DIM_CACHE[key] = len(embed_one("dimension probe"))
    return _DIM_CACHE[key]
