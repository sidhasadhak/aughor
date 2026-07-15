"""R1 — uploading files RE-ARMS background schema exploration.

On-connect exploration (create_connection) fires before any file is uploaded, so
a file connection's first real data never triggered intelligence — profiling,
join inference, ontology and BusinessProfile materialized only lazily on the
first question. Every upload path now re-arms Scout, scoped to the schema that
received the tables, debounced for bulk, and best-effort (a re-arm failure never
fails an ingest that already succeeded).

Hermetic: the storage root is redirected to a tmp dir, and the kickoff seam
(`_kickoff_exploration`) is replaced with a recorder so no real background
explorer spawns.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aughor.platform import vending
from aughor.routers import connections


@pytest.fixture
def isolated_uploads(tmp_path, monkeypatch):
    monkeypatch.setattr(vending, "STORAGE_ROOT", tmp_path / "uploads")
    return tmp_path


@pytest.fixture
def rearm_calls(monkeypatch):
    """Record every re-arm call and stop real explorers from spawning."""
    calls: list[tuple[str, dict]] = []

    def _record(conn_id, **kw):
        calls.append((conn_id, kw))
        return True

    monkeypatch.setattr(connections, "_kickoff_exploration", _record)
    return calls


def _csv(field: str, name: str, body: str):
    return (field, (name, body, "text/csv"))


def test_single_upload_rearms_scoped_to_schema(client: TestClient, isolated_uploads, rearm_calls):
    r = client.post(
        "/connections/workspace/files",
        files=[_csv("file", "orders.csv", "id,amt\n1,5\n2,9\n")],
        data={"schema": "rearm_single"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["exploring"] is True
    # Scoped to the schema that received the table, under Scout governance (auto=True).
    assert rearm_calls == [("workspace", {"schema_name": "rearm_single", "auto": True})]


def test_single_upload_defaults_schema_to_main(client: TestClient, isolated_uploads, rearm_calls):
    r = client.post(
        "/connections/workspace/files",
        files=[_csv("file", "nums.csv", "n\n1\n2\n")],
    )
    assert r.status_code == 201, r.text
    assert rearm_calls == [("workspace", {"schema_name": "main", "auto": True})]


def test_bulk_upload_rearms_exactly_once(client: TestClient, isolated_uploads, rearm_calls):
    """A batch fires ONE re-arm for the whole schema, not one per file."""
    r = client.post(
        "/connections/workspace/files/bulk",
        files=[
            _csv("files", "a.csv", "x\n1\n"),
            _csv("files", "b.csv", "y\n2\n"),
            _csv("files", "c.csv", "z\n3\n"),
        ],
        data={"schema": "rearm_bulk"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["added"] == 3 and body["exploring"] is True
    assert rearm_calls == [("workspace", {"schema_name": "rearm_bulk", "auto": True})]


def test_bulk_all_failed_does_not_rearm(client: TestClient, isolated_uploads, rearm_calls):
    """Nothing landed → no re-arm, and exploring is False."""
    r = client.post(
        "/connections/workspace/files/bulk",
        files=[("files", ("broken.xyz", "not a real format", "application/octet-stream"))],
        data={"schema": "rearm_none"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["added"] == 0 and body["exploring"] is False
    assert rearm_calls == []


def test_rearm_failure_never_fails_the_upload(client: TestClient, isolated_uploads, monkeypatch):
    """The ingest already succeeded — a kickoff error is swallowed to `exploring: False`."""
    def _boom(conn_id, **kw):
        raise RuntimeError("scout store unreachable")

    monkeypatch.setattr(connections, "_kickoff_exploration", _boom)
    r = client.post(
        "/connections/workspace/files",
        files=[_csv("file", "ok.csv", "a\n1\n")],
        data={"schema": "rearm_boom"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["table_name"] == "ok"
    assert body["exploring"] is False
