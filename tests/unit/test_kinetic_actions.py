"""Wave K1 — declared KineticActions overlaid onto the ontology graph.

The K1 substrate: a human declares a governed action in the per-connection ontology overlay
(one YAML file per action, `target_kind: action`), and it is overlaid onto the graph at read
time — flag-gated, surviving rebuilds, malformed specs rejected at parse (never at execute), and
the authored submission-criterion failure message preserved byte-for-byte. Nothing executes here
(that is the K2 executor). Hermetic: an isolated override root + the flag forced per test.
"""
from __future__ import annotations

import pytest

from aughor.ontology import overrides as OV
from aughor.ontology.models import (
    KineticAction,
    OntologyEntity,
    OntologyGraph,
    SideEffect,
    SubmissionCriterion,
)
import aughor.kernel.flags as flags


def _graph() -> OntologyGraph:
    g = OntologyGraph(connection_id="c", schema_name="s", schema_fingerprint="fp1")
    g.entities["Order"] = OntologyEntity(
        id="Order", display_name="Order", source_tables=["orders"], identity_key="order_id",
        grain_verified=True,
    )
    return g


# One realistic declared action: refund an order, capped, notifying on completion.
_MESSAGE = "Refunds above €10,000 need finance sign-off — route to the approvals queue instead."
_ACTION_FIELDS = {
    "display_name": "Refund order",
    "description": "Issue a refund for an order.",
    "entity": "Order",
    "kind": "side_effect",
    "params": [
        {"name": "order_id", "data_type": "VARCHAR", "required": True},
        {"name": "amount_eur", "data_type": "NUMERIC", "required": True},
    ],
    "submission_criteria": [{"expr": "amount_eur <= 10000", "message": _MESSAGE}],
    "side_effects": [{"kind": "trigger_investigation", "config": {"reason": "refund"}}],
    "risk": "high",
}


def _save_action(target_id: str, fields: dict) -> None:
    OV.save_override("c", "s", OV.OntologyOverride(
        target_kind="action", target_id=target_id, fields=fields))


@pytest.fixture(autouse=True)
def _isolated_root(tmp_path, monkeypatch):
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")


@pytest.fixture
def _flag_on(monkeypatch):
    monkeypatch.setattr(flags, "flag_enabled", lambda name: name == "kinetic.actions")


# ── the decision gate ────────────────────────────────────────────────────────────

def test_declared_action_round_trips_yaml_to_graph(_flag_on):
    _save_action("refund_order", _ACTION_FIELDS)
    g, report = OV.apply_overrides(_graph(), "c", "s")

    assert "refund_order" in g.kinetic_actions
    a = g.kinetic_actions["refund_order"]
    assert a.id == "refund_order" and a.kind == "side_effect" and a.risk == "high"
    assert [p.name for p in a.params] == ["order_id", "amount_eur"]
    assert a.side_effects[0].kind == "trigger_investigation"
    assert report.count == 1
    # the read-side actions dict is untouched — the two "action" concepts never collide
    assert g.actions == {}


def test_authored_failure_message_is_preserved_byte_for_byte(_flag_on):
    _save_action("refund_order", _ACTION_FIELDS)
    g, _ = OV.apply_overrides(_graph(), "c", "s")
    assert g.kinetic_actions["refund_order"].submission_criteria[0].message == _MESSAGE


def test_graph_dump_reload_preserves_the_message(_flag_on):
    # The graph is JSON-cached; a declared action must survive model_dump → model_validate
    # unchanged (the API and the cache both round-trip through this).
    _save_action("refund_order", _ACTION_FIELDS)
    g, _ = OV.apply_overrides(_graph(), "c", "s")
    reloaded = OntologyGraph.model_validate(g.model_dump())
    assert reloaded.kinetic_actions["refund_order"].submission_criteria[0].message == _MESSAGE


def test_malformed_criterion_is_rejected_at_parse_not_execute(_flag_on):
    bad = dict(_ACTION_FIELDS,
               submission_criteria=[{"expr": "amount_eur <= 10000"}])  # NO authored message
    _save_action("bad_refund", bad)
    g, report = OV.apply_overrides(_graph(), "c", "s")

    assert "bad_refund" not in g.kinetic_actions           # never entered the graph
    assert any("bad_refund" in s for s in report.skipped)  # rejected at overlay, with a reason


