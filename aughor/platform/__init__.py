"""The control plane (PLATFORM_ARCHITECTURE.md §4).

Aughor is designed as a *platform*: the operator owns the infrastructure, tenants
are provisioned within it, and the classic split keeps single-org-now and
multi-tenant-later the same codebase —

  • **Control plane** (this package + the org registry): identity/tenant registry,
    the metastore/catalog seam, **storage-credential vending**, grant/policy
    resolution, scheduling, metering & billing. It resolves *who · what catalog ·
    which scoped credential · what budget* and hands compute a capability.

  • **Data plane** (``db`` / ``connectors`` / ``explorer`` / ``agent``): the stored
    objects and the compute that runs queries and agents over them. It receives a
    vended capability and never reaches storage on its own authority.

Today the planes run in one process and the "credential" is a tenant-scoped local
path — but the boundary is explicit so the data plane already calls *through* the
control plane (``vend_storage``) rather than building storage paths itself. That is
what makes the multi-tenant flip a config change, not a rewrite.

The tenant registry itself lives in :mod:`aughor.org` (control-plane in role); this
package hosts the storage-vending seam and is the home for further control-plane
primitives (grants, the catalog/metastore service) as they land.
"""
from aughor.platform.vending import (
    STORAGE_ROOT,
    StorageCapability,
    migrate_uploads_to_org_layout,
    vend_storage,
)

__all__ = [
    "STORAGE_ROOT",
    "StorageCapability",
    "vend_storage",
    "migrate_uploads_to_org_layout",
]
