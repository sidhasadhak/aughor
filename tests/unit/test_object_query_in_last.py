"""Arc AP-2 — the object door's relative condition: `in_last` keeps the objects whose date or time falls in the last N
days, today (UTC) included, resolved to a date where the query is compiled (docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md
§4.3: "One addition the door needs"). A cockpit's set "placed in the last 14 days" reads the same fortnight for every
reader today, and a different one tomorrow — never a date frozen into the kept cockpit.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from aughor.ontology.models import OntologyGraph
from aughor.semantic import object_query as oq
from tests.unit.test_object_bindings import GRAPH


@pytest.fixture
def graph() -> OntologyGraph:
    return OntologyGraph.model_validate(json.loads(GRAPH.read_text()))


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(oq, "_today_utc", lambda: date(2026, 10, 11))


def _count(graph, *filters):
    return oq.compile_object_query({"object_type": "Order", "measures": [{"name": "n", "agg": "count"}],
                                    "filters": list(filters)}, graph)


def test_the_last_n_days_are_today_and_the_days_before_it(graph):
    assert "t0.order_date >= '2026-09-28'" in _count(graph, {"path": "order_date", "op": "in_last", "value": 14}).sql
    assert "t0.order_date >= '2026-10-11'" in _count(graph, {"path": "order_date", "op": "in_last", "value": 1}).sql
    assert "t0.order_date >= '2026-09-28'" in _count(graph, {"path": "order_date", "op": "in_last", "value": "14"}).sql


def test_it_is_read_again_each_day_never_frozen(graph, monkeypatch):
    monkeypatch.setattr(oq, "_today_utc", lambda: date(2026, 10, 12))
    assert "t0.order_date >= '2026-09-29'" in _count(graph, {"path": "order_date", "op": "in_last", "value": 14}).sql


@pytest.mark.parametrize("value,says", [
    (0, "takes 1 to"), (oq.MAX_IN_LAST_DAYS + 1, "takes 1 to"), ("fourteen", "whole number"), (True, "whole number"),
    (None, "whole number"), (2.5, "whole number"), ([14], "whole number"),
])
def test_anything_but_a_whole_number_of_days_is_refused(graph, value, says):
    with pytest.raises(oq.ObjectQueryRefused) as refused:
        _count(graph, {"path": "order_date", "op": "in_last", "value": value})
    assert says in refused.value.reason


def test_a_property_that_is_not_a_date_or_a_time_is_refused(graph):
    with pytest.raises(oq.ObjectQueryRefused) as refused:
        _count(graph, {"path": "status", "op": "in_last", "value": 7})
    assert "reads a date or a time" in refused.value.reason


def test_a_listing_keeps_the_same_days(graph):
    listing = oq.compile_object_listing({"entity": "Order", "limit": 5,
                                         "filters": [{"path": "order_date", "op": "in_last", "value": 7}]}, graph)
    assert "t0.order_date >= '2026-10-05'" in listing.sql
