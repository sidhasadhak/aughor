"""Wave P2 — the warrant class derived from provenance.

The load-bearing tests here are the ROT GUARDS: the warrant for a join and for an
ambiguity resolution is read out of `Provenance.note`, which the projection writes. If a
projection ever stops emitting `join_confidence=` or `resolution_source=`, every affected
edge would silently fall to the weakest class and the surface would keep rendering, quietly
wrong. So those two are proven through the REAL projection, not a hand-built Provenance.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from aughor.ontology.context_graph import (
    ContextGraph, GraphEdge, GraphNode, Provenance, project_graph,
)
from aughor.ontology.graph_warrant import (
    WARRANT_ORDER, audit, note_field, warrant_for, warrant_of_edge, warrant_of_node,
)


# ── the rule that matters most: a number, not a source name, makes a measurement ──

def test_join_guard_without_a_number_is_not_measured():
    """The proxy trap: `source="join_guard"` names an origin, not a measurement."""
    unprobed = Provenance(source="join_guard", measured=None,
                          note="unprobed join_confidence=inferred")
    v = warrant_for(unprobed)
    assert v.warrant == "inferred"
    assert "not probed" in v.detail


def test_join_guard_with_a_number_is_measured():
    probed = Provenance(source="join_guard", measured=0.983,
                        note="value_overlap=0.983 join_confidence=verified")
    v = warrant_for(probed)
    assert v.warrant == "measured"
    assert "98%" in v.detail


def test_declared_foreign_key_outranks_a_name_match():
    """Both are unprobed; only one is a statement by the source system."""
    fk = warrant_for(Provenance(source="join_guard", note="unprobed join_confidence=exact"))
    name = warrant_for(Provenance(source="join_guard", note="unprobed join_confidence=inferred"))
    assert fk.warrant == "declared"
    assert name.warrant == "inferred"
    assert WARRANT_ORDER.index(fk.warrant) < WARRANT_ORDER.index(name.warrant)


def test_verified_tier_without_an_overlap_does_not_claim_a_measurement():
    v = warrant_for(Provenance(source="join_guard", note="unprobed join_confidence=verified"))
    assert v.warrant == "declared"
    assert "no overlap recorded" in v.detail


# ── an ambiguity resolution's TIER is its warrant ────────────────────────────────

@pytest.mark.parametrize("tier,expected", [
    ("probe", "measured"),   # the warehouse was actually queried
    ("user", "human"),
    ("verdict", "human"),
])
def test_resolution_tier_decides_the_warrant(tier, expected):
    v = warrant_for(Provenance(source="ambiguity_ledger", note=f"resolution_source={tier}"))
    assert v.warrant == expected


def test_an_unrecorded_resolution_tier_is_not_a_probe():
    """The projection used to default a missing tier to `probe`, which P2 reads as a
    MEASUREMENT — publishing a probe nobody ran. Neither end may assume it."""
    for note in ("resolution_source=mystery", "resolution_source=", ""):
        v = warrant_for(Provenance(source="ambiguity_ledger", note=note))
        assert v.warrant == "inferred", f"{note!r} was reported as {v.warrant}"


def test_a_resolution_with_no_recorded_tier_projects_as_inferred():
    """End to end through the REAL projection — the defect lived in the default there."""
    res = SimpleNamespace(id="r9", subject="revenue", resolved_reading="net",
                          resolution_source="", evidence="")
    cg = project_graph(_ontology_with_a_join(overlap=None, confidence="exact"),
                       org_id="o", connection_id="c", resolutions=[res])
    node = next(n for n in cg.nodes.values() if n.provenance.source == "ambiguity_ledger")
    assert warrant_of_node(node).warrant == "inferred"


# ── the rest of the source table ─────────────────────────────────────────────────

@pytest.mark.parametrize("source,expected", [
    ("ontology.entity", "declared"),
    ("ontology.metric", "declared"),
    ("metrics_catalog", "declared"),
    ("ontology.domain", "inferred"),
    ("dossier", "derived"),
    ("exploration", "derived"),
    ("evidence_ledger", "derived"),
    ("briefing", "derived"),
])
def test_source_table(source, expected):
    assert warrant_for(Provenance(source=source)).warrant == expected


def test_written_glossary_definition_beats_an_auto_seeded_one():
    written = warrant_for(Provenance(source="glossary"), node_data={"auto_generated": False})
    seeded = warrant_for(Provenance(source="glossary"), node_data={"auto_generated": True})
    assert written.warrant == "declared"
    assert seeded.warrant == "inferred"


def test_defines_edge_is_a_name_coincidence_regardless_of_source():
    """`defines` is emitted on exact name equality — the construction rule IS the evidence."""
    v = warrant_for(Provenance(source="glossary", note="term name matches metric"),
                    edge_kind="defines")
    assert v.warrant == "inferred"


def test_unknown_source_degrades_to_the_weakest_class():
    v = warrant_for(SimpleNamespace(source="something_new", measured=None, note=""))
    assert v.warrant == "inferred"


def test_a_non_numeric_measured_is_not_a_measurement():
    """`measured` is the field that decides the strongest class, so a non-number in it
    must fall through to the SOURCE — not be rescued into 'measured' by an except-branch.
    The earlier version of this test asserted only membership in WARRANT_ORDER, which
    every branch satisfies, so it passed ON the defect."""
    for bad in ("n/a", "", [], {}, object()):
        v = warrant_for(SimpleNamespace(source="join_guard", measured=bad,
                                        note="unprobed join_confidence=inferred"))
        assert v.warrant == "inferred", f"{bad!r} was reported as {v.warrant}"


def test_a_boolean_measured_does_not_render_as_100_percent():
    """`bool` is an int subclass: float(True) == 1.0 would print '100% of key values
    overlap' for a flag."""
    v = warrant_for(SimpleNamespace(source="join_guard", measured=True,
                                    note="unprobed join_confidence=inferred"))
    assert v.warrant == "inferred"
    assert "100%" not in v.detail


