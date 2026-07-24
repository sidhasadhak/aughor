"""The vouched model matrix (Wave R2) — which model ids we have actually checked.

Two bugs in this repo's history share one shape: **a model id nobody verified**.

* The first pass at the OpenRouter defaults shipped two ids that do not exist. The
  failover chain answered anyway, so the app looked healthy while the binding an
  operator had chosen was dead.
* A per-agent pin clobbered the ``fast`` tier, running every throwaway interpret call on
  a 550B reasoning model — because "may this model serve the cheap tier" was a rule
  written in an ``if`` rather than a property of the model.

Both are unfixable by testing harder, because both are facts about the *outside world*
that the code merely assumed. What can be fixed is where the assumption lives: this
module is the single place a model id carries a **verification date** and a **tier
eligibility**, and the built-in defaults are required to resolve through it
(``tests/unit/test_model_matrix.py``). A default can no longer be a guess, because an
unvouched default fails CI.

**What this module refuses to do is block a model id it does not know.** New ids appear
weekly and the picker is deliberately free text
(:mod:`aughor.llm.models`) — "the failure mode of guessing wrong is 'you cannot use the
model you are paying for'". So an unvouched id *warns*; only our own shipped defaults
are held to the higher bar.

``verified_on = ""`` means exactly what it says: nobody has checked this id against a
live catalogue. It is not a soft yes. A matrix that vouched for what it could not verify
would be worse than no matrix, because it would launder a guess into a date.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VouchedModel:
    """One model id, and what we actually know about it."""

    backend: str
    model: str
    #: ISO date this id was seen in the provider's own live catalogue, or "" for never.
    verified_on: str
    #: May this model serve the cheap ``fast`` tier? See :func:`fast_eligible`.
    fast_eligible: bool
    note: str = ""

    @property
    def vouched(self) -> bool:
        return bool(self.verified_on)


# ── The matrix ────────────────────────────────────────────────────────────────
# Every `verified_on` below was produced by fetching the provider's own live catalogue
# and matching the id — not by reading it off a docs page. Where that was not possible
# (no key configured on the machine that built this table) the date is "" and the entry
# is honest about being unverified.
#
# `fast_eligible` is a policy declaration, and it is conservative: True only for models
# small or cheap enough that a throwaway call (a phase interpret, a question classify,
# the evidence digest) is not a waste. Anything unlisted resolves to False, which
# preserves today's blanket "a run pin never reaches `fast`" behaviour exactly.

_VERIFIED_2026_07_24 = "2026-07-24"

VOUCHED: tuple[VouchedModel, ...] = (
    # ── OpenRouter ── all 14 confirmed present in the public /models catalogue on
    # 2026-07-24 (343 ids listed). This is the backend the app is bound to.
    VouchedModel("openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free", _VERIFIED_2026_07_24,
                 False, "1M ctx, the coder ceiling — NEVER fast-eligible: a run pin "
                        "reaching `fast` through this model is the exact cost bug #202 fixed"),
    VouchedModel("openrouter", "google/gemma-4-31b-it:free", _VERIFIED_2026_07_24,
                 False, "narrator default — user-visible prose, not a throwaway tier"),
    VouchedModel("openrouter", "google/gemma-4-26b-a4b-it:free", _VERIFIED_2026_07_24, False),
    VouchedModel("openrouter", "nvidia/nemotron-3-super-120b-a12b:free", _VERIFIED_2026_07_24, False),
    VouchedModel("openrouter", "cohere/north-mini-code:free", _VERIFIED_2026_07_24, False),
    VouchedModel("openrouter", "openai/gpt-oss-20b:free", _VERIFIED_2026_07_24,
                 False, "20B but 3702ms — cheap in size, not in latency"),
    VouchedModel("openrouter", "nvidia/nemotron-3-nano-30b-a3b:free", _VERIFIED_2026_07_24,
                 True, "the throughput pick and the `fast` default — 91 t/s"),
    VouchedModel("openrouter", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
                 _VERIFIED_2026_07_24, True, "the latency pick — 410ms"),
    VouchedModel("openrouter", "nvidia/nemotron-nano-9b-v2:free", _VERIFIED_2026_07_24, True),
    VouchedModel("openrouter", "nvidia/nemotron-nano-12b-v2-vl:free", _VERIFIED_2026_07_24,
                 False, "vision-language"),
    VouchedModel("openrouter", "nvidia/nemotron-3.5-content-safety:free", _VERIFIED_2026_07_24,
                 False, "a safety classifier, not a general LLM"),
    VouchedModel("openrouter", "poolside/laguna-m.1:free", _VERIFIED_2026_07_24, False),
    VouchedModel("openrouter", "poolside/laguna-s-2.1:free", _VERIFIED_2026_07_24, False),
    VouchedModel("openrouter", "poolside/laguna-xs-2.1:free", _VERIFIED_2026_07_24, False),

    # ── Gemini ── confirmed in the live catalogue on 2026-07-24, which lists them
    # PREFIXED as `models/<id>`. See `normalize_id`: comparing raw would report all
    # three as gone on every startup, and a drift warning that cries wolf is ignored.
    VouchedModel("gemini", "gemini-3.1-flash-lite", _VERIFIED_2026_07_24,
                 True, "15 RPM / 500 req-day measured 2026-07-22 — the failover lands here"),
    VouchedModel("gemini", "gemini-flash-latest", _VERIFIED_2026_07_24,
                 True, "5 RPM / 20 req-DAY — real, but unusable for a brief"),
    VouchedModel("gemini", "gemini-pro-latest", _VERIFIED_2026_07_24, False),

    # ── Ollama ── local, so "the catalogue" is whatever this machine has pulled. Three
    # were present on 2026-07-24; the other two are shipped suggestions that simply are
    # not pulled here. Absent from a local install is NOT evidence an id is wrong, so
    # they are recorded unverified rather than removed.
    VouchedModel("ollama", "qwen3-coder-next:cloud", _VERIFIED_2026_07_24, False),
    VouchedModel("ollama", "kimi-k2.6:cloud", _VERIFIED_2026_07_24, False),
    VouchedModel("ollama", "qwen3.5:397b-cloud", _VERIFIED_2026_07_24, False),
    VouchedModel("ollama", "glm-5.2:cloud", "", False, "not pulled on the verifying machine"),
    VouchedModel("ollama", "gpt-oss:120b-cloud", "", False, "not pulled on the verifying machine"),

    # ── LM Studio ── a placeholder id by design: LM Studio serves whatever is loaded.
    VouchedModel("lmstudio", "local-model", "", False, "placeholder — LM Studio routes by load"),

    # ── Backends with no key on the verifying machine ── honestly unverified. These are
    # shipped suggestions, and until someone runs the catalogue check with a key they
    # carry no more authority than the docs page they came from.
    VouchedModel("anthropic", "claude-opus-4-8", "", False),
    VouchedModel("anthropic", "claude-sonnet-5", "", False),
    VouchedModel("anthropic", "claude-sonnet-4-6", "", False),
    VouchedModel("anthropic", "claude-haiku-4-5-20251001", "", True, "the cheap tier of its family"),
    VouchedModel("groq", "llama-3.3-70b-versatile", "", False),
    VouchedModel("groq", "llama-3.1-8b-instant", "", True, "8B instant — a genuine cheap tier"),
    VouchedModel("groq", "mixtral-8x7b-32768", "", False),
    VouchedModel("together", "Qwen/Qwen2.5-Coder-32B-Instruct", "", False),
    VouchedModel("together", "meta-llama/Llama-3.3-70B-Instruct-Turbo", "", False),
    VouchedModel("together", "deepseek-ai/DeepSeek-V3", "", False),
)

_BY_KEY: dict[tuple[str, str], VouchedModel] = {(v.backend, v.model): v for v in VOUCHED}


# ── id normalization ──────────────────────────────────────────────────────────

def normalize_id(backend: str, model: str) -> str:
    """A provider's catalogue id reduced to the form our bindings use.

    Only Gemini needs this today: its ``/models`` endpoint returns ``models/gemini-…``
    while its ``/chat/completions`` endpoint takes the bare id, so a raw string compare
    marks every correct Gemini binding as missing. That is how a drift warning becomes
    noise nobody reads.
    """
    m = (model or "").strip()
    if backend == "gemini" and m.startswith("models/"):
        return m[len("models/"):]
    return m


# ── lookups ───────────────────────────────────────────────────────────────────

def lookup(backend: str, model: str) -> Optional[VouchedModel]:
    return _BY_KEY.get((backend, normalize_id(backend, model)))


def is_vouched(backend: str, model: str) -> bool:
    """True only when this id was seen in the provider's live catalogue on a known date."""
    entry = lookup(backend, model)
    return bool(entry and entry.vouched)


