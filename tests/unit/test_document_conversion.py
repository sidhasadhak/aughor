"""Any document in, Markdown out — and the original kept.

Three defects motivated this plane, all measured on real files rather than argued:

  * A Word document holding a four-row table came back as 117 characters with **every
    number gone**. `python-docx`'s `.paragraphs` does not walk tables, so the table was
    dropped in silence and the document still reported a healthy chunk count.
  * The same table in a PDF arrived as a column of orphaned cells: the values survived,
    the rows and columns did not.
  * A `.pptx` handed to the old `read_text(errors="replace")` fallback produced **26,928
    characters of decoded ZIP container**, which would then be chunked and embedded as
    if it were prose. Nothing downstream could tell that from a document.

The third is the one these tests guard hardest, because it is the failure that looks
like success. The rule is fail closed: input this plane cannot positively identify
raises, and never reaches the index as text.

Fixtures are BUILT here rather than committed, so the assertion is about what a real
`.docx` does today, not about a blob someone generated once and stopped checking.

Hermetic — `tests/conftest.py` points both the registry and the retained-bytes
directory at tempdirs.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

converter = pytest.importorskip("anydoc", reason="the 'docs' extra is not installed")
docx = pytest.importorskip("docx", reason="the 'docs' extra is not installed")

from aughor.knowledge import blobs, convert  # noqa: E402

TABLE_ROWS = [("Region", "Revenue", "Growth"), ("EMEA", "4,200,000", "12%"),
              ("AMER", "7,850,000", "8%"), ("APAC", "3,100,000", "23%")]


@pytest.fixture(autouse=True)
def _offline_embedder(monkeypatch):
    """Index without reaching a live embedder.

    These tests upload, and uploading embeds. A developer machine usually has a local
    embedder answering, and CI has none — so this file passed here and failed on the
    first machine without one, with a 500 and `Connection refused`. That is the
    "run the suite without what only your machine has" trap in its purest form: the
    thing under test never needed a real embedder, the test just silently used one.

    768 is the width the rest of the suite caches. `embedding_dim()` memoizes into a
    module-level cache that outlives monkeypatch, so a narrower fake would be compared
    against an earlier test's 768 and every write refused.
    """
    monkeypatch.setattr("aughor.semantic.embedder.embed",
                        lambda texts: [[0.0] * 768 for _ in texts])
    monkeypatch.setattr("aughor.semantic.embedder.embedding_dim", lambda: 768)


@pytest.fixture
def revenue_docx(tmp_path: Path) -> Path:
    """A Word file whose entire point is the table — the shape that used to vanish."""
    d = docx.Document()
    d.add_heading("Q3 Revenue Review", level=1)
    d.add_paragraph("Revenue grew across all regions.")
    table = d.add_table(rows=len(TABLE_ROWS), cols=3)
    for i, row in enumerate(TABLE_ROWS):
        for j, value in enumerate(row):
            table.cell(i, j).text = value
    path = tmp_path / "revenue.docx"
    d.save(path)
    return path


# ── The population is discovered, not restated ────────────────────────────────

def test_the_supported_set_is_asked_of_the_converter_not_hand_listed():
    """The allowlist was five literals; the converter reads far more than five.

    A hand-copied list rots in the direction that looks safe — it keeps refusing
    formats the library gained, and its own test keeps passing while it does. So the
    assertion here is deliberately NOT a list of extensions: it is that the set comes
    from anydoc's own declared formats, and is therefore bigger than what one module
    author remembered to type.
    """
    import typing

    supported = convert.supported_suffixes()
    declared = {f".{name}" for name in typing.get_args(converter.Format)}
    assert declared <= supported, f"converter declares formats we refuse: {declared - supported}"
    # Text formats anydoc does not claim, because they are already text.
    assert convert.TEXT_SUFFIXES <= supported
    # The old hand-written set, as a floor. If this ever regresses to five, the
    # derivation has been replaced by a literal again.
    assert len(supported) > 15


def test_the_router_allowlist_is_the_converters_set():
    """One source for upload and preview — a preview that accepted what upload
    rejects would show a person chunks they can never index."""
    from aughor.routers.knowledge import _allowed_suffixes

    assert _allowed_suffixes() == convert.supported_suffixes()


# ── The measured defects ──────────────────────────────────────────────────────

def test_a_word_table_survives_conversion(revenue_docx: Path):
    """The regression that started this: 117 characters, no numbers."""
    markdown = convert.to_markdown(revenue_docx.read_bytes(), revenue_docx.name)

    for _, revenue, growth in TABLE_ROWS[1:]:
        assert revenue in markdown, f"lost {revenue} — the table was dropped again"
        assert growth in markdown
    # Not merely present as loose text: present AS a table.
    assert "| Region" in markdown or "|Region" in markdown
    assert "Q3 Revenue Review" in markdown


def test_a_pptx_is_read_as_a_document_not_as_mojibake(tmp_path: Path):
    """The failure that looked like success.

    An Office file is a ZIP. Decoded as UTF-8 with `errors="replace"` it yields tens
    of thousands of plausible-looking characters — a chunk count, an index entry, and
    nothing a reader could recognise as broken.
    """
    pptx = pytest.importorskip("pptx", reason="the 'export' extra is not installed")
    presentation = pptx.Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = "Q3 Revenue Review"
    slide.placeholders[1].text = "APAC +23%"
    path = tmp_path / "deck.pptx"
    presentation.save(path)

    markdown = convert.to_markdown(path.read_bytes(), path.name)

    assert "Q3 Revenue Review" in markdown
    assert "APAC +23%" in markdown
    assert "PK\x03\x04" not in markdown, "the ZIP container leaked into the text"
    assert "�" not in markdown, "replacement characters — this was decoded, not parsed"
    assert len(markdown) < 1_000, f"{len(markdown)} chars from one slide is container, not content"


# ── Fail closed ───────────────────────────────────────────────────────────────

def test_bytes_that_are_not_a_document_raise_rather_than_decode(tmp_path: Path):
    """No path returns a best-effort string. 'We could not read this' must never
    reach the index disguised as content."""
    with pytest.raises(convert.ConversionError) as exc:
        convert.to_markdown(os.urandom(4096), "mystery.bin")
    assert exc.value.code == "unsupported"


def test_the_extension_does_not_decide_what_a_file_is(revenue_docx: Path):
    """Content is the authority; the extension is a hint that can lie.

    A `.docx` renamed to `.pdf` must still be read as the Word file it is — and,
    critically, must not be handed to a PDF parser that would fail obscurely or to a
    text decoder that would succeed meaninglessly.
    """
    data = revenue_docx.read_bytes()
    assert convert.sniff(data, "actually_a_word_file.pdf") == "docx"
    markdown = convert.to_markdown(data, "actually_a_word_file.pdf")
    assert "Q3 Revenue Review" in markdown


def test_an_empty_file_is_refused_by_name():
    with pytest.raises(convert.ConversionError) as exc:
        convert.to_markdown(b"", "empty.pdf")
    assert exc.value.code == "empty"


def test_an_oversized_file_is_refused_before_it_is_parsed():
    """The limit is checked on the byte count, not by attempting the parse."""
    with pytest.raises(convert.ConversionError) as exc:
        convert.to_markdown(b"x" * (convert.MAX_DOCUMENT_BYTES + 1), "big.pdf")
    assert exc.value.code == "too_large"


def test_hosted_ocr_is_off_unless_asked_for(monkeypatch):
    """OCR sends the document to a third party. Absence of the variable means no."""
    monkeypatch.delenv("AUGHOR_DOC_OCR", raising=False)
    assert convert._ocr_mode() == ("reject", None)
    monkeypatch.setenv("AUGHOR_DOC_OCR", "hosted")
    monkeypatch.setenv("FIRECRAWL_API_KEY", "k")
    assert convert._ocr_mode() == ("hosted", "k")


# ── Markdown and text pass through ────────────────────────────────────────────

def test_markdown_is_returned_unchanged_not_reparsed():
    """Converting Markdown to Markdown is not a no-op, it is a reparse — and a
    reparse can only lose. These formats take the native path."""
    source = "# Title\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n"
    assert convert.to_markdown(source.encode(), "notes.md") == source


# ── Retention: the keystone ───────────────────────────────────────────────────

def test_the_original_is_kept_and_readable_back(tmp_path: Path, revenue_docx: Path):
    data = revenue_docx.read_bytes()
    blobs.put_original("doc1", "revenue.docx", data)

    stored = blobs.original_path("doc1")
    assert stored is not None and stored.read_bytes() == data, "bytes must be verbatim"
    info = blobs.info("doc1")
    assert info["has_original"] is True
    assert info["original_bytes"] == len(data)
    assert info["original_suffix"] == ".docx"


def test_markdown_is_reconverted_from_the_original_when_the_cache_is_gone(revenue_docx):
    """The cache must be disposable — deleting the `.md` files is always safe."""
    blobs.put_original("doc2", "revenue.docx", revenue_docx.read_bytes())
    assert blobs.read_markdown("doc2") is None      # never cached

    text = blobs.markdown("doc2")                    # re-converted on demand
    assert text is not None and "Q3 Revenue Review" in text
    assert blobs.read_markdown("doc2") is not None   # and cached for next time


def test_a_document_with_no_original_reports_absence_not_an_error():
    """Every document uploaded before retention existed is in this state. It is a
    real condition to render, not a missing file to explain."""
    assert blobs.original_path("never-uploaded") is None
    assert blobs.markdown("never-uploaded") is None
    assert blobs.info("never-uploaded")["has_original"] is False


def test_deleting_a_document_removes_its_bytes(revenue_docx: Path):
    """A person who deletes a document has asked for the file to be gone."""
    blobs.put_original("doc3", "revenue.docx", revenue_docx.read_bytes())
    blobs.put_markdown("doc3", "# x")
    assert blobs.delete("doc3") is True
    assert blobs.original_path("doc3") is None
    assert blobs.info("doc3")["has_original"] is False
    assert blobs.delete("doc3") is False             # idempotent


def test_a_doc_id_cannot_escape_its_directory():
    """`doc_id` reaches this store from a URL path segment."""
    escaped = blobs.doc_dir("../../etc/passwd")
    root = Path(os.environ["AUGHOR_DOCUMENTS_DIR"]).resolve()
    assert root in escaped.resolve().parents, f"{escaped} escaped {root}"


def test_the_store_root_is_resolved_per_call_not_frozen_at_import(monkeypatch, tmp_path):
    """A module-level `Path(os.environ[...])` is bound by the first import, so a test
    that sets the variable afterwards is ignored and the write lands in the real
    `data/`. That has cost this codebase live data three times."""
    monkeypatch.setenv("AUGHOR_DOCUMENTS_DIR", str(tmp_path / "elsewhere"))
    assert (tmp_path / "elsewhere") in blobs.doc_dir("d").parents


# ── The routes, end to end ────────────────────────────────────────────────────

def _upload(client, name: str = "revenue.docx"):
    """Upload a Word file with a table and return the created entry."""
    import io

    d = docx.Document()
    d.add_heading("Q3 Revenue Review", level=1)
    table = d.add_table(rows=len(TABLE_ROWS), cols=3)
    for i, row in enumerate(TABLE_ROWS):
        for j, value in enumerate(row):
            table.cell(i, j).text = value
    buf = io.BytesIO()
    d.save(buf)
    return client.post("/documents/upload", files={"file": (name, buf.getvalue(), "")})


def test_upload_indexes_the_markdown_and_keeps_the_file(client):
    r = _upload(client)
    assert r.status_code == 201, r.text
    entry = r.json()

    assert entry["has_original"] is True, "the upload was destroyed after indexing again"
    assert entry["original_bytes"] > 0
    assert entry["chunk_count"] >= 1
    assert entry["filename"] == "revenue.docx"


def test_the_indexed_text_is_the_table_not_a_paragraph_scrape(client):
    doc_id = _upload(client).json()["doc_id"]

    r = client.get(f"/documents/{doc_id}/markdown")
    assert r.status_code == 200
    markdown = r.json()["markdown"]
    for _, revenue, _ in TABLE_ROWS[1:]:
        assert revenue in markdown


def test_the_original_is_served_back_for_preview(client):
    entry = _upload(client).json()

    r = client.get(f"/documents/{entry['doc_id']}/original")
    assert r.status_code == 200
    assert len(r.content) == entry["original_bytes"]
    assert "wordprocessingml" in r.headers["content-type"]
    # Inline, so a browser renders it rather than downloading it.
    assert r.headers["content-disposition"].startswith("inline")


def test_the_listing_says_which_documents_can_be_previewed(client):
    _upload(client)

    rows = client.get("/documents").json()
    assert rows, "the upload did not reach the registry"
    assert all("has_original" in row for row in rows), \
        "the UI cannot tell which rows offer a preview"


def test_deleting_through_the_api_takes_the_bytes_with_it(client):
    doc_id = _upload(client).json()["doc_id"]

    assert client.delete(f"/documents/{doc_id}").status_code == 200
    assert client.get(f"/documents/{doc_id}/markdown").status_code == 404
    assert client.get(f"/documents/{doc_id}/original").status_code == 404
    assert blobs.original_path(doc_id) is None


def test_an_unreadable_upload_fails_with_its_own_reason(client):
    """Not "no text could be extracted" for everything. A scanned PDF, a
    password-protected file and a wrong file type are three different problems and a
    person can only act on the one they actually have."""
    r = client.post("/documents/upload",
                    files={"file": ("notes.md", b"", "text/markdown")})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "empty"


def test_an_unsupported_type_is_refused_with_the_list_of_what_works(client):
    r = client.post("/documents/upload",
                    files={"file": ("movie.mp4", b"\x00\x00\x00\x20ftyp", "video/mp4")})
    assert r.status_code == 422
    assert ".docx" in str(r.json()["detail"])


def test_a_document_too_short_to_index_is_refused_not_silently_accepted(client):
    """A 201 that indexes nothing is the worst possible answer.

    `index_text` returns early WITHOUT registering when chunking yields nothing —
    which happens for any document shorter than `min_chars` (50 by default, and a
    chunk below it is discarded rather than kept). Reported as success, the caller
    gets a doc_id that appears in no listing, fetches 404 and deletes 404: they were
    told "Created" and have nothing.

    The message names `min_chars` because it is a setting the person controls in this
    very panel — "no text could be extracted" would send them looking at their file.
    """
    before = len(client.get("/documents").json())
    r = client.post("/documents/upload",
                    files={"file": ("tiny2.md", b"# Hi\n\nShort.\n", "text/markdown")})

    assert r.status_code == 422, "a zero-chunk upload reported success"
    detail = r.json()["detail"]
    assert detail["code"] == "no_chunks"
    assert "minimum chunk length" in detail["message"].lower()
    # Delta, not absolute: the registry is shared across this module's tests, and
    # asserting an empty corpus would pass alone and fail in the file.
    assert len(client.get("/documents").json()) == before, \
        "an unindexed document reached the registry"


def test_a_refused_upload_leaves_no_orphaned_bytes(client):
    """Retention happens after indexing succeeds. Storing bytes under a doc_id that
    was never registered would leave a file nothing in the product can reach."""
    root = Path(os.environ["AUGHOR_DOCUMENTS_DIR"])
    count = lambda: len(list(root.rglob("original*"))) if root.is_dir() else 0
    before = count()

    client.post("/documents/upload",
                files={"file": ("tiny3.md", b"# Hi\n\nShort.\n", "text/markdown")})

    assert count() == before, "a refused upload still wrote bytes to disk"


def test_preview_reads_the_formats_upload_accepts(client):
    """One list, both doors. A preview that accepted what upload rejects would show
    someone chunks they can never index; the reverse hides a working format."""
    import io

    d = docx.Document()
    d.add_heading("Q3 Revenue Review", level=1)
    d.add_paragraph("Revenue grew across every region this quarter, "
                    "with EMEA leading on margin and APAC on growth.")
    buf = io.BytesIO()
    d.save(buf)

    r = client.post("/documents/preview", files={"file": ("r.docx", buf.getvalue(), "")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_chunks"] >= 1
    assert "Q3 Revenue Review" in body["chunks"][0]["text"]


def test_preview_refuses_an_unreadable_file_with_the_same_reason_upload_gives(client):
    """Both doors answer alike, or a person debugs two different products."""
    r = client.post("/documents/preview",
                    files={"file": ("empty.md", b"", "text/markdown")})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "empty"


def test_a_lean_install_still_reads_its_own_allowlist(monkeypatch):
    """Without the `docs` extra the plane still offers `.md`/`.txt` — and must then
    actually accept them.

    `_anydoc()` RAISES when the extra is absent. Letting that escape from `sniff` made
    a lean install refuse its own allowlist: `supported_suffixes()` advertised `.md`
    and the upload answered "install the docs extra" for a file needing no converter.
    """
    monkeypatch.setattr(convert, "available", lambda: False)

    assert convert.supported_suffixes() == convert.TEXT_SUFFIXES
    assert convert.to_markdown(b"# Notes\n\nno converter needed", "notes.md") \
        == "# Notes\n\nno converter needed"
    with pytest.raises(convert.ConversionError) as exc:
        convert.to_markdown(b"%PDF-1.4 ...", "report.pdf")
    assert exc.value.code == "unsupported", "a lean install must refuse, not decode"


def test_content_beats_a_text_extension_too(revenue_docx: Path):
    """The ordering that keeps the mojibake bug dead.

    Checking the extension first would be the tidier-looking guard and would quietly
    re-open the hole: a binary renamed `.md` is exactly the file most likely to be
    mislabelled, and 'it ends in .md' would send it straight to the text decoder.
    """
    assert convert.sniff(revenue_docx.read_bytes(), "renamed.md") == "docx"
    assert "Q3 Revenue Review" in convert.to_markdown(
        revenue_docx.read_bytes(), "renamed.md")


def test_prose_is_not_mistaken_for_a_spreadsheet():
    """A `.txt` of prose with commas in it must stay prose, not become a CSV table."""
    assert convert.sniff(b"plain prose, with a comma", "notes.txt") == "text"
    assert convert.sniff(b"a,b,c\n1,2,3\n", "notes.txt") == "text"


# ── Part-scanned PDFs: read what CAN be read ──────────────────────────────────

@pytest.fixture
def scanned_deck(tmp_path: Path) -> bytes:
    """A deck shaped like a real investor presentation: a scanned cover, text pages
    with a table, a full-bleed image page, then more text.

    The shape that motivated this: a live 40-page deck was refused whole because
    pages 1, 33 and 40 are images — a designed cover and two chart pages — throwing
    away 37 pages of perfectly good text.
    """
    Image = pytest.importorskip("PIL.Image", reason="pillow is not installed")
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image as RLImage
    from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                    Table, TableStyle)

    png = tmp_path / "cover.png"
    Image.new("RGB", (600, 800), (31, 56, 100)).save(png)
    st = getSampleStyleSheet()
    table = Table(TABLE_ROWS)
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))

    def cover():
        return RLImage(str(png), width=120 * mm, height=160 * mm)

    out = tmp_path / "deck.pdf"
    SimpleDocTemplate(str(out), pagesize=A4).build([
        cover(), PageBreak(),                                        # 1 scanned
        Paragraph("Q3 Performance", st["Heading1"]),
        Paragraph("Revenue grew across all regions.", st["BodyText"]),
        Spacer(1, 12), table, PageBreak(),                           # 2 text + table
        Paragraph("Outlook", st["Heading1"]),
        Paragraph("APAC leads on growth.", st["BodyText"]), PageBreak(),   # 3 text
        cover(), PageBreak(),                                        # 4 scanned
        Paragraph("Appendix", st["Heading1"]),
        Paragraph("Definitions and methodology.", st["BodyText"]),   # 5 text
    ])
    return out.read_bytes()


def test_a_part_scanned_pdf_keeps_the_pages_that_can_be_read(scanned_deck: bytes):
    """All-or-nothing is the wrong trade when 'nothing' is the common case.

    Any deck with a designed cover has an image page one. Refusing the document over
    it discards every readable page — including, here, the table that is the entire
    point of the deck.
    """
    result = convert.convert_document(scanned_deck, "deck.pdf")

    assert result.page_count == 5
    assert result.pages_needing_ocr == [1, 4]
    assert result.pages_read == [2, 3, 5]
    assert result.partial is True
    # The table on a readable page survives — that is what was being thrown away.
    for _, revenue, _ in TABLE_ROWS[1:]:
        assert revenue in result.markdown


def test_an_unreadable_page_leaves_a_visible_marker_where_it_falls(scanned_deck: bytes):
    """Nothing may go missing silently. A reader — person or model — must see the gap
    at the point it occurs, not infer a document that flows across a hole."""
    markdown = convert.convert_document(scanned_deck, "deck.pdf").markdown

    assert "Page 1 could not be read" in markdown
    assert "Page 4 could not be read" in markdown
    assert markdown.index("Page 1 could not be read") < markdown.index("Q3 Performance")
    assert markdown.index("Page 4 could not be read") < markdown.index("Appendix")


def test_a_fully_scanned_pdf_is_still_refused(tmp_path: Path):
    """Recovery must not turn a document with NO text into a successful import of
    nothing — that is the failure that looks like success, one level up."""
    Image = pytest.importorskip("PIL.Image", reason="pillow is not installed")
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import Image as RLImage
    from reportlab.platypus import PageBreak, SimpleDocTemplate

    png = tmp_path / "page.png"
    Image.new("RGB", (600, 800), (20, 20, 20)).save(png)

    def page():
        return RLImage(str(png), width=120 * mm, height=160 * mm)

    out = tmp_path / "all-scanned.pdf"
    SimpleDocTemplate(str(out), pagesize=A4).build([page(), PageBreak(), page()])

    with pytest.raises(convert.ConversionError) as exc:
        convert.convert_document(out.read_bytes(), "all-scanned.pdf")
    assert exc.value.code == "needs_ocr"
    assert "all 2 pages" in str(exc.value)


def test_a_clean_pdf_reports_no_pages_and_takes_the_fast_path(revenue_docx: Path):
    """`page_count` is 0 for anything that did not need per-page recovery, so the UI
    shows a scanned-pages warning only when there is one."""
    result = convert.convert_document(revenue_docx.read_bytes(), "revenue.docx")
    assert result.page_count == 0
    assert result.partial is False
    assert result.pages_needing_ocr == []


def test_to_markdown_still_returns_a_plain_string(revenue_docx: Path):
    """A dozen callers want the string. Adding page detail must not change them."""
    text = convert.to_markdown(revenue_docx.read_bytes(), "revenue.docx")
    assert isinstance(text, str)
    assert "Q3 Revenue Review" in text


def test_uploading_a_part_scanned_pdf_succeeds_and_says_what_was_missed(client, scanned_deck):
    """It imports — and the response names the pages that did not, so the UI can too.
    'Indexed' alone would read as 'all of it'."""
    r = client.post("/documents/upload",
                    files={"file": ("deck.pdf", scanned_deck, "application/pdf")})

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["page_count"] == 5
    assert body["pages_read"] == 3
    assert body["pages_needing_ocr"] == [1, 4]
    assert body["chunk_count"] >= 1, "the readable pages should be indexed"


# ── Unattributed numeric runs stay out of the index ───────────────────────────

CHART_RUN = "### Value (GMV)245.9 268.9 279.6 224.5 290.7 243.4 118.6 125.3 130.7"


def test_a_chart_run_is_recognised_and_a_sentence_is_not():
    """The line this exists for, and the line it must not touch.

    A bar chart's labels are positioned graphics, so three series across three
    quarters extract as nine correct figures attached to nothing. A sentence citing
    the same figures carries its own attribution and must survive.
    """
    from aughor.knowledge.documents import is_numeric_run

    assert is_numeric_run(CHART_RUN) is True
    assert is_numeric_run("+140bps +700bps +70bps +240bps (60bps) +390bps") is True, \
        "a unit welded to a value belongs to the number, not to the prose"
    assert is_numeric_run(
        "GMV increased by +11.3% ex-FX (+7.0% reported) and Net Sales by +9.9%") is False
    assert is_numeric_run("Revenue grew across all regions.") is False


def test_a_colon_names_the_figure_that_follows_it():
    """The line the guard was suppressing, from a live retail market deck.

    `2026:` and `2025:` are periods being named, not figures being reported. Scored
    among the numbers they made six against five words — `H1` and `Ø` are not words
    by design — and the one line per city where every figure was attached to the
    period it measures was held out of the index, while the scrambled chart axes
    around it, being shorter than four numbers, went in.
    """
    from aughor.knowledge.documents import is_numeric_run

    assert is_numeric_run(
        "Take-up H1 2026: 24,000 sqm | H1 2025: 32,000 sqm | Ø 5 years 24,000 sqm"
    ) is False


def test_one_label_does_not_launder_an_axis():
    """The limit of the colon rule, and what makes it safe to widen the filter.

    Only the colon-terminated token stops counting as a figure; everything after it
    still counts. So a name in front of a stream names the STREAM, not each value in
    it, and a labelled axis is still an axis. These are the lines that would come
    back into the index if the rescue were applied to the whole line instead.
    """
    from aughor.knowledge.documents import is_numeric_run

    assert is_numeric_run("Prime rent: 340 320 300 280 260") is True
    assert is_numeric_run("Take-up: 24,000 32,000 18,000 9,000") is True
    assert is_numeric_run("Hamburg 235 200 170 165 150 Cologne 230 150") is True


# A chart interleaved into fragments. Not one of these lines reaches the four-figure
# floor on its own, which is exactly why the per-line rule left all of them in.
INTERLEAVED = "40.000 80 79\n25.000 50\n37"


def test_a_chart_spread_thin_is_still_a_chart():
    """The second shape a chart leaves, and the one the line rule could not see.

    A PowerPoint export interleaves two side-by-side charts into a column of two- and
    three-figure fragments. Measured on an 83-page retail deck: the per-line rule held
    back 83 lines and left 73 more of this kind in the index — a plausible-looking
    splice of two different charts, which is worse company than the long row ever was.
    """
    from aughor.knowledge.documents import _strip_numeric_runs, is_numeric_run

    # The premise: every line here is individually innocent.
    for line in INTERLEAVED.splitlines():
        assert is_numeric_run(line) is False, f"{line!r} should be under the line floor"

    assert _strip_numeric_runs(INTERLEAVED).strip() == ""


def test_a_line_that_carries_a_name_survives_the_block_around_it():
    """The neighbourhood is evidence, not a verdict.

    `52.225.499 Friedrichstr.` is a footfall count with its street on the same line. It
    sits in the middle of the axis debris the block rule is there to take, and it is
    the one line in that block nothing else attributes.
    """
    from aughor.knowledge.documents import _strip_numeric_runs

    kept = _strip_numeric_runs("40.000 80 79\n52.225.499 Friedrichstr.\n25.000 50\n37")
    assert kept.strip() == "52.225.499 Friedrichstr."


def test_a_heading_survives_the_block_around_it():
    """`##### 2021 - H1 2026` is the period a chart covers. It has no words in it — `H1`
    is not one by design — so only its heading marker keeps it, and it must: dropping it
    takes away the chunk's last remaining context."""
    from aughor.knowledge.documents import _strip_numeric_runs

    kept = _strip_numeric_runs("40.000 80 79\n##### 2021 - H1 2026\n25.000 50\n37")
    assert kept.strip() == "##### 2021 - H1 2026"


