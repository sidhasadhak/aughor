"""Arc NV-4 — a bound candidate becomes a proposal in the ONE inbox; accepting declares it through the ontology's own
doors, rejecting keeps it.

Three seams: `proposal_detail` resolves what an accept would declare against the served graph, or says why it cannot
(a join whose table backs no entity, a formula over two entities); `stage_candidates` stages idempotently by the
candidate's own text and reports what it could not stage; `_accept_ontology_candidate` declares a link through the
link door's body, a measure as a computed property, a filter as a segment — and a door's refusal is the outcome.
"""
from __future__ import annotations

import pytest

from aughor.actions import inbox
from aughor.ontology.candidates import Candidate, proposal_detail
from aughor.ontology.models import EntityProperty, OntologyEntity, OntologyGraph

T2E = {"orders": "Order", "customers": "Customer", "order_items": "OrderItem"}


def _c(kind, proposal, subject="orders", evidence="computed as `gmv` over orders in 12 of 400 runs in the query history"):
    return Candidate(connection_id="c1", kind=kind, subject=subject, proposal=proposal, origin="query_log",
                     source_rank="mined", evidence=evidence, bound=True)


# ── what an accept would declare ──────────────────────────────────────────────────────────

def test_a_join_resolves_to_a_link_spec_for_the_link_door():
    d, why = proposal_detail(_c("join", "customers.id = orders.customer_id", subject="customers"), T2E)
    assert why == "" and d == {"declares": "link", "from_entity": "Customer", "to_entity": "Order", "from_column": "id",
                               "to_column": "customer_id", "name": "customer_to_order_from_history"}


def test_a_join_on_a_table_the_graph_does_not_back_is_not_staged_and_says_why():
    d, why = proposal_detail(_c("join", "orders.region_code = regions.code"), T2E)
    assert d is None and why == "no entity backs regions in the served graph"


def test_a_measure_over_one_entity_is_a_computed_property():
    d, why = proposal_detail(_c("measure", "SUM(gmv_eur)", subject="orders"), T2E)
    assert why == "" and d == {"declares": "computed_property", "entity_id": "Order", "prop_id": "gmv", "label": "gmv",
                               "formula_sql": "SUM(gmv_eur)"}


def test_a_measure_over_two_tables_is_declared_by_hand():
    d, why = proposal_detail(_c("measure", "SUM(order_items.quantity * orders.fx)", subject="order_items, orders"), T2E)
    assert d is None and "several tables" in why


def test_a_filter_is_a_segment_on_its_entity():
    d, why = proposal_detail(_c("filter", "status IN ('shipped', 'delivered')", subject="orders.status"), T2E)
    assert why == "" and d["declares"] == "segment" and d["entity_id"] == "Order"
    assert d["segment_id"] == "status_from_history" and d["filter_sql"] == "status IN ('shipped', 'delivered')"


# ── staging ───────────────────────────────────────────────────────────────────────────────

def _graph():
    return OntologyGraph(connection_id="c1", schema_name="main", schema_fingerprint="fp",
                         entities={e: OntologyEntity(id=e, display_name=e, source_tables=[t], identity_key="id",
                                                     grain_verified=True, properties={"id": EntityProperty(name="id")})
                                   for t, e in T2E.items()},
                         table_to_entity=dict(T2E))


def test_staging_is_idempotent_and_says_what_it_could_not_stage():
    from aughor.routers.ontology import stage_candidates
    cands = [_c("measure", "SUM(gmv_eur)"), _c("join", "orders.region_code = regions.code"),
             _c("filter", "status IN ('shipped')", subject="orders.status")]
    first = stage_candidates(cands, _graph(), "c-stage", "main")
    # Arc NV-7: a formula is never a card here — it is proposed in the Semantic Layer's catalogue (one door per kind)
    assert [p["declares"] for p in first["proposals"]] == ["segment"]
    assert first["already_staged"] == 0 and [u["kind"] for u in first["unstageable"]] == ["measure", "join"]
    assert first["unstageable"][0]["why"].startswith("a formula is proposed and adopted in the Semantic Layer")
    assert first["unstageable"][1]["why"] == "no entity backs regions in the served graph"
    again = stage_candidates(cands, _graph(), "c-stage", "main")
    assert again["already_staged"] == 1 and [p["id"] for p in again["proposals"]] == [p["id"] for p in first["proposals"]]
    row = inbox.get_proposal(first["proposals"][0]["id"])
    assert row.kind == "ontology_candidate" and row.proposer == "query_history" and row.params["proposal"] == "status IN ('shipped')"
    assert row.detail["declares"] == "segment" and row.action_id == "ontology.filter"


