"""The knowledge-source door (`/knowledge/sources`) — Confluence/Notion become creatable.

Both connectors were built and reachable per-connection, and impossible to CREATE: they
are deliberately not registered as data connectors ("open_connection() is not called on
them"), so the connection door's connect test would refuse them and no catalog row ever
offered them. Decided 2026-09-06 (the user's call): they surface on the DOCUMENTS
surface, and the data catalog's category ratchet stays exactly as pinned.

These tests pin the door's three laws: the form is SERVED from the connector registry
(never mirrored), a source is tested live before it is saved, and secret values never
come back out. Plus the state-path fix: sync state follows `AUGHOR_STATE_DIR`, never the
process's CWD — a bare `Path("data")` made any process started elsewhere read an empty
sync state and re-sync from scratch.

Hermetic — `tests/conftest.py` points the registry DB and `AUGHOR_STATE_DIR` at tempdirs.
"""
from __future__ import annotations

import os
from pathlib import Path


def test_the_form_is_served_from_the_connector_registry(client):
    r = client.get("/knowledge/sources")
    assert r.status_code == 200
    body = r.json()
    types = {t["conn_type"]: t for t in body["types"]}
    assert set(types) == {"confluence", "notion"}
    notion_fields = {f["key"]: f for f in types["notion"]["fields"]}
    assert notion_fields["integration_token"]["secret"] is True
    confluence_fields = {f["key"]: f for f in types["confluence"]["fields"]}
    assert confluence_fields["api_token"]["secret"] is True
    assert confluence_fields["base_url"]["secret"] is False


def test_an_unknown_type_is_refused(client):
    r = client.post("/knowledge/sources", json={
        "conn_type": "sharepoint", "name": "x", "config": {}})
    assert r.status_code == 400
    assert "sharepoint" in r.json()["detail"]


def test_missing_required_fields_fail_in_the_connectors_own_words(client):
    r = client.post("/knowledge/sources", json={
        "conn_type": "notion", "name": "My wiki", "config": {}})
    assert r.status_code == 400
    assert "integration_token" in r.json()["detail"]


def test_a_source_that_fails_its_live_test_is_never_saved(client, monkeypatch):
    from aughor.connectors.knowledge.notion import NotionSync
    monkeypatch.setattr(NotionSync, "test",
                        lambda self: (False, "401 from api.notion.com"))
    r = client.post("/knowledge/sources", json={
        "conn_type": "notion", "name": "My wiki",
        "config": {"integration_token": "secret_x"}})
    assert r.status_code == 400
    assert "401" in r.json()["detail"]
    listed = client.get("/knowledge/sources").json()["sources"]
    assert all(s["name"] != "My wiki" for s in listed)


def test_create_then_list_carries_status_and_never_the_secret(client, monkeypatch):
    from aughor.connectors.knowledge.notion import NotionSync
    monkeypatch.setattr(NotionSync, "test", lambda self: (True, "Notion connected"))
    r = client.post("/knowledge/sources", json={
        "conn_type": "notion", "name": "Team wiki",
        "config": {"integration_token": "secret_abc123"}})
    assert r.status_code == 201
    conn_id = r.json()["id"]

    listed = client.get("/knowledge/sources")
    sources = {s["id"]: s for s in listed.json()["sources"]}
    assert conn_id in sources
    assert sources[conn_id]["conn_type"] == "notion"
    assert sources[conn_id]["status"] is not None  # last_sync None until a sync runs
    assert "secret_abc123" not in listed.text  # the token never leaves the server


def test_sync_state_follows_the_state_dir_not_the_cwd(tmp_path, monkeypatch):
    from aughor.connectors.knowledge.notion import NotionSync

    monkeypatch.setenv("AUGHOR_STATE_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path / ".." if (tmp_path / "..").exists() else tmp_path)
    syncer = NotionSync("connX", {"integration_token": "t"})
    syncer._save_state({"last_sync": "2026-09-06T00:00:00Z"})

    assert (tmp_path / "knowledge_sync_connX.json").exists()
    assert not (Path(os.getcwd()) / "data" / "knowledge_sync_connX.json").exists()
    # A second instance — a different process, in spirit — reads the same state back.
    again = NotionSync("connX", {"integration_token": "t"})
    assert again._load_state()["last_sync"] == "2026-09-06T00:00:00Z"
