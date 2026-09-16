"""HB-2 — the wave's receipt, held as tests (HB-1's precedent; the live receipt wants
real traffic, which is HB-3's breach):

  *"a Briefing tile the screen shows is held at departure by a failing tie-out, with the
  reason recorded"* — a brief asserting a governed metric whose quality test genuinely
  fails on the connection's own data is HELD by the engine's send path, reason in the
  ledger and the runs rail, while the text itself (what the screen shows) is untouched.

  *"an automation on probation reaches only its declarer until its measured precision
  graduates it"* — a declared automation's clean sends land on the declarer's queue;
  five accepted marks graduate it; the next send reaches the transport.
"""
from __future__ import annotations

import duckdb
import pytest
from fastapi.testclient import TestClient

from aughor.automations.models import Automation, Effect
from aughor.automations.engine import _dispatch_slack_post
from aughor.automations.store import get_automation, set_probation, upsert_automation
from aughor.govern import departure_store as ds
from aughor.semantic.metrics import MetricDefinition, save_metric


@pytest.fixture(autouse=True)
def _own_metrics(tmp_path, monkeypatch):
    """This file SAVES governed metrics; the session-shared registry file must not
    carry them into other tests' expectations (the dedup suite counts raw rows)."""
    monkeypatch.setenv("AUGHOR_METRICS_PATH", str(tmp_path / "metrics.json"))


@pytest.fixture()
def client():
    from aughor.api import app
    return TestClient(app)


_COND = [{"kind": "schedule", "config": {"cron": "0 9 * * *"}}]


def _register_conn(tmp_path, *, with_null: bool):
    from aughor.db import registry
    p = tmp_path / "hb2.duckdb"
    con = duckdb.connect(str(p))
    con.execute("CREATE TABLE orders (order_id INT, total_amount DOUBLE, status TEXT)")
    con.execute("INSERT INTO orders VALUES (1, 120.0, 'complete'), (2, 80.0, 'complete')")
    if with_null:
        con.execute("INSERT INTO orders VALUES (3, NULL, 'complete')")
    con.close()
    return registry.add_connection("hb2-receipt", "duckdb", str(p))


def _governed_revenue(conn_id: str):
    save_metric(MetricDefinition(
        name="revenue", connection=conn_id, label="Revenue", sql="SUM(total_amount)",
        tables=["orders"],
        quality_tests=["SELECT COUNT(*) = 0 FROM orders WHERE total_amount IS NULL"],
        approved_by="Finance"))


def _slack_chain(conn_id: str, text: str, **auto_kw) -> tuple[Effect, Automation]:
    effect = Effect(kind="slack_post",
                    config={"bot_id": "sb_missing", "channel": "#ops", "message": text})
    auto = Automation(id=auto_kw.pop("id", "hb2auto"), conn_id=conn_id,
                      name="HB2 receipt chain", conditions=_COND,
                      effects=[effect], **auto_kw)
    return effect, auto


# ── receipt, first sentence: held at departure by a failing tie-out ───────────────

def test_a_failing_tieout_holds_the_send_with_the_reason_recorded(tmp_path):
    conn_id = _register_conn(tmp_path, with_null=True)   # a NULL total_amount exists
    _governed_revenue(conn_id)
    text = "Revenue reached 200.0 this week, led by repeat customers."
    effect, auto = _slack_chain(conn_id, text)

    out = _dispatch_slack_post(effect, auto)

    assert out.status == "held"
    assert "tie-out" in out.message and "revenue" in out.message
    rows = ds.list_departures(automation_id=auto.id, state="held")
    assert rows and "FAILED" in rows[0]["checks"]
    # the screen's copy is untouched — the gate held the DEPARTURE, not the report
    assert "NOT reliable" not in text


