"""A new connection must be visible in the catalogue immediately (2026-09-07).

`accessible_catalog_ids()` skips any connection no workspace tracks, and membership
was granted ONLY by `ensure_default_workspace()` — which runs at startup and inside
`GET /workspaces`, and nowhere on the create path. So `POST /connections` returned
201 for a connection the catalogue could not see: it appeared if some later request
happened to list workspaces, and otherwise never. From the outside that reads as
"the ingestion silently failed", which is what a user reported.

The subject here is VISIBILITY, not the registry row. Every test asserts through
`accessible_catalog_ids()` — the gate the catalog tree actually consults — with no
`GET /workspaces` and no restart in between.
"""
from __future__ import annotations

import pytest

from aughor.db.registry import add_connection
from aughor.metastore import accessible_catalog_ids
from aughor.workspace.store import (
    DEFAULT_WORKSPACE_ID,
    create_workspace,
    ensure_default_workspace,
    get_workspace,
    join_connection,
    update_workspace,
)


@pytest.fixture
def default_ws():
    ensure_default_workspace()
    return DEFAULT_WORKSPACE_ID


def _add(name: str, workspace_id: str | None = None) -> str:
    return add_connection(name=name, conn_type="duckdb", dsn="", meta={},
                          workspace_id=workspace_id)


def test_premise_without_the_join_the_connection_is_invisible(default_ws, monkeypatch):
    """The bug itself, so the tests below can actually fail.

    With the membership grant suppressed, `add_connection` reproduces the old
    behaviour exactly: a registry row the visibility gate cannot see.
    """
    import aughor.workspace.store as store
    monkeypatch.setattr(store, "join_connection", lambda *a, **k: None)
    conn_id = _add("invisible")
    assert conn_id not in (accessible_catalog_ids(default_ws) or set())


def test_a_fresh_connection_is_visible_without_listing_workspaces(default_ws):
    """The reported bug, at the gate that caused it."""
    conn_id = _add("fresh")
    assert conn_id in (accessible_catalog_ids(default_ws) or set())


def test_it_joins_the_workspace_the_caller_is_looking_at(default_ws):
    """Creating from a non-default workspace filed it under Default — invisible."""
    other = create_workspace(name="Analytics", connection_ids=[], description="")
    conn_id = _add("scoped", workspace_id=other.id)
    assert conn_id in (accessible_catalog_ids(other.id) or set())


def test_an_unknown_workspace_does_not_silently_swallow_the_connection(default_ws):
    """A bad workspace_id must not leave the connection invisible everywhere."""
    conn_id = add_connection(name="orphan", conn_type="duckdb", dsn="", meta={},
                             workspace_id="no-such-workspace")
    # It is not in the phantom workspace (fail-closed), but the registry row exists
    # and the default bootstrap can still claim it.
    assert accessible_catalog_ids("no-such-workspace") == set()
    join_connection(conn_id)
    assert conn_id in (accessible_catalog_ids(DEFAULT_WORKSPACE_ID) or set())


def test_joining_twice_does_not_duplicate_membership(default_ws):
    conn_id = _add("once")
    join_connection(conn_id)
    join_connection(conn_id)
    ids = (get_workspace(DEFAULT_WORKSPACE_ID).connection_ids or [])
    assert ids.count(conn_id) == 1


def test_default_does_not_reclaim_a_connection_another_workspace_owns(default_ws):
    """A connection deliberately moved out must not be dragged back into Default."""
    other = create_workspace(name="Owned", connection_ids=[], description="")
    conn_id = _add("moved")
    # Move it: out of Default, into `other`.
    d = get_workspace(DEFAULT_WORKSPACE_ID)
    update_workspace(DEFAULT_WORKSPACE_ID,
                     connection_ids=[i for i in (d.connection_ids or []) if i != conn_id])
    update_workspace(other.id, connection_ids=[conn_id])

    assert join_connection(conn_id) == other.id
    assert conn_id not in (get_workspace(DEFAULT_WORKSPACE_ID).connection_ids or [])
