"""Wave K5 (backend) — the author / annotate write surface.

Author a declared KineticAction (validated at author time), and write a human overlay annotation
directly (the 'annotate this cell' affordance). Hermetic: overrides root + overlay ledger are the
temp paths; approval is off.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from aughor.ontology import overrides as OV
from aughor.routers import kinetic as K
from aughor.routers import ontology as ONT


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ov")
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "0")   # the gate is on by default since 2026-10-04


def _valid_body() -> "ONT._DeclaredActionBody":
    # Phase 4 of the 2027 study: a side-effect action is declared with the read that verifies it
    # and the undo that compensates it — the door refuses one without (test_action_authority).
    return ONT._DeclaredActionBody(
        kind="side_effect", display_name="Refund order",
        params=[{"name": "amount", "data_type": "NUMERIC", "required": True}],
        submission_criteria=[{"expr": "amount <= 100", "message": "cap is EUR 100"}],
        side_effects=[{"kind": "webhook", "config": {"url": "https://x"}}], risk="high",
        reversibility="compensable",
        verification={"sql": "SELECT 1 FROM refunds WHERE amount = {amount}", "expects": "rows"},
        undo={"action_id": "reverse_refund", "window_hours": 72})


# ── author a declared action ──────────────────────────────────────────────────────

def test_author_valid_action_persists_and_reads_back_whole():
    from aughor.actions.authority import declaration_problem
    from aughor.ontology.models import OntologyGraph
    out = ONT.author_kinetic_action("refund", _valid_body(), connection_id="c", schema_name=None)
    assert out["override"]["target_kind"] == "action" and out["override"]["target_id"] == "refund"
    assert out["override"]["fields"]["kind"] == "side_effect"
    # a YAML override file was written under the isolated root
    assert list(OV._ROOT.rglob("*.yaml"))
    # Every reader — the executor, the GET door, the inbox — sees the action through the overlay. The door persisted
    # the phase-4 fields and the overlay dropped them, so a stored side-effect action read back undeclarable: it
    # never graduated and its undo was refused.
    schema = ONT._resolve_schema("c", None)
    graph, _ = OV.apply_overrides(OntologyGraph(connection_id="c", schema_name=schema, schema_fingerprint="x"),
                                  "c", schema)
    action = {a.id: a for a in graph.declared_actions()}["refund"]
    assert action.reversibility == "compensable"
    assert action.verification is not None
    assert action.verification.sql == "SELECT 1 FROM refunds WHERE amount = {amount}"
    assert action.undo is not None and (action.undo.action_id, action.undo.window_hours) == ("reverse_refund", 72)
    assert declaration_problem(action) == ""


def test_author_malformed_criterion_is_422():
    body = ONT._DeclaredActionBody(kind="side_effect",
                                  submission_criteria=[{"expr": "amount <= 100"}])  # no message
    with pytest.raises(HTTPException) as e:
        ONT.author_kinetic_action("bad", body, connection_id="c", schema_name=None)
    assert e.value.status_code == 422


def test_author_missing_kind_is_400():
    with pytest.raises(HTTPException) as e:
        ONT.author_kinetic_action("x", ONT._DeclaredActionBody(display_name="x"),
                                  connection_id="c", schema_name=None)
    assert e.value.status_code == 400


# ── annotate + list ────────────────────────────────────────────────────────────────

def test_annotate_writes_and_lists(monkeypatch):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda n: n == "kinetic.overlay")
    from aughor.actions import overlay as OVL
    OVL.purge_connections(["c-k5"])
    try:
        out = K.annotate(K.AnnotateRequest(table="orders", column="status", key_column="order_id",
                                           row_key="8821", body="known test order"),
                         connection_id="c-k5")
        assert out["target"] == "orders.status#order_id=8821"
        listed = K.list_annotations(connection_id="c-k5")
        assert len(listed["edits"]) == 1 and listed["edits"][0]["body"] == "known test order"
    finally:
        OVL.purge_connections(["c-k5"])


def test_annotate_missing_fields_is_400(monkeypatch):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda n: n == "kinetic.overlay")
    with pytest.raises(HTTPException) as e:
        K.annotate(K.AnnotateRequest(table="", body="x"), connection_id="c")
    assert e.value.status_code == 400
