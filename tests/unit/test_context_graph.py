"""Wave C1 — the connection knowledge graph projection + store.

Hermetic: the projection is pure (no DB, no LLM), so every test constructs a
synthetic OntologyGraph in memory. The store tests redirect the artifact root to a
tmp path. These encode the C1 decision gate: every edge carries provenance citing
measured evidence, accepted joins_on edges surface value_overlap, and findings
(the write-only half of the open loop) become nodes.
"""
from __future__ import annotations

import types

import pytest
from pydantic import ValidationError

from aughor.ontology.models import (
    OntologyEntity,
    OntologyGraph,
    OntologyMetric,
    OntologyRelationship,
)
from aughor.ontology import context_graph as cg_mod
from aughor.ontology.context_graph import (
    ContextGraph,
    GraphEdge,
    Provenance,
    ProvenanceSource,
    project_graph,
)


def _entity(eid: str, table: str, *, domain: str | None = None, cols=("id",)) -> OntologyEntity:
    return OntologyEntity(
        id=eid,
        display_name=eid,
        source_tables=[table],
        identity_key="id",
        grain_verified=True,
        domain=domain,
        properties={c: {"name": c} for c in cols},  # EntityProperty coerces from dict
    )


def _rel(from_e: str, to_e: str, *, overlap, confidence="inferred") -> OntologyRelationship:
    return OntologyRelationship(
        id=f"{from_e}_to_{to_e}",
        from_entity=from_e,
        to_entity=to_e,
        cardinality="N:1",
        join_sql=f"{from_e.lower()}.id = {to_e.lower()}.id",
        from_table=from_e.lower(),
        from_col="id",
        to_table=to_e.lower(),
        to_col="id",
        join_confidence=confidence,
        value_overlap=overlap,
    )


def _ontology() -> OntologyGraph:
    g = OntologyGraph(connection_id="c1", schema_name="main", schema_fingerprint="fp1")
    g.entities = {
        "Order": _entity("Order", "orders", domain="Commerce", cols=("id", "customer_id", "revenue")),
        "Customer": _entity("Customer", "customers", domain="Customer"),
    }
    g.relationships = {"r1": _rel("Order", "Customer", overlap=0.98, confidence="verified")}
    g.metrics = {
        "revenue": OntologyMetric(
            id="revenue", display_name="Revenue", entity="Order",
            formula_sql="SUM(revenue)", tables=["orders"], verified=True,
        )
    }
    return g


def _build(**kw) -> ContextGraph:
    return project_graph(_ontology(), org_id="org1", connection_id="c1",
                         schema_name="main", **kw)


# ── the type system ───────────────────────────────────────────────────────────

def test_provenance_is_required_on_every_edge():
    """J4 by construction: an edge without provenance is not constructible."""
    with pytest.raises(ValidationError):
        GraphEdge(id="e", kind="joins_on", from_id="a", to_id="b")  # no provenance


def test_no_self_reported_confidence_source_exists():
    """The banned provenance sources (self-reported model confidences) must not be
    part of the allowed set — the design guarantee, checked as a ratchet."""
    allowed = set(ProvenanceSource.__args__)  # type: ignore[attr-defined]
    assert "evidence_confidence" not in allowed
    assert "llm_inferred" not in allowed
    # the strongest measured source IS present
    assert "join_guard" in allowed


# ── the projection ────────────────────────────────────────────────────────────

def test_tables_metrics_and_domains_projected():
    g = _build()
    tables = {n.id for n in g.nodes_of("table")}
    assert tables == {"table:Order", "table:Customer"}
    assert {n.id for n in g.nodes_of("metric")} == {"metric:revenue"}
    assert {n.label for n in g.nodes_of("domain")} == {"Commerce", "Customer"}
    # the table node carries its columns + domain, not just a name
    order = g.nodes["table:Order"]
    assert order.data["domain"] == "Commerce"
    assert "revenue" in order.data["columns"]


