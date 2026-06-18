"""Human ontology overrides — override-wins, survive-rebuild, and authority reach.

Locks the behaviours proven during the nao-inspired editable-ontology work:
  1. apply_overrides honours the verified gate (bound SQL → verified; unbound → not).
  2. A bound override SURVIVES a schema-fingerprint change (the drift that used to
     wipe edits on every data refresh).
  3. The metrics catalog ADDITIVELY injects a verified human metric (the wiring
     bug where a brand-new metric override silently never reached the prompt).
"""
from __future__ import annotations

import pytest

from aughor.ontology.models import OntologyEntity, OntologyGraph, OntologyMetric
from aughor.ontology import overrides as OV


def _graph() -> OntologyGraph:
    g = OntologyGraph(connection_id="c", schema_name="s", schema_fingerprint="fp1")
    g.entities["OrderItem"] = OntologyEntity(
        id="OrderItem", display_name="Order Line", source_tables=["order_items"],
        identity_key="item_id", grain_verified=True,
    )
    return g


@pytest.fixture(autouse=True)
def _isolated_root(tmp_path, monkeypatch):
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")


def test_verified_gate_bound_vs_unbound():
    ov_ok = OV.OntologyOverride(
        target_kind="computed_property", target_id="OrderItem::rev",
        fields={"label": "Rev", "formula_sql": "SUM(line_total)"},
        binding={"formula_sql": {"bound": True, "note": ""}})
    ov_bad = OV.OntologyOverride(
        target_kind="computed_property", target_id="OrderItem::bad",
        fields={"label": "Bad", "formula_sql": "SUM(nope)"},
        binding={"formula_sql": {"bound": False, "note": "no col"}})
    OV.save_override("c", "s", ov_ok)
    OV.save_override("c", "s", ov_bad)

    g, report = OV.apply_overrides(_graph(), "c", "s")
    cps = {c.id: c for c in g.entities["OrderItem"].computed_properties}
    assert cps["rev"].verified is True and cps["rev"].verification_note == "human-asserted"
    assert cps["bad"].verified is False          # unbound SQL never earns authority
    assert "no col" in cps["bad"].verification_note
    assert len(report.applied) == 2


def test_yaml_roundtrip():
    ov = OV.OntologyOverride(
        target_kind="metric", target_id="category_revenue",
        fields={"entity": "OrderItem", "formula_sql": "SUM(line_total)"},
        binding={"formula_sql": {"bound": True, "note": ""}})
    OV.save_override("c", "s", ov)
    loaded = OV.load_overrides("c", "s")
    assert len(loaded) == 1
    assert loaded[0].target_id == "category_revenue"
    assert loaded[0].fields["formula_sql"] == "SUM(line_total)"


def test_override_survives_fingerprint_rebuild(tmp_path, monkeypatch):
    """A data refresh re-fingerprints and rebuilds; the override must still apply."""
    from aughor.util.json_store import KeyedJsonStore
    from aughor.ontology import store as ST
    monkeypatch.setattr(ST, "_store", KeyedJsonStore(tmp_path / "onto_cache.json", max_entries=20))

    base = _graph()
    ST.save_ontology("c", "s", "fp1", base)
    ov = OV.OntologyOverride(
        target_kind="computed_property", target_id="OrderItem::rev",
        fields={"label": "Rev", "formula_sql": "SUM(line_total)"},
        binding={"formula_sql": {"bound": True, "note": ""}})
    OV.save_override("c", "s", ov)

    # present under the original fingerprint
    g1 = ST.load_latest_ontology("c", "s")
    assert any(c.id == "rev" and c.verified for c in g1.entities["OrderItem"].computed_properties)

    # simulate a data refresh: new fingerprint, fresh structural graph (no edit baked in)
    base2 = _graph()
    base2.schema_fingerprint = "fp2_after_refresh"
    ST.save_ontology("c", "s", "fp2_after_refresh", base2)

    g2 = ST.load_latest_ontology("c", "s")
    survivors = [c for c in g2.entities["OrderItem"].computed_properties if c.id == "rev"]
    assert survivors and survivors[0].verified, "override LOST on fingerprint rebuild"


def test_additive_metric_overlay_injects_human_metric(monkeypatch):
    """A verified ontology metric with no catalog counterpart renders; unverified doesn't."""
    from aughor.semantic import metrics as M

    g = OntologyGraph(connection_id="c", schema_name="s", schema_fingerprint="fp", validated=True)
    g.metrics["category_revenue"] = OntologyMetric(
        id="category_revenue", display_name="Category Revenue", entity="OrderItem",
        formula_sql="SUM(line_total)", unit="USD", verified=True,
        verification_note="human-asserted")
    g.metrics["unverified_thing"] = OntologyMetric(
        id="unverified_thing", display_name="Unverified Thing", entity="OrderItem",
        formula_sql="SUM(bogus)", verified=False)

    monkeypatch.setattr(M, "load_latest_ontology", lambda *_a, **_k: g, raising=False)
    # also patch the name the function imports at call time
    import aughor.ontology.store as ST
    monkeypatch.setattr(ST, "load_latest_ontology", lambda *_a, **_k: g)

    block = M.build_metrics_block(schema_text="", connection_id="c")
    assert "CATEGORY_REVENUE" in block.upper()
    assert "SUM(line_total)" in block
    assert "Human-curated" in block
    assert "UNVERIFIED_THING" not in block.upper()  # verified gate holds for additive too
