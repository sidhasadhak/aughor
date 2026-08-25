"""The workspace payload carries the EFFECTIVE access set, not just membership.

The gate the routers enforce is ``membership ∪ explicit catalog grants``
(`aughor.metastore.sync.accessible_catalog_ids`), but the workspace payload used
to carry membership alone — so the frontend picker, which can only filter on what
the payload says, hid a granted catalog the API was happily serving. Every
endpoint that returns a workspace now serves ``accessible_connection_ids``
resolved by that same gate. (Also the first direct coverage this router has had.)
"""
import aughor.workspace.store as wstore
from aughor.metastore.models import USAGE, catalog_securable, workspace_principal
from aughor.metastore.store import add_grant
from aughor.routers.workspace import (
    CreateWorkspaceRequest,
    UpdateWorkspaceRequest,
    create_workspace_endpoint,
    get_workspace_endpoint,
    get_workspaces,
    update_workspace_endpoint,
)


def _hermetic(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(wstore, "_DB_PATH", tmp_path / "workspaces.db")
    import aughor.metastore.store as cat_store
    monkeypatch.setattr(cat_store, "_DB_PATH", tmp_path / "metastore.db")


def test_grant_widens_the_served_set_beyond_membership(tmp_path, monkeypatch):
    _hermetic(tmp_path, monkeypatch)
    ws = wstore.create_workspace(name="sales", connection_ids=["c1"])
    add_grant(workspace_principal(ws.id), catalog_securable("c2"), USAGE,
              source="explicit", org_id=ws.org_id)

    row = next(w for w in get_workspaces() if w["id"] == ws.id)
    assert row["connection_ids"] == ["c1"]                      # membership untouched
    assert sorted(row["accessible_connection_ids"]) == ["c1", "c2"]

    single = get_workspace_endpoint(ws.id)
    assert sorted(single["accessible_connection_ids"]) == ["c1", "c2"]


def test_without_grants_the_set_is_exactly_membership(tmp_path, monkeypatch):
    _hermetic(tmp_path, monkeypatch)
    made = create_workspace_endpoint(CreateWorkspaceRequest(
        name="plain", connection_ids=["c1", "c3"]))
    assert sorted(made["accessible_connection_ids"]) == ["c1", "c3"]


def test_update_reshapes_the_served_set(tmp_path, monkeypatch):
    _hermetic(tmp_path, monkeypatch)
    ws = wstore.create_workspace(name="edit-me", connection_ids=[])
    add_grant(workspace_principal(ws.id), catalog_securable("c9"), USAGE,
              source="explicit", org_id=ws.org_id)

    out = update_workspace_endpoint(ws.id, UpdateWorkspaceRequest(connection_ids=["c1"]))
    assert out["connection_ids"] == ["c1"]
    assert sorted(out["accessible_connection_ids"]) == ["c1", "c9"]


def test_a_metastore_failure_degrades_to_membership(tmp_path, monkeypatch):
    """The list must never 500 because grants could not be read — a workspace with
    an unreadable metastore still knows its own members."""
    _hermetic(tmp_path, monkeypatch)
    ws = wstore.create_workspace(name="degraded", connection_ids=["c1"])

    def _boom(workspace_id):
        raise RuntimeError("metastore unavailable")
    monkeypatch.setattr("aughor.metastore.sync.accessible_catalog_ids", _boom)

    row = next(w for w in get_workspaces() if w["id"] == ws.id)
    assert row["accessible_connection_ids"] == ["c1"]
