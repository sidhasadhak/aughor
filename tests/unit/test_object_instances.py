"""ON-3 — one object, resolved live through its backing: its properties, its links, its linked objects.

Every expectation is read back from the same seeded samples warehouse with a hand-written query, so
a wrong join, a wrong key or a wrong count cannot pass by agreeing with itself.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from aughor.db.connection import open_connection
from aughor.demo.setup import _seed_ecommerce
from aughor.ontology.models import Backing, OntologyGraph
from aughor.semantic.object_instances import ObjectNotFound, get_object, list_linked, title_column
from aughor.semantic.object_query import ObjectQueryRefused

GRAPH = Path(__file__).resolve().parents[2] / "evals" / "ablation_samples_ecommerce_ontology_measured.json"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("samples") / "samples.duckdb"
    con = duckdb.connect(str(path))
    _seed_ecommerce(con)
    con.close()
    conn = open_connection("duckdb", str(path), schema_name="ecommerce", connection_id="instances-t")
    yield conn
    conn.close()


@pytest.fixture
def graph():
    return OntologyGraph.model_validate(json.loads(GRAPH.read_text()))


def _one(db, sql):
    return [str(v) for v in db.execute("reference", sql).rows[0]]


def test_an_order_opens_with_its_properties_and_its_links_resolved_to_a_key_or_a_count(db, graph):
    order = get_object(graph, db, "order", "O000123")
    props = {p["name"]: str(p["value"]) for p in order.properties}
    customer_id, status = _one(db, "SELECT customer_id, status FROM orders WHERE order_id = 'O000123'")
    assert (order.object_type, order.key, order.pk) == ("order", "order_id", "O000123")
    assert props["customer_id"] == customer_id and props["status"] == status
    links = {link["name"]: link for link in order.links}
    assert links["order_to_customer"]["kind"] == "to-one" and links["order_to_customer"]["pk"] == customer_id
    (items,) = _one(db, "SELECT COUNT(*) FROM order_items WHERE order_id = 'O000123'")
    assert links["order_to_order_item"]["kind"] == "to-many"
    assert links["order_to_order_item"]["count"] == int(items) and int(items) > 0


def test_a_customer_is_titled_by_its_name_and_lists_its_orders_a_page_at_a_time(db, graph):
    customer = get_object(graph, db, "customer", "C00042")
    (full_name,) = _one(db, "SELECT full_name FROM customers WHERE customer_id = 'C00042'")
    assert title_column(graph.entities["Customer"]) == "full_name" and customer.title == full_name
    expected = [str(r[0]) for r in db.execute(
        "reference", "SELECT order_id FROM orders WHERE customer_id = 'C00042' ORDER BY order_id").rows]
    page = list_linked(graph, db, "customer", "C00042", "order", limit=3)
    position = page["columns"].index("order_id")
    assert [str(r[position]) for r in page["rows"]] == expected[:3] and page["has_more"] is (len(expected) > 3)
    rest = list_linked(graph, db, "customer", "C00042", "customer_to_order", limit=50, offset=3)
    assert [str(r[position]) for r in rest["rows"]] == expected[3:] and rest["has_more"] is False
    assert next(link for link in customer.links if link["name"] == "customer_to_order")["count"] == len(expected)


def test_a_link_the_compiler_refuses_is_shown_with_its_reason_and_never_traversed(db, graph):
    item = get_object(graph, db, "order_item", "7")
    review = next(link for link in item.links if link["to"] == "review")
    assert review["usable"] is False and "N:N" in review["why_not"] and "count" not in review
    with pytest.raises(ObjectQueryRefused) as refused:
        list_linked(graph, db, "order_item", "7", review["name"])
    assert "N:N" in refused.value.reason


def test_a_link_touching_a_query_backed_type_is_not_traversed(db, graph):
    graph.entities["Product"].backing = Backing(kind="query", sql="SELECT * FROM products", primary_key="product_id")
    item = get_object(graph, db, "order_item", "7")
    product = next(link for link in item.links if link["to"] == "product")
    assert product["usable"] is False and "query backing" in product["why_not"]


def test_a_missing_key_is_not_found_an_unknown_type_is_refused_and_a_key_is_never_spliced(db, graph):
    with pytest.raises(ObjectNotFound):
        get_object(graph, db, "order", "O999999")
    with pytest.raises(ObjectNotFound):
        get_object(graph, db, "order", "x' OR '1'='1")
    with pytest.raises(ObjectQueryRefused) as refused:
        get_object(graph, db, "invoice", "1")
    assert "order" in refused.value.available
    item = get_object(graph, db, "order_item", "7")                 # a BIGINT key, typed as a number
    assert {p["name"]: str(p["value"]) for p in item.properties}["item_id"] == "7"


# ── the names behind the keys ────────────────────────────────────────────────────
#
# An answer table linked a key and rendered the key. Every type already declares the property that
# names its objects, measured against its backing — it just never reached the table. These pin the
# batch door that resolves a page of keys in ONE query, and its refusals.

def test_many_keys_are_named_in_one_query_and_a_key_nothing_matches_is_simply_absent(db, graph):
    from aughor.semantic.object_instances import titles

    reference = {str(r[0]): str(r[1]) for r in db.execute(
        "reference", "SELECT customer_id, full_name FROM customers ORDER BY customer_id LIMIT 5").rows}
    found = titles(graph, db, "customer", [*reference, "C99999"])

    assert found["property"] == "full_name" and found["truncated"] is False
    assert found["titles"] == reference          # every key named, and the key nothing matches is not invented
    assert "C99999" not in found["titles"]


def test_a_type_named_by_its_key_resolves_nothing_and_says_so(db, graph):
    from aughor.semantic.object_instances import titles

    found = titles(graph, db, "order", ["O000123"])

    assert found["titles"] == {} and found["property"] == "order_id"
    assert "named by its key" in found["note"]   # the key is already on screen; a title would repeat it


def test_titling_repeats_no_key_caps_the_batch_and_never_splices_one(db, graph):
    from aughor.semantic.object_instances import MAX_TITLES, titles

    over = titles(graph, db, "customer", [f"C{n:05d}" for n in range(MAX_TITLES + 10)])
    assert over["truncated"] is True

    quoted = titles(graph, db, "customer", ["x' OR '1'='1", "C00042", "C00042"])
    assert set(quoted["titles"]) == {"C00042"}   # the injection matched nothing; the repeat asked once


def test_a_name_on_a_static_binding_titles_the_object_and_the_batch_reads_it_through_the_binding(db, graph):
    """ON-1b let a property live on a bound source; naming an object by one was the leftover. The binding joins
    on the OBJECT's key, so its name is as single-valued as a column of the backing."""
    from aughor.ontology.models import Binding, DisplayProperty, EntityProperty
    from aughor.semantic.object_instances import titles

    product = graph.entities["Product"]
    product.bindings = [Binding(name="naming", kind="static", table="products", key="product_id",
                                properties={"label": EntityProperty(name="label", data_type="VARCHAR")},
                                columns={"label": "product_name"}, verified=True, note="one row per Product")]
    product.display_property = DisplayProperty(name="label", source="human")

    reference = {str(r[0]): str(r[1]) for r in db.execute(
        "reference", "SELECT product_id, product_name FROM products ORDER BY product_id LIMIT 3").rows}
    found = titles(graph, db, "product", list(reference))
    assert found["titles"] == reference and found["through"] == "naming"

    one = next(iter(reference))
    assert get_object(graph, db, "product", one).title == reference[one]


