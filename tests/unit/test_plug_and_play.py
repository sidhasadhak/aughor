"""Plug-and-play proof — the Platform runs without the Agent.

The separation's promise is that the Data Intelligence Platform is a self-contained
*home*: it renders schemas, executes queries, and tears down connections on its own
authority, and the Aughor Agent plugs *in* through the registries. These tests prove
both halves: the agent's contribution is registered and legible (the manifest), and
with that contribution removed the platform degrades to correct raw behaviour rather
than breaking.
"""
from __future__ import annotations


def test_plugin_manifest_is_populated():
    """After registration the agent's contributions are legible via the manifest."""
    from aughor.kernel.registries import manifest
    m = manifest()
    # enrichment / intelligence / exploration annotators
    assert set(m["schema_annotators"]) >= {"enrichment", "intelligence", "exploration"}
    assert m["purge_hooks"]                       # per-store purge hooks
    assert "knowledge" in m["ingest_sinks"]       # the knowledge-ingestion sink
    assert m["post_execute_hooks"] and m["on_connect_hooks"]   # ai_sql hooks


def test_platform_renders_schema_without_the_agent():
    """With the schema annotators cleared, get_schema() still returns the raw governed
    schema (structure renders), and it is the agent's annotators that add enrichment."""
    from aughor.db.connection import open_connection_for
    from aughor.kernel.registries import schema_annotators as sa

    db = open_connection_for("fixture")
    enriched = db.get_schema()                    # agent registered (conftest fixture)

    saved = list(sa._ANNOTATORS)
    sa.clear()
    try:
        bare = db.get_schema()
        assert "TABLE:" in bare                   # raw structure renders with no agent
        assert len(bare) < len(enriched)          # the annotators added the enrichment
    finally:
        sa._ANNOTATORS[:] = saved                 # restore for the rest of the session


def test_platform_purge_runs_platform_only_without_the_agent():
    """With the purge hooks cleared, the connection-delete cascade runs only its
    platform-owned steps — never an agent store — and never raises."""
    from aughor.db import purge
    from aughor.kernel.registries import purge_hooks as ph

    saved = (list(ph._CONN), list(ph._SCHEMA), list(ph._INV))
    ph.clear()
    try:
        counts = purge.purge_connection_artifacts("nonexistent_conn")
        # No agent-owned artifact keys appear (those come from the hooks we cleared).
        for agent_key in ("ontology", "profile", "evidence_claims", "monitors",
                          "pack_bindings", "briefing_cache"):
            assert agent_key not in counts
    finally:
        ph._CONN[:], ph._SCHEMA[:], ph._INV[:] = saved
