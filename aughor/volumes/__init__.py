"""Volumes — the governed unstructured tier (PLATFORM_ARCHITECTURE.md §5.4).

A Volume is a catalog-scoped container for unstructured objects (files, images, PDFs,
video). Bytes live under the tenant path the control plane vends; a metadata row per
object is the catalog SQL queries. R8 `prompt()`/`embedding()` over extracted content
is a later step.
"""
from aughor.volumes.models import Volume, VolumeObject
from aughor.volumes.ops import (
    create_volume,
    delete_object,
    list_objects,
    list_volumes,
    put_object,
    read_object,
)

__all__ = [
    "Volume", "VolumeObject",
    "create_volume", "list_volumes",
    "put_object", "list_objects", "read_object", "delete_object",
]
