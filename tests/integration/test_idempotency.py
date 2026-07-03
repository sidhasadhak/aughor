"""REC-10b / API-03 — Idempotency-Key prevents duplicate resource creation.

A retried create (same key) must return the already-created resource, not a
second row. Keys are scoped to the endpoint AND the org.
"""
from __future__ import annotations


def test_store_roundtrip_and_no_key_is_noop():
    from aughor.util import idempotency
    assert idempotency.lookup("canvas", "k1") is None
    idempotency.remember("canvas", "k1", "res1")
    assert idempotency.lookup("canvas", "k1") == "res1"
    # A missing key is a no-op on both sides (never raises, never matches).
    assert idempotency.lookup("canvas", None) is None
    idempotency.remember("canvas", None, "resX")
    assert idempotency.lookup("canvas", None) is None


def test_keys_are_org_scoped():
    from aughor.org.context import using_org
    from aughor.util import idempotency
    with using_org("orgA"):
        idempotency.remember("canvas", "shared-key", "canvasA")
    with using_org("orgB"):
        assert idempotency.lookup("canvas", "shared-key") is None
    with using_org("orgA"):
        assert idempotency.lookup("canvas", "shared-key") == "canvasA"


def test_scopes_do_not_collide():
    from aughor.util import idempotency
    idempotency.remember("canvas", "dup", "the-canvas")
    idempotency.remember("connection", "dup", "the-connection")
    assert idempotency.lookup("canvas", "dup") == "the-canvas"
    assert idempotency.lookup("connection", "dup") == "the-connection"


def test_canvas_create_is_idempotent(client):
    body = {"name": "idem-canvas", "connection_id": "fixture", "tables": []}
    headers = {"Idempotency-Key": "canvas-create-abc"}
    r1 = client.post("/canvases", json=body, headers=headers)
    r2 = client.post("/canvases", json=body, headers=headers)
    assert r1.status_code == 201 and r2.status_code == 201
    # Same key → same canvas, not a duplicate.
    assert r1.json()["id"] == r2.json()["id"]


def test_canvas_create_without_key_makes_distinct(client):
    body = {"name": "no-key-canvas", "connection_id": "fixture", "tables": []}
    r1 = client.post("/canvases", json=body)
    r2 = client.post("/canvases", json=body)
    assert r1.json()["id"] != r2.json()["id"]
