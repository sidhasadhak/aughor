"""The Capability-plane registry — the swap-point (AL-02).

A new capability drops in by `register_capability(impl)`; orchestration finds it by domain with
`get_capability` / `run_capability`, touching no other plane. Matches the module-level-dict
registry idiom of `kernel/registries/*` (a plain dict + register/get + `clear` for tests).
"""
from __future__ import annotations

from aughor.capability.pipeline import CapabilityPipeline, CapabilityRequest, CapabilityResult, run

_PIPELINES: dict[str, CapabilityPipeline] = {}


def register_capability(pipeline: CapabilityPipeline) -> None:
    """Register (or replace) the capability for `pipeline.domain`."""
    _PIPELINES[pipeline.domain] = pipeline


def get_capability(domain: str) -> CapabilityPipeline | None:
    return _PIPELINES.get(domain)


def registered_domains() -> list[str]:
    return sorted(_PIPELINES)


def run_capability(domain: str, req: CapabilityRequest) -> CapabilityResult | None:
    """Run the registered capability for `domain`, or None if none is registered."""
    p = _PIPELINES.get(domain)
    return run(p, req) if p is not None else None


def clear() -> None:
    """Drop all registrations (tests). Call `register_builtins()` to restore the built-ins."""
    _PIPELINES.clear()
