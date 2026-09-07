"""Any document → Markdown, via anydoc (Firecrawl's Rust converter).

Markdown is the PIVOT of the documents plane. Everything that comes in becomes
Markdown once, is stored as Markdown, and every other format we hand back out is
rendered *from* that Markdown. One canonical form in the middle means N inbound
formats and M outbound ones cost N + M seams instead of N × M.

Why a library and not the parsers we had
----------------------------------------
The path this replaces was `pypdf` for PDFs, `python-docx` paragraphs for Word, and
`read_text(errors="replace")` for everything else. Measured on a Word file holding a
four-row revenue table, that path returned 117 characters and **every number was
gone** — `python-docx`'s `.paragraphs` does not traverse tables, so the table was
dropped in silence and the document still reported a healthy chunk count. The same
table in a PDF came back as a column of orphaned cells with no row or column
association left.

The `errors="replace"` fallback was worse than lossy. Handed a `.pptx` it read the
raw ZIP container and produced 26,928 characters of mojibake, which would then be
chunked and embedded as though it were prose. Nothing downstream could tell that
from a real document. The only thing standing between that and the index was a
hand-written extension allowlist in the router — and `index_text()`'s callers (the
API knowledge connectors) never pass through the router at all.

So the rule here is **fail closed**: a byte string this module cannot positively
identify raises. It never guesses, and it never falls back to reading binary as text.

What is actually supported
--------------------------
The population is DISCOVERED from anydoc, not restated here. `typing.get_args` on
its `Format` literal gives the canonical formats; probing `format_from_extension`
gives the extensions that map onto them (17 extensions → 12 formats: `.docm` is a
`docx`, `.xls`/`.xlsm`/`.xlsb` are all `xlsx`, and so on). A hand-copied list would
drift the first time anydoc added a format and would keep passing its own test while
doing it.

Markdown and plain text are deliberately NOT in that set — anydoc does not claim
them, because they are already text. They take the native path below and are
returned unchanged. That is not a gap being papered over; converting Markdown to
Markdown would only risk mangling it.

Scanned PDFs and the network
----------------------------
anydoc does no OCR. A scanned PDF raises `NeedsOcrError`, which we surface by name
and with the page numbers rather than returning an empty document that looks like a
successful import of nothing. anydoc *can* delegate OCR to Firecrawl's hosted
service, but that is a network call carrying the user's document off the box, so it
is **off unless `AUGHOR_DOC_OCR=hosted` is set** and stays off by default. Consent
for that is external, the way every other outbound seam here works.
"""
from __future__ import annotations

import logging
import os
import typing
from pathlib import Path

logger = logging.getLogger(__name__)

#: Suffixes we serve WITHOUT conversion because they are already text. anydoc does
#: not list these — asking it to convert Markdown to Markdown is not a no-op, it is a
#: reparse — so they are ours to handle and are named here on purpose.
TEXT_SUFFIXES: frozenset[str] = frozenset({".md", ".markdown", ".txt"})

#: Bytes above this are refused before anydoc sees them. anydoc has its own internal
#: safety limits (decompression ratio, nesting depth, node count — it raises
#: `ResourceLimitError`), so this is not the bomb defence; it is the "a person picked
#: the wrong file" defence, and it keeps a 2 GB video out of an in-memory convert.
MAX_DOCUMENT_BYTES = 64 * 1024 * 1024


class ConversionError(Exception):
    """A document could not be converted, with a reason fit to show a person.

    `code` is the stable machine-readable half — the API surfaces it so a client can
    branch (offer OCR for `needs_ocr`, offer a password prompt for `encrypted`)
    without pattern-matching on English.
    """

    def __init__(self, message: str, *, code: str = "unconvertible") -> None:
        super().__init__(message)
        self.code = code


def available() -> bool:
    """Is the converter installed? Mirrors `vector_store.available()`.

    Callers use this to degrade with an honest message instead of an ImportError
    traceback; it is never used to justify falling back to reading binary as text.
    """
    try:
        import anydoc  # noqa: F401
        return True
    except ImportError:
        return False


def _anydoc():
    try:
        import anydoc
        return anydoc
    except ImportError:
        raise ConversionError(
            "Document conversion needs the 'docs' extra. Install with: "
            "uv pip install -e '.[docs]'",
            code="converter_missing",
        )


