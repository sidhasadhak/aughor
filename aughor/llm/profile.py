"""Model-sized capability budgets — the knobs follow the bound model, not the weakest
model the platform ever ran on.

The constants this module replaces were all sized for one transport at one moment
(the 2026-06 Groq free tier): a 20k-char schema window, a 6k-char evidence budget for
the ENTIRE deep synthesis, 12 rows per interpreted result, a 4096-token output
ceiling. Every one of them silently restricted a stronger model to the weakest
model's diet. The 2026-08-01 roadmap's Track A thesis: if a smarter model makes a
mechanism unnecessary, the mechanism is a RESTRICTION and must scale with the model.

`profile_for(role)` resolves the effective :class:`ModelProfile` from the SAME
binding a real call uses (`resolve_binding` — org default → run/agent pin → role
default), so the budgets can never disagree with the model actually answering.
Unknown models get exactly the old constants — byte-identical behaviour, the
conservative floor — and known large-context families get budgets sized for what
they can actually hold.

Parallelism (formerly the four `performance_profile` flags — flag endgame Wave 6,
verdict sheet 2026-08-01) is a TRANSPORT decision, not a preference: under the
OpenRouter free tier's documented 20 requests/min, a 3–5-call concurrent wave
starves the rest of the run; on a transport with real headroom, serial waves throw
away wall-clock. Neither default is honest, so there is no switch — the profile
derives it from the DECLARED rate budget. `AUGHOR_LLM_RPM` explicitly set wins in
both directions (`0` means declared-unbounded — coherently, the same value that
disables `_pace`); an OpenRouter `:free` model IS a 20 RPM declaration by suffix.
And an UNKNOWN budget is not an unlimited one — with no declaration at all the
waves stay serial, which keeps the out-of-box topology byte-identical to the
default-off flags this replaces. Concurrency still runs behind the existing
per-endpoint gate (`AUGHOR_LLM_MAX_CONCURRENCY`).

Env precedence is unchanged everywhere: an operator's existing `AUGHOR_MAX_OUTPUT_TOKENS`
/ `AUGHOR_REASONING_EFFORT` / `AUGHOR_LLM_RPM` still decides. The profile only moves
the DEFAULT from "frozen at the weakest era" to "sized to the binding".

Resolved per call, never at import — a module-level snapshot would make
`monkeypatch.setenv` a no-op in tests and would miss a runtime rebind
(`POST /llm/config`). One small dict lookup + the already-cached config read.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ModelProfile:
    """The effective capability budgets for one resolved (backend, model) binding."""

    backend: str
    model: str
    #: Char budget for schema context handed to planning/synthesis prompts
    #: (successor of `investigate._SCHEMA_CHAR_LIMIT` = 20_000).
    schema_char_limit: int
    #: Char budget for the deep-synthesis evidence block
    #: (successor of `investigate._EVIDENCE_BUDGET` = 6_000).
    evidence_budget: int
    #: Rows per query result rendered for LLM interpretation
    #: (successor of the `max_rows=12` default in `investigate._results_to_text`).
    interpret_max_rows: int
    #: Output-token ceiling per call (successor of `provider._MAX_OUTPUT_TOKENS` = 4096;
    #: the 4096 default demonstrably truncated a ~25-finding briefing outright). This
    #: is the ceiling for THIS profile's own role — see :func:`role_output_cap`, which
    #: the provider calls with the role and model of the request it is about to send.
    max_output_tokens: int
    #: Attempts instructor may spend inside one structured call. Deliberately 1 for
    #: EVERY tier: this is retry ECONOMICS (Wave R1's normalizer + bounded repair own
    #: the budget at near-zero request cost), not a capability cap — a stronger model
    #: does not make instructor's blind full-prompt re-ask a better trade.
    structured_attempts: int
    #: Max tool-choosing turns per converse question (Layer 3's loop budget). Lives here
    #: rather than as a module constant because it is a capability knob, and ModelProfile
    #: exists so those stop coming back as constants.
    tool_loop_steps: int
    #: Reasoning effort for backends that expose it ("low"|"medium"|"high").
    reasoning_effort: str
    #: A3 linker budgets — rank bounds for the schema-linking pre-filter; the char
    #: budget that actually caps the packed schema is `schema_char_limit`. Baseline
    #: = the old hardcoded 4×8 bouncer exactly; a capable model ranks further down
    #: the list because its window genuinely holds it.
    linker_top_tables: int
    linker_top_cols: int
    #: Post-catalog table cap (successor of the hardcoded ``max_tables=10`` at the
    #: `enforce_context_cap` call sites and the join-expansion ``cap=10``).
    context_table_cap: int
    #: Transport-derived: may independent phases/lenses/sub-questions run as
    #: concurrent waves? (Replaces explore.parallel_subq,
    #: deep_analysis.parallel_lenses/parallel_phases/parallel_why_lenses.)
    parallel_waves: bool
    #: The rate budget the parallel decision was derived from
    #: (0 = declared-unbounded, None = undeclared/unknown).
    rpm_budget: Optional[int]
    #: True when the model earned a family tier above BASELINE (PE-2). Prompt builders
    #: use it to TIER guardrail prose: a capable model gets the short contract and code
    #: verifies its output; a baseline model keeps the long-form guidance the old
    #: constants were written for. Defaulted so a hand-built profile (tests) reads as
    #: baseline — the conservative register.
    capable: bool = False


# ── Tier tables ───────────────────────────────────────────────────────────────
# The BASELINE tier is the old constants exactly — the behaviour every existing test
# and receipt was measured against. A model earns the CAPABLE tier by family entry
# below, not by name-parsing heuristics: an unknown model is somebody's fine-tune we
# know nothing about, and it gets the floor.

_BASELINE = dict(
    schema_char_limit=20_000,
    evidence_budget=6_000,
    interpret_max_rows=12,
    max_output_tokens=4_096,
    structured_attempts=1,
    reasoning_effort="low",
    linker_top_tables=4,
    linker_top_cols=8,
    context_table_cap=10,
    # Every role at the old constant — BASELINE is "the behaviour everything was
    # measured against", so it stays byte-identical.
    role_output_tokens={"coder": 4_096, "narrator": 4_096, "fast": 4_096},
    # How many tool-choosing turns one converse question may spend. A ceiling, not a
    # target: the model stops when it has an answer. BASELINE is deliberately tight —
    # a weaker model that has not converged in four steps is usually looping, and each
    # step is a whole request against a 1,000/day free-tier allowance.
    tool_loop_steps=4,
)

# The budgets for a large-context binding — reached by any model whose provider declares
# at least `_CAPABLE_CONTEXT_TOKENS` (see `tier_for`), never by being named in a list.
# 60k chars of schema is ~15k tokens, still conservative against a 128k window. Output
# ceiling doubled because 4096 is a measured briefing-killer; effort "medium" because the
# constraint on the free tier is request RATE, not tokens, and reasoning depth is the
# direct quality lever.
_CAPABLE = dict(
    schema_char_limit=60_000,
    evidence_budget=18_000,
    interpret_max_rows=36,
    max_output_tokens=8_192,
    structured_attempts=1,
    reasoning_effort="medium",
    linker_top_tables=24,
    linker_top_cols=24,
    context_table_cap=24,
    # The narrator is the role that was measured TRUNCATING (a ~25-finding briefing
    # died at 4096), and prose does not carry the reasoning-token runaway risk that
    # made a high ceiling dangerous for structured calls — so it gets real headroom.
    # `fast` deliberately does NOT take the capable bump: it is the cheap-by-
    # declaration tier (phase interprets, classifies, the evidence digest), where a
    # bigger ceiling buys nothing and costs the run's largest per-call multiplier.
    # A ceiling is not a target; the only risk of a high one is a runaway, and the
    # deadline plus reasoning-effort caps bound that independently.
    role_output_tokens={"coder": 8_192, "narrator": 12_288, "fast": 4_096},
    # A capable model can afford to look something up, be wrong, and recover — which is
    # the whole argument for a loop over a single shot.
    tool_loop_steps=8,
)

#: Context window (in tokens) at which a binding earns the CAPABLE budgets. 60k chars of
#: schema is ~15k tokens, so 128k leaves the model roughly 8× that for everything else —
#: the same bar the old hand-maintained family table was curated against.
_CAPABLE_CONTEXT_TOKENS = 128_000

#: Test-only escape hatch (aughor/llm/faux.py). The faux backend serves scripted text and
#: publishes no catalogue, so there is nothing to derive a tier from; this id declares
#: itself capable so tier-dependent behaviour stays testable offline. Not a provider model
#: and not selectable — `faux` is absent from BACKENDS.
_FAUX_CAPABLE_ID = "faux-capable"

#: The OpenRouter free tier's documented request budget. A model id ending in
#: `:free` is bound to this whether or not the operator paces for it.
_FREE_TIER_RPM = 20

#: Below this declared RPM, a concurrent wave (3–5 calls) visibly starves the rest
#: of the run; at/above it, waves fit. 30 = a 5-call wave every 10s with half the
#: budget left over.
_PARALLEL_RPM_FLOOR = 30


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        return default


def _bare_model_name(model_id: str) -> str:
    """The model's own name, without the vendor namespace or an alias marker:
    ``google/gemini-3.1-flash-lite`` and ``~google/gemini-flash-latest`` → the part after
    the slash. Transport suffixes (``:free``, ``:batch``, ``:cloud``) are kept, because
    they can carry genuinely different windows — OpenRouter reports 1,000,000 for one
    Nemotron variant and 262,144 for its ``:free`` twin."""
    return (model_id or "").lstrip("~").rsplit("/", 1)[-1].strip().lower()


def _context_by_bare_name(known: dict, model: str) -> Optional[int]:
    """A recorded window for the same model under a DIFFERENT vendor namespace.

    The same model is served under two ids: OpenRouter calls it
    ``google/gemini-3.1-flash-lite``, Google's own API calls it
    ``gemini-3.1-flash-lite``. The catalogue had already captured 1,048,576 for the
    first, and the exact-match lookup missed it for the second — so a binding fell to the
    32,768 default while the true window sat in the same map under a longer key.

    This is still derivation, not a list: every number comes from a provider's own
    catalogue. It only widens WHICH id can find one. Ambiguity is resolved
    conservatively (the smallest recorded window wins) so a mismatch can never overstate
    the budget, which is the direction that silences the overflow guard.
    """
    bare = _bare_model_name(model)
    if not bare:
        return None
    hits = [int(v) for k, v in known.items()
            if _bare_model_name(k) == bare and isinstance(v, (int, float)) and v > 0]
    return min(hits) if hits else None


def declared_context(model: str) -> Optional[int]:
    """The model's context window in tokens, as the PROVIDER declared it, or None.

    Sources, in order: ``AUGHOR_MODEL_CONTEXT_TOKENS`` (an operator who knows, and the
    only way to declare it for a backend that publishes no context length), then the
    ``model_context`` map in the runtime config — recorded by the catalogue fetch from
    each provider's own ``/models`` payload (``aughor.llm.models``).

    Deliberately does NOT fetch: this is called on every profile resolution, and a tier
    that depends on a network round-trip would be both slow and non-deterministic. It
    reads what a previous catalogue load persisted, so the answer is the same on every
    call until the catalogue is refreshed.
    """
    env = os.getenv("AUGHOR_MODEL_CONTEXT_TOKENS", "").strip()
    if env:
        try:
            return int(env)
        except ValueError:
            from aughor.kernel.errors import tolerate
            tolerate(ValueError(env), "AUGHOR_MODEL_CONTEXT_TOKENS is not an integer; "
                                      "falling back to the recorded catalogue value",
                     counter="llm.model_context")
    key = (model or "").strip()
    if not key:
        return None
    try:
        from aughor.llm.provider import read_config
        known = read_config().get("model_context") or {}
        raw = known.get(key)
        if raw is None:
            raw = _context_by_bare_name(known, key)
        return int(raw) if raw is not None else None
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "context window unreadable; the binding falls back to the "
                      "BASELINE tier rather than assuming a large window",
                 counter="llm.model_context")
        return None


def tier_for(model: str) -> dict:
    """The capability-tier defaults for a model id — public because the provider
    consults it for its own env-fallback defaults (max output tokens, reasoning
    effort) without re-resolving the binding it already holds.

    DERIVED, not listed. This used to be a hand-maintained table of model-id prefixes
    (``nvidia/nemotron-3-super`` → capable, and seven more), which had the failure mode
    every hardcoded model list here has had: it went out of date silently and in the
    direction that costs you. The live example — `deepseek-v4-flash:cloud` was listed
    under its OpenRouter spelling `deepseek/deepseek-v4` but not its Ollama-cloud one,
    so a capable model ran on baseline budgets (20k of schema instead of 60k) and
    nothing said so.

    Now the provider's own declared context window decides, because that is the fact the
    tier was always a proxy for. Unknown context ⇒ BASELINE: the conservative floor, and
    the same answer the old table gave for anything it had not heard of.
    """
    base = (model or "").split(":", 1)[0].strip().lower()
    if base == _FAUX_CAPABLE_ID:
        return dict(_CAPABLE)
    ctx = declared_context(model)
    if ctx is not None and ctx >= _CAPABLE_CONTEXT_TOKENS:
        return dict(_CAPABLE)
    return dict(_BASELINE)


def role_output_cap(role: str, model: str) -> int:
    """The output-token ceiling for ``role`` on ``model`` (Wave 3 / 4.2a).

    Public because the provider needs it at request-build time, where it holds the
    role and the model but not a resolved profile — and re-resolving the binding
    there would ignore the fallback link actually about to serve the call.

    An unknown role falls back to the tier's own ``max_output_tokens``, which is the
    pre-4.2a number for every tier — so a role added to :data:`ROLES` without a cap
    behaves exactly as it did before rather than inheriting someone else's budget.
    """
    tier = tier_for(model)
    caps = tier.get("role_output_tokens") or {}
    return int(caps.get(role, tier["max_output_tokens"]))


def _rpm_budget(model: str) -> Optional[int]:
    """The transport's DECLARED requests-per-minute budget.

    An explicitly-set `AUGHOR_LLM_RPM` wins in BOTH directions (an operator who paid
    for throughput can declare it; one who wants to be gentler can lower it), with
    `0` meaning declared-unbounded — the same value that disables `_pace`, so the
    two reads of the variable cannot disagree about what the transport is. Unset, an
    OpenRouter `:free` binding is a 20 RPM declaration by suffix. Anything else is
    ``None``: UNKNOWN, which is not the same claim as unlimited.
    """
    raw = os.getenv("AUGHOR_LLM_RPM")
    if raw is not None and raw.strip() != "":
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    if model.strip().lower().endswith(":free"):
        return _FREE_TIER_RPM
    return None


def _parallel_waves(rpm: Optional[int]) -> bool:
    """Parallel only on a transport whose budget is DECLARED and sufficient.

    An unknown budget derives serial — claiming headroom from silence is how a
    measured 20 RPM tier ends up eating a 5-call wave — which also keeps the
    out-of-box topology byte-identical to the default-off flags this replaces.
    """
    if rpm is None:
        return False
    concurrency = max(1, _int_env("AUGHOR_LLM_MAX_CONCURRENCY", 4))
    if concurrency < 2:
        return False
    return rpm == 0 or rpm >= _PARALLEL_RPM_FLOOR


def profile_for(role: str = "coder", *, model: Optional[str] = None) -> ModelProfile:
    """The effective :class:`ModelProfile` for a role's resolved binding.

    Resolves through :func:`aughor.llm.provider.resolve_binding` (imported lazily —
    provider also consults this module for its own defaults), so a run/agent model
    pin changes the budgets the same way it changes the model. Fail-safe: if the
    binding cannot be resolved (bare test harness, no config), the profile is the
    BASELINE on an unknown model — the old constants exactly.
    """
    backend = ""
    eff_model = (model or "").strip()
    try:
        from aughor.llm.provider import resolve_binding
        backend, eff_model, _ = resolve_binding(role, model=model)  # type: ignore[arg-type]
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "binding unresolvable (bare harness / no config) — baseline profile",
                 counter="llm.profile_binding_unresolved")
    tier = tier_for(eff_model)
    rpm = _rpm_budget(eff_model)

    # Existing env overrides keep deciding — the profile moves defaults, never
    # authority. (`AUGHOR_REASONING_EFFORT` is applied by the provider itself at
    # request-build time; it is mirrored here so readers of the profile see the
    # effective value, not just the tier default.)
    # Role-sized (4.2a): the profile a caller asks for describes the budgets THAT
    # role will really run under, so `profile_for("narrator").max_output_tokens` is
    # the narrator's ceiling rather than a tier-wide number no call actually uses.
    max_out = max(256, _int_env("AUGHOR_MAX_OUTPUT_TOKENS",
                                role_output_cap(role, eff_model)))
    attempts = max(1, _int_env("AUGHOR_LLM_STRUCTURED_ATTEMPTS", tier["structured_attempts"]))
    effort = os.getenv("AUGHOR_REASONING_EFFORT", tier["reasoning_effort"]).strip().lower() \
        or tier["reasoning_effort"]

    return ModelProfile(
        backend=backend,
        model=eff_model,
        schema_char_limit=tier["schema_char_limit"],
        evidence_budget=tier["evidence_budget"],
        interpret_max_rows=tier["interpret_max_rows"],
        max_output_tokens=max_out,
        structured_attempts=attempts,
        tool_loop_steps=max(1, _int_env("AUGHOR_TOOL_LOOP_STEPS", tier["tool_loop_steps"])),
        reasoning_effort=effort,
        linker_top_tables=tier["linker_top_tables"],
        linker_top_cols=tier["linker_top_cols"],
        context_table_cap=tier["context_table_cap"],
        parallel_waves=_parallel_waves(rpm),
        rpm_budget=rpm,
        capable=(tier != dict(_BASELINE)),
    )


def parallel_waves_enabled() -> bool:
    """The transport-derived parallelism decision, fail-safe.

    The single successor of the four deleted `performance_profile` flags. Any
    resolution error means 'serial' — the safe, byte-identical sequential path the
    old flags defaulted to.
    """
    try:
        return profile_for("coder").parallel_waves
    except Exception:
        return False
