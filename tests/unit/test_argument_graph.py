"""Argument-graph builder (Briefing cockpit, Slice 3).

Pure/deterministic unit tests for `build_argument_graph` — the projection of the impact-ranked
briefing drivers + the explorer's own typed edges (composition_type/parents, drill_of) into a
{nodes, edges} graph. No LLM, no I/O. Verifies node/edge derivation, parent resolution across
domains, the verdict apex, cited flags, the parent cap, and dedup/self-loop safety.
"""
from __future__ import annotations

from aughor.knowledge.argument_graph import VERDICT_ID, build_argument_graph


def _edges_of(graph, etype):
    return [(e["source"], e["target"]) for e in graph["edges"] if e["type"] == etype]


def _node(graph, nid):
    return next((n for n in graph["nodes"] if n["id"] == nid), None)


DOMAIN_DATA = {
    "Customer": [
        {"id": "cust__a", "domain": "Customer", "finding": "Return rate is 32%",
         "sql": "SELECT 0.32", "_impact": 0.80},
        {"id": "cust__b", "domain": "Customer", "finding": "Repeat-buy rate slipped",
         "sql": "SELECT 1", "_impact": 0.50},
    ],
    "Marketing": [
        {"id": "mkt__c", "domain": "Marketing", "finding": "Paid search is the closer",
         "sql": "SELECT 2", "_impact": 0.60},
    ],
    "Synthesis": [
        {"id": "synth__tension__1", "domain": "Synthesis", "angle": "tension",
         "finding": "Returns rise as repeat-buy falls", "sql": "SELECT 3", "_impact": 0.90,
         "composition_type": "tension", "parents": ["cust__a", "cust__b"], "synthesized": True},
    ],
}


def test_empty_top_is_empty_graph():
    assert build_argument_graph([], "headline", DOMAIN_DATA) == {"nodes": [], "edges": []}


def test_verdict_apex_and_supports_edges():
    top = [DOMAIN_DATA["Marketing"][0], DOMAIN_DATA["Customer"][0]]
    g = build_argument_graph(top, "Returns Pressure The Quarter", DOMAIN_DATA)

    verdict = _node(g, VERDICT_ID)
    assert verdict and verdict["kind"] == "verdict"
    assert verdict["title"] == "Returns Pressure The Quarter"
    # Every ranked driver supports the verdict (evidence → claim).
    assert set(_edges_of(g, "supports")) == {("mkt__c", VERDICT_ID), ("cust__a", VERDICT_ID)}
    assert _node(g, "cust__a")["is_driver"] is True
    assert _node(g, "cust__a")["has_sql"] is True


def test_synthesis_parents_resolved_and_typed():
    # The synth driver's two parents — one is also a driver (cust__a), one is NOT in top (cust__b).
    top = [DOMAIN_DATA["Synthesis"][0], DOMAIN_DATA["Customer"][0]]
    g = build_argument_graph(top, "headline", DOMAIN_DATA)

    # cust__b was pulled in from domain_data as a (non-driver) node so its edge resolves.
    b = _node(g, "cust__b")
    assert b is not None and b["is_driver"] is False
    # Typed composition edges point parent → synthesis.
    assert set(_edges_of(g, "tension")) == {
        ("cust__a", "synth__tension__1"), ("cust__b", "synth__tension__1"),
    }
    # The synth node carries its composition_type for distinct rendering.
    assert _node(g, "synth__tension__1")["composition_type"] == "tension"


def test_cited_flag_from_citations():
    top = [DOMAIN_DATA["Customer"][0], DOMAIN_DATA["Marketing"][0]]
    g = build_argument_graph(top, "h", DOMAIN_DATA,
                             citations=[{"ref": "1", "insight_id": "cust__a"}])
    assert _node(g, "cust__a")["cited"] is True
    assert _node(g, "mkt__c")["cited"] is False


def test_drill_of_explains_why_between_drivers():
    data = {"Ops": [
        {"id": "ops__parent", "domain": "Ops", "finding": "Warehouse overbuy", "sql": "s", "_impact": 0.7},
        {"id": "ops__drill", "domain": "Ops", "finding": "Bologna markdown 33%", "sql": "s",
         "_impact": 0.85, "drill_of": "ops__parent"},
    ]}
    # Both the drill and its parent are ranked drivers → the explains_why edge connects them.
    g = build_argument_graph([data["Ops"][1], data["Ops"][0]], "h", data)
    assert ("ops__drill", "ops__parent") in _edges_of(g, "explains_why")


