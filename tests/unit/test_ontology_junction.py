"""Arc NV-2 — the junction mark is a measured fact, and the N:N through it is said in both prompt blocks.

The rule (`aughor.ontology.junction`): one table, no measure, exactly two value-verified (or engine-declared) foreign
keys to two different entities, nothing else but its own key and timestamps. Each test below is a table that fails one
clause — the measure, the dimension, a third entity, an unmeasured edge — against the one that qualifies, so the mark
cannot pass for the wrong reason. The study's own check is here too: an order line with measures is NOT a junction.
"""
from __future__ import annotations

from aughor.ontology.builder import render_ontology_annotations
from aughor.ontology.junction import MIN_OVERLAP, mark_junctions, qualifies
from aughor.ontology.models import EntityProperty, OntologyEntity, OntologyGraph, OntologyRelationship
from aughor.ontology.semantic_block import render_relationship_block


def _entity(eid, table, props, key="", **kw):
    return OntologyEntity(id=eid, display_name=eid, source_tables=[table], identity_key=key,
                          grain_verified=bool(key), properties=props, **kw)


def _fk(name):
    return EntityProperty(name=name, data_type="INTEGER", semantic_type="identifier", is_foreign_key=True)


def _rel(frm, to, ft, fc, tt, tc, overlap=0.97, confidence="verified"):
    return OntologyRelationship(id=f"{frm}_RELATES_TO_{to}", from_entity=frm, to_entity=to, cardinality="N:1",
                                join_sql=f"{ft}.{fc} = {tt}.{tc}", from_table=ft, from_col=fc, to_table=tt,
                                to_col=tc, join_confidence=confidence, value_overlap=overlap,
                                measured_cardinality="N:1")


def _graph(junction_props, extra_rels=(), **entity_kw):
    customer = _entity("Customer", "customers", {"customer_id": EntityProperty(name="customer_id", is_primary_key=True)},
                       key="customer_id")
    product = _entity("Product", "products", {"product_id": EntityProperty(name="product_id", is_primary_key=True)},
                      key="product_id")
    j = _entity("CustomerProduct", "customer_products", junction_props, **entity_kw)
    rels = {
        "a": _rel("CustomerProduct", "Customer", "customer_products", "customer_id", "customers", "customer_id"),
        "b": _rel("CustomerProduct", "Product", "customer_products", "product_id", "products", "product_id", 0.91),
    }
    for r in extra_rels:
        rels[r.id] = r
    g = OntologyGraph(connection_id="c", schema_name="main", schema_fingerprint="fp",
                      entities={"Customer": customer, "Product": product, "CustomerProduct": j},
                      relationships=rels)
    g.relationship_index = {e: [] for e in g.entities}
    return g


def test_a_pure_bridge_is_marked_and_the_link_through_it_declared():
    g = _graph({"customer_id": _fk("customer_id"), "product_id": _fk("product_id"),
                "added_at": EntityProperty(name="added_at", data_type="TIMESTAMP", semantic_type="timestamp")})
    assert mark_junctions(g) == ["CustomerProduct"]
    j = g.entities["CustomerProduct"].junction
    assert j is not None and j.between == ["Customer", "Product"] and j.through == ["customer_id", "product_id"]
    assert j.overlaps == [0.97, 0.91] and j.verified
    assert "every non-key column is a foreign key" in j.note and "91% of keys found" in j.note

    rid = "Customer_RELATES_TO_Product_via_CustomerProduct"
    rel = g.relationships[rid]
    assert rel.via == "CustomerProduct" and rel.cardinality == "N:N" and rel.measured_cardinality == "N:N"
    assert rel.join_sql == ("customers.customer_id = customer_products.customer_id "
                            "AND customer_products.product_id = products.product_id")
    assert rel.join_confidence == "verified" and rel.value_overlap == 0.91
    assert rel.api_name == "customer_to_product_via_customer_product"
    assert "Product" in g.relationship_index["Customer"] and "Customer" in g.relationship_index["Product"]


def test_marking_twice_changes_nothing():
    g = _graph({"customer_id": _fk("customer_id"), "product_id": _fk("product_id")})
    mark_junctions(g)
    n = len(g.relationships)
    assert mark_junctions(g) == [] and len(g.relationships) == n


