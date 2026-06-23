"""Org — the tenant boundary above Workspace (PLATFORM_ARCHITECTURE.md Phase 1).

The Org is the top of the namespace and the scope key (`org_id`) stamped onto every
persisted object so multi-tenant becomes a config flip, not a migration. Single-org
today; the context defaults to `DEFAULT_ORG_ID` so unscoped code is unaffected.
"""
from aughor.org.context import (
    DEFAULT_ORG_ID,
    current_org_id,
    reset_org_id,
    set_org_id,
    using_org,
)
from aughor.org.models import Org
from aughor.org.store import (
    create_org,
    ensure_default_org,
    get_org,
    list_orgs,
)

__all__ = [
    "DEFAULT_ORG_ID",
    "current_org_id",
    "set_org_id",
    "reset_org_id",
    "using_org",
    "Org",
    "create_org",
    "get_org",
    "list_orgs",
    "ensure_default_org",
]
