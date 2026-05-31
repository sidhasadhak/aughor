"""
Document parsing and chunking for external context ingestion.

Supports: PDF (.pdf), Word (.docx), Markdown (.md), plain text (.txt).
Install optional deps with:  uv pip install -e ".[docs]"
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

CHUNK_CHARS = 1_600    # ~400 tokens
OVERLAP_CHARS = 200    # ~50 tokens


@dataclass
class DocumentChunk:
    doc_id: str
    chunk_index: int
    text: str
    filename: str
    title: str
    uploaded_at: str

    def embed_text(self) -> str:
        return f"{self.title}\n\n{self.text}"

    def payload(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "chunk_index": self.chunk_index,
            "text": self.text,
            "filename": self.filename,
            "title": self.title,
            "uploaded_at": self.uploaded_at,
        }

    def point_id(self) -> str:
        return f"doc::{self.doc_id}::{self.chunk_index}"


# ── Text extraction ───────────────────────────────────────────────────────────

def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(path)
    if suffix == ".docx":
        return _extract_docx(path)
    if suffix in (".md", ".txt", ".markdown"):
        return path.read_text(encoding="utf-8", errors="replace")
    # Fallback: try UTF-8 text
    return path.read_text(encoding="utf-8", errors="replace")


def _extract_pdf(path: Path) -> str:
    try:
        import PyPDF2
        reader = PyPDF2.PdfReader(str(path))
        pages = []
        for page in reader.pages:
            text = page.extract_text() or ""
            pages.append(text)
        return "\n\n".join(pages)
    except ImportError:
        raise RuntimeError(
            "PyPDF2 is required for PDF ingestion. "
            "Install with: uv pip install -e '.[docs]'"
        )


def _extract_docx(path: Path) -> str:
    try:
        import docx
        doc = docx.Document(str(path))
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except ImportError:
        raise RuntimeError(
            "python-docx is required for Word ingestion. "
            "Install with: uv pip install -e '.[docs]'"
        )


# ── Chunking ──────────────────────────────────────────────────────────────────

def _split_into_chunks(text: str) -> list[str]:
    """
    Paragraph-aware chunker. Tries to break at paragraph boundaries
    then falls back to hard splits at CHUNK_CHARS with OVERLAP_CHARS overlap.
    """
    # Normalise whitespace
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para)
        if current_len + para_len + 2 > CHUNK_CHARS and current:
            chunks.append("\n\n".join(current))
            # Overlap: keep last paragraph(s) that fit within OVERLAP_CHARS
            overlap: list[str] = []
            overlap_len = 0
            for p in reversed(current):
                if overlap_len + len(p) + 2 <= OVERLAP_CHARS:
                    overlap.insert(0, p)
                    overlap_len += len(p) + 2
                else:
                    break
            current = overlap
            current_len = overlap_len

        # If a single paragraph exceeds chunk size, hard-split it
        if para_len > CHUNK_CHARS:
            for i in range(0, para_len, CHUNK_CHARS - OVERLAP_CHARS):
                seg = para[i: i + CHUNK_CHARS].strip()
                if seg:
                    chunks.append(seg)
        else:
            current.append(para)
            current_len += para_len + 2

    if current:
        chunks.append("\n\n".join(current))

    return [c for c in chunks if len(c.strip()) >= 50]


def chunk_text(
    text: str,
    doc_id: str | None = None,
    title: str = "Document",
    filename: str = "api_sync",
    uploaded_at: str | None = None,
) -> list[DocumentChunk]:
    """Chunk raw text string directly — no file I/O. Used by API knowledge connectors."""
    import datetime
    doc_id = doc_id or uuid.uuid4().hex
    uploaded_at = uploaded_at or datetime.datetime.utcnow().isoformat() + "Z"
    texts = _split_into_chunks(text)
    return [
        DocumentChunk(
            doc_id=doc_id,
            chunk_index=i,
            text=t,
            filename=filename,
            title=title,
            uploaded_at=uploaded_at,
        )
        for i, t in enumerate(texts)
    ]


def chunk_file(
    path: Path,
    doc_id: str | None = None,
    title: str | None = None,
    uploaded_at: str | None = None,
) -> list[DocumentChunk]:
    import datetime
    doc_id = doc_id or uuid.uuid4().hex
    title = title or path.stem.replace("_", " ").replace("-", " ").title()
    uploaded_at = uploaded_at or datetime.datetime.utcnow().isoformat() + "Z"

    raw = extract_text(path)
    texts = _split_into_chunks(raw)

    return [
        DocumentChunk(
            doc_id=doc_id,
            chunk_index=i,
            text=t,
            filename=path.name,
            title=title,
            uploaded_at=uploaded_at,
        )
        for i, t in enumerate(texts)
    ]
