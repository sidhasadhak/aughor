"""REC-05 / SEC-01 / SEC-05 — request identity + object-level authorization.

Two properties:
  * localhost mode (AUGHOR_REQUIRE_IDENTITY unset) is UNCHANGED — by-id endpoints
    answer without any identity header (REC-05a: pin current behavior).
  * identity mode (flag on) binds the caller's org and blocks cross-org access to
    by-id investigation/canvas endpoints (REC-05c), while exempt paths stay open.

Ownership resolves through resource → connection → connections.org_id, so the
fixtures create a connection owned by org "acme" and derive a canvas + an
investigation from it.
"""
from __future__ import annotations

import pytest

from aughor.canvas.models import CanvasScope
from aughor.canvas.store import create_canvas
from aughor.db.history import create_investigation
from aughor.db.registry import add_connection
from aughor.org.context import using_org


@pytest.fixture
def acme_resources():
    """A connection owned by org 'acme', plus a canvas + investigation on it."""
    with using_org("acme"):
        conn_id = add_connection(name="acme-conn", conn_type="duckdb", dsn="/tmp/acme.duckdb", meta={})
    canvas = create_canvas(
        name="acme-canvas",
        scopes=[CanvasScope(connection_id=conn_id, schema_name=None, tables=[])],
    )
    inv_id = create_investigation(question="acme q", connection_id=conn_id, canvas_id=canvas.id)
    return {"conn_id": conn_id, "canvas_id": canvas.id, "inv_id": inv_id}


# ── REC-05a: localhost mode is unchanged (no identity, no ownership enforcement) ──

def test_localhost_mode_needs_no_identity(client, acme_resources, monkeypatch):
    monkeypatch.delenv("AUGHOR_REQUIRE_IDENTITY", raising=False)
    # No headers, no flag → the by-id endpoints answer exactly as before.
    assert client.get(f"/canvases/{acme_resources['canvas_id']}").status_code == 200
    assert client.get(f"/investigations/{acme_resources['inv_id']}").status_code == 200


# ── REC-05c: identity mode enforces org ownership ────────────────────────────────

def test_identity_required_returns_401_without_org_header(client, acme_resources, monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    r = client.get(f"/canvases/{acme_resources['canvas_id']}")
    assert r.status_code == 401


def test_exempt_paths_open_even_with_identity_on(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    assert client.get("/health").status_code == 200


def test_owner_org_may_read_canvas_and_investigation(client, acme_resources, monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    h = {"X-Aughor-Org": "acme"}
    assert client.get(f"/canvases/{acme_resources['canvas_id']}", headers=h).status_code == 200
    assert client.get(f"/investigations/{acme_resources['inv_id']}", headers=h).status_code == 200


def test_other_org_is_forbidden_on_canvas(client, acme_resources, monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    r = client.get(f"/canvases/{acme_resources['canvas_id']}", headers={"X-Aughor-Org": "intruder"})
    assert r.status_code == 403


def test_other_org_is_forbidden_on_investigation(client, acme_resources, monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    r = client.get(f"/investigations/{acme_resources['inv_id']}", headers={"X-Aughor-Org": "intruder"})
    assert r.status_code == 403


def test_cross_org_delete_is_blocked_and_resource_survives(client, acme_resources, monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    inv_id = acme_resources["inv_id"]
    # Intruder cannot delete...
    assert client.delete(f"/investigations/{inv_id}", headers={"X-Aughor-Org": "intruder"}).status_code == 403
    # ...and the investigation is still there (the delete never ran).
    assert client.get(f"/investigations/{inv_id}", headers={"X-Aughor-Org": "acme"}).status_code == 200
    # The owner can delete it.
    assert client.delete(f"/investigations/{inv_id}", headers={"X-Aughor-Org": "acme"}).status_code == 204


def test_org_contextvar_is_bound_in_the_handler(client, monkeypatch):
    """When identity is on, the principal's org is bound to current_org_id() for the
    request scope (via _OrgContextMiddleware) so it reaches the handler — sync or
    async — and is reset afterward. This is what makes the tenant key ride the
    request path (SEC-01); a generator dependency alone could not (its contextvar
    set never reaches the handler)."""
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    from aughor.api import app
    from aughor.org.context import DEFAULT_ORG_ID, current_org_id

    seen = {}

    @app.get("/_authz_probe_org")
    def _probe():
        seen["org"] = current_org_id()
        return {"org": seen["org"]}

    r = client.get("/_authz_probe_org", headers={"X-Aughor-Org": "acme"})
    assert r.status_code == 200 and r.json()["org"] == "acme"
    assert seen["org"] == "acme"                # bound inside the handler (the point)
    assert current_org_id() == DEFAULT_ORG_ID   # never leaks into the ambient context
