"""The cron tick: auth contract, due-this-minute semantics, fault-isolated families."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aughor.routers import cron as C


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(C.router)
    return TestClient(app)


def test_due_in_window_semantics():
    now = datetime(2026, 8, 6, 9, 30, 12, tzinfo=timezone.utc)
    assert C._due_in_window("30 9 * * *", now, 60) is True     # fires 09:30
    assert C._due_in_window("31 9 * * *", now, 60) is False    # fires 09:31 — not yet
    assert C._due_in_window("*/7 * * * *", now, 60) is False   # 09:28 outside a 60s window
    assert C._due_in_window("*/7 * * * *", now, 600) is True   # inside a 10-min window
    assert C._due_in_window("0 9 * * *", now, 86400) is True   # daily floor catches 09:00
    assert C._due_in_window("not a cron", now, 60) is False    # unparseable → skipped


def test_secret_required_when_configured(client, monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "s3cret")
    assert client.get("/cron/tick").status_code == 401
    assert client.get("/cron/tick", headers={"Authorization": "Bearer wrong"}).status_code == 401
    r = client.get("/cron/tick", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200 and r.json()["ok"] is True


def test_unconfigured_secret_refuses_on_vercel_but_allows_locally(client, monkeypatch):
    monkeypatch.delenv("CRON_SECRET", raising=False)
    monkeypatch.setenv("VERCEL", "1")
    assert client.get("/cron/tick").status_code == 403        # never an open faucet
    monkeypatch.delenv("VERCEL", raising=False)
    assert client.get("/cron/tick").status_code == 200        # local/manual tick


def test_tick_runs_due_families_and_reports_counts(client, monkeypatch):
    monkeypatch.delenv("CRON_SECRET", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)

    ran: dict[str, list] = {"monitors": [], "briefs": [], "auto": []}

    from aughor.automations import scheduler as auto_sched
    monkeypatch.setattr(auto_sched, "tick_once", lambda: ran["auto"].append(1))

    class _Mon:
        id, enabled, check_cron = "m1", True, "* * * * *"     # always due

    class _MonOff:
        id, enabled, check_cron = "m2", False, "* * * * *"    # disabled → skipped

    from aughor.monitors import scheduler as mon_sched, store as mon_store
    monkeypatch.setattr(mon_store, "list_monitors", lambda: [_Mon(), _MonOff()])
    monkeypatch.setattr(mon_sched, "run_monitor_job", lambda mid: ran["monitors"].append(mid))

    class _Sub:
        id, enabled = "s1", True
        def resolved_cron(self):
            return "0 0 1 1 *"                                 # never due today

    from aughor.briefing import scheduler as brief_sched, store as brief_store
    monkeypatch.setattr(brief_store, "list_subscriptions", lambda: [_Sub()])
    monkeypatch.setattr(brief_sched, "trigger_now", lambda sid: ran["briefs"].append(sid))

    body = client.get("/cron/tick").json()
    assert body["ok"] is True
    assert ran["auto"] == [1]
    assert ran["monitors"] == ["m1"]                           # due + enabled only
    assert ran["briefs"] == []                                 # not its minute
    assert body["counts"]["monitors_run"] == 1
    assert body["counts"]["briefs_delivered"] == 0
    assert "stale_jobs_swept" in body["counts"]