def test_a_rejected_candidate_is_kept_and_never_restaged():
    from aughor.routers.ontology import stage_candidates
    seg = _c("filter", "status IN ('returned')", subject="orders.status")
    out = stage_candidates([seg], _graph(), "c-reject", "main")
    pid = out["proposals"][0]["id"]
    assert inbox.reject_proposal(pid, actor="ana")
    row = inbox.get_proposal(pid)
    assert row.status == "rejected" and row.resolved_by == "ana"
    again = stage_candidates([seg], _graph(), "c-reject", "main")
    assert again["proposals"][0]["id"] == pid and again["proposals"][0]["status"] == "rejected"


# ── accepting declares through the doors ──────────────────────────────────────────────────

def _staged(detail, kind="measure", proposal="SUM(gmv_eur)", conn="c-accept"):
    return inbox.stage_proposal(inbox.StagedProposal(
        kind="ontology_candidate", connection_id=conn, schema_name="main", action_id=f"ontology.{kind}",
        params=_c(kind, proposal).to_dict(), detail=detail, proposer="query_history", source="candidates:query_history"))


def test_accepting_a_join_declares_the_link_through_the_link_door_as_the_persons_declaration(monkeypatch):
    import aughor.routers.ontology as RO
    seen = {}
    def fake_declare(spec, connection_id, schema_name):
        seen.update(spec=spec, connection_id=connection_id, schema_name=schema_name)
        return {"relationship": "Customer_to_Order", "link": {}}
    monkeypatch.setattr(RO, "declare_link_core", fake_declare)
    p = _staged({"declares": "link", "from_entity": "Customer", "to_entity": "Order", "from_column": "id",
                 "to_column": "customer_id", "name": "customer_to_order_from_history"}, kind="join",
                proposal="customers.id = orders.customer_id")
    result, _ = inbox.accept_proposal(p.id, actor="ana")
    assert result.ok and result.status == "executed"
    assert seen["spec"]["origin"] == "human" and seen["spec"]["name"] == "customer_to_order_from_history"
    assert seen["spec"]["provenance"].startswith("mined from the warehouse's query history")
    assert seen["connection_id"] == "c-accept" and seen["schema_name"] == "main"
    row = inbox.get_proposal(p.id)
    assert row.status == "executed" and row.outcome["relationship"] == "Customer_to_Order" and "as ana's declaration" in result.message


def test_accepting_a_measure_writes_a_computed_property_override_that_is_bound_first(monkeypatch):
    import aughor.routers.ontology as RO
    seen = {}
    def fake_bind(connection_id, schema, ov):
        seen.update(connection_id=connection_id, schema=schema, kind=ov.target_kind, target=ov.target_id, fields=dict(ov.fields))
        return ov, None
    monkeypatch.setattr(RO, "bind_and_persist_override", fake_bind)
    monkeypatch.setattr(RO, "served_scope", lambda cid, s: "main")
    p = _staged({"declares": "computed_property", "entity_id": "Order", "prop_id": "gmv", "label": "gmv",
                 "formula_sql": "SUM(gmv_eur)"})
    result, _ = inbox.accept_proposal(p.id, actor="ana")
    assert result.ok and seen == {"connection_id": "c-accept", "schema": "main", "kind": "computed_property",
                                  "target": "Order::gmv", "fields": {"label": "gmv", "formula_sql": "SUM(gmv_eur)"}}


