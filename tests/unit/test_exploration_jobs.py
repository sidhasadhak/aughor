"""The Explorer's jobs run apart, and the Catalog's doors set what they may do (exploration principles, 2026-10-08).

Decision 2: until a person sets a dataset's layer it gets structure learning only, "which spends no
model call" — so the structure job is run here on a real DuckDB file with every model door refusing.
And the datasets doors: the read the Catalog draws (layer, proposal with evidence, off, maturity,
budget), and the person's writes, recorded under the person signed in.
"""
from __future__ import annotations

import asyncio
import uuid

import duckdb
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aughor.db.connection import open_connection


@pytest.fixture
def wh(tmp_path):
    path = tmp_path / "wh.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE orders AS SELECT range AS id, range % 7 AS customer_id, "
                "CASE WHEN range % 5 = 0 THEN NULL ELSE 'paid' END AS status, range * 1.5 AS amount, "
                "DATE '2026-01-01' + CAST(range AS INTEGER) AS created_at FROM range(60)")
    con.execute("CREATE TABLE customers AS SELECT range AS id, 'c' || range AS name FROM range(7)")
    con.close()
    return f"wh-{uuid.uuid4().hex[:8]}", str(path)


def test_the_structure_job_learns_the_structure_and_calls_no_model(wh, monkeypatch):
    from aughor.explorer import program
    from aughor.explorer.agent import SchemaExplorer

    def no_model(*a, **k):
        raise AssertionError("the structure job called a model")

    monkeypatch.setattr("aughor.llm.provider.get_provider", no_model)
    conn_id, path = wh
    ex = SchemaExplorer(conn_id, open_connection("duckdb", path, connection_id=conn_id))
    ex.build_intelligence = no_model
    ex._conn.build_intelligence = no_model
    asyncio.run(ex._explore_run(structure_only=True, reason="structure learned; its questions wait"))

    assert ex._status.phase.value == "complete", ex._status.error
    assert ex._state["structure_learned"]["fp"] == ex._state["dataset_fingerprint"]
    assert ex._state["domain_intel_skipped"] is True
    assert "questions wait" in ex._state["domain_intel_note"]
    run = program.last_run(program.load(conn_id))
    assert run["job"] == "structure" and run["outcome"] == "complete"


@pytest.fixture
def client(monkeypatch):
    from aughor.routers import datasets as D
    monkeypatch.setattr(D, "_schemas_of", lambda conn_id: [
        {"name": "stage_marketing", "tables": [{"name": "stg_clicks"}, {"name": "stg_sessions"}]},
        {"name": "marts", "tables": [{"name": "fct_orders"}, {"name": "dim_calendar"}, {"name": "orders"}]}])
    monkeypatch.setattr("aughor.routers.datasets._questions_on_layer", lambda *a: "its questions have started")
    monkeypatch.setenv("AUGHOR_LOCAL_USER", "amit")
    app = FastAPI()
    app.include_router(D.router)
    return TestClient(app)


def test_the_catalog_read_proposes_each_layer_with_its_evidence(client):
    conn = f"c-{uuid.uuid4().hex[:6]}"
    got = client.get(f"/exploration/{conn}/datasets")
    assert got.status_code == 200, got.text
    body = got.json()
    by = {s["name"]: s for s in body["schemas"]}
    stage = by["stage_marketing"]["layer"]
    assert stage["set"] is None and stage["proposed"]["layer"] == "raw"
    assert "stage" in stage["proposed"]["evidence"][0]
    assert stage["jobs"] == ["structure"], "unset: structure only"
    assert "wait for a person" in stage["policy"]
    marts = {t["name"]: t for t in by["marts"]["tables"]}
    assert marts["dim_calendar"]["layer"]["proposed"] is None, "same as its schema's — said once"
    assert {"structure", "questions", "time"} == set(by["marts"]["maturity"]) - {"percent", "stage"}
    assert body["budget"]["sentence"] and [x["id"] for x in body["layers"]][0] == "business"


