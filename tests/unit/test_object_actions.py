"""ON-4 — declared actions on objects.

An object parameter names ONE object by type and key and is read live; a submission criterion may read
that object's properties; an accepted annotate writes the property the author declared onto the object,
stamped with who accepted it; and the next object query and object page merge it at read time with its
provenance — while the source rows stay exactly as they were. Declared the way a human declares one:
through the overrides tree.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import duckdb
import pytest

from aughor.actions import overlay as OVL
from aughor.actions.executor import (
    CriterionError,
    ParamError,
    coerce_params,
    default_dispatch,
    default_object_resolver,
    evaluate_predicate,
    resolve_objects,
)
from aughor.actions.inbox import StagedProposal, accept_proposal, stage_proposal
from aughor.actions.propose import evaluate_proposal, propose_actions
from aughor.db.connection import open_connection
from aughor.demo.setup import _seed_ecommerce
from aughor.ontology import overrides as OV
from aughor.ontology.models import OntologyGraph
from aughor.org.context import current_org_id
from aughor.semantic.object_context import object_context
from aughor.semantic.object_instances import get_object
from aughor.semantic.object_query import ObjectQueryRefused, compile_object_query

GRAPH = Path(__file__).resolve().parents[2] / "evals" / "ablation_samples_ecommerce_ontology_measured.json"
CONN = "object-actions-t"
ORDER = "O000123"
FLAG = {
    "display_name": "Flag order for review", "kind": "annotate", "risk": "low", "object_type": "order",
    "params": [{"name": "order", "kind": "object", "object_type": "order"},
               {"name": "reason", "data_type": "VARCHAR"}],
    "submission_criteria": [{"expr": "order.status != 'refunded'",
                             "message": "A refunded order is closed — there is nothing left to review."}],
    "edits": [{"object": "order", "property": "review_flag", "value": "true", "note": "{reason}"}],
}


class _Borrowed:
    """The module's database, lent to a resolver that closes what it opens."""

    def __init__(self, db):
        self._db = db

    def __getattr__(self, name):
        return getattr(self._db, name)

    def close(self):
        pass


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("samples") / "samples.duckdb"
    con = duckdb.connect(str(path))
    _seed_ecommerce(con)
    con.close()
    conn = open_connection("duckdb", str(path), schema_name="ecommerce", connection_id=CONN)
    yield conn
    conn.close()


def _declare(graph, action_id: str, fields: dict) -> None:
    OV.save_override(CONN, "ecommerce", OV.OntologyOverride(target_kind="action", target_id=action_id, fields=fields))
    OV.apply_overrides(graph, CONN, "ecommerce")


@pytest.fixture
def graph(tmp_path, monkeypatch, db):
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")
    monkeypatch.setattr("aughor.explorer.store.get_findings", lambda key: [])
    OVL.purge_connections([CONN])
    g = OntologyGraph.model_validate(json.loads(GRAPH.read_text()))
    _declare(g, "flag_order_for_review", FLAG)
    # The live reads an action makes go to THIS graph and THIS database — through the real resolver.
    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology", lambda conn, schema=None: g)
    monkeypatch.setattr("aughor.db.connection.open_connection_for_with_schema", lambda conn, schema: _Borrowed(db))
    yield g
    OVL.purge_connections([CONN])


def _action(graph, action_id: str = "flag_order_for_review"):
    return next(a for a in graph.declared_actions() if a.id == action_id)


def _scalar(db, sql):
    return db.execute("reference", sql).rows[0][0]


def _accept(order: str = ORDER, *, actor: str = "amit", action_id: str = "flag_order_for_review", reason="duplicate charge"):
    staged = stage_proposal(StagedProposal(
        connection_id=CONN, schema_name="ecommerce", action_id=action_id,
        params={"order": f"order:{order}", "reason": reason}, reasoning="a finding names it",
        # A fresh run key per staging: the inbox is idempotent by (run, call), and a reused key would
        # hand back a proposal an earlier test already executed.
        proposer="test", source="agent", run_id=uuid.uuid4().hex, call_id="0"))
    return accept_proposal(staged.id, actor=actor)[0]


