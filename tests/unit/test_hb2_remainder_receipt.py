"""HB-2 remainder — the wave's receipt, held as tests on every path information leaves by
(HB-1's precedent; the live drive wants the merged build):

  *every outbound transport asks the departure gate* — a monitor alert, a scheduled
  briefing, an agent alert, a person's Share and Execute, and the engine's Slack post and
  notify — and what departs carries its receipt ON the message;

  *the laws hold on real paths* — the 2026-09-16 dispatch watch's order count is held at
  departure; a finding whose number moved since it was found is held when a person shares
  it; a forecast recommendation does not leave; a briefing sends its sound lines and names
  how many it cut; a draft metric holds an alert;

  *an analysis that paused on divergent readings asks the owner* — the chain's send is held
  for the metric's owner with the readings, the answer is remembered, and nothing was sent.

The outbound HTTP (``fire_action``, ``post_as_bot``) is the one stub; stores, gate, ledger,
routers and engine are real.
"""
from __future__ import annotations

from types import SimpleNamespace

import duckdb
import pytest
from fastapi.testclient import TestClient

from aughor.automations.models import Automation, Condition, Effect
from aughor.govern import departure_store as ds
from aughor.govern.departure import Measurement
from aughor.util.time import now_iso_z

DISPATCH = "promise:order_to_delivery.dispatch"
LIVE_DISPATCH = (
    "⚠ Dispatch promise breached: 10,423 of 99,441 order lines (9.35%) missed the declared "
    "dispatch window, measured as of 2018-09-11 on the Olist connection. Declared segment: "
    "late_orders. This finding is filed on promise:order_to_delivery.dispatch — receipt: "
    "GET /links?object_ref=promise:order_to_delivery.dispatch")


@pytest.fixture(autouse=True)
def _own_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_DEPARTURES_DB", str(tmp_path / "departures.db"))
    monkeypatch.delenv("AUGHOR_WEB_URL", raising=False)


@pytest.fixture()
def client():
    from aughor.api import app
    return TestClient(app)


@pytest.fixture()
def sent(monkeypatch):
    """The ONE stub: what would have left through the Action Hub."""
    out: list = []

    def fake_fire(trigger, payload):
        out.append((trigger, payload))
        return SimpleNamespace(status="ok", error=None, http_status=200, id="log1",
                               resource_ref="", to_dict=lambda: {"status": "ok"})
    monkeypatch.setattr("aughor.notifications.executor.fire_action", fake_fire)
    return out


def _trigger(tid="tr_ops"):
    from aughor.notifications.models import ActionTrigger
    from aughor.notifications.store import save_trigger
    save_trigger(ActionTrigger(id=tid, name="#ops", type="webhook",
                               url="https://hooks.example.test/ops"))
    return tid


# ── a monitor alert ───────────────────────────────────────────────────────────────

def _alert(**kw):
    from aughor.monitors.models import MonitorAlert
    base = dict(id="al1", monitor_id="m1", monitor_name="Refund spike", conn_id="c1",
                metric_name="refunds", triggered_at=now_iso_z(), alert_on="threshold_cross",
                severity="critical", current_value=12.4, previous_value=8.0, threshold=10.0,
                message="refunds crossed its critical threshold")
    base.update(kw)
    return MonitorAlert(**base)


def test_a_monitor_alert_departs_with_its_receipt_on_the_payload(sent, monkeypatch):
    from aughor.monitors.notify import dispatch_alert
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda **_: [])
    tid = _trigger()
    dispatch_alert(_alert(), SimpleNamespace(id="m1", name="Refund spike",
                                             notification_channel=tid))
    assert len(sent) == 1
    receipt = sent[0][1].context["receipt_line"]
    assert receipt.startswith("Receipt: monitor 'Refund spike'")
    assert "defined by monitor 'Refund spike' (declared)" in receipt
    row = ds.list_departures(kind="monitor_alert")[0]
    assert row["state"] == "departed" and row["source_id"] == "m1"


