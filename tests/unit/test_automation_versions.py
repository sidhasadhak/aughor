"""Arc TC, TC-3 — versions for automations and monitors, a run that names its own, and a replay.

What these hold (part of the platform since 2026-10-28):

* **Every save keeps the definition before it**, numbered, with who saved it and when —
  superseded in the ledger, never deleted. Saving the same definition twice keeps one version,
  and lifecycle (pausing, switching off) is not a version at all. A chain saved before versions
  began keeps its earlier definition at its first save since.
* **A save that cannot keep its version is refused** and writes nothing: the store never holds a
  definition whose version was not kept.
* **Every recorded run names the version it ran under and keeps its trigger** — the tick, who
  asked, each condition's verdict and the payload a trigger handed the chain, capped at 16 KB with
  the cap said. A monitor's run names the MONITOR's version.
* **A past run replays as a dry run** of its own version against its kept trigger: nothing is
  dispatched, nothing is written, and a step bound to `trigger.<key>` reads the value that run
  read. A replay whose version or payload was not kept is refused by name.

What was saved and run before versions began — every chain on the live install until 2026-10-28 — is stood in for by
`_before_versions`, which keeps nothing, as the platform did then.
"""
from __future__ import annotations

import contextlib
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from aughor.automations import versions as V
from aughor.automations.engine import evaluate_conditions, run_automation
from aughor.automations.models import Automation, Condition, Effect, EffectOutcome
from aughor.automations.store import (
    get_automation,
    get_run,
    get_run_stamp,
    get_runs,
    pause_automation,
    set_automation_enabled,
    upsert_automation,
)
from aughor.kernel.ledger import Ledger
from aughor.monitors.models import Monitor
from aughor.monitors.store import set_monitor_enabled, upsert_monitor

NOW = datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)


@contextlib.contextmanager
def _before_versions(monkeypatch):
    """A save or a run as it was before versions began: nothing kept, no version and no stamp."""
    with monkeypatch.context() as m:
        m.setattr(V, "keep_automation_version", lambda automation: None)
        m.setattr(V, "keep_monitor_version", lambda monitor: None)
        m.setattr(V, "version_for_run", lambda automation: {})
        m.setattr(V, "keep_run", lambda run, kept: None)
        yield


def _auto(name="Refund watch", conn_id="conn-tc3", **kw) -> Automation:
    base = dict(conn_id=conn_id, name=name, max_retries=0, retry_backoff_seconds=0.0,
                conditions=[Condition(kind="schedule", config={"cron": "0 9 * * *"})],
                effects=[Effect(kind="notify", config={"trigger_id": "t1"})])
    base.update(kw)
    return Automation(**base)


def _promise_auto(**kw) -> Automation:
    """A chain whose one step binds the trigger's payload — what a replay must hand back."""
    return _auto(conditions=[Condition(kind="promise_breached", config={"process": "p"})],
                 effects=[Effect(kind="slack_post", config={
                     "bot_id": "b1", "channel": {"$from": "trigger.about"},
                     "message": {"$from": "trigger.breach_rate", "$as": "text"}})], **kw)


def _probe(payload=None, fired=True):
    def probe(cond, automation):
        if payload is None:
            return fired, f"{cond.kind}: {'fired' if fired else 'quiet'}"
        return fired, f"{cond.kind}: fired", payload
    return probe


def _stub(calls=None):
    def dispatch(effect, automation):
        if calls is not None:
            calls.append(dict(effect.config))
        return EffectOutcome(kind=effect.kind, target="stub", status="executed")
    return dispatch


def _versions(automation_id: str) -> list[dict]:
    return V.history(V.AUTOMATION_KIND, automation_id, None)["versions"]


def _artifact_count() -> int:
    led = Ledger.default()
    with led._lock:
        return int(led._conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0])


# ── every save keeps the definition before it ────────────────────────────────────