def test_every_edge_carries_provenance_with_a_source():
    """The C1 gate: zero edges without provenance."""
    g = _build()
    assert g.edges  # non-empty
    for e in g.edges.values():
        assert isinstance(e.provenance, Provenance)
        assert e.provenance.source  # non-empty ProvenanceSource


def test_joins_on_surfaces_the_measured_overlap():
    """The J4 showcase: an accepted join edge carries the measured value_overlap as a
    number (not collapsed to a boolean), sourced from the join guard."""
    g = _build()
    joins = g.nodes_of  # noqa: F841 (readability)
    edge = next(e for e in g.edges.values() if e.kind == "joins_on")
    assert edge.from_id == "table:Order" and edge.to_id == "table:Customer"
    assert edge.provenance.source == "join_guard"
    assert edge.provenance.measured == pytest.approx(0.98)
    assert "value_overlap=0.980" in edge.provenance.note


def test_unprobed_join_is_honest_not_faked():
    """An unprobed relationship still projects (it is a real ontology edge) but says
    so — measured is None and the note reads 'unprobed', never a fabricated number."""
    g = OntologyGraph(connection_id="c1", schema_fingerprint="fp")
    g.entities = {"A": _entity("A", "a"), "B": _entity("B", "b")}
    g.relationships = {"r": _rel("A", "B", overlap=None)}
    out = project_graph(g, org_id="o", connection_id="c1")
    edge = next(e for e in out.edges.values() if e.kind == "joins_on")
    assert edge.provenance.measured is None
    assert "unprobed" in edge.provenance.note


def test_dangling_edge_is_never_emitted():
    """A relationship whose endpoint has no entity node must not produce a floating
    edge (the anti-hairball / integrity guarantee)."""
    g = OntologyGraph(connection_id="c1", schema_fingerprint="fp")
    g.entities = {"A": _entity("A", "a")}  # B is missing
    g.relationships = {"r": _rel("A", "B", overlap=0.9)}
    out = project_graph(g, org_id="o", connection_id="c1")
    assert not [e for e in out.edges.values() if e.kind == "joins_on"]


def test_derived_from_links_metric_to_its_tables():
    g = _build()
    edge = next(e for e in g.edges.values() if e.kind == "derived_from")
    assert edge.from_id == "metric:revenue"
    assert edge.to_id == "table:Order"  # revenue reads the orders table


def test_glossary_terms_are_scoped_to_the_connection():
    """The global-by-name store is read-time-scoped: a term on a table this
    connection does not expose is dropped; only described columns become terms."""
    merged = {
        "orders": {"columns": {
            "revenue": {"description": "gross booking value, pre-refund"},
            "id": {},  # no description → not a term
        }},
        "unrelated_table": {"columns": {"x": {"description": "some other connection"}}},
    }
    g = _build(merged_glossary=merged)
    terms = {n.label for n in g.nodes_of("glossary_term")}
    assert "revenue" in terms
    assert "id" not in terms
    assert "x" not in terms  # scoped out — different connection's table
    # defines edge: term 'revenue' → metric:revenue (exact name match)
    assert any(e.kind == "defines" and e.to_id == "metric:revenue"
               for e in g.edges.values())


def test_glossary_source_is_unwrapped_from_the_store_envelope(monkeypatch):
    """The projection takes ``{table: meta}``; the STORE returns the envelope
    ``{"tables": {table: meta}}``. Handing the envelope straight through made the
    projection loop once on the literal key ``"tables"``, fail the connection-scope
    check, and drop every term on every connection — silently, with `defines`
    unreachable. The tests missed it because they hand-built the unwrapped shape
    while production called the real loader.

    So this asserts the BOUNDARY against the producer's real shape: the fixture below
    is the envelope `load_merged_glossary` actually returns.
    """
    from aughor.ontology import context_graph_build as build_mod

    envelope = {"tables": {"orders": {"columns": {
        "revenue": {"description": "gross booking value, pre-refund"}}}}}
    monkeypatch.setattr("aughor.semantic.glossary.load_merged_glossary",
                        lambda *a, **k: envelope)

    unwrapped = build_mod._load_glossary()
    assert "tables" not in unwrapped, "envelope leaked into the projection's input"
    assert unwrapped == envelope["tables"]
    # and it survives the projection it feeds
    assert "revenue" in {n.label for n in _build(merged_glossary=unwrapped)
                         .nodes_of("glossary_term")}


