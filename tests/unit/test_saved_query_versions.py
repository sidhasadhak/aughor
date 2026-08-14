"""SE-4 J — the read side of saved-query version history.

`update_saved_query` overwrites the only row and has recorded a lifecycle revision beside
it since Wave V3. Nothing could read that history, so a saved query had a version trail
and no way to see or use it — both ends of a feature existing while the feature did not.

These routes are that read side. The claims:

  1. History accumulates on update and reads back newest-first, with bodies.
  2. The diff is FIELD-level (paths), not a text blob — so a spec change is legible.
  3. Restore writes a NEW version rather than rewinding the counter, AND applies the old
     body to the live row. Either half alone is a lie: rewinding would erase the evidence
     that a version shipped, and reverting only the history would show the user a restore
     the editor never saw.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aughor.api import app

client = TestClient(app)


@pytest.fixture()
def saved(tmp_path, monkeypatch):
    """A saved query with three edits behind it.

    The kernel ledger is redirected too: revisions ride it, so without this the test
    writes into the live `data/system.db`.
    """
    monkeypatch.setenv("AUGHOR_SAVEDQUERY_DB", str(tmp_path / "sq.db"))
    monkeypatch.setenv("AUGHOR_SYSTEM_DB", str(tmp_path / "system.db"))
    import importlib
    import aughor.savedquery.store as store
    importlib.reload(store)
    from aughor.kernel.ledger import Ledger
    Ledger._instances.clear()

    q = store.create_saved_query("conn-demo", "Margin", sql="SELECT 1", spec={})
    store.update_saved_query(q.id, sql="SELECT 2")
    store.update_saved_query(q.id, sql="SELECT 3", name="Margin v3")
    yield q.id
    Ledger._instances.clear()
    importlib.reload(store)


# ── 1. history ────────────────────────────────────────────────────────────────

def test_versions_list_newest_first_with_bodies(saved):
    r = client.get(f"/saved-queries/{saved}/versions")
    assert r.status_code == 200, r.text
    versions = r.json()["versions"]
    assert len(versions) >= 2, "updates did not accumulate history"
    assert [v["version"] for v in versions] == sorted(
        (v["version"] for v in versions), reverse=True), "history is not newest-first"
    # Bodies ride along so the rail can diff without a request per row.
    assert versions[0]["sql"] == "SELECT 3"
    assert versions[0]["name"] == "Margin v3"


def test_versions_404_for_an_unknown_query(saved):
    assert client.get("/saved-queries/does-not-exist/versions").status_code == 404


# ── 2. the diff is field-level ────────────────────────────────────────────────

def test_diff_reports_paths_not_a_text_blob(saved):
    versions = client.get(f"/saved-queries/{saved}/versions").json()["versions"]
    newest = versions[0]["version"]
    r = client.get(f"/saved-queries/{saved}/versions/{newest}/diff")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["to_version"] == newest and body["from_version"] == newest - 1
    paths = {c["path"] for c in body["changes"]}
    assert "sql" in paths, f"the sql change is not reported: {body['changes']}"
    sql_change = next(c for c in body["changes"] if c["path"] == "sql")
    assert sql_change["before"] == "SELECT 2" and sql_change["after"] == "SELECT 3"


def test_diff_against_an_explicit_version(saved):
    versions = client.get(f"/saved-queries/{saved}/versions").json()["versions"]
    newest, oldest = versions[0]["version"], versions[-1]["version"]
    r = client.get(f"/saved-queries/{saved}/versions/{newest}/diff?against={oldest}")
    assert r.status_code == 200
    assert r.json()["from_version"] == oldest


def test_diff_404_on_a_missing_version(saved):
    assert client.get(f"/saved-queries/{saved}/versions/999/diff").status_code == 404


# ── 3. restore ────────────────────────────────────────────────────────────────

def test_restore_applies_the_old_body_to_the_live_row(saved):
    versions = client.get(f"/saved-queries/{saved}/versions").json()["versions"]
    oldest = versions[-1]["version"]
    old_sql = versions[-1]["sql"]

    r = client.post(f"/saved-queries/{saved}/restore", json={"version": oldest})
    assert r.status_code == 200, r.text
    assert r.json()["restored_from"] == oldest
    assert r.json()["query"]["sql"] == old_sql
    # The LIVE record, not just the response — a restore the editor never saw is not one.
    assert client.get(f"/saved-queries/{saved}").json()["sql"] == old_sql


def test_restore_appends_a_version_rather_than_rewinding(saved):
    before = client.get(f"/saved-queries/{saved}/versions").json()["versions"]
    top = before[0]["version"]
    client.post(f"/saved-queries/{saved}/restore", json={"version": before[-1]["version"]})
    after = client.get(f"/saved-queries/{saved}/versions").json()["versions"]
    assert after[0]["version"] > top, \
        "restore rewound the counter — the evidence that a version shipped was erased"
    assert len(after) > len(before)


def test_restore_404_on_a_missing_version(saved):
    assert client.post(f"/saved-queries/{saved}/restore",
                       json={"version": 999}).status_code == 404
