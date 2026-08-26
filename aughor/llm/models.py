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

def _as_float(value: Any) -> Optional[float]:
    """A catalogue number as a float, or None when the provider sent something else.

    A predicate, not a try/except around the assignment: a missing or malformed price is
    an ordinary shape in a third-party payload, and a silently swallowed exception is the
    pattern this repo ratchets against.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _openai_style_models(base_url: str, key: str, *, timeout: float) -> list[dict]:
    """``GET {base}/models`` — the OpenAI-compatible shape most backends serve."""
    import httpx

    url = base_url.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    r = httpx.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    # Two shapes in the wild. OpenAI's is `{"data": [...]}` and most compatibles copy it;
    # Together answers with the BARE array. Assuming the envelope turned that into
    # `AttributeError: 'list' object has no attribute 'get'`, which `fetch_live_models`
    # dutifully reported as the picker's error — so a backend whose key was valid (the
    # fetch got a 200) showed an empty model list and could not be selected at all.
    payload = r.json()
    data = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(data, list):
        data = []
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
        # Native tool calling, as the provider declares it. This is what decides
        # instructor's TOOLS-vs-JSON mode, and it used to be a keyword list.
        params = m.get("supported_parameters")
        if isinstance(params, list):
            entry["tools"] = "tools" in params
        name = m.get("name")
        if name and name != mid:
            entry["label"] = str(name)
        pricing = m.get("pricing") or {}
        prompt_price = _as_float(pricing.get("prompt"))
        if prompt_price is not None:
            entry["free"] = prompt_price == 0.0
        # The RATE, not just whether it is zero. OpenRouter quotes USD per TOKEN as a
        # string; every cost surface in this repo works in USD per 1M, so convert once
        # here at the edge. This is what lets `obs.usage` price a call from the
        # provider's own catalogue instead of a table somebody has to hand-maintain —
        # the same reason no model id is hardcoded in this product.
        for _src, _dst in (("prompt", "price_in"), ("completion", "price_out")):
            _rate = _as_float(pricing.get(_src))
            if _rate is not None:
                entry[_dst] = _rate * 1_000_000.0
        out.append(entry)
    return out


def _ollama_root(base_url: str) -> str:
    """Ollama's native API root. Its OpenAI-compat base ends in /v1, which the
    native endpoints (/api/tags, /api/show) do not live under."""
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    return root.rstrip("/")


#: How many models one catalogue load will interrogate with /api/show. Each is its own
#: HTTP call, so an operator with a large local library must not turn opening Settings
#: into a hundred round-trips. The cap is generous against a real Ollama library and the
#: results are persisted, so a bound model gets its facts on the first load and keeps them.
_OLLAMA_DETAIL_CAP = 30


def ollama_model_facts(base_url: str, model: str, *, timeout: float = 6.0) -> dict:
    """``{"context": int, "tools": bool}`` for one Ollama model, from ``/api/show``.

    Ollama publishes both facts this codebase used to guess at from the model NAME:
    ``capabilities`` (does it do native tool calling) and
    ``model_info["<arch>.context_length"]``. Asking is strictly better than matching a
    substring — it is right about a model nobody here has heard of, and it was wrong
    about one we had: `deepseek-v4-flash:cloud` declares tools + a 1M window, matched no
    keyword, and was therefore driven in JSON mode, which returns empty content for a
    thinking model. Empty dict on any failure — the caller keeps its conservative default.
    """
    import httpx

    try:
        r = httpx.post(_ollama_root(base_url) + "/api/show", json={"model": model},
                       timeout=timeout)
        r.raise_for_status()
        doc = r.json() or {}
    except Exception:
        return {}
    out: dict = {}
    caps = doc.get("capabilities")
    if isinstance(caps, list):
        out["tools"] = "tools" in caps
    # The context key is architecture-prefixed (`deepseek4.context_length`,
    # `gemma4.context_length`), so match on the suffix rather than naming architectures —
    # naming them would be the same mistake one layer down.
    for key, value in (doc.get("model_info") or {}).items():
        if str(key).endswith(".context_length") and isinstance(value, int) and value > 0:
            out["context"] = value
            break
    return out


def _ollama_models(base_url: str, *, timeout: float) -> list[dict]:
    """Ollama's tag list, enriched with each model's declared facts.

    ``/api/tags`` alone gives only names. The per-model ``/api/show`` calls are what
    supply the context window and tool support, which is why they are worth the
    round-trips (bounded by ``_OLLAMA_DETAIL_CAP``, and cached like any catalogue).
    """
    import httpx

    root = _ollama_root(base_url)
    r = httpx.get(root + "/api/tags", timeout=timeout)
    r.raise_for_status()
    out = [{"id": m["name"], "source": "live"}
           for m in (r.json().get("models") or []) if m.get("name")]
    for entry in out[:_OLLAMA_DETAIL_CAP]:
        entry.update(ollama_model_facts(base_url, entry["id"], timeout=timeout))
    return out


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


def _record_model_facts(entries: list[dict]) -> None:
    """Persist what the provider declared about each model — the context window (read
    back by :func:`aughor.llm.profile.declared_context`) and native tool support (read
    back by :func:`aughor.llm.provider.model_supports_tools`).

    This is what replaced three hand-maintained tables: the capability tiers, the
    context-window map and the tools-mode keyword list. Every one of them matched on the
    model NAME, which is a guess about someone else's product, and each was wrong in a
    way nobody could see — the tools list did not recognise a thinking model that
    declares `tools`, so it was driven in JSON mode and returned empty content on every
    structured call.

    Only ever adds or updates, and only from a successful fetch — a provider that omits a
    field leaves the previous value alone rather than erasing it. Best effort: this file
    is shared with the encrypted keys, so a write failure must degrade a default (to the
    conservative one) and never the config.
    """
    sizes = {str(m["id"]): int(m["context"]) for m in entries
             if m.get("id") and isinstance(m.get("context"), int) and m["context"] > 0}
    tools = {str(m["id"]): bool(m["tools"]) for m in entries
             if m.get("id") and isinstance(m.get("tools"), bool)}
    if not sizes and not tools:
        return
    try:
        from aughor.llm.provider import read_config, write_config
        cfg = dict(read_config())
        ctx_known = dict(cfg.get("model_context") or {})
        tools_known = dict(cfg.get("model_tools") or {})
        if (all(ctx_known.get(k) == v for k, v in sizes.items())
                and all(tools_known.get(k) == v for k, v in tools.items())):
            return                      # nothing new — do not touch the keys file
        ctx_known.update(sizes)
        tools_known.update(tools)
        cfg["model_context"] = ctx_known
        cfg["model_tools"] = tools_known
        write_config(cfg)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "model-fact capture is best-effort; defaults stay conservative",
                 counter="llm.model_facts")


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
    # A custom entry needs its facts too, and Ollama is the case that proves it: a
    # `:cloud` model absent from /api/tags is still served, and it is exactly the kind
    # of id an operator types in by hand. Without this the model the deployment actually
    # runs on would be the one model whose capabilities nobody looked up.
    if backend == "ollama" and customs and os.environ.get("AUGHOR_LLM_MODEL_FETCH", "1") != "0":
        from aughor.llm.provider import active_base_url
        base = active_base_url(backend)
        for m in merged:
            if m.get("source") == "custom" and "tools" not in m:
                m.update(ollama_model_facts(base, m["id"], timeout=timeout))
    if merged:
        _record_model_facts(merged)
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
