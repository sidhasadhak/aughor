"""Prefix-cache probe — does this binding actually reuse a shared prompt prefix?

PLATFORM_ARCHITECTURE.md §5b.3 (Layer B): exploiting a stable prompt prefix only pays
off if the serving backend reuses the prefix KV-cache *across separate requests*. That is
certain for local Ollama, automatic on OpenAI-style providers — and **unverified** for the
shipped default `qwen3-coder-next:cloud` (Ollama Cloud multiplexes requests across workers,
so a warm cache may not survive between calls). We refuse to *assume*; we measure.

The experiment (run over the real provider, so it measures the real binding):
  • SHARED series — N calls with an identical large system prefix and a tiny varying user
    suffix. Call #1 is cold (must prefill the prefix); #2..N should be *warm* if the
    backend reuses the prefix KV across requests.
  • DISTINCT series — N calls of the same size whose prefix diverges at the first token
    (a unique tag), so the prefix can never be reused — every call is cold. This controls
    for model warm-up and load variance.

Verdict = median(shared warm) / median(distinct cold):
  • ≤ 0.60  → reuse_active   (warm calls skip the prefill — caching works)  → ``auto_prefix``
  • ≥ 0.85  → no_reuse       (warm ≈ cold — no cross-request reuse)         → ``none``
  • else    → inconclusive   (leave the declared default in place)

The verdict is persisted (`provider.set_measured_cache_mode`) so the capability seam
overrides the declared default with measured truth (`capability_for` cache_mode_override),
the Settings chip stops saying "unverified", and Layer B can trust the signal.
"""
from __future__ import annotations

import logging
import statistics
import time
from typing import Optional

from pydantic import BaseModel

from aughor.llm import provider as _provider

logger = logging.getLogger(__name__)

# Verdict thresholds on the warm/cold latency ratio (see module docstring).
_REUSE_AT = 0.60
_NO_REUSE_AT = 0.85

# cache_mode each verdict maps to when persisted as the measured override.
_VERDICT_TO_MODE = {"reuse_active": "auto_prefix", "no_reuse": "none", "inconclusive": None}


class _Tiny(BaseModel):
    """Forces a minimal, fixed-size completion so latency is dominated by *prefill*
    (the thing prefix-caching skips), not generation."""
    n: int


def _filler(approx_tokens: int) -> str:
    # Deterministic ~4-chars/token filler; a stand-in for a big stable schema/rules block.
    unit = "The quick brown fox jumps over the lazy dog. "  # ~12 tokens
    return (unit * (max(1, approx_tokens // 12) + 1))


def verdict_for(warm_ms: list[float], cold_ms: list[float]) -> tuple[str, float]:
    """Pure verdict: ``(label, ratio)`` from warm (shared, post-cold) vs cold (distinct)
    latency samples. Separated from the I/O so it is unit-testable without a network."""
    warm = [m for m in warm_ms if m and m > 0]
    cold = [m for m in cold_ms if m and m > 0]
    if not warm or not cold:
        return "inconclusive", 0.0
    ratio = statistics.median(warm) / statistics.median(cold)
    if ratio <= _REUSE_AT:
        return "reuse_active", ratio
    if ratio >= _NO_REUSE_AT:
        return "no_reuse", ratio
    return "inconclusive", ratio


def _timed(prov, system: str, user: str) -> float:
    t0 = time.monotonic()
    # Call the chosen backend directly (no fallback masking), like test_provider().
    prov._complete_on(prov._client, prov.backend, prov._model, system, user, _Tiny, 0.0)
    return (time.monotonic() - t0) * 1000.0


def probe_prefix_cache(role: str = "coder", *, rounds: int = 3, prefix_tokens: int = 1000,
                       backend: Optional[str] = None, model: Optional[str] = None,
                       persist: bool = True) -> dict:
    """Measure prefix-cache reuse for a binding over the *real* provider and (by default)
    persist the verdict so the capability seam adopts it. Returns a JSON-able report.

    ``rounds`` ≥ 2 (the first shared call is the cold anchor; the rest are the warm sample).
    Network/cost: ``2 * rounds`` tiny completions with a ~``prefix_tokens`` prefix.
    """
    rounds = max(2, int(rounds))
    b = (backend or _provider._active_backend()).strip()
    m = (model or _provider._active_model(b, role)).strip()
    _provider._active_base_url(b)

    prefix = _filler(prefix_tokens)
    report: dict = {"backend": b, "model": m, "rounds": rounds, "prefix_tokens": prefix_tokens}
    try:
        prov = _provider.LLMProvider(b, role, model=m)  # type: ignore[arg-type]
        # SHARED: identical big system prefix; only the tiny user line varies.
        shared = [_timed(prov, prefix + "\nYou return a single integer.",
                         f"Return n={i}.") for i in range(rounds)]
        # DISTINCT: prefix diverges at the first token → never reusable (all cold).
        distinct = [_timed(prov, f"[req-{i}-{i*7+3}] " + prefix + "\nYou return a single integer.",
                           f"Return n={i}.") for i in range(rounds)]
    except Exception as e:  # surface, do not swallow — a failed probe must read as failed
        logger.warning("cache_probe: %s/%s failed: %s", b, m, str(e)[:160])
        report.update(ok=False, error=str(e)[:240])
        return report

    warm = shared[1:]          # exclude the cold first call
    cold = distinct
    label, ratio = verdict_for(warm, cold)
    mode = _VERDICT_TO_MODE[label]
    report.update(ok=True, verdict=label, ratio=round(ratio, 3), cache_mode=mode,
                  shared_ms=[round(x) for x in shared], distinct_ms=[round(x) for x in distinct],
                  warm_median_ms=round(statistics.median(warm)) if warm else None,
                  cold_median_ms=round(statistics.median(cold)) if cold else None)
    if persist:
        _provider.set_measured_cache_mode(b, m, mode)  # None clears (inconclusive)
        report["persisted"] = True
    return report
