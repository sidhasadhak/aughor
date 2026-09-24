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
    assert [f["id"] for f in findings if f["kind"] == "finding" and not f.get("scope")] == ["f1"]
    assert findings[0]["matched"] == "order_items.order_id = 'O000123'"
    # PENDING item 13: the aggregate one is shown, marked as about orders in general; the one
    # pinned to ANOTHER order is about that order, and is not shown here at all
    assert [(f["id"], f.get("scope")) for f in findings if f.get("scope")] == [("f2", "type")]
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


def test_a_finding_about_the_objects_segment_is_shown_as_its_segment(db, graph, monkeypatch):
    """PENDING item 13 — exploration findings are aggregates, so the exact tier was empty on every
    object page of every connection. A finding that filters one of the object's own label columns
    to its value, or groups by that column and names the value, is about its SEGMENT."""
    customer = get_object(graph, db, "customer", "C00042")
    props = {p["name"]: p["value"] for p in customer.properties}
    label = next(c for c in ("country", "segment", "tier", "city", "region", "channel")
                 if isinstance(props.get(c), str) and props.get(c))
    value = props[label]
    monkeypatch.setattr("aughor.explorer.store.get_findings", lambda key: [
        {"id": "g1", "finding": f"Customers in {value} spend 18% more than average.",
         "sql": f"SELECT {label}, AVG(total_amount) FROM customers c JOIN orders o USING (customer_id) GROUP BY 1"},
        {"id": "g2", "finding": f"Revenue from the {value} {label} fell 4%.",
         "sql": f"SELECT SUM(total_amount) FROM orders o JOIN customers c USING (customer_id) WHERE c.{label} = '{value}'"},
        {"id": "g3", "finding": "Customers elsewhere spend less.",
         "sql": f"SELECT {label}, AVG(total_amount) FROM customers GROUP BY 1"},
        {"id": "g4", "finding": "Another customer churned.", "sql": "SELECT * FROM customers WHERE customer_id = 'C00999'"},
    ])
    findings = object_context(graph, db, CONN, "ecommerce", customer)["findings"]
    scoped = {f["id"]: (f.get("scope"), f.get("segment"), f["matched"]) for f in findings}
    assert scoped["g1"][0] == "segment" and scoped["g1"][1].lower() == f"{label} {value}".lower()
    assert scoped["g1"][2] == f"grouped by {label}; names '{value}'"
    assert scoped["g2"][0] == "segment" and scoped["g2"][2] == f"customers.{label} = '{value}'"
    assert scoped["g3"][0] == "type"                   # groups by it, but never names this value
    assert "g4" not in scoped                          # about another customer


def test_a_number_that_arrives_as_text_does_not_segment(db, graph):
    """The samples customer's `lifetime_orders` arrives as '46': a measure, not a label."""
    from aughor.semantic.object_context import segment_values
    customer = get_object(graph, db, "customer", "C00042")
    segment = segment_values(graph.entities["Customer"], customer)
    assert "country" in segment and "lifetime_orders" not in segment and "lifetime_spend" not in segment



def test_bigquery_findings_are_read_and_another_objects_segment_twin_is_not_shown(db, graph, monkeypatch):
    """Branch review, 2026-09-24: backticked BigQuery tables failed the neutral parse and those
    findings vanished from the wider tiers; and a finding pinned to ANOTHER customer who shares
    this one's country was shown as "about its segment"."""
    customer = get_object(graph, db, "customer", "C00042")
    country = {p["name"]: p["value"] for p in customer.properties}["country"]
    monkeypatch.setattr("aughor.explorer.store.get_findings", lambda key: [
        {"id": "bq", "finding": f"{country} leads repeat purchases.",
         "sql": "SELECT c.country, COUNT(*) FROM `proj.shop.customers` c GROUP BY c.country"},
        {"id": "twin", "finding": "C00077 spent the most.",
         "sql": f"SELECT * FROM customers WHERE customer_id = 'C00077' AND country = '{country}'"},
    ])
    found = {f["id"]: f.get("scope") for f in object_context(graph, db, CONN, "ecommerce", customer)["findings"]}
    assert found.get("bq") == "segment" and "twin" not in found
