"""Knowledge — document ingestion and glossary management."""
from __future__ import annotations

import logging
import re
from pathlib import Path as _Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from aughor.semantic.glossary import load_glossary, update_column, update_table

logger = logging.getLogger(__name__)
router = APIRouter(tags=["knowledge"])


# ── Documents ─────────────────────────────────────────────────────────────────

def _allowed_suffixes() -> frozenset[str]:
    """The file types the parser can read — ASKED of the converter, not restated here.

    This was a hand-written set of five. A hand-written allowlist is a claim about
    another module's capability, and it rots in the safe-looking direction: the
    converter gained fourteen formats and the set kept refusing them, so the product
    was capped by a literal nobody remembered to edit. Derived, it cannot drift.

    Still one source for upload AND preview — a preview that accepted what upload
    rejects would show a person chunks they can never index.
    """
    from aughor.knowledge.convert import supported_suffixes
    return supported_suffixes()

#: Chunks returned by a preview. Enough to judge the settings, not the whole document —
#: this runs on every keystroke-ish adjustment and the point is that it stays cheap.
_PREVIEW_CHUNKS = 10


def _safe_download_name(stem: str) -> str:
    """A filename safe to put in a Content-Disposition header.

    The title comes from an uploaded file's name, so it is attacker-influenceable. A
    quote or a newline in it would break out of the quoted string and let a caller
    write their own headers; stripping to a conservative set is the whole defence.
    """
    cleaned = re.sub(r'[^A-Za-z0-9 ._-]', "_", stem).strip() or "document"
    return cleaned[:120]


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


async def _read_upload(file: UploadFile) -> bytes:
    """The upload's bytes, with its extension checked before anything reads them.

    The extension check is a courtesy that fails fast with a helpful message; it is
    NOT the safety boundary. `convert.to_markdown` decides what a file really is from
    its content, so a `.pdf` that is secretly a ZIP is refused there even though it
    passes here.
    """
    from pathlib import Path as _Path

    allowed = _allowed_suffixes()
    suffix = _Path(file.filename or "").suffix.lower()
    if suffix not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type '{suffix or '(none)'}'. "
                   f"Allowed: {', '.join(sorted(allowed))}",
        )
    return await file.read()


async def _spool(file: UploadFile):
    """`_read_upload` to a temp file, for the callers that still need a path."""
    import tempfile
    from pathlib import Path as _Path

    content = await _read_upload(file)
    suffix = _Path(file.filename or "").suffix.lower()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        return _Path(tmp.name)


@router.get("/documents/formats")
def document_formats():
    """What this deployment can actually read, for the drop zone to advertise.

    The UI used to carry its own copy of the list (`.pdf,.docx,.md,.txt,.markdown`).
    Two hand-written lists of the same fact drift apart, and they drift silently: the
    converter gained fourteen formats and the drop zone went on rejecting them in the
    file picker, so the capability existed and was unreachable. Served, there is one
    list and it is the one the parser enforces.

    `converter` reports whether the document converter is installed at all — without
    it only Markdown and plain text can be read, and the UI should say so rather than
    offering formats that will fail.
    """
    from aughor.knowledge.convert import available, document_suffixes

    return {
        "suffixes": sorted(_allowed_suffixes()),
        "accept": ",".join(sorted(_allowed_suffixes())),
        "converter": available(),
        "converts": sorted(document_suffixes()),
    }


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
                                            extract_text, numeric_run_lines)

    from aughor.knowledge.convert import ConversionError

    settings = _settings_from(chunk_settings)
    path = await _spool(file)
    try:
        raw = extract_text(path)
    except ConversionError as exc:
        # The same typed reason upload gives. A preview that answers "No text could be
        # extracted" for a scanned PDF sends a person to look at their file, when what
        # they need to be told is that it has no text layer.
        raise HTTPException(status_code=422,
                            detail={"message": str(exc), "code": exc.code})
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
        # Same rule as upload, reported the same way — a preview that silently kept
        # what upload holds back would misrepresent what is searchable.
        "suppressed_numeric_runs": len(
            numeric_run_lines(raw)
            if (settings or DEFAULT_CHUNK_SETTINGS).suppress_numeric_runs else []),
        "chunks": [{
            "index": c.chunk_index,
            "characters": len(c.text),
            # Estimated, and named so. A real count needs the embedder's tokeniser, which
            # this endpoint exists to avoid calling.
            "tokens_estimate": max(1, len(c.text) // 4),
            "text": c.text,
        } for c in shown],
    }


