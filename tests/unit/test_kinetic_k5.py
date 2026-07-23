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
    monkeypatch.delenv("AUGHOR_ACTION_APPROVAL", raising=False)


def _valid_body() -> "ONT._KineticActionBody":
    return ONT._KineticActionBody(
        kind="side_effect", display_name="Refund order",
        params=[{"name": "amount", "data_type": "NUMERIC", "required": True}],
        submission_criteria=[{"expr": "amount <= 100", "message": "cap is EUR 100"}],
        side_effects=[{"kind": "webhook", "config": {"url": "https://x"}}], risk="high")


# ── author a declared action ──────────────────────────────────────────────────────

def test_author_valid_action_persists_as_an_override():
    out = ONT.author_kinetic_action("refund", _valid_body(), connection_id="c", schema_name=None)
    assert out["override"]["target_kind"] == "action" and out["override"]["target_id"] == "refund"
    assert out["override"]["fields"]["kind"] == "side_effect"
    # a YAML override file was written under the isolated root
    assert list(OV._ROOT.rglob("*.yaml"))


def test_author_malformed_criterion_is_422():
    body = ONT._KineticActionBody(kind="side_effect",
                                  submission_criteria=[{"expr": "amount <= 100"}])  # no message
    with pytest.raises(HTTPException) as e:
        ONT.author_kinetic_action("bad", body, connection_id="c", schema_name=None)
    assert e.value.status_code == 422


def test_author_missing_kind_is_400():
    with pytest.raises(HTTPException) as e:
        ONT.author_kinetic_action("x", ONT._KineticActionBody(display_name="x"),
                                  connection_id="c", schema_name=None)
    assert e.value.status_code == 400


# ── annotate + list ────────────────────────────────────────────────────────────────

def test_annotate_flag_off_is_404(monkeypatch):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda n: False)
    with pytest.raises(HTTPException) as e:
        K.annotate(K.AnnotateRequest(table="orders", body="note"), connection_id="c")
    assert e.value.status_code == 404


def test_annotate_writes_and_lists(monkeypatch):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda n: n == "kinetic.overlay")
    from aughor.kinetic import overlay as OVL
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
