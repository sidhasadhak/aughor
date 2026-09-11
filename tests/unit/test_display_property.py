"""ON-3b — the display property: proposed from the profile, declared by a person, measured against the data.

The proposal is pinned rule by rule; the measurement against hand-written counts over the seeded samples
warehouse; and every reader — the object page's title, a person's declaration through the overrides tree,
the file tree — against what was declared, so a refuted proposal cannot keep titling objects and a
person's choice cannot be lost or silently replaced.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import duckdb
import pytest
import yaml

from aughor.db.connection import open_connection
from aughor.demo.setup import _seed_ecommerce
from aughor.ontology import overrides as OV
from aughor.ontology.display import (
    NAMES_MIN_DISTINCT,
    NAMES_MIN_NON_NULL,
    apply_display_measurements,
    display_of,
    measure_override_display_properties,
    verdict,
)
from aughor.ontology.models import DisplayProperty, EntityProperty, OntologyEntity, OntologyGraph
from aughor.semantic.object_instances import get_object, title_column

GRAPH = Path(__file__).resolve().parents[2] / "evals" / "ablation_samples_ecommerce_ontology_measured.json"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("samples") / "samples.duckdb"
    con = duckdb.connect(str(path))
    _seed_ecommerce(con)
    con.close()
    conn = open_connection("duckdb", str(path), schema_name="ecommerce", connection_id="display-t")
    yield conn
    conn.close()


@pytest.fixture
def graph():
    return OntologyGraph.model_validate(json.loads(GRAPH.read_text()))


@pytest.fixture
def tree(tmp_path, monkeypatch):
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")
    return tmp_path


def _counts(db, table: str, column: str) -> tuple[int, int, int]:
    """(rows, values, distinct values) by hand. Aliased, and cast: the connection hands cells back as text and
    redacts a result column by its name."""
    sql = f"SELECT COUNT(*) AS n, COUNT({column}) AS v, COUNT(DISTINCT {column}) AS d FROM {table}"
    return tuple(int(v) for v in db.execute("reference", sql).rows[0])


def _brand(**props) -> OntologyEntity:
    return OntologyEntity(id="Brand", display_name="Brand", source_tables=["brands"], identity_key="brand_id",
                          grain_verified=True,
                          properties={name: EntityProperty(name=name, semantic_type=role, null_rate=null,
                                                           is_primary_key=name == "brand_id")
                                      for name, (role, null) in props.items()})


# ── the proposal ──────────────────────────────────────────────────────────────────────────

def test_the_profile_proposes_a_property_named_after_the_type_then_a_name_then_the_key():
    assert _brand(brand_id=("key", 0.0), brand=("text", 0.0), label=("dimension", 0.0)).display_property.name == "brand"
    assert _brand(brand_id=("key", 0.0), house_label=("dimension", 0.0),
                  full_name=("dimension", 0.0)).display_property.name == "full_name"      # hints keep their order
    keyed = _brand(brand_id=("key", 0.0), tier=("dimension", 0.0))
    assert (keyed.display_property.name, keyed.display_property.source, keyed.display_property.verified) == (
        "brand_id", "proposed", None)
    assert "the key does" in keyed.display_property.note
    assert _brand(brand_id=("key", 0.0), name=("dimension", 0.8)).display_property.name == "brand_id"  # mostly empty
    assert _brand(brand_id=("key", 0.0), name=("measure", 0.0)).display_property.name == "brand_id"    # not text


def test_a_graph_built_before_the_field_existed_loads_with_a_proposal(graph):
    assert {eid: e.display_property.name for eid, e in graph.entities.items()} == {
        "Customer": "full_name", "Product": "product_name", "Order": "order_id",
        "OrderItem": "item_id", "Review": "review_id"}


def test_the_verdict_names_objects_only_when_most_carry_a_value_and_most_values_differ():
    assert verdict(100, 100, 100)[0] is True
    assert verdict(100, 95, 60)[0] is True                                   # shared names are still names
    assert verdict(100, 80, 80) == (False, "80 of 100 objects carry a value, 80 distinct — too many objects "
                                           "have none for it to name them")
    assert "a category, not a name" in verdict(100, 100, 5)[1] and verdict(100, 100, 5)[0] is False
    assert verdict(0, 0, 0)[0] is None and verdict(None, None, None)[0] is None


# ── the measurement ───────────────────────────────────────────────────────────────────────

def test_the_measure_counts_the_proposal_over_the_backing_and_says_whether_it_names_objects(db, graph):
    report = apply_display_measurements(graph, db)
    shown = graph.entities["Customer"].display_property
    rows, non_null, distinct = _counts(db, "customers", "full_name")
    assert (shown.name, shown.rows, shown.non_null, shown.distinct) == ("full_name", rows, non_null, distinct)
    assert shown.verified is (non_null / rows >= NAMES_MIN_NON_NULL and distinct / non_null >= NAMES_MIN_DISTINCT)
    order = graph.entities["Order"].display_property
    assert (order.name, order.verified) == ("order_id", True)                     # a key always names its objects
    summary = report.summary()
    assert summary["entities"] == len(graph.entities) and "Order" in summary["names"]


def test_a_category_is_refuted_as_a_name_and_a_refuted_proposal_gives_way_to_the_key(db, graph):
    product = graph.entities["Product"]
    product.display_property = DisplayProperty(name="category")                   # as though the profile proposed it
    apply_display_measurements(graph, db)
    rows, non_null, distinct = _counts(db, "products", "category")
    assert distinct / non_null < NAMES_MIN_DISTINCT                               # the premise: few categories
    assert product.display_property.verified is False and "a category, not a name" in product.display_property.note
    shown = display_of(product)
    assert (shown["property"], shown["source"], shown["refuted"]) == ("product_id", "key", "category")
    assert title_column(product) is None


def test_a_pii_named_property_is_still_measured(db, graph):
    """A reader's result column is redacted by its NAME (`count(email)`); the probe runs as platform plumbing — its
    `__display_probe__` id skips redaction — so a PII-named property still measures instead of reading as unreadable."""
    graph.entities["Customer"].display_property = DisplayProperty(name="email")
    apply_display_measurements(graph, db)
    shown = graph.entities["Customer"].display_property
    assert (shown.rows, shown.non_null, shown.distinct) == _counts(db, "customers", "email")


# ── a person's declaration ────────────────────────────────────────────────────────────────

def test_a_persons_declaration_binds_is_measured_and_titles_the_object_whatever_the_verdict(db, graph, tree):
    ov = OV.OntologyOverride(target_kind="entity", target_id="Customer", fields={"display_property": "city"})
    OV.bind_overrides(ov, graph, lambda sql: None)
    assert ov.binding["display_property"] == {"bound": True, "note": "", "property": "city"}
    OV.save_override("samples", "ecommerce", ov)
    report = measure_override_display_properties("samples", "ecommerce", db, graph)
    assert report.overrides_measured == ["Customer"]
    served = copy.deepcopy(graph)
    OV.apply_overrides(served, "samples", "ecommerce")
    shown = served.entities["Customer"].display_property
    rows, non_null, distinct = _counts(db, "customers", "city")
    assert (shown.name, shown.source, shown.rows, shown.non_null, shown.distinct) == (
        "city", "human", rows, non_null, distinct)
    assert shown.verified is verdict(rows, non_null, distinct)[0]
    (city,) = db.execute("reference", "SELECT city FROM customers WHERE customer_id = 'C00042'").rows[0]
    page = get_object(served, db, "customer", "C00042")
    # a person's declaration stands even where the measurement says it does not name objects — shown beside it
    assert page.title == city and (page.display["property"], page.display["source"]) == ("city", "human")
    assert graph.entities["Customer"].display_property.name == "full_name"      # the raw graph still proposes


def test_a_declaration_the_type_cannot_honour_never_binds_and_never_titles_anything(graph, tree):
    ov = OV.OntologyOverride(target_kind="entity", target_id="Customer", fields={"display_property": "nickname"})
    OV.bind_overrides(ov, graph, lambda sql: None)
    assert ov.binding["display_property"]["bound"] is False
    assert "no property 'nickname'" in ov.binding["display_property"]["note"]
    OV.save_override("samples", "ecommerce", ov)
    _, report = OV.apply_overrides(graph, "samples", "ecommerce")
    assert graph.entities["Customer"].display_property.name == "full_name"      # the proposal stands
    assert any(line.startswith("entity:Customer") for line in report.skipped)


def test_re_declaring_the_same_property_keeps_its_measurement(db, graph, tree):
    ov = OV.OntologyOverride(target_kind="entity", target_id="Customer", fields={"display_property": "city"})
    OV.bind_overrides(ov, graph, lambda sql: None)
    OV.save_override("samples", "ecommerce", ov)
    measure_override_display_properties("samples", "ecommerce", db, graph)
    again = OV.find_override("samples", "ecommerce", "entity", "Customer")
    OV.bind_overrides(again, graph, lambda sql: None)
    assert again.binding["display_property"]["rows"] == _counts(db, "customers", "city")[0]
    again.fields["display_property"] = "country"                               # a different property is unmeasured
    OV.bind_overrides(again, graph, lambda sql: None)
    assert "rows" not in again.binding["display_property"]


def test_the_file_tree_round_trips_the_display_property_as_its_name(graph, tmp_path):
    from aughor.ontology.filetree import export_tree, import_tree
    export_tree(tmp_path, graph)
    assert import_tree(tmp_path, graph) == []
    path = tmp_path / "entities" / "Customer.yaml"
    doc = yaml.safe_load(path.read_text())
    assert doc["editable"]["display_property"] == "full_name"
    doc["editable"]["display_property"] = "city"
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    [ov] = import_tree(tmp_path, graph)
    assert (ov.target_id, ov.fields) == ("Customer", {"display_property": "city"})
