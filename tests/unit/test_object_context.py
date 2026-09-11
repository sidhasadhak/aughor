"""ON-3 — the panels around one object, each measured: metrics compiled for this object, findings cited
by an exact key literal in their SQL (never by being about the type), the overlay notes on its row, and
declared actions that take it with the key pre-filled — declared through the overrides tree, the way a
human declares one."""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from aughor.db.connection import open_connection
from aughor.demo.setup import _seed_ecommerce
from aughor.ontology import overrides as OV
from aughor.ontology.models import OntologyGraph
from aughor.semantic.object_context import identity_columns, object_context
from aughor.semantic.object_instances import get_object

GRAPH = Path(__file__).resolve().parents[2] / "evals" / "ablation_samples_ecommerce_ontology_measured.json"
CONN = "object-context-t"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("samples") / "samples.duckdb"
    con = duckdb.connect(str(path))
    _seed_ecommerce(con)
    con.close()
    conn = open_connection("duckdb", str(path), schema_name="ecommerce", connection_id=CONN)
    yield conn
    conn.close()


@pytest.fixture
def graph(tmp_path, monkeypatch):
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")
    monkeypatch.setattr("aughor.explorer.store.get_findings", lambda key: [])
    return OntologyGraph.model_validate(json.loads(GRAPH.read_text()))


def _scalar(db, sql):
    return db.execute("reference", sql).rows[0][0]


def test_a_customers_metrics_are_compiled_across_its_orders(db, graph):
    customer = get_object(graph, db, "customer", "C00042")
    metrics = {m["metric"]: m for m in object_context(graph, db, CONN, "ecommerce", customer)["metrics"]}
    revenue = _scalar(db, "SELECT SUM(total_amount) FROM orders WHERE customer_id = 'C00042'")
    assert metrics["revenue"]["via"] == "customer_to_order" and metrics["revenue"]["on"] == "order"
    assert round(float(metrics["revenue"]["value"]), 2) == round(float(revenue), 2)
    aov = _scalar(db, "SELECT AVG(total_amount) FROM orders WHERE customer_id = 'C00042'")
    assert round(float(metrics["aov"]["value"]), 4) == round(float(aov), 4)


def test_a_finding_cites_the_object_only_by_an_exact_key_literal(db, graph, monkeypatch):
    monkeypatch.setattr("aughor.explorer.store.get_findings", lambda key: [
        {"id": "f1", "finding": "three lines", "sql": "SELECT COUNT(*) FROM order_items WHERE order_id = 'O000123'"},
        {"id": "f2", "finding": "about orders in aggregate", "sql": "SELECT status, COUNT(*) FROM orders GROUP BY 1"},
        {"id": "f3", "finding": "another order", "sql": "SELECT * FROM orders WHERE order_id = 'O000999'"},
    ])
    from aughor.kernel.ledger import Ledger
    Ledger.default().artifact_write("chat_answer", f"chat:{CONN}:t1",
                                    {"question": "what did O000123 cost?", "headline": "It cost…",
                                     "sql": "SELECT o.total_amount FROM orders o WHERE o.order_id = 'O000123'"},
                                    conn_id=CONN)
    order = get_object(graph, db, "order", "O000123")
    assert ("order_items", "order_id") in identity_columns(graph, graph.entities["Order"], order)
    findings = object_context(graph, db, CONN, "ecommerce", order)["findings"]
    assert [f["id"] for f in findings if f["kind"] == "finding"] == ["f1"]
    assert findings[0]["matched"] == "order_items.order_id = 'O000123'"
    assert any(f["kind"] == "answer" and f["question"] == "what did O000123 cost?" for f in findings)


def test_notes_on_the_row_and_actions_that_take_the_object_arrive_pre_filled(db, graph):
    from aughor.actions.overlay import OverlayEdit, save_edit
    from aughor.org.context import current_org_id
    org = current_org_id() or ""
    save_edit(OverlayEdit(connection_id=CONN, org_id=org, table="orders", column="status", row_key="O000123",
                          key_column="order_id", body="checked by ops"))
    save_edit(OverlayEdit(connection_id=CONN, org_id=org, table="orders", column="status", row_key="O000124",
                          key_column="order_id", body="a different order"))
    for action_id, fields in {
        "flag_order_for_review": {"display_name": "Flag order for review", "entity": "Order", "kind": "annotate",
                                  "risk": "low", "params": [{"name": "order_id"}, {"name": "reason"}]},
        "refund_orders": {"kind": "side_effect", "params": [{"name": "amount_eur", "data_type": "NUMERIC"}]},
    }.items():
        OV.save_override(CONN, "ecommerce", OV.OntologyOverride(target_kind="action", target_id=action_id,
                                                                fields=fields))
    OV.apply_overrides(graph, CONN, "ecommerce")
    order = get_object(graph, db, "order", "O000123")
    related = object_context(graph, db, CONN, "ecommerce", order)
    assert [n["body"] for n in related["notes"]] == ["checked by ops"]
    assert [a["id"] for a in related["actions"]] == ["flag_order_for_review"]
    flag = related["actions"][0]
    assert flag["prefilled"] == ["order_id"]
    assert {p["name"]: p["value"] for p in flag["params"]} == {"order_id": "O000123", "reason": None}