def test_findings_become_nodes_with_grounded_in_edges():
    """The write-only half of the open loop, finally a node. Provenance is the
    derivation source — never the finding's self-reported confidence."""
    findings = [{
        "id": "f1",
        "text": "32% of orders never reach a terminal state",
        "sql": "SELECT ... FROM orders",
        "tables": ["orders"],
        "source": "dossier",
        "generated_at": "2026-07-25T00:00:00Z",
    }]
    g = _build(findings=findings)
    fnode = g.nodes["finding:f1"]
    assert fnode.kind == "finding"
    assert fnode.provenance.source == "dossier"
    assert fnode.provenance.measured is None  # confidence is NOT laundered into a measurement
    edge = next(e for e in g.edges.values() if e.kind == "grounded_in")
    assert edge.from_id == "finding:f1" and edge.to_id == "table:Order"


def test_resolutions_project_to_resolves_edges():
    res = types.SimpleNamespace(
        id="res1", subject="revenue", resolved_reading="gross, pre-refund",
        resolution_source="verdict", evidence="reviewer accepted",
    )
    g = _build(resolutions=[res])
    edge = next(e for e in g.edges.values() if e.kind == "resolves")
    assert edge.provenance.source == "ambiguity_ledger"
    assert "resolution_source=verdict" in edge.provenance.note


def test_counts_shape():
    g = _build()
    c = g.counts()
    assert c["table"] == 2 and c["metric"] == 1 and c["edges"] == len(g.edges)


# ── Wave L1: the live-path incremental write ──────────────────────────────────

_L1_FINDING = {"id": "rcpt1", "text": "Refund rate spiked 4.2pp in the EU region",
               "sql": "SELECT * FROM orders", "tables": ["orders"],
               "source": "evidence_ledger", "generated_at": ""}


@pytest.fixture()
def _graph_store(tmp_path, monkeypatch):
    """Redirect the committed-artifact root and seed one built graph for `c1`."""
    from aughor.ontology import context_graph_store as store
    monkeypatch.setattr(store, "_ROOT", tmp_path / "context_graph")
    store.save_graph(_build())
    return store


def test_note_finding_is_a_noop_when_the_flag_is_off(_graph_store, monkeypatch):
    """Byte-identical with `graph.build` off: nothing read, nothing written."""
    from aughor.ontology import context_graph_build as build_mod
    monkeypatch.setattr(build_mod, "flag_enabled", lambda name: False)

    before = _graph_store.graph_path("org1", "c1", "main").read_bytes()
    assert build_mod.note_finding("c1", _L1_FINDING, org_id="org1") is False
    assert _graph_store.graph_path("org1", "c1", "main").read_bytes() == before


def test_note_finding_lands_the_node_and_its_grounded_in_edge(_graph_store, monkeypatch):
    """The L1 gate, at the unit: an answer becomes a `finding` node + `grounded_in`
    edge on the COMMITTED artifact, with no full rebuild and no manual step."""
    from aughor.ontology import context_graph_build as build_mod
    monkeypatch.setattr(build_mod, "flag_enabled", lambda name: True)

    assert build_mod.note_finding("c1", _L1_FINDING, org_id="org1") is True

    g = _graph_store.load_graph("org1", "c1", "main")
    assert g.version == 2                      # supersede-not-delete
    node = g.nodes["finding:rcpt1"]
    assert node.kind == "finding"
    assert node.provenance.source == "evidence_ledger"
    assert any(e.kind == "grounded_in" and e.from_id == "finding:rcpt1"
               for e in g.edges.values())


