"""
Document parsing and chunking for external context ingestion.

Reading is delegated to `knowledge.convert` (anydoc): Word, PowerPoint, Excel,
OpenDocument, RTF, EPUB, CSV and PDF all arrive here as Markdown, with tables intact.
Markdown and plain text pass through untouched. This module owns the CHUNKING — how
that text is cut for embedding — which is the part that has to stay stable, because
the corpus was indexed under these settings.

Install the readers with:  uv pip install -e ".[docs]"
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from aughor.knowledge.convert import TEXT_SUFFIXES  # noqa: F401  (one definition, re-exported)

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

    `suppress_numeric_runs` defaults ON, and it is the one default here that was
    deliberately chosen rather than inherited. The rule above — a changed default makes
    old and new documents incomparable — is what makes that worth explaining.

    It is a different KIND of setting from the one beside it. `strip_urls_emails`
    deletes from the document; this deletes only from the INDEX. Every number stays in
    the stored Markdown, in the preview and in every converted file, so nothing is lost
    and a re-index can always put it back by turning this off.

    What it prevents is specific and was measured on a live investor deck: a bar
    chart's labels are positioned graphics, so its values extract as
    `245.9 268.9 279.6 224.5 290.7 243.4 118.6 125.3 130.7` with the quarters on
    another line. Indexed, that is a retrievable passage in which every figure is
    correct and none is attached to what it measures — so an agent asked for one
    segment's GMV can answer confidently from the wrong position. A correct number
    against the wrong label is worse than a missing one, because it arrives looking
    exactly like a good answer.
    """

    delimiter: str = "\n\n"
    max_chars: int = CHUNK_CHARS
    overlap_chars: int = OVERLAP_CHARS
    min_chars: int = MIN_CHUNK_CHARS
    collapse_whitespace: bool = True
    strip_urls_emails: bool = False
    suppress_numeric_runs: bool = True

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
                "strip_urls_emails": self.strip_urls_emails,
                "suppress_numeric_runs": self.suppress_numeric_runs}

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

#: A numeric token: 1,234.5 · 47.1% · (12.9%) · +140bps · €279.6 · 2026. Signs,
#: currency, thousands separators, parentheses-as-negative and a trailing unit all
#: belong to the number rather than to the words around it. A trailing COLON matches
#: here too, but `is_numeric_run` reads it as a label — `2026:` names a period, it
#: does not report one.
_NUMERIC_TOKEN = re.compile(
    r"^[(\[]?[+\-−]?[€$£¥]?\d[\d,.\s]*\)?%?(?:bps|bp|k|m|bn|mm|x)?[)\]]?[.,;:]?$",
    re.IGNORECASE)
#: A word: two or more letters in a row. "Q1", "FY26" and "H1" deliberately do not
#: qualify — an axis of quarter labels is exactly as unattributed as the bars above it.
_WORD_TOKEN = re.compile(r"[^\W\d_]{2,}", re.UNICODE)

#: How many numbers it takes before a line is treated as a data run rather than as a
#: sentence that happens to cite figures. Four is deliberately conservative: a pair of
#: numbers under a heading ("774 847") is usually still readable from its context,
#: while a run of four or more is a chart axis.
_NUMERIC_RUN_MIN = 4

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
    """A document file's text, as Markdown, for chunking and embedding.

    Routes through `knowledge.convert` (anydoc) so that tables arrive as tables and
    fourteen formats are readable instead of two. The function keeps its name and
    signature because a dozen callers use it; what changed is what it can read and,
    just as importantly, what it now REFUSES to read.

    It used to end with `return path.read_text(errors="replace")` for anything it did
    not recognise. Handed a `.pptx` that produced 26,928 characters of decoded ZIP
    container, which went on to be chunked and embedded as prose — indistinguishable
    downstream from a real document. Unreadable input now raises.

    The legacy pypdf/python-docx path survives only for installs without the
    converter, and only for the two formats it ever handled correctly.
    """
    from aughor.knowledge.convert import ConversionError, available, to_markdown_file

    if available():
        return to_markdown_file(path)

    # No converter installed — the pre-anydoc readers, unchanged, for their formats.
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(path)
    if suffix == ".docx":
        return _extract_docx(path)
    if suffix in TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8", errors="replace")
    raise ConversionError(
        f"Cannot read '{suffix or path.name}' without the document converter. "
        f"Install it with: uv pip install -e '.[docs]'",
        code="converter_missing",
    )


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

