"""HB-6 — the hub-wide map: every automation on one screen, with the seven columns the
roadmap names — trigger, destinations, grant, owner, last run, cost, probation state.

The cost column is asserted as what it claims to be: a FLOOR folded over the traces the
automation's runs caused, with the unpriced caveats carried — never a total, and a
precision that was never measured renders as null, never as 0%.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aughor.automations.models import Automation, AutomationRun, Condition, Effect, EffectOutcome
from aughor.automations.store import append_run, upsert_automation
from aughor.org.context import current_org_id

_AID = "hb6-map-watch"
_PROMISE = "promise:order_to_delivery.dispatch"


@pytest.fixture()
def client():
    from aughor.api import app
    return TestClient(app)


def _seed_automation() -> Automation:
    return upsert_automation(Automation(
        id=_AID, conn_id="olist", name="Dispatch watch (map)",
        declared_by="user:ana", probation=True,
        conditions=[Condition(kind="schedule", config={"cron": "0 9 * * *"})],
        effects=[
            Effect(kind="notify", config={"route_about": _PROMISE, "message": "m"}),
            Effect(kind="slack_post", config={"bot_id": "b1", "channel": "#ops"}),
        ]))


def _seed_run():
    append_run(AutomationRun(
        id="hb6-map-run-1", automation_id=_AID, automation_name="Dispatch watch (map)",
        conn_id="olist", outcome="fired", trace_id="tr-1",
        effects=[EffectOutcome(kind="investigate", status="executed",
                               investigation_id="inv-1")]))


def _row(client) -> dict:
    body = client.get("/hub/map").json()
    rows = {r["id"]: r for r in body["rows"]}
    assert _AID in rows, f"the map is missing the seeded automation: {list(rows)}"
    return rows[_AID]


def test_the_map_carries_all_seven_columns(client, monkeypatch):
    _seed_automation()
    _seed_run()
    from aughor.rbac.groups import upsert_group
    from aughor.metastore.store import add_grant
    oid = current_org_id()
    upsert_group(oid, "maptest", "Map Test")
    add_grant("group:maptest", "process:order_to_delivery", "subscribe", org_id=oid)
    from aughor.actions.grants import mint_notify_grant
    mint_notify_grant(_AID, "trg-9", connection_id="olist", created_by="user:ana")
    # The session log's per-trace fold, pinned: one investigation trace priced, the
    # run's own trace with one call that reported no usage at all.
    import aughor.obs.session_log as sl
    monkeypatch.setattr(sl, "recent_sessions", lambda **kw: [
        {"trace_id": "inv-1", "total_tokens": 1234, "cost_usd": 0.05,
         "unpriced_calls": 1, "calls_without_usage": 0},
        {"trace_id": "tr-1", "total_tokens": 10, "cost_usd": 0.0,
         "unpriced_calls": 0, "calls_without_usage": 1},
        {"trace_id": "somebody-else", "total_tokens": 9999, "cost_usd": 9.0,
         "unpriced_calls": 0, "calls_without_usage": 0},
    ])

    row = _row(client)

    # TRIGGER — the condition's own one-liner.
    assert row["trigger"] and row["trigger"][0].startswith("schedule(")

    # DESTINATIONS — the routed notify resolves through route(); slack names its channel.
    routed = next(d for d in row["destinations"] if d.get("routed_about") == _PROMISE)
    assert any(r["principal"] == "group:maptest" for r in routed["resolved"])
    slack = next(d for d in row["destinations"] if d["kind"] == "slack_post")
    assert slack["channel"] == "#ops"

    # GRANT — the minted standing grant, bucketed onto its owner.
    assert any(g["action_id"] == f"notify:{_AID}" and g["target_value"] == "trg-9"
               for g in row["grants"])

    # OWNER and LAST RUN.
    assert row["owner"]["declared_by"] == "user:ana"
    assert row["last_run"]["status"] == "fired" and row["last_run"]["at"]

    # COST — a floor over exactly this automation's traces, caveats carried.
    cost = row["cost"]
    assert cost["floor"] is True
    assert cost["total_tokens"] == 1244            # inv-1 + tr-1, never somebody-else's
    assert cost["cost_usd"] == 0.05
    assert cost["unpriced_calls"] == 1 and cost["calls_without_usage"] == 1
    assert cost["runs"] == 1 and cost["deep_runs"] == 1

    # PROBATION — on, and honestly unmeasured (null, not 0%).
    assert row["probation"]["on"] is True
    assert row["probation"]["precision"] is None
    assert row["probation"]["graduates_at"] == {"min_marked": 5, "precision": 0.8}

    # State + totals.
    assert row["state"] == "live"
    body = client.get("/hub/map").json()
    assert body["totals"]["automations"] >= 1
    assert body["totals"]["probation"] >= 1


def test_marked_departures_show_as_measured_precision(client):
    _seed_automation()
    from aughor.govern import departure_store as ds
    for n in range(5):
        ds.record_departure(id=f"hb6-map-dep-{n}", automation_id=_AID,
                            state="held_probation", org_id=current_org_id())
        ds.mark_departure(f"hb6-map-dep-{n}", "accept" if n < 4 else "correct")
    row = _row(client)
    assert row["probation"]["marked"] == 5
    assert row["probation"]["precision"] == 1.0    # correct counts as useful (HB-2)


def test_the_map_narrows_by_connection_and_a_foreign_one_is_empty_of_it(client):
    _seed_automation()
    ours = client.get("/hub/map", params={"conn_id": "olist"}).json()
    assert any(r["id"] == _AID for r in ours["rows"])
    other = client.get("/hub/map", params={"conn_id": "elsewhere"}).json()
    assert not any(r["id"] == _AID for r in other["rows"])


def test_a_disarmed_pack_automation_reads_as_disabled_with_its_lineage(client):
    """The pack half meets the map half: an installed pack automation appears on the
    map disarmed, on probation, owned by its pack."""
    from aughor.packs.install import install_pack
    install_pack("supply-chain", connection_id="olist")
    body = client.get("/hub/map").json()
    rows = {r["id"]: r for r in body["rows"]}
    row = rows["pack-supply-chain-dispatch-watch"]
    assert row["state"] == "disabled"
    assert row["owner"]["declared_by"] == "pack:supply-chain"
    assert row["probation"]["on"] is True
    assert not row["last_run"]["at"]               # never ran: waiting, plainly