def test_accepting_a_filter_writes_a_segment_override(monkeypatch):
    import aughor.routers.ontology as RO
    seen = {}
    monkeypatch.setattr(RO, "bind_and_persist_override", lambda cid, s, ov: (seen.update(kind=ov.target_kind, target=ov.target_id, fields=dict(ov.fields)), (ov, None))[1])
    monkeypatch.setattr(RO, "served_scope", lambda cid, s: "main")
    p = _staged({"declares": "segment", "entity_id": "Order", "segment_id": "status_from_history",
                 "display_name": "status as queried", "filter_sql": "status IN ('shipped')", "description": "d"},
                kind="filter", proposal="status IN ('shipped')")
    result, _ = inbox.accept_proposal(p.id, actor="ana")
    assert result.ok and seen["kind"] == "object_set" and seen["target"] == "Order::status_from_history"
    assert seen["fields"]["filter_sql"] == "status IN ('shipped')"


def test_the_doors_refusal_is_the_outcome_verbatim(monkeypatch):
    import aughor.routers.ontology as RO
    from fastapi import HTTPException
    def refuse(spec, connection_id, schema_name):
        raise HTTPException(status_code=400, detail="link 'x' did not bind: 0 of 100 keys found")
    monkeypatch.setattr(RO, "declare_link_core", refuse)
    p = _staged({"declares": "link", "from_entity": "Customer", "to_entity": "Order", "from_column": "id",
                 "to_column": "customer_id", "name": "x"}, kind="join", proposal="customers.id = orders.customer_id")
    result, _ = inbox.accept_proposal(p.id, actor="ana")
    assert not result.ok and "the ontology door refused: link 'x' did not bind" in result.message
    assert inbox.get_proposal(p.id).status == "failed"


def test_a_second_accept_declares_nothing_twice(monkeypatch):
    import aughor.routers.ontology as RO
    calls = []
    monkeypatch.setattr(RO, "declare_link_core", lambda spec, c, s: (calls.append(1), {"relationship": "r"})[1])
    p = _staged({"declares": "link", "from_entity": "Customer", "to_entity": "Order", "from_column": "id",
                 "to_column": "customer_id", "name": "n"}, kind="join", proposal="customers.id = orders.customer_id")
    inbox.accept_proposal(p.id, actor="ana")
    inbox.accept_proposal(p.id, actor="bo")
    assert calls == [1]


def test_the_public_door_names_are_bound():
    import aughor.routers.ontology as RO
    assert callable(RO.declare_link_core) and callable(RO.bind_and_persist_override) and callable(RO.served_scope)
    assert RO.declare_link_core is RO._declare_link_core


def test_the_mining_door_stages_when_asked(monkeypatch):
    from aughor.db.query_history import HistoryRow, QueryHistory
    from aughor.orgsettings import allows as A
    from aughor.routers import ontology as R
    monkeypatch.setattr(A, "allows", lambda s: True)
    monkeypatch.setattr(R, "_served_scope", lambda cid, s: "main")
    monkeypatch.setattr(R, "_get_ontology_graph", lambda cid, s=None: _graph())
    class Conn:
        dialect = "duckdb"
        def query_history(self, *, hours, limit):
            return QueryHistory(engine="duckdb", supported=True, source="t", rows=[
                HistoryRow("t", "SELECT SUM(gmv_eur) AS gmv FROM orders"), HistoryRow("t", "SELECT SUM(gmv_eur) AS gmv FROM orders")])
        def dry_run(self, sql):
            return True, ""
        def close(self):
            pass
    import aughor.db.connection as C
    monkeypatch.setattr(C, "open_connection_for_with_schema", lambda cid, s=None: Conn())
    out = R.mine_ontology_candidates(R._MineCandidatesRequest(stage=True), connection_id="c-door", schema_name="main")
    assert len(out["offered"]) == 1 and out["staged"]["proposals"] == []       # Arc NV-7: a formula is not a card here
    assert out["staged"]["unstageable"][0]["why"].startswith("a formula is proposed and adopted in the Semantic Layer")
    plain = R.mine_ontology_candidates(None, connection_id="c-door", schema_name="main")
    assert "staged" not in plain


@pytest.fixture(autouse=True)
def _no_trace(monkeypatch):
    monkeypatch.setattr("aughor.telemetry.current_trace_id", lambda: "", raising=False)
