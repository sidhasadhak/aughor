"""The arc's close-out, C3 — the context graph as a projection of the ledger, rebuilt on demand
(the 2027 study §F: "a way of reading claims, not a place they live").

What these hold: the Record's measured findings and observations become the graph's finding nodes,
each naming the claim it reads, with the claim's tier as its warrant; a withdrawn finding, a
hypothesis and a said statement project nothing; a legacy source's finding that a claim already
covers is dropped and one that predates the Record is kept; a missing graph is rebuilt on demand
by the readers that answer questions and a present one is read, not rebuilt; and nothing under
`data/context_graph/` is tracked any more.
"""
from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

from aughor.ontology import context_graph_build as B
from aughor.ontology import context_graph_store as S
from aughor.ontology.context_graph import ProvenanceSource, project_graph
from aughor.ontology.graph_warrant import warrant_for, warrant_of_node
from aughor.ontology.models import OntologyEntity, OntologyGraph
from aughor.record import claims as C

REPO = Path(__file__).resolve().parents[2]


def _conn():
    return "conn-" + uuid.uuid4().hex[:6]


def _ontology(conn: str) -> OntologyGraph:
    g = OntologyGraph(connection_id=conn, schema_name="main", schema_fingerprint="fp")
    g.entities["Order"] = OntologyEntity(id="Order", display_name="Order", source_tables=["main.orders"], identity_key="id", grain_verified=True)
    return g


def _book(conn: str, kind: str, text: str, sql: str, *, tier="measured", key: str, extra=None, state=""):
    claim = C.Claim(kind=kind, tier=tier, about=C.About(kind="connection", key=conn),
                    statement=C.Statement(text=text), as_of="2026-10-01", author="agent:explorer", author_kind="agent", state=state,
                    warrants=[C.Warrant(kind="run", ref="rcpt-1", detail=sql)] if tier == "measured" else [], extra=extra or {})
    return C.book(claim, key=key, conn_id=conn)


def test_the_records_findings_are_the_graphs_finding_nodes_and_the_claims_tier_is_their_warrant():
    conn = _conn()
    fid = _book(conn, "finding", "Weekend days carry 31% of units", "SELECT dow, SUM(units) FROM main.orders GROUP BY 1",
                key=C.claim_key("finding", "explorer", conn, "main", "Sales__seasonality__1"), extra={"finding_id": "Sales__seasonality__1", "writer": "explorer"})
    oid = _book(conn, "observation", "1,744 orders a day last week", "SELECT COUNT(*) FROM orders",
                key=C.claim_key("observation", "answer", conn, "inv9"), extra={"investigation_id": "inv9"})
    _book(conn, "hypothesis", "returns rise with discounts", "", tier="said", key=C.claim_key("h", conn, "1"), state="open")
    _book(conn, "said", "we breached 187", "", tier="said", key=C.claim_key("said", conn, "1"))
    gone_key = C.claim_key("finding", "explorer", conn, "main", "Gone__1")
    _book(conn, "finding", "an old finding", "SELECT 1", key=gone_key)
    prior = C.latest(gone_key)
    new = prior.model_copy(deep=True); new.confidence = None; new.state = "withdrawn"
    C.restate(gone_key, new, conn_id=conn)
    found = B.load_record_findings(conn)
    by_id = {f["id"]: f for f in found}
    assert set(by_id) == {fid, oid}                                   # the hypothesis, the said statement and the withdrawn finding are not nodes
    f = by_id[fid]
    assert f["source"] == "record" and f["tables"] == ["main.orders"] and f["claim_key"].startswith("claim:finding:explorer") and f["tier"] == "measured"
    assert f["finding_id"] == "Sales__seasonality__1" and by_id[oid]["investigation_id"] == "inv9" and f["generated_at"] == "2026-10-01"
    cg = project_graph(_ontology(conn), org_id="default", connection_id=conn, schema_name="main", findings=found)
    node = cg.nodes[f"finding:{fid}"]
    assert node.provenance.source == "record" and "record" in ProvenanceSource.__args__
    assert node.data["claim_id"] == fid and node.data["claim_key"] == f["claim_key"] and node.data["tier"] == "measured" and node.data["author"] == "agent:explorer"
    assert any(e.kind == "grounded_in" and e.from_id == node.id for e in cg.edges.values())
    assert warrant_of_node(node).warrant == "derived" and "tier measured" in warrant_of_node(node).detail
    assert warrant_for(type("P", (), {"source": "record", "note": "tier=declared", "measured": None})()).warrant == "human"
    assert warrant_for(type("P", (), {"source": "record", "note": "tier=said", "measured": None})()).warrant == "inferred"
    assert warrant_for(type("P", (), {"source": "record", "note": "", "measured": None})()).warrant == "derived"


