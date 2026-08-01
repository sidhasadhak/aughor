"""Volume data models — the governed unstructured tier (PLATFORM_ARCHITECTURE.md §5.4).

Structured data lives in tables; unstructured objects (files, images, PDFs, video)
live in **Volumes**: the bytes sit in the object store under the tenant path (vended,
never ambient — Invariant #2), with a catalog row of metadata per object. SQL runs
over the *catalog* of objects ("all videos > 1 GB uploaded last week"); the R8
semantic operators (`prompt()` / `embedding()`) reason over `extracted_text` later.
This is the honest "SQL over any object": a governed catalog of objects, not "video
as a table".

A Volume belongs to a catalog (the catalog.volume namespace); UC's three-part
catalog.schema.volume is a later refinement.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, computed_field

from aughor.org.context import DEFAULT_ORG_ID


class Volume(BaseModel):
    """A governed container for unstructured objects within a catalog."""

    id: str
    org_id: str = DEFAULT_ORG_ID
    catalog_id: str
    name: str
    created_at: str = ""
    updated_at: str = ""

    @computed_field
    @property
    def full_name(self) -> str:
        return f"{self.catalog_id}.{self.name}"


class VolumeObject(BaseModel):
    """One object's metadata row — the catalog entry SQL queries. The bytes live at
    the tenant-pathed storage location the vending seam resolves."""

    id: str
    org_id: str = DEFAULT_ORG_ID
    volume_id: str
    path: str                          # storage path relative to the volume root
    name: str
    mime_type: str = ""
    size_bytes: int = 0
    extracted_text: Optional[str] = None   # filled by R8 extraction later
    created_at: str = ""
