"""LLM provider abstraction — Ollama, LM Studio, Groq, Together, Anthropic, or Gemini.

Two roles, two model slots:
  coder   — SQL generation, hypothesis scoring, decomposition (structured reasoning)
  narrator — report synthesis (long-form prose)
  fast     — a cheaper narrator sub-tier for simpler per-phase interpret calls

Configuration precedence (highest first):
  1. runtime config   data/llm_config.json — set from the Settings → Inference UI
                      (POST /llm/config); API keys are secretvault-encrypted.
  2. environment      AUGHOR_BACKEND / AUGHOR_*_MODEL / *_API_KEY / *_BASE_URL
  3. built-in default per-backend models + localhost base URLs

So the provider is switchable at runtime (no restart, no env edit) AND still honours
the env for headless/CI runs. `get_provider(role)` is process-global and rebuilds
its cache whenever the config changes (a version bump on every save).

Env vars (still honoured as the layer-2 fallback):
  AUGHOR_BACKEND, AUGHOR_CODER_MODEL, AUGHOR_NARRATOR_MODEL, AUGHOR_FAST_NARRATOR_MODEL,
  AUGHOR_MODEL, OLLAMA_BASE_URL, LMSTUDIO_BASE_URL, GROQ_API_KEY, TOGETHER_API_KEY,
  ANTHROPIC_API_KEY, GEMINI_API_KEY, AUGHOR_FALLBACK_MODEL, AUGHOR_FALLBACK_DISABLED.
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import random
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Literal, Optional, Type, TypeVar

import instructor
from openai import OpenAI
from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

Role = Literal["coder", "narrator", "fast"]
ROLES: tuple[Role, ...] = ("coder", "narrator", "fast")
BACKENDS: tuple[str, ...] = ("ollama", "lmstudio", "groq", "together", "anthropic",
                             "gemini", "openrouter")
# Backends that require an API key (the others are local).
NEEDS_KEY: tuple[str, ...] = ("groq", "together", "anthropic", "gemini", "openrouter")
# Backends whose base URL is user-overridable (the hosted ones are fixed).
LOCAL_BACKENDS: tuple[str, ...] = ("ollama", "lmstudio")

_KEY_ENV = {"groq": "GROQ_API_KEY", "together": "TOGETHER_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
            "gemini": "GEMINI_API_KEY", "openrouter": "OPENROUTER_API_KEY"}
_BASE_URL_ENV = {"ollama": "OLLAMA_BASE_URL", "lmstudio": "LMSTUDIO_BASE_URL"}

_DEFAULT_BASE_URLS = {
    "ollama":   "http://localhost:11434/v1",
    "lmstudio": "http://localhost:1234/v1",
    "groq":     "https://api.groq.com/openai/v1",
    "together": "https://api.together.xyz/v1",
    # Google Gemini's OpenAI-compatibility endpoint (chat/completions + tools + json_schema).
    "gemini":   "https://generativelanguage.googleapis.com/v1beta/openai/",
    # OpenRouter — one key, many vendors, OpenAI-compatible. Its /models endpoint is
    # public, which is what lets the model picker show a live catalogue.
    "openrouter": "https://openrouter.ai/api/v1",
}

_DEFAULT_MODELS: dict[str, dict[Role, str]] = {
    "ollama":    {"coder": "qwen3-coder-next:cloud", "narrator": "kimi-k2.6:cloud", "fast": "qwen3-coder-next:cloud"},
    "lmstudio":  {"coder": "local-model",                      "narrator": "local-model"},
    "groq":      {"coder": "llama-3.3-70b-versatile",          "narrator": "llama-3.3-70b-versatile"},
    "together":  {"coder": "Qwen/Qwen2.5-Coder-32B-Instruct",  "narrator": "meta-llama/Llama-3.3-70B-Instruct-Turbo"},
    "anthropic": {"coder": "claude-sonnet-4-6",                "narrator": "claude-sonnet-4-6"},
    # PINNED to flash-lite, deliberately against the "…-latest aliases never deprecate" rule used
    # elsewhere here — the free-tier REQUEST budgets differ by 25×, and that dominates. Measured on
    # the live account 2026-07-22 (Google AI Studio rate-limit dashboard):
    #     gemini-flash-latest → Gemini 3.6 Flash :   5 RPM,  20 requests/DAY   ← unusable
    #     gemini-3.1-flash-lite                  :  15 RPM, 500 requests/DAY
    # 20 requests a day cannot serve a single briefing, and this binding is what the failover chain
    # lands on. The alias would silently re-point at whatever "latest flash" becomes, whose quota is
    # unknown; the whole reason for this binding is a quota we have actually measured. A pinned id
    # that is retired fails loudly (404) and the fallback chain covers it.
    # On a PAID key, bump coder → "gemini-pro-latest" for stronger SQL generation.
    "gemini":    {"coder": "gemini-3.1-flash-lite", "narrator": "gemini-3.1-flash-lite",
                  "fast": "gemini-3.1-flash-lite"},
    # OpenRouter ids are "vendor/model". These defaults are free-tier so a fresh key
    # works immediately; the picker's live catalogue is the way to reach paid models.
    # Free-tier ids VERIFIED against OpenRouter's live /models (the first pass
    # guessed two that do not exist). Coder gets the strongest coder available
    # because wrong SQL is the expensive failure; fast gets the throughput pick.
    "openrouter": {"coder": "nvidia/nemotron-3-ultra-550b-a55b:free",
                   "narrator": "google/gemma-4-31b-it:free",
                   "fast": "nvidia/nemotron-3-nano-30b-a3b:free"},
}

_CONFIG_PATH = Path(__file__).parent.parent.parent / "data" / "llm_config.json"


def _flag(name: str, default: str = "") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


# Output ceiling for OpenAI-compatible backends. The Anthropic path has always passed
# max_tokens=4096 (the SDK requires it); every other backend passed NOTHING, so generation was
# bounded only by the model stopping or by our own 600s deadline. On a reasoning model that is a
# runaway: the 2026-07-22 OpenRouter export shows three requests that each ran the full 600s and
# emitted 13.5k / 15.4k / 18.9k tokens of pure reasoning with NO finish_reason and no usable
# output — 4 requests (6% of traffic) burned 58% of all output tokens for nothing.
_MAX_OUTPUT_TOKENS = 4096
# Reasoning effort for backends that expose it. 93% of completion tokens in that same export were
# reasoning, so this is the direct lever on output volume. OpenRouter reads `reasoning` from the
# request body; other OpenAI-compat shims reject unknown fields, so it is sent ONLY where it is
# known to be understood (see _complete_on's retry-without-extras path for the rest).
_REASONING_EFFORT_DEFAULT = "low"


def _max_output_tokens() -> int:
    """Cap on generated tokens per call (AUGHOR_MAX_OUTPUT_TOKENS)."""
    return max(256, _int_env("AUGHOR_MAX_OUTPUT_TOKENS", _MAX_OUTPUT_TOKENS))


def _reasoning_extra_body(backend: str) -> dict:
    """Provider-specific body extras that bound reasoning, or ``{}``.

    ``AUGHOR_REASONING_EFFORT`` accepts low|medium|high, or ``off`` to omit the field
    entirely (for a binding that rejects it)."""
    effort = os.getenv("AUGHOR_REASONING_EFFORT", _REASONING_EFFORT_DEFAULT).strip().lower()
    if backend != "openrouter" or effort in ("", "off", "none"):
        return {}
    if effort not in ("low", "medium", "high"):
        effort = _REASONING_EFFORT_DEFAULT
    return {"reasoning": {"effort": effort}}


def _fallback_model() -> str:
    """Anthropic model used when the primary backend fails. Defaults to the
    latest Opus; override with AUGHOR_FALLBACK_MODEL (e.g. claude-opus-4-6)."""
    return os.getenv("AUGHOR_FALLBACK_MODEL", "claude-opus-4-8")


# Order the fallback chain is tried in when the primary backend fails. Anthropic stays
# first so an install that already had a key keeps its exact previous behaviour; the rest
# follow so a install WITHOUT an Anthropic key (the common case) still has somewhere to go
# — which is the whole point: the fallback used to be Anthropic-or-nothing, so the majority
# of installs had no fallback at all and a rate-limited role model surfaced as a 500.
# Local backends are deliberately absent: they need no key, so they would always look
# "configured" and a fallback would hang against a server that isn't running. Name one in
# AUGHOR_FALLBACK_BACKENDS to opt in.
_FALLBACK_ORDER: tuple[str, ...] = ("anthropic", "gemini", "groq", "together", "openrouter")


def _fallback_backends() -> tuple[str, ...]:
    """Backends to try, in order, when the primary fails.

    Override with AUGHOR_FALLBACK_BACKENDS (comma-separated, e.g. "gemini,groq") to pin a
    chain — order is honoured as given, and unknown names are dropped rather than raising,
    so a typo degrades to a shorter chain instead of breaking every LLM call."""
    raw = os.getenv("AUGHOR_FALLBACK_BACKENDS", "").strip()
    if not raw:
        return _FALLBACK_ORDER
    return tuple(b for b in (p.strip() for p in raw.split(",")) if b in BACKENDS)


# A backend that answered "quota exhausted" will answer the same way for every call until
# its allowance resets, so re-probing it once per LLM call adds a guaranteed-failed round
# trip to each one. A briefing fans out into dozens of calls: that cost a wasted probe every
# time and turned a 9s brief into 76s. Cooldown is in-process and self-healing — the entry
# simply expires, so a topped-up account recovers on its own without a restart.
_QUOTA_COOLDOWN_S = 900.0
_quota_cooldown: dict[str, float] = {}
_quota_lock = threading.Lock()


def _mark_quota_exhausted(backend: str) -> None:
    with _quota_lock:
        _quota_cooldown[backend] = time.monotonic() + max(
            0.0, _float_env("AUGHOR_QUOTA_COOLDOWN_S", _QUOTA_COOLDOWN_S))


def _in_quota_cooldown(backend: str) -> bool:
    with _quota_lock:
        until = _quota_cooldown.get(backend)
        if until is None:
            return False
        if time.monotonic() >= until:      # expired — let it prove itself again
            del _quota_cooldown[backend]
            return False
        return True


def _fallback_model_for(backend: str, role: Role) -> str:
    """The model a fallback backend should use for this role.

    Anthropic keeps AUGHOR_FALLBACK_MODEL (the pre-existing contract); every other backend
    uses its own role default, so a narrator falling back to Gemini gets Gemini's narrator
    model rather than something pinned for a different vendor."""
    if backend == "anthropic":
        return _fallback_model()
    defaults = _DEFAULT_MODELS.get(backend, {})
    return defaults.get(role) or defaults.get("narrator", "")


# ── Runtime config (data/llm_config.json) ────────────────────────────────────
# Schema: {backend?: str, models?: {coder,narrator,fast}, base_urls?: {ollama,lmstudio},
#          keys?: {groq,together,anthropic}}  — keys are secretvault-encrypted strings.

_runtime: Optional[dict] = None
_config_version = 0          # bumped on every config (re)load
_cache_version = -1          # the version the _providers cache was built against
_providers: dict[Role, "LLMProvider"] = {}
# Providers pinned to an explicit model (per-agent override), keyed by (role, model).
_pinned_providers: dict[tuple, "LLMProvider"] = {}

# Per-agent LLM model: a run can pin the model its LLM calls use (set by the kernel from
# the agent's governance, override-wins). A contextvar so it scopes to the run without
# threading a model arg through every get_provider() call site — mirrors the metering hook.
_run_model: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "aughor_run_model", default=None
)


def set_run_model(model: Optional[str]):
    """Pin the LLM model for the current run/context (returns a reset token)."""
    return _run_model.set((model or "").strip() or None)


def reset_run_model(token) -> None:
    try:
        _run_model.reset(token)
    except (ValueError, LookupError) as exc:
        logger.debug("reset_run_model: stale token ignored (%s)", exc)  # token from another context


def current_run_model() -> Optional[str]:
    return _run_model.get()


def _read_config() -> dict:
    try:
        if _CONFIG_PATH.exists():
            data = json.loads(_CONFIG_PATH.read_text())
            return data if isinstance(data, dict) else {}
    except Exception:
        logger.warning("llm: could not read %s — using env/defaults", _CONFIG_PATH, exc_info=True)
    return {}


def _cfg() -> dict:
    global _runtime
    if _runtime is None:
        _runtime = _read_config()
    return _runtime


def load_config() -> None:
    """(Re)load the on-disk config and invalidate the provider cache. Call on
    startup and after any change so live providers pick up the new settings."""
    global _runtime, _config_version
    _runtime = _read_config()
    _config_version += 1


# ── Public accessors for the rest of the inference plane ─────────────────────
# The catalogue (aughor/llm/models.py) needs the effective base URL, key and
# defaults for a backend, and a way to persist. Exposed as public names so it
# imports an interface rather than reaching into this module's internals.

def read_config() -> dict:
    """The on-disk config as written (secrets still encrypted)."""
    return _read_config()


def write_config(cfg: dict) -> None:
    """Persist and reload. One writer, because the file holds encrypted keys and
    the mkdir/write/chmod/reload sequence must not drift between call sites."""
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    try:
        _CONFIG_PATH.chmod(0o600)  # it holds encrypted keys
    except Exception:
        logger.debug("could not chmod %s (non-fatal)", _CONFIG_PATH, exc_info=True)
    load_config()


def active_base_url(backend: str) -> str:
    return _active_base_url(backend)


def active_key(backend: str) -> str:
    return _active_key(backend)


def default_models(backend: str) -> dict:
    return dict(_DEFAULT_MODELS.get(backend, {}))


# ── Active accessors (runtime config → env → default) ─────────────────────────

def _active_backend() -> str:
    return ((_cfg().get("backend") or os.getenv("AUGHOR_BACKEND") or "ollama")).strip()


def _active_base_url(backend: str) -> str:
    cfg_url = (_cfg().get("base_urls") or {}).get(backend)
    if cfg_url:
        return cfg_url.strip()
    env = _BASE_URL_ENV.get(backend)
    if env and os.getenv(env):
        return os.getenv(env).strip()
    return _DEFAULT_BASE_URLS.get(backend, "")


def _active_key(backend: str) -> str:
    from aughor.secretvault import decrypt_secret
    enc = (_cfg().get("keys") or {}).get(backend)
    if enc:
        return decrypt_secret(enc) or ""
    return os.getenv(_KEY_ENV.get(backend, ""), "") or ""


def _env_model_for_role(backend: str, role: Role) -> str:
    """Layer-2/3 model resolution (env → built-in default), unchanged from before."""
    defaults = _DEFAULT_MODELS.get(backend, _DEFAULT_MODELS["ollama"])
    base_role = "narrator" if role in ("narrator", "fast") else role
    fallback = os.getenv("AUGHOR_MODEL", defaults.get(role, defaults[base_role]))
    if role == "coder":
        return os.getenv("AUGHOR_CODER_MODEL", fallback)
    narrator_model = os.getenv("AUGHOR_NARRATOR_MODEL", fallback)
    if role == "fast":
        return os.getenv("AUGHOR_FAST_NARRATOR_MODEL", narrator_model)
    return narrator_model


def measured_cache_mode(backend: str, model: str) -> Optional[str]:
    """The empirically-measured cache_mode for a binding, or None if never probed.
    Persisted in the runtime config under ``measured_cache: {"backend:model": mode}`` by
    the prefix-cache probe (`aughor/llm/cache_probe.py`); consulted by the capability seam
    so a measured verdict overrides the declared default (evidence > guess)."""
    return (_cfg().get("measured_cache") or {}).get(f"{backend}:{model}") or None


def set_measured_cache_mode(backend: str, model: str, mode: Optional[str]) -> None:
    """Persist (or clear, with ``mode=None``) a measured cache_mode for one binding, then
    reload so live capabilities reflect it. Written by the probe after it runs."""
    cfg = dict(_read_config())
    measured = dict(cfg.get("measured_cache") or {})
    key = f"{backend}:{model}"
    if mode:
        measured[key] = mode
    else:
        measured.pop(key, None)
    cfg["measured_cache"] = measured
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    load_config()


def resolve_binding(role: Role = "coder", *, model: Optional[str] = None) -> tuple[str, str, str]:
    """The single binding resolver — the effective ``(backend, model, base_url)`` for a role.

    Shared by :func:`get_provider` (data plane, builds the client) and
    :func:`aughor.platform.inference.vend_llm` (control-plane seam, describes the binding),
    so a vended :class:`InferenceCapability` always matches the binding a real call uses.
    Model precedence mirrors :func:`get_provider`: explicit pin → run/agent contextvar
    (``set_run_model``) → role default — i.e. Org default → … → Agent override."""
    backend = _active_backend()
    pinned = (model or current_run_model() or "").strip()
    eff_model = pinned or _active_model(backend, role)
    return backend, eff_model, _active_base_url(backend)


def _active_model(backend: str, role: Role) -> str:
    cfg = _cfg()
    cfg_model = (cfg.get("models") or {}).get(role)
    if cfg_model:
        return cfg_model.strip()
    # If a backend was explicitly chosen in the runtime config, the env model
    # overrides (AUGHOR_*_MODEL — tuned for the env backend) no longer apply; use
    # this backend's built-in default. Pure-env runs keep the original precedence.
    if cfg.get("backend"):
        d = _DEFAULT_MODELS.get(backend, _DEFAULT_MODELS["ollama"])
        return d.get(role) or d["narrator"]   # explicit per-role default; narrator is the fallback
    return _env_model_for_role(backend, role)


# ── Client builders ───────────────────────────────────────────────────────────

def _build_ollama_client(model: str, base_url: str) -> instructor.Instructor:
    # Cloud-backed models (e.g. kimi:cloud, qwen3-coder-next:cloud) go through Ollama
    # to an external API and can hang indefinitely without a timeout.
    # connect=30s, read=300s (5 min) — enough for any realistic single inference call.
    import httpx
    _timeout = httpx.Timeout(connect=30.0, read=300.0, write=30.0, pool=10.0)
    raw = OpenAI(base_url=base_url, api_key="ollama", timeout=_timeout)
    # Reasoning models (qwen3, kimi, deepseek-r1, qwq) support native tool calling.
    # Use TOOLS mode so <think>…</think> tokens are isolated from structured output.
    # JSON mode causes reasoning tokens to pollute the output and trigger retries.
    _TOOLS_MODELS = ("qwen3", "kimi", "deepseek-r1", "qwq", "qwen-coder")
    use_tools = any(kw in model.lower() for kw in _TOOLS_MODELS)
    mode = instructor.Mode.TOOLS if use_tools else instructor.Mode.JSON
    return instructor.from_openai(raw, mode=mode)


def _build_lmstudio_client(base_url: str) -> instructor.Instructor:
    # LM Studio only accepts response_format.type = "json_schema" or "text",
    # not "json_object" — use JSON_SCHEMA mode which sends the full Pydantic schema.
    raw = OpenAI(base_url=base_url, api_key="lm-studio")
    return instructor.from_openai(raw, mode=instructor.Mode.JSON_SCHEMA)


def _build_openai_compat(base_url: str, api_key: str) -> instructor.Instructor:
    if not api_key:
        raise RuntimeError("missing API key for this backend — set it in Settings → Inference")
    raw = OpenAI(base_url=base_url, api_key=api_key)
    return instructor.from_openai(raw, mode=instructor.Mode.JSON)


def _build_gemini_client(base_url: str, api_key: str) -> instructor.Instructor:
    """Google Gemini via its OpenAI-compatibility endpoint. Gemini 2.x are thinking models,
    so TOOLS mode (schema-native function-calling structured output) keeps reasoning tokens out
    of the JSON — same rationale as the ollama reasoning-model path, where plain JSON mode lets
    <thinking> pollute the output. Tune with AUGHOR_GEMINI_INSTRUCTOR_MODE (TOOLS|JSON|JSON_SCHEMA)."""
    if not api_key:
        raise RuntimeError("missing Gemini API key — set it in Settings → Inference (or GEMINI_API_KEY)")
    raw = OpenAI(base_url=base_url, api_key=api_key)
    mode = getattr(instructor.Mode, os.getenv("AUGHOR_GEMINI_INSTRUCTOR_MODE", "TOOLS").upper(),
                   instructor.Mode.TOOLS)
    return instructor.from_openai(raw, mode=mode)


def _build_anthropic_client(api_key: str) -> instructor.Instructor:
    if not api_key:
        raise RuntimeError("missing Anthropic API key — set it in Settings → Inference")
    import anthropic
    raw = anthropic.Anthropic(api_key=api_key)
    return instructor.from_anthropic(raw)


def _extract_usage(raw) -> tuple[int, int]:
    """(prompt_tokens, completion_tokens) from a raw OpenAI/Anthropic completion,
    best-effort. Returns (0, 0) when unavailable (e.g. some local backends omit
    usage) — metering is honest about what it could measure, never guesses."""
    usage = getattr(raw, "usage", None)
    if usage is None:
        return 0, 0
    pt = getattr(usage, "prompt_tokens", None)          # OpenAI-compatible
    if pt is None:
        pt = getattr(usage, "input_tokens", 0)           # Anthropic
    ct = getattr(usage, "completion_tokens", None)       # OpenAI-compatible
    if ct is None:
        ct = getattr(usage, "output_tokens", 0)          # Anthropic
    try:
        return int(pt or 0), int(ct or 0)
    except Exception:
        return 0, 0


# ── Resilience: per-endpoint concurrency cap + transient-error retry/backoff ──
# Cloud inference endpoints throttle and intermittently 429/5xx/timeout under sustained load
# (observed: a benchmark run hung after ~2.5h of unbounded parallel calls). This is a platform
# concern, not a benchmark one — every Aughor LLM call goes through here. We (a) cap concurrent
# in-flight calls per base_url with a shared semaphore so bursts don't trip throttling, and
# (b) retry transient failures with exponential backoff + jitter under an overall deadline.
# All knobs are env-tunable; defaults are conservative and behaviour-preserving on the happy path.

_SEMAPHORES: dict[str, threading.Semaphore] = {}
_SEM_LOCK = threading.Lock()


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _semaphore_for(base_url: str) -> threading.Semaphore:
    """Shared per-endpoint concurrency gate (cap = AUGHOR_LLM_MAX_CONCURRENCY, default 4)."""
    key = base_url or "default"
    with _SEM_LOCK:
        sem = _SEMAPHORES.get(key)
        if sem is None:
            sem = threading.Semaphore(max(1, _int_env("AUGHOR_LLM_MAX_CONCURRENCY", 4)))
            _SEMAPHORES[key] = sem
        return sem


_TRANSIENT_TYPES = (
    "RateLimitError", "APITimeoutError", "APIConnectionError", "InternalServerError",
    "ReadTimeout", "ConnectTimeout", "PoolTimeout", "WriteTimeout", "TimeoutException",
    "ConnectError", "RemoteProtocolError",
)
_TRANSIENT_MSGS = (
    "timeout", "timed out", "rate limit", "too many requests", "overloaded",
    "temporarily unavailable", "service unavailable", "connection reset", "connection error",
    "econnreset", "bad gateway", "gateway timeout",
    # A per-minute allowance throttle. Safe to retry because _is_quota_exhausted runs
    # FIRST and has already claimed the day-scale and spent-balance wordings — so what
    # reaches here is the kind that clears within the backoff ladder (Gemini's free tier
    # caps requests per minute and phrases it exactly this way).
    "quota exceeded", "exceeded your current quota",
)
# A 429 that will NOT clear on the retry timescale: a daily/monthly allowance or a spent
# balance, not a per-minute throttle. Retrying these burns the whole backoff ladder
# (~15s) on a counter that resets tomorrow — and, worse, delays the fallback that
# WOULD have answered.
#
# These markers are deliberately narrow. The first cut also matched "billing" and
# "quota exceeded", which sounded day-scale but are exactly the words Gemini uses for its
# per-MINUTE free-tier limit ("You exceeded your current quota … limit: 5 … check your
# plan and billing details"). That misread put a backend into a 15-minute cooldown over a
# 60-second throttle. Only phrases naming a day, or a balance that needs topping up, count.
_QUOTA_EXHAUSTED_MSGS = (
    "per-day", "per day", "daily limit", "requests per day",
    # Google names the exhausted quota in a camel-case id with no separators —
    # "GenerateRequestsPerDayPerProjectPerModel-FreeTier" — which none of the spaced
    # forms above match. Its message ALSO carries a "retry in 36s" that is simply wrong
    # for a daily cap, so missing this meant retrying a day-long block three times.
    "perday",
    "insufficient_quota", "credit limit exceeded", "add credits", "payment required",
)


# Providers usually say how long to wait — Gemini as "Please retry in 42.3s", OpenAI-compatible
# shims as a retryDelay field or a Retry-After header. Our ladder tops out around 15s, so a 42s
# window was never survived: we exhausted the retries and failed a call that would have succeeded.
# Honour the server's own number when it gives one.
_RETRY_AFTER_RE = re.compile(
    r"(?:retry(?:\s+again)?\s+in|retry[-_]?after|retrydelay)\D{0,12}?(\d+(?:\.\d+)?)\s*s",
    re.IGNORECASE,
)
_RETRY_AFTER_MAX_S = 120.0


def _retry_after_seconds(exc: BaseException) -> Optional[float]:
    """Seconds the provider asked us to wait, or None. Capped so a pathological value
    cannot park a request for minutes; the overall deadline still bounds everything."""
    m = _RETRY_AFTER_RE.search(str(exc))
    if not m:
        return None
    try:
        return min(_RETRY_AFTER_MAX_S, max(0.0, float(m.group(1))))
    except ValueError:
        return None


# Overall budget for one logical call, INCLUDING backoff. Was 600s, which is the only reason
# the runaway generations in the 2026-07-22 export ran exactly 600.2s — our own deadline was
# the sole brake. Not lowered to 90s: the same export contains a legitimate call that finished
# at 86.7s, and a ceiling that kills real work is worse than a loose one. 180s bounds the
# runaway (now also capped by max_tokens) with real headroom above the observed honest maximum.
_DEADLINE_S = 180.0

# 429/quota-shaped: the errors where ANOTHER attempt is itself another request against the limit.
_RATE_LIMIT_MSGS = ("rate limit", "too many requests", "quota", "resource_exhausted", "429")


def _is_rate_limited(exc: BaseException) -> bool:
    """True when the failure is the endpoint refusing on volume, not a transient fault."""
    if type(exc).__name__ == "RateLimitError":
        return True
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status == 429:
        return True
    return any(k in str(exc).lower() for k in _RATE_LIMIT_MSGS)


def _is_quota_exhausted(exc: BaseException) -> bool:
    """True when the error is an exhausted allowance rather than a momentary throttle.

    Such an error is 'transient' by status (429/402) but not by timescale, so it is
    routed to the fallback chain immediately instead of through the retry ladder."""
    return any(k in str(exc).lower() for k in _QUOTA_EXHAUSTED_MSGS)


def _is_transient(exc: BaseException) -> bool:
    """True for errors worth retrying (throttle / transient network), False for real failures
    (validation, 4xx-other, auth) which must surface immediately.

    Checked before the type/status tests below, because an exhausted quota arrives as a
    RateLimitError with status 429 and 'rate limit' in the message — it would match all
    three and be retried pointlessly."""
    if _is_quota_exhausted(exc):
        return False
    if type(exc).__name__ in _TRANSIENT_TYPES:
        return True
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        status = getattr(exc, "status", None)
    if isinstance(status, int) and (status == 429 or 500 <= status < 600):
        return True
    msg = str(exc).lower()
    return any(k in msg for k in _TRANSIENT_MSGS)


def _record_llm_call(*, backend: str, model: str, role: str,
                     prompt_tokens: Optional[int], completion_tokens: Optional[int],
                     ms: float, ok: bool = True, error_class: Optional[str] = None,
                     retries: int = 0, temperature: Optional[float] = None,
                     fallback: bool = False, streamed: bool = False,
                     system: Optional[str] = None, user: Optional[str] = None,
                     output: Any = None) -> None:
    """Mirror one model call into the session log (flag ``obs.session_log``).

    ``metering.record_llm`` sums the same numbers into a per-run aggregate, which
    answers "what did this run cost" but not "which model was asked, how long it
    took, how hard it had to try, or whether the fallback quietly swapped it
    mid-run" — the questions a measurement must answer before it can be trusted.
    The dedicated per-call record (``telemetry.log_generation``) existed but had
    no call sites, so all of it was discarded.

    Provider, model and token counts go to real columns rather than payload JSON:
    "tokens by model this week" should be a GROUP BY, not a JSON extraction —
    especially through ``aughor_ops``, where an agent writes the SQL itself.

    ``prompt_tokens``/``completion_tokens`` are ``None`` when the backend did not
    report usage. That is deliberately distinct from 0: several local backends
    omit usage entirely, and folding them into zero makes every cost aggregate
    silently wrong.

    Strict no-op when the flag is off; never raises (the sink swallows).
    """
    from aughor.obs import session_log
    session_log.emit(
        session_log.LLM_CALL, name=model, ok=ok, duration_ms=round(ms, 1),
        error_class=error_class, provider=backend, model=model,
        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        retries=retries or None,
        payload={"role": role, "fallback": fallback, "streamed": streamed,
                 **({"temperature": temperature} if temperature is not None else {}),
                 **({"usage_reported": False} if prompt_tokens is None
                    and completion_tokens is None else {}),
                 # Content only when `obs.prompt_capture` is separately opted in;
                 # the helper owns the capping + truncation-marking policy.
                 **session_log.capture_prompt(system, user, _response_text(output))},
    )


def _response_text(output: Any) -> Optional[str]:
    """A model response as text, across the shapes the three paths produce
    (pydantic model, dict, str). Only ever consumed under `obs.prompt_capture`;
    returns None when there is nothing to record."""
    if output is None:
        return None
    try:
        dump = getattr(output, "model_dump_json", None)
        if callable(dump):
            return dump()
        if isinstance(output, (dict, list)):
            import json as _json
            return _json.dumps(output, default=str)
        return str(output)
    except Exception:
        return None


def _usage_or_none(raw) -> tuple[Optional[int], Optional[int]]:
    """Token counts, or (None, None) when the backend reported no usage at all.

    ``_extract_usage`` collapses that case to (0, 0) because metering only needs
    a number to add; the per-call record needs to know it was never measured."""
    if getattr(raw, "usage", None) is None:
        return None, None
    return _extract_usage(raw)


def _run_resilient(do, base_url: str, *, stats: dict | None = None,
                   max_retries: Optional[int] = None):
    """Run ``do()`` under the per-endpoint semaphore, retrying transient errors with exponential
    backoff + jitter, bounded by AUGHOR_LLM_MAX_RETRIES (default 3) and an overall deadline
    AUGHOR_LLM_DEADLINE_S (default 180s, see _DEADLINE_S). Non-transient errors raise immediately.

    ``stats`` (optional, mutated in place) reports ``retries`` — the count was
    previously local and discarded, so a model that only ever succeeds on its
    second attempt looked identical to one that never struggles. A degrading
    endpoint should be visible before it starts failing outright."""
    if stats is not None:
        stats["retries"] = 0
    sem = _semaphore_for(base_url)
    max_retries = (max(0, int(max_retries)) if max_retries is not None
                   else max(0, _int_env("AUGHOR_LLM_MAX_RETRIES", 3)))
    deadline = time.monotonic() + max(1.0, _float_env("AUGHOR_LLM_DEADLINE_S", _DEADLINE_S))
    attempt = 0
    while True:
        with sem:  # hold a slot only during the call, never during backoff sleep
            try:
                return do()
            except Exception as e:
                # A rate limit gets ONE retry, not the full ladder. Every attempt is itself a
                # REQUEST against the very limit that just rejected us, so firing three more is
                # how a throttle becomes a spiral — the live Gemini account peaked at 19 RPM
                # against a 15 RPM cap with a 429-dominated error chart. One retry, at the delay
                # the server itself asked for, is the most that can help.
                # min(), not a bare 1: this is a CEILING on the ladder, and written as a
                # plain assignment it became a FLOOR — a caller that explicitly asked for
                # max_retries=0 got one retry anyway, plus a sleep honouring the server's
                # retry-after (up to 120s). That silently defeats the health check, which
                # passes 0 precisely so it reports what is true NOW; and the health check is
                # the likeliest place to meet a 429 (12 of 62 requests in the 2026-07-22
                # export were health probes, against a 50/day cap).
                budget = min(1, max_retries) if _is_rate_limited(e) else max_retries
                if not _is_transient(e) or attempt >= budget or time.monotonic() >= deadline:
                    raise
                attempt += 1
                if stats is not None:
                    stats["retries"] = attempt
                err_name = type(e).__name__   # `e` is unbound after the except block
                err_budget = budget           # ditto — report the ladder we actually ran
                wait = min(30.0, 2.0 ** attempt) + random.uniform(0.0, 0.5 * attempt)
                # The provider's own number wins when it is LONGER than our guess: a
                # throttle that says "retry in 42s" is not survivable on a 15s ladder.
                asked = _retry_after_seconds(e)
                if asked is not None and asked > wait:
                    wait = asked
        if time.monotonic() + wait >= deadline:
            wait = max(0.0, deadline - time.monotonic())
        logger.warning("llm: transient error (%s); retry %d/%d in %.1fs",
                       err_name, attempt, err_budget, wait)
        time.sleep(wait)


class LLMProvider:
    """Call .complete() with a Pydantic response_model, get a typed object back."""

    def __init__(self, backend: str, role: Role, *,
                 model: Optional[str] = None, api_key: Optional[str] = None,
                 base_url: Optional[str] = None):
        self.backend = backend
        self.role = role
        self._model = model or _active_model(backend, role)
        key = api_key if api_key is not None else _active_key(backend)
        url = base_url or _active_base_url(backend)
        self._base_url = url
        if backend == "ollama":
            self._client = _build_ollama_client(self._model, url)
        elif backend == "lmstudio":
            self._client = _build_lmstudio_client(url)
        elif backend in ("groq", "together", "openrouter"):
            # OpenRouter is OpenAI-compatible, so it shares this client. Registering
            # a backend in the metadata tables without a branch here is silent until
            # someone selects it: the constructor falls through to the error below,
            # which then lists the backend it just refused. test_every_backend_builds
            # covers the whole set so that cannot recur.
            self._client = _build_openai_compat(url, key)
        elif backend == "gemini":
            self._client = _build_gemini_client(url, key)
        elif backend == "anthropic":
            self._client = _build_anthropic_client(key)
        else:
            raise ValueError(f"Unknown backend: {backend!r}. Use one of {', '.join(BACKENDS)}.")

    @property
    def capability(self):
        """The vended :class:`InferenceCapability` describing this provider's binding —
        backend, model, endpoint, and the declared profile (cache_mode, privacy_class, …).
        The seam Layer-A/Layer-B optimisation and governance routing dispatch on
        (PLATFORM_ARCHITECTURE.md §5b). Lazy import avoids a module-load cycle."""
        from aughor.org.context import current_org_id
        from aughor.platform.inference import capability_for

        return capability_for(self.backend, self._model, self.role, self._base_url, current_org_id())

    def complete(
        self,
        system: str,
        user: str,
        response_model: Type[T],
        temperature: float = 0.1,
    ) -> T:
        self._warn_if_over_window(system, user)
        # A primary known to be out of allowance is skipped rather than re-probed: the
        # answer cannot have changed, and the wasted round trip is paid by EVERY call.
        if _in_quota_cooldown(self.backend) and self._fallback_candidates():
            primary_exc: Exception = RuntimeError(
                f"{self.backend} is in quota cooldown (allowance exhausted)")
            return self._complete_via_fallback(
                system, user, response_model, temperature, primary_exc)
        try:
            return self._complete_on(self._client, self.backend, self._model,
                                     system, user, response_model, temperature,
                                     base_url=self._base_url, role=self.role)
        except Exception as primary_exc:
            if _is_quota_exhausted(primary_exc):
                _mark_quota_exhausted(self.backend)
            # Resilience: if the primary backend is unreachable, erroring, or out of
            # allowance, transparently fall back to the next CONFIGURED backend. Enabled
            # by default; disable with AUGHOR_FALLBACK_DISABLED=1, pin the order with
            # AUGHOR_FALLBACK_BACKENDS. This used to be Anthropic-or-nothing, which meant
            # an install without an Anthropic key had no fallback at all: an exhausted
            # free-tier quota took down every brief with an opaque 500.
            if not self._fallback_candidates():
                raise
            return self._complete_via_fallback(
                system, user, response_model, temperature, primary_exc)

    def _complete_via_fallback(self, system: str, user: str, response_model: Type[T],
                               temperature: float, primary_exc: BaseException) -> T:
        """Walk the fallback chain for one call. Raises ``primary_exc`` if every link fails."""
        for backend in self._fallback_candidates():
            fb = self._fallback_provider(backend)
            if fb is None:
                continue
            logger.warning("provider: %s failed (%s); falling back to %s %s",
                           self.backend, str(primary_exc)[:120], backend, fb._model)
            try:
                return self._complete_on(fb._client, backend, fb._model,
                                         system, user, response_model, temperature,
                                         base_url=fb._base_url,
                                         role=self.role, fallback=True)
            except Exception as fb_exc:
                # Try the next link rather than giving up on the first miss — the
                # chain exists precisely because any one backend can be down or spent.
                if _is_quota_exhausted(fb_exc):
                    _mark_quota_exhausted(backend)
                logger.warning("provider: fallback %s also failed (%s)",
                               backend, str(fb_exc)[:120])
        raise primary_exc  # every link failed — surface the ORIGINAL cause, not the last

    def complete_streaming(
        self,
        *,
        system: str,
        user: str,
        response_model: Type[T],
        temperature: float = 0.0,
        text_field: str,
        on_text: Callable[[str], None],
    ) -> T:
        """Like :meth:`complete`, but streams the growing value of one text field
        (``text_field``) through ``on_text`` while the model writes it — instructor
        partial streaming (CK-0.2). Each callback receives the FULL text so far
        (replace semantics, never a suffix delta), and only when it grew.

        Self-healing: any failure — before or during the stream, including a final
        partial that doesn't validate as a complete ``response_model`` — falls back
        to the blocking :meth:`complete` (which itself has the Anthropic fallback).
        Partial ``on_text`` calls that already happened are harmless: the caller's
        terminal event always carries the authoritative final value."""
        self._warn_if_over_window(system, user)
        try:
            return self._stream_on(self._client, self.backend, self._model,
                                   system, user, response_model, temperature,
                                   text_field, on_text, base_url=self._base_url,
                                   role=self.role)
        except Exception as stream_exc:
            logger.warning("provider: partial streaming failed (%s); falling back to blocking complete()",
                           str(stream_exc)[:120])
            return self.complete(system=system, user=user,
                                 response_model=response_model, temperature=temperature)

    def _warn_if_over_window(self, system: str, user: str) -> None:
        """Layer-A safety net (§5b.3): a single, universal overflow check on every call.
        Warn-only — never truncates (silently cutting evidence would risk grounding); the
        signal is "the bound model is too small for this prompt; bind a larger-context one".
        Best-effort: a budgeting hiccup must never block a real completion."""
        try:
            from aughor.llm.context_budget import overflow_tokens

            over = overflow_tokens(system, user, self.capability.max_context)
            if over:
                est, budget = over
                logger.warning(
                    "llm: prompt ~%d tok exceeds %s's usable window ~%d tok (ctx %d) — "
                    "the call may be rejected or truncated; bind a larger-context model.",
                    est, self._model, budget, self.capability.max_context)
        except Exception:
            logger.debug("llm: overflow check skipped", exc_info=True)

    @staticmethod
    def _complete_on(client, backend, model, system, user, response_model, temperature,
                     base_url: str = "", *, role: str = "", fallback: bool = False,
                     max_retries: Optional[int] = None):
        from aughor.kernel import metering
        if backend == "anthropic":
            endpoint = client.messages
            kwargs = dict(model=model, max_tokens=_max_output_tokens(), system=system,
                          messages=[{"role": "user", "content": user}],
                          response_model=response_model)
        else:
            endpoint = client.chat.completions
            kwargs = dict(model=model, temperature=temperature, response_model=response_model,
                          max_tokens=_max_output_tokens(),
                          messages=[{"role": "system", "content": system},
                                    {"role": "user", "content": user}])
            extra = _reasoning_extra_body(backend)
            if extra:
                kwargs["extra_body"] = extra
        # Prefer create_with_completion (instructor ≥1.0) so we can read token usage
        # off the raw response. Falls back to create() with no usage on older clients.
        cwc = getattr(endpoint, "create_with_completion", None)

        def _call(kw):
            if cwc is not None:
                return cwc(**kw)
            return endpoint.create(**kw), None

        def _do():
            try:
                return _call(kwargs)
            except Exception as exc:
                # Same shape as the stream_options fallback below: an OpenAI-compat shim that
                # rejects `reasoning` must not take the call down with it. Retry once without the
                # extras, and only for a 4xx-shaped complaint — a rate limit or outage has to stay
                # transient so the retry ladder and fallback chain still see it.
                if "extra_body" not in kwargs or _is_transient(exc) or _is_quota_exhausted(exc):
                    raise
                logger.warning("llm: %s rejected the reasoning extras (%s); retrying without",
                               backend, str(exc)[:100])
                return _call({k: v for k, v in kwargs.items() if k != "extra_body"})

        _t0 = time.monotonic()
        _stats: dict = {}
        try:
            # concurrency cap + transient-error retry/backoff
            out, raw = _run_resilient(_do, base_url, stats=_stats, max_retries=max_retries)
        except Exception as exc:
            # A call that fails past its retries must still leave a record —
            # otherwise "which model fails" is unanswerable precisely when it
            # matters, and the log flatters the provider it is meant to audit.
            _record_llm_call(backend=backend, model=model, role=role,
                             prompt_tokens=None, completion_tokens=None,
                             ms=(time.monotonic() - _t0) * 1000.0, ok=False,
                             error_class=type(exc).__name__,
                             retries=_stats.get("retries", 0), temperature=temperature,
                             fallback=fallback, system=system, user=user)
            raise
        pt, ct = _extract_usage(raw)
        _ms = (time.monotonic() - _t0) * 1000.0
        metering.record_llm(pt, ct, _ms)
        _pt, _ct = _usage_or_none(raw)
        _record_llm_call(backend=backend, model=model, role=role, prompt_tokens=_pt,
                         completion_tokens=_ct, ms=_ms, retries=_stats.get("retries", 0),
                         temperature=temperature, fallback=fallback,
                         system=system, user=user, output=out)
        metering.check_budget()   # in-context budget (chat/insight path); no-op for jobs
        return out

    @staticmethod
    def _json_stream_instruction(response_model) -> str:
        """A compact 'answer as this JSON object' instruction for the raw streaming
        path (which bypasses instructor's own schema prompt). Field names + types
        only — the terminal ``model_validate`` is the real contract, and a mismatch
        falls back to the blocking instructor call."""
        props = response_model.model_json_schema().get("properties", {})
        fields = ", ".join(f'"{k}" ({v.get("type", "value")})' for k, v in props.items())
        return (f"\n\nReturn ONLY a JSON object with fields: {fields}. "
                "No markdown fences, no prose outside the JSON.")

    @staticmethod
    def _stream_on(client, backend, model, system, user, response_model, temperature,
                   text_field, on_text, base_url: str = "", *, role: str = ""):
        from aughor.kernel import metering
        if backend == "anthropic":
            # instructor's anthropic wrapper streams tool-mode JSON reliably.
            create_partial = getattr(client.messages, "create_partial", None)
            if create_partial is None:
                raise RuntimeError("anthropic client has no create_partial — partial streaming unavailable")
            kwargs = dict(model=model, max_tokens=_max_output_tokens(), system=system,
                          messages=[{"role": "user", "content": user}],
                          response_model=response_model)

            def _do():
                # Drain the WHOLE stream inside the resilient closure: the per-endpoint
                # semaphore is released the moment do() returns, so the slot must be
                # held for the stream's entire life.
                last, seen = None, ""
                for partial in create_partial(**kwargs):
                    last = partial
                    text = getattr(partial, text_field, None)
                    if isinstance(text, str) and len(text) > len(seen):
                        seen = text
                        try:
                            on_text(text)   # full text so far — replace semantics
                        except Exception:
                            logger.debug("llm: on_text callback failed; delta dropped", exc_info=True)
                if last is None:
                    raise RuntimeError("partial stream yielded no objects")
                return last, getattr(last, "_raw_response", None)

            _t0 = time.monotonic()
            _stats: dict = {}
            try:
                last, raw_usage_src = _run_resilient(_do, base_url, stats=_stats)
            except Exception as exc:
                _record_llm_call(backend=backend, model=model, role=role,
                                 prompt_tokens=None, completion_tokens=None,
                                 ms=(time.monotonic() - _t0) * 1000.0, ok=False,
                                 error_class=type(exc).__name__,
                                 retries=_stats.get("retries", 0),
                                 temperature=temperature, streamed=True,
                                 system=system, user=user)
                raise
            pt, ct = _extract_usage(raw_usage_src)
            _ms = (time.monotonic() - _t0) * 1000.0
            metering.record_llm(pt, ct, _ms)
            _pt, _ct = _usage_or_none(raw_usage_src)
            _record_llm_call(backend=backend, model=model, role=role, prompt_tokens=_pt,
                             completion_tokens=_ct, ms=_ms,
                             retries=_stats.get("retries", 0), temperature=temperature,
                             streamed=True, system=system, user=user, output=last)
            metering.check_budget()
            # Partial[...] objects skipped required-field validation mid-stream —
            # re-validate the terminal one; a failure heals via the complete() fallback.
            return response_model.model_validate(last.model_dump())

        # OpenAI-compatible family (ollama/lmstudio/groq/together): stream RAW and
        # parse the growing buffer ourselves. instructor's partial parser chokes the
        # moment a model emits any preamble/fence before the JSON ("expected value at
        # line 1 column 1" — observed live on glm via the ollama shim); scanning to
        # the first '{' and partial-parsing with jiter tolerates that entire class,
        # and stream_options.include_usage gives REAL token accounting.
        import json as _json
        import jiter as _jiter
        raw_client = getattr(client, "client", None)   # instructor wrapper → underlying OpenAI client
        if raw_client is None:
            raise RuntimeError(f"{backend} instructor wrapper exposes no raw client — streaming unavailable")
        sys_prompt = system + LLMProvider._json_stream_instruction(response_model)
        # max_tokens rides here for the same reason it rides on _complete_on: without it the
        # only brake on a reasoning model is the deadline. It was set on the blocking path only,
        # so the three highest-volume calls in the app — the quick-path headline, the post-answer
        # insight, and the deep synthesis — are all STREAMED and were all still unbounded.
        # It is deliberately NOT part of the degrade ladder below: `max_tokens` is core OpenAI,
        # every compat shim takes it, and a cap that can be silently dropped is not a cap.
        base_kwargs = dict(model=model, temperature=temperature, stream=True,
                           max_tokens=_max_output_tokens(),
                           messages=[{"role": "system", "content": sys_prompt},
                                     {"role": "user", "content": user}])
        extra = _reasoning_extra_body(backend)
        if extra:
            base_kwargs["extra_body"] = extra

        # Degrade ladder, richest first. `stream_options` and `reasoning` are both shim-optional
        # and an endpoint that has never heard of one rejects the whole request, so drop them one
        # at a time rather than lose the call.
        _ladder = [dict(stream_options={"include_usage": True}, **base_kwargs)]
        if extra:
            _ladder.append({k: v for k, v in _ladder[0].items() if k != "extra_body"})
        _ladder.append({k: v for k, v in base_kwargs.items() if k != "extra_body"})

        def _open_stream():
            last = len(_ladder) - 1
            for i, kw in enumerate(_ladder):
                try:
                    return raw_client.chat.completions.create(**kw)
                except Exception as exc:
                    # Only a 4xx-shaped "I don't know that field" earns a degrade. A transient
                    # error or a quota block must propagate untouched: re-sending it here is
                    # another request against the very limit that just refused us (#200), and it
                    # would hide the failure from the retry ladder and the fallback chain.
                    if i == last or _is_transient(exc) or _is_quota_exhausted(exc):
                        raise
                    logger.warning("llm: %s rejected a streaming extra (%s); degrading",
                                   backend, str(exc)[:100])

        def _do():
            # Semaphore held for the stream's whole life (drained fully in here).
            stream = _open_stream()
            buf, seen, usage = "", "", None
            for chunk in stream:
                usage = getattr(chunk, "usage", None) or usage
                if not (chunk.choices and chunk.choices[0].delta):
                    continue
                piece = chunk.choices[0].delta.content
                if not piece:
                    continue
                buf += piece
                start = buf.find("{")
                if start < 0:
                    continue   # still in a preamble/fence
                try:
                    obj = _jiter.from_json(buf[start:].encode(), partial_mode="trailing-strings")
                except Exception:
                    continue   # incomplete escape mid-chunk etc. — next chunk heals it
                text = obj.get(text_field) if isinstance(obj, dict) else None
                if isinstance(text, str) and len(text) > len(seen):
                    seen = text
                    try:
                        on_text(text)   # full text so far — replace semantics
                    except Exception:
                        logger.debug("llm: on_text callback failed; delta dropped", exc_info=True)
            start, end = buf.find("{"), buf.rfind("}")
            if start < 0 or end <= start:
                raise RuntimeError("stream produced no JSON object")
            return _json.loads(buf[start:end + 1]), usage

        _t0 = time.monotonic()
        _stats: dict = {}
        try:
            final_dict, usage = _run_resilient(_do, base_url, stats=_stats)
        except Exception as exc:
            _record_llm_call(backend=backend, model=model, role=role,
                             prompt_tokens=None, completion_tokens=None,
                             ms=(time.monotonic() - _t0) * 1000.0, ok=False,
                             error_class=type(exc).__name__,
                             retries=_stats.get("retries", 0),
                             temperature=temperature, streamed=True,
                             system=system, user=user)
            raise
        from types import SimpleNamespace
        _raw = SimpleNamespace(usage=usage)
        pt, ct = _extract_usage(_raw)   # extractor reads .usage
        _ms = (time.monotonic() - _t0) * 1000.0
        metering.record_llm(pt, ct, _ms)
        _pt, _ct = _usage_or_none(_raw)
        _record_llm_call(backend=backend, model=model, role=role, prompt_tokens=_pt,
                         completion_tokens=_ct, ms=_ms, retries=_stats.get("retries", 0),
                         temperature=temperature, streamed=True,
                         system=system, user=user, output=final_dict)
        metering.check_budget()   # in-context budget (chat/insight path); no-op for jobs
        # Terminal validation is the contract; a mismatch heals via complete() fallback.
        return response_model.model_validate(final_dict)

    def _fallback_provider(self, backend: str) -> Optional["LLMProvider"]:
        """A provider bound to `backend` for this role, or None if it cannot be built.

        Building a full LLMProvider (rather than a bare client) is what keeps the chain
        honest: model resolution, base URL and client construction all come from the one
        constructor that already knows every backend, so a backend added there is
        fallback-capable for free."""
        cache = getattr(self, "_fb_providers", None)
        if cache is None:
            cache = self._fb_providers = {}
        if backend not in cache:
            try:
                cache[backend] = LLMProvider(
                    backend=backend, role=self.role,
                    model=_fallback_model_for(backend, self.role) or None,
                )
            except Exception as exc:
                logger.debug("provider: fallback %s unavailable (%s)", backend, exc)
                cache[backend] = None
        return cache[backend]

    def _fallback_candidates(self) -> list[str]:
        """Configured backends worth trying for this call, in order — never the primary,
        only those holding a key (an unkeyed backend fails identically every time, so
        trying it just adds latency to a call that is already failing), and never one
        currently in quota cooldown."""
        if _flag("AUGHOR_FALLBACK_DISABLED"):
            return []
        return [b for b in _fallback_backends()
                if b != self.backend
                and (b not in NEEDS_KEY or _active_key(b))
                and not _in_quota_cooldown(b)]


def get_provider(role: Role = "coder", *, model: Optional[str] = None) -> LLMProvider:
    """Process-global provider for `role`. Rebuilds when the config changes.

    When a model is pinned — explicitly via ``model=`` or implicitly by the current run's
    ``set_run_model`` (the per-agent override) — returns a provider bound to that model,
    cached per ``(role, model)``. With no pin, the normal role-default provider is used, so
    unpinned code is unaffected."""
    global _cache_version
    if _cache_version != _config_version:
        _providers.clear()
        _pinned_providers.clear()
        _cache_version = _config_version
    pinned = (model or current_run_model() or "").strip()
    if pinned:
        key = (role, pinned)
        if key not in _pinned_providers:
            _pinned_providers[key] = LLMProvider(_active_backend(), role, model=pinned)
        return _pinned_providers[key]
    if role not in _providers:
        _providers[role] = LLMProvider(_active_backend(), role)
    return _providers[role]


# ── Config management (used by the /llm/config API) ───────────────────────────

def current_config() -> dict:
    """A secret-free view of the effective config, for the Settings UI.

    `models`/`base_urls` are the *effective* values (what calls actually use);
    `keys_set` says whether a key is available (config OR env) — never the value.
    `capabilities` is the per-role vended profile (§5b) — what the bound model can do
    and, crucially for BYO-model governance, its `privacy_class` (local · private_endpoint
    · public_api). All non-secret; surfaced so Settings → Inference shows it plainly."""
    from aughor.platform.inference import capability_for

    cfg = _cfg()
    backend = _active_backend()
    base_url = _active_base_url(backend)

    def _capability(role: Role) -> dict:
        m = _active_model(backend, role)
        cap = capability_for(backend, m, role, base_url,
                             cache_mode_override=measured_cache_mode(backend, m))
        return {
            "cache_mode": cap.cache_mode,
            "tooling": cap.tooling,
            "structured_output": cap.structured_output,
            "token_accounting": cap.token_accounting,
            "max_context": cap.max_context,
            "privacy_class": cap.privacy_class,
            "cost": cap.cost,
        }

    return {
        "backend": backend,
        # effective values (what calls actually use):
        "models": {r: _active_model(backend, r) for r in ROLES},
        "base_urls": {b: _active_base_url(b) for b in LOCAL_BACKENDS},
        "keys_set": {b: bool(_active_key(b)) for b in NEEDS_KEY},
        # the vended capability profile per role (§5b, Invariant #7):
        "capabilities": {r: _capability(r) for r in ROLES},
        # explicit overrides on disk (so the UI shows set vs default), never secrets:
        "models_set": dict(cfg.get("models") or {}),
        "base_urls_set": dict(cfg.get("base_urls") or {}),
        "backends": list(BACKENDS),
        "needs_key": list(NEEDS_KEY),
        "local_backends": list(LOCAL_BACKENDS),
        "default_models": _DEFAULT_MODELS,
    }


def set_config(patch: dict) -> dict:
    """Merge `patch` into the on-disk config and reload. Returns current_config().

    - models / base_urls: a non-empty string sets it; "" clears it back to default.
    - keys: a new string is encrypted; "" clears it; a masked/None value is left as-is.
    """
    from aughor.secretvault import encrypt_secret, is_masked

    cfg = dict(_read_config())

    if patch.get("backend"):
        if patch["backend"] not in BACKENDS:
            raise ValueError(f"unknown backend {patch['backend']!r}")
        cfg["backend"] = patch["backend"]

    if isinstance(patch.get("models"), dict):
        models = dict(cfg.get("models") or {})
        for r, m in patch["models"].items():
            if r not in ROLES:
                continue
            if m and str(m).strip():
                models[r] = str(m).strip()
            else:
                models.pop(r, None)
        cfg["models"] = models

    if isinstance(patch.get("base_urls"), dict):
        urls = dict(cfg.get("base_urls") or {})
        for b, u in patch["base_urls"].items():
            if b not in LOCAL_BACKENDS:
                continue
            if u and str(u).strip():
                urls[b] = str(u).strip()
            else:
                urls.pop(b, None)
        cfg["base_urls"] = urls

    if isinstance(patch.get("keys"), dict):
        keys = dict(cfg.get("keys") or {})
        for b, k in patch["keys"].items():
            if b not in NEEDS_KEY:
                continue
            if k is None or is_masked(k):
                continue  # unchanged
            if str(k).strip() == "":
                keys.pop(b, None)  # cleared
            else:
                keys[b] = encrypt_secret(str(k).strip())
        cfg["keys"] = keys

    write_config(cfg)
    return current_config()


# Health-check verdicts, keyed (backend, model) → (expires_at, result). A connection test fires
# one real completion PER BOUND MODEL, and the 2026-07-22 OpenRouter export shows those 113-token
# probes were 12 of 62 requests — 19% of the traffic, against a 50-request DAILY cap. Roughly ten
# of fifty daily requests spent re-proving that the models exist. A verdict is stable on the
# minute scale; the UI can still force a fresh probe.
_PING_TTL_S = 300.0
_ping_cache: dict[tuple[str, str], tuple[float, dict]] = {}
_ping_lock = threading.Lock()


def _ping_cached(backend: str, model: str, role: Role = "coder", *, force: bool = False) -> dict:
    """`_ping` behind a short TTL. ``force`` always re-probes (an operator asking "is it up NOW")."""
    ttl = max(0.0, _float_env("AUGHOR_PING_TTL_S", _PING_TTL_S))
    key = (backend, model)
    if not force and ttl:
        with _ping_lock:
            hit = _ping_cache.get(key)
            if hit and time.monotonic() < hit[0]:
                return {**hit[1], "cached": True}
    result = _ping(backend, model, role)
    if ttl:
        with _ping_lock:
            _ping_cache[key] = (time.monotonic() + ttl, result)
    return result


def _ping(backend: str, model: str, role: Role = "coder") -> dict:
    """One tiny real completion against an explicit (backend, model)."""
    class _Ping(BaseModel):
        ok: bool

    t0 = time.monotonic()
    try:
        prov = LLMProvider(backend, role, model=model)
        # The fallback would mask a real failure — test the chosen backend directly.
        # max_retries=0: a health check reports what is true NOW. Backing off a 429
        # for 30s to eventually report the same rate limit is the wrong trade when
        # someone is waiting on a button.
        prov._complete_on(prov._client, backend, prov._model,
                          "You are a health check. Reply with ok=true.",
                          "Return ok=true.", _Ping, 0.0, max_retries=0)
        return {"model": prov._model, "ok": True,
                "ms": round((time.monotonic() - t0) * 1000, 1)}
    except Exception as e:
        return {"model": model, "ok": False, "error": str(e)[:240],
                "ms": round((time.monotonic() - t0) * 1000, 1)}


def test_provider(backend: Optional[str] = None, model: Optional[str] = None, *,
                  include_agents: bool = False, force: bool = False) -> dict:
    """Validate a backend with real completions. Returns {ok, backend, model, results[]}.

    With no explicit ``model`` this tests EVERY DISTINCT model the deployment
    would actually use — the three role bindings, plus the per-agent pins when
    ``include_agents``. It previously tested only the coder model, so a green
    result said nothing about the narrator or fast bindings even though they can
    be different models with their own ids, quotas and availability.

    Models are deduplicated: most setups point several roles at one model, and
    three identical pings would be three times the cost for one fact. Each result
    reports which roles/agents map to it.
    """
    b = (backend or _active_backend()).strip()
    if b not in BACKENDS:
        return {"ok": False, "backend": b, "error": f"unknown backend {b!r}", "results": []}

    is_active = b == _active_backend()
    # model -> what uses it. A non-active backend is probed with ITS OWN defaults;
    # the active model is tuned for the active backend and would 404 elsewhere.
    targets: dict[str, list[str]] = {}
    if model:
        targets[model] = ["explicit"]
    else:
        for role in ROLES:
            m = (_active_model(b, role) if is_active
                 else _DEFAULT_MODELS.get(b, _DEFAULT_MODELS["ollama"]).get(role))
            if m:
                targets.setdefault(m, []).append(role)
        if include_agents and is_active:
            try:
                from aughor.kernel.agents import effective_governance, list_charters
                for c in list_charters():
                    pinned = effective_governance(c.id).model
                    if pinned:
                        targets.setdefault(pinned, []).append(f"agent:{c.id}")
            except Exception as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "connection test: agent pins unresolved; roles still tested",
                         counter="llm.test.agents")

    def _role_for(used_by: list[str]) -> Role:
        for u in used_by:
            if u in ROLES:
                return u  # type: ignore[return-value]
        return "coder"

    # Independent calls — run them together so the wait is the slowest model, not
    # the sum. The per-endpoint semaphore still bounds real concurrency.
    results = []
    if len(targets) == 1:
        (m, used_by), = targets.items()
        results.append({**_ping_cached(b, m, _role_for(used_by), force=force), "used_by": used_by})
    else:
        from aughor.kernel.concurrency import ContextThreadPoolExecutor
        with ContextThreadPoolExecutor(max_workers=min(len(targets), 4)) as pool:
            futures = {pool.submit(_ping_cached, b, m, _role_for(u), force=force): (m, u)
                       for m, u in targets.items()}
            for fut in futures:
                m, used_by = futures[fut]
                results.append({**fut.result(), "used_by": used_by})
    results.sort(key=lambda r: (ROLES.index(r["used_by"][0])
                                if r["used_by"] and r["used_by"][0] in ROLES else 99))

    failed = [r for r in results if not r["ok"]]
    coder_model = next((r["model"] for r in results if "coder" in r["used_by"]),
                       results[0]["model"] if results else (model or ""))
    out = {
        "ok": not failed,
        "backend": b,
        "model": coder_model,          # back-compat: the headline model
        "results": results,
        "tested": len(results),
        "failed": len(failed),
    }
    if failed:
        out["error"] = f"{failed[0]['model']}: {failed[0].get('error', 'failed')}"
    return out