def test_a_person_sets_a_layer_accepts_the_rest_and_turns_one_off(client):
    conn = f"c-{uuid.uuid4().hex[:6]}"
    r = client.put(f"/exploration/{conn}/datasets/layer", json={"schema_name": "marts", "layer": "business"})
    assert r.status_code == 200, r.text
    assert r.json()["set_by"] == "amit" and r.json()["started"] == "its questions have started"
    assert client.put(f"/exploration/{conn}/datasets/layer",
                      json={"schema_name": "marts", "layer": "gold"}).status_code == 422

    acc = client.post(f"/exploration/{conn}/datasets/layers/accept", json={}).json()
    assert acc["accepted"] == [{"schema": "stage_marketing", "layer": "raw"}], "a layer already set is left"

    off = client.put(f"/exploration/{conn}/datasets/off",
                     json={"schema_name": "stage_marketing", "off": True, "reason": "out_of_domain"})
    assert off.status_code == 200 and off.json()["off"]["declared_by"] == "amit"
    from aughor.ontology.visibility import excluded
    assert excluded(conn, "stage_marketing", "stg_clicks") is not None
    body = client.get(f"/exploration/{conn}/datasets").json()
    stage = next(s for s in body["schemas"] if s["name"] == "stage_marketing")
    assert stage["off"]["reason"] == "out_of_domain" and stage["layer"]["set"]["layer"] == "raw"
    back = client.put(f"/exploration/{conn}/datasets/off", json={"schema_name": "stage_marketing", "off": False})
    assert back.status_code == 200 and excluded(conn, "stage_marketing", "stg_clicks") is None


def test_the_system_layer_is_never_read(client):
    conn = f"c-{uuid.uuid4().hex[:6]}"
    client.put(f"/exploration/{conn}/datasets/layer", json={"schema_name": "marts", "layer": "system"})
    from aughor.ontology.visibility import excluded
    hit = excluded(conn, "marts", "fct_orders")
    assert hit is not None and hit.reason == "system_table"


def test_a_heartbeats_budget_kill_is_a_budget_stop_not_a_persons(monkeypatch):
    """§1 measured it: the kernel's heartbeat enforces the run budget with a bare cancel, and the
    run wrote "budget exceeded or stopped" — which the continuous loop must read as a person's stop,
    so it was never continued. The kernel's own stop reason now tells them apart."""
    from aughor.explorer.agent import SchemaExplorer
    from aughor.explorer.continuous import stopped_on_budget_at
    from aughor.explorer.models import ExplorationPhase

    def run(reason: str) -> SchemaExplorer:
        ex = SchemaExplorer.__new__(SchemaExplorer)
        ex.connection_id, ex.schema_name, ex._store_key, ex._state, ex._rate_seconds = "c", None, "c", {}, 0

        class _Status:
            phase = ExplorationPhase.PENDING
            error = None
            domain_intel_skipped = False
            domain_intel_note = None
            started_at = ""
            tables_total = columns_total = joins_total = 0

        ex._status = _Status()
        monkeypatch.setattr(ex, "_load_profiler_data", lambda: ({"t": object()}, {}, {"joins": []}))
        monkeypatch.setattr(ex, "_compute_time_window", lambda *a, **k: None)
        monkeypatch.setattr(ex, "_compute_macro_context", lambda *a, **k: None)
        monkeypatch.setattr(ex, "_save_state", lambda: None)
        monkeypatch.setattr(ex, "_journal", lambda *a, **k: None)
        monkeypatch.setattr("aughor.kernel.jobs.stop_reason", lambda job_id=None: reason)

        async def cancel(*a, **k):
            raise asyncio.CancelledError()

        monkeypatch.setattr(ex, "_phase8_domain_intelligence", cancel)
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(ex._explore_run(domain_intel_only=True))
        return ex

    killed = run("budget exceeded: time budget (600s)")
    assert killed._status.error == "cancelled (time budget (600s) exceeded) — progress saved"
    assert killed._state.get("stopped_on_budget_at")
    assert stopped_on_budget_at({**killed._state, "phase": "failed", "error": killed._status.error}) is not None
    persons = run("")
    assert persons._status.error == "cancelled (budget exceeded or stopped) — progress saved"
    assert not persons._state.get("stopped_on_budget_at")
