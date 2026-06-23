"""Volume operations — object bytes via the vended capability + the metadata catalog.

The bytes are written under the tenant path the control plane vends (Invariant #2):
``{storage_root}/{org}/{catalog}/_volumes/{volume}/{stored_name}``. The metadata row
(name, mime, size, …) goes in the volume store, which is what SQL queries. Content
extraction + R8 `embedding()` over `extracted_text` is a later step.
"""
from __future__ import annotations

import mimetypes
import re
import uuid
from pathlib import Path
from typing import List, Optional

from aughor.org.context import current_org_id
from aughor.platform.vending import vend_storage
from aughor.volumes import store
from aughor.volumes.models import Volume, VolumeObject

_VOLUMES_PREFIX = "_volumes"


def _safe_object_name(name: str) -> str:
    base = (name or "").replace("\\", "/").split("/")[-1]
    return re.sub(r"[^A-Za-z0-9._-]", "_", base) or "object"


def _volume_dir(vol: Volume) -> Path:
    """The tenant-scoped directory for a volume's objects, via the vending seam."""
    return vend_storage(vol.catalog_id, org_id=vol.org_id).resolve(_VOLUMES_PREFIX, vol.name)


def create_volume(catalog_id: str, name: str, org_id: Optional[str] = None) -> Volume:
    """Create (or return) a volume under a catalog. The catalog must exist."""
    from aughor.metastore import get_catalog
    oid = org_id or current_org_id()
    if get_catalog(catalog_id, org_id=oid) is None:
        raise ValueError(f"catalog '{catalog_id}' not found")
    return store.create_volume(catalog_id, name, org_id=oid)


def list_volumes(catalog_id: str, org_id: Optional[str] = None) -> List[Volume]:
    return store.list_volumes(catalog_id, org_id=org_id)


def put_object(volume_id: str, name: str, data: bytes, mime_type: str = "",
               org_id: Optional[str] = None) -> VolumeObject:
    """Write an object's bytes to the tenant-pathed store + record its metadata."""
    oid = org_id or current_org_id()
    vol = store.get_volume(volume_id, org_id=oid)
    if vol is None:
        raise ValueError(f"volume '{volume_id}' not found")
    safe = _safe_object_name(name)
    stored_name = f"{uuid.uuid4().hex[:12]}_{safe}"
    dest = _volume_dir(vol) / stored_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    mt = mime_type or (mimetypes.guess_type(safe)[0] or "application/octet-stream")
    return store.add_object(volume_id, path=stored_name, name=name, mime_type=mt,
                            size_bytes=len(data), org_id=oid)


def list_objects(volume_id: str, org_id: Optional[str] = None) -> List[VolumeObject]:
    return store.list_objects(volume_id, org_id=org_id)


def read_object(object_id: str, org_id: Optional[str] = None) -> bytes:
    """Read an object's bytes back from its tenant-pathed location."""
    oid = org_id or current_org_id()
    obj = store.get_object(object_id, org_id=oid)
    if obj is None:
        raise ValueError(f"object '{object_id}' not found")
    vol = store.get_volume(obj.volume_id, org_id=oid)
    if vol is None:
        raise ValueError(f"volume '{obj.volume_id}' not found")
    return (_volume_dir(vol) / obj.path).read_bytes()


def delete_object(object_id: str, org_id: Optional[str] = None) -> bool:
    """Remove an object's bytes and its metadata row."""
    oid = org_id or current_org_id()
    obj = store.get_object(object_id, org_id=oid)
    if obj is None:
        return False
    vol = store.get_volume(obj.volume_id, org_id=oid)
    if vol is not None:
        try:
            (_volume_dir(vol) / obj.path).unlink(missing_ok=True)
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "volume object unlink", counter="volumes.unlink")
    return store.delete_object(object_id, org_id=oid)
