"""The date a metric is proposed with is the business event its rows belong to (the Olist study, Gap 21).

Olist's GMV reads order lines JOIN orders. The first table's main date — `shipping_limit_date`, a shipping
deadline — was proposed first and saved as GMV's date, so a person who approved without opening Dates got
monthly GMV by shipping deadline. Two rules now: the table another statement table's key NAMES leads (order
lines carry `order_id`, which names orders), and within a table the date that says the record was MADE
(`order_purchase_timestamp`) leads the profiler's main one (`order_approved_at`). Table names are matched past
the prefix and suffix every table shares (`olist_<what>_dataset`).
"""
from aughor.semantic import metric_statement as MS

COLS = {
    "olist_order_items_dataset": {"order_id": "VARCHAR", "price": "DOUBLE", "shipping_limit_date": "TIMESTAMP"},
    "olist_orders_dataset": {"order_id": "VARCHAR", "order_status": "VARCHAR", "order_approved_at": "TIMESTAMP",
                             "order_purchase_timestamp": "TIMESTAMP", "order_delivered_customer_date": "TIMESTAMP"},
    "olist_customers_dataset": {"customer_id": "VARCHAR", "customer_state": "VARCHAR"},
}
PROFILE = {
    "tables": {"olist_order_items_dataset": {"primary_timestamp": "shipping_limit_date"},
               "olist_orders_dataset": {"primary_timestamp": "order_approved_at"}},
    "columns": {f"{t}.{c}": {"table": t, "column": c, "dtype": d} for t, cols in COLS.items() for c, d in cols.items()},
}
GMV = ("SELECT SUM(oi.price) AS gmv FROM olist.olist_order_items_dataset oi JOIN olist.olist_orders_dataset o "
       "ON o.order_id = oi.order_id")


def test_gmv_is_proposed_by_the_orders_purchase_date():
    grains = [c["grain"] for c in MS.date_candidates(GMV, [], PROFILE)]
    assert grains[0] == "olist.olist_orders_dataset.order_purchase_timestamp", grains
    assert grains.index("olist.olist_order_items_dataset.shipping_limit_date") > grains.index(
        "olist.olist_orders_dataset.order_approved_at")                  # the child's deadline comes last


def test_shared_affixes_are_looked_past_and_unshared_names_kept():
    cores = MS._core_names(list(COLS))
    assert cores == {"olist_customers_dataset": "customers", "olist_order_items_dataset": "order_items",
                     "olist_orders_dataset": "orders"}
    assert MS._core_names(["orders", "order_items"]) == {"order_items": "order_items", "orders": "orders"}
    assert MS._named_by_keys(["olist.olist_order_items_dataset", "olist.olist_orders_dataset"], PROFILE) == {
        "olist_orders_dataset"}


def test_a_date_one_join_away_is_found_through_olist_names():
    """`order_items` alone has only a shipping deadline; the order's dates are one key away."""
    away = MS.dates_one_join_away("SELECT SUM(price) FROM olist.olist_order_items_dataset", [], PROFILE)
    assert {a["column"] for a in away} >= {"order_purchase_timestamp"} and all(a["via"] == "order_id" for a in away)