def test_an_order_line_with_measures_is_not_a_junction():
    """The study's own receipt: order_items → products carries quantity and price, so it is a line, not a bridge."""
    g = _graph({"customer_id": _fk("customer_id"), "product_id": _fk("product_id"),
                "quantity": EntityProperty(name="quantity", data_type="INTEGER", semantic_type="measure")})
    assert qualifies(g, "CustomerProduct") == [] and mark_junctions(g) == []


def test_a_dimension_of_its_own_disqualifies():
    g = _graph({"customer_id": _fk("customer_id"), "product_id": _fk("product_id"),
                "role": EntityProperty(name="role", data_type="VARCHAR", semantic_type="dimension")})
    assert mark_junctions(g) == []


def test_an_own_surrogate_key_is_allowed():
    g = _graph({"id": EntityProperty(name="id", data_type="INTEGER", is_primary_key=True),
                "customer_id": _fk("customer_id"), "product_id": _fk("product_id")}, key="id")
    assert mark_junctions(g) == ["CustomerProduct"]


def test_an_edge_below_the_floor_is_not_a_foreign_key():
    g = _graph({"customer_id": _fk("customer_id"), "product_id": _fk("product_id")})
    g.relationships["b"].value_overlap = MIN_OVERLAP - 0.01
    assert mark_junctions(g) == []


def test_an_unmeasured_edge_is_not_a_fact_unless_the_engine_declared_it():
    g = _graph({"customer_id": _fk("customer_id"), "product_id": _fk("product_id")})
    g.relationships["b"].value_overlap = None
    g.relationships["b"].join_confidence = "inferred"
    assert mark_junctions(g) == []
    g.relationships["b"].join_confidence = "declared"
    assert mark_junctions(g) == ["CustomerProduct"]
    j = g.entities["CustomerProduct"].junction
    assert j is not None and not j.verified and "overlap not measured" in j.note
    rel = g.relationships["Customer_RELATES_TO_Product_via_CustomerProduct"]
    assert rel.join_confidence == "inferred" and rel.value_overlap is None


def test_a_third_foreign_key_is_not_a_pair():
    third = _entity("Store", "stores", {"store_id": EntityProperty(name="store_id", is_primary_key=True)}, key="store_id")
    g = _graph({"customer_id": _fk("customer_id"), "product_id": _fk("product_id"), "store_id": _fk("store_id")},
               extra_rels=[_rel("CustomerProduct", "Store", "customer_products", "store_id", "stores", "store_id")])
    g.entities["Store"] = third
    assert mark_junctions(g) == []


def test_a_declared_or_absorbed_type_is_left_to_its_person():
    g = _graph({"customer_id": _fk("customer_id"), "product_id": _fk("product_id")}, origin="human")
    assert mark_junctions(g) == []
    g = _graph({"customer_id": _fk("customer_id"), "product_id": _fk("product_id")}, absorbed_into="Customer")
    assert mark_junctions(g) == []


def test_both_prompt_blocks_say_the_junction():
    g = _graph({"customer_id": _fk("customer_id"), "product_id": _fk("product_id")})
    mark_junctions(g)
    entity_block = render_ontology_annotations(g)
    assert "junction between Customer and Product (customer_id, product_id) — join through it; it carries no measure" in entity_block
    rel_block = render_relationship_block(g, {
        "customers": ["customer_id"], "products": ["product_id"], "customer_products": ["customer_id", "product_id"]})
    assert ("- customers.customer_id → products.product_id via CustomerProduct (customers.customer_id = "
            "customer_products.customer_id AND customer_products.product_id = products.product_id) [N:N, verified, 91% key overlap]") in rel_block


def test_the_object_compiler_still_refuses_the_n_n_through_a_junction():
    """The study's falsifier keeps the compiler change waiting; until then the declared N:N is refused BY NAME, as
    every N:N is — the link is listed, and `link_problem` says why it may not be traversed."""
    from aughor.semantic.object_query import link_problem, object_links
    g = _graph({"customer_id": _fk("customer_id"), "product_id": _fk("product_id")})
    mark_junctions(g)
    links = {h.rel.id: h for h in object_links(g, g.entities["Customer"])}
    via = links["Customer_RELATES_TO_Product_via_CustomerProduct"]
    assert via.label == "N:N"
    problem = link_problem(via)
    assert "N:N" in problem and "measurement" in problem
