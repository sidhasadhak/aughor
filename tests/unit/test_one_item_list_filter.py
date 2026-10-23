"""A comparison given a one-item list reads that value (the Olist study, Gap 12, 2026-10-22).

The model drafted `delivered_orders: order_status = ['delivered']` and the door refused it with "filter
'order_status =' needs one value (is_null / not_null for NULL, in for a list)" — the most useful rule of the
run (96,478 delivered orders) gone, and a parser's sentence in its place. A one-item list is unambiguous, so
it is read; a longer one, or none, is refused in words that say what to write instead.
"""
import pytest

from aughor.ontology.models import EntityProperty
from aughor.semantic.object_query import ObjectFilter, ObjectQueryRefused, _predicate

STATUS = EntityProperty(name="order_status", data_type="VARCHAR", semantic_type="dimension")


@pytest.mark.parametrize("f", [ObjectFilter(path="order_status", op="=", value=["delivered"]),
                               ObjectFilter(path="order_status", op="=", values=["delivered"])])
def test_a_one_item_list_is_its_value(f):
    assert _predicate("o.order_status", STATUS, f) == "o.order_status = 'delivered'"


def test_a_longer_list_is_refused_with_what_to_write_instead():
    with pytest.raises(ObjectQueryRefused, match="compares with one value and was given 2; to match any of them, "
                                                 "use 'order_status in' with the list"):
        _predicate("o.order_status", STATUS, ObjectFilter(path="order_status", op="=", value=["delivered", "shipped"]))


def test_no_value_is_refused_with_the_null_door_named():
    with pytest.raises(ObjectQueryRefused, match="needs a value to compare with; to match an empty order_status, "
                                                 "use 'order_status is_null'"):
        _predicate("o.order_status", STATUS, ObjectFilter(path="order_status", op="!="))
