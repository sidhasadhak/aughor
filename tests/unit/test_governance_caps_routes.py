"""The usage-cap door (`/governance/caps`) — G4's store finally gets a writer.

The cap store shipped with `set_cap`/`clear_cap` and no route: caps could be read by the
enforcement path and set by nobody. These tests pin the door's contract — the vocabulary
is SERVED (never mirrored into a client), a bad dimension is a 400 in the store's own
words, and a delete of nothing is a 404 (an operator lifting a cap that isn't there
should hear that, not "removed").

Hermetic — `tests/conftest.py` points `AUGHOR_GOVERN_CAPS_DB` at a tempdir.
"""
from __future__ import annotations


def test_list_serves_caps_and_the_vocabulary(client):
    r = client.get("/governance/caps")
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"caps", "scopes", "metrics", "actions"}
    assert "calls" in body["metrics"] and "org" in body["scopes"]


def test_set_list_delete_roundtrip(client):
    put = client.put("/governance/caps", json={
        "scope": "org", "subject": "*", "metric": "calls",
        "limit": 500, "window_hours": 24, "action": "alert"})
    assert put.status_code == 200
    assert put.json()["limit"] == 500

    listed = client.get("/governance/caps").json()["caps"]
    mine = [c for c in listed if c["metric"] == "calls" and c["scope"] == "org"]
    assert mine and mine[0]["limit"] == 500
    # The observed value rides along (may be 0.0 on an empty ledger, never absent).
    assert "observed" in mine[0]

    deleted = client.delete("/governance/caps?scope=org&metric=calls&subject=*&window_hours=24")
    assert deleted.status_code == 200 and deleted.json()["removed"] is True

    again = client.delete("/governance/caps?scope=org&metric=calls&subject=*&window_hours=24")
    assert again.status_code == 404


def test_an_unknown_dimension_is_a_400_in_the_stores_own_words(client):
    r = client.put("/governance/caps", json={
        "scope": "org", "subject": "*", "metric": "vibes", "limit": 1})
    assert r.status_code == 400
    assert "vibes" in r.json()["detail"]


def test_a_negative_limit_is_refused_by_the_schema(client):
    r = client.put("/governance/caps", json={
        "scope": "org", "subject": "*", "metric": "calls", "limit": -3})
    assert r.status_code == 422