def test_note_finding_matches_what_a_full_rebuild_would_project(_graph_store, monkeypatch):
    """The incremental path and the rebuild path must not drift into two shapes —
    which is why both go through `_project_findings` rather than each building a node.
    """
    from aughor.ontology import context_graph_build as build_mod
    monkeypatch.setattr(build_mod, "flag_enabled", lambda name: True)
    build_mod.note_finding("c1", _L1_FINDING, org_id="org1")
    incremental = _graph_store.load_graph("org1", "c1", "main").nodes["finding:rcpt1"]

    rebuilt = _build(findings=[_L1_FINDING]).nodes["finding:rcpt1"]
    assert incremental.model_dump() == rebuilt.model_dump()


def test_note_finding_declines_rather_than_guessing_the_schema(tmp_path, monkeypatch):
    """Two graphs and no schema named ⇒ decline. Writing the finding onto whichever
    schema sorted first would attach it to data it never read."""
    from aughor.ontology import context_graph_store as store
    from aughor.ontology import context_graph_build as build_mod
    monkeypatch.setattr(store, "_ROOT", tmp_path / "context_graph")
    monkeypatch.setattr(build_mod, "flag_enabled", lambda name: True)
    for schema in ("main", "other"):
        g = _build()
        g.schema_name = schema
        store.save_graph(g)

    assert build_mod.note_finding("c1", _L1_FINDING, org_id="org1") is False
    assert build_mod.note_finding("c1", _L1_FINDING, org_id="org1",
                                  schema_name="main") is True


def test_note_finding_on_an_unbuilt_connection_is_not_an_error(tmp_path, monkeypatch):
    """No graph yet ⇒ False, not a raise: the finding is still in the Ledger and the
    next full build projects it from `load_investigation_findings`."""
    from aughor.ontology import context_graph_store as store
    from aughor.ontology import context_graph_build as build_mod
    monkeypatch.setattr(store, "_ROOT", tmp_path / "context_graph")
    monkeypatch.setattr(build_mod, "flag_enabled", lambda name: True)
    assert build_mod.note_finding("never_built", _L1_FINDING, org_id="org1") is False


def test_answer_receipts_become_findings_with_evidence_ledger_provenance(monkeypatch):
    """Investigations were structurally invisible to the graph: `load_findings` reads
    the EXPLORER store, while an answer writes an `ada_report`/`chat_answer` receipt.
    This is the source that closes that gap."""
    from aughor.ontology import context_graph_build as build_mod

    class _FakeLedger:
        def artifacts_of_kind(self, kinds, *, conn_id=None, org_id=None, limit=200):
            assert set(kinds) == set(build_mod._RECEIPT_KINDS)
            return [
                {"id": "a1", "kind": "ada_report", "created_at": "2026-07-26",
                 "payload": {"headline": "GMV fell in EU", "sql": "SELECT 1",
                             "tables": ["orders"], "question": "why did GMV fall?"}},
                {"id": "a2", "kind": "chat_answer", "created_at": "2026-07-26",
                 "payload": {"question": "how many?", "tables": ["returns"]}},
            ]
    monkeypatch.setattr("aughor.kernel.ledger.Ledger.default",
                        staticmethod(lambda: _FakeLedger()))

    found = build_mod.load_investigation_findings("c1", "org1")
    # a2 concluded nothing (no headline) — a question is not a discovery
    assert [f["id"] for f in found] == ["a1"]
    assert found[0]["source"] == "evidence_ledger"
    assert found[0]["tables"] == ["orders"]