@router.post("/documents/convert")
async def convert_document_only(file: UploadFile = File(...),
                                chunk_settings: Optional[str] = Form(None)):
    """Convert a document and hand back the Markdown WITHOUT indexing or keeping it.

    The look-before-you-commit step. Upload used to convert, chunk, embed and register
    in one motion, so the first time anyone saw what the converter made of their file
    was after it was already in the corpus — and on a hosted embedder, already paid
    for. A scanned deck that yields eight unreadable pages, or a spreadsheet that comes
    out as a wall of numbers, is a decision a person should get to make BEFORE it costs
    anything and before it starts answering questions.

    Writes nothing: no registry row, no vectors, no retained bytes. The client keeps the
    file and posts it again to `/documents/upload` on approval — deliberately, so there
    is no staging area to expire, sweep, or leak. Conversion is deterministic, so what
    is approved here is exactly what is indexed there.

    Reports the same page and suppression detail upload reports, because the decision
    being asked for is whether THIS is worth indexing.
    """
    from aughor.knowledge.convert import ConversionError, convert_document
    from aughor.knowledge.documents import (DEFAULT_CHUNK_SETTINGS, chunk_text,
                                            numeric_run_lines)

    settings = _settings_from(chunk_settings)
    filename = file.filename or "document"
    data = await _read_upload(file)

    try:
        converted = convert_document(data, filename)
    except ConversionError as exc:
        raise HTTPException(status_code=422,
                            detail={"message": str(exc), "code": exc.code})

    effective = settings or DEFAULT_CHUNK_SETTINGS
    suppressed = (numeric_run_lines(converted.markdown)
                  if effective.suppress_numeric_runs else [])
    # The chunk count this WOULD produce, so "add it" is not a leap in the dark. Costs
    # nothing: chunking is string work, and no embedder is touched.
    chunks = chunk_text(converted.markdown, title=filename, filename=filename,
                        settings=settings)

    return {
        "filename": filename,
        "markdown": converted.markdown,
        "characters": len(converted.markdown),
        "would_index_chunks": len(chunks),
        "page_count": converted.page_count,
        "pages_read": len(converted.pages_read),
        "pages_needing_ocr": converted.pages_needing_ocr,
        "pages_failed": converted.pages_failed,
        "suppressed_numeric_runs": len(suppressed),
        "suppressed_sample": [line.strip()[:160] for line in suppressed[:3]],
        # Content the document GAINED. A chart's values are in the file as exact text
        # that Markdown cannot carry, so they are read back from their positions and
        # appended as tables — said out loud at the door, because a person approving a
        # document should know it now contains more than the converter alone produced.
        "charts_recovered": converted.charts_recovered,
        "chart_pages": converted.chart_pages,
        "settings": effective.as_dict(),
    }


