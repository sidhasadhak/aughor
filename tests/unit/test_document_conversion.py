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
