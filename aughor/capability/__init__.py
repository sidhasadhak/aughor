"""The Capability plane (③) — one `Generate → Validate → Execute → Interpret` template,
parameterized by domain, with a registry swap-point (AL-02 of the Part-2 architecture review).

    from aughor.capability import run_capability, CapabilityRequest
    from aughor.trust import Scope
    res = run_capability("data", CapabilityRequest(artifact=sql, scope=Scope(conn=db)))

`validate` routes through the Trust plane (`aughor/trust`, AL-01); a new capability is added by
registering one impl (see `builtins.SqlCapability`), reusing Trust/Semantic/Memory unchanged.
"""
from aughor.capability.pipeline import (
    CapabilityPipeline,
    CapabilityRequest,
    CapabilityResult,
    default_validate,
    run,
)
from aughor.capability.registry import (
    clear,
    get_capability,
    register_capability,
    registered_domains,
    run_capability,
)
from aughor.capability.builtins import register_builtins

# Register the built-in capabilities on import, so `run_capability("data", …)` works out of the box.
register_builtins()

__all__ = [
    "CapabilityPipeline", "CapabilityRequest", "CapabilityResult", "default_validate", "run",
    "register_capability", "get_capability", "registered_domains", "run_capability", "clear",
    "register_builtins",
]
