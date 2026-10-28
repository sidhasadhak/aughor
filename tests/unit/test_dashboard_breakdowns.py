"""A breakdown on a dashboard (the Grist study §10).

The piece is drawn by the web; the server compiles a breakdown's query with the other pieces', so a property the
ontology does not hold is refused at the keep, not discovered by a reader.
"""
from __future__ import annotations

from aughor.dashboards import pieces

BREAKDOWN = {"type": "ObjectBreakdown", "children": [], "props": {
    "entity": "order", "label": "Orders by country", "by": "placed_by.country",
    "measures": [{"agg": "count"}, {"agg": "sum", "path": "revenue", "format": "money"}]}}


def test_a_breakdown_is_named_and_probed_as_the_door_will_be_asked():
    assert pieces.title_of("ObjectBreakdown", BREAKDOWN["props"]) == "Breakdown · Orders by country"
    [(what, body)] = pieces._from_object_probes("ObjectBreakdown", BREAKDOWN["props"])
    assert what == "it"
    assert body == {"object_type": "order", "by": ["placed_by.country"], "measures": [
        {"name": "m0", "agg": "count", "path": ""}, {"name": "m1", "agg": "sum", "path": "revenue"}]}
    assert "ObjectBreakdown" in pieces.PIECES and "ObjectBreakdown" in pieces.FROM_OBJECT
