"""Version-control round-trip — export ontology to files, edit, import as overrides.

Locks the nao-headline behaviour: an unedited export re-imports as a no-op, and
only the fields a human changed on disk become overrides.
"""
from __future__ import annotations

import yaml

from aughor.ontology.models import OntologyEntity, OntologyGraph, OntologyMetric
from aughor.ontology.filetree import export_tree, import_tree


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
