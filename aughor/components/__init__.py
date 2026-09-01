"""DS-10 — one component registry: every capability this deployment actually has.

The rosters existed; there were five of them, and nothing could read them together. An
automation kind lived in `automations/palette.py`, a connector type in
`connectors/registry.py`, an agent tool in `agent/platform_tools.py`, an MCP tool in a
decorator inside `mcp/server.py`, and a declared action in an ontology overlay. Each was
correct and none knew about the others, so "what can this install do" had no answer — and
the palette, which is the surface that most needs one, could only offer the two families it
happened to import.

This package does NOT copy them. Each family is adapted from its own source of truth at
read time, which is the only arrangement in which a sixth effect kind or a new connector
appears here without anyone remembering to add it twice.
"""
from aughor.components.registry import (
    BADGES,
    Component,
    ComponentPort,
    FAMILIES,
    GOVERNORS,
    components,
)

__all__ = ["BADGES", "Component", "ComponentPort", "FAMILIES", "GOVERNORS", "components"]
