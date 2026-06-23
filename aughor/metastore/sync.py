"""Derive catalogs from the connection registry, and the data-path gate.

Grants are an **independent access-control layer**, not a projection of membership.
The live data-path gate is `accessible_catalog_ids()` = a workspace's connection
membership (read live) **∪** its explicit catalog grants. So:
  • with no explicit grants the gate equals the legacy `workspace_connection_ids()`
    (behaviour-preserving), and
  • an explicit grant adds access to a catalog beyond the workspace's membership —
    a real grant/revoke API, durable and decoupled from membership.

There is no reconcile-on-read and no stored membership grants: membership is one
input (read live from `connection_ids`), explicit grants are the other.
"""
from __future__ import annotations

import logging
from typing import Optional

from aughor.metastore import store
from aughor.metastore.models import USAGE, securable_catalog_id

logger = logging.getLogger(__name__)


def ensure_catalogs_for_connections() -> int:
    """Upsert one catalog per registered connection (built-ins included). Idempotent.
    Returns the number of catalogs synced."""
    from aughor.db.registry import list_connections
    n = 0
    for conn in list_connections():
        cid = conn.get("id")
        if not cid:
            continue
        store.upsert_catalog(catalog_id=cid, name=conn.get("name") or cid, conn_id=cid)
        n += 1
    return n


def sync_metastore_from_registry() -> dict:
    """One idempotent pass: catalogs ← connections. (Grants are not derived from
    membership — they are an independent layer.) Safe to call on every startup."""
    catalogs = ensure_catalogs_for_connections()
    logger.info("Metastore synced: %d catalog(s)", catalogs)
    return {"catalogs": catalogs}


def explicit_catalog_ids(workspace_id: str, org_id: Optional[str] = None) -> set:
    """Catalog ids a workspace holds an explicit USAGE grant on (the durable,
    independently-managed access layer — excludes legacy membership-source rows)."""
    ids = set()
    for g in store.grants_for_workspace(workspace_id, org_id=org_id):
        if g.privilege == USAGE and g.source == "explicit":
            cid = securable_catalog_id(g.securable)
            if cid is not None:
                ids.add(cid)
    return ids


def accessible_catalog_ids(workspace_id: Optional[str]) -> Optional[set]:
    """The LIVE data-path gate (wired into the router visibility gates): a workspace's
    connection membership **∪** its explicit catalog grants. Same None / set /
    fail-closed semantics as the legacy `workspace_connection_ids()`:

      • ``None`` when no workspace is given (unscoped),
      • ``membership ∪ explicit-grants`` for a known workspace,
      • an EMPTY set for an unknown workspace (fail-closed).

    Behaviour-preserving when there are no explicit grants; an explicit grant widens
    access beyond membership. No reconcile, no stored membership grants — a pure read.
    """
    if not workspace_id:
        return None
    from aughor.workspace.store import get_workspace
    ws = get_workspace(workspace_id)
    if not ws:
        return set()
    return set(ws.connection_ids or []) | explicit_catalog_ids(ws.id, org_id=ws.org_id)
