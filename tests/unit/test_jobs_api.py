"""The /jobs Fleet surface (R2) — list/get/logs/cancel over the kernel ledger,
with agent enrichment + per-run cost. Jobs are seeded with unique conn_ids so the
assertions are isolated from any real jobs the app's lifespan may have started.
"""
import json

from aughor.kernel.ledger import Ledger


def _seed_job(jid, kind, state, conn_id, *, metrics=None, payload=None, finished=True):
    led = Ledger.default()
    led.job_insert({
        "id": jid, "kind": kind, "state": state, "attempt": 1,
        "conn_id": conn_id, "payload": payload,
        "created_at": "2026-01-01T00:00:00+00:00",
        "started_at": "2026-01-01T00:00:00+00:00",
        "finished_at": "2026-01-01T00:00:01+00:00" if finished else None,
    })
    if metrics is not None:
        led.job_update(jid, metrics=json.dumps(metrics))


def test_list_enriches_agent_cost_and_title(client):
    _seed_job("fleet_inv", "investigation", "SUCCEEDED", "fleet_inv_conn",
              metrics={"total_tokens": 1234, "query_count": 3, "rows_returned": 50},
              payload={"question": "why did margin drop?"})
    rows = client.get("/jobs", params={"conn_id": "fleet_inv_conn"}).json()
    assert len(rows) == 1
    j = rows[0]
    assert j["agent"]["agent"] == "Analyst"
    assert j["title"] == "why did margin drop?"
    assert j["cost"]["total_tokens"] == 1234
    assert j["duration_ms"] == 1000.0


def test_exploration_maps_to_scout(client):
    _seed_job("fleet_exp", "exploration", "RUNNING", "fleet_scout_conn", finished=False)
    j = client.get("/jobs", params={"conn_id": "fleet_scout_conn"}).json()[0]
    assert j["agent"]["agent"] == "Scout"
    assert j["title"].startswith("Exploring")
    assert j["cost"] is None and j["duration_ms"] is None  # running, unmetered yet


def test_active_filter_excludes_terminal(client):
    _seed_job("fleet_run", "exploration", "RUNNING", "fleet_active_conn", finished=False)
    _seed_job("fleet_done", "exploration", "SUCCEEDED", "fleet_active_conn")
    ids = {j["id"] for j in client.get(
        "/jobs", params={"conn_id": "fleet_active_conn", "state": "active"}).json()}
    assert "fleet_run" in ids and "fleet_done" not in ids


def test_get_job_and_404(client):
    _seed_job("fleet_one", "investigation", "SUCCEEDED", "fleet_get_conn")
    assert client.get("/jobs/fleet_one").json()["id"] == "fleet_one"
    assert client.get("/jobs/does_not_exist").status_code == 404


def test_job_logs_returns_journal_slice(client):
    _seed_job("fleet_log", "investigation", "SUCCEEDED", "fleet_log_conn")
    Ledger.default().emit("phase.start", {"phase": "intake"}, job_id="fleet_log")
    kinds = [e["kind"] for e in client.get("/jobs/fleet_log/logs").json()]
    assert "phase.start" in kinds


def test_cancel_unknown_is_404(client):
    assert client.post("/jobs/nope/cancel").status_code == 404