def is_numeric_run(line: str) -> bool:
    """Is this line a run of numbers with nothing to attribute them to?

    The shape a bar chart leaves behind. A chart's data labels are positioned
    graphics, not structure, so a slide of three series across three quarters
    extracts as `245.9 268.9 279.6 224.5 290.7 243.4 118.6 125.3 130.7` with the axis
    `Q1 Q2 Q3 Q1 Q2 Q3 Q1 Q2 Q3` on a separate line. Every value is correct and not
    one of them is attached to what it measures.

    Three guards keep prose and tables out of it:

      * A TABLE ROW is attributed — its header names the column — so a line of pipes
        is never a run, however many numbers it holds.
      * A COLON NAMES the figure after it, so a colon-terminated token is a label and
        not one of the headless numbers. Measured on a retail market deck:
        `Take-up H1 2026: 24,000 sqm | H1 2025: 32,000 sqm | Ø 5 years 24,000 sqm`
        scored `2026:` and `2025:` among six numbers against five words and was
        suppressed — one per city, and the only line on the page where every figure
        was attached to the period it measures. A colon is the one attribution that
        survives a PowerPoint export intact, because it is typed into the text box
        while position is not.
      * Numbers must DOMINATE. "GMV increased by +11.3% ex-FX (+7.0% reported) and
        Net Sales by +9.9%" has four numbers and fifteen words; it is a sentence, and
        a sentence carries its own attribution.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith("|"):
        return False
    figures, words = _weigh([stripped])
    return figures >= _NUMERIC_RUN_MIN and figures > words


def _weigh(lines: list[str]) -> tuple[int, int]:
    """Figures and words across a group of lines — the scale both rules read.

    A label is not a measurement, so a colon-terminated token weighs nothing: the
    colon rescues just the name it terminates, and every figure downstream of it still
    counts, so a name in front of a stream ("Prime rent: 340 320 300 280 260") names
    the stream and is still an axis.

    Words are counted among the NON-numeric tokens only. A unit welded to its value
    belongs to the number, not to the prose: counting the "bps" in "+140bps" as a word
    let a line of nine bare deltas score nine words and call itself a sentence, which
    is precisely the line this exists to catch.
    """
    figures = words = 0
    for line in lines:
        tokens = line.split()
        numeric = [t for t in tokens if _NUMERIC_TOKEN.match(t)]
        figures += sum(1 for t in numeric if not t.endswith(":"))
        words += sum(1 for t in tokens if t not in numeric and _WORD_TOKEN.search(t))
    return figures, words


def _has_word(line: str) -> bool:
    """Does this line carry a name of any kind? `52.225.499 Friedrichstr.` does."""
    return any(_WORD_TOKEN.search(t) for t in line.split())


def _run_lines(text: str) -> set[int]:
    """Line numbers carrying figures with nothing to attribute them to.

    A chart leaves TWO shapes and the per-line rule only ever saw one of them.

    The first is the long headless row `is_numeric_run` describes. The second is the
    same chart spread thin: a PowerPoint export interleaves two side-by-side charts
    into a column of two- and three-figure fragments — `40.000 80 79`, then
    `73 70 65 66 65`, then `37` — and most of those are under the floor a single line
    has to clear. Measured on an 83-page retail deck, the per-line rule held back 83
    lines and left 73 more of exactly this kind in the index, where a plausible-looking
    fragment of two charts is worse company than the long row ever was.

    So the NEIGHBOURHOOD is evidence. A figure with nothing to attribute it to on its
    own line might still be named by the line above it — unless that line is nameless
    too. Judge the paragraph: where its figures outnumber its words and there are at
    least four of them, the nameless lines in it are what a chart left behind.

    Three things are never taken this way, because each is already a claim of
    attribution:

      * a TABLE — its header names the column, so a block holding one is left alone
        entirely rather than picked over;
      * a HEADING — `##### 2021 - H1 2026` is the period a chart covers, and dropping
        it would take a chunk's only remaining context with it;
      * any line carrying a WORD — `52.225.499 Friedrichstr.` has its name on it, and
        the block around it cannot take that away.
    """
    lines = text.splitlines()
    # Numbers inside a code fence are program output or data someone pasted
    # deliberately; the fence IS their attribution, so they are never candidates.
    open_air = [True] * len(lines)
    inside = False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            inside = not inside
            open_air[i] = False
        elif inside:
            open_air[i] = False

    drop = {i for i, line in enumerate(lines) if open_air[i] and is_numeric_run(line)}

    # A block is a run of consecutive lines with no blank between them — the same
    # split the chunker makes, so what is judged together is what travels together.
    block: list[int] = []
    for i, line in enumerate(lines):
        if open_air[i] and line.strip():
            block.append(i)
            continue
        drop |= _nameless_in_run_block(lines, block)
        block = []
    drop |= _nameless_in_run_block(lines, block)
    return drop


def _nameless_in_run_block(lines: list[str], block: list[int]) -> set[int]:
    """The lines a figure-dominated paragraph gives up. See `_run_lines`.

    An empty block weighs nothing and gives up nothing, so the caller can flush
    unconditionally rather than guard every call site.
    """
    group = [lines[i] for i in block]
    if any(line.lstrip().startswith("|") for line in group):
        return set()
    figures, words = _weigh(group)
    if figures < _NUMERIC_RUN_MIN or figures <= words:
        return set()
    return {i for i in block
            if not _has_word(lines[i]) and not lines[i].lstrip().startswith("#")}


def numeric_run_lines(text: str) -> list[str]:
    """The lines that would be suppressed — for REPORTING, never mutation.

    The door uses this to tell a person what was held back from search, because
    quietly indexing less than the document contains is the same class of failure as
    quietly indexing more.
    """
    lines = text.splitlines()
    return [lines[i] for i in sorted(_run_lines(text))]


def _strip_numeric_runs(text: str) -> str:
    """Drop unattributed numeric runs from text destined for the INDEX.

    Only the index. The lines stay in the stored Markdown, in the preview and in
    every converted file, so nothing is deleted from the document — what changes is
    that semantic search will not offer a headless row of figures as the source of an
    answer. A correct number retrieved against the wrong label is worse than no
    number at all, and it arrives looking exactly like a good answer.
    """
    drop = _run_lines(text)
    return "\n".join(line for i, line in enumerate(text.splitlines()) if i not in drop)


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
    if s.suppress_numeric_runs:
        text = _strip_numeric_runs(text)

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
