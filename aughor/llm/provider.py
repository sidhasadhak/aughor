"""LLM provider abstraction — Ollama, LM Studio, Groq, Together, or Anthropic.

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
  ANTHROPIC_API_KEY, AUGHOR_FALLBACK_MODEL, AUGHOR_FALLBACK_DISABLED.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Literal, Optional, Type, TypeVar

import instructor
from openai import OpenAI
from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

Role = Literal["coder", "narrator", "fast"]
ROLES: tuple[Role, ...] = ("coder", "narrator", "fast")
BACKENDS: tuple[str, ...] = ("ollama", "lmstudio", "groq", "together", "anthropic")
# Backends that require an API key (the others are local).
NEEDS_KEY: tuple[str, ...] = ("groq", "together", "anthropic")
# Backends whose base URL is user-overridable (the hosted ones are fixed).
LOCAL_BACKENDS: tuple[str, ...] = ("ollama", "lmstudio")

_KEY_ENV = {"groq": "GROQ_API_KEY", "together": "TOGETHER_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
_BASE_URL_ENV = {"ollama": "OLLAMA_BASE_URL", "lmstudio": "LMSTUDIO_BASE_URL"}

_DEFAULT_BASE_URLS = {
    "ollama":   "http://localhost:11434/v1",
    "lmstudio": "http://localhost:1234/v1",
    "groq":     "https://api.groq.com/openai/v1",
    "together": "https://api.together.xyz/v1",
}

_DEFAULT_MODELS: dict[str, dict[Role, str]] = {
    "ollama":    {"coder": "qwen3-coder-next:cloud", "narrator": "kimi-k2.6:cloud", "fast": "qwen3-coder-next:cloud"},
    "lmstudio":  {"coder": "local-model",                      "narrator": "local-model"},
    "groq":      {"coder": "llama-3.3-70b-versatile",          "narrator": "llama-3.3-70b-versatile"},
    "together":  {"coder": "Qwen/Qwen2.5-Coder-32B-Instruct",  "narrator": "meta-llama/Llama-3.3-70B-Instruct-Turbo"},
    "anthropic": {"coder": "claude-sonnet-4-6",                "narrator": "claude-sonnet-4-6"},
}

_CONFIG_PATH = Path(__file__).parent.parent.parent / "data" / "llm_config.json"


def _flag(name: str, default: str = "") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _fallback_model() -> str:
    """Anthropic model used when the primary backend fails. Defaults to the
    latest Opus; override with AUGHOR_FALLBACK_MODEL (e.g. claude-opus-4-6)."""
    return os.getenv("AUGHOR_FALLBACK_MODEL", "claude-opus-4-8")


# ── Runtime config (data/llm_config.json) ────────────────────────────────────
# Schema: {backend?: str, models?: {coder,narrator,fast}, base_urls?: {ollama,lmstudio},
#          keys?: {groq,together,anthropic}}  — keys are secretvault-encrypted strings.

_runtime: Optional[dict] = None
_config_version = 0          # bumped on every config (re)load
_cache_version = -1          # the version the _providers cache was built against
_providers: dict[Role, "LLMProvider"] = {}


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
        if backend == "ollama":
            self._client = _build_ollama_client(self._model, url)
        elif backend == "lmstudio":
            self._client = _build_lmstudio_client(url)
        elif backend in ("groq", "together"):
            self._client = _build_openai_compat(url, key)
        elif backend == "anthropic":
            self._client = _build_anthropic_client(key)
        else:
            raise ValueError(f"Unknown backend: {backend!r}. Use one of {', '.join(BACKENDS)}.")

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
        import time as _time
        from aughor.kernel import metering
        if backend == "anthropic":
            endpoint = client.messages
            kwargs = dict(model=model, max_tokens=4096, system=system,
                          messages=[{"role": "user", "content": user}],
                          response_model=response_model)
        else:
            endpoint = client.chat.completions
            kwargs = dict(model=model, temperature=temperature, response_model=response_model,
                          messages=[{"role": "system", "content": system},
                                    {"role": "user", "content": user}])
        # Prefer create_with_completion (instructor ≥1.0) so we can read token usage
        # off the raw response. Falls back to create() with no usage on older clients.
        _t0 = _time.monotonic()
        cwc = getattr(endpoint, "create_with_completion", None)
        if cwc is not None:
            out, raw = cwc(**kwargs)
        else:
            out, raw = endpoint.create(**kwargs), None
        pt, ct = _extract_usage(raw)
        metering.record_llm(pt, ct, (_time.monotonic() - _t0) * 1000.0)
        metering.check_budget()   # in-context budget (chat/insight path); no-op for jobs
        return out

    def _fallback_client(self):
        """Lazily build (and cache) an Anthropic client for fallback, or None when
        unavailable (already on anthropic, disabled, or no Anthropic key)."""
        if self.backend == "anthropic":
            return None
        if _flag("AUGHOR_FALLBACK_DISABLED"):
            return None
        if not _active_key("anthropic"):
            return None
        if getattr(self, "_fb_client", None) is None:
            try:
                self._fb_client = _build_anthropic_client(_active_key("anthropic"))
            except Exception:
                self._fb_client = None
        return self._fb_client


def get_provider(role: Role = "coder") -> LLMProvider:
    """Process-global provider for `role`. Rebuilds when the config changes."""
    global _cache_version
    if _cache_version != _config_version:
        _providers.clear()
        _cache_version = _config_version
    if role not in _providers:
        _providers[role] = LLMProvider(_active_backend(), role)
    return _providers[role]


# ── Config management (used by the /llm/config API) ───────────────────────────

def current_config() -> dict:
    """A secret-free view of the effective config, for the Settings UI.

    `models`/`base_urls` are the *effective* values (what calls actually use);
    `keys_set` says whether a key is available (config OR env) — never the value."""
    cfg = _cfg()
    backend = _active_backend()
    return {
        "backend": backend,
        # effective values (what calls actually use):
        "models": {r: _active_model(backend, r) for r in ROLES},
        "base_urls": {b: _active_base_url(b) for b in LOCAL_BACKENDS},
        "keys_set": {b: bool(_active_key(b)) for b in NEEDS_KEY},
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

    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    try:
        _CONFIG_PATH.chmod(0o600)  # it holds encrypted keys
    except Exception:
        logger.debug("could not chmod %s (non-fatal)", _CONFIG_PATH, exc_info=True)
    load_config()
    return current_config()


def test_provider(backend: Optional[str] = None, model: Optional[str] = None) -> dict:
    """Do a tiny real completion to validate a backend (defaults to the active one),
    using the saved/env key. Returns {ok, backend, model, error?}."""
    class _Ping(BaseModel):
        ok: bool

    b = (backend or _active_backend()).strip()
    if b not in BACKENDS:
        return {"ok": False, "backend": b, "error": f"unknown backend {b!r}"}
    if not model:
        # Probe a non-active backend with ITS own default model — the env/active
        # model is tuned for the active backend and would 404 elsewhere.
        model = (_active_model(b, "coder") if b == _active_backend()
                 else _DEFAULT_MODELS.get(b, _DEFAULT_MODELS["ollama"])["coder"])
    try:
        prov = LLMProvider(b, "coder", model=model)
        # The fallback would mask a real failure — test the chosen backend directly.
        prov._complete_on(prov._client, b, prov._model,
                          "You are a health check. Reply with ok=true.",
                          "Return ok=true.", _Ping, 0.0)
        return {"ok": True, "backend": b, "model": prov._model}
    except Exception as e:
        return {"ok": False, "backend": b, "model": model or _active_model(b, "coder"),
                "error": str(e)[:240]}
