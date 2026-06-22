"""Derive the metastore from the connection registry + workspace membership, and
the grant resolver.

Foundation behaviour: catalogs mirror connections (1:1), and grants are *reconciled*
to each workspace's current `connection_ids` — so the metastore is fully derived from
today's state and the grant resolver returns the exact same visibility as the
`workspace_connection_ids()` gate (proven by the parity test). Nothing in the live
data path consumes this yet; flipping the 8 gate sites onto `granted_catalog_ids` is
the next checkpoint, at which point grants become authoritative (no auto-reconcile).
"""
from __future__ import annotations

import logging
from typing import Optional

from aughor.metastore import store
from aughor.metastore.models import (
    USAGE,
    catalog_securable,
    securable_catalog_id,
    workspace_principal,
)

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


def ensure_grants_for_memberships() -> int:
    """Reconcile each workspace's catalog grants to its current `connection_ids`
    (add missing USAGE grants, revoke ones no longer backed by membership). Idempotent.
    Returns the number of grant mutations applied."""
    from aughor.workspace.store import list_workspaces
    changed = 0
    for ws in list_workspaces():
        desired = set(ws.connection_ids or [])
        current = granted_catalog_ids(ws.id) or set()
        for cid in desired - current:
            store.add_grant(workspace_principal(ws.id), catalog_securable(cid), org_id=ws.org_id)
            changed += 1
        for cid in current - desired:
            store.revoke_grant(workspace_principal(ws.id), catalog_securable(cid), org_id=ws.org_id)
            changed += 1
    return changed


def sync_metastore_from_registry() -> dict:
    """One idempotent pass: catalogs ← connections, grants ← workspace membership.
    Safe to call on every startup."""
    catalogs = ensure_catalogs_for_connections()
    grants_changed = ensure_grants_for_memberships()
    logger.info("Metastore synced: %d catalog(s), %d grant change(s)", catalogs, grants_changed)
    return {"catalogs": catalogs, "grants_changed": grants_changed}


def granted_catalog_ids(workspace_id: Optional[str]) -> Optional[set]:
    """The catalog ids a workspace has USAGE on — the grant-based equivalent of
    `workspace_connection_ids()`, with identical semantics:

      • ``None`` when no workspace is given (unscoped),
      • the set of granted catalog ids for a known workspace,
      • an EMPTY set for an unknown workspace (fail-closed).

    Built and parity-tested, but not yet wired into the live gate sites.
    """
    if not workspace_id:
        return None
    from aughor.workspace.store import get_workspace
    ws = get_workspace(workspace_id)
    if not ws:
        return set()
    ids = set()
    for g in store.grants_for_workspace(ws.id, org_id=ws.org_id):
        if g.privilege != USAGE:
            continue
        cid = securable_catalog_id(g.securable)
        if cid is not None:
            ids.add(cid)
    return ids
