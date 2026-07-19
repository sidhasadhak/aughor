"""Argument-graph builder (Briefing cockpit, Slice 3).

Pure/deterministic unit tests for `build_argument_graph` — the projection of the impact-ranked
briefing drivers + the explorer's own typed edges (composition_type/parents, drill_of) into a
{nodes, edges} graph. No LLM, no I/O. Verifies node/edge derivation, parent resolution across
domains, the verdict apex, cited flags, the parent cap, and dedup/self-loop safety.
"""
from __future__ import annotations

from aughor.knowledge.argument_graph import VERDICT_ID, build_argument_graph, relate_cards


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


def test_non_driver_drill_parent_pulled_and_rooted():
    # Only the drill is a driver; its parent is NOT. The parent is pulled in from domain_data as a
    # non-driver node and rooted with a supports→verdict edge, so the why-chain connects (instead of
    # the drill floating): drill → parent (explains_why), parent → verdict (supports).
    data = {"Ops": [
        {"id": "ops__parent", "domain": "Ops", "finding": "Warehouse overbuy", "sql": "s", "_impact": 0.7},
        {"id": "ops__drill", "domain": "Ops", "finding": "Bologna markdown 33%", "sql": "s",
         "_impact": 0.85, "drill_of": "ops__parent"},
    ]}
    g = build_argument_graph([data["Ops"][1]], "h", data)
    parent = _node(g, "ops__parent")
    assert parent is not None and parent["is_driver"] is False
    assert ("ops__drill", "ops__parent") in _edges_of(g, "explains_why")
    assert ("ops__parent", VERDICT_ID) in _edges_of(g, "supports")


def test_drill_parent_absent_from_domain_data_is_noop():
    # drill_of points at an id that isn't in domain_data at all → nothing to pull; no crash, no edge.
    data = {"Ops": [
        {"id": "ops__drill", "domain": "Ops", "finding": "Bologna markdown 33%", "sql": "s",
         "_impact": 0.85, "drill_of": "ghost__id"},
    ]}
    g = build_argument_graph([data["Ops"][0]], "h", data)
    assert _node(g, "ghost__id") is None
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


# ── relate_cards (card ↔ finding connective tissue, Slice 4) ──────────────────

_FINDINGS = [
    {"id": "f_orders", "sql": "SELECT region, SUM(gmv) AS gmv FROM orders GROUP BY region",
     "signature": {"tables": ["orders"], "measures": ["gmv"], "dimensions": ["region"]}},
    {"id": "f_cust", "sql": "SELECT COUNT(*) AS n FROM customers",
     "signature": {"tables": ["customers"], "measures": ["n"], "dimensions": []}},
]


def test_relate_cards_links_by_signature_overlap():
    cards = [{"id": "card1", "title": "GMV total", "sql": "SELECT SUM(gmv) AS gmv FROM orders"}]
    r = relate_cards(cards, _FINDINGS)
    # The card shares table `orders` + measure `gmv` with f_orders (not f_cust).
    assert any(n["id"] == "card1" and n["kind"] == "card" for n in r["nodes"])
    assert r["edges"] == [{"source": "card1", "target": "f_orders", "type": "relates_to"}]


def test_relate_cards_no_overlap_no_edge():
    cards = [{"id": "card2", "title": "Consent", "sql": "SELECT COUNT(*) FROM consent"}]
    r = relate_cards(cards, _FINDINGS)
    assert r == {"nodes": [], "edges": []}                    # no shared table/measure → nothing


def test_relate_cards_caps_edges_per_card():
    findings = [
        {"id": f"f{i}", "sql": f"SELECT SUM(gmv) FROM orders WHERE d={i}",
         "signature": {"tables": ["orders"], "measures": ["gmv"], "dimensions": []}}
        for i in range(5)
    ]
    cards = [{"id": "c", "title": "GMV", "sql": "SELECT SUM(gmv) FROM orders"}]
    r = relate_cards(cards, findings, max_edges_per_card=2)
    assert len([e for e in r["edges"] if e["source"] == "c"]) == 2   # capped


