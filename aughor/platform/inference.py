"""Inference-credential vending — the control plane's *third* seam (Invariant #7).

PLATFORM_ARCHITECTURE.md §5b: inference is a vended resource alongside storage (§5.2)
and compute (§4) — and the one that, until now, was still *ambient*. Every intelligence
surface calls one chokepoint (`aughor/llm/provider.py` `LLMProvider.complete`), but the
backend, endpoint, and key behind it came from a single **global** config. That violated
Invariant #1 (tenant-keyed everything) and Invariant #2 (vend, never ambient) for the
inference dimension.

`vend_llm` mirrors `vend_storage`: the control plane resolves the binding once and hands
the caller a **scoped capability** that describes *what backend it bound* and *what that
backend can actually do* — so nothing downstream branches on provider identity. A new
backend (a local Llama, a public API, Ollama Cloud, a private Databricks endpoint) becomes
a config row + a capability profile, not a code change.

The binding is resolved **Org → Workspace → Agent** (inherited, last-most-specific wins).
Today the org default *is* the global `data/llm_config.json` and the agent override *is*
the `set_run_model` contextvar — `resolve_binding` (in `llm/provider.py`) is the single
shared resolution, so the vended capability always describes the binding a call will use.
Per-org/per-workspace persisted bindings land with the Phase 4 multi-tenant flip; the seam
is what makes that a config change, not a rewrite.

Two-layer optimisation (§5b.3) consumes this capability:
  • Layer A — backend-independent payload reduction, gated on ``max_context``.
  • Layer B — a canonical prompt assembler whose per-provider adapter dispatches on
    ``cache_mode`` (explicit breakpoint · free auto-prefix · none).
And ``privacy_class`` (§5b.4) is a governance routing constraint: an org policy can bind
"agents on public_api providers receive schema-only context, never raw cells".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Optional, Type, TypeVar

from aughor.org.context import DEFAULT_ORG_ID, current_org_id

if TYPE_CHECKING:  # avoid an import cycle at module load — provider imports this module
    from aughor.llm.provider import LLMProvider, Role
    from pydantic import BaseModel

# ── The capability profile vocabulary (§5b.2) ─────────────────────────────────
# How (if at all) a stable prompt prefix can be exploited.
CacheMode = Literal["explicit_breakpoint", "auto_prefix", "auto_prefix_unverified", "none"]
# Whether mid-generation tool/retrieval calls are available.
Tooling = Literal["native_tools", "none"]
# How `response_model` is enforced — schema-native vs instructor reprompt-on-mismatch.
StructuredOutput = Literal["native", "instructor_emulated"]
# Whether the backend reliably returns a token-usage block.
TokenAccounting = Literal["exact", "estimated"]
# What context a provider may be *sent* — a governance routing constraint.
PrivacyClass = Literal["local", "private_endpoint", "public_api"]
# How spend is modelled for per-agent budgets.
Cost = Literal["per_token", "flat", "unknown"]

T = TypeVar("T", bound="BaseModel")

_LOCALHOST = ("localhost", "127.0.0.1", "0.0.0.0", "::1")

# Tools-capable model keywords — mirrors `provider._build_ollama_client`'s `_TOOLS_MODELS`,
# the same signal that selects instructor TOOLS mode (schema-native structured output).
_TOOLS_KEYWORDS = ("qwen3", "kimi", "deepseek-r1", "qwq", "qwen-coder", "qwen2.5-coder")

# Best-effort context windows (substring match on the model id). Conservative on purpose:
# `max_context` tightens Layer-A payload caps, so under-estimating is safe and
# over-estimating risks overflow. Override per-model as real limits are confirmed.
_CONTEXT_WINDOWS: dict[str, int] = {
    "claude": 200_000,
    "qwen3-coder": 131_072,
    "qwen2.5-coder": 131_072,
    "kimi": 131_072,
    "llama-3.3": 131_072,
    "deepseek": 131_072,
}
_DEFAULT_CONTEXT = 32_768


def _is_local_url(url: str) -> bool:
    u = (url or "").lower()
    return any(h in u for h in _LOCALHOST)


def _is_cloud_ollama(model: str) -> bool:
    # Ollama Cloud models carry a ``:cloud`` tag and egress to a multiplexed hosted
    # service — they are *not* local even when reached via a localhost Ollama daemon.
    return model.lower().endswith(":cloud")


def _cache_mode(backend: str, model: str, base_url: str) -> CacheMode:
    if backend == "anthropic":
        return "explicit_breakpoint"            # cache_control breakpoints
    if backend in ("ollama", "lmstudio", "groq", "together"):
        if backend == "ollama" and _is_cloud_ollama(model):
            # Hosted/multiplexed — prefix-KV reuse across separate requests is not
            # guaranteed; flag it so Layer B never *assumes* a cache hit (measure first).
            return "auto_prefix_unverified"
        return "auto_prefix"                    # llama.cpp / OpenAI-style automatic prefix reuse
    return "none"


def _tooling(backend: str, model: str) -> Tooling:
    if backend in ("anthropic", "groq", "together"):
        return "native_tools"
    if backend == "ollama":
        return "native_tools" if any(k in model.lower() for k in _TOOLS_KEYWORDS) else "none"
    return "none"                                # lmstudio / unknown: conservative


def _structured_output(backend: str, model: str) -> StructuredOutput:
    # "native" = provider enforces the schema (tool / json_schema mode);
    # "instructor_emulated" = plain JSON mode with reprompt-on-mismatch.
    if backend in ("anthropic", "lmstudio"):
        return "native"
    if backend == "ollama":
        return "native" if any(k in model.lower() for k in _TOOLS_KEYWORDS) else "instructor_emulated"
    return "instructor_emulated"                 # groq / together JSON mode


def _token_accounting(backend: str) -> TokenAccounting:
    # LM Studio frequently omits the usage block; everything else returns one.
    return "estimated" if backend == "lmstudio" else "exact"


def _privacy_class(backend: str, model: str, base_url: str) -> PrivacyClass:
    if backend in ("anthropic", "groq", "together"):
        return "public_api"
    if backend == "ollama":
        if _is_cloud_ollama(model):
            return "public_api"                  # Ollama Cloud egress
        return "local" if _is_local_url(base_url) else "private_endpoint"
    if backend == "lmstudio":
        return "local" if _is_local_url(base_url) else "private_endpoint"
    return "private_endpoint"                     # unknown OpenAI-compatible endpoint


def _cost(backend: str, model: str, base_url: str) -> Cost:
    if backend in ("anthropic", "groq", "together"):
        return "per_token"
    if backend == "ollama" and _is_cloud_ollama(model):
        return "unknown"                          # cloud pricing not modelled here
    if _is_local_url(base_url):
        return "flat"                             # local compute, no per-token charge
    return "unknown"


def _max_context(model: str) -> int:
    m = model.lower()
    for key, n in _CONTEXT_WINDOWS.items():
        if key in m:
            return n
    return _DEFAULT_CONTEXT


@dataclass(frozen=True)
class InferenceCapability:
    """A scoped capability to one inference binding within one org. Returned by
    :func:`vend_llm`; carries the *resolved binding* (backend · model · endpoint) and a
    *declared profile* so callers dispatch on capability, never on provider identity —
    the same seam :class:`~aughor.platform.vending.StorageCapability` is for storage."""

    org_id: str
    role: str
    backend: str
    model: str
    base_url: str
    # profile (§5b.2)
    cache_mode: CacheMode
    tooling: Tooling
    structured_output: StructuredOutput
    token_accounting: TokenAccounting
    max_context: int
    privacy_class: PrivacyClass
    cost: Cost

    def provider(self) -> "LLMProvider":
        """The live provider for this binding (lazy import avoids a load-time cycle)."""
        from aughor.llm.provider import get_provider

        return get_provider(self.role, model=self.model)  # type: ignore[arg-type]

    def complete(self, system: str, user: str, response_model: Type[T],
                 temperature: float = 0.1) -> T:
        """Front-door call through the vended capability."""
        return self.provider().complete(system, user, response_model, temperature)


def capability_for(backend: str, model: str, role: str, base_url: str,
                   org_id: Optional[str] = None) -> InferenceCapability:
    """Build the capability for an already-resolved binding (pure: strings in, profile out).
    Shared by :func:`vend_llm` and ``LLMProvider.capability`` so the two never drift."""
    return InferenceCapability(
        org_id=org_id or current_org_id() or DEFAULT_ORG_ID,
        role=role,
        backend=backend,
        model=model,
        base_url=base_url,
        cache_mode=_cache_mode(backend, model, base_url),
        tooling=_tooling(backend, model),
        structured_output=_structured_output(backend, model),
        token_accounting=_token_accounting(backend),
        max_context=_max_context(model),
        privacy_class=_privacy_class(backend, model, base_url),
        cost=_cost(backend, model, base_url),
    )


def vend_llm(role: "Role" = "coder", *, org_id: Optional[str] = None,
             model: Optional[str] = None) -> InferenceCapability:
    """The control plane vends a scoped inference capability for ``role``.

    Mirrors :func:`~aughor.platform.vending.vend_storage`: ``org_id`` defaults to the
    current tenant context, and the backend/model/endpoint are resolved through the one
    shared binding resolver (:func:`aughor.llm.provider.resolve_binding`) — so the vended
    capability always describes the binding a real ``complete()`` call will use. ``model``
    pins an explicit per-agent override (the future Agent level); with none, the run's
    ``set_run_model`` contextvar then the role default apply (Org → Workspace → Agent).
    """
    from aughor.llm.provider import resolve_binding  # lazy: provider imports this module

    backend, eff_model, base_url = resolve_binding(role, model=model)
    return capability_for(backend, eff_model, role, base_url, org_id=org_id)
