"""Idea 7 · the fact-check door: a memo in, every number checked against the data.

Two ways in — pasted text, or an uploaded document converted by the same converter the
Documents tab uses (PDF, DOCX, PPTX, XLSX and the rest; charts inside a PDF come back as
tables). Out: an answer envelope (Arc CP), filed as a turn so it exports and reloads.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from aughor.security.authz import connection_owner_guard, get_principal

# DATA-06 — a door that names a connection asks whose it is, on every route.
router = APIRouter(tags=["factcheck"], dependencies=[Depends(connection_owner_guard)])

#: A memo, not a warehouse dump: the same ceiling the prose mapper takes.
MAX_CHARS = 60_000


class FactCheckRequest(BaseModel):
    text: str = Field(description="The document's text — a memo, an email, a pasted deck")
    connection_id: str
    schema_name: Optional[str] = Field(default=None, alias="schema")

    model_config = {"populate_by_name": True}


def _run(text: str, connection_id: str, schema_name: Optional[str], source: str) -> dict:
    from aughor.factcheck import factcheck
    if not (text or "").strip():
        raise HTTPException(status_code=400, detail="nothing to check: the text is empty")
    if len(text) > MAX_CHARS:
        raise HTTPException(status_code=413, detail=f"the text is longer than {MAX_CHARS} characters")
    env = factcheck(text, connection_id, schema_name=schema_name, source=source)
    return {"investigation_id": env.provenance.investigation_id, "envelope": env.model_dump()}


@router.post("/factcheck")
def factcheck_text(req: FactCheckRequest, principal=Depends(get_principal)) -> dict:
    """Check every numeric claim in pasted text against the connection's data."""
    return _run(req.text, req.connection_id, req.schema_name, "text")


@router.post("/factcheck/upload")
async def factcheck_upload(file: UploadFile = File(...), connection_id: str = Form(...),
                           schema_name: Optional[str] = Form(default=None),
                           principal=Depends(get_principal)) -> dict:
    """Check every numeric claim in an uploaded document — converted the way the Documents
    tab converts it, charts in a PDF read back as tables — against the connection's data."""
    from aughor.knowledge.convert import ConversionError, convert_document
    data = await file.read()
    try:
        conversion = convert_document(data, file.filename or "")
    except ConversionError as exc:
        raise HTTPException(status_code=422, detail=f"could not read the document: {exc}") from exc
    markdown = str(getattr(conversion, "markdown", "") or "")
    return _run(markdown, connection_id, schema_name, f"file {file.filename or ''}".strip())
