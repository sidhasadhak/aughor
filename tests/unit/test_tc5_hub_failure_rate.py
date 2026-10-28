"""Arc TC, TC-5 — each node on the hub map says how often its runs failed over
a window, counted at the run store.

Three answers are kept apart and each is asserted as itself: a measured rate (a tick that broke,
or a run whose step failed, over every tick that started); "no runs" — never 0%, which would claim
a run that never happened succeeded; and "not permitted" — the node stays on the map with no
count, never dropped, because an absent node teaches the reader it does not exist.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from aughor.automations.models import Automation, AutomationRun, Condition, Effect, EffectOutcome
from aughor.automations.store import append_run, upsert_automation


@pytest.fixture()
def client():
    from aughor.api import app
    return TestClient(app)


def _conn() -> str:
    return f"tc5-hub-{uuid.uuid4().hex[:8]}"


def _automation(conn_id: str, name: str = "Nightly watch") -> Automation:
    return upsert_automation(Automation(
        id=f"tc5-{uuid.uuid4().hex[:10]}", conn_id=conn_id, name=name,
        conditions=[Condition(kind="schedule", config={"cron": "0 9 * * *"})],
        effects=[Effect(kind="slack_post", config={"bot_id": "b1", "channel": "#ops"})]))


def _run(a: Automation, outcome: str, *, days_ago: int = 0, step: str | None = None) -> None:
    at = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    append_run(AutomationRun(
        automation_id=a.id, automation_name=a.name, conn_id=a.conn_id, outcome=outcome,
        started_at=at,
        effects=[EffectOutcome(kind="slack_post", status=step)] if step else []))


def _rows(client, conn_id: str, **params) -> dict:
    body = client.get("/hub/map", params={"conn_id": conn_id, **params}).json()
    return {r["id"]: r for r in body["rows"]}


def test_a_measured_rate_counts_broken_ticks_and_failed_steps(client):
    """A failed step is recorded as a STATUS on a fired run, never as an `error` outcome, so a
    rate read off outcomes alone would say 0% for a chain whose every send failed."""
    conn_id = _conn()
    a = _automation(conn_id)
    for _ in range(3):
        _run(a, "not_fired")
    _run(a, "error")                          # the tick broke
    _run(a, "fired", step="failed")           # ran on, one step failed
    _run(a, "fired", step="executed")         # ran clean
    _run(a, "gated")                          # never started: neither ran nor failed

    rate = _rows(client, conn_id)[a.id]["failure_rate"]
    assert rate["state"] == "measured"
    assert rate["ran"] == 6 and rate["failed"] == 2 and rate["gated"] == 1
    assert rate["rate"] == pytest.approx(2 / 6, abs=1e-4)
    assert rate["label"] == "33% failed"
    assert rate["window_days"] == 7


def test_a_node_with_no_runs_says_no_runs_never_zero(client):
    """No runs in the window is not a 0% failure rate: a gated tick never started, and a run
    from before the window is outside it."""
    conn_id = _conn()
    a = _automation(conn_id)
    _run(a, "gated")
    _run(a, "error", days_ago=20)

    rate = _rows(client, conn_id)[a.id]["failure_rate"]
    assert rate["state"] == "no_runs"
    assert rate["rate"] is None, "no runs read as a rate"
    assert rate["label"] == "no runs"
    assert rate["gated"] == 1


def test_the_window_is_the_callers(client):
    conn_id = _conn()
    a = _automation(conn_id)
    _run(a, "error", days_ago=10)
    _run(a, "fired")

    week = _rows(client, conn_id)[a.id]["failure_rate"]
    fortnight = _rows(client, conn_id, window_days=14)[a.id]["failure_rate"]
    assert (week["ran"], week["failed"]) == (1, 0)
    assert (fortnight["ran"], fortnight["failed"]) == (2, 1)
    body = client.get("/hub/map", params={"conn_id": conn_id, "window_days": 14}).json()
    assert body["failure_window"]["days"] == 14 and body["failure_window"]["since"]
    assert client.get("/hub/map", params={"window_days": 0}).status_code == 422


def test_a_node_the_reader_may_not_see_says_not_permitted_and_stays(client, monkeypatch):
    """The reader's organisation does not hold this node's connection: the node stays on the map
    and its rate says not permitted, with no count — never dropped, never a number."""
    conn_id = _conn()
    mine, theirs = _automation(conn_id, "Mine"), _automation(_conn(), "Theirs")
    _run(mine, "fired")
    _run(theirs, "error")
    import aughor.security.authz as authz
    monkeypatch.setattr(authz, "org_visible_conn_ids", lambda: {conn_id})

    rows = _rows(client, "")
    assert theirs.id in rows, "a node the reader may not see was dropped from the map"
    withheld = rows[theirs.id]["failure_rate"]
    assert withheld["state"] == "not_permitted" and withheld["label"] == "not permitted"
    assert "ran" not in withheld and "failed" not in withheld and "rate" not in withheld
    assert rows[mine.id]["failure_rate"]["state"] == "measured"


def test_a_permission_check_that_cannot_run_withholds_and_says_why(client, monkeypatch):
    conn_id = _conn()
    a = _automation(conn_id)
    _run(a, "fired")

    def _broken():
        raise RuntimeError("registry down")

    import aughor.security.authz as authz
    monkeypatch.setattr(authz, "org_visible_conn_ids", _broken)
    rate = _rows(client, conn_id)[a.id]["failure_rate"]
    assert rate["state"] == "not_permitted"
    assert "could not be checked" in rate["why"]
