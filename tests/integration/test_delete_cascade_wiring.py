"""The DELETE /connections/{id} endpoint must invoke the catalog-delete cascade for
a real (non-builtin) connection — and must NOT for a builtin (which is only hidden,
its intelligence restorable). This pins the WIRING; the cascade itself is covered by
tests/unit/test_connection_purge.py.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_delete_connection_runs_cascade(client: TestClient, monkeypatch):
    from aughor.db import purge, registry

    calls: list[str] = []
    monkeypatch.setattr(purge, "purge_connection_artifacts",
                        lambda conn_id, *a, **k: calls.append(conn_id) or {})

    conn_id = registry.add_connection("throwaway", "local_upload", "local://")
    try:
        r = client.delete(f"/connections/{conn_id}")
        assert r.status_code == 204, r.text
        assert calls == [conn_id], "cascade was not invoked for the deleted catalog"
    finally:
        # endpoint already deleted the row; guard against a failed assert above
        try:
            registry.delete_connection(conn_id)
        except Exception:
            pass


def test_delete_builtin_does_not_cascade(client: TestClient, monkeypatch, tmp_path):
    """Deleting the builtin only hides it; its artifacts are preserved (restorable)."""
    from aughor.db import purge, registry

    calls: list[str] = []
    monkeypatch.setattr(purge, "purge_connection_artifacts",
                        lambda conn_id, *a, **k: calls.append(conn_id) or {})
    # Isolate the hide so it doesn't pollute the real settings file / sibling tests.
    monkeypatch.setattr(registry, "_SETTINGS_PATH", tmp_path / "settings.json")

    r = client.delete("/connections/fixture")  # BUILTIN_ID
    assert r.status_code == 204, r.text
    assert calls == [], "builtin hide must not purge its intelligence"
