"""Knowledge — document ingestion and glossary management."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from aughor.semantic.glossary import load_glossary, update_column, update_table

logger = logging.getLogger(__name__)
router = APIRouter(tags=["knowledge"])


# ── Documents ─────────────────────────────────────────────────────────────────

@router.post("/documents/upload", status_code=201)
async def upload_document(file: UploadFile = File(...)):
    """Upload a PDF, Word, Markdown, or plain-text document for semantic indexing."""
    import tempfile
    from pathlib import Path as _Path

    allowed = {".pdf", ".docx", ".md", ".txt", ".markdown"}
    suffix = _Path(file.filename or "").suffix.lower()
    if suffix not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type '{suffix}'. Allowed: {', '.join(sorted(allowed))}",
        )
    content = await file.read()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = _Path(tmp.name)
    try:
        from aughor.knowledge.indexer import index_file
        entry = index_file(tmp_path, title=_Path(file.filename or "").stem.replace("_", " ").replace("-", " ").title())
        entry["filename"] = file.filename or entry["filename"]
        return entry
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        logger.exception("Document indexing failed")
        raise HTTPException(status_code=500, detail="Indexing failed")
    finally:
        tmp_path.unlink(missing_ok=True)


@router.get("/documents")
def list_documents_endpoint():
    from aughor.knowledge.indexer import list_documents
    return list_documents()


@router.delete("/documents/{doc_id}")
def delete_document_endpoint(doc_id: str):
    from aughor.knowledge.indexer import delete_document
    if not delete_document(doc_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return {"ok": True, "doc_id": doc_id}


@router.post("/documents/search")
def search_documents_endpoint(body: dict):
    from aughor.knowledge.indexer import search_documents
    query = body.get("query", "")
    top_k = int(body.get("top_k", 5))
    return search_documents(query, top_k=top_k)


# ── Org Intelligence ──────────────────────────────────────────────────────────

@router.get("/org-intelligence")
def list_org_intelligence_endpoint():
    """List all insights promoted to the org-wide intelligence collection."""
    from aughor.knowledge.org_intelligence import list_org_intelligence
    return list_org_intelligence()


@router.delete("/org-intelligence/{point_id}")
def delete_org_intelligence_endpoint(point_id: str):
    """Remove a promoted insight from the org-wide collection."""
    from aughor.knowledge.org_intelligence import delete_org_insight
    if not delete_org_insight(point_id):
        raise HTTPException(status_code=404, detail="Org insight not found")
    return {"ok": True, "id": point_id}


# ── Glossary ──────────────────────────────────────────────────────────────────

@router.get("/glossary")
def get_glossary():
    return load_glossary()


class UpdateTableRequest(BaseModel):
    description: Optional[str] = None
    grain: Optional[str] = None
    joins: Optional[list[str]] = None


class UpdateColumnRequest(BaseModel):
    description: Optional[str] = None
    values: Optional[str] = None
    caveats: Optional[str] = None


@router.put("/glossary/{table}")
def put_table_glossary(table: str, req: UpdateTableRequest):
    update_table(table, description=req.description, grain=req.grain, joins=req.joins)
    return {"ok": True, "table": table}


@router.put("/glossary/{table}/{column}")
def put_column_glossary(table: str, column: str, req: UpdateColumnRequest):
    update_column(table, column, description=req.description, values=req.values, caveats=req.caveats)
    return {"ok": True, "table": table, "column": column}