def is_known(backend: str, model: str) -> bool:
    """True when the matrix carries the id at all, verified or not."""
    return lookup(backend, model) is not None


def fast_eligible(backend: str, model: str) -> bool:
    """May this model serve the cheap ``fast`` tier?

    Unlisted ⇒ False, which is what makes wiring this safe: the pre-R2 rule was a
    blanket "a run pin never reaches ``fast``", and an unknown model still resolves to
    exactly that. The matrix only ever *widens* the rule, and only for a model someone
    declared cheap on purpose.
    """
    entry = lookup(backend, model)
    return bool(entry and entry.fast_eligible)


def vouched_for(backend: str) -> tuple[VouchedModel, ...]:
    return tuple(v for v in VOUCHED if v.backend == backend)


# ── drift, in the shape of the flag-drift audit ───────────────────────────────

def drift(backend: str, live_ids) -> dict:
    """Diff the matrix against a provider's live catalogue.

    Returns ``{"gone": [...], "unlisted": [...], "checked": n}``:

    * **gone** — an id the matrix vouched for that the provider no longer lists. This is
      the one that matters; a binding on it will fail with a config error, and now says
      so before a user meets it.
    * **unlisted** — live ids the matrix has never recorded. Informational only: the
      catalogue is hundreds of models and the matrix covers what we ship.

    A verified entry that has gone missing is the warning. An *unverified* entry cannot
    have "gone" — it was never claimed present, so reporting it would be inventing a
    regression out of an absence we already documented.
    """
    live = {normalize_id(backend, i) for i in (live_ids or []) if i}
    ours = vouched_for(backend)
    gone = sorted(v.model for v in ours if v.vouched and v.model not in live)
    unlisted = sorted(live - {v.model for v in ours})
    return {"gone": gone, "unlisted": unlisted, "checked": len(ours)}