@router.post("/documents/upload", status_code=201)
async def upload_document(file: UploadFile = File(...),
                          chunk_settings: Optional[str] = Form(None)):
    """Upload any supported document: convert it to Markdown, index it, KEEP it.

    Three things happen here, in an order that matters. The bytes are converted to
    Markdown once. The Markdown is chunked and embedded. Both the original bytes and
    the Markdown are retained under the document's id.

    That last step is new, and it is the reason the rest of the documents section can
    exist. This handler used to spool the upload to a temp file and unlink it in a
    `finally:` — the document was destroyed the moment it was indexed. A preview had
    nothing to show but chunk text, conversion had nothing to convert, and a re-index
    could only re-embed the old parse because the source was gone.

    Conversion runs BEFORE indexing on purpose: a file that cannot be read must fail
    with its own reason ("this PDF is scanned", "this document is password-protected")
    rather than producing zero chunks and a generic complaint about no text.
    """
    from pathlib import Path as _Path

    from aughor.knowledge import blobs
    from aughor.knowledge.convert import ConversionError, convert_document

    settings = _settings_from(chunk_settings)
    filename = file.filename or "document"
    data = await _read_upload(file)

    try:
        converted = convert_document(data, filename)
    except ConversionError as exc:
        # 422 with the machine-readable code, so a client can offer the right remedy
        # (OCR, a password, a smaller file) instead of parsing the English.
        raise HTTPException(status_code=422,
                            detail={"message": str(exc), "code": exc.code})
    markdown = converted.markdown

    # What was held back from SEARCH. Quietly indexing less than the document
    # contains is the same class of failure as quietly indexing more, so the count
    # travels with the response and the lines themselves stay in the document.
    from aughor.knowledge.documents import DEFAULT_CHUNK_SETTINGS, numeric_run_lines
    effective = settings or DEFAULT_CHUNK_SETTINGS
    suppressed = numeric_run_lines(markdown) if effective.suppress_numeric_runs else []

    title = _Path(filename).stem.replace("_", " ").replace("-", " ").title()
    try:
        from aughor.knowledge.indexer import index_text
        entry = index_text(text=markdown, title=title, source=filename,
                           settings=settings)
    except Exception:
        logger.exception("Document indexing failed")
        raise HTTPException(status_code=500, detail="Indexing failed")

    # Zero chunks is a FAILED upload, and it has to be said out loud here.
    # `index_text` returns early without registering when chunking yields nothing,
    # so a 201 at this point would hand back a doc_id that is in no list, cannot be
    # fetched and cannot be deleted — the person is told "Created" and has nothing.
    # The usual cause is a document shorter than `min_chars`, which is a setting they
    # control, so the message names it instead of saying "no text could be extracted".
    if not entry.get("chunk_count"):
        from aughor.knowledge.documents import DEFAULT_CHUNK_SETTINGS
        floor = (settings or DEFAULT_CHUNK_SETTINGS).min_chars
        raise HTTPException(
            status_code=422,
            detail={"message": (
                        f"Nothing was indexed: the document is {len(markdown)} "
                        f"characters and chunks shorter than {floor} are discarded. "
                        f"Lower the minimum chunk length to index it."),
                    "code": "no_chunks"})

    doc_id = entry["doc_id"]
    try:
        blobs.put_original(doc_id, filename, data)
        blobs.put_markdown(doc_id, markdown)
    except OSError:
        # Retention is best-effort against a full or read-only disk. The document IS
        # indexed and searchable at this point; losing the original costs preview and
        # conversion, which `has_original: false` reports honestly, and is not worth
        # failing an otherwise successful upload over.
        logger.exception("Could not retain original bytes for %s", doc_id)

    entry["filename"] = filename
    entry["characters"] = len(markdown)
    # A part-scanned PDF imports the pages that HAVE a text layer, so the response has
    # to say which ones did not — otherwise "indexed" reads as "all of it", and the
    # pages behind a scanned cover go missing with nothing to notice.
    if converted.page_count:
        entry["page_count"] = converted.page_count
        entry["pages_read"] = len(converted.pages_read)
        entry["pages_needing_ocr"] = converted.pages_needing_ocr
        # Reported apart, because the remedies differ: OCR fixes one and nothing the
        # person can buy fixes the other.
        entry["pages_failed"] = converted.pages_failed
    if suppressed:
        entry["suppressed_numeric_runs"] = len(suppressed)
        # A sample, not the lot: enough for a person to recognise what was held back
        # and object if it was wrong, without shipping the document back to them.
        entry["suppressed_sample"] = [line.strip()[:160] for line in suppressed[:3]]
    if converted.charts_recovered:
        entry["charts_recovered"] = converted.charts_recovered
        entry["chart_pages"] = converted.chart_pages
    entry.update(blobs.info(doc_id))
    return entry