def test_a_display_property_is_measured_over_the_binding_that_supplies_it(db, graph):
    from aughor.ontology.display import display_source, measure_display
    from aughor.ontology.models import Binding, EntityProperty

    product = graph.entities["Product"]
    product.bindings = [Binding(name="naming", kind="static", table="products", key="product_id",
                                properties={"label": EntityProperty(name="label", data_type="VARCHAR")},
                                columns={"label": "product_name"}, verified=True, note="one row per Product")]

    from_clause, column, through = display_source(product, "label")
    assert through == "naming" and column == "product_name" and "products" in from_clause

    measured = measure_display(db, product, "label", source="human")
    rows, non_null, distinct = _one(db, "SELECT COUNT(*), COUNT(product_name), COUNT(DISTINCT product_name) "
                                       "FROM products")
    assert [measured.rows, measured.non_null, measured.distinct] == [int(rows), int(non_null), int(distinct)]
    assert "read through the naming binding" in measured.note


def test_an_unmeasured_binding_does_not_get_to_name_anything(db, graph):
    """The one law for reading a binding holds for titles too: an uncounted binding is never joined, so its
    column cannot become a name through the back door."""
    from aughor.ontology.display import display_source
    from aughor.ontology.models import Binding, EntityProperty

    product = graph.entities["Product"]
    product.bindings = [Binding(name="unmeasured", kind="static", table="products", key="product_id",
                                properties={"label": EntityProperty(name="label", data_type="VARCHAR")},
                                columns={"label": "product_name"})]                       # verified is None

    from_clause, column, through = display_source(product, "label")
    assert through == "" and column == "label"          # falls back to the backing, where there is no such column