def test_an_object_parameter_names_one_object_of_its_type(graph):
    flag = _action(graph)
    for passed in ("Order:O000123", "O000123", {"object_type": "order", "pk": "O000123"}):
        assert coerce_params(flag, {"order": passed, "reason": "x"})["order"] == "order:O000123"
    with pytest.raises(ParamError, match="takes an object of type order, not Customer"):
        coerce_params(flag, {"order": "Customer:C00042", "reason": "x"})
    with pytest.raises(ValueError, match="only an annotate action declares edits"):
        type(flag).model_validate({**FLAG, "id": "x", "kind": "side_effect"})
    with pytest.raises(ValueError, match="not one of this action's object parameters"):
        type(flag).model_validate({**FLAG, "id": "x", "edits": [{"object": "reason", "property": "p"}]})


def test_a_criterion_reads_the_object_live_and_fails_closed(graph, db):
    flag = _action(graph)
    coerced = coerce_params(flag, {"order": ORDER, "reason": "odd"})
    objects = resolve_objects(flag, coerced, default_object_resolver(flag, CONN, "ecommerce"))
    status = _scalar(db, f"SELECT status FROM orders WHERE order_id = '{ORDER}'")
    assert objects["order"]["properties"]["status"] == status and objects["object"] is objects["order"]
    assert evaluate_predicate(f"order.status == '{status}'", coerced, objects) is True
    assert evaluate_predicate(f"object.status != '{status}'", coerced, objects) is False
    with pytest.raises(CriterionError, match="no property 'colour'"):
        evaluate_predicate("order.colour == 'red'", coerced, objects)
    with pytest.raises(CriterionError, match="not allowed"):
        evaluate_predicate("reason.upper == 'X'", coerced, objects)
    # A number reads as a number, so a numeric criterion can pass — and a number against text fails closed.
    assert evaluate_predicate("order.total_amount > 0", coerced, objects) is True
    with pytest.raises(CriterionError, match="cannot compare"):
        evaluate_predicate("order.total_amount > 'many'", coerced, objects)


def test_a_missing_object_is_invalid_params_and_never_dispatches(graph):
    status, message, _ = evaluate_proposal(_action(graph), {"order": "order:NOPE", "reason": "x"},
                                           scope=CONN, schema_name="ecommerce")
    assert status == "invalid_params" and "NOPE" in message
    assert OVL.object_edits(CONN, current_org_id() or "") == []


def test_an_accepted_proposal_writes_the_declared_property_stamped_with_who_accepted(graph, db):
    result = _accept()
    assert result.ok, result.message
    [edit] = OVL.object_edits(CONN, current_org_id() or "")
    assert (edit.object_type, edit.row_key, edit.column, edit.body, edit.note, edit.actor, edit.origin) == (
        "order", ORDER, "review_flag", "true", "duplicate charge", "amit", "action:flag_order_for_review")
    assert edit.provenance().startswith("annotated by amit via flag_order_for_review, 20")
    # The source is never written: no such column appears anywhere in the warehouse.
    assert int(_scalar(db, "SELECT COUNT(*) FROM information_schema.columns WHERE column_name = 'review_flag'")) == 0


def test_a_criterion_the_object_fails_stops_the_accept_with_the_authored_message(graph, db):
    status = _scalar(db, f"SELECT status FROM orders WHERE order_id = '{ORDER}'")
    message = f"An order that is {status} cannot be flagged."
    _declare(graph, "flag_unless_status", {**FLAG, "submission_criteria": [
        {"expr": f"order.status != '{status}'", "message": message}]})
    result = _accept(action_id="flag_unless_status")
    assert (result.status, result.message) == ("criterion_failed", message)
    assert OVL.object_edits(CONN, current_org_id() or "") == []