def test_relate_cards_skips_empty_card_sql():
    r = relate_cards([{"id": "note1", "title": "A note", "sql": ""}], _FINDINGS)
    assert r == {"nodes": [], "edges": []}                    # a note (no SQL) has nothing to relate


# ── Densify: `related` sibling edges among the drivers (Slice-3 follow-up) ─────

def _related(g):
    return [(e["source"], e["target"], e.get("label")) for e in g["edges"] if e["type"] == "related"]


def test_densify_relates_drivers_sharing_a_join_key():
    top = [
        {"id": "rev", "domain": "Sales", "finding": "Revenue by region", "sql": "x", "_impact": 0.9,
         "signature": {"tables": ["orders"], "dimensions": ["region"], "measures": ["revenue"]}},
        {"id": "ret", "domain": "Returns", "finding": "Return rate by region", "sql": "x", "_impact": 0.8,
         "signature": {"tables": ["returns"], "dimensions": ["region"], "measures": ["return_rate"]}},
    ]
    g = build_argument_graph(top, "h", {"d": top})
    rel = _related(g)
    # Both are drivers sharing the `region` cut with different measures → one `related` edge,
    # labelled with the shared dimension.
    assert len(rel) == 1
    assert {rel[0][0], rel[0][1]} == {"rev", "ret"}
    assert rel[0][2] == "region"


def test_densify_does_not_duplicate_a_composition_edge():
    # A synth driver already links its two parents via `chain`; densify must not ALSO relate them.
    data = {"S": [
        {"id": "syn", "domain": "S", "finding": "combined", "sql": "x", "_impact": 0.9,
         "composition_type": "chain", "parents": ["p1", "p2"],
         "signature": {"tables": ["t"], "dimensions": ["seg"], "measures": ["m1"]}},
    ], "P": [
        {"id": "p1", "domain": "P", "finding": "p1", "sql": "x", "_impact": 0.85,
         "signature": {"tables": ["t"], "dimensions": ["seg"], "measures": ["a"]}},
        {"id": "p2", "domain": "P", "finding": "p2", "sql": "x", "_impact": 0.8,
         "signature": {"tables": ["t"], "dimensions": ["seg"], "measures": ["b"]}},
    ]}
    top = [data["S"][0], data["P"][0], data["P"][1]]
    g = build_argument_graph(top, "h", data)
    # p1↔p2 are already joined (p1→syn, p2→syn via chain); no `related` edge between p1 and p2.
    assert frozenset(("p1", "p2")) not in {frozenset((s, t)) for s, t, _ in _related(g)}


def test_densify_no_shared_key_no_related():
    top = [
        {"id": "a", "domain": "A", "finding": "a", "sql": "x", "_impact": 0.9,
         "signature": {"tables": ["ta"], "dimensions": ["da"], "measures": ["ma"]}},
        {"id": "b", "domain": "B", "finding": "b", "sql": "x", "_impact": 0.8,
         "signature": {"tables": ["tb"], "dimensions": ["db"], "measures": ["mb"]}},
    ]
    g = build_argument_graph(top, "h", {"d": top})
    assert _related(g) == []                                  # disjoint signatures → no relatedness


def test_densify_is_bounded():
    from aughor.knowledge.argument_graph import MAX_RELATED_EDGES
    # Many drivers all sharing one dimension but with distinct measures → many eligible pairs.
    top = [
        {"id": f"n{i}", "domain": f"D{i}", "finding": f"f{i}", "sql": "x", "_impact": 1.0 - i / 100,
         "signature": {"tables": ["t"], "dimensions": ["seg"], "measures": [f"m{i}"]}}
        for i in range(8)
    ]
    g = build_argument_graph(top, "h", {"d": top})
    assert len(_related(g)) <= MAX_RELATED_EDGES              # capped — never a hairball
