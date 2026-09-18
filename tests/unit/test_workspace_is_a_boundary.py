"""A workspace must be a boundary, not a filter the caller may decline.

Before this, `workspace_id` was an optional query parameter on a handful of handlers.
`accessible_catalog_ids(None)` means UNSCOPED, so any caller who simply omitted it saw
every connection in the org — and the operational plane (agents, automations, Slack
bots, briefing subscriptions) never took the parameter at all, so it was never scoped
by anything. Live, before the change: `/connections` returned all 9 whichever workspace
was asked for.

The fix is ambient rather than per-call: the workspace rides a header, a middleware
binds it to a contextvar, and the gate reads it. These tests hold the two halves — the
resolver honouring the ambient workspace, and the routes actually applying it.
"""
import pytest

from aughor.metastore.sync import scoped_to_workspace
from aughor.workspace.context import (
    current_workspace_id,
    set_workspace_id,
    reset_workspace_id,
    workspace_scope,
)


# ── the contextvar itself ──────────────────────────────────────────────────────

def test_unscoped_by_default_and_restored_after():
    """`None` must survive as a distinct value: unscoped is not "the default workspace"."""
    assert current_workspace_id() is None
    with workspace_scope("ws_a"):
        assert current_workspace_id() == "ws_a"
    assert current_workspace_id() is None


def test_blank_workspace_reads_as_unscoped_not_as_a_workspace_named_empty():
    """A blank header must not fail closed against a workspace whose id is "".

    `accessible_catalog_ids("")` would look up a workspace that cannot exist and return
    an EMPTY set — locking the caller out of everything rather than leaving them
    unscoped. Normalising at the setter is what keeps a stray header harmless.
    """
    token = set_workspace_id("")
    try:
        assert current_workspace_id() is None
    finally:
        reset_workspace_id(token)


# ── the operational-plane filter ───────────────────────────────────────────────

ROWS = [{"connection_id": "conn_a"}, {"connection_id": "conn_b"}, {"connection_id": ""}]


def test_unscoped_sees_everything():
    assert len(scoped_to_workspace(ROWS)) == 3


def test_unknown_workspace_fails_closed():
    """An id that resolves to no workspace must not fall open to the whole org."""
    with workspace_scope("no-such-workspace"):
        kept = scoped_to_workspace(ROWS)
    assert [r["connection_id"] for r in kept] == [""], "only the unbound row may survive"


def test_a_row_naming_no_connection_stays_visible():
    """An org-level record (a Slack bot bound to no connection) belongs to no workspace.

    Hiding it would be a guess about ownership this layer cannot make — that guess is
    the separate schema change. Until then it must not vanish from every workspace.
    """
    with workspace_scope("no-such-workspace"):
        assert {"connection_id": ""} in scoped_to_workspace(ROWS)


def test_objects_are_filtered_like_mappings():
    """Stores hand back models, not dicts — the filter must read both."""
    class _Row:
        def __init__(self, cid): self.conn_id = cid
    rows = [_Row("conn_a"), _Row("")]
    with workspace_scope("no-such-workspace"):
        kept = scoped_to_workspace(rows, key="conn_id")
    assert [r.conn_id for r in kept] == [""]


# ── the header actually binds the request ──────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from aughor.api import app
    with TestClient(app) as c:
        yield c


def test_header_binds_the_workspace_for_the_request(client):
    """The middleware is the whole point: without it the gate is opt-in per handler."""
    from aughor.api import app

    @app.get("/_test/ambient-workspace")
    def _probe():
        return {"workspace": current_workspace_id()}

    assert client.get("/_test/ambient-workspace").json()["workspace"] is None
    r = client.get("/_test/ambient-workspace", headers={"X-Aughor-Workspace": "ws_hdr"})
    assert r.json()["workspace"] == "ws_hdr"
    # …and it must not leak into the next request.
    assert client.get("/_test/ambient-workspace").json()["workspace"] is None


def test_query_param_still_binds_so_legacy_callers_agree(client):
    """The handlers that already pass `?workspace_id=` must see the same ambient value,
    or the two sources could disagree within one request."""
    r = client.get("/_test/ambient-workspace?workspace_id=ws_qs")
    assert r.json()["workspace"] == "ws_qs"


def test_connections_list_is_scoped(client):
    """The widest hole: this list returned the whole org whatever workspace was active."""
    unscoped = client.get("/connections")
    assert unscoped.status_code == 200
    scoped = client.get("/connections", headers={"X-Aughor-Workspace": "no-such-workspace"})
    assert scoped.status_code == 200
    assert scoped.json() == [], "an unknown workspace must see no connections"
    # Unscoped behaviour is unchanged — this change adds a gate, it does not close one.
    assert len(unscoped.json()) >= len(scoped.json())
