"""Wave C1 — the finding-node path proven end-to-end through the REAL stores.

Runs under the conftest data isolation (``AUGHOR_STATE_DIR`` + ``AUGHOR_SYSTEM_DB``
point at a temp dir), so this exercises the real ``explorer.store`` enumeration and
the real Ledger dossier read — the write-only half of the open feedback loop becoming
a graph node — without touching live data or spending an LLM request. The unit tests
prove the projection logic in isolation; this proves the build orchestration reads
real persisted findings and marks their provenance from the actual dossier artifact.
"""
from __future__ import annotations

from aughor.explorer import store as explorer_store
from aughor.kernel.ledger import Ledger
from aughor.ontology.context_graph_build import build_context_graph
from aughor.ontology.models import OntologyEntity, OntologyGraph
from aughor.ontology.store import save_ontology

SCHEMA = "main"
FP = "itfp1"


def _seed_ontology(conn: str) -> None:
    g = OntologyGraph(connection_id=conn, schema_name=SCHEMA, schema_fingerprint=FP)
    g.entities = {
        "Widget": OntologyEntity(
            id="Widget", display_name="Widget", source_tables=["widgets"],
            identity_key="id", grain_verified=True, domain="Catalog",
        )
    }
    save_ontology(conn, SCHEMA, FP, g)


def test_finding_node_from_a_real_dossier(monkeypatch):
    conn = "ctxgraph_it_dossier"
    monkeypatch.setenv("AUGHOR_GRAPH_BUILD", "1")
    _seed_ontology(conn)

    insight_id = "Catalog__widgets__1"
    # a real exploration insight, persisted through the real store
    explorer_store.save(conn, {"insights": [{
        "id": insight_id,
        "finding": "8% of widgets have never been ordered",
        "sql": "SELECT COUNT(*) FROM widgets WHERE order_count = 0",
        "domain": "Catalog",
        "generated_at": "2026-07-25T00:00:00Z",
    }]})
    # a real captured dossier for that finding — the supersede-not-delete 'finding'
    # artifact the CEO-'how was this derived?' path renders at zero recompute
    Ledger.default().artifact_write(
        "finding", f"insight:{conn}:{insight_id}",
        {"finding": "8% of widgets have never been ordered",
         "dossier": {"dossier_version": 1, "sql": "SELECT ... FROM widgets",
                     "grounding": {"grounded": True, "checked": 3, "ungrounded": []}}},
        conn_id=conn,
    )

    g = build_context_graph(conn)
    assert g is not None, "build returned None — flag or ontology missing"

    # the finding is now a NODE — the open loop closed for this finding
    fnode = g.nodes.get(f"finding:{insight_id}")
    assert fnode is not None and fnode.kind == "finding"
    # sourced from the DOSSIER (proving _has_dossier read the real Ledger artifact),
    # and its self-reported confidence is NOT laundered into a measurement
    assert fnode.provenance.source == "dossier"
    assert fnode.provenance.measured is None

    # grounded_in edge: finding → the table it reads, carrying dossier provenance
    edge = next(e for e in g.edges.values()
                if e.kind == "grounded_in" and e.from_id == f"finding:{insight_id}")
    assert edge.to_id == "table:Widget"
    assert edge.provenance.source == "dossier"


def test_finding_without_dossier_is_honestly_sourced_as_exploration(monkeypatch):
    conn = "ctxgraph_it_nodossier"
    monkeypatch.setenv("AUGHOR_GRAPH_BUILD", "1")
    _seed_ontology(conn)
    explorer_store.save(conn, {"insights": [{
        "id": "x1", "finding": "a finding with no captured dossier",
        "sql": "SELECT 1 FROM widgets", "generated_at": "",
    }]})

    g = build_context_graph(conn)
    assert g is not None
    fnode = g.nodes.get("finding:x1")
    assert fnode is not None
    assert fnode.provenance.source == "exploration"  # not "dossier" — none was written
