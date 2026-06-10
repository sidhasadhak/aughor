"""Commercial capability gating — the Free / Pro / Enterprise tier layer.

Lands *dark*: the default tier is `enterprise` (every capability on), so existing
behaviour is unchanged until a real sub-enterprise tier is assigned to a connection
(or via the `AUGHOR_TIER` env). Enforcement is opt-in per route via the
`require_capability` FastAPI dependency; the frontend reads `GET /capabilities`.

Single source of truth:
  - `capabilities.py` — the `Tier` + `Capability` enums and the additive tier→caps map.
  - `resolver.py`     — `resolve_tier()` / `has_capability()` (per-connection → env).
  - `deps.py`         — `require_capability(cap)` → HTTP 402 + upgrade hint.
"""
from aughor.licensing.capabilities import Capability, Tier, TIER_CAPABILITIES, capabilities_for
from aughor.licensing.resolver import resolve_tier, has_capability
from aughor.licensing.deps import require_capability

__all__ = [
    "Capability", "Tier", "TIER_CAPABILITIES", "capabilities_for",
    "resolve_tier", "has_capability", "require_capability",
]
