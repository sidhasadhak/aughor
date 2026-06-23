"""Volumes API — the governed unstructured tier (catalog-scoped).

Create volumes under a catalog and put/list/get/delete objects. Bytes are stored at
the tenant path the control plane vends; the metadata catalog is what SQL queries.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from aughor import volumes

router = APIRouter(prefix="/metastore", tags=["volumes"])


class CreateVolumeRequest(BaseModel):
    name: str


@router.post("/catalogs/{catalog_id}/volumes")
def create_volume(catalog_id: str, req: CreateVolumeRequest) -> dict:
    try:
        return volumes.create_volume(catalog_id, req.name).model_dump()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/catalogs/{catalog_id}/volumes")
def list_volumes(catalog_id: str) -> dict:
    return {"volumes": [v.model_dump() for v in volumes.list_volumes(catalog_id)]}


@router.post("/volumes/{volume_id}/objects")
async def put_object(volume_id: str, file: UploadFile) -> dict:
    data = await file.read()
    try:
        obj = volumes.put_object(volume_id, file.filename or "object", data,
                                 mime_type=file.content_type or "")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return obj.model_dump()


@router.get("/volumes/{volume_id}/objects")
def list_objects(volume_id: str) -> dict:
    return {"objects": [o.model_dump() for o in volumes.list_objects(volume_id)]}


@router.get("/volumes/{volume_id}/objects/{object_id}/content")
def get_object_content(volume_id: str, object_id: str) -> Response:
    from aughor.volumes import store as vol_store
    obj = vol_store.get_object(object_id)
    if obj is None or obj.volume_id != volume_id:
        raise HTTPException(status_code=404, detail=f"object '{object_id}' not found")
    try:
        data = volumes.read_object(object_id)
    except Exception:
        raise HTTPException(status_code=404, detail="object bytes not found")
    return Response(content=data, media_type=obj.mime_type or "application/octet-stream")


@router.delete("/volumes/{volume_id}/objects/{object_id}")
def delete_object(volume_id: str, object_id: str) -> dict:
    return {"deleted": volumes.delete_object(object_id)}