def check_drift(backend: str, *, timeout: float = 6.0) -> dict:
    """Fetch ``backend``'s live catalogue and report :func:`drift`, logging any ``gone``.

    Best-effort and never raises: an unreachable catalogue is not evidence of drift, and
    a startup check that can fail a startup is worse than the drift it looks for. A
    backend that returns nothing is reported as ``skipped`` rather than as total drift —
    the difference between "everything is gone" and "we could not look" is the whole
    value of the check.
    """
    try:
        from aughor.llm.models import fetch_live_models

        live, _src = fetch_live_models(backend, timeout=timeout)
        ids = [m.get("id") for m in (live or [])]
    except Exception as exc:
        logger.debug("matrix: could not fetch %s catalogue (%s)", backend, exc)
        return {"backend": backend, "skipped": "catalogue unavailable", "gone": [], "unlisted": []}
    if not ids:
        return {"backend": backend, "skipped": "empty catalogue", "gone": [], "unlisted": []}

    report = drift(backend, ids)
    if report["gone"]:
        logger.warning(
            "matrix: %s no longer lists %d model(s) we vouched for: %s — a binding on one "
            "of these will fail as a config error. Update aughor/llm/matrix.py.",
            backend, len(report["gone"]), ", ".join(report["gone"]))
    return {"backend": backend, **report}