def test_prose_beside_a_headless_row_does_not_rescue_it():
    """The block rule WIDENS the line rule, it does not replace it.

    Sat next to a sentence, a headless row is in a paragraph where words dominate — so
    the block says nothing about it and the line rule still has to. Reading only the
    block would have quietly let this back into the index.
    """
    from aughor.knowledge.documents import _strip_numeric_runs

    prose = "Revenue rose sharply across every region we operate in this year."
    kept = _strip_numeric_runs(f"{prose}\n245.9 268.9 279.6 224.5")
    assert kept.strip() == prose


def test_a_pair_in_its_own_paragraph_is_still_left_alone():
    """The floor holds at the block level too — four figures, not two. A heading and a
    pair is a shape people write on purpose."""
    from aughor.knowledge.documents import _strip_numeric_runs

    assert _strip_numeric_runs("#### 774 847").strip() == "#### 774 847"


def test_what_is_reported_is_exactly_what_is_removed():
    """The count shown at the door and the lines taken from the index come from one
    answer. They were two passes over the same text, which is a drift waiting to
    happen — and the number is the only thing a person sees before approving."""
    from aughor.knowledge.documents import _strip_numeric_runs, numeric_run_lines

    text = f"# Deck\n\n{INTERLEAVED}\n\nSome prose that carries the chunk.\n\n{CHART_RUN}\n"
    removed = [line for line in text.splitlines()
               if line not in _strip_numeric_runs(text).splitlines()]
    assert numeric_run_lines(text) == removed
    assert len(removed) == 4