def test_a_draft_metric_holds_the_alert_and_the_alert_row_stays(sent, monkeypatch):
    from aughor.monitors.notify import dispatch_alert
    draft = SimpleNamespace(name="refunds", label="Refunds", sql="SUM(refund)", tables=[],
                            dimensions=[], quality_tests=[], wrong_usage_examples=[],
                            status="draft", version=0)
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda **_: [draft])
    tid = _trigger()
    assert dispatch_alert(_alert(), SimpleNamespace(id="m1", name="Refund spike",
                                                    notification_channel=tid)) is None
    assert sent == []
    row = ds.list_departures(kind="monitor_alert")[0]
    assert row["state"] == "held" and "draft" in row["reasons"]


# ── a scheduled briefing ──────────────────────────────────────────────────────────

def test_a_briefing_sends_its_sound_lines_and_names_what_it_cut(sent, monkeypatch):
    from aughor.briefing.delivery import deliver_subscription
    from aughor.briefing.models import BriefSubscription
    from aughor.monitors.alert_summary import AlertSummary, AlertSummarySection

    brief = AlertSummary(conn_id="c1", period="week", generated_at=now_iso_z(), alert_count=1,
                         sections=[
        AlertSummarySection(title="Monitor Alerts", kind="monitor_alerts", items=[
            "🔴 [2026-09-16 08:00] Refund spike [critical]: 12.4 vs threshold 10"]),
        AlertSummarySection(title="Exploration Insights", kind="findings", items=[
            "APAC orders fell 12.5% on the outage day. (found 2026-09-15)",
            "Conversion rate was 3.4% yesterday. (found 2026-09-15)"]),
        AlertSummarySection(title="Top Causal Relationships", kind="causal_links", items=[
            "discount → refunds (strength: 0.62)", "carrier → late (strength: 0.41)"]),
    ])
    monkeypatch.setattr("aughor.monitors.alert_summary.build_alert_summary",
                        lambda conn_id, period: brief)
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda **_: [])
    sub = BriefSubscription(id="sub1", conn_id="c1", name="Weekly ops", trigger_id=_trigger())

    result = deliver_subscription(sub, persist=False)

    assert result["status"] == "ok", result
    body = sent[0][1].headline
    assert "APAC orders fell 12.5%" in body and "Refund spike" in body
    assert "Conversion rate" not in body and "strength" not in body
    assert "3 lines of this briefing did not leave the platform" in body
    assert "3 lines held at departure" in sent[0][1].context["receipt_line"]
    row = ds.get_departure(result["departure_id"])
    assert row["kind"] == "briefing" and row["checks"].count("causal relationship") == 2


# ── an agent alert ────────────────────────────────────────────────────────────────

def test_an_agent_alert_departs_with_its_receipt(sent):
    from aughor.obs.agent_alert_runner import deliver
    from aughor.obs.agent_alerts import AgentAlertEvent, AgentAlertRule
    rule = AgentAlertRule(id="r1", name="Error rate", metric="error_rate", comparator="gte",
                          threshold=0.2, window_minutes=1440, channel=_trigger())
    event = AgentAlertEvent(id="e1", rule_id="r1", metric="error_rate", severity="warning",
                            fired_at=now_iso_z(), value=0.25, threshold=0.2, population=40,
                            window_minutes=1440,
                            reason="error_rate=0.25 crosses >= 0.2 over 40 run(s) in 1440m")
    delivered, detail = deliver(event, rule)
    assert delivered, detail
    assert sent[0][1].context["receipt_line"].startswith("Receipt: alert rule 'Error rate'")


# ── a person's Share and Execute ──────────────────────────────────────────────────

def _warehouse(tmp_path, value: int) -> str:
    from aughor.db import registry
    path = tmp_path / f"share-{value}.duckdb"
    con = duckdb.connect(str(path))
    con.execute(f"CREATE TABLE weekly AS SELECT {value} AS orders")
    con.close()
    return registry.add_connection(f"share-{value}", "duckdb", str(path))


