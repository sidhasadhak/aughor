"""Self-improving loop — detector precision, recurrence/dismiss, and accept->override.

Locks the behaviours proven during the loop's empirical close:
  1. observe() proposes ONLY an uncovered, currency, non-per_unit, single-column
     measure (the genuine gap) and nothing else.
  2. recurrence bumps support (ripeness); a dismissed rec is never resurrected.
  3. accept() promotes a recommendation into a bound metric override.
"""
from __future__ import annotations

import pytest

from aughor.ontology.models import EntityProperty, OntologyEntity, OntologyGraph, OntologyMetric
from aughor.ontology import recommendations as REC
from aughor.ontology import overrides as OV


def _measure(name, grain=""):
    return EntityProperty(name=name, semantic_type="measure",
                          value_interpretation="currency amount", unit="USD", measure_grain=grain)


def _graph() -> OntologyGraph:
    g = OntologyGraph(connection_id="c", schema_name="s", schema_fingerprint="fp", validated=True)
    oi = OntologyEntity(id="OrderItem", display_name="Order Line", source_tables=["order_items"],
                        identity_key="item_id", grain_verified=True)
    oi.properties = {"line_total": _measure("line_total", "per_line"),
                     "unit_price": _measure("unit_price", "per_unit"),
                     "quantity": EntityProperty(name="quantity", semantic_type="measure",
                                                value_interpretation="count", unit="count")}
    o = OntologyEntity(id="Order", display_name="Order", source_tables=["orders"],
                       identity_key="order_id", grain_verified=True)
    o.properties = {"total_amount": _measure("total_amount", "per_unit")}
    g.entities = {"OrderItem": oi, "Order": o}
    # Order.total_amount IS covered by a canonical metric.
    g.metrics = {"revenue": OntologyMetric(id="revenue", display_name="Revenue", entity="Order",
                                           formula_sql="SUM(total_amount)", verified=True)}
    return g


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(REC, "_ROOT", tmp_path / "recs")
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "overrides")


def test_detector_precision():
    g = _graph()
    # uncovered per_line currency measure -> proposed
    assert REC.observe("c", "s", "rev by cat", "SELECT category, SUM(line_total) FROM order_items GROUP BY 1", g)
    # covered measure -> NOT proposed
    assert not REC.observe("c", "s", "rev", "SELECT SUM(total_amount) FROM orders", g)
    # per_unit measure -> NOT proposed (SUM without ×qty is wrong)
    assert not REC.observe("c", "s", "x", "SELECT SUM(unit_price) FROM order_items", g)

    recs = REC.load_recommendations("c", "s")
    assert len(recs) == 1
    r = recs[0]
    assert r.id == "metric__orderitem__line_total"
    # the PROPOSED formula is always the pre-computed column, never the re-derivation
    assert r.proposed_fields["formula_sql"] == "SUM(line_total)"
    assert r.entity == "OrderItem"


def test_rederivation_counts_as_evidence():
    """v2: SUM(quantity*unit_price) is the model's mistake — it must NOT be proposed
    verbatim, but it SHOULD reinforce the pre-computed line_total metric proposal."""
    g = _graph()
    # direct usage once, then two re-derivations -> all three reinforce ONE rec
    REC.observe("c", "s", "q1", "SELECT category, SUM(line_total) FROM order_items GROUP BY 1", g)
    REC.observe("c", "s", "q2", "SELECT category, SUM(quantity * unit_price) FROM order_items oi GROUP BY 1", g)
    REC.observe("c", "s", "q3", "SELECT p.category, SUM(oi.quantity * oi.unit_price) FROM order_items oi GROUP BY 1", g)

    recs = REC.load_recommendations("c", "s")
    assert len(recs) == 1                                   # never proposes quantity*unit_price
    r = recs[0]
    assert r.proposed_fields["formula_sql"] == "SUM(line_total)"
    assert r.support == 3 and r.ripe is True               # mistakes turned into signal
    assert any("re-derived" in e["question"] for e in r.evidence)


def test_recurrence_and_dismiss():
    g = _graph()
    sql = "SELECT category, SUM(line_total) FROM order_items GROUP BY 1"
    REC.observe("c", "s", "q1", sql, g)
    REC.observe("c", "s", "q2", sql, g)
    r = REC.get_recommendation("c", "s", "metric__orderitem__line_total")
    assert r.support == 2 and r.ripe is True          # ripe once seen twice
    assert len(r.evidence) == 2                         # distinct questions captured

    # dismiss -> the loop must not resurrect it
    r.status = "dismissed"
    REC.save_recommendation("c", "s", r)
    REC.observe("c", "s", "q3", sql, g)
    assert REC.get_recommendation("c", "s", r.id).status == "dismissed"


def test_accept_creates_bound_override():
    g = _graph()
    REC.observe("c", "s", "rev by cat", "SELECT category, SUM(line_total) FROM order_items GROUP BY 1", g)
    res = REC.accept("c", "s", "metric__orderitem__line_total", g, explain=lambda _sql: None)
    assert res is not None and res["bound"] is True

    ovs = OV.load_overrides("c", "s")
    assert len(ovs) == 1
    ov = ovs[0]
    assert ov.target_kind == "metric"
    assert ov.fields["formula_sql"] == "SUM(line_total)"
    assert ov.binding["formula_sql"]["bound"] is True
    # the recommendation is now marked accepted
    assert REC.get_recommendation("c", "s", "metric__orderitem__line_total").status == "accepted"
