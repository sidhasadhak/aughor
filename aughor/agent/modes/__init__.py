"""Declarative agent modes (AI-FDE Pillar C, P5).

Editable mode manifests + a registry that tunes routing/context-scope from files with a
hardcoded fallback. See :mod:`aughor.agent.modes.registry`.
"""
from aughor.agent.modes.models import ModeManifest, SchemaScope
from aughor.agent.modes.registry import (
    STRUCTURAL_MODES,
    apply_route_overrides,
    declarative_modes_enabled,
    get_mode,
    list_modes,
    load_manifests,
    scope_for_mode,
)

__all__ = [
    "ModeManifest", "SchemaScope", "STRUCTURAL_MODES",
    "apply_route_overrides", "declarative_modes_enabled",
    "get_mode", "list_modes", "load_manifests", "scope_for_mode",
]