@typing.no_type_check
def document_suffixes() -> frozenset[str]:
    """Extensions anydoc converts, discovered by asking it — never hand-listed.

    Derived by probing `format_from_extension` over the canonical formats plus the
    container variants that map onto them. Returns empty when anydoc is absent, so a
    caller that unions this with `TEXT_SUFFIXES` still accepts `.md`/`.txt` on a lean
    install rather than accepting nothing.
    """
    if not available():
        return frozenset()
    anydoc = _anydoc()
    # The canonical formats anydoc declares, straight off its own type.
    canonical = set(typing.get_args(anydoc.Format))
    # Container variants that resolve onto a canonical format (.docm → docx, .xlsb →
    # xlsx). Probed, not assumed: any that stops resolving simply drops out.
    variants = {"docm", "pptm", "xls", "xlsm", "xlsb"}
    found: set[str] = set()
    for stem in canonical | variants:
        suffix = f".{stem}"
        try:
            if anydoc.format_from_extension(suffix) is not None:
                found.add(suffix)
        except Exception:
            continue
    return frozenset(found)


def supported_suffixes() -> frozenset[str]:
    """Everything the documents plane accepts: converted formats plus native text."""
    return frozenset(TEXT_SUFFIXES | document_suffixes())


def _ocr_mode() -> tuple[str, str | None]:
    """OCR mode and API key. Hosted OCR sends the document to a third party, so it
    is opt-in via `AUGHOR_DOC_OCR=hosted` and silent by absence."""
    mode = (os.environ.get("AUGHOR_DOC_OCR") or "reject").strip().lower()
    if mode != "hosted":
        return "reject", None
    return "hosted", os.environ.get("FIRECRAWL_API_KEY") or None


def sniff(data: bytes, filename: str = "") -> str | None:
    """The format these BYTES are, ignoring what the filename claims.

    Extensions lie — sometimes innocently (a `.doc` that is really a `.docx`), and
    sometimes not. Content is the authority here; the extension is only consulted for
    the text formats anydoc has no signature for.

    Returns a canonical anydoc format name, `"text"` for the native text path, or
    None when neither can place it.
    """
    if data:
        try:
            detected = _anydoc().format_from_bytes(data)
            if detected:
                return str(detected)
        except ConversionError:
            raise
        except Exception:
            pass  # Unrecognised signature — fall through to the extension.
    suffix = Path(filename or "").suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return "text"
    return None


def to_markdown(data: bytes, filename: str = "") -> str:
    """Convert a document's bytes to GitHub-Flavoured Markdown.

    Dispatches on what the bytes ARE (see `sniff`), not on what they are called, which
    is what stops a mislabelled binary from being read as text. Text formats are
    returned decoded and otherwise untouched.

    Raises ConversionError — never returns a best-effort string — so that "we could
    not read this" can never reach the index disguised as content.
    """
    if not data:
        raise ConversionError("The file is empty.", code="empty")
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ConversionError(
            f"File is {len(data) // (1024 * 1024)} MB; the limit is "
            f"{MAX_DOCUMENT_BYTES // (1024 * 1024)} MB.",
            code="too_large",
        )

    detected = sniff(data, filename)
    if detected == "text":
        return data.decode("utf-8", errors="replace")
    if detected is None:
        suffix = Path(filename or "").suffix.lower() or "(no extension)"
        raise ConversionError(
            f"Cannot read '{suffix}' — the file's content does not match any "
            f"supported document format. Supported: "
            f"{', '.join(sorted(supported_suffixes()))}.",
            code="unsupported",
        )

    anydoc = _anydoc()
    mode, api_key = _ocr_mode()
    try:
        return anydoc.to_markdown_bytes(data, detected, ocr=mode, api_key=api_key)
    except anydoc.NeedsOcrError as exc:
        pages = getattr(exc, "pages", None) or []
        count = getattr(exc, "page_count", None)
        where = (f"page{'s' if len(pages) != 1 else ''} "
                 f"{', '.join(str(p) for p in pages[:10])}"
                 f"{'…' if len(pages) > 10 else ''}") if pages else "some pages"
        scope = f" of {count}" if count else ""
        raise ConversionError(
            f"This PDF is scanned — {where}{scope} are images with no text layer. "
            f"OCR is needed to read it.",
            code="needs_ocr",
        ) from exc
    except anydoc.EncryptedError as exc:
        raise ConversionError(
            "This document is password-protected and cannot be opened.",
            code="encrypted",
        ) from exc
    except anydoc.ResourceLimitError as exc:
        limit = getattr(exc, "limit", None)
        raise ConversionError(
            f"The document crossed a safety limit ({limit or 'resource limit'}) — "
            f"it may be corrupt or deliberately malformed.",
            code="resource_limit",
        ) from exc
    except anydoc.UnsupportedError as exc:
        raise ConversionError(f"Unsupported document: {exc}", code="unsupported") from exc
    except anydoc.ConvertError as exc:
        # The typed base: malformed, missing part, hosted-OCR failure. One clause,
        # because to a person they are all "this file did not open".
        raise ConversionError(f"Could not read the document: {exc}",
                              code="unconvertible") from exc


def to_markdown_file(path: Path) -> str:
    """`to_markdown` for a file on disk, keeping the name for the extension hint."""
    return to_markdown(path.read_bytes(), path.name)
