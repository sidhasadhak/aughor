"""Arc FA, FA-3 — an earlier version of a declaration, put back into the draft (ROADMAP §3.60).

Before: every save and withdrawal was a version (OC-1) and a change waited in a draft (OC-2), but nothing put a version
back — a promise moved from five days to seven could be read as it was, and putting five back meant typing it again.
Behind `ontology.put_back`: the version's fields go through the normal save path into the DRAFT, counted again by the
kind's own measurement and classed like any change, so readers get it only when a person publishes. Refused with a
sentence while releases are off, for an organisation's ontology and for a version the history does not hold. Off, the
history door answers exactly as before and the put-back door refuses.

Hermetic: the overrides tree, its draft layer and the ledger are per test; the door flow counts on the seeded samples
warehouse, as the release suite does.
"""
from __future__ import annotations

import copy

import pytest

from aughor.ontology import overrides as OV
from aughor.ontology import put_back as PB
from aughor.ontology.overrides import OntologyOverride, find_override, save_override, viewing
from tests.unit.test_object_processes import FULFILMENT, PARAMS, door  # noqa: F401 — `door` is a fixture

CONN, SCHEMA = "put-back-t", "ecommerce"
PROCESS = {"kind": "process", "target_id": "order_fulfilment"}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from aughor.kernel.ledger import Ledger
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")
    monkeypatch.setattr(OV, "_SEED_ROOT", tmp_path / "seed")
    monkeypatch.setattr(OV, "_DRAFT_ROOT", tmp_path / "ontology_overrides_draft")
    ledger = Ledger(str(tmp_path / "system.db"))
    monkeypatch.setattr(Ledger, "default", classmethod(lambda cls: ledger))
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "0")
    monkeypatch.setattr("aughor.automations.store.list_automations", lambda *a, **k: [])


def _flags(monkeypatch, *on: str) -> None:
    names = set(on)
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: name in names)


def _promise_days(process: dict) -> int:
    return process["stages"][2]["promise"]["within_days"]


def _published_and_moved(client) -> int:
    """FULFILMENT published as release 2 at five days, then moved to seven and published as release 3. Returns the
    version number of the five-day declaration readers read before the move."""
    assert client.post("/ontology/processes", params=PARAMS, json=FULFILMENT).status_code == 200
    assert client.post("/ontology/release/publish", params=PARAMS).json()["number"] == 2
    longer = copy.deepcopy(FULFILMENT)
    longer["stages"][2]["promise"]["within_days"] = 7
    assert client.put("/ontology/processes/order_fulfilment", params=PARAMS, json=longer).status_code == 200
    assert client.post("/ontology/release/publish", params=PARAMS).json()["number"] == 3
    history = client.get("/ontology/history", params={**PARAMS, **PROCESS}).json()
    five = [v for v in history["versions"] if v["state"] == "declared" and _promise_days(v["fields"]) == 5]
    assert five, history
    return five[0]["version"]


# ── on: through the doors ──────────────────────────────────────────────────────────────────────

def test_a_version_put_back_waits_in_the_draft_classed_and_counted_until_published(door, client, monkeypatch):  # noqa: F811
    _flags(monkeypatch, "ontology.release", "ontology.put_back")
    monkeypatch.setattr("aughor.db.registry.get_meta", lambda conn: {"schema_name": "ecommerce"})
    five = _published_and_moved(client)
    history = client.get("/ontology/history", params={**PARAMS, **PROCESS}).json()
    assert history["put_back"] == {"enabled": True, "said": ""}

    put = client.post("/ontology/history/put-back", params=PARAMS, json={**PROCESS, "version": five})
    assert put.status_code == 200, put.text
    out = put.json()
    assert (out["landed"], out["version"], out["change"]["class"]) == ("draft", five, "MEANING")
    assert any("within_days 7 → 5" in r["why"] for r in out["change"]["reasons"]), out["change"]
    assert "waits in the draft" in out["said"] and "publishes" in out["said"]

    readers = client.get("/ontology/processes", params=PARAMS).json()["processes"][0]
    assert _promise_days(readers) == 7                                           # readers keep seven…
    editors = client.get("/ontology/processes", params={**PARAMS, "ontology_view": "draft"}).json()["processes"][0]
    assert _promise_days(editors) == 5 and editors["verified"] is True           # …the draft holds five, counted again
    with viewing("draft"):
        drafted = find_override(PARAMS["connection_id"], "ecommerce", "process", "order_fulfilment")
    assert drafted.note == f"put back from version {five}" and drafted.source == "human"
    assert drafted.binding["process"]["bound"] is True

    assert client.post("/ontology/release/publish", params=PARAMS).json()["number"] == 4
    readers = client.get("/ontology/processes", params=PARAMS).json()["processes"][0]
    assert _promise_days(readers) == 5                                           # …until a person publishes
    latest = client.get("/ontology/history", params={**PARAMS, **PROCESS}).json()["versions"][0]
    assert latest["declaration_note"] == f"put back from version {five}" and latest["state"] == "declared"


