"""The metastore — org-level namespace + access registry (PLATFORM_ARCHITECTURE.md
Phase 2). Catalog (the unit of isolation, = a connection within an org) + Grant
(workspace → catalog) as first-class objects.

Catalogs are derived from the connection registry. Grants are an **independent
access-control layer** (not a projection of membership): the live data-path gate
`accessible_catalog_ids()` = a workspace's connection membership (read live) **∪** its
explicit catalog grants. With no explicit grants it equals the legacy
`workspace_connection_ids()`; an explicit grant widens access beyond membership.
"""
from aughor.metastore.models import (
    USAGE,
    Catalog,
    Grant,
    Schema,
    catalog_securable,
    schema_securable,
    securable_catalog_id,
    securable_schema,
    workspace_principal,
)
from aughor.metastore.store import (
    add_grant,
    delete_catalog,
    get_catalog,
    grants_for_workspace,
    list_catalogs,
    list_grants,
    list_schemas,
    revoke_grant,
    set_catalog_schemas,
    upsert_catalog,
    upsert_schema,
)
from aughor.metastore.sync import (
    accessible_catalog_ids,
    ensure_catalogs_for_connections,
    explicit_catalog_ids,
    sync_metastore_from_registry,
)

__all__ = [
    # models
    "Catalog", "Grant", "Schema", "USAGE",
    "workspace_principal", "catalog_securable", "securable_catalog_id",
    "schema_securable", "securable_schema",
    # store
    "upsert_catalog", "get_catalog", "list_catalogs", "delete_catalog",
    "add_grant", "revoke_grant", "list_grants", "grants_for_workspace",
    "upsert_schema", "list_schemas", "set_catalog_schemas",
    # sync + resolver
    "sync_metastore_from_registry", "ensure_catalogs_for_connections",
    "explicit_catalog_ids", "accessible_catalog_ids",
]
