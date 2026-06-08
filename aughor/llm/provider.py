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

import logging
import os
from typing import Literal, Type, TypeVar

import instructor

logger = logging.getLogger(__name__)


def _flag(name: str, default: str = "") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _fallback_model() -> str:
    """Anthropic model used when the primary backend fails. Defaults to the
    latest Opus; override with AUGHOR_FALLBACK_MODEL (e.g. claude-opus-4-6)."""
    return os.getenv("AUGHOR_FALLBACK_MODEL", "claude-opus-4-8")
from openai import OpenAI
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

Role = Literal["coder", "narrator", "fast"]

OLLAMA_BASE_URL    = os.getenv("OLLAMA_BASE_URL",    "http://localhost:11434/v1")
LMSTUDIO_BASE_URL  = os.getenv("LMSTUDIO_BASE_URL",  "http://localhost:1234/v1")
GROQ_BASE_URL      = "https://api.groq.com/openai/v1"
TOGETHER_BASE_URL  = "https://api.together.xyz/v1"

_DEFAULT_MODELS: dict[str, dict[Role, str]] = {
    "ollama":    {"coder": "qwen2.5-coder:32b",                       "narrator": "kimi-k2.6:cloud"},
    "lmstudio":  {"coder": "local-model",                             "narrator": "local-model"},
    "groq":      {"coder": "llama-3.3-70b-versatile",                 "narrator": "llama-3.3-70b-versatile"},
    "together":  {"coder": "Qwen/Qwen2.5-Coder-32B-Instruct",         "narrator": "meta-llama/Llama-3.3-70B-Instruct-Turbo"},
    "anthropic": {"coder": "claude-sonnet-4-6",                       "narrator": "claude-sonnet-4-6"},
}

def _model_for_role(backend: str, role: Role) -> str:
    defaults = _DEFAULT_MODELS.get(backend, _DEFAULT_MODELS["ollama"])
    # "fast" is a narrator sub-tier — a cheaper/quicker model for the simpler per-phase
    # interpret calls. It shares the narrator default and falls back to the narrator model
    # when AUGHOR_FAST_NARRATOR_MODEL is unset → no behaviour change until it is configured.
    base_role = "narrator" if role in ("narrator", "fast") else role
    fallback = os.getenv("AUGHOR_MODEL", defaults[base_role])
    if role == "coder":
        return os.getenv("AUGHOR_CODER_MODEL", fallback)
    narrator_model = os.getenv("AUGHOR_NARRATOR_MODEL", fallback)
    if role == "fast":
        return os.getenv("AUGHOR_FAST_NARRATOR_MODEL", narrator_model)
    return narrator_model


def _build_ollama_client(model: str = "") -> instructor.Instructor:
    # Cloud-backed models (e.g. kimi:cloud, qwen3-coder-next:cloud) go through Ollama
    # to an external API and can hang indefinitely without a timeout.
    # connect=30s, read=300s (5 min) — enough for any realistic single inference call.
    import httpx
    _timeout = httpx.Timeout(connect=30.0, read=300.0, write=30.0, pool=10.0)
    raw = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama", timeout=_timeout)
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
        try:
            return self._complete_on(self._client, self.backend, self._model,
                                     system, user, response_model, temperature)
        except Exception as primary_exc:
            # Resilience: if the primary backend (e.g. local/cloud Ollama) is
            # unreachable or erroring, transparently fall back to Anthropic when
            # a key is configured. Enabled by default; disable with
            # AUGHOR_FALLBACK_DISABLED=1. Model via AUGHOR_FALLBACK_MODEL
            # (default claude-opus-4-8 — the latest Opus).
            fb = self._fallback_client()
            if fb is None:
                raise
            logger.warning("provider: %s backend failed (%s); falling back to Anthropic %s",
                           self.backend, str(primary_exc)[:120], _fallback_model())
            try:
                return self._complete_on(fb, "anthropic", _fallback_model(),
                                         system, user, response_model, temperature)
            except Exception:
                raise primary_exc  # surface the original failure if fallback also fails

    @staticmethod
    def _complete_on(client, backend, model, system, user, response_model, temperature):
        if backend == "anthropic":
            return client.messages.create(
                model=model, max_tokens=4096, system=system,
                messages=[{"role": "user", "content": user}],
                response_model=response_model,
            )
        return client.chat.completions.create(
            model=model, temperature=temperature, response_model=response_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )

    def _fallback_client(self):
        """Lazily build (and cache) an Anthropic client for fallback, or None when
        unavailable (already on anthropic, disabled, or no ANTHROPIC_API_KEY)."""
        if self.backend == "anthropic":
            return None
        if _flag("AUGHOR_FALLBACK_DISABLED"):
            return None
        if not os.getenv("ANTHROPIC_API_KEY"):
            return None
        if getattr(self, "_fb_client", None) is None:
            try:
                self._fb_client = _build_anthropic_client()
            except Exception:
                self._fb_client = None
        return self._fb_client


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