def test_every_save_keeps_the_earlier_definition_numbered_with_who_and_when():
    from aughor.org.context import reset_actor, set_actor
    token = set_actor("amit")
    try:
        a = upsert_automation(_auto())
        upsert_automation(a.model_copy(update={
            "effects": [Effect(kind="notify", config={"trigger_id": "t2"})]}))
    finally:
        reset_actor(token)

    vs = _versions(a.id)
    assert [v["version"] for v in vs] == [2, 1], "newest first, numbered from one"
    assert vs[1]["definition"]["effects"][0]["config"] == {"trigger_id": "t1"}
    assert vs[0]["definition"]["effects"][0]["config"] == {"trigger_id": "t2"}
    assert vs[1]["superseded_by"] == vs[0]["version_id"], "superseded, never deleted"
    assert {v["saved_by"] for v in vs} == {"user:amit"}
    assert all(v["saved_at"] and v["source"] == V.SAVED for v in vs)
    current = V.history(V.AUTOMATION_KIND, a.id, V.automation_definition(get_automation(a.id)))
    assert current["current_version"] == 2 and current["current_kept"]


def test_saving_the_same_definition_twice_keeps_one_version():
    a = upsert_automation(_auto())
    upsert_automation(a)
    upsert_automation(get_automation(a.id))
    assert [v["version"] for v in _versions(a.id)] == [1]


def test_lifecycle_is_not_a_version():
    """Pausing, switching off and on, an expiry: the chain did not change, so no version."""
    a = upsert_automation(_auto())
    pause_automation(a.id, "2027-01-01T00:00:00Z")
    set_automation_enabled(a.id, False)
    upsert_automation(get_automation(a.id).model_copy(update={
        "enabled": True, "paused_until": None, "expires_at": "2027-06-01T00:00:00Z"}))
    assert [v["version"] for v in _versions(a.id)] == [1]


def test_a_chain_saved_before_versions_keeps_its_earlier_definition_at_its_first_save_since(monkeypatch):
    with _before_versions(monkeypatch):
        a = upsert_automation(_auto())
    assert _versions(a.id) == []
    upsert_automation(a.model_copy(update={
        "effects": [Effect(kind="notify", config={"trigger_id": "t2"})]}))
    vs = _versions(a.id)
    assert [(v["version"], v["source"]) for v in vs] == [(2, V.SAVED), (1, V.BEFORE_VERSIONS)]
    assert vs[1]["definition"]["effects"][0]["config"] == {"trigger_id": "t1"}
    assert vs[1]["saved_by"] == "", "nobody is named for a save nobody recorded"


def test_a_save_whose_version_cannot_be_kept_is_refused_and_writes_nothing(monkeypatch):
    a = upsert_automation(_auto())

    def broken(self, *args, **kwargs):
        raise RuntimeError("ledger is read-only")
    monkeypatch.setattr(Ledger, "artifact_write", broken)
    with pytest.raises(V.VersionNotKept, match="its version could not be kept"):
        upsert_automation(a.model_copy(update={"name": "Renamed"}))
    assert get_automation(a.id).name == "Refund watch", "the row was replaced without its version"


# ── a run names its version and keeps its trigger ────────────────────────────────

def test_every_run_names_its_version_and_keeps_its_trigger():
    a = upsert_automation(_promise_auto())
    payload = {"about": "promise:p.d", "breach_rate": 0.0935}
    first = run_automation(a, now=NOW, probe=_probe(payload), dispatch=_stub())
    assert first.outcome == "fired", first.reason
    stamp = get_run_stamp(first.id)
    assert stamp["version"] == 1 and stamp["version_id"]
    trig = stamp["trigger"]
    assert trig["at"] == "2026-10-26T09:00:00Z" and trig["via"] == "tick"
    assert trig["conditions"] == [{"kind": "promise_breached", "held": True,
                                   "detail": "promise_breached: fired"}]
    assert trig.get("data") == payload and not stamp["trigger_capped"]

    v2 = upsert_automation(a.model_copy(update={"name": "Renamed"}))
    second = run_automation(v2, now=NOW, probe=_probe(payload), dispatch=_stub(), manual=True,
                            via="webhook")
    assert get_run_stamp(second.id)["version"] == 2
    assert get_run_stamp(second.id)["trigger"]["via"] == "webhook"
    assert get_run_stamp(first.id)["version"] == 1, "a run keeps the version it ran under"


