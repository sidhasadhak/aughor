"""HB-3 — the manifest's doors: file a thing on an object, read what is filed, close it
with an outcome.

The chain files automatically when a send declares what it is `about`; these doors are
for the person — filing a ticket that arrived some other way, reading a promise's chain
(finding → ticket → close) and recording the outcome that graduates a push from noise to
value. The close snapshots the object's stamped measures beside the filing's, so
"breach rate before and after" is two recorded facts with the chain between them.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from aughor.hub.links import close_link, file_link, get_link, list_links

router = APIRouter(tags=["links"])

_KINDS = ("ticket", "thread", "webhook", "doc")


class FileLinkBody(BaseModel):
    object_ref: str          # securable string: promise:… process:… finding:… entity:…
    kind: str
    ref: str = ""            # OPS-123 · channel:ts · the caller's own reference
    url: str = ""
    title: str = ""


@router.post("/links")
def file_one(body: FileLinkBody):
    if body.kind not in _KINDS:
        raise HTTPException(status_code=422,
                            detail=f"kind must be one of {', '.join(_KINDS)}")
    if ":" not in body.object_ref:
        raise HTTPException(status_code=422,
                            detail="object_ref must be a securable string (kind:id)")
    from aughor.org.context import current_user_id
    uid = current_user_id()
    return file_link(object_ref=body.object_ref.strip(), kind=body.kind,
                     ref=body.ref.strip(), url=body.url.strip(), title=body.title,
                     source=f"user:{uid}" if uid else "user:")


@router.get("/links")
def get_links(object_ref: Optional[str] = Query(default=None),
              status: Optional[str] = Query(default=None),
              kind: Optional[str] = Query(default=None),
              limit: int = Query(default=100, ge=1, le=500)):
    return {"links": list_links(object_ref=object_ref, status=status, kind=kind,
                                limit=limit)}


@router.get("/links/{link_id}")
def get_one(link_id: str):
    row = get_link(link_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Link not found")
    return row


class CloseBody(BaseModel):
    outcome: str
    number_recovered: str = ""


@router.post("/links/{link_id}/close")
def close_one(link_id: str, body: CloseBody):
    """The outcome column: what happened, and the object's stamped measures re-read at
    close beside the filing's — before and after, recorded."""
    if not body.outcome.strip():
        raise HTTPException(status_code=422, detail="outcome must say what happened")
    from aughor.org.context import current_user_id
    uid = current_user_id()
    row = close_link(link_id, outcome=body.outcome.strip(),
                     number_recovered=body.number_recovered.strip(),
                     closed_by=f"user:{uid}" if uid else "user:")
    if row is None:
        raise HTTPException(status_code=404, detail="Link not found")
    return row