def test_a_legacy_finding_a_claim_covers_is_dropped_and_one_that_predates_the_record_is_kept():
    record = [{"id": "c1", "text": "x", "source": "record", "investigation_id": "inv9"},
              {"id": "c2", "text": "y", "source": "record", "finding_id": "Sales__1"}]
    legacy = [{"id": "rcpt-a", "text": "x again", "source": "evidence_ledger", "investigation_id": "inv9"},
              {"id": "Sales__1", "text": "y again", "source": "exploration"},
              {"id": "rcpt-old", "text": "from before the Record", "source": "evidence_ledger", "investigation_id": "inv1"},
              {"id": "Ops__7", "text": "an explorer finding never booked", "source": "dossier"}]
    merged = B.merge_finding_sources(record, legacy)
    assert [f["id"] for f in merged] == ["c1", "c2", "rcpt-old", "Ops__7"]
    assert B.merge_finding_sources([], legacy) == legacy and B.merge_finding_sources(record, []) == record


def test_a_missing_graph_is_rebuilt_on_demand_and_a_present_one_is_read_not_rebuilt(tmp_path, monkeypatch):
    from aughor.ontology.context_graph import ContextGraph
    monkeypatch.setattr(S, "_ROOT", tmp_path / "context_graph")
    built: list = []

    def fake_build(connection_id, schema_name=None, *, org_id=None, persist=True):
        built.append((connection_id, schema_name, org_id, persist))
        g = ContextGraph(org_id=org_id or "default", connection_id=connection_id, schema_name="main", schema_fingerprint="fp")
        if persist:
            S.save_graph(g)
        return g
    monkeypatch.setattr(B, "build_context_graph", fake_build)
    graphs = S.graphs_for_connection("default", "c-new")
    assert len(graphs) == 1 and built == [("c-new", None, "default", True)]
    assert S.load_graph("default", "c-new", "main") is not None                   # kept for the next reader
    assert len(S.graphs_for_connection("default", "c-new")) == 1 and len(built) == 1   # present → read, not rebuilt
    assert S.graphs_for_connection("default", "c-none", build=False) == [] and len(built) == 1
    monkeypatch.setattr(B, "build_context_graph", lambda *a, **k: None)
    assert S.graphs_for_connection("default", "no-ontology") == []                 # no ontology yet → no graph, said by the empty list
    # the readers that answer questions go through the on-demand door
    import inspect
    from aughor.govern import lineage
    from aughor.mcp import knowledge_tools
    from aughor.ontology import answer_trace, context_graph_readback
    for mod in (lineage, knowledge_tools, answer_trace, context_graph_readback):
        assert "graphs_for_connection" in inspect.getsource(mod), mod.__name__


def test_nothing_under_the_graph_directory_is_tracked_any_more():
    try:
        out = subprocess.run(["git", "ls-files", "data/context_graph"], cwd=REPO, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return                                                         # not a git checkout: nothing to measure
    assert out.strip() == "", out
    from aughor.db import home
    assert "context_graph" not in home.AUTHORED_ENTRIES
    ignore = (REPO / ".gitignore").read_text()
    assert "\ndata/context_graph/\n" in ignore