@pytest.mark.parametrize("now_value, expected", [(4100, "ok"), (4600, "held")])
def test_a_shared_finding_is_re_measured_at_departure(client, sent, monkeypatch, tmp_path,
                                                       now_value, expected):
    conn_id = _warehouse(tmp_path, now_value)
    monkeypatch.setattr("aughor.govern.departure_basis.find_finding",
                        lambda fid, cid: {"id": fid, "sql": "SELECT orders FROM weekly",
                                          "generated_at": "2026-09-01T00:00:00Z"})
    tid = _trigger()
    resp = client.post(f"/actions/triggers/{tid}/send", json={
        "text": "Orders reached 4,100 this week.", "source_id": "f1", "conn_id": conn_id})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == expected and body["departure_id"]
    row = ds.get_departure(body["departure_id"])
    assert row["origin"] == "person" and row["kind"] == "finding_share"
    if expected == "held":
        assert "re-measured at departure: 4,100 is not in finding f1" in body["error"]
        assert sent == []
    else:
        assert "re-executed at departure" in row["checks"]
        assert sent[0][1].context["receipt_line"].startswith("Receipt: finding f1")


def test_a_forecast_recommendation_does_not_leave(client, sent, monkeypatch):
    inv = {"id": "inv1", "connection_id": "c1", "headline": "Volume is climbing",
           "report_json": {"recommended_actions": [
               "Order volume is on track to double next quarter; add warehouse staff."]}}
    monkeypatch.setattr("aughor.db.history.get_investigation", lambda _id: dict(inv))
    tid = _trigger()
    resp = client.post("/investigations/inv1/recommendations/0/execute", json={"trigger_id": tid})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "held" and "a forecast never departs" in body["error"]
    assert sent == []


# ── the engine: the anchor, and the owner asked ───────────────────────────────────

def _olist_stamp(_about, _conn):
    return Measurement(source="promise dispatch of order_to_delivery",
                       values=[112650.0, 111456.0, 10423.0, 101033.0, 1194.0, 1193.0],
                       rates=[0.093517], measured_at="2026-09-13T00:05:20+00:00",
                       as_of="2018-09-11 19:48:28",
                       stale_note="a promise is re-measured by the ontology's measure pass")


@pytest.mark.parametrize("text, held", [(LIVE_DISPATCH, True),
                                         (LIVE_DISPATCH.replace("99,441", "111,456"), False)])
def test_the_dispatch_watch_is_held_for_stating_an_order_count_as_lines(monkeypatch, text, held):
    from aughor.automations.engine import _dispatch_slack_post
    monkeypatch.setattr("aughor.govern.departure_basis.measurement_for_promise", _olist_stamp)
    monkeypatch.setattr("aughor.govern.departure_basis.declared_thing",
                        lambda s, c: {"kind": "promise", "measured": True,
                                      "label": "promise dispatch of order_to_delivery"})
    effect = Effect(kind="slack_post", config={"bot_id": "sb_missing", "channel": "#canvas",
                                               "about": DISPATCH, "message": text})
    auto = Automation(id="watch", conn_id="baef6c3e", name="Dispatch promise watch",
                      conditions=[{"kind": "schedule", "config": {"cron": "0 9 * * *"}}],
                      effects=[effect])
    out = _dispatch_slack_post(effect, auto)
    if held:
        assert out.status == "held"
        assert "99,441 is not in promise dispatch of order_to_delivery" in out.message
    else:
        # past the gate: the dispatcher reached the transport and failed on the missing bot
        assert out.status == "dispatch_error", out.message
    row = ds.list_departures(automation_id="watch")[0]
    assert row["about"] == DISPATCH and row["as_of"] == "2018-09-11 19:48:28"