def test_a_table_row_is_never_a_run_however_many_numbers_it_holds():
    """Its header names the column, so every figure in it is attributed. This is the
    guard that keeps the financial tables — the part worth indexing — intact."""
    from aughor.knowledge.documents import is_numeric_run

    assert is_numeric_run("| EMEA | 4,200,000 | 12% | 47.1% | 86.8 | 1,064 |") is False


def test_two_numbers_are_left_alone():
    """Four is the floor on purpose. A pair under a heading is usually readable from
    its context, and suppressing it would widen the blast radius for no gain."""
    from aughor.knowledge.documents import is_numeric_run

    assert is_numeric_run("#### 774 847") is False


def test_numbers_inside_a_code_fence_are_kept():
    """The fence IS their attribution — that is program output or data someone pasted
    deliberately, not a chart axis."""
    from aughor.knowledge.documents import _strip_numeric_runs

    fenced = "```\n1.1 2.2 3.3 4.4 5.5 6.6\n```\n"
    assert "1.1 2.2 3.3" in _strip_numeric_runs(fenced)


def test_suppression_removes_the_run_from_the_index_but_not_the_document(client):
    """The distinction the whole feature rests on.

    The numbers stay in the stored Markdown — so preview, download and every
    conversion are faithful — and only what is embedded for retrieval changes.
    """
    body = (f"# Deck\n\n{CHART_RUN}\n\n"
            "Revenue grew across every region this quarter, with EMEA leading on "
            "margin and APAC on growth, as the table below sets out.\n")
    r = client.post("/documents/upload",
                    files={"file": ("deck.md", body.encode(), "text/markdown")})
    assert r.status_code == 201, r.text
    entry = r.json()

    assert entry["suppressed_numeric_runs"] == 1
    assert "245.9" in entry["suppressed_sample"][0]

    # The DOCUMENT still has it — this is the half that must not be lost.
    stored = client.get(f"/documents/{entry['doc_id']}/markdown").json()["markdown"]
    assert "245.9" in stored, "suppression reached the document, not just the index"

    # And every conversion is faithful to the document, not to the index.
    converted = client.get(f"/documents/{entry['doc_id']}/convert", params={"to": "txt"})
    assert "245.9" in converted.text


