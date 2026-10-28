"""Arc FA, FA-1 — the ontology's declarations can be searched (ROADMAP §3.60).

Measured 2026-10-26: the connection graph's node kinds held no declaration — a published process, rule or segment was
found by no search, the read-back never named one, and an outside agent asking the knowledge door could not reach
them. Now each published declaration is a ``declaration`` node with a ``defines`` edge to the table node of its
entity: found by its own words, read back beside its entity, withheld wherever its entity's tables are, read from the
release consumers read (never a draft), and rebuilt the moment a person publishes.

Hermetic: the overrides tree, its draft layer and the ledger are per test; the ontology is the samples shop's measured
graph, overlaid with what each test declares.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from aughor.ontology import overrides as OV
from aughor.ontology import release as R
from aughor.ontology.models import OntologyGraph
from aughor.ontology.overrides import OntologyOverride, save_override, viewing

CONN, SCHEMA = "declarations-t", "ecommerce"
GRAPH = Path(__file__).resolve().parents[2] / "evals" / "ablation_samples_ecommerce_ontology_measured.json"
BASE = OntologyGraph.model_validate(json.loads(GRAPH.read_text()))


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from aughor.kernel.ledger import Ledger
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")
    monkeypatch.setattr(OV, "_SEED_ROOT", tmp_path / "seed")
    monkeypatch.setattr(OV, "_DRAFT_ROOT", tmp_path / "ontology_overrides_draft")
    ledger = Ledger(str(tmp_path / "system.db"))
    monkeypatch.setattr(Ledger, "default", classmethod(lambda cls: ledger))
    monkeypatch.setattr("aughor.automations.store.list_automations", lambda *a, **k: [])
    monkeypatch.setattr("aughor.explorer.store.get_findings", lambda key: [])
    from aughor.ontology import context_graph_store as store
    monkeypatch.setattr(store, "_ROOT", tmp_path / "context_graph")

    def served(conn, schema=None):
        graph = copy.deepcopy(BASE)
        graph.connection_id = CONN
        OV.apply_overrides(graph, CONN, SCHEMA)
        return graph
    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology", served)


def _in_force(ov: OntologyOverride) -> None:
    """A published declaration — the release's own door into the tree."""
    OV.publish_override(CONN, SCHEMA, ov)


def _rule(values=("DE", "AT", "CH"), **fields) -> OntologyOverride:
    return OntologyOverride(target_kind="rule", target_id="dach", edited_by="person:ana", fields={
        "declared": True, "display_name": "DACH", "description": "the German-speaking markets", "entity": "Customer",
        "kind": "value_set", "property": "country", "values": list(values), **fields},
        binding={"rule": {"bound": True}})


def _declare_the_shop() -> None:
    _in_force(_rule())
    _in_force(OntologyOverride(
        target_kind="object_set", target_id="Order::active_orders", edited_by="person:ana",
        fields={"description": "orders still on their way to the customer"}))
    _in_force(OntologyOverride(
        target_kind="link", target_id="Customer_RELATES_TO_Order", fields={"name": "customer_places_order"}))
    _in_force(OntologyOverride(target_kind="action", target_id="flag_order", fields={
        "display_name": "Flag order for review", "kind": "annotate", "risk": "low", "object_type": "order",
        "description": "mark an order a person should look at"}))


def _build():
    from aughor.ontology.context_graph_build import build_context_graph
    return build_context_graph(CONN, SCHEMA, org_id="default", persist=False)


def _declarations(cg) -> dict:
    return {n.id: n for n in cg.nodes.values() if n.kind == "declaration"}


def _without_dates(items: dict) -> dict:
    """Nodes or edges as they read, less the build's own clock (a fact the sources leave undated takes it)."""
    return {k: {**v.model_dump(exclude={"provenance"}), "provenance": v.provenance.model_dump(exclude={"observed_at"})}
            for k, v in items.items()}