def test_the_next_object_query_merges_the_property_with_provenance(graph, db):
    assert _accept().ok
    edits = OVL.object_edits(CONN, current_org_id() or "")
    one = compile_object_query({"object_type": "order", "filters": [{"path": "order_id", "value": ORDER}],
                                "by": ["order_id", "review_flag"], "measures": [{"name": "n", "agg": "count"}]},
                               graph, overlay=edits)
    # This connection hands cells back as text; the values are what matter.
    assert [[str(v).lower() for v in r] for r in db.execute("t", one.sql).rows] == [[ORDER.lower(), "true", "1"]]
    assert one.overlay[0]["provenance"].startswith("annotated by amit")
    assert any(line.startswith("overlay property review_flag on Order") for line in one.plan)
    flagged = compile_object_query({"object_type": "order", "filters": [{"path": "review_flag", "value": True}],
                                    "measures": [{"name": "n", "agg": "count"}]}, graph, overlay=edits)
    assert int(db.execute("t", flagged.sql).rows[0][0]) == 1
    unflagged = compile_object_query({"object_type": "order", "filters": [{"path": "review_flag", "op": "is_null"}],
                                      "measures": [{"name": "n", "agg": "count"}]}, graph, overlay=edits)
    assert int(db.execute("t", unflagged.sql).rows[0][0]) == int(_scalar(db, "SELECT COUNT(*) FROM orders")) - 1
    with pytest.raises(ObjectQueryRefused, match="no property 'review_flag'"):
        compile_object_query({"object_type": "order", "by": ["review_flag"],
                              "measures": [{"name": "n", "agg": "count"}]}, graph)


def test_the_object_page_shows_the_property_and_offers_the_action_pre_filled(graph, db):
    assert _accept().ok
    order = get_object(graph, db, "order", ORDER, overlay=OVL.object_edits(CONN, current_org_id() or ""))
    flag = next(p for p in order.properties if p["name"] == "review_flag")
    assert flag["value"] is True and flag["overlay"]["by"] == "amit" and flag["overlay"]["note"] == "duplicate charge"
    related = object_context(graph, db, CONN, "ecommerce", order)
    assert not [n for n in related["notes"] if n["column"] == "review_flag"]
    offer = next(a for a in related["actions"] if a["id"] == "flag_order_for_review")
    assert offer["prefilled"] == ["order"]
    assert {p["name"]: p["value"] for p in offer["params"]}["order"] == f"order:{ORDER}"


def test_an_edit_that_would_rewrite_a_source_column_is_refused(graph):
    _declare(graph, "rewrite_status", {**FLAG, "submission_criteria": [],
                                       "edits": [{"object": "order", "property": "status", "value": "ok"}]})
    action = _action(graph, "rewrite_status")
    coerced = coerce_params(action, {"order": ORDER, "reason": "x"})
    objects = resolve_objects(action, coerced, default_object_resolver(action, CONN, "ecommerce"))
    with pytest.raises(RuntimeError, match="reads from its source"):
        default_dispatch(action, coerced, CONN, actor="amit", objects=objects)
    assert OVL.object_edits(CONN, current_org_id() or "") == []


def test_the_proposer_is_told_how_to_pass_an_object(graph):
    seen = {}

    class _Model:
        def complete(self, *, system, user, response_model, temperature):
            seen["system"] = system
            return response_model(proposals=[{"action_id": "flag_order_for_review",
                                              "params": {"order": "Order:O000123", "reason": "the finding"}}])

    [proposal] = propose_actions(graph, f"a finding about {ORDER}", scope=CONN, schema_name="ecommerce",
                                 provider=_Model())
    assert proposal.ok and proposal.params["order"] == f"order:{ORDER}"
    assert "one order object, passed as 'order:<key>'" in seen["system"]
    assert "sets review_flag = 'true' on order" in seen["system"]
