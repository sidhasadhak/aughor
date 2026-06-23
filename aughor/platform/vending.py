"""Storage-credential vending — the control plane's storage seam (Invariant #2).

PLATFORM_ARCHITECTURE.md §5.2: *access is vended, never ambient.* Compute never
reaches storage on its own authority — it asks the control plane for a scoped
capability and addresses *logical* objects through it. Today the "credential" is
just a tenant-scoped path under the managed root, and the implementation is a
trivial local-filesystem one. The seam is what matters: the same call becomes real
S3 STS / GCS signed-credential vending later, with no change to callers.

Storage is pathed by tenant from day one (§5.1):

    {STORAGE_ROOT}/{org_id}/{conn_id}/{schema}/{table-or-volume}/...

Local FS now → S3/GCS prefixes later is the *same shape* (swap STORAGE_ROOT for a
bucket; swap direct-FS for vended credentials).
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from aughor.org.context import DEFAULT_ORG_ID, current_org_id

logger = logging.getLogger(__name__)

# The managed-storage root the platform owns. An org gets a subtree; a workspace
# never addresses storage directly — it addresses logical objects and the control
# plane resolves the physical path here.
STORAGE_ROOT = Path("data/uploads")


@dataclass(frozen=True)
class StorageCapability:
    """A scoped capability to one connection's storage within one org. Returned by
    :func:`vend_storage`; callers resolve paths *through* it rather than building
    ``{root}/{org}/{conn}`` themselves — so when the capability becomes a real
    vended cloud credential, every caller is already on the seam."""

    org_id: str
    conn_id: str

    @property
    def root(self) -> Path:
        """The tenant-scoped base directory for this connection's objects."""
        return STORAGE_ROOT / self.org_id / self.conn_id

    def resolve(self, *parts: str) -> Path:
        """A path to a logical object under this capability's scope."""
        return self.root.joinpath(*parts)


def vend_storage(conn_id: str, org_id: str | None = None) -> StorageCapability:
    """The control plane vends a scoped storage capability for ``conn_id``.

    ``org_id`` defaults to the current tenant context (the bootstrap org in the
    single-org case), so callers stay org-agnostic and the request layer pins the
    tenant once via :func:`aughor.org.set_org_id`. An empty ``conn_id`` resolves to
    the conventional ``"default"`` connection slot, matching the prior behaviour.
    """
    return StorageCapability(
        org_id=org_id or current_org_id() or DEFAULT_ORG_ID,
        conn_id=conn_id or "default",
    )


# Marker written once the on-disk layout is tenant-pathed; its presence is the
# authority for "already migrated" so the migration is exactly-once and resumable.
_LAYOUT_MARKER = ".org_layout"


def migrate_uploads_to_org_layout(org_id: str = DEFAULT_ORG_ID) -> bool:
    """One-time, idempotent, crash-safe move of the legacy flat upload layout
    ``{STORAGE_ROOT}/{conn_id}/...`` under the tenant subtree
    ``{STORAGE_ROOT}/{org_id}/{conn_id}/...``. Returns True if it migrated.

    Safety:
      • A dot-prefixed staging dir (``.__org_<id>__``) holds the moved children;
        real conn ids are never dot-prefixed, so a conn dir literally named
        ``"default"`` nests correctly instead of colliding with the org dir.
      • No deletes and resumable: a crash mid-move leaves already-moved children in
        staging; a re-run skips them and finishes. The final ``staging → org`` is an
        atomic rename, and only then is the marker written.
    """
    root = STORAGE_ROOT
    if not root.exists():
        return False
    marker = root / _LAYOUT_MARKER
    if marker.exists():
        return False

    staging = root / f".__org_{org_id}__"
    staging.mkdir(parents=True, exist_ok=True)
    moved = 0
    for child in root.iterdir():
        if child.name in (_LAYOUT_MARKER, staging.name):
            continue
        if child.name.startswith(".__org_"):
            continue
        dest = staging / child.name
        if dest.exists():  # already moved by an interrupted prior run
            continue
        shutil.move(str(child), str(dest))
        moved += 1

    org_dir = root / org_id
    if org_dir.exists():
        # Org dir already present (e.g. a partly-migrated/merged tree): merge in.
        for child in staging.iterdir():
            target = org_dir / child.name
            if not target.exists():
                shutil.move(str(child), str(target))
        staging.rmdir()
    else:
        staging.rename(org_dir)

    marker.write_text(org_id)
    logger.info("Migrated upload storage to tenant layout: %d connection dir(s) → %s/", moved, org_id)
    return True
