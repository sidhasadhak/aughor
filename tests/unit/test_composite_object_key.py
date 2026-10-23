"""An object's key may be several columns together (the Olist study, Gap 13, 2026-10-22).

Order lines are keyed by (order_id, order_item_id), payments by (order_id, payment_sequential), reviews by
(review_id, order_id) — and the key door offered one column, so all three carried "not unique per row" for
good. A key of several columns is read through a backing that adds ONE key column built from them, so every
reader of a key keeps reading one column; it is measured over the rows like any backing.
"""
from types import SimpleNamespace

import duckdb
import pytest
from fastapi import HTTPException

from aughor.routers import ontology as R

TABLE = "olist.olist_order_items_dataset"


def test_one_column_reads_the_table_itself_and_several_read_one_built_key():
    assert R.composite_key_backing("order_line", TABLE, ["order_id"]) == {
        "kind": "table", "table": TABLE, "primary_key": "order_id"}
    b = R.composite_key_backing("order_line", TABLE, ["order_id", "order_item_id"])
    assert b["kind"] == "query" and b["primary_key"] == "order_line_key"
    assert b["sql"] == ("SELECT *, CONCAT_WS('|', CAST(order_id AS VARCHAR), CAST(order_item_id AS VARCHAR)) "
                        "AS order_line_key FROM olist.olist_order_items_dataset")


def test_the_pair_is_unique_where_one_column_is_not():
    """Measured the way the backing probe measures a key: rows, non-null keys, distinct keys."""
    c = duckdb.connect()
    c.execute("CREATE SCHEMA olist")
    c.execute("CREATE TABLE olist.olist_order_items_dataset AS SELECT * FROM (VALUES "
              "('o1', 1, 10.0), ('o1', 2, 5.0), ('o2', 1, 7.0)) t(order_id, order_item_id, price)")
    one = c.execute(f"SELECT COUNT(*), COUNT(DISTINCT order_id) FROM {TABLE}").fetchone()
    assert one == (3, 2)                                                    # one column repeats
    b = R.composite_key_backing("order_line", TABLE, ["order_id", "order_item_id"])
    rows, distinct = c.execute(f"SELECT COUNT(*), COUNT(DISTINCT order_line_key) FROM ({b['sql']})").fetchone()
    assert rows == distinct == 3                                            # the pair names one line each
    assert c.execute(f"SELECT price FROM ({b['sql']}) WHERE order_line_key = 'o1|2'").fetchone() == (5.0,)
    c.close()


@pytest.fixture
def graph(monkeypatch):
    entity = SimpleNamespace(backing=None, source_tables=[TABLE],
                             properties={"order_id": object(), "order_item_id": object(), "price": object()})
    monkeypatch.setattr(R, "_get_ontology_graph", lambda conn, scope: SimpleNamespace(entities={"order_line": entity}))
    monkeypatch.setattr(R, "_served_scope", lambda conn, schema: schema or "")
    sent = {}
    monkeypatch.setattr(R, "override_ontology_entity", lambda eid, body, conn, schema: sent.update(
        eid=eid, backing=body.backing.model_dump()) or {"ok": True})
    return sent


def test_the_door_writes_the_backing_through_the_override(graph):
    assert R.set_ontology_entity_key("order_line", R._EntityKey(columns=["order_id", " order_item_id", "order_id"]),
                                     "workspace", "olist") == {"ok": True}
    assert graph["eid"] == "order_line" and graph["backing"]["primary_key"] == "order_line_key"


@pytest.mark.parametrize("columns, code, said", [
    ([], 422, "name the column, or the columns together"),
    (["order_id", "seller_id"], 422, "order_line has no seller_id"),
    (["order id; drop"], 422, "not a column name"),
])
def test_the_door_refuses_what_is_not_a_key_of_this_type(graph, columns, code, said):
    with pytest.raises(HTTPException) as refused:
        R.set_ontology_entity_key("order_line", R._EntityKey(columns=columns), "workspace", "olist")
    assert refused.value.status_code == code and said in str(refused.value.detail)