def test_turning_it_off_indexes_the_run_again(client):
    """It is a setting, not a law — and it is reversible by re-indexing."""
    import json

    body = f"# Deck\n\n{CHART_RUN}\n\nSome prose to carry the chunk over the minimum.\n"
    r = client.post("/documents/upload",
                    files={"file": ("deck2.md", body.encode(), "text/markdown")},
                    data={"chunk_settings": json.dumps({"suppress_numeric_runs": False})})
    assert r.status_code == 201, r.text
    assert "suppressed_numeric_runs" not in r.json()


def test_the_preview_door_reports_the_same_suppression(client):
    """Two doors, one rule — a preview that kept what upload holds back would
    misrepresent what is actually searchable."""
    body = f"# Deck\n\n{CHART_RUN}\n\nProse long enough to clear the minimum length.\n"
    r = client.post("/documents/preview",
                    files={"file": ("deck.md", body.encode(), "text/markdown")})
    assert r.status_code == 200
    assert r.json()["suppressed_numeric_runs"] == 1


def test_the_setting_round_trips_through_the_registry():
    """A re-index has to reproduce what cut a document, including this."""
    from aughor.knowledge.documents import ChunkSettings

    off = ChunkSettings(suppress_numeric_runs=False)
    assert off.as_dict()["suppress_numeric_runs"] is False
    assert ChunkSettings.from_dict(off.as_dict()) == off
    # Absence still means the defaults, which now include suppression.
    assert ChunkSettings.from_dict(None).suppress_numeric_runs is True


