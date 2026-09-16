"""HB-6 — packs ship function groups (§6 24 c, taken on its recorded recommendation).

THE RECEIPT, in the roadmap's words: installing a supply-chain pack creates the group,
tagged and subscribed, waiting for members. "Tagged" is spelled as subscribe grants on
the pack's domains (grants by tag are what make a function group self-maintaining, 24 b);
"subscribed" as subscribe grants on its securables; "waiting" as zero members, no
channel, and automations that land declared, on probation and DISARMED.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aughor.org.context import current_org_id
from aughor.packs.install import InstallRefused, install_pack

_GROUP = "group:supply-chain"
_PROMISE = "promise:order_to_delivery.dispatch"


@pytest.fixture()
def client():
    from aughor.api import app
    return TestClient(app)


def _grants() -> set[tuple[str, str]]:
    from aughor.metastore.store import list_grants
    return {(g.securable, g.privilege)
            for g in list_grants(org_id=current_org_id(), principal=_GROUP)}


# ── THE RECEIPT ───────────────────────────────────────────────────────────────────

def test_receipt_installing_the_supply_chain_pack_creates_the_group(client):
    resp = client.post("/packs/supply-chain/install",
                       json={"actor": "user:ana", "connection_id": "olist"})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # The group exists — WAITING FOR MEMBERS.
    from aughor.rbac.groups import get_group, list_members
    oid = current_org_id()
    group = get_group(oid, "supply-chain")
    assert group is not None and group.name == "Supply Chain"
    assert list_members(oid, "supply-chain") == []
    assert body["group"]["members"] == 0

    # TAGGED: the pack's domains land as subscribe grants on domain:<value>...
    grants = _grants()
    for d in ("supply-chain", "logistics", "fulfilment"):
        assert (f"domain:{d}", "subscribe") in grants
    # ...and SUBSCRIBED to the order process.
    assert ("process:order_to_delivery", "subscribe") in grants

    # The automation landed declared, on probation, disarmed — HB-2's law from birth.
    from aughor.automations.store import get_automation
    auto = get_automation("pack-supply-chain-dispatch-watch")
    assert auto is not None
    assert auto.declared_by == "pack:supply-chain"
    assert auto.probation is True
    assert auto.enabled is False
    assert auto.conn_id == "olist"


def test_the_installed_group_is_a_destination_the_router_already_finds(client):
    """The point of "subscribed": a breach on the promise now ROUTES to the group —
    channel-less for now (waiting), reachable the day it gets members and a channel."""
    client.post("/packs/supply-chain/install", json={"connection_id": "olist"})
    from aughor.rbac.routing import route
    oid = current_org_id()

    dests = route(_PROMISE, org_id=oid, parents=["process:order_to_delivery"])
    assert any(d.principal == _GROUP for d in dests)

    # Self-maintaining (24 b): ANY securable later tagged into the domain reaches it.
    tagged = route("table:shipments", org_id=oid, tags={"domain": "supply-chain"})
    assert any(d.principal == _GROUP for d in tagged)


def test_reinstall_is_idempotent_and_never_takes_back_what_operators_set(client):
    client.post("/packs/supply-chain/install", json={"connection_id": "olist"})

    # Operators act between installs: a channel on the group, a member, a graduation,
    # an arming.
    from aughor.rbac.groups import add_member, get_group, list_members, upsert_group
    from aughor.automations.store import get_automation, set_probation, upsert_automation
    oid = current_org_id()
    g = get_group(oid, "supply-chain")
    upsert_group(oid, "supply-chain", name=g.name, description=g.description,
                 channel_trigger_id="trg-ops")
    add_member(oid, "supply-chain", "user:ana")
    set_probation("pack-supply-chain-dispatch-watch", False)      # graduated
    armed = get_automation("pack-supply-chain-dispatch-watch").model_copy(
        update={"enabled": True})
    upsert_automation(armed)
    grants_before = _grants()

    resp = client.post("/packs/supply-chain/install", json={"connection_id": "olist"})
    assert resp.status_code == 200
    body = resp.json()

    assert body["group"]["existed"] is True
    assert get_group(oid, "supply-chain").channel_trigger_id == "trg-ops"
    assert list_members(oid, "supply-chain") == ["user:ana"]
    auto = get_automation("pack-supply-chain-dispatch-watch")
    assert auto.probation is False        # graduation survives a re-install
    assert auto.enabled is True           # so does the operator's arming
    assert auto.declared_by == "pack:supply-chain"
    assert _grants() == grants_before     # no duplicates
    assert all(g["existed"] for g in body["grants"])


def test_without_a_connection_the_automations_wait_and_the_group_still_lands():
    from aughor.automations.store import list_automations
    before = len(list_automations())
    report = install_pack("supply-chain", org_id="org-hb6-nc")
    assert report["group"]["members"] == 0
    assert report["automations"] and report["automations"][0]["state"] == "waiting"
    # Waiting means waiting: the library did not grow.
    assert len(list_automations()) == before
    from aughor.rbac.groups import get_group
    assert get_group("org-hb6-nc", "supply-chain") is not None


# ── refusals: whole, plain, and with nothing written ─────────────────────────────

def _write_pack(root: Path, pack_id: str, *, status: str = "draft",
                function_yaml: str = "") -> None:
    d = root / pack_id
    d.mkdir(parents=True)
    (d / "pack.yaml").write_text(
        f"id: {pack_id}\nname: T\nstatus: {status}\nscope:\n  connections: [\"*\"]\n")
    if function_yaml:
        (d / "function.yaml").write_text(function_yaml)


def test_a_deprecated_pack_refuses_to_install(tmp_path, monkeypatch, client):
    monkeypatch.setenv("AUGHOR_IMPORTED_PACKS_DIR", str(tmp_path))
    _write_pack(tmp_path, "retired-fn", status="deprecated",
                function_yaml="group:\n  id: retired-fn\n")
    resp = client.post("/packs/retired-fn/install", json={})
    assert resp.status_code == 409
    assert "deprecated" in resp.json()["detail"]


def test_a_pack_without_a_function_layer_refuses_plainly(client):
    resp = client.post("/packs/core-ecommerce/install", json={})
    assert resp.status_code == 409
    assert "no function.yaml" in resp.json()["detail"]


def test_an_invalid_layer_refuses_whole_with_nothing_written(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_IMPORTED_PACKS_DIR", str(tmp_path))
    _write_pack(tmp_path, "half-good", function_yaml=(
        "group:\n  id: half-good\n"
        "subscriptions:\n  - \"process:ok_process\"\n"
        "grants:\n  - securable: \"metric:m\"\n    privilege: superuser\n"))
    with pytest.raises(InstallRefused, match="superuser"):
        install_pack("half-good", org_id="org-hb6-refuse")
    from aughor.rbac.groups import get_group
    from aughor.metastore.store import list_grants
    assert get_group("org-hb6-refuse", "half-good") is None
    assert list_grants(org_id="org-hb6-refuse") == []


def test_a_broken_automation_spec_refuses_before_anything_writes(
        tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_IMPORTED_PACKS_DIR", str(tmp_path))
    _write_pack(tmp_path, "bad-auto", function_yaml=(
        "group:\n  id: bad-auto\n"
        "automations:\n  - id: watch\n    name: W\n"
        "    conditions:\n      - kind: no_such_kind\n        config: {}\n"
        "    effects:\n      - kind: notify\n        config: {trigger_id: t1}\n"))
    with pytest.raises(InstallRefused, match="save-time validators"):
        install_pack("bad-auto", org_id="org-hb6-badauto", connection_id="c1")
    from aughor.rbac.groups import get_group
    assert get_group("org-hb6-badauto", "bad-auto") is None


# ── the roster names the layer ───────────────────────────────────────────────────

def test_the_roster_shows_which_packs_ship_a_function(client):
    packs = {p["id"]: p for p in client.get("/packs").json()["packs"]}
    assert packs["supply-chain"]["function"] is True
    assert packs["supply-chain"]["ok"] is True, packs["supply-chain"]["errors"]
    assert packs["core-ecommerce"]["function"] is False


def test_a_broken_layer_is_named_on_the_roster_not_at_the_door(tmp_path, monkeypatch,
                                                               client):
    monkeypatch.setenv("AUGHOR_IMPORTED_PACKS_DIR", str(tmp_path))
    _write_pack(tmp_path, "bad-slug", function_yaml="group:\n  id: \"Not A Slug\"\n")
    summary = {p["id"]: p for p in client.get("/packs").json()["packs"]}["bad-slug"]
    assert summary["ok"] is False
    assert any("group id" in e for e in summary["errors"])