@router.get("/documents/{doc_id}/markdown")
def document_markdown(doc_id: str):
    """The document as Markdown — what every agent, canvas and prompt actually reads.

    Served from the cache when it is there and re-converted from the original when it
    is not, so this answers for documents stored before the cache existed.
    """
    from aughor.knowledge import blobs
    from aughor.knowledge.indexer import get_document

    if get_document(doc_id) is None:
        raise HTTPException(status_code=404, detail="Document not found")
    text = blobs.markdown(doc_id)
    if text is None:
        raise HTTPException(
            status_code=409,
            detail={"message": "This document was uploaded before originals were "
                               "retained, so it cannot be re-read. Re-upload it to "
                               "enable preview and conversion.",
                    "code": "no_original"})
    return {"doc_id": doc_id, "markdown": text, "characters": len(text)}


@router.get("/documents/{doc_id}/convert")
def convert_document(doc_id: str, to: str = "pdf"):
    """Hand a stored document back in a different format.

    The other half of the pivot. Anything readable became Markdown on the way in; this
    renders that Markdown into any format the deployment can write — so a PowerPoint
    deck can leave as a PDF, and a scanned-in Word report as clean HTML, without a
    converter per pair.

    Rendered from the CACHED Markdown, or re-converted from the original when the
    cache is cold. A document whose original was never retained can still be converted
    if its Markdown survives; only one with neither is refused.
    """
    from fastapi.responses import Response

    from aughor.knowledge import blobs
    from aughor.knowledge.indexer import get_document
    from aughor.knowledge.render import RenderError, render

    doc = get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    markdown = blobs.markdown(doc_id)
    if markdown is None:
        raise HTTPException(
            status_code=409,
            detail={"message": "Nothing is retained for this document to convert from. "
                               "Re-upload it to enable conversion.",
                    "code": "no_original"})

    title = doc.get("title") or "Document"
    try:
        data, media_type, suffix = render(markdown, to, title=title)
    except RenderError as exc:
        # 422 for "you asked for a format that does not exist", 501 for "this
        # deployment cannot write it" — a person can fix the first and only an
        # operator can fix the second.
        status = 501 if exc.code == "renderer_missing" else 422
        raise HTTPException(status_code=status,
                            detail={"message": str(exc), "code": exc.code})

    stem = _Path(doc.get("filename") or title).stem or "document"
    return Response(
        content=data, media_type=media_type,
        headers={"Content-Disposition":
                 f'attachment; filename="{_safe_download_name(stem)}{suffix}"'})


@router.get("/documents/{doc_id}/formats")
def document_convert_formats(doc_id: str):
    """What this document can be turned into HERE — not what the code can do in theory.

    PDF and PowerPoint need the `export` extra; offering them on a deployment without
    it produces a button that fails at the click, which is worse than a button that
    was never shown.
    """
    from aughor.knowledge.render import available_formats

    return {"doc_id": doc_id, "formats": available_formats()}


@router.get("/documents/{doc_id}/original")
def document_original(doc_id: str):
    """The document's own bytes, for a real preview.

    Inline rather than attachment, so a browser renders the PDF instead of downloading
    it; the filename is quoted for a Content-Disposition header and never interpolated
    from user input unescaped.
    """
    import mimetypes

    from fastapi.responses import FileResponse

    from aughor.knowledge import blobs
    from aughor.knowledge.indexer import get_document

    doc = get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    path = blobs.original_path(doc_id)
    if path is None:
        raise HTTPException(
            status_code=409,
            detail={"message": "The original was not retained for this document.",
                    "code": "no_original"})
    name = doc.get("filename") or path.name
    media = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media,
                        content_disposition_type="inline", filename=name)


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

    ⚠️ It recovers what the STORE holds and nothing more. The plan reports what it cannot
    reach as `unrecoverable_chunks` rather than letting a person infer a full recovery.

    That count is now smaller than it was, and shrinking. Uploads used to be unlinked
    straight after indexing, so a chunk missing from the store had no source anywhere;
    documents uploaded since retention began keep their original bytes and CAN be read
    again from source. This endpoint does not do that yet — it re-embeds — but the
    material a real re-read needs is on disk, which it never was before.
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


