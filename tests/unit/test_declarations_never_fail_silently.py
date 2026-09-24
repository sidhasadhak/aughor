"""PENDING item 21 — a declaration that did not land is said, never reported as saved.

Measured 2026-09-24 by reading: `save_override` was documented "never raises", and `_write` and `_unlink` swallowed
every exception — so every declare and confirm door answered 200 for a declaration that was never written, and the
explorer recorded such a proposal as written. The ontology store turned a saved graph that failed validation into
"no ontology" with no log, and a failed build into None with no trace.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aughor.ontology import overrides as OV
from aughor.ontology.overrides import OntologyOverride, OverrideWriteFailed


@pytest.fixture()
def unwritable(tmp_path, monkeypatch):
    """An overrides root that cannot hold a directory: a FILE sits where it should be."""
    root = tmp_path / "ontology_overrides"
    root.write_text("not a directory\n")
    monkeypatch.setattr(OV, "_ROOT", root)
    return root


def test_a_write_that_does_not_land_raises_and_names_what_was_not_saved(unwritable):
    ov = OntologyOverride(target_kind="entity", target_id="Order", fields={"display_name": "Sale"})
    with pytest.raises(OverrideWriteFailed) as failed:
        OV.save_override("c1", "main", ov)
    message = str(failed.value)
    assert "entity 'Order' was not saved" in message
    assert str(unwritable) not in message                  # the reason, never the install's paths


def test_a_withdrawal_that_does_not_land_raises(unwritable):
    with pytest.raises(OverrideWriteFailed, match="was not withdrawn"):
        OV.delete_override("c1", "main", "entity", "Order")


def test_a_door_answers_not_saved_instead_of_200(unwritable, monkeypatch):
    """The API's handler turns the raise into what a person can act on, not 'internal_error'."""
    from aughor.api import app
    monkeypatch.setattr("aughor.ontology.overrides.save_override",
                        lambda conn, schema, ov: (_ for _ in ()).throw(
                            OverrideWriteFailed("saved", ov.target_kind, ov.target_id, OSError(28, "No space left on device"))))

    @app.get("/__test__/declare")
    def _declare():
        OV.save_override("c1", "main", OntologyOverride(target_kind="metric", target_id="revenue"))
        return {"ok": True}

    try:
        res = TestClient(app, raise_server_exceptions=False).get("/__test__/declare")
    finally:
        app.router.routes = [r for r in app.router.routes if getattr(r, "path", "") != "/__test__/declare"]
    assert res.status_code == 500
    body = res.json()
    assert body["error"] == "declaration_not_saved" and body["target"] == "revenue"
    assert "No space left on device" in body["detail"]


def test_an_unreadable_saved_graph_is_counted_not_silent(monkeypatch):
    from aughor.ontology import store as ST
    seen: list[str] = []
    monkeypatch.setattr("aughor.kernel.errors.tolerate",
                        lambda exc, reason, **kw: seen.append(kw.get("counter", "")))
    assert ST._graph_from({"graph": {"entities": "not a mapping"}}, "c1") is None
    assert seen == ["ontology.saved_graph_unreadable"]