# ── Look before you commit ────────────────────────────────────────────────────

def test_convert_shows_the_result_without_indexing_anything(client):
    """The decision this exists for.

    Upload used to convert, chunk, embed and register in one motion, so the first
    sight of what the converter made of a file came after it was in the corpus — and
    on a hosted embedder, already paid for.
    """
    before = len(client.get("/documents").json())
    body = ("# Q3\n\n| Region | Revenue |\n| --- | --- |\n| EMEA | 4,200,000 |\n\n"
            "Revenue grew across every region this quarter, with EMEA leading.\n")

    r = client.post("/documents/convert",
                    files={"file": ("q3.md", body.encode(), "text/markdown")})

    assert r.status_code == 200, r.text
    out = r.json()
    assert "4,200,000" in out["markdown"]
    assert out["would_index_chunks"] >= 1, "a person deciding needs the chunk count"
    # Nothing was written anywhere.
    assert len(client.get("/documents").json()) == before, "convert registered a document"


def test_convert_retains_no_bytes(client):
    """No staging area means nothing to expire, sweep or leak."""
    root = Path(os.environ["AUGHOR_DOCUMENTS_DIR"])
    count = lambda: len(list(root.rglob("original*"))) if root.is_dir() else 0
    before = count()

    client.post("/documents/convert",
                files={"file": ("x.md", b"# Title\n\nEnough prose to clear the floor.\n",
                                "text/markdown")})

    assert count() == before


