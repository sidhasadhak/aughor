"""Mode manifest registry (P5, AI-FDE Pillar C).

Loads the editable mode manifests from ``manifests/*.yaml`` and exposes them to the
router, with the hardcoded modes as a validated fallback. Adding a route keyword to a
manifest changes routing with no code change; an invalid/absent manifest falls back to
code behaviour, so it can never break the agent (fail-safe). Gated by
``AUGHOR_DECLARATIVE_MODES`` — off by default, so the router path is unchanged.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

import yaml

from aughor.agent.modes.models import ModeManifest, SchemaScope

_MANIFEST_DIR = Path(__file__).parent / "manifests"

# The structural modes the graph knows how to run. A manifest may tune these; it may
# NOT invent a fifth structural mode (that needs a graph branch), so an unknown-name
# manifest is ignored for routing.
STRUCTURAL_MODES = ("direct", "investigate", "explore", "final_text")


def declarative_modes_enabled() -> bool:
    return os.getenv("AUGHOR_DECLARATIVE_MODES", "").strip().lower() in ("1", "true", "yes", "on")


@lru_cache(maxsize=1)
def load_manifests() -> dict[str, ModeManifest]:
    """Load + validate every manifest. Malformed files are skipped (one bad file never
    blocks the rest); returns {mode_name: ModeManifest}. Cached — call cache_clear() in tests."""
    out: dict[str, ModeManifest] = {}
    if not _MANIFEST_DIR.is_dir():
        return out
    for f in sorted(_MANIFEST_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text()) or {}
            m = ModeManifest(**data)
            out[m.name] = m
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, f"skip malformed mode manifest {f.name}; others still load",
                     counter="modes.manifest_parse")
    return out


def get_mode(name: str) -> ModeManifest | None:
    return load_manifests().get(name)


def list_modes() -> list[ModeManifest]:
    return list(load_manifests().values())


def scope_for_mode(name: str) -> SchemaScope:
    """The context-scope policy for a mode (feeds the P2 context surface). Falls back to
    the default breadth/cap when no manifest declares one."""
    m = get_mode(name)
    return m.schema_scope if m else SchemaScope()


def apply_route_overrides(question: str, effective_mode: str, decision) -> tuple[str, object]:
    """Deterministic, file-driven routing overrides layered on the LLM decision.

    No-op when declarative modes are disabled (default) → router behaviour unchanged.
    When enabled, the first enabled manifest whose ``route_keywords`` match the question
    (and whose ``route_from`` admits the current mode) overrides the mode. Returns the
    possibly-updated (mode, decision)."""
    if not declarative_modes_enabled():
        return effective_mode, decision
    q = question or ""
    for m in load_manifests().values():
        if not m.enabled or m.name not in STRUCTURAL_MODES or not m.route_keywords:
            continue
        if m.route_from and effective_mode not in m.route_from:
            continue
        if m.name == effective_mode:
            continue  # nothing to override
        for pat in m.route_keywords:
            try:
                matched = re.search(pat, q, re.IGNORECASE)
            except re.error as _e:
                from aughor.kernel.errors import tolerate
                tolerate(_e, f"skip invalid regex in mode manifest '{m.name}'; routing survives",
                         counter="modes.bad_pattern")
                continue
            if matched:
                if decision is not None:
                    decision.mode = m.name
                    decision.reasoning = (getattr(decision, "reasoning", "") or "") + \
                        f" [mode-manifest '{m.name}' keyword override]"
                return m.name, decision
    return effective_mode, decision
