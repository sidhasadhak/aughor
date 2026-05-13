"""LLM provider abstraction — Ollama (local) or Anthropic (cloud), both via instructor."""
from __future__ import annotations

import os
from typing import Type, TypeVar

import instructor
from openai import OpenAI
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

# Default model — qwen2.5-coder is best-in-class for SQL + structured reasoning
DEFAULT_OLLAMA_MODEL = os.getenv("HERMES_MODEL", "qwen3-coder-next:cloud")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")


def _build_ollama_client() -> instructor.Instructor:
    raw = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")
    return instructor.from_openai(raw, mode=instructor.Mode.JSON)


def _build_anthropic_client() -> instructor.Instructor:
    import anthropic
    raw = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return instructor.from_anthropic(raw)


class LLMProvider:
    """Thin wrapper: call .complete() with a Pydantic response_model, get a typed object back."""

    def __init__(self, backend: str = "ollama"):
        self.backend = backend
        if backend == "ollama":
            self._client = _build_ollama_client()
            self._model = DEFAULT_OLLAMA_MODEL
        elif backend == "anthropic":
            self._client = _build_anthropic_client()
            self._model = os.getenv("HERMES_MODEL", "claude-sonnet-4-6")
        else:
            raise ValueError(f"Unknown backend: {backend!r}. Use 'ollama' or 'anthropic'.")

    def complete(
        self,
        system: str,
        user: str,
        response_model: Type[T],
        temperature: float = 0.1,
    ) -> T:
        if self.backend == "anthropic":
            return self._client.messages.create(
                model=self._model,
                max_tokens=4096,
                system=system,
                messages=[{"role": "user", "content": user}],
                response_model=response_model,
            )
        else:
            return self._client.chat.completions.create(
                model=self._model,
                temperature=temperature,
                response_model=response_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )


_provider: LLMProvider | None = None


def get_provider() -> LLMProvider:
    global _provider
    if _provider is None:
        backend = os.getenv("HERMES_BACKEND", "ollama")
        _provider = LLMProvider(backend=backend)
    return _provider
