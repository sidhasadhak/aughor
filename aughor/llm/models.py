"""The model catalogue — what goes in the model picker.

Two sources, merged, in this order of authority:

1. **live** — the backend's own model list, fetched when reachable. OpenRouter
   publishes a public ``/models`` endpoint; the OpenAI-compatible backends serve
   the same path with a key; Ollama and LM Studio serve theirs locally. This is
   the list that is actually correct, because it comes from the thing that will
   serve the request.
2. **custom** — models the user typed and chose to keep. Persisted in
   ``data/llm_config.json`` beside the rest of the inference config, so they
   survive restarts and travel with the deployment.

**No model id is hardcoded here** (operator decision, 2026-08-15). There used to be
a third source — ``KNOWN_MODELS``, a curated per-backend floor so the picker was
never empty offline — and it is gone: 28 ids across 7 backends that this repo had
to keep true about somebody else's catalogue. It could not be kept true. Its own
comments are the receipt: ``qwen3-coder-next:cloud`` retired mid-life,
``kimi-k2.6:cloud`` silently became subscription-only, two OpenRouter ids never
existed at all. A list that ships stale is worse than no list, because the picker
presents it with the same authority as the live one.

So the catalogue is now exactly what the provider says it serves, plus what the
operator typed. When the live fetch fails the picker is EMPTY and says why — an
honest empty beats a confident wrong. The field remains free text, so a model the
fetch missed is still reachable by typing it.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

_CACHE_TTL_S = 300.0
_cache: dict[str, tuple[float, list[dict]]] = {}
_cache_lock = threading.Lock()


# ── custom entries (persisted in llm_config.json) ────────────────────────────

def _config() -> dict:
    from aughor.llm.provider import read_config
    return read_config()


def custom_models(backend: str) -> list[str]:
    entry = (_config().get("custom_models") or {}).get(backend)
    return [str(m) for m in entry] if isinstance(entry, list) else []


def _write_custom(backend: str, models: list[str]) -> list[str]:
    from aughor.llm.provider import write_config

    cfg = dict(_config())
    customs = dict(cfg.get("custom_models") or {})
    if models:
        customs[backend] = models
    else:
        customs.pop(backend, None)
    cfg["custom_models"] = customs
    write_config(cfg)        # shares a file with encrypted keys — one writer owns it
    return models


def add_custom_model(backend: str, model: str) -> list[str]:
    """Keep a typed model in the picker. Idempotent."""
    from aughor.llm.provider import BACKENDS

    if backend not in BACKENDS:
        raise ValueError(f"unknown backend {backend!r}")
    name = (model or "").strip()
    if not name:
        raise ValueError("model is required")
    existing = custom_models(backend)
    if name in existing:
        return existing
    return _write_custom(backend, [*existing, name])


def remove_custom_model(backend: str, model: str) -> list[str]:
    """Drop a custom entry. Live entries are not removable — they are not ours to
    delete, and hiding a model the backend actually serves would make the picker
    disagree with reality."""
    from aughor.llm.provider import BACKENDS

    if backend not in BACKENDS:
        raise ValueError(f"unknown backend {backend!r}")
    name = (model or "").strip()
    existing = custom_models(backend)
    if name not in existing:
        raise ValueError(f"{name!r} is not a custom entry for {backend}")
    return _write_custom(backend, [m for m in existing if m != name])


# ── live fetch ────────────────────────────────────────────────────────────────

def _openai_style_models(base_url: str, key: str, *, timeout: float) -> list[dict]:
    """``GET {base}/models`` — the OpenAI-compatible shape most backends serve."""
    import httpx

    url = base_url.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    r = httpx.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    data = r.json().get("data") or []
    out = []
    for m in data:
        mid = m.get("id") or m.get("name")
        if not mid:
            continue
        entry = {"id": str(mid), "source": "live"}
        # OpenRouter enriches this; the rest usually do not. Surfaced because
        # picking a model without knowing its context window is guesswork.
        if m.get("context_length"):
            entry["context"] = m["context_length"]
        name = m.get("name")
        if name and name != mid:
            entry["label"] = str(name)
        pricing = m.get("pricing") or {}
        prompt_price = pricing.get("prompt")
        if prompt_price is not None:
            try:
                entry["free"] = float(prompt_price) == 0.0
            except (TypeError, ValueError):
                pass
        out.append(entry)
    return out


def _ollama_models(base_url: str, *, timeout: float) -> list[dict]:
    """Ollama's native tag list. Its OpenAI-compat base ends in /v1, which the
    tags endpoint does not live under."""
    import httpx

    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    r = httpx.get(root.rstrip("/") + "/api/tags", timeout=timeout)
    r.raise_for_status()
    return [{"id": m["name"], "source": "live"}
            for m in (r.json().get("models") or []) if m.get("name")]


def _anthropic_models(key: str, *, timeout: float) -> list[dict]:
    import httpx

    r = httpx.get("https://api.anthropic.com/v1/models",
                  headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                  timeout=timeout)
    r.raise_for_status()
    return [{"id": m["id"], "source": "live",
             **({"label": m["display_name"]} if m.get("display_name") else {})}
            for m in (r.json().get("data") or []) if m.get("id")]


def fetch_live_models(backend: str, *, timeout: float = 6.0) -> tuple[list[dict], str]:
    """``(models, error)`` from the backend itself. Never raises.

    An error is RETURNED rather than swallowed so the UI can say "showing the
    built-in list because the live fetch failed, here is why" instead of
    presenting a stale fallback as though it were authoritative.
    """
    from aughor.llm.provider import active_base_url, active_key

    base_url = active_base_url(backend)
    key = active_key(backend)
    try:
        if backend == "ollama":
            return _ollama_models(base_url, timeout=timeout), ""
        if backend == "anthropic":
            if not key:
                return [], "no API key configured"
            return _anthropic_models(key, timeout=timeout), ""
        # OpenRouter's /models is public; the rest need the key.
        if backend != "openrouter" and backend != "lmstudio" and not key:
            return [], "no API key configured"
        return _openai_style_models(base_url, key, timeout=timeout), ""
    except Exception as exc:
        return [], f"{type(exc).__name__}: {str(exc)[:160]}"


def _record_context_windows(live: list[dict]) -> None:
    """Persist ``{model_id: context_length}`` from a live catalogue into the runtime
    config, for :func:`aughor.llm.profile.declared_context`.

    This is what replaced the hand-maintained capability table: the tier a binding runs
    under is derived from the context window the PROVIDER declares, so it can be right
    about a model nobody here has heard of, and cannot go stale in the direction that
    silently shrinks a capable model's budgets.

    Only ever adds or updates, and only from a successful fetch — a provider that omits
    ``context_length`` leaves the previous value alone rather than erasing it. Best
    effort: this file is shared with the encrypted keys, so a write failure must degrade
    the tier (to BASELINE) and never the config.
    """
    sizes = {str(m["id"]): int(m["context"]) for m in live
             if m.get("id") and isinstance(m.get("context"), int) and m["context"] > 0}
    if not sizes:
        return
    try:
        from aughor.llm.provider import read_config, write_config
        cfg = dict(read_config())
        known = dict(cfg.get("model_context") or {})
        if all(known.get(k) == v for k, v in sizes.items()):
            return                      # nothing new — do not touch the keys file
        known.update(sizes)
        cfg["model_context"] = known
        write_config(cfg)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "context-window capture is best-effort; the tier falls back to baseline",
                 counter="llm.model_context")


def list_models(backend: str, *, refresh: bool = False,
                timeout: float = 6.0) -> dict[str, Any]:
    """The picker's payload for one backend.

    Live results are cached for ``_CACHE_TTL_S`` — the catalogue moves in days,
    not seconds, and re-fetching on every keystroke would make the settings
    screen depend on a remote host being fast.
    """
    from aughor.llm.provider import BACKENDS

    if backend not in BACKENDS:
        raise ValueError(f"unknown backend {backend!r}")

    live: list[dict] = []
    error = ""
    if os.environ.get("AUGHOR_LLM_MODEL_FETCH", "1") != "0":
        with _cache_lock:
            hit = _cache.get(backend)
        if hit and not refresh and (time.monotonic() - hit[0]) < _CACHE_TTL_S:
            live = hit[1]
        else:
            live, error = fetch_live_models(backend, timeout=timeout)
            if live:
                with _cache_lock:
                    _cache[backend] = (time.monotonic(), live)
                _record_context_windows(live)

    seen = {m["id"] for m in live}
    merged = list(live)
    customs = custom_models(backend)
    for mid in customs:                                 # user-kept, always present
        if mid not in seen:
            merged.append({"id": mid, "source": "custom"})
            seen.add(mid)
        else:
            for m in merged:
                if m["id"] == mid:
                    m["source"] = "custom"              # removable even if also live
    return {
        "backend": backend,
        "models": merged,
        "custom": customs,
        "live_count": len(live),
        "live": bool(live),
        "error": error,
        # Kept as a key so the payload shape is stable for the UI, but always empty:
        # nothing ships a default model any more, so there is nothing to suggest.
        "defaults": {},
    }


def clear_cache(backend: Optional[str] = None) -> None:
    with _cache_lock:
        _cache.pop(backend, None) if backend else _cache.clear()
