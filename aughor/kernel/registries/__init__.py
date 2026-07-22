"""Platform extension registries — the seams the Agent plugs into.

The Data Intelligence Platform owns these registries (purge hooks, schema
annotators, ingestion sinks, execution hooks) but never imports the Agent. The
Agent contributes its intelligence by *registering* into them at startup (see
``aughor.agent.bootstrap.register_agent_plugins``). With nothing registered, the
platform degrades to its raw, agent-free behaviour — which is exactly the
"platform runs without the agent" plug-and-play property.
"""
from __future__ import annotations


def manifest() -> dict[str, list[str]]:
    """What is currently plugged into the platform — the agent's contribution made
    legible (for the fleet view / introspection / the plug-and-play proof). Returns
    ``{registry: [names]}``; all-empty means a bare platform (no agent)."""
    from aughor.kernel.registries import (
        execution_hooks as _eh,
        ingestion as _ing,
        purge_hooks as _ph,
        resource_org as _ro,
        schema_annotators as _sa,
    )
    return {
        "schema_annotators": [n for n, _ph_, _fn in _sa._ANNOTATORS],
        "purge_hooks": (
            [n for n, _ in _ph._CONN]
            + [f"schema:{n}" for n, _ in _ph._SCHEMA]
            + [f"inv:{n}" for n, _ in _ph._INV]
        ),
        "ingest_sinks": list(_ing._SINKS),
        "post_execute_hooks": [n for n, _ in _eh._POST_EXECUTE],
        "on_connect_hooks": [n for n, _ in _eh._ON_CONNECT],
        "resource_org_resolvers": _ro.registered_kinds(),
        "evaluators": _registered_evaluators(),
    }


def _registered_evaluators() -> list[str]:
    """The Evals plane's registrations (Wave E2). Imported lazily and tolerantly:
    the manifest is introspection, and a plane failing to load must show up as an
    empty list here rather than breaking the view that would have revealed it."""
    try:
        from aughor.evals.registry import registered_evaluators
        return registered_evaluators()
    except Exception:
        return []