def test_the_declarations_add_their_own_nodes_and_edges_and_change_nothing_else(monkeypatch):
    from aughor.ontology import context_graph_build as B
    _declare_the_shop()
    on = _build()
    monkeypatch.setattr(B, "load_declarations", lambda *a, **k: [])
    without = _build()
    kept = {k: n for k, n in on.nodes.items() if n.kind != "declaration"}
    edges = {k: e for k, e in on.edges.items() if not e.from_id.startswith("declaration:")}
    assert len(kept) < len(on.nodes) and len(edges) < len(on.edges)
    assert _without_dates(kept) == _without_dates(without.nodes)
    assert _without_dates(edges) == _without_dates(without.edges)


# ── each published declaration is a node about its entity ─────────────────────────────────

def test_each_published_declaration_is_a_node_with_an_edge_to_its_entity(monkeypatch):
    from aughor.ontology.graph_warrant import warrant_of_edge, warrant_of_node
    _declare_the_shop()
    cg = _build()
    found = _declarations(cg)
    assert set(found) == {"declaration:rule:dach", "declaration:segment:Order::active_orders",
                          "declaration:link:Customer_RELATES_TO_Order", "declaration:action:flag_order"}
    rule = found["declaration:rule:dach"]
    assert (rule.label, rule.summary, rule.data["decl_kind"], rule.data["entities"]) == (
        "DACH", "the German-speaking markets", "rule", ["Customer"])
    assert rule.data["source_tables"] == ["customers"] and rule.data["detail"] == "country in DE, AT, CH"
    assert rule.provenance.source == "ontology.declaration" and rule.provenance.author == "person:ana"
    assert rule.provenance.observed_basis == "source" and rule.provenance.observed_at
    edge = cg.edges["declaration:rule:dach--defines-->table:Customer"]
    assert warrant_of_edge(edge).warrant == "human" and "declared by a person" in warrant_of_node(rule).detail
    link = found["declaration:link:Customer_RELATES_TO_Order"]
    assert link.label == "customer_places_order" and link.data["entities"] == ["Customer", "Order"]
    assert {e.to_id for e in cg.edges.values() if e.from_id == link.id} == {"table:Customer", "table:Order"}
    assert found["declaration:action:flag_order"].data["entities"] == ["Order"]
    assert cg.counts()["declaration"] == 4


def test_a_models_unconfirmed_proposal_is_not_a_declaration(monkeypatch):
    _in_force(_rule(origin="model"))
    assert not _declarations(_build())


def test_the_graph_search_finds_a_declaration_by_its_own_words(monkeypatch):
    from aughor.ontology import context_graph_search as S
    monkeypatch.setattr(S, "_vector_search", lambda *a, **k: [])
    _declare_the_shop()
    cg = _build()
    hits = [n.id for n, _ in S.search_graph(cg, "German-speaking markets DACH", top_k=3)]
    assert hits[0] == "declaration:rule:dach"
    on_the_way = [n.id for n, _ in S.search_graph(cg, "orders on their way to the customer", top_k=5)]
    assert "declaration:segment:Order::active_orders" in on_the_way


# ── never a draft; a publish rebuilds the graph ───────────────────────────────────────────────

def test_a_change_waiting_in_the_draft_is_not_read_even_by_a_door_that_reads_the_draft(monkeypatch):
    _in_force(_rule(values=("DE", "AT")))                                    # in force before the first change
    save_override(CONN, SCHEMA, _rule(values=("DE", "AT", "CH"), display_name="DACH+"))   # waits in the draft
    with viewing("draft"):                                                   # a POST to /ontology reads the draft
        rule = _declarations(_build())["declaration:rule:dach"]
    assert (rule.label, rule.data["detail"]) == ("DACH", "country in DE, AT")
    assert "release=declarations-t/ecommerce@1" in rule.provenance.note


