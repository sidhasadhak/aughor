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