def test_empty_criterion_message_is_rejected(_flag_on):
    bad = dict(_ACTION_FIELDS, submission_criteria=[{"expr": "x", "message": ""}])
    _save_action("blank_msg", bad)
    g, _ = OV.apply_overrides(_graph(), "c", "s")
    assert "blank_msg" not in g.kinetic_actions


def test_invalid_kind_is_rejected(_flag_on):
    _save_action("weird", dict(_ACTION_FIELDS, kind="mutate"))   # not annotate|side_effect|query
    g, _ = OV.apply_overrides(_graph(), "c", "s")
    assert "weird" not in g.kinetic_actions


# ── the flag gate: off = byte-identical ──────────────────────────────────────────

def test_flag_off_leaves_kinetic_actions_empty(monkeypatch):
    monkeypatch.setattr(flags, "flag_enabled", lambda name: False)
    _save_action("refund_order", _ACTION_FIELDS)
    g, report = OV.apply_overrides(_graph(), "c", "s")
    assert g.kinetic_actions == {}
    assert any("kinetic.actions off" in s for s in report.skipped)


def test_flag_off_does_not_disturb_other_overrides(monkeypatch):
    # A declared action with the flag off must not break a co-located metric override.
    monkeypatch.setattr(flags, "flag_enabled", lambda name: False)
    _save_action("refund_order", _ACTION_FIELDS)
    OV.save_override("c", "s", OV.OntologyOverride(
        target_kind="metric", target_id="gmv",
        fields={"entity": "Order", "display_name": "GMV"}))
    g, report = OV.apply_overrides(_graph(), "c", "s")
    assert "gmv" in g.metrics and g.kinetic_actions == {}


# ── persistence + survives rebuild ───────────────────────────────────────────────

def test_yaml_file_roundtrip_persists_the_spec():
    _save_action("refund_order", _ACTION_FIELDS)
    loaded = OV.load_overrides("c", "s")
    assert len(loaded) == 1 and loaded[0].target_kind == "action"
    assert loaded[0].fields["submission_criteria"][0]["message"] == _MESSAGE


def test_declared_action_survives_a_fresh_graph(_flag_on):
    # Overrides exist to survive fingerprint rebuilds — applying onto a brand-new graph
    # (different fingerprint) still yields the action.
    _save_action("refund_order", _ACTION_FIELDS)
    g2 = OntologyGraph(connection_id="c", schema_name="s", schema_fingerprint="fp2-REBUILT")
    g2, _ = OV.apply_overrides(g2, "c", "s")
    assert "refund_order" in g2.kinetic_actions


# ── model-level validation (defensive) ───────────────────────────────────────────

def test_kineticaction_defaults_risk_high():
    a = KineticAction(id="a", kind="annotate")
    assert a.risk == "high" and a.origin == "manual"       # fail-safe defaults


def test_submission_criterion_requires_message():
    with pytest.raises(Exception):
        SubmissionCriterion(expr="x <= 1")                 # missing message
    with pytest.raises(Exception):
        SubmissionCriterion(expr="", message="m")          # empty expr


def test_side_effect_kind_is_constrained():
    SideEffect(kind="webhook", config={"url": "https://x"})  # ok
    with pytest.raises(Exception):
        SideEffect(kind="delete_rows")                       # not a declared side-effect kind


# ── the read-only API surface ────────────────────────────────────────────────────

def test_api_returns_declared_actions(_flag_on, monkeypatch):
    from aughor.routers import ontology as R
    _save_action("refund_order", _ACTION_FIELDS)
    g, _ = OV.apply_overrides(_graph(), "c", "s")
    monkeypatch.setattr(R, "_get_ontology_graph", lambda *a, **k: g)

    out = R.get_kinetic_actions(connection_id="c", schema_name=None)
    assert "refund_order" in out
    assert out["refund_order"]["submission_criteria"][0]["message"] == _MESSAGE


def test_api_404_when_no_ontology(monkeypatch):
    from fastapi import HTTPException
    from aughor.routers import ontology as R
    monkeypatch.setattr(R, "_get_ontology_graph", lambda *a, **k: None)
    with pytest.raises(HTTPException):
        R.get_kinetic_actions(connection_id="c", schema_name=None)
