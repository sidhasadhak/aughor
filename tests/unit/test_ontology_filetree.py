"""Version-control round-trip — export ontology to files, edit, import as overrides.

Locks the nao-headline behaviour: an unedited export re-imports as a no-op, and
only the fields a human changed on disk become overrides.
"""
from __future__ import annotations

import yaml

from aughor.ontology.business_rules import rule_fields
from aughor.ontology.declared import entity_fields, link_fields
from aughor.ontology.models import Backing, OntologyEntity, OntologyGraph, OntologyMetric
from aughor.ontology.filetree import export_tree, import_tree, read_declarations
from aughor.ontology.overrides import OntologyOverride


def _graph() -> OntologyGraph:
    g = OntologyGraph(connection_id="c", schema_name="s", schema_fingerprint="fp")
    g.entities["Order"] = OntologyEntity(
        id="Order", display_name="Order", description="auto desc",
        source_tables=["orders"], identity_key="order_id", grain_verified=True)
    g.metrics["revenue"] = OntologyMetric(
        id="revenue", display_name="Revenue", entity="Order",
        formula_sql="SUM(total_amount)", verified=True)
    return g


def test_export_then_unedited_import_is_noop(tmp_path):
    g = _graph()
    paths = export_tree(tmp_path, g)
    assert any("entities" in p for p in paths) and any("metrics" in p for p in paths)
    # round-trip with no edits → zero overrides
    assert import_tree(tmp_path, g) == []


def test_edit_on_disk_becomes_overrides(tmp_path):
    g = _graph()
    export_tree(tmp_path, g)

    # human edits the metric formula and the entity description on disk
    mpath = tmp_path / "metrics" / "revenue.yaml"
    doc = yaml.safe_load(mpath.read_text())
    doc["editable"]["formula_sql"] = "SUM(total_amount) * 1.0"
    mpath.write_text(yaml.safe_dump(doc))

    epath = tmp_path / "entities" / "Order.yaml"
    edoc = yaml.safe_load(epath.read_text())
    edoc["editable"]["description"] = "human-curated description"
    epath.write_text(yaml.safe_dump(edoc))

    # author a brand-new metric file
    (tmp_path / "metrics" / "category_revenue.yaml").write_text(yaml.safe_dump({
        "_kind": "metric", "id": "category_revenue", "entity": "OrderItem",
        "editable": {"display_name": "Category Revenue", "formula_sql": "SUM(line_total)"},
    }))

    overrides = import_tree(tmp_path, g)
    by_target = {o.target_id: o for o in overrides}

    assert by_target["revenue"].target_kind == "metric"
    assert by_target["revenue"].fields["formula_sql"] == "SUM(total_amount) * 1.0"
    assert by_target["Order"].fields["description"] == "human-curated description"
    assert by_target["category_revenue"].fields["formula_sql"] == "SUM(line_total)"
    assert by_target["category_revenue"].fields["entity"] == "OrderItem"
    # the unchanged metric display_name must NOT generate an override field
    assert "display_name" not in by_target["revenue"].fields


# ── R3: a declaration is not a diff — it is written whole and declared again ─────────────────

def _declarations() -> list[OntologyOverride]:
    return [
        OntologyOverride(target_kind="entity", target_id="Payment", fields={
            "declared": True, "display_name": "Payment", "origin": "human", "domain": "Finance",
            "backing": {"kind": "table", "primary_key": "payment_id", "table": "payments"},
            "bindings": {"refunds": {"kind": "static", "table": "refunds", "key": "payment_id"}}}),
        OntologyOverride(target_kind="link", target_id="Payment_pays_for_Order", fields={
            "declared": True, "from_entity": "Payment", "to_entity": "Order", "name": "pays_for",
            "from_column": "order_id", "to_column": "order_id", "origin": "human"}),
        OntologyOverride(target_kind="rule", target_id="eu_orders", fields={
            "declared": True, "entity": "Order", "kind": "value_set", "property": "country",
            "values": ["DE", "FR"], "origin": "human"}),
        OntologyOverride(target_kind="entity", target_id="Order", fields={"description": "an edit, not a declaration"}),
    ]


def _with_payment() -> OntologyGraph:
    g = _graph()
    g.entities["Payment"] = OntologyEntity(id="Payment", display_name="Payment", source_tables=["payments"],
                                           identity_key="payment_id", grain_verified=True, origin="human")
    return g


def test_a_declaration_is_written_as_the_spec_its_door_takes_and_read_back_in_declaring_order(tmp_path):
    declarations = _declarations()
    export_tree(tmp_path, _with_payment(), declarations)
    assert not (tmp_path / "entities" / "Payment.yaml").exists()          # a declared type: one file, under declared/
    assert (tmp_path / "entities" / "Order.yaml").exists()

    read, unreadable = read_declarations(tmp_path)
    assert unreadable == []
    assert [(kind, target) for kind, target, _, _ in read] == [
        ("entity", "Payment"), ("link", "Payment_pays_for_Order"), ("rule", "eu_orders")]
    (_, _, payment, edits), (_, _, link, _), (_, _, rule, _) = read
    assert payment == {"id": "Payment", "display_name": "Payment", "domain": "Finance", "origin": "human",
                       "backing": {"primary_key": "payment_id", "table": "payments"}}
    assert edits == ["bindings"]                                          # a later edit is named, not carried
    # Each door's own trim of the spec stores exactly what the declaration stored.
    assert entity_fields(payment) == {k: v for k, v in declarations[0].fields.items() if k != "bindings"}
    assert link_fields(link) == declarations[1].fields and rule_fields(rule) == declarations[2].fields
    assert import_tree(tmp_path, _graph()) == []                          # a declared type is not diffed as an edit


def test_an_export_leaves_no_file_for_a_declaration_since_withdrawn_and_names_a_broken_one(tmp_path):
    export_tree(tmp_path, _with_payment(), _declarations())
    export_tree(tmp_path, _graph(), _declarations()[1:])                  # Payment withdrawn since
    read, _ = read_declarations(tmp_path)
    assert "Payment" not in [target for _, target, _, _ in read]
    (tmp_path / "declared" / "links" / "broken.yaml").write_text("spec: [not, a, mapping]\n")
    _, unreadable = read_declarations(tmp_path)
    assert unreadable == ["declared/links/broken.yaml"]


def test_a_backing_keeps_the_connection_its_rows_live_on_through_the_tree(tmp_path):
    g = _graph()
    g.entities["Order"].backing = Backing(kind="table", table="orders", primary_key="order_id", connection_id="crm")
    export_tree(tmp_path, g)
    assert yaml.safe_load((tmp_path / "entities" / "Order.yaml").read_text())["editable"]["backing"]["connection_id"] == "crm"
    assert import_tree(tmp_path, g) == []                                 # unedited: still a no-op
    built = _graph()
    built.entities["Order"].backing = Backing(kind="table", table="orders", primary_key="order_id")
    [moved] = import_tree(tmp_path, built)
    assert moved.fields == {"backing": {"kind": "table", "table": "orders", "sql": None, "primary_key": "order_id",
                                        "connection_id": "crm"}}