def test_convert_reports_what_upload_would_hold_back(client):
    """The preview has to show the same losses the upload would incur, or approving it
    means approving something you were not shown."""
    body = f"# Deck\n\n{CHART_RUN}\n\nProse long enough to clear the minimum length.\n"

    out = client.post("/documents/convert",
                      files={"file": ("d.md", body.encode(), "text/markdown")}).json()

    assert out["suppressed_numeric_runs"] == 1
    assert "245.9" in out["suppressed_sample"][0]
    # And the figures are still IN the markdown being shown — suppression is index-only.
    assert "245.9" in out["markdown"]


def test_convert_refuses_what_upload_refuses(client):
    """Two doors, one answer — approving something upload will reject is worse than a
    plain refusal."""
    r = client.post("/documents/convert",
                    files={"file": ("empty.md", b"", "text/markdown")})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "empty"


def test_what_convert_shows_is_what_upload_indexes(client):
    """Conversion is deterministic, which is what makes the client re-post safe: the
    approved Markdown and the indexed Markdown are the same string."""
    body = b"# Report\n\nRevenue grew across every region this quarter, led by EMEA.\n"

    shown = client.post("/documents/convert",
                        files={"file": ("r.md", body, "text/markdown")}).json()["markdown"]
    entry = client.post("/documents/upload",
                        files={"file": ("r.md", body, "text/markdown")}).json()
    stored = client.get(f"/documents/{entry['doc_id']}/markdown").json()["markdown"]

    assert shown == stored