def test_never_raises_on_a_malformed_provenance():
    v = warrant_for(SimpleNamespace(source=None, measured=None, note=None))
    assert v.warrant in WARRANT_ORDER


def test_note_field_reads_only_its_own_key():
    note = "value_overlap=0.983 join_confidence=verified"
    assert note_field(note, "join_confidence") == "verified"
    assert note_field(note, "value_overlap") == "0.983"
    assert note_field(note, "confidence") is None   # not a prefix match
    assert note_field("", "join_confidence") is None


# ── ROT GUARDS: the note fields must survive the real projection ─────────────────

def _ontology_with_a_join(*, overlap, confidence):
    ent = lambda eid: SimpleNamespace(  # noqa: E731
        display_name=eid, entity_type="fact", grain_verified=True,
        source_tables=[eid.lower()], identity_key="id", properties={}, implements=[],
    )
    return SimpleNamespace(
        schema_name="s", schema_fingerprint="fp",
        entities={"Order": ent("Order"), "Customer": ent("Customer")},
        metrics={},
        relationships={
            "r1": SimpleNamespace(from_entity="Order", to_entity="Customer",
                                  value_overlap=overlap, join_confidence=confidence,
                                  verb="belongs to"),
        },
    )


def test_rot_guard_join_note_still_carries_join_confidence():
    """If the projection stops writing `join_confidence=`, this fails LOUDLY — rather than
    every unprobed join silently degrading to the weakest class on a live graph."""
    cg = project_graph(_ontology_with_a_join(overlap=None, confidence="exact"),
                       org_id="o", connection_id="c")
    joins = [e for e in cg.edges.values() if e.kind == "joins_on"]
    assert joins, "projection emitted no join edge — the fixture no longer exercises the path"
    assert note_field(joins[0].provenance.note, "join_confidence") == "exact"
    assert warrant_of_edge(joins[0]).warrant == "declared"


def test_rot_guard_measured_join_projects_as_measured():
    cg = project_graph(_ontology_with_a_join(overlap=0.97, confidence="verified"),
                       org_id="o", connection_id="c")
    join = [e for e in cg.edges.values() if e.kind == "joins_on"][0]
    assert join.provenance.measured == pytest.approx(0.97)
    assert warrant_of_edge(join).warrant == "measured"


def test_rot_guard_resolution_note_still_carries_resolution_source():
    res = SimpleNamespace(id="r1", subject="revenue", resolved_reading="net of returns",
                          resolution_source="verdict", evidence="")
    cg = project_graph(_ontology_with_a_join(overlap=None, confidence="exact"),
                       org_id="o", connection_id="c", resolutions=[res])
    nodes = [n for n in cg.nodes.values() if n.provenance.source == "ambiguity_ledger"]
    assert nodes, "projection emitted no resolution node — fixture no longer exercises the path"
    assert note_field(nodes[0].provenance.note, "resolution_source") == "verdict"
    assert warrant_of_node(nodes[0]).warrant == "human"