def test_a_definition_no_save_kept_is_kept_when_it_runs(monkeypatch):
    with _before_versions(monkeypatch):
        a = upsert_automation(_auto())
    run = run_automation(a, now=NOW, probe=_probe(), dispatch=_stub(), manual=True)
    assert get_run_stamp(run.id)["version"] == 1
    assert [(v["version"], v["source"]) for v in _versions(a.id)] == [(1, V.KEPT_AT_RUN)]


def test_the_trigger_payload_is_capped_and_the_cap_said():
    a = upsert_automation(_promise_auto())
    big = {"about": "promise:p.d", "breach_rate": 0.1, "segment": "x" * (V.TRIGGER_CAP_BYTES + 10)}
    run = run_automation(a, now=NOW, probe=_probe(big), dispatch=_stub())
    stamp = get_run_stamp(run.id)
    assert stamp["trigger_capped"] is True
    assert stamp["trigger_bytes"] > V.TRIGGER_CAP_BYTES
    assert stamp["trigger"]["data"] == {}
    assert stamp["trigger"]["data_keys"] == ["about", "breach_rate", "segment"]
    with pytest.raises(V.NotReplayable, match=r"not kept whole: it was [\d,]+ bytes, over the 16,384 kept"):
        V.replay(get_run(run.id))


def test_a_gated_run_keeps_its_gate_and_its_replay_is_refused_by_name():
    a = upsert_automation(_auto(enabled=False))
    run = run_automation(a, now=NOW, probe=_probe(), dispatch=_stub())
    assert run.outcome == "gated"
    assert get_run_stamp(run.id)["trigger"]["gated"] == "disabled"
    with pytest.raises(V.NotReplayable, match=r"stopped before its trigger was read \(disabled\)"):
        V.replay(get_run(run.id))


def test_a_run_from_before_versions_is_refused_by_name(monkeypatch):
    with _before_versions(monkeypatch):
        a = upsert_automation(_auto())
        run = run_automation(a, now=NOW, probe=_probe(), dispatch=_stub(), manual=True)
    with pytest.raises(V.NotReplayable, match="it ran before versions were kept"):
        V.replay(get_run(run.id))


def test_a_runs_stamp_goes_with_its_run_and_a_removed_connection_takes_its_versions():
    from aughor.automations.store import delete_automation, purge_connection
    a = upsert_automation(_auto(conn_id="conn-tc3-del"))
    one = run_automation(a, now=NOW, probe=_probe(), dispatch=_stub(), manual=True)
    assert get_run_stamp(one.id) is not None
    delete_automation(a.id)
    assert get_run_stamp(one.id) is None, "a deleted automation's run left its stamp behind"
    assert _versions(a.id), "supersede, never delete: the automation's versions stay"

    b = upsert_automation(_auto(conn_id="conn-tc3-gone"))
    two = run_automation(b, now=NOW, probe=_probe(), dispatch=_stub(), manual=True)
    purge_connection("conn-tc3-gone")
    Ledger.default().purge_connection("conn-tc3-gone")
    assert get_run_stamp(two.id) is None, "a removed connection left a run's stamp behind"
    assert _versions(b.id) == [], "a removed connection left its automation's versions behind"


# ── replay ───────────────────────────────────────────────────────────────────────

def _no_dispatch(monkeypatch):
    """Every real dispatcher raises: a replay that reached one would fail the test loudly."""
    from aughor.automations import engine

    def refuse(effect, automation):
        raise AssertionError(f"a replay dispatched {effect.kind}")
    monkeypatch.setattr(engine, "_DISPATCHERS", {k: refuse for k in engine._DISPATCHERS})
    monkeypatch.setattr(engine, "default_dispatch", refuse)