@router.post("/documents/purge-orphans")
def purge_orphans_endpoint(dry_run: bool = True):
    """Remove chunks whose document is no longer in the registry, WITHOUT re-embedding.

    Separate from `/documents/reindex` because the costs are not comparable. That route
    re-embeds the entire corpus on its way past the orphans — on a hosted embedder,
    148 chunks paid for to delete 14. An orphan needs no vector to be deleted.

    `dry_run` defaults TRUE, like its sibling: everything below it is destructive.
    """
    from aughor.knowledge import reindex

    if dry_run:
        return {"dry_run": True, **reindex.plan(purge_orphans=True)}
    try:
        return {"dry_run": False, **reindex.purge_orphans_only()}
    except Exception:
        logger.exception("Orphan purge failed")
        raise HTTPException(status_code=500,
                            detail="Purge failed; the index is unchanged")


class RestoreDoctreesIn(BaseModel):
    """`dry_run` defaults TRUE, like its sibling. `connection_id` limits it to one."""
    dry_run: bool = True
    connection_id: Optional[str] = None


@router.post("/documents/restore-doctrees")
def restore_doctrees(body: RestoreDoctreesIn):
    """Put the schema documentation back into the store from its persisted artifact.

    `/documents/reindex` re-embeds what the store holds; when the store has lost chunks,
    that is all it can do. Schema docs are the exception, because the ontology compiles
    them to a doc tree on disk before anything is embedded — so the artifact, not the
    collection, is their source. Measured live: a store holding 5 chunks for a document
    whose artifact held 59 table docs, with no path back in short of re-running
    intelligence over the whole connection to rebuild something already compiled.

    Scoped to connections that still exist. An artifact can outlive its connection, and a
    restore that ignored the registry would resurrect exactly the documents a purge just
    removed; those trees are reported under `skipped` with the reason rather than dropped
    quietly. Each document is replaced independently, so a partial failure names what
    failed instead of leaving the caller to infer it.
    """
    from aughor.knowledge import reindex

    if body.dry_run:
        return {"dry_run": True, **reindex.doctree_plan(connection_id=body.connection_id)}
    try:
        return {"dry_run": False, **reindex.doctree_restore(connection_id=body.connection_id)}
    except Exception:
        logger.exception("Doc-tree restore failed")
        raise HTTPException(status_code=500, detail="Restore failed; the corpus is unchanged")


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
    """The corpus, each row saying what is actually retained for it.

    `has_original` is the field the UI branches on — it decides whether a row offers
    preview and conversion or only search. It is read from disk per row rather than
    stored on the registry entry, because the registry cannot know that a directory
    was cleared underneath it, and a row claiming a preview that 404s is worse than a
    row that never offered one.
    """
    from aughor.knowledge import blobs
    from aughor.knowledge.indexer import is_generated, list_documents

    return [{**doc, **blobs.info(doc["doc_id"]),
             # Compiled schema documentation shares this collection with uploads, which
             # is right for retrieval and wrong for this list. Flagged rather than
             # filtered: the surface decides how to present them, and a caller that
             # wants everything still gets everything.
             "generated": is_generated(doc["doc_id"])}
            for doc in list_documents()]


@router.delete("/documents/{doc_id}")
def delete_document_endpoint(doc_id: str):
    """Remove a document from the registry, the vector store, AND disk.

    The retained bytes are deleted here rather than in `delete_document` so that the
    indexer keeps knowing nothing about the blob store. Deleting them is not optional
    housekeeping: a person who deletes a document has asked for their file to be gone,
    and leaving the original on disk after the row disappears would be the one copy
    nothing in the product can see or reach.
    """
    from aughor.knowledge import blobs
    from aughor.knowledge.indexer import delete_document

    if not delete_document(doc_id):
        raise HTTPException(status_code=404, detail="Document not found")
    blobs.delete(doc_id)
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