def test_rot_guard_glossary_term_carries_the_auto_generated_marker():
    """The projection must keep passing the autodoc marker through, or every generated
    description would be reported as a written definition."""
    glossary = {
        "order": {"auto_generated": True,
                  "columns": {"total": {"description": "the order total"}}},
        "customer": {"columns": {"tier": {"description": "loyalty tier"}}},
    }
    cg = project_graph(_ontology_with_a_join(overlap=None, confidence="exact"),
                       org_id="o", connection_id="c", merged_glossary=glossary)
    terms = {n.data.get("table"): n for n in cg.nodes.values() if n.kind == "glossary_term"}
    assert set(terms) == {"order", "customer"}, "glossary projection changed shape"
    assert warrant_of_node(terms["order"]).warrant == "inferred"
    assert warrant_of_node(terms["customer"]).warrant == "declared"


# ── the audit scorecard ──────────────────────────────────────────────────────────

def _graph_with(edges):
    cg = ContextGraph(org_id="o", connection_id="c")
    for i, (kind, prov) in enumerate(edges):
        a, b = f"table:a{i}", f"table:b{i}"
        for nid in (a, b):
            cg.add_node(GraphNode(id=nid, kind="table", label=nid,
                                  provenance=Provenance(source="ontology.entity")))
        cg.add_edge(GraphEdge(id=f"e{i}", kind=kind, from_id=a, to_id=b, provenance=prov))
    return cg


def test_audit_counts_every_class_and_reports_the_grounded_share():
    cg = _graph_with([
        ("joins_on", Provenance(source="join_guard", measured=1.0,
                                note="value_overlap=1.000 join_confidence=verified")),
        ("joins_on", Provenance(source="join_guard", note="unprobed join_confidence=inferred")),
        ("derived_from", Provenance(source="ontology.metric", note="metric formula reads table")),
        ("resolves", Provenance(source="ambiguity_ledger", note="resolution_source=user")),
    ])
    out = audit(cg)
    assert out["edges"]["measured"] == 1
    assert out["edges"]["inferred"] == 1
    assert out["edges"]["declared"] == 1
    assert out["edges"]["human"] == 1
    assert out["totals"]["edges"] == 4
    assert out["edge_grounded_share"] == pytest.approx(0.5)
    assert out["edges_by_kind"]["joins_on"]["measured"] == 1
    # The HEADLINE is about joins only: 1 of 2 joins measured.
    assert out["totals"]["joins"] == 2
    assert out["joins_measured_share"] == pytest.approx(0.5)


def test_the_headline_is_not_dragged_down_by_provenance_links():
    """`grounded_in` edges can never be measured — there is no probe for "this finding
    came from this table" — and they are ~95% of a real graph. An all-edge share read 3%
    on a connection whose every join WAS measured: a proxy standing in for the number the
    reader wants, which is this codebase's most-repeated defect."""
    cg = _graph_with(
        [("joins_on", Provenance(source="join_guard", measured=1.0,
                                 note="value_overlap=1.000 join_confidence=verified"))]
        + [("grounded_in", Provenance(source="dossier")) for _ in range(50)])
    out = audit(cg)
    assert out["joins_measured_share"] == 1.0          # every join was probed
    assert out["edge_grounded_share"] < 0.05           # …and the all-edge number is noise
    assert out["totals"]["joins"] == 1


def test_audit_reports_every_class_even_at_zero():
    """A scorecard that omitted the empty classes would read as 'nothing weak here'."""
    out = audit(_graph_with([("joins_on", Provenance(source="join_guard", measured=1.0))]))
    # Pinned against the literal set, not against another field of the same response —
    # comparing `out["edges"]` to `out["order"]` would pass on any pair built from the
    # same constant.
    assert set(out["edges"]) == {"measured", "human", "declared", "derived", "inferred"}
    assert out["edges"]["inferred"] == 0
    assert out["edges"]["measured"] == 1


def test_audit_of_an_empty_graph_does_not_divide_by_zero():
    out = audit(ContextGraph(org_id="o", connection_id="c"))
    assert out["totals"] == {"nodes": 0, "edges": 0, "joins": 0}
    assert out["edge_grounded_share"] == 0.0
    assert out["joins_measured_share"] == 0.0