# ── Generated schema docs are not the person's uploads ────────────────────────

def test_the_listing_says_which_rows_the_platform_generated(client):
    """Measured on a live install: 15 of 16 rows were compiled schema docs, so one real
    upload looked like sixteen documents nobody could act on."""
    from aughor.knowledge.indexer import index_text, is_generated

    client.post("/documents/upload",
                files={"file": ("mine.md",
                                b"# Mine\n\nA document a person actually uploaded here.\n",
                                "text/markdown")})
    index_text(text="Schema documentation for a table.\n" * 3, title="Schema doc",
               source="schema-docs/conn/default", doc_id="doctree::conn::default")

    rows = {d["doc_id"]: d for d in client.get("/documents").json()}
    assert rows["doctree::conn::default"]["generated"] is True
    mine = [d for d in rows.values() if d.get("filename") == "mine.md"]
    assert mine and mine[0]["generated"] is False

    assert is_generated("doctree::anything::x") is True
    assert is_generated("9bdef0884d5b4d5189cb24b8096e1114") is False


# ── Purging orphans must not cost an embedding run ────────────────────────────

def test_purging_orphans_embeds_nothing(client, monkeypatch):
    """`/documents/reindex` re-embeds the whole corpus on its way past the orphans —
    148 chunks paid for to delete 14 on the live install. An orphan needs no vector to
    be deleted."""
    from aughor.knowledge import reindex

    def _forbidden(*a, **k):
        raise AssertionError("purging orphans must never call the embedder")

    monkeypatch.setattr("aughor.semantic.embedder.embed", _forbidden)

    result = reindex.purge_orphans_only()
    assert result["ok"] is True
    assert result["embedded"] == 0


def test_the_purge_door_defaults_to_a_dry_run(client):
    r = client.post("/documents/purge-orphans")
    assert r.status_code == 200
    assert r.json()["dry_run"] is True
