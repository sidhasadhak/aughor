"""
Document parsing and chunking for external context ingestion.

Supports: PDF (.pdf), Word (.docx), Markdown (.md), plain text (.txt).
Install optional deps with:  uv pip install -e ".[docs]"
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path

CHUNK_CHARS = 1_600    # ~400 tokens
OVERLAP_CHARS = 200    # ~50 tokens
MIN_CHUNK_CHARS = 50   # below this a chunk was silently discarded; see ChunkSettings


class ChunkSettingsError(ValueError):
    """Settings that would produce no chunks, or hang trying."""


@dataclass(frozen=True)
class ChunkSettings:
    """How a document is cut up, as DATA rather than as three module constants.

    Every default here reproduces the previous behaviour exactly, and a test holds that:
    the constants did not move, they became defaults. That matters because the corpus was
    indexed under them and a changed default would silently make old documents and new ones
    incomparable without either being re-indexed.

    `min_chars` is the one worth noticing. A chunk shorter than it was DISCARDED, with no
    record anywhere — a document of short paragraphs lost content and still reported a
    chunk count for what survived. It was never a knob; it was a magic number inside a list
    comprehension. Now it is visible and can be lowered.

    `strip_urls_emails` defaults OFF, unlike the tool that inspired it. Deleting URLs from a
    document is destructive to meaning as often as it is helpful — a policy that cites a
    source loses the citation — so it is offered, not assumed.
    """

    delimiter: str = "\n\n"
    max_chars: int = CHUNK_CHARS
    overlap_chars: int = OVERLAP_CHARS
    min_chars: int = MIN_CHUNK_CHARS
    collapse_whitespace: bool = True
    strip_urls_emails: bool = False

    def __post_init__(self) -> None:
        if self.max_chars < 1:
            raise ChunkSettingsError("max_chars must be at least 1")
        if not self.delimiter:
            raise ChunkSettingsError("delimiter cannot be empty — there would be nothing "
                                     "to split on")
        if self.overlap_chars < 0:
            raise ChunkSettingsError("overlap_chars cannot be negative")
        if self.overlap_chars >= self.max_chars:
            # Not merely wrong — the hard-split path steps by (max - overlap), so an
            # overlap at or above the size is a zero or negative step: ValueError from
            # range(), or a silently empty result. Refused where it can be explained.
            raise ChunkSettingsError(
                f"overlap_chars ({self.overlap_chars}) must be smaller than max_chars "
                f"({self.max_chars}) — a chunk cannot overlap itself entirely")
        if self.min_chars < 0:
            raise ChunkSettingsError("min_chars cannot be negative")

    def as_dict(self) -> dict:
        """For the registry, so a re-index can reproduce what a document was cut with."""
        return {"delimiter": self.delimiter, "max_chars": self.max_chars,
                "overlap_chars": self.overlap_chars, "min_chars": self.min_chars,
                "collapse_whitespace": self.collapse_whitespace,
                "strip_urls_emails": self.strip_urls_emails}

    @classmethod
    def from_dict(cls, raw: dict | None) -> "ChunkSettings":
        """Tolerant of absence and of extra keys; strict about values.

        Absence is the normal case — every document indexed before this existed has no
        settings recorded, and the defaults ARE what cut them.
        """
        if not raw:
            return cls()
        allowed = {f for f in cls().as_dict()}
        return cls(**{k: v for k, v in raw.items() if k in allowed})


DEFAULT_CHUNK_SETTINGS = ChunkSettings()

_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")


@dataclass
class DocumentChunk:
    doc_id: str
    chunk_index: int
    text: str
    filename: str
    title: str
    uploaded_at: str
    # Provenance (R8a) — where this knowledge CAME FROM. `fqn` is the ontology
    # doc-tree node (schema.table) for compiled schema docs; `kind` distinguishes
    # uploaded documents ("") from generated ones ("schema_doc"); `source_url`
    # is the connector origin (Confluence/Notion page) — previously accepted by
    # index_text but silently dropped before reaching the payload.
    fqn: str = ""
    kind: str = ""
    source_url: str = ""

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
            "fqn": self.fqn,
            "kind": self.kind,
            "source_url": self.source_url,
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
        import pypdf
        reader = pypdf.PdfReader(str(path))
        pages = []
        for page in reader.pages:
            text = page.extract_text() or ""
            pages.append(text)
        return "\n\n".join(pages)
    except ImportError:
        raise RuntimeError(
            "pypdf is required for PDF ingestion. "
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

def _split_into_chunks(text: str, settings: ChunkSettings | None = None) -> list[str]:
    """
    Delimiter-aware chunker. Breaks at the delimiter where it can, then falls back to hard
    splits at `max_chars` with `overlap_chars` overlap.

    `settings=None` means the defaults, which are the three constants this used to read
    directly — so every existing caller gets byte-identical output.
    """
    s = settings or DEFAULT_CHUNK_SETTINGS

    # Normalise whitespace
    text = re.sub(r"\r\n", "\n", text)
    if s.collapse_whitespace:
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
    else:
        text = text.strip()
    if s.strip_urls_emails:
        text = _EMAIL_RE.sub("", _URL_RE.sub("", text))

    paragraphs = [p.strip() for p in text.split(s.delimiter) if p.strip()]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para)
        if current_len + para_len + 2 > s.max_chars and current:
            chunks.append(s.delimiter.join(current))
            # Overlap: keep last paragraph(s) that fit within overlap_chars
            overlap: list[str] = []
            overlap_len = 0
            for p in reversed(current):
                if overlap_len + len(p) + 2 <= s.overlap_chars:
                    overlap.insert(0, p)
                    overlap_len += len(p) + 2
                else:
                    break
            current = overlap
            current_len = overlap_len

        # If a single paragraph exceeds chunk size, hard-split it
        if para_len > s.max_chars:
            for i in range(0, para_len, s.max_chars - s.overlap_chars):
                seg = para[i: i + s.max_chars].strip()
                if seg:
                    chunks.append(seg)
        else:
            current.append(para)
            current_len += para_len + 2

    if current:
        chunks.append(s.delimiter.join(current))

    return [c for c in chunks if len(c.strip()) >= s.min_chars]


def chunk_text(
    text: str,
    doc_id: str | None = None,
    title: str = "Document",
    filename: str = "api_sync",
    uploaded_at: str | None = None,
    source_url: str = "",
    settings: ChunkSettings | None = None,
) -> list[DocumentChunk]:
    """Chunk raw text string directly — no file I/O. Used by API knowledge connectors."""
    import datetime
    doc_id = doc_id or uuid.uuid4().hex
    uploaded_at = uploaded_at or datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    texts = _split_into_chunks(text, settings)
    return [
        DocumentChunk(
            doc_id=doc_id,
            chunk_index=i,
            text=t,
            filename=filename,
            title=title,
            uploaded_at=uploaded_at,
            source_url=source_url,
        )
        for i, t in enumerate(texts)
    ]


def chunk_file(
    path: Path,
    doc_id: str | None = None,
    title: str | None = None,
    uploaded_at: str | None = None,
    settings: ChunkSettings | None = None,
) -> list[DocumentChunk]:
    import datetime
    doc_id = doc_id or uuid.uuid4().hex
    title = title or path.stem.replace("_", " ").replace("-", " ").title()
    uploaded_at = uploaded_at or datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

    raw = extract_text(path)
    texts = _split_into_chunks(raw, settings)

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