def test_an_analysis_paused_on_divergent_readings_asks_the_owner_and_sends_nothing(
        client, monkeypatch):
    from aughor.automations.engine import run_automation
    from aughor.automations.store import upsert_automation
    from aughor.runners.investigation import InvestigationRun

    readings = {
        "subject": "definition of refund rate", "metric_label": "refund rate",
        "metric_name": "refund_rate",
        "question": "“refund rate” can be computed two ways (2.10% vs 7.80%) — which?",
        "options": ["Governed: refund_rate", "As I read the question"],
        "previews": ["= 2.10%", "= 7.80%"],
        "readings": [{"label": "Governed: refund_rate", "sql": "SUM(refunds) / COUNT(*)"},
                     {"label": "As I read the question", "sql": "SUM(rv) / SUM(v)"}]}
    monkeypatch.setattr("aughor.runners.run_investigation",
                        lambda req, **kw: InvestigationRun(
                            "executed", "ran inline (caller waited)", basis="inline",
                            investigation_id="inv-paused", clarify=dict(readings)))
    monkeypatch.setattr("aughor.govern.departure_basis.owner_for_disagreement",
                        lambda d, c: "group:finance")
    posts: list = []
    monkeypatch.setattr("aughor.slackbots.post.post_as_bot",
                        lambda *a, **kw: posts.append(a) or (True, {"ts": "1"}))

    auto = upsert_automation(Automation(
        name="refund rate to Slack", conn_id="conn-law6-chain",
        conditions=[Condition(kind="schedule", config={"cron": "0 9 * * *"})],
        effects=[Effect(kind="investigate", alias="refunds",
                        config={"question": "what is the refund rate this week?"}),
                 Effect(kind="slack_post", alias="tell",
                        config={"bot_id": "sb_1", "channel": "#finance",
                                "message": {"$from": "refunds.summary"}})],
        max_retries=0))
    run = run_automation(auto, persist=True, manual=True, probe=lambda *x, **k: True,
                         sleeper=lambda _s: None, rng=lambda: 0.0)

    investigate, tell = run.effects[0], run.effects[1]
    assert "paused: the readings of refund rate disagree" in investigate.message
    assert tell.status == "held", tell.message
    assert "held for its owner" in tell.message and "group:finance is asked" in tell.message
    assert posts == []
    row = ds.list_departures(automation_id=auto.id)[0]
    assert row["state"] == "held_owner" and row["addressed_to"] == "group:finance"
    assert row["investigation_id"] == "inv-paused"

    answered = client.post(f"/departures/{row['id']}/answer",
                           json={"reading": "Governed: refund_rate"})
    assert answered.status_code == 200, answered.text
    from aughor.semantic.ambiguity_ledger import list_resolutions
    assert any(r.subject == "definition of refund rate"
               and r.resolved_reading == "Governed: refund_rate"
               for r in list_resolutions("conn-law6-chain"))


def test_the_runner_reports_a_pause_on_divergent_readings(monkeypatch):
    import json as _json

    from aughor.runners import InvestigationRequest, run_investigation

    frames = [{"type": "start", "investigation_id": "inv-p"},
              {"type": "clarify_pending", "investigation_id": "inv-p",
               "subject": "definition of refund rate", "metric_label": "refund rate",
               "metric_name": "refund_rate", "question": "which?",
               "options": ["a", "b"], "previews": ["= 1", "= 2"],
               "readings": [{"label": "a", "sql": "x"}, {"label": "b", "sql": "y"}]},
              {"type": "done"}]

    def fake_stream(req, request):
        async def _gen():
            for f in frames:
                yield f"data: {_json.dumps(f)}\n\n"
        return _gen()

    monkeypatch.setattr("aughor.routers.investigations.build_ask_stream", fake_stream)
    monkeypatch.setattr("aughor.db.history.get_investigation",
                        lambda _id: {"status": "paused"})
    run = run_investigation(InvestigationRequest(question="q", connection_id="c1", wait=True))
    assert run.status == "executed" and run.investigation_id == "inv-p"
    assert run.clarify["metric_name"] == "refund_rate"
    assert [r["label"] for r in run.clarify["readings"]] == ["a", "b"]
