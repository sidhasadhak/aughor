"""A breakdown on a dashboard (the Grist study §10; flag ``dashboard.breakdowns``, off).

The piece is drawn by the web; the server holds a kept spec to the flag — a dashboard holding one is refused while
breakdowns are off, and every other dashboard keeps as it did — and compiles a breakdown's query with the other
pieces', so a property the ontology does not hold is refused at the keep, not discovered by a reader.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aughor.dashboards import breakdowns as B
from aughor.dashboards import pieces
from aughor.dashboards.compose import default_spec
from aughor.kernel.flags import flag_overrides

BREAKDOWN = {"type": "ObjectBreakdown", "children": [], "props": {
    "entity": "order", "label": "Orders by country", "by": "placed_by.country",
    "measures": [{"agg": "count"}, {"agg": "sum", "path": "revenue", "format": "money"}]}}


def _with_breakdown(spec: dict, key: str = "by-country") -> dict:
    s = {**spec, "elements": dict(spec["elements"])}
    section = next(k for k, el in s["elements"].items() if el.get("type") == "Section")
    s["elements"][section] = {**s["elements"][section], "children": [*s["elements"][section]["children"], key]}
    s["elements"][key] = BREAKDOWN
    return s


def test_off_a_spec_holding_a_breakdown_is_refused_and_any_other_is_not():
    bare = default_spec("Desk", [])   # a new dashboard's own root, as one starts
    spec = default_spec("Desk", [])
    spec["elements"][spec["root"]]["children"] = ["s"]
    spec["elements"].update({"s": {"type": "Section", "props": {}, "children": ["b"]}, "b": BREAKDOWN})
    with flag_overrides({"dashboard.breakdowns": False}):
        assert B.held(spec) == ["b"]
        assert B.refused_off(spec) == ["The dashboard holds a breakdown — b — and breakdowns are off on this install."]
        assert B.refused_off(bare) == []
    with flag_overrides({"dashboard.breakdowns": True}):
        assert B.refused_off(spec) == []


def test_a_breakdown_is_named_and_probed_as_the_door_will_be_asked():
    assert pieces.title_of("ObjectBreakdown", BREAKDOWN["props"]) == "Breakdown · Orders by country"
    [(what, body)] = pieces._from_object_probes("ObjectBreakdown", BREAKDOWN["props"])
    assert what == "it"
    assert body == {"object_type": "order", "by": ["placed_by.country"], "measures": [
        {"name": "m0", "agg": "count", "path": ""}, {"name": "m1", "agg": "sum", "path": "revenue"}]}
    assert "ObjectBreakdown" in pieces.PIECES and "ObjectBreakdown" in pieces.FROM_OBJECT


@pytest.fixture(scope="module")
def client():
    from aughor.api import app
    return TestClient(app)


from tests.unit.test_dashboard_routes import Desk, needs_rules  # noqa: E402 — the route tests' own dashboard-to-be


@needs_rules
def test_a_dashboard_holding_a_breakdown_is_refused_at_the_keep_while_breakdowns_are_off(client):
    desk = Desk()
    with flag_overrides({"dashboard.composed": True, "dashboard.breakdowns": False}):
        r = client.put(desk.path, params=desk.q, json={"spec": _with_breakdown(desk.spec)})
    assert r.status_code != 200 and "breakdowns are off on this install" in r.text
