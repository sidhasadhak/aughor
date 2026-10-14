"""A schema's Graph is that schema's graph (2026-10-13).

LuxExperience keeps one committed graph per schema (gold_finance, luxexperience). Every graph read merged them, so the
luxexperience Graph tab drew gold_finance's 37 tables beside its own, and its freshness compared that merge with one
schema's ontology. And "Rebuild owed" said a rebuild was owed with nothing that could do it.
"""
from __future__ import annotations

import pytest


def _graph(schema: str, table: str):
    from aughor.ontology.context_graph import ContextGraph, GraphNode, Provenance
    cg = ContextGraph(org_id="default", connection_id="lux", schema_name=schema)
    cg.add_node(GraphNode(id=f"table:{table}", kind="table", label=table, provenance=Provenance(source="ontology.entity")))
    return cg


@pytest.fixture
def two_schemas(monkeypatch, tmp_path):
    from aughor.ontology import context_graph_store as store
    monkeypatch.setattr(store, "_ROOT", tmp_path / "context_graph")
    store.save_graph(_graph("gold_finance", "Ledger"))
    store.save_graph(_graph("luxexperience", "Order"))
    return store


def test_a_named_schema_reads_its_own_graph_and_the_connection_reads_them_merged(two_schemas):
    own = two_schemas.committed_graph("default", "lux", "luxexperience")
    assert set(own.nodes) == {"table:Order"}
    assert set(two_schemas.committed_graph("default", "lux").nodes) == {"table:Order", "table:Ledger"}
    assert two_schemas.committed_graph("default", "lux", "nowhere") is None


def test_the_graph_route_answers_for_the_schema_it_was_asked_about(two_schemas):
    from aughor.routers.ontology import get_context_graph
    out = get_context_graph("lux", "luxexperience")
    assert set(out["nodes"]) == {"table:Order"}


def test_rebuild_runs_the_forced_refresh_and_says_when_nothing_was_rebuilt(monkeypatch):
    from fastapi import HTTPException

    from aughor.ontology import graph_freshness as gf
    from aughor.routers.ontology import rebuild_context_graph

    asked: list[tuple] = []

    def refresh(conn, schema, *, org_id="", reindex=True, force=False):
        asked.append((conn, schema, force))
        return gf.RefreshResult(verdict=gf.FreshnessVerdict("full", "stale"), rebuilt=True, indexed=12)
    monkeypatch.setattr(gf, "refresh_context_graph", refresh)
    assert rebuild_context_graph("lux", "luxexperience")["indexed"] == 12
    assert asked == [("lux", "luxexperience", True)]

    monkeypatch.setattr(gf, "refresh_context_graph", lambda *a, **k: gf.RefreshResult(
        verdict=gf.FreshnessVerdict("unknown", "unknown", reason="no built ontology"), rebuilt=False))
    with pytest.raises(HTTPException) as said:
        rebuild_context_graph("lux", "luxexperience")
    assert said.value.status_code == 409 and "no built ontology" in said.value.detail
