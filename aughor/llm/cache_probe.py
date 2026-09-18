"""Prefix-cache probe — does this binding actually reuse a shared prompt prefix?

PLATFORM_ARCHITECTURE.md §5b.3 (Layer B): exploiting a stable prompt prefix only pays
off if the serving backend reuses the prefix KV-cache *across separate requests*. That is
certain for local Ollama, automatic on OpenAI-style providers — and **unverified** for the
shipped default `gemma4:31b-cloud` (Ollama Cloud multiplexes requests across workers,
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

…but only once the samples are fit to be read at all. Latency inference is a weak
instrument and this module learned it the hard way: three probes of one live hosted binding
minutes apart returned `no_reuse` (2.027), `no_reuse` (2.876) and `reuse_active` (0.137),
because the thresholds above compared two medians without ever asking whether the numbers
under them could resolve the effect. They could not — one series held 909 ms and 46,114 ms
for identical work. `_decline_reason` now refuses in three cases: too few samples to read a
noise floor, a noise floor wider than the effect, and a ratio above 1 (warm SLOWER than
cold, which a cache cannot cause — evidence the run measured something else, not evidence
of no reuse). Refusing is the useful answer: `inconclusive` maps to ``None``, which CLEARS
a persisted override instead of writing a wrong one.

🔑 A better instrument exists for backends that report it: the provider's own cached-token
count (`provider._extract_cached_tokens` — OpenAI `prompt_tokens_details.cached_tokens`,
Anthropic `cache_read_input_tokens`, Gemini `cached_content_token_count`), which is exact
and rides on calls already being made instead of buying its own. This module does NOT use
it yet, for a concrete reason: `_complete_on` returns the parsed object and keeps `raw` to
itself, and `metering.record_llm` takes only (prompt, completion, ms), so there is no seam
through which a caller can see the count. The smallest one that would work is adding
cached tokens to `metering.record_llm`; until then, prefer the metered aggregate
(`obs.usage` `cache_hit_rate`) over this probe wherever real traffic exists.

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

# ── Two guards against answering from noise (added 2026-09-18 after a live failure) ──
#
# Three probes of the same live binding minutes apart returned `no_reuse` (ratio 2.027),
# `no_reuse` (2.876) and `reuse_active` (0.137). The thresholds above are a bare
# comparison of two medians, so the probe read its own jitter as a confident verdict —
# and persisted it.

#: A ratio ABOVE 1.0 says the warm calls were SLOWER than the cold ones. Prefix caching
#: cannot cause that: it can only make a warm call faster or leave it unchanged. So a ratio
#: meaningfully above 1 is not evidence of no reuse — it is evidence that whatever the
#: numbers measured, it was not caching. 1.10 rather than 1.00 because a genuinely
#: non-caching binding sits AT 1.0 and ordinary jitter puts it either side; a hard 1.0 cut
#: would send half of all honest `no_reuse` results to inconclusive.
_IMPOSSIBLE_ABOVE = 1.10

#: Within ONE series every call does identical work — same prefix, same cache state — so
#: all spread inside a series is noise. `max/min` is therefore a direct read of the noise
#: floor, and a median cannot resolve an effect smaller than it. The effect here is the
#: prefill of a `prefix_tokens` prefix: tens of ms on a hosted model. The three live probes
#: above ran at 4.3×, 15.3×, 21.2× and 50.7× — one `distinct` series held both 909 ms and
#: 46,114 ms for the same work.
_MAX_SPREAD = 3.0

#: A series with fewer samples than this has no spread to read, so its noise floor is
#: unknown and no verdict from it is honest.
_MIN_SAMPLES = 2

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


def spread_of(samples: list[float]) -> float:
    """``max/min`` over one series — its noise floor. 1.0 when there is nothing to compare.

    Every call in a series does identical work, so this is noise and nothing else. Public
    because the report carries it: an operator reading "inconclusive" is owed the number
    that made it inconclusive.
    """
    xs = [m for m in samples if m and m > 0]
    return (max(xs) / min(xs)) if len(xs) >= 2 else 1.0


def _decline_reason(warm: list[float], cold: list[float], ratio: float) -> Optional[str]:
    """Why these samples cannot support a verdict, or None if they can.

    The single ordered list of refusal rules. `verdict_for` asks it whether to decline and
    the report asks it what to tell the operator, so the sentence an operator reads can
    never disagree with the rule that produced it — a reason string maintained beside the
    logic instead of derived from it drifts the first time a threshold moves.
    """
    if len(warm) < _MIN_SAMPLES or len(cold) < _MIN_SAMPLES:
        return (f"too few usable samples (warm {len(warm)}, cold {len(cold)}; "
                f"{_MIN_SAMPLES} needed to read a noise floor at all)")
    noise = max(spread_of(warm), spread_of(cold))
    if noise > _MAX_SPREAD:
        return (f"noise floor {noise:.1f}x exceeds {_MAX_SPREAD}x — calls doing IDENTICAL "
                "work varied by that much, so a median cannot resolve the prefill this "
                "probe is trying to see")
    if ratio > _IMPOSSIBLE_ABOVE:
        return (f"warm/cold {ratio:.2f} is above {_IMPOSSIBLE_ABOVE} — the warm calls were "
                "SLOWER than the cold ones, which prefix caching cannot cause; this run "
                "measured something other than caching")
    return None


def verdict_for(warm_ms: list[float], cold_ms: list[float]) -> tuple[str, float]:
    """Pure verdict: ``(label, ratio)`` from warm (shared, post-cold) vs cold (distinct)
    latency samples. Separated from the I/O so it is unit-testable without a network.

    Returns ``inconclusive`` — which CLEARS any persisted override rather than writing one —
    whenever the samples cannot support a verdict. Declining is the useful answer here: this
    probe informs whether to spend effort shrinking a prompt prefix, and a wrong confident
    answer sends that work in the wrong direction. The ratio is always returned, including
    when it is being refused, because it is the diagnostic.
    """
    warm = [m for m in warm_ms if m and m > 0]
    cold = [m for m in cold_ms if m and m > 0]
    if not warm or not cold:
        return "inconclusive", 0.0
    ratio = statistics.median(warm) / statistics.median(cold)
    if _decline_reason(warm, cold, ratio):
        return "inconclusive", ratio
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


def probe_prefix_cache(role: str = "coder", *, rounds: int = 5, prefix_tokens: int = 8000,
                       backend: Optional[str] = None, model: Optional[str] = None,
                       persist: bool = True) -> dict:
    """Measure prefix-cache reuse for a binding over the *real* provider and (by default)
    persist the verdict so the capability seam adopts it. Returns a JSON-able report.

    ``rounds`` ≥ 2 (the first shared call is the cold anchor; the rest are the warm sample).
    Network/cost: ``2 * rounds`` tiny completions with a ~``prefix_tokens`` prefix.

    The defaults changed 2026-09-18 after the probe returned three disagreeing verdicts for
    one binding. ``prefix_tokens`` was 1000 — a prefill of tens of milliseconds on a hosted
    model, one to two orders below the jitter it was being compared against, so the
    measurement could not have worked whatever the thresholds were. 8000 is chosen to mirror
    the prefix this question is actually asked about: the measured `run_tool_loop` prompt
    prefix is ~5,400 tokens. ``rounds`` moved 3 → 5 so each series has enough samples for
    `spread_of` to read its own noise floor (3 rounds leaves only 2 warm samples).

    Cost rises with both: 10 calls at ~8k prompt tokens ≈ 80k tokens per probe. That is the
    price of an answer that means something, and it is still one investigation's worth.
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
                  cold_median_ms=round(statistics.median(cold)) if cold else None,
                  # The diagnostics behind the verdict. An operator who reads
                  # "inconclusive" is owed the number that refused the answer, and a
                  # noise floor near _MAX_SPREAD is the signal to probe a quieter
                  # moment rather than to believe a borderline verdict.
                  warm_spread=round(spread_of(warm), 2),
                  cold_spread=round(spread_of(cold), 2),
                  noise_ceiling=_MAX_SPREAD)
    if label == "inconclusive":
        report["reason"] = _decline_reason(warm, cold, ratio) or (
            f"ratio {ratio:.2f} fell in the undecided band between {_REUSE_AT} and "
            f"{_NO_REUSE_AT} — the samples are clean, the effect is just not clear")
    if persist:
        _provider.set_measured_cache_mode(b, m, mode)  # None clears (inconclusive)
        report["persisted"] = True
    return report
