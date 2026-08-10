"""Workspace membership must not outlive the connections it references.

`connection_ids` is documented as "references entries in the connection registry",
and nothing removed an id when its connection was deleted. Every workspace-scoped
picker intersects membership against the live registry, so a dangling id is
invisible — right up until it is ALL that is left, at which point the workspace
renders as having no connections and the Briefing has nothing to show. Measured on
one machine: the Default workspace listed ten members, three of which existed.
"""
from __future__ import annotations

import pytest

from aughor.workspace import store as ws_store


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    """Point the workspace store at a temp DB — this suite WRITES memberships."""
    monkeypatch.setattr(ws_store, "_DB_PATH", str(tmp_path / "workspaces.db"))
    return ws_store


def test_delete_drops_the_id_from_every_workspace(isolated_store) -> None:
    a = ws_store.create_workspace("A", connection_ids=["keep", "doomed"])
    b = ws_store.create_workspace("B", connection_ids=["doomed"])
    c = ws_store.create_workspace("C", connection_ids=["keep"])

    changed = ws_store.drop_connection_everywhere("doomed")

    assert changed == 2, "only the workspaces that held it should be rewritten"
    assert ws_store.get_workspace(a.id).connection_ids == ["keep"]
    assert ws_store.get_workspace(b.id).connection_ids == []
    assert ws_store.get_workspace(c.id).connection_ids == ["keep"]


def test_dropping_an_absent_id_changes_nothing(isolated_store) -> None:
    a = ws_store.create_workspace("A", connection_ids=["x", "y"])
    assert ws_store.drop_connection_everywhere("never-there") == 0
    assert ws_store.get_workspace(a.id).connection_ids == ["x", "y"]


def test_prune_removes_only_ids_with_no_connection(isolated_store, monkeypatch) -> None:
    a = ws_store.create_workspace("A", connection_ids=["live1", "ghost1", "live2"])
    b = ws_store.create_workspace("B", connection_ids=["ghost2"])

    monkeypatch.setattr("aughor.db.registry.list_connections",
                        lambda org_id=None: [{"id": "live1"}, {"id": "live2"}])

    removed = ws_store.prune_dangling_members()

    assert removed[a.id] == ["ghost1"]
    assert removed[b.id] == ["ghost2"]
    assert ws_store.get_workspace(a.id).connection_ids == ["live1", "live2"]
    assert ws_store.get_workspace(b.id).connection_ids == []


def test_prune_leaves_everything_alone_when_the_registry_cannot_be_read(
        isolated_store, monkeypatch) -> None:
    """A transient registry failure must not empty every workspace — that would turn
    a blip into the exact symptom this repairs."""
    a = ws_store.create_workspace("A", connection_ids=["x", "y"])

    def _boom(org_id=None):
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr("aughor.db.registry.list_connections", _boom)

    assert ws_store.prune_dangling_members() == {}
    assert ws_store.get_workspace(a.id).connection_ids == ["x", "y"]


def test_prune_treats_an_empty_registry_as_unreadable(isolated_store, monkeypatch) -> None:
    """An empty result is indistinguishable from a failed read here, and emptying
    every workspace is not a repair."""
    a = ws_store.create_workspace("A", connection_ids=["x"])
    monkeypatch.setattr("aughor.db.registry.list_connections", lambda org_id=None: [])

    assert ws_store.prune_dangling_members() == {}
    assert ws_store.get_workspace(a.id).connection_ids == ["x"]


def test_prune_never_touches_another_orgs_workspace(isolated_store, monkeypatch) -> None:
    """The safety argument for the whole repair.

    `list_workspaces()` returns EVERY org's workspaces while `list_connections()`
    returns only the current org's, so comparing them directly would read another
    tenant's valid members as ghosts and delete them — worse than the bug being
    fixed. Only workspaces belonging to the org whose connections were listed may
    be rewritten.
    """
    mine = ws_store.create_workspace("mine", connection_ids=["live1", "ghost"])
    theirs = ws_store.create_workspace("theirs", connection_ids=["their-conn"])
    # Force the other workspace onto a different tenant.
    c = ws_store._conn()
    c.execute("UPDATE workspaces SET org_id = ? WHERE id = ?", ("other-org", theirs.id))
    c.commit()

    monkeypatch.setattr("aughor.db.registry.list_connections",
                        lambda org_id=None: [{"id": "live1"}])

    removed = ws_store.prune_dangling_members()

    assert theirs.id not in removed, "another org's membership was rewritten"
    assert ws_store.get_workspace(theirs.id).connection_ids == ["their-conn"], (
        "another tenant's valid connection was deleted as a ghost")
    assert ws_store.get_workspace(mine.id).connection_ids == ["live1"]


def test_prune_is_idempotent(isolated_store, monkeypatch) -> None:
    a = ws_store.create_workspace("A", connection_ids=["live", "ghost"])
    monkeypatch.setattr("aughor.db.registry.list_connections",
                        lambda org_id=None: [{"id": "live"}])

    first = ws_store.prune_dangling_members()
    second = ws_store.prune_dangling_members()

    assert first[a.id] == ["ghost"]
    assert second == {}, "a second pass found work to do — the repair is not idempotent"
    assert ws_store.get_workspace(a.id).connection_ids == ["live"]