# ── Knowledge sources (2026-09-06) — Confluence / Notion, on the documents surface ──
#
# Both connectors were built, reachable per-connection (`/connections/{id}/knowledge-sync`),
# and impossible to CREATE: they are deliberately not in `REGISTRY.supported_types()`
# ("not DB connectors — open_connection() is not called on them"), so `POST /connections`
# would fail them at its connect test and no catalog row ever offered them. The decision
# (2026-09-06, the user's): they surface HERE, with documents — they feed the doc KB, not
# tables — and the data catalog's category ratchet (`test_connector_categories`) stays
# exactly as pinned.

_KNOWLEDGE_SOURCE_TYPES = ("confluence", "notion")

_KNOWLEDGE_SOURCE_LABELS = {"confluence": "Confluence", "notion": "Notion"}


def _knowledge_syncer(conn_type: str, conn_id: str, meta: dict):
    if conn_type == "confluence":
        from aughor.connectors.knowledge.confluence import ConfluenceSync
        return ConfluenceSync(conn_id, meta)
    from aughor.connectors.knowledge.notion import NotionSync
    return NotionSync(conn_id, meta)


class KnowledgeSourceIn(BaseModel):
    conn_type: str
    name: str
    config: dict[str, str] = {}


@router.get("/knowledge/sources")
def list_knowledge_sources():
    """The Documents surface's source catalog: what can be connected (form fields
    SERVED from the connector registry, never mirrored into the client) and what is
    connected, each with its sync state. Secret values never leave the server —
    only the field descriptors do."""
    from aughor.connectors.registry import FORM_FIELDS
    from aughor.db.registry import get_meta, list_connections

    types = [{"conn_type": t,
              "label": _KNOWLEDGE_SOURCE_LABELS[t],
              "fields": FORM_FIELDS.get(t, [])}
             for t in _KNOWLEDGE_SOURCE_TYPES]

    sources = []
    for conn in list_connections():
        if conn.get("conn_type") not in _KNOWLEDGE_SOURCE_TYPES:
            continue
        entry = {"id": conn.get("id"), "name": conn.get("name"),
                 "conn_type": conn.get("conn_type"), "status": None}
        try:
            syncer = _knowledge_syncer(conn["conn_type"], conn["id"], get_meta(conn["id"]))
            entry["status"] = syncer.status()
        except Exception as exc:
            entry["error"] = str(exc)
        sources.append(entry)
    return {"types": types, "sources": sources}


@router.post("/knowledge/sources", status_code=201)
async def create_knowledge_source(body: KnowledgeSourceIn):
    """Connect a knowledge source. The credentials are tested against the live
    counterparty BEFORE the record exists (mirroring `POST /connections`) — a saved
    source that was never reachable would sit in the list as a sync that quietly
    indexes nothing. Secret config fields are Fernet-encrypted by the connection
    registry on write."""
    import asyncio

    from aughor.db.registry import add_connection

    if body.conn_type not in _KNOWLEDGE_SOURCE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"unknown knowledge source {body.conn_type!r} — "
                   f"known: {list(_KNOWLEDGE_SOURCE_TYPES)}")
    if not (body.name or "").strip():
        raise HTTPException(status_code=400, detail="name is required")

    config = {k: v for k, v in (body.config or {}).items() if str(v or "").strip()}
    try:
        syncer = _knowledge_syncer(body.conn_type, "pending", config)
    except ValueError as exc:  # the connector names its own required fields
        raise HTTPException(status_code=400, detail=str(exc))

    loop = asyncio.get_running_loop()
    ok, msg = await loop.run_in_executor(None, syncer.test)
    if not ok:
        raise HTTPException(status_code=400, detail=f"Source test failed: {msg}")

    dsn = config.get("base_url", "") if body.conn_type == "confluence" else "notion://"
    conn_id = add_connection(name=body.name.strip(), conn_type=body.conn_type,
                             dsn=dsn, meta=config)
    return {"id": conn_id, "message": f"{_KNOWLEDGE_SOURCE_LABELS[body.conn_type]} "
                                      f"source connected", "test_result": msg}