def test_receipt_truncation_is_counted_never_silent(monkeypatch):
    """A bounded projection must say how much it dropped (the no-silent-caps rule)."""
    from aughor.ontology import context_graph_build as build_mod
    monkeypatch.setattr(build_mod, "_MAX_RECEIPT_FINDINGS", 2)
    over = [{"id": f"a{i}", "kind": "ada_report", "created_at": "2026-07-26",
             "payload": {"headline": f"finding {i}", "tables": []}} for i in range(5)]

    class _FakeLedger:
        def artifacts_of_kind(self, kinds, *, conn_id=None, org_id=None, limit=200):
            return over[:limit]
    monkeypatch.setattr("aughor.kernel.ledger.Ledger.default",
                        staticmethod(lambda: _FakeLedger()))
    bumped: dict = {}
    monkeypatch.setattr("aughor.stats.bump",
                        lambda c, n=1: bumped.__setitem__(c, bumped.get(c, 0) + n))

    assert len(build_mod.load_investigation_findings("c1", "org1")) == 2
    assert bumped["context_graph.receipts_truncated"] == 1  # asked for cap+1, saw 3


# ── Wave L1: briefs ───────────────────────────────────────────────────────────

_L1_BRIEF = {"id": "c1", "text": "Refunds are the quarter's story.",
             "theme": "Refund Pressure On Margin",
             "citations": ["rcpt1", "not_in_this_graph"], "generated_at": ""}


def test_briefs_become_nodes_with_derived_from_edges_to_cited_findings():
    """`brief` was a declared node kind with NO projector — the type existed, the
    header documented it, and nothing ever emitted one."""
    g = _build(findings=[_L1_FINDING], briefs=[_L1_BRIEF])

    node = g.nodes["brief:c1"]
    assert node.kind == "brief"
    assert node.label == "Refund Pressure On Margin"
    assert node.provenance.source == "briefing"

    cites = [e for e in g.edges.values()
             if e.kind == "derived_from" and e.from_id == "brief:c1"]
    assert [e.to_id for e in cites] == ["finding:rcpt1"]


def test_a_citation_to_an_absent_finding_is_not_a_dangling_edge():
    """A brief citing something this graph doesn't hold drops the edge, never emits
    one pointing at a node that isn't there."""
    g = _build(briefs=[_L1_BRIEF])          # no findings projected at all
    assert "brief:c1" in g.nodes
    assert not [e for e in g.edges.values() if e.kind == "derived_from"
                and e.from_id == "brief:c1"]


def test_regenerating_a_brief_supersedes_rather_than_accumulates():
    """One node per brief SCOPE. A refresh must not leave a node per generation."""
    g = _build(findings=[_L1_FINDING], briefs=[_L1_BRIEF])
    from aughor.ontology.context_graph import add_briefs
    add_briefs(g, [{**_L1_BRIEF, "text": "Rewritten.", "theme": "New Theme"}])

    assert len([n for n in g.nodes.values() if n.kind == "brief"]) == 1
    assert g.nodes["brief:c1"].summary == "Rewritten."


def test_note_brief_lands_on_the_committed_artifact(_graph_store, monkeypatch):
    from aughor.ontology import context_graph_build as build_mod
    monkeypatch.setattr(build_mod, "flag_enabled", lambda name: True)
    build_mod.note_finding("c1", _L1_FINDING, org_id="org1")

    assert build_mod.note_brief("c1", _L1_BRIEF, org_id="org1") is True
    g = _graph_store.load_graph("org1", "c1", "main")
    assert g.nodes["brief:c1"].kind == "brief"
    assert any(e.kind == "derived_from" and e.to_id == "finding:rcpt1"
               for e in g.edges.values())


def test_note_brief_is_a_noop_when_the_flag_is_off(_graph_store, monkeypatch):
    from aughor.ontology import context_graph_build as build_mod
    monkeypatch.setattr(build_mod, "flag_enabled", lambda name: False)
    before = _graph_store.graph_path("org1", "c1", "main").read_bytes()
    assert build_mod.note_brief("c1", _L1_BRIEF, org_id="org1") is False
    assert _graph_store.graph_path("org1", "c1", "main").read_bytes() == before