def test_publishing_rebuilds_the_graph_from_the_release_it_made(monkeypatch):
    _in_force(_rule(values=("DE", "AT")))
    save_override(CONN, SCHEMA, _rule(values=("DE", "AT", "CH")))
    calls: list = []

    def refresh(conn, schema=None, **kw):
        from aughor.ontology.graph_freshness import RefreshResult
        from aughor.kernel.freshness import FreshnessVerdict
        calls.append((conn, schema, kw.get("force"), OV.draft_view()))
        return RefreshResult(verdict=FreshnessVerdict("fresh", "full"), rebuilt=True, indexed=7)
    monkeypatch.setattr("aughor.ontology.graph_freshness.refresh_context_graph", refresh)
    with viewing("draft"):                                                   # the publish door reads the draft
        made = R.publish(CONN, SCHEMA, by="person:ana")
    assert made["graph"] == {"rebuilt": True, "indexed": 7}
    assert calls == [(CONN, SCHEMA, True, False)]                           # built as the published ontology
    rule = _declarations(_build())["declaration:rule:dach"]
    assert rule.data["detail"] == "country in DE, AT, CH" and "release=declarations-t/ecommerce@2" in rule.provenance.note


def test_a_graph_that_could_not_rebuild_says_why_and_the_publish_stands(monkeypatch):
    _in_force(_rule(values=("DE", "AT")))
    save_override(CONN, SCHEMA, _rule(values=("DE",)))
    monkeypatch.setattr("aughor.ontology.graph_freshness.refresh_context_graph", lambda *a, **k: None)
    made = R.publish(CONN, SCHEMA, by="person:ana")
    assert made["number"] == 2 and made["graph"]["rebuilt"] is False and made["graph"]["why"]


# ── withheld with its entity's tables, at every door ──────────────────────────────────────────

def _block(monkeypatch, table: str) -> None:
    from aughor.govern import tags as T
    from aughor.govern.tags import ClearanceDecision, Requirement
    req = Requirement(key="tier", value="restricted", clearance="clearance.restricted")
    monkeypatch.setattr(T, "check", lambda s, held, bypass=False: (
        ClearanceDecision(securable=s, allowed=False, requirements=[req], missing=[req]) if s.endswith(f".{table}")
        else ClearanceDecision(securable=s, allowed=True)))


def test_a_declaration_over_a_withheld_table_is_withheld_at_the_knowledge_door_and_counted(monkeypatch):
    from aughor.mcp import knowledge_tools as KT
    _declare_the_shop()
    cg = _build()
    _block(monkeypatch, "customers")
    monkeypatch.setattr(KT, "_load_graph", lambda *a, **k: cg)
    monkeypatch.setattr("aughor.ontology.context_graph_search.search_graph",
                        lambda g, q, top_k=10: [(g.nodes[i], 1.0) for i in (
                            "declaration:rule:dach", "declaration:link:Customer_RELATES_TO_Order",
                            "declaration:segment:Order::active_orders")])
    out = KT.search_graph(CONN, "markets")
    assert [n["id"] for n in out["nodes"]] == ["declaration:segment:Order::active_orders"]
    assert "[2 items withheld by data governance" in out["notice"]


def test_the_read_back_names_the_declarations_and_withholds_one_over_a_withheld_table(monkeypatch):
    from aughor.ontology import context_graph_search as S
    from aughor.ontology import context_graph_store as store
    from aughor.ontology.context_graph_readback import build_graph_prior
    monkeypatch.setattr(S, "_vector_search", lambda *a, **k: [])
    _declare_the_shop()
    store.save_graph(_build())
    prior = build_graph_prior("which customers are in DACH and which orders are active", CONN, org_id="default")
    assert "Declared on these entities" in prior.section
    assert 'rule "DACH" on Customer — the German-speaking markets  [declaration:rule:dach]' in prior.section
    assert "declaration:rule:dach" in prior.cited_node_ids
    _block(monkeypatch, "customers")
    held = build_graph_prior("which customers are in DACH and which orders are active", CONN, org_id="default")
    assert "DACH" not in held.section and "withheld by data governance" in held.section


# ── the pack an agent reads offline ───────────────────────────────────────────────────────────

def test_the_exported_skill_names_the_declaration_kind_only_when_the_graph_holds_one():
    from aughor.ontology import context_graph_export as X
    plain = X._skill_answer_from_graph("fresh", "")
    assert plain == X._skill_answer_from_graph_text("fresh", "") and "`declaration`" not in plain
    told = X._skill_answer_from_graph("fresh", "", declarations=True)
    assert "| `declaration` | a published segment" in told and "(from a `declaration`)" in told