def test_putting_back_what_readers_read_takes_the_waiting_change_away(door, client, monkeypatch):  # noqa: F811
    _flags(monkeypatch, "ontology.release", "ontology.put_back")
    monkeypatch.setattr("aughor.db.registry.get_meta", lambda conn: {"schema_name": "ecommerce"})
    _published_and_moved(client)
    seven = client.get("/ontology/history", params={**PARAMS, **PROCESS}).json()["versions"][0]["version"]
    nothing = client.post("/ontology/history/put-back", params=PARAMS, json={**PROCESS, "version": seven})
    assert nothing.status_code == 409 and "what readers read already" in nothing.json()["detail"]
    nine = copy.deepcopy(FULFILMENT)
    nine["stages"][2]["promise"]["within_days"] = 9
    assert client.put("/ontology/processes/order_fulfilment", params=PARAMS, json=nine).status_code == 200
    assert len(client.get("/ontology/release", params=PARAMS).json()["draft"]) == 1
    back = client.post("/ontology/history/put-back", params=PARAMS, json={**PROCESS, "version": seven}).json()
    assert back["landed"] == "discard" and "taken away" in back["said"]
    assert client.get("/ontology/release", params=PARAMS).json()["draft"] == []


def test_refusals_are_said(door, client, monkeypatch):  # noqa: F811
    _flags(monkeypatch, "ontology.release", "ontology.put_back")
    monkeypatch.setattr("aughor.db.registry.get_meta", lambda conn: {"schema_name": "ecommerce"})
    _published_and_moved(client)
    missing = client.post("/ontology/history/put-back", params=PARAMS, json={**PROCESS, "version": 99})
    assert missing.status_code == 404 and "no version 99 of process 'order_fulfilment'" in missing.json()["detail"]
    never = client.post("/ontology/history/put-back", params=PARAMS,
                        json={"kind": "rule", "target_id": "nothing_here", "version": 1})
    assert never.status_code == 404 and "no recorded version" in never.json()["detail"]
    unknown = client.post("/ontology/history/put-back", params=PARAMS, json={"kind": "widget", "target_id": "x", "version": 1})
    assert unknown.status_code == 400

    _flags(monkeypatch, "ontology.put_back", "ontology.history")                 # releases off
    off = client.post("/ontology/history/put-back", params=PARAMS, json={**PROCESS, "version": 1})
    assert off.status_code == 409 and "needs releases on" in off.json()["detail"]
    assert client.get("/ontology/history", params={**PARAMS, **PROCESS}).json()["put_back"]["enabled"] is False
    assert "outside releases" in PB.unavailable("org=acme")
    assert "outside releases" in PB.unavailable("domain:default")


def test_a_version_that_no_longer_counts_is_refused_and_nothing_is_written(door, client, monkeypatch):  # noqa: F811
    _flags(monkeypatch, "ontology.release", "ontology.put_back")
    monkeypatch.setattr("aughor.db.registry.get_meta", lambda conn: {"schema_name": "ecommerce"})
    five = _published_and_moved(client)
    monkeypatch.setattr("aughor.ontology.processes.resolve_process",
                        lambda graph, pid, fields: ("stage 'delivered': Order has no delivered_at", fields))
    refused = client.post("/ontology/history/put-back", params=PARAMS, json={**PROCESS, "version": five})
    assert refused.status_code == 400 and "no delivered_at" in refused.json()["detail"]
    assert "nothing was put back" in refused.json()["detail"]
    assert client.get("/ontology/release", params=PARAMS).json()["draft"] == []


def test_a_withdrawn_version_puts_back_the_fields_it_had(monkeypatch):
    _flags(monkeypatch, "ontology.release", "ontology.put_back")
    rule = OntologyOverride(target_kind="rule", target_id="dach", fields={
        "declared": True, "entity": "Customer", "kind": "value_set", "property": "country", "values": ["DE", "AT"]})
    _flags(monkeypatch, "ontology.history")
    save_override(CONN, SCHEMA, rule)
    assert OV.delete_override(CONN, SCHEMA, "rule", "dach")                       # withdrawn, recorded with its fields
    _flags(monkeypatch, "ontology.release", "ontology.put_back")
    from aughor.ontology import history
    gone = history.versions(CONN, SCHEMA, "rule", "dach")[0]
    assert gone["state"] == "withdrawn" and gone["fields"]["values"] == ["DE", "AT"]
    plan = PB.plan(CONN, SCHEMA, "rule", "dach", gone["version"], by="person:ana")
    assert (plan.outcome, plan.state, plan.override.fields["values"]) == ("draft", "withdrawn", ["DE", "AT"])
    plan.override.binding = {"rule": {"bound": True, "note": "admits 3"}}       # what the rule door counts
    save_override(CONN, SCHEMA, plan.override)
    from aughor.ontology import release as R
    (row,) = R.changes(CONN, SCHEMA)
    assert (row["change"], row["class"]) == ("added", "SAFE")
    with viewing("published"):
        assert find_override(CONN, SCHEMA, "rule", "dach") is None               # nothing served until published


# ── off: byte-identical ────────────────────────────────────────────────────────────────────────

def test_off_the_history_door_answers_as_before_and_the_put_back_door_refuses(door, client, monkeypatch):  # noqa: F811
    _flags(monkeypatch, "ontology.release")
    monkeypatch.setattr("aughor.db.registry.get_meta", lambda conn: {"schema_name": "ecommerce"})
    assert client.post("/ontology/processes", params=PARAMS, json=FULFILMENT).status_code == 200
    history = client.get("/ontology/history", params={**PARAMS, **PROCESS}).json()
    assert set(history) == {"element", "kept", "versions"}
    assert history["versions"] and all(set(v) == {"version", "state", "in_force_from", "recorded_at", "by", "note",
                                                  "fields", "source", "changes"} for v in history["versions"])
    refused = client.post("/ontology/history/put-back", params=PARAMS, json={**PROCESS, "version": 1})
    assert refused.status_code == 409 and "off on this install" in refused.json()["detail"]