def test_drill_parent_not_in_graph_is_skipped():
    # Only the drill is a driver; its parent is not — no floating unrooted node/edge is added.
    data = {"Ops": [
        {"id": "ops__parent", "domain": "Ops", "finding": "Warehouse overbuy", "sql": "s", "_impact": 0.7},
        {"id": "ops__drill", "domain": "Ops", "finding": "Bologna markdown 33%", "sql": "s",
         "_impact": 0.85, "drill_of": "ops__parent"},
    ]}
    g = build_argument_graph([data["Ops"][1]], "h", data)
    assert _node(g, "ops__parent") is None
    assert _edges_of(g, "explains_why") == []


def test_parent_cap_bounds_the_graph():
    parents = [f"p{i}" for i in range(10)]
    data = {
        "P": [{"id": p, "domain": "P", "finding": p, "sql": "s"} for p in parents],
        "S": [{"id": "s__share__1", "domain": "S", "finding": "big synth", "sql": "s",
               "_impact": 0.9, "composition_type": "share", "parents": parents}],
    }
    g = build_argument_graph([data["S"][0]], "h", data, max_parents=3)
    # verdict + synth + at most 3 parents.
    assert len([n for n in g["nodes"] if n["kind"] == "finding"]) == 1 + 3
    assert len(_edges_of(g, "share")) == 3


def test_dedup_and_no_self_loop():
    data = {"S": [{"id": "s1", "domain": "S", "finding": "f", "sql": "s", "_impact": 0.9,
                   "composition_type": "chain", "parents": ["s1", "cust__a", "cust__a"]}],
            "Customer": DOMAIN_DATA["Customer"]}
    g = build_argument_graph([data["S"][0]], "h", data)
    chain = _edges_of(g, "chain")
    assert ("s1", "s1") not in [(s, t) for s, t in chain]     # no self-loop
    assert chain.count(("cust__a", "s1")) == 1                # duplicate parent → one edge


def test_missing_parent_id_is_skipped():
    data = {"S": [{"id": "s1", "domain": "S", "finding": "f", "sql": "s", "_impact": 0.9,
                   "composition_type": "confound", "parents": ["ghost_id"]}]}
    g = build_argument_graph([data["S"][0]], "h", data)
    assert _edges_of(g, "confound") == []                     # unresolvable parent → no edge
    assert _node(g, "ghost_id") is None


def test_generate_narrative_wires_graph_into_response(monkeypatch):
    """The graph rides along with the briefing narrative dict (which the endpoint spreads to the
    client). Stub the LLM narrator so the test stays deterministic and offline."""
    from aughor.knowledge import briefing as B

    class _FakeNarrator:
        def complete(self, **_kw):
            return B.BriefingNarrative(
                narrative="Returns are rising [1] as repeat-buy slips [2].",
                citations=[
                    B.BriefingCitation(ref="1", insight_id="", finding="", domain="Customer", angle=""),
                    B.BriefingCitation(ref="2", insight_id="", finding="", domain="Customer", angle=""),
                ],
                headline_theme="Returns Pressure The Quarter",
            )

    monkeypatch.setattr("aughor.llm.provider.get_provider", lambda role: _FakeNarrator())

    domain_data = {
        "Customer": [
            {"id": "cust__a", "domain": "Customer", "finding": "Return rate is 32%",
             "sql": "SELECT 0.32", "novelty": 3, "confidence": 0.8},
        ],
        "Synthesis": [
            {"id": "synth__tension__1", "domain": "Synthesis", "angle": "tension",
             "finding": "Returns rise as repeat-buy falls", "sql": "SELECT 1", "novelty": 4,
             "confidence": 0.7, "composition_type": "tension",
             "parents": ["cust__a", "cust__b"], "synthesized": True},
        ],
    }
    result = B.generate_narrative(domain_data, patterns=[], connection_id="conn_ag_test")

    assert "graph" in result
    g = result["graph"]
    assert any(n["kind"] == "verdict" and n["title"] == "Returns Pressure The Quarter"
               for n in g["nodes"])
    assert any(e["type"] == "supports" for e in g["edges"])          # drivers → verdict
