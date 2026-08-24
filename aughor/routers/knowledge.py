"""Knowledge — document ingestion and glossary management."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from aughor.semantic.glossary import load_glossary, update_column, update_table

logger = logging.getLogger(__name__)
router = APIRouter(tags=["knowledge"])


# ── Documents ─────────────────────────────────────────────────────────────────

#: The file types the parser can read. One list, used by upload AND preview — a preview
#: that accepted what upload rejects would show a person chunks they can never index.
_ALLOWED_SUFFIXES = {".pdf", ".docx", ".md", ".txt", ".markdown"}

#: Chunks returned by a preview. Enough to judge the settings, not the whole document —
#: this runs on every keystroke-ish adjustment and the point is that it stays cheap.
_PREVIEW_CHUNKS = 10


def _settings_from(raw: Optional[str]):
    """Parse a JSON settings blob from a form field, or the defaults when absent."""
    import json

    from aughor.knowledge.documents import ChunkSettings, ChunkSettingsError

    if not raw:
        return None                      # None means "the defaults", all the way down
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"chunk settings are not JSON: {exc}")
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=422, detail="chunk settings must be an object")
    try:
        return ChunkSettings.from_dict(parsed)
    except ChunkSettingsError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


async def _spool(file: UploadFile):
    """Write an upload to a temp file the parsers can read, after checking its type."""
    import tempfile
    from pathlib import Path as _Path

    suffix = _Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type '{suffix}'. "
                   f"Allowed: {', '.join(sorted(_ALLOWED_SUFFIXES))}",
        )
    content = await file.read()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        return _Path(tmp.name)


@router.post("/documents/preview")
async def preview_document_chunks(file: UploadFile = File(...),
                                  chunk_settings: Optional[str] = Form(None)):
    """Chunk a document and return the first chunks WITHOUT indexing it.

    KB-2. Chunk settings are only meaningful if a person can see what they do, and the
    alternative to seeing is uploading, looking at a number, deleting and trying again —
    with an embedding call per attempt against a local model.

    Deliberately embeds nothing and writes nothing: no vector store, no registry, no
    `doc_id`. That is what makes it safe to call repeatedly, and it also means a preview
    works when the embedder is DOWN — the one moment a person most needs to know their
    settings are sane before they queue an upload.
    """
    from aughor.knowledge.documents import (DEFAULT_CHUNK_SETTINGS, chunk_text,
                                            extract_text)

    settings = _settings_from(chunk_settings)
    path = await _spool(file)
    try:
        raw = extract_text(path)
    except Exception:
        logger.exception("Document parsing failed during preview")
        raise HTTPException(status_code=422, detail="No text could be extracted")
    finally:
        path.unlink(missing_ok=True)

    chunks = chunk_text(raw, title="preview", filename=file.filename or "preview",
                        settings=settings)
    shown = chunks[:_PREVIEW_CHUNKS]
    return {
        "total_chunks": len(chunks),
        "shown": len(shown),
        "characters": len(raw),
        # The settings that PRODUCED this, echoed back — a preview whose settings are
        # implicit cannot be compared with the next one.
        "settings": (settings or DEFAULT_CHUNK_SETTINGS).as_dict(),
        "chunks": [{
            "index": c.chunk_index,
            "characters": len(c.text),
            # Estimated, and named so. A real count needs the embedder's tokeniser, which
            # this endpoint exists to avoid calling.
            "tokens_estimate": max(1, len(c.text) // 4),
            "text": c.text,
        } for c in shown],
    }


@router.post("/documents/upload", status_code=201)
async def upload_document(file: UploadFile = File(...),
                          chunk_settings: Optional[str] = Form(None)):
    """Upload a PDF, Word, Markdown, or plain-text document for semantic indexing."""
    from pathlib import Path as _Path

    settings = _settings_from(chunk_settings)
    tmp_path = await _spool(file)
    try:
        from aughor.knowledge.indexer import index_file
        entry = index_file(tmp_path,
                           title=_Path(file.filename or "").stem.replace("_", " ").replace("-", " ").title(),
                           settings=settings)
        entry["filename"] = file.filename or entry["filename"]
        return entry
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        logger.exception("Document indexing failed")
        raise HTTPException(status_code=500, detail="Indexing failed")
    finally:
        tmp_path.unlink(missing_ok=True)


class ReindexIn(BaseModel):
    """`dry_run` defaults TRUE. Everything this endpoint can do is destructive."""
    dry_run: bool = True
    purge_orphans: bool = False


@router.post("/documents/reindex")
def reindex_documents(body: ReindexIn):
    """Re-embed the corpus with the ACTIVE model, and stop the registry claiming chunks the
    store does not hold.

    Needed the moment embeddings became a switch: a different model is a different vector
    space, and a different WIDTH means the collection must be rebuilt. Live measurement that
    prompted it — a hosted embedding model returned 3072 against a stored 768. (The id
    is deliberately not written here: the package names no hosted model, and a rot-guard
    enforces that even in prose, because prose is where a convenient default starts.)

    ⚠️ It recovers what the STORE holds and nothing more. Uploaded files are unlinked after
    indexing, so a chunk absent from the store has no source anywhere; the plan reports that
    count as `unrecoverable_chunks` rather than letting a person infer a full recovery.
    """
    from aughor.knowledge import reindex

    if body.dry_run:
        return {"dry_run": True, **reindex.plan(purge_orphans=body.purge_orphans)}
    try:
        return {"dry_run": False, **reindex.run(purge_orphans=body.purge_orphans)}
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception:
        logger.exception("Re-index failed")
        raise HTTPException(status_code=500, detail="Re-index failed; the corpus is unchanged")


@router.get("/knowledge/status")
def knowledge_status_endpoint():
    """Whether the knowledge plane can index, can search, and holds what it claims.

    Exists because an empty search result had four possible causes and one appearance. The
    surface that shows a knowledge base has to be able to tell a person which of them
    happened — "no match" and "your embedder is not running" are not the same news.
    """
    from aughor.knowledge.health import knowledge_status

    return knowledge_status()


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
def list_org_intelligence_endpoint(connection_id: str | None = None, schema: str | None = None):
    """List insights promoted to the org-wide intelligence collection.

    Unscoped → the whole collection (the Org panel). With ``connection_id`` (and
    optionally ``schema``) → only that scope's promotions, so scoped surfaces
    (the Hub) don't blend every connection's insights together."""
    from aughor.knowledge.org_intelligence import list_org_intelligence
    return list_org_intelligence(connection_id=connection_id, schema=schema)


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


# `schema` rides as a QUERY param, not a path segment: `/glossary/{table}` and
# `/glossary/{table}/{column}` are already two- and three-segment routes, so a schema segment
# would be ambiguous with a column. Additive and optional — an omitted schema keeps the old
# unqualified behaviour, so existing callers are unaffected.

@router.put("/glossary/{table}")
def put_table_glossary(table: str, req: UpdateTableRequest, schema: Optional[str] = None):
    update_table(table, description=req.description, grain=req.grain, joins=req.joins,
                 schema=schema)
    return {"ok": True, "table": table, "schema": schema}


@router.put("/glossary/{table}/{column}")
def put_column_glossary(table: str, column: str, req: UpdateColumnRequest,
                        schema: Optional[str] = None):
    update_column(table, column, description=req.description, values=req.values,
                  caveats=req.caveats, schema=schema)
    return {"ok": True, "table": table, "column": column, "schema": schema}
