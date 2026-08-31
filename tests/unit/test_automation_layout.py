"""DS-4 — where a person arranged the canvas survives, and stays out of the record.

The arrangement is a VIEW PREFERENCE. It lives in a sidecar keyed by (automation, user)
rather than on the `Automation` row for a reason this subsystem has paid for three times:
the authoring `PUT` rebuilds the record from what a person typed, so anything the request
body does not carry is erased by a rename. A layout column would have been the fourth.

The properties worth locking are therefore: it round-trips, a save REPLACES rather than
accumulates, editing the automation cannot touch it, and deleting the automation takes it
with them.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aughor.api import app
from aughor.automations.store import get_layout, set_layout

client = TestClient(app)

BODY = {
    "conn_id": "conn-layout",
    "name": "Arranged",
    "conditions": [{"kind": "schedule", "config": {"cron": "0 8 * * 1"}}],
    "effects": [{"kind": "notify", "config": {"trigger_id": "trig-1"}}],
}

LAYOUT = {"__trigger": {"x": 0, "y": 60}, "step1": {"x": 320, "y": 120}}


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled",
                        lambda n: n == "automations.engine")


def _create() -> str:
    return client.post("/automations", json=BODY).json()["id"]


def test_layout_round_trips(flag_on):
    aid = _create()
    assert client.get(f"/automations/{aid}/layout").json()["layout"] == {}

    assert client.put(f"/automations/{aid}/layout", json={"layout": LAYOUT}).status_code == 200
    assert client.get(f"/automations/{aid}/layout").json()["layout"] == LAYOUT


def test_a_save_replaces_rather_than_accumulates(flag_on):
    """A step that was removed must not keep a coordinate in the row forever. Merging
    would mean the stored layout only ever grows, and a canvas eventually opens carrying
    the ghosts of every step anyone ever deleted."""
    aid = _create()
    client.put(f"/automations/{aid}/layout", json={"layout": LAYOUT})
    client.put(f"/automations/{aid}/layout", json={"layout": {"step1": {"x": 9, "y": 9}}})

    assert client.get(f"/automations/{aid}/layout").json()["layout"] == {"step1": {"x": 9, "y": 9}}


def test_editing_the_automation_cannot_move_anybody_s_nodes(flag_on):
    """The whole reason this is a sidecar. `PUT /automations/{id}` carries the governed
    record; it must not be able to touch an arrangement it does not know about."""
    aid = _create()
    client.put(f"/automations/{aid}/layout", json={"layout": LAYOUT})

    renamed = client.put(f"/automations/{aid}", json={**BODY, "name": "Renamed"})
    assert renamed.status_code == 200

    assert client.get(f"/automations/{aid}/layout").json()["layout"] == LAYOUT


def test_two_automations_do_not_share_an_arrangement(flag_on):
    a, b = _create(), _create()
    client.put(f"/automations/{a}/layout", json={"layout": LAYOUT})

    assert client.get(f"/automations/{b}/layout").json()["layout"] == {}


def test_deleting_the_automation_takes_its_arrangement(flag_on):
    """Otherwise a new automation that reused the id opens onto a stranger's layout."""
    aid = _create()
    client.put(f"/automations/{aid}/layout", json={"layout": LAYOUT})
    client.delete(f"/automations/{aid}")

    assert get_layout(aid, "default") == {}


def test_an_unarranged_automation_answers_with_an_empty_layout_not_a_404(flag_on):
    """"Nobody has arranged this" is an answer, not an error — the canvas opens at its
    computed default and nothing on screen has to explain a failure."""
    res = client.get("/automations/does-not-exist/layout")
    assert res.status_code == 200
    assert res.json()["layout"] == {}


def test_a_corrupt_layout_opens_the_canvas_instead_of_breaking_it():
    """A layout is a convenience. A row that cannot be parsed must degrade to the default
    arrangement, not to a canvas that refuses to draw."""
    from aughor.automations import store

    with store._LOCK:
        conn = store._connect()
        try:
            conn.execute(
                """INSERT INTO automation_layouts
                       (automation_id, user_id, layout_json, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(automation_id, user_id) DO UPDATE SET
                       layout_json = excluded.layout_json""",
                ("corrupt-auto", "default", "{not json", ""),
            )
            conn.commit()
        finally:
            conn.close()

    assert get_layout("corrupt-auto", "default") == {}


def test_a_layout_that_is_not_an_object_is_refused_the_same_way():
    set_layout("odd-auto", "default", {})
    from aughor.automations import store

    with store._LOCK:
        conn = store._connect()
        try:
            conn.execute("UPDATE automation_layouts SET layout_json = ? "
                         "WHERE automation_id = ?", ("[1, 2, 3]", "odd-auto"))
            conn.commit()
        finally:
            conn.close()

    assert get_layout("odd-auto", "default") == {}
