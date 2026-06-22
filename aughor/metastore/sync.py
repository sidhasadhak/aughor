"""Derive the metastore from the connection registry + workspace membership, and
the grant resolver.

Catalogs mirror connections (1:1), and grants are *reconciled* to each workspace's
current `connection_ids`. The live data-path gate `accessible_catalog_ids()`
reconciles a workspace's grants on read and then returns them, so it is provably
equal to the legacy `workspace_connection_ids()` gate at all times while routing the
gate through the metastore. The control-path reverse lookups (`workspace_for_connection`
— governance/compute) deliberately stay on the workspace store. Making grants fully
authoritative (independent of membership) is a later step.
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


def reconcile_workspace_grants(ws) -> int:
    """Reconcile ONE workspace's catalog grants to its current `connection_ids`
    (add missing USAGE grants, revoke ones no longer backed by membership). Idempotent.
    Returns the number of grant mutations applied."""
    desired = set(ws.connection_ids or [])
    current = granted_catalog_ids(ws.id) or set()
    changed = 0
    for cid in desired - current:
        store.add_grant(workspace_principal(ws.id), catalog_securable(cid), org_id=ws.org_id)
        changed += 1
    for cid in current - desired:
        store.revoke_grant(workspace_principal(ws.id), catalog_securable(cid), org_id=ws.org_id)
        changed += 1
    return changed


def ensure_grants_for_memberships() -> int:
    """Reconcile EVERY workspace's catalog grants to its membership. Idempotent.
    Returns the total number of grant mutations applied."""
    from aughor.workspace.store import list_workspaces
    return sum(reconcile_workspace_grants(ws) for ws in list_workspaces())


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


def accessible_catalog_ids(workspace_id: Optional[str]) -> Optional[set]:
    """The LIVE data-path gate — the grant-based replacement for
    `workspace_connection_ids()`, wired into the router visibility gates.

    Reconciles the workspace's catalog grants to its current membership **on read**,
    then returns the granted set. The reconcile makes the gate provably equal to
    `workspace_connection_ids()` at all times (no staleness, no missed-hook risk),
    while routing the live gate through the metastore and keeping the grants table —
    the future authority — continuously maintained. Same None / set / fail-closed
    semantics as the gate it replaces.
    """
    if not workspace_id:
        return None
    from aughor.workspace.store import get_workspace
    ws = get_workspace(workspace_id)
    if not ws:
        return set()
    reconcile_workspace_grants(ws)
    return granted_catalog_ids(workspace_id)