def test_only_the_connection_scoped_brief_is_projected(monkeypatch):
    """A canvas brief is keyed `canvas:<id>`, which does not name a connection —
    attributing it would ground a brief in data it may never have read."""
    from aughor.ontology import context_graph_build as build_mod
    seen: list[str] = []

    def _peek(scope_key):
        seen.append(scope_key)
        return {"narrative": "n", "headline_theme": "t",
                "citations": [{"insight_id": "rcpt1"}]}
    monkeypatch.setattr("aughor.knowledge.briefing.peek_briefing", _peek)

    out = build_mod.load_briefs("c1")
    assert seen == ["c1"]                      # asked only for the connection scope
    assert out[0]["id"] == "c1" and out[0]["citations"] == ["rcpt1"]


# ── Wave L1: the exploration-completion trigger ───────────────────────────────

def test_exploration_completion_forces_a_rebuild(monkeypatch):
    """The graph had no structural trigger: only the C4 surface routes ever built it.
    An exploration is the one event that moves both halves at once (new findings AND
    possibly the schema), so completion rebuilds — and it must FORCE, because the
    change classifier compares schema fingerprints and cannot see a new finding."""
    from aughor.explorer.agent import SchemaExplorer
    calls: list[dict] = []
    monkeypatch.setattr(
        "aughor.ontology.graph_freshness.refresh_context_graph",
        lambda conn, *a, **kw: calls.append({"conn": conn, **kw}) or None)

    ex = object.__new__(SchemaExplorer)
    ex.connection_id = "c1"
    ex._rebuild_context_graph()

    assert calls == [{"conn": "c1", "force": True}]


def test_a_failed_rebuild_never_fails_the_exploration(monkeypatch):
    """An exploration that finished must not be reported as failed because a
    projection didn't land."""
    from aughor.explorer.agent import SchemaExplorer
    monkeypatch.setattr(
        "aughor.ontology.graph_freshness.refresh_context_graph",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("disk full")))

    ex = object.__new__(SchemaExplorer)
    ex.connection_id = "c1"
    ex._rebuild_context_graph()  # must not raise


# ── the committed-artifact store ──────────────────────────────────────────────

def test_store_roundtrip_and_version_bump(tmp_path, monkeypatch):
    from aughor.ontology import context_graph_store as store
    monkeypatch.setattr(store, "_ROOT", tmp_path / "context_graph")

    g = _build()
    path = store.save_graph(g)
    assert path.exists()
    assert g.version == 1

    loaded = store.load_graph("org1", "c1", "main")
    assert loaded is not None
    assert set(loaded.nodes) == set(g.nodes)
    assert set(loaded.edges) == set(g.edges)

    # a rebuild supersedes: version bumps, one file (git holds history)
    again = store.save_graph(_build())
    assert store.load_graph("org1", "c1", "main").version == 2
    assert again == path  # same committed path


def test_store_missing_returns_none(tmp_path, monkeypatch):
    from aughor.ontology import context_graph_store as store
    monkeypatch.setattr(store, "_ROOT", tmp_path / "context_graph")
    assert store.load_graph("org1", "nope", "main") is None


# ── the flag gate (byte-identical when off) ───────────────────────────────────

def test_build_returns_none_when_flag_off():
    """Default off ⇒ the projection is never invoked and nothing is written."""
    from aughor.ontology.context_graph_build import build_context_graph
    # graph.build is default-off; no override set here.
    assert build_context_graph("any-conn") is None


def test_module_has_no_llm_or_sql_imports():
    """The projection must be a real program calling neither — a ratchet against the
    pipeline-as-prompt anti-pattern creeping in."""
    import inspect
    src = inspect.getsource(cg_mod)
    assert "provider" not in src and "complete(" not in src
    assert "execute(" not in src and "db.execute" not in src
