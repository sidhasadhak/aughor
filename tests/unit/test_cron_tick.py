"""The cron tick: auth contract, one-loop delegation, fault isolation.

The per-family monitor/brief blocks (and their `_due_in_window` lookback) were deleted
with the legacy schedulers (flag endgame Wave 4, 2026-08-06): the tick now delegates to
the automation engine's `tick_once`, which carries monitors and briefs as virtual
automations and owns due-ness ("did the cron match since the last run"). Driving the
families here as well DOUBLE-DELIVERED briefs — the engine tick delivered, then the
brief family's `trigger_now` delivered again.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aughor.routers import cron as C


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(C.router)
    return TestClient(app)


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


def test_tick_runs_the_one_loop_and_reports_what_it_evaluated(client, monkeypatch):
    """ONE engine tick covers all three families; the endpoint reports the engine's
    own per-family evaluation counts rather than recomputing due-ness itself."""
    monkeypatch.delenv("CRON_SECRET", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)

    calls: list[int] = []

    from aughor.automations import scheduler as auto_sched

    def _tick_once():
        calls.append(1)
        return {"automations": 2, "monitors": 3, "briefs": 1}

    monkeypatch.setattr(auto_sched, "tick_once", _tick_once)

    body = client.get("/cron/tick").json()
    assert body["ok"] is True
    assert calls == [1], "exactly one engine tick per cron tick"
    assert body["counts"]["automations_tick"] == 1
    assert body["counts"]["monitors_evaluated"] == 3
    assert body["counts"]["briefs_evaluated"] == 1
    assert "stale_jobs_swept" in body["counts"]


def test_tick_survives_a_crashing_engine_tick(client, monkeypatch):
    """Fault isolation: a tick_once that raises must not take down the endpoint —
    the sweep and housekeeping families still run and the tick still answers."""
    monkeypatch.delenv("CRON_SECRET", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)

    from aughor.automations import scheduler as auto_sched
    monkeypatch.setattr(auto_sched, "tick_once",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    body = client.get("/cron/tick").json()
    assert body["ok"] is True
    assert "automations_tick" not in body["counts"]
    assert "stale_jobs_swept" in body["counts"]


def test_the_per_family_lookback_is_gone():
    """`_due_in_window` was the families' own due-ness clock; with due-ness owned by
    the engine (since-last-run), a revived copy here would be a second, disagreeing
    clock — the drift the collapse removed."""
    assert not hasattr(C, "_due_in_window")