def test_the_same_send_departs_once_the_tieout_passes(tmp_path):
    conn_id = _register_conn(tmp_path, with_null=False)  # clean data, same test
    _governed_revenue(conn_id)
    effect, auto = _slack_chain(conn_id, "Revenue reached 200.0 this week.")

    out = _dispatch_slack_post(effect, auto)

    # past the gate: the dispatcher proceeds to the transport and fails on the missing
    # bot — which is exactly the proof the departure was NOT held.
    assert out.status == "dispatch_error" and "unknown Slack bot" in out.message
    rows = ds.list_departures(automation_id=auto.id)
    assert rows and rows[0]["state"] == "departed"


# ── receipt, second sentence: probation reaches only the declarer, then graduates ──

def test_probation_send_lands_on_the_declarers_queue_not_the_channel(tmp_path):
    conn_id = _register_conn(tmp_path, with_null=False)
    effect, auto = _slack_chain(conn_id, "All quiet this week.",
                                id="hb2prob", probation=True, declared_by="user:ana")
    out = _dispatch_slack_post(effect, auto)
    assert out.status == "held"
    assert "probation" in out.message and "user:ana" in out.message
    rows = ds.list_departures(automation_id="hb2prob", state="held_probation")
    assert rows and rows[0]["addressed_to"] == "user:ana"


def test_five_accepted_marks_graduate_and_the_next_send_reaches_the_transport(
        tmp_path, client):
    conn_id = _register_conn(tmp_path, with_null=False)
    effect, auto = _slack_chain(conn_id, "All quiet.", id="hb2grad",
                                probation=True, declared_by="user:ana")
    upsert_automation(auto)   # graduation flips the STORE row; the engine reads models

    ids = []
    for _ in range(5):
        out = _dispatch_slack_post(effect, get_automation("hb2grad"))
        assert out.status == "held"
        ids.append(ds.list_departures(automation_id="hb2grad",
                                      state="held_probation")[0]["id"])

    last = None
    for i, dep_id in enumerate(dict.fromkeys(ids)):
        last = client.post(f"/departures/{dep_id}/verdict",
                           json={"verdict": "accept"}).json()
    assert last["graduated"] is True
    assert get_automation("hb2grad").probation is False

    out = _dispatch_slack_post(effect, get_automation("hb2grad"))
    assert out.status == "dispatch_error"     # past the gate, onto the transport


# ── probation lifecycle at the store and the doors ────────────────────────────────

def test_create_door_declares_and_probates(client, tmp_path, monkeypatch):
    from aughor.org.context import set_user_id
    token = set_user_id("ana")
    try:
        resp = client.post("/automations", json={
            "conn_id": "any", "name": "born through the door",
            "conditions": [{"kind": "schedule", "config": {"cron": "0 9 * * *"}}],
            "effects": [{"kind": "notify", "config": {"trigger_id": "t1"}}]})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["probation"] is True and body["declared_by"] == "user:ana"
    finally:
        from aughor.org.context import reset_user_id
        reset_user_id(token)


def test_upsert_preserves_probation_and_declarer():
    a = Automation(id="hb2keep", conn_id="c", name="keeper", conditions=_COND,
                   effects=[Effect(kind="notify", config={"trigger_id": "t"})],
                   probation=True, declared_by="user:ana")
    upsert_automation(a)
    # an authoring save carrying neither field must erase neither
    edited = a.model_copy(update={"name": "renamed", "probation": False,
                                  "declared_by": "user:mallory"})
    saved = upsert_automation(edited)
    assert saved.probation is True                  # lifecycle: preserved
    assert saved.declared_by == "user:ana"          # birth fact: first writer wins
    assert saved.name == "renamed"                  # the authoring change itself lands
    set_probation("hb2keep", False)
    assert get_automation("hb2keep").probation is False


def test_manual_graduation_door(client):
    a = Automation(id="hb2hand", conn_id="c", name="hand", conditions=_COND,
                   effects=[Effect(kind="notify", config={"trigger_id": "t"})],
                   probation=True, declared_by="user:ana")
    upsert_automation(a)
    resp = client.post("/automations/hb2hand/graduate")
    assert resp.status_code == 200 and resp.json()["probation"] is False
    assert get_automation("hb2hand").probation is False
