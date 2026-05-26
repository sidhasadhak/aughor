"""Text embeddings via Ollama's OpenAI-compatible /v1/embeddings endpoint."""
from __future__ import annotations

import os

EMBED_MODEL = os.getenv("AUGHOR_EMBED_MODEL", "nomic-embed-text")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")

_BATCH_SIZE = 64


def embed(texts: list[str]) -> list[list[float]]:
    """Return one 768-dim embedding per text. Batches automatically."""
    from openai import OpenAI
    client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")

    results: list[list[float]] = []
    for i in range(0, len(texts), _BATCH_SIZE):
        batch = texts[i : i + _BATCH_SIZE]
        resp = client.embeddings.create(model=EMBED_MODEL, input=batch)
        results.extend(item.embedding for item in resp.data)
    return results


def embed_one(text: str) -> list[float]:
    return embed([text])[0]
