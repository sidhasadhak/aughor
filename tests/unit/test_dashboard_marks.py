"""Rows marked by a declared rule (the Grist study §10).

A table's or a list's ``marked`` names a segment the ontology declares and a tone; the web marks the rows it admits and
says how many. The server compiles each mark's count over the served ontology, so a segment the entity does not
declare is refused at the keep.
"""
from __future__ import annotations

import pytest

from aughor.dashboards import marks as M
from aughor.dashboards import pieces
from aughor.dashboards.compose import default_spec
from tests.unit.test_dashboard_pieces import _graph


def _spec(marked: dict | None) -> dict:
    """A new dashboard's own root, as one starts, holding a section with one objects table."""
    props = {"entity": "order", **({"marked": marked} if marked is not None else {})}
    spec = default_spec("Desk", [])
    spec["elements"][spec["root"]]["children"] = ["s"]
    spec["elements"].update({"s": {"type": "Section", "props": {"title": "Orders"}, "children": ["t"]},
                             "t": {"type": "ObjectTable", "props": props, "children": []}})
    return spec


def test_a_mark_counts_its_rows_through_the_door_as_a_set_of_the_entity():
    [(what, body)] = M.probes({"marked": {"segment": "overdue_dispatch", "tone": "bad"}}, "order",
                              {"filters": [{"path": "status", "op": "=", "value": "Shipped"}]})
    assert what == 'its mark "overdue_dispatch"'
    assert body == {"object_type": "order", "measures": [{"name": "n", "agg": "count"}], "filters": [
        {"path": "status", "op": "=", "value": "Shipped"},
        {"path": "", "op": "in_set", "sets": [{"entity": "order", "segment": "overdue_dispatch"}]}]}


@pytest.fixture
def no_edits(monkeypatch):
    monkeypatch.setattr(pieces, "accepted_edits", lambda conn: [])


def test_a_mark_naming_a_segment_the_entity_declares_keeps_and_one_it_does_not_is_refused(monkeypatch, no_edits):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: False)
    # `delivered_orders` is a verified segment the test graph declares on orders
    assert pieces.not_resolved("c", _spec({"segment": "delivered_orders", "tone": "good"}), graph=_graph()) == []
    said = pieces.not_resolved("c", _spec({"segment": "no_such_rule", "tone": "warn"}), graph=_graph())
    assert len(said) == 1 and said[0].startswith('The objects table "t" cannot be read — its mark "no_such_rule":')