def test_a_replay_walks_its_own_version_against_its_kept_trigger_and_sends_nothing(monkeypatch):
    a = upsert_automation(_promise_auto())
    payload = {"about": "promise:p.d", "breach_rate": 0.0935}
    sent: list[dict] = []
    past = run_automation(a, now=NOW, probe=_probe(payload), dispatch=_stub(sent))
    assert sent and sent[0]["channel"] == "promise:p.d"
    # The chain changes after the run: the replay must walk the version the run ran under.
    upsert_automation(a.model_copy(update={"name": "Now different", "effects": [
        Effect(kind="notify", config={"trigger_id": "t2"})]}))

    _no_dispatch(monkeypatch)
    runs_before, artifacts_before = len(get_runs(automation_id=a.id, limit=500)), _artifact_count()
    automation, dry, version = V.replay(get_run(past.id))

    assert version == 1 and automation.name == "Refund watch"
    assert dry.outcome == "fired" and dry.reason.startswith("replay — nothing was sent")
    assert dry.conditions_fired == ["promise_breached: fired"]
    assert [(o.kind, o.status) for o in dry.effects] == [("slack_post", "executed")]
    # The kept payload reached the step: the channel it would have posted to is the run's own.
    assert dry.effects[0].message.startswith("would run → promise:p.d")
    assert len(get_runs(automation_id=a.id, limit=500)) == runs_before, "a replay wrote a run"
    assert get_run_stamp(dry.id) is None, "a replay kept a stamp"
    assert _artifact_count() == artifacts_before, "a replay wrote to the ledger"


def test_without_the_kept_trigger_the_same_dry_run_cannot_read_it():
    """The contrast that makes the replay worth having: an ordinary dry run has no payload, so a
    step bound to the trigger reads nothing."""
    dry = run_automation(_promise_auto(), dry_run=True)
    assert dry.effects[0].status == "skipped"


def test_a_replay_is_always_a_dry_run_even_when_the_caller_does_not_say_so():
    called: list = []
    trigger = {"at": "2026-10-26T09:00:00Z", "via": "tick",
               "conditions": [{"kind": "schedule", "held": True, "detail": "due"}], "data": {}}
    run = run_automation(_auto(), replay=trigger, dispatch=_stub(called))
    assert called == [], "a replay reached the dispatcher it was handed"
    assert run.effects[0].message.startswith("would run")


def test_a_replay_re_reads_the_kept_verdicts_under_the_versions_logic():
    both = [Condition(kind="schedule", config={"cron": "0 9 * * *"}),
            Condition(kind="metric", config={"monitor_id": "m1"})]
    trigger = {"at": "2026-10-26T09:00:00Z", "via": "tick", "data": {},
               "conditions": [{"kind": "schedule", "held": True, "detail": "due"},
                              {"kind": "metric", "held": False, "detail": "metric(m1): no alert"}]}
    quiet = run_automation(_auto(conditions=both, condition_logic="all"), replay=trigger)
    assert quiet.outcome == "not_fired" and quiet.effects == []
    assert "metric(m1): no alert" in quiet.reason
    loud = run_automation(_auto(conditions=both, condition_logic="any"), replay=trigger)
    assert loud.outcome == "fired" and loud.conditions_fired == ["due"]


# ── monitors ─────────────────────────────────────────────────────────────────────

def _monitor(**kw) -> Monitor:
    base = dict(conn_id="conn-tc3", name="Revenue drop", custom_sql="SELECT 1",
                check_cron="0 * * * *", alert_on="threshold_cross", warning_threshold=10.0)
    base.update(kw)
    return Monitor(**base)


def test_a_monitor_save_keeps_versions_and_switching_it_off_is_not_one():
    m = upsert_monitor(_monitor())
    upsert_monitor(m.model_copy(update={"warning_threshold": 20.0}))
    set_monitor_enabled(m.id, False)
    vs = V.history(V.MONITOR_KIND, m.id, None)["versions"]
    assert [v["version"] for v in vs] == [2, 1]
    assert [v["definition"]["warning_threshold"] for v in vs] == [20.0, 10.0]


def test_a_monitors_run_names_the_monitors_version_and_replays_as_it(monkeypatch):
    from aughor.automations.adopt import monitor_as_automation
    m = upsert_monitor(_monitor())
    run = run_automation(monitor_as_automation(m), now=NOW, dispatch=_stub())
    assert run.outcome == "fired", run.reason
    stamp = get_run_stamp(run.id)
    assert stamp["version"] == 1
    assert Ledger.default().artifact_by_id(stamp["version_id"])["kind"] == V.MONITOR_KIND

    upsert_monitor(m.model_copy(update={"name": "Renamed", "warning_threshold": 20.0}))
    _no_dispatch(monkeypatch)
    automation, dry, version = V.replay(get_run(run.id))
    assert version == 1 and automation.name == "Revenue drop" and automation.id == f"monitor:{m.id}"
    assert [(o.kind, o.status) for o in dry.effects] == [("monitor", "executed")]


