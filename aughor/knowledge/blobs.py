"""Where an uploaded document's ORIGINAL bytes live, beside its Markdown.

The plane this joins used to throw the original away. `upload_document` spooled the
upload to a temp file, extracted text, indexed the chunks, and then unlinked the
file in a `finally:`. The registry kept a filename and a chunk count; the bytes were
gone. Three things a documents section is expected to do were impossible as a direct
result, and none of them could be fixed anywhere else:

  * **Preview.** You cannot show a person their PDF when you no longer have it. The
    old "preview" showed chunk text — the shape of the parse, not the document.
  * **Convert.** Handing back a `.docx` as a PDF means re-rendering from something.
  * **Re-read.** Every improvement to extraction — this one included — is worthless
    on documents already uploaded if their source is gone. Retaining originals is
    what makes a re-index an actual re-read rather than a re-embed of an old parse.

So each document keeps two artefacts: the bytes exactly as uploaded, and the
Markdown they converted to. The Markdown is CACHED, not authoritative — the original
is the truth, and a conversion can always be redone from it when the converter
improves.

Layout and tenancy
------------------
    {AUGHOR_DOCUMENTS_DIR}/{org_id}/{doc_id}/original{suffix}
                                            /converted.md

Org-pathed from day one, the same shape `control_plane.vending` gives connection
uploads (§5.1) — so Arc MT's tenant isolation lands here for free rather than
needing a migration later.

It does NOT ride `vend_storage` itself, for two reasons. That seam is keyed by
*connection*, and a policy PDF belongs to no data connection — routing it through
one would mean inventing a fake connection id to satisfy the signature. And its
`STORAGE_ROOT` is bound at import, so a test that sets the env after import silently
writes to the developer's live tree. The root here is resolved **per call**, which
is the rule this codebase has now learned three times.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path

from aughor.org.context import current_org_id

logger = logging.getLogger(__name__)

#: The converted Markdown, cached beside the original. One fixed name — the original
#: keeps its own extension, this never needs one.
MARKDOWN_NAME = "converted.md"

_SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9._:-]")


def _root() -> Path:
    """Resolved PER CALL, never captured at import.

    A module-level `Path(os.environ[...])` is frozen by the first import, so a test
    (or a serverless boot) that sets the variable afterwards is ignored and the write
    lands in the developer's real `data/`. That has cost this codebase real data
    three times; the fix each time was this function shape.
    """
    return Path(os.environ.get("AUGHOR_DOCUMENTS_DIR") or "data/documents")


def _safe(segment: str) -> str:
    """A path segment that cannot escape its parent.

    `doc_id` is a uuid4 hex for uploads, but `doctree::{conn}::{schema}` ids also
    exist in the registry, and connection ids are user-named. Traversal is stripped
    rather than rejected because this runs on a delete path too, where refusing an
    id would strand bytes instead of removing them.
    """
    cleaned = _SAFE_SEGMENT.sub("_", (segment or "").replace("\\", "/").split("/")[-1])
    return cleaned.strip(".") or "unknown"


def doc_dir(doc_id: str, org_id: str | None = None) -> Path:
    """The directory holding one document's artefacts. Not created by this call."""
    return _root() / _safe(org_id or current_org_id()) / _safe(doc_id)


def put_original(doc_id: str, filename: str, data: bytes,
                 org_id: str | None = None) -> Path:
    """Store the uploaded bytes verbatim, keeping the original extension.

    Verbatim matters: the point of retaining the source is that a later conversion,
    or a re-read by a better parser, sees exactly what the person uploaded.
    """
    suffix = Path(filename or "").suffix.lower()[:16]
    dest = doc_dir(doc_id, org_id) / f"original{suffix}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def original_path(doc_id: str, org_id: str | None = None) -> Path | None:
    """The stored original, or None when this document predates byte retention.

    That None is a real and common state, not an error: every document uploaded
    before this existed has a registry row and no bytes. Callers must render it as
    "original not retained", never as a missing file.
    """
    directory = doc_dir(doc_id, org_id)
    if not directory.is_dir():
        return None
    for entry in sorted(directory.glob("original*")):
        if entry.is_file():
            return entry
    return None


def put_markdown(doc_id: str, markdown: str, org_id: str | None = None) -> Path:
    """Cache the converted Markdown beside the original."""
    dest = doc_dir(doc_id, org_id) / MARKDOWN_NAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(markdown, encoding="utf-8")
    return dest


def read_markdown(doc_id: str, org_id: str | None = None) -> str | None:
    """The cached Markdown, or None when it was never stored."""
    path = doc_dir(doc_id, org_id) / MARKDOWN_NAME
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def markdown(doc_id: str, org_id: str | None = None) -> str | None:
    """The document as Markdown — cached if present, re-converted if not.

    The re-conversion path is what makes the cache disposable: deleting the `.md`
    files is always safe, and a document stored before the cache existed still
    answers. Returns None only when there is nothing left to read from.
    """
    cached = read_markdown(doc_id, org_id)
    if cached is not None:
        return cached
    source = original_path(doc_id, org_id)
    if source is None:
        return None
    from aughor.knowledge.convert import ConversionError, to_markdown
    try:
        converted = to_markdown(source.read_bytes(), source.name)
    except ConversionError:
        logger.exception("Re-conversion failed for document %s", doc_id)
        return None
    put_markdown(doc_id, converted, org_id)
    return converted


def delete(doc_id: str, org_id: str | None = None) -> bool:
    """Remove a document's stored artefacts. False when there were none."""
    directory = doc_dir(doc_id, org_id)
    if not directory.is_dir():
        return False
    shutil.rmtree(directory, ignore_errors=True)
    return True


def info(doc_id: str, org_id: str | None = None) -> dict:
    """What is retained for this document — for the registry and the UI.

    `has_original` is the field the UI branches on: it decides whether a preview can
    show the document itself or only its text, and whether conversion is offered at
    all. Reported from the filesystem rather than from a registry flag, because the
    registry cannot know that someone cleared the directory.
    """
    source = original_path(doc_id, org_id)
    return {
        "has_original": source is not None,
        "original_bytes": source.stat().st_size if source else 0,
        "original_suffix": source.suffix if source else "",
        "has_markdown": (doc_dir(doc_id, org_id) / MARKDOWN_NAME).is_file(),
    }
