"""LLM provider abstraction — Ollama, LM Studio, Groq, Together, or Anthropic.

Two roles, two model slots:
  coder   — SQL generation, hypothesis scoring, decomposition (structured reasoning)
  narrator — report synthesis (long-form prose)

Env vars:
  AUGHOR_BACKEND         ollama (default) | lmstudio | groq | together | anthropic
  AUGHOR_CODER_MODEL     default per backend (see _DEFAULT_MODELS)
  AUGHOR_NARRATOR_MODEL  default per backend
  AUGHOR_MODEL           fallback for both if role-specific var is unset
  LMSTUDIO_BASE_URL      default http://localhost:1234/v1
  GROQ_API_KEY           required when AUGHOR_BACKEND=groq
  TOGETHER_API_KEY       required when AUGHOR_BACKEND=together
  ANTHROPIC_API_KEY      required when AUGHOR_BACKEND=anthropic
"""
from __future__ import annotations

import os
from typing import Literal, Type, TypeVar

import instructor
from openai import OpenAI
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

Role = Literal["coder", "narrator"]

OLLAMA_BASE_URL    = os.getenv("OLLAMA_BASE_URL",    "http://localhost:11434/v1")
LMSTUDIO_BASE_URL  = os.getenv("LMSTUDIO_BASE_URL",  "http://localhost:1234/v1")
GROQ_BASE_URL      = "https://api.groq.com/openai/v1"
TOGETHER_BASE_URL  = "https://api.together.xyz/v1"

_DEFAULT_MODELS: dict[str, dict[Role, str]] = {
    "ollama":    {"coder": "qwen2.5-coder:32b",                       "narrator": "llama3.3:70b"},
    "lmstudio":  {"coder": "local-model",                             "narrator": "local-model"},
    "groq":      {"coder": "llama-3.3-70b-versatile",                 "narrator": "llama-3.3-70b-versatile"},
    "together":  {"coder": "Qwen/Qwen2.5-Coder-32B-Instruct",         "narrator": "meta-llama/Llama-3.3-70B-Instruct-Turbo"},
    "anthropic": {"coder": "claude-sonnet-4-6",                       "narrator": "claude-sonnet-4-6"},
}

def _model_for_role(backend: str, role: Role) -> str:
    defaults = _DEFAULT_MODELS.get(backend, _DEFAULT_MODELS["ollama"])
    fallback = os.getenv("AUGHOR_MODEL", defaults[role])
    if role == "coder":
        return os.getenv("AUGHOR_CODER_MODEL", fallback)
    return os.getenv("AUGHOR_NARRATOR_MODEL", fallback)


def _build_ollama_client(model: str = "") -> instructor.Instructor:
    raw = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")
    # Reasoning models (qwen3, kimi, deepseek-r1, qwq) support native tool calling.
    # Use TOOLS mode so <think>…</think> tokens are isolated from structured output.
    # JSON mode causes reasoning tokens to pollute the output and trigger retries.
    _TOOLS_MODELS = ("qwen3", "kimi", "deepseek-r1", "qwq", "qwen-coder")
    use_tools = any(kw in model.lower() for kw in _TOOLS_MODELS)
    mode = instructor.Mode.TOOLS if use_tools else instructor.Mode.JSON
    return instructor.from_openai(raw, mode=mode)


def _build_lmstudio_client() -> instructor.Instructor:
    # LM Studio only accepts response_format.type = "json_schema" or "text",
    # not "json_object" — use JSON_SCHEMA mode which sends the full Pydantic schema.
    raw = OpenAI(base_url=LMSTUDIO_BASE_URL, api_key="lm-studio")
    return instructor.from_openai(raw, mode=instructor.Mode.JSON_SCHEMA)


def _build_groq_client() -> instructor.Instructor:
    raw = OpenAI(base_url=GROQ_BASE_URL, api_key=os.environ["GROQ_API_KEY"])
    return instructor.from_openai(raw, mode=instructor.Mode.JSON)


def _build_together_client() -> instructor.Instructor:
    raw = OpenAI(base_url=TOGETHER_BASE_URL, api_key=os.environ["TOGETHER_API_KEY"])
    return instructor.from_openai(raw, mode=instructor.Mode.JSON)


def _build_anthropic_client() -> instructor.Instructor:
    import anthropic
    raw = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return instructor.from_anthropic(raw)


class LLMProvider:
    """Call .complete() with a Pydantic response_model, get a typed object back."""

    def __init__(self, backend: str, role: Role):
        self.backend = backend
        self.role = role
        self._model = _model_for_role(backend, role)
        if backend == "ollama":
            self._client = _build_ollama_client(self._model)
        elif backend == "lmstudio":
            self._client = _build_lmstudio_client()
        elif backend == "groq":
            self._client = _build_groq_client()
        elif backend == "together":
            self._client = _build_together_client()
        elif backend == "anthropic":
            self._client = _build_anthropic_client()
        else:
            raise ValueError(f"Unknown backend: {backend!r}. Use 'ollama', 'lmstudio', 'groq', 'together', or 'anthropic'.")

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

        return self._client.chat.completions.create(
            model=self._model,
            temperature=temperature,
            response_model=response_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )


# Per-role provider cache — one client per role per process
_providers: dict[Role, LLMProvider] = {}
_cached_backend: str | None = None


def get_provider(role: Role = "coder") -> LLMProvider:
    global _cached_backend
    backend = os.getenv("AUGHOR_BACKEND", "ollama")
    if backend != _cached_backend:
        # Backend changed (e.g. env var updated at runtime) — flush cache
        _providers.clear()
        _cached_backend = backend
    if role not in _providers:
        _providers[role] = LLMProvider(backend=backend, role=role)
    return _providers[role]