# ── a verdict list ───────────────────────────────────────────────────────────────

def test_evaluate_conditions_answers_the_same_with_a_verdict_list():
    a = _auto(conditions=[Condition(kind="metric", config={"monitor_id": "m1"})])
    plain = evaluate_conditions(a, now=NOW, probe=_probe(fired=False))
    collected: list = []
    with_list = evaluate_conditions(a, now=NOW, probe=_probe(fired=False), verdicts=collected)
    assert plain == with_list
    assert collected == [{"kind": "metric", "held": False, "detail": "metric: quiet"}]


# ── the doors ────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    from aughor.api import app
    return TestClient(app)


BODY = {"conn_id": "conn-tc3-api", "name": "Refund watch",
        "conditions": [{"kind": "schedule", "config": {"cron": "0 9 * * *"}}],
        "effects": [{"kind": "notify", "config": {"trigger_id": "t1"}}]}


def test_the_doors_read_versions_a_runs_stamp_and_replay_it(client):
    aid = client.post("/automations", json=BODY).json()["id"]
    changed = {**BODY, "effects": [{"kind": "notify", "config": {"trigger_id": "t2"}}]}
    assert client.put(f"/automations/{aid}", json=changed).status_code == 200

    vs = client.get(f"/automations/{aid}/versions").json()
    assert [v["version"] for v in vs["versions"]] == [2, 1] and vs["current_version"] == 2

    run = run_automation(get_automation(aid), now=NOW, probe=_probe(), dispatch=_stub(),
                         manual=True)
    kept = client.get(f"/automations/runs/{run.id}/version").json()
    assert kept["kept"] and kept["version"] == 2 and kept["replayable"]
    assert kept["trigger"]["via"] == "hand" and kept["cap_bytes"] == V.TRIGGER_CAP_BYTES
    assert client.get(f"/automations/{aid}/runs").json()["runs"][0]["version"] == 2

    replayed = client.post(f"/automations/runs/{run.id}/replay")
    assert replayed.status_code == 200
    body = replayed.json()
    assert body["replay_of"] == run.id and body["version"] == 2
    assert body["run"]["outcome"] == "fired" and body["graph"]["dry_run"] is True

    assert client.post("/automations/runs/no-such-run/replay").status_code == 404


def test_a_replay_of_a_run_that_kept_nothing_is_a_409_that_says_why(client, monkeypatch):
    with _before_versions(monkeypatch):
        aid = client.post("/automations", json=BODY).json()["id"]
        run = run_automation(get_automation(aid), now=NOW, probe=_probe(), dispatch=_stub(),
                             manual=True)
    refused = client.post(f"/automations/runs/{run.id}/replay")
    assert refused.status_code == 409
    assert "it ran before versions were kept" in refused.json()["detail"]
    view = client.get(f"/automations/runs/{run.id}/version").json()
    assert view["kept"] is False and "before versions were kept" in view["why_not"]


def test_a_save_that_cannot_keep_its_version_is_a_503(client, monkeypatch):
    aid = client.post("/automations", json=BODY).json()["id"]

    def broken(self, *args, **kwargs):
        raise RuntimeError("ledger is read-only")
    monkeypatch.setattr(Ledger, "artifact_write", broken)
    resp = client.put(f"/automations/{aid}", json={**BODY, "name": "Renamed"})
    assert resp.status_code == 503 and "its version could not be kept" in resp.json()["detail"]
    assert get_automation(aid).name == "Refund watch"


def test_a_monitors_versions_door(client):
    m = upsert_monitor(_monitor())
    upsert_monitor(m.model_copy(update={"warning_threshold": 20.0}))
    body = client.get(f"/monitors/{m.id}/versions").json()
    assert [v["version"] for v in body["versions"]] == [2, 1] and body["current_version"] == 2
