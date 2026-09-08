"""Markdown back out again — the other half of the pivot.

`convert.py` brings fourteen formats IN by turning them into Markdown. This takes that
Markdown OUT into six. Together that is twenty seams rather than the eighty-four a
format-pair matrix would need, and it is the whole reason "any document to any format"
is a small amount of code.

Almost none of the rendering is new: `aughor/export/` has produced PDFs and PowerPoint
from an `ExportDoc` for a long time and was simply wired to one producer, an
investigation's `report_json`. The new part is a Markdown parser that builds the same
`ExportDoc`, which is what these tests concentrate on — a renderer fed the wrong blocks
produces a beautifully typeset wrong document.

The assertion that matters most is the round trip. A table that survives
`docx → Markdown → docx` proves both halves at once, and it is exactly what the old
extraction path could not do: it dropped Word tables in silence.
"""
from __future__ import annotations

import pytest

anydoc = pytest.importorskip("anydoc", reason="the 'docs' extra is not installed")

from aughor.knowledge.render import (  # noqa: E402
    FORMATS, RenderError, available_formats, parse_markdown, render, strip_inline,
)

TABLE_MD = """# Q3 Revenue Review

Revenue grew across all regions.

## By region

| Region | Revenue | Growth |
| --- | --- | --- |
| EMEA | 4,200,000 | 12% |
| AMER | 7,850,000 | 8% |
| APAC | 3,100,000 | 23% |

- APAC outperformed.
- EMEA held margin.
"""

AMOUNTS = ("4,200,000", "7,850,000", "3,100,000")


# ── Parsing to blocks ─────────────────────────────────────────────────────────

def test_markdown_becomes_the_block_model_the_renderers_already_speak():
    doc = parse_markdown(TABLE_MD, title="Q3")

    kinds = [b.kind for b in doc.blocks]
    assert kinds == ["heading", "prose", "heading", "table", "bullets"]
    table = next(b for b in doc.blocks if b.kind == "table")
    assert table.columns == ["Region", "Revenue", "Growth"]
    assert len(table.rows) == 3
    assert table.rows[0] == ["EMEA", "4,200,000", "12%"]


def test_a_line_of_pipes_is_only_a_table_when_it_has_its_rule():
    """Prose containing pipes is prose. Without the `| --- |` line beneath it, a row
    of pipes is a sentence someone wrote, and turning it into a one-row table would
    silently restructure their document."""
    doc = parse_markdown("Use | to separate fields.\n", title="t")
    assert [b.kind for b in doc.blocks] == ["prose"]


def test_a_short_row_is_padded_rather_than_dropped():
    """A converted spreadsheet ends rows early where trailing cells were empty.
    Dropping the row would lose data that is merely short."""
    doc = parse_markdown(
        "| a | b | c |\n| --- | --- | --- |\n| 1 | 2 |\n", title="t")
    table = doc.blocks[0]
    assert table.rows == [["1", "2", ""]]


def test_fenced_code_is_kept_verbatim():
    doc = parse_markdown("```sql\nSELECT 1\n  FROM t\n```\n", title="t")
    assert doc.blocks[0].kind == "code"
    assert doc.blocks[0].text == "SELECT 1\n  FROM t"
    assert doc.blocks[0].caption == "sql"


def test_a_table_inside_a_code_fence_stays_code():
    """The fence wins. A document explaining Markdown must not have its example
    parsed as the thing it is describing."""
    doc = parse_markdown("```\n| a |\n| --- |\n```\n", title="t")
    assert [b.kind for b in doc.blocks] == ["code"]


def test_inline_syntax_is_stripped_but_the_words_survive():
    assert strip_inline("**bold** and *it* and `code`") == "bold and it and code"
    assert strip_inline("see [the docs](https://example.com)") == "see the docs"
    assert strip_inline("![a chart](chart.png)") == "a chart"


# ── Rendering ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fmt", sorted(FORMATS))
def test_every_declared_format_renders_something(fmt: str):
    """The declaration and the capability are the same list, or the UI offers a
    button that fails at the click."""
    ready = {f["format"] for f in available_formats() if f["available"]}
    if fmt not in ready:
        pytest.skip(f"{fmt} needs an extra this install does not have")

    data, media_type, suffix = render(TABLE_MD, fmt, title="Q3 Revenue")
    assert data, f"{fmt} rendered zero bytes"
    assert suffix == FORMATS[fmt][2]
    assert media_type == FORMATS[fmt][1]


@pytest.mark.parametrize("fmt", ["md", "txt", "html", "docx"])
def test_the_numbers_survive_every_format(fmt: str):
    """The defect that started all of this was a table's values disappearing."""
    data, _, _ = render(TABLE_MD, fmt, title="Q3 Revenue")
    text = anydoc.to_markdown_bytes(data) if fmt == "docx" else data.decode()
    for amount in AMOUNTS:
        assert amount in text, f"{fmt} lost {amount}"


def test_html_escapes_the_document_rather_than_passing_it_through():
    """These documents come from outside and are rendered for other people to look
    at. Building the page from parsed blocks — instead of converting Markdown to HTML
    with a library that allows raw HTML by default — is what makes that safe."""
    hostile = "# Title\n\n<script>alert(1)</script>\n"
    page = render(hostile, "html", title="<img src=x onerror=alert(1)>")[0].decode()

    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page
    assert "<img src=x" not in page, "the title was interpolated unescaped"


def test_plain_text_lays_tables_out_as_columns():
    """The point of asking for text is that it reads without a renderer."""
    text = render(TABLE_MD, "txt", title="Q3")[0].decode()
    assert "|" not in text, "pipes are not a layout"
    assert "Region" in text and "Revenue" in text
    # Values line up under their header.
    header = next(line for line in text.splitlines() if line.startswith("Region"))
    row = next(line for line in text.splitlines() if line.startswith("EMEA"))
    assert row.index("4,200,000") == header.index("Revenue")


def test_an_unknown_format_is_refused_by_name():
    with pytest.raises(RenderError) as exc:
        render(TABLE_MD, "wordperfect")
    assert exc.value.code == "unknown_format"
    assert "md" in str(exc.value), "the error should say what IS available"


# ── The round trip: both halves at once ───────────────────────────────────────

def test_a_word_table_survives_docx_to_markdown_to_docx():
    """The end-to-end proof.

    A Word file goes in, becomes Markdown, is rendered back to Word, and is read
    again. Every value must still be there. The path this replaced could not manage
    the first step alone — `python-docx`'s `.paragraphs` does not walk tables, so the
    numbers were gone before any of the rest of this ran.
    """
    docx = pytest.importorskip("docx", reason="the 'docs' extra is not installed")
    import io

    source = docx.Document()
    source.add_heading("Q3 Revenue Review", level=1)
    table = source.add_table(rows=4, cols=3)
    rows = [("Region", "Revenue", "Growth"), ("EMEA", "4,200,000", "12%"),
            ("AMER", "7,850,000", "8%"), ("APAC", "3,100,000", "23%")]
    for i, row in enumerate(rows):
        for j, value in enumerate(row):
            table.cell(i, j).text = value
    buf = io.BytesIO()
    source.save(buf)

    as_markdown = anydoc.to_markdown_bytes(buf.getvalue())
    back_to_word, _, _ = render(as_markdown, "docx", title="Q3 Revenue Review")
    read_again = anydoc.to_markdown_bytes(back_to_word)

    for amount in AMOUNTS:
        assert amount in read_again, f"{amount} did not survive the round trip"
    assert "Q3 Revenue Review" in read_again


# ── The routes ────────────────────────────────────────────────────────────────

def _upload_markdown(client, text: str = TABLE_MD, name: str = "revenue.md"):
    return client.post("/documents/upload",
                       files={"file": (name, text.encode(), "text/markdown")}).json()


def test_a_stored_document_converts_through_the_api(client):
    doc_id = _upload_markdown(client)["doc_id"]

    r = client.get(f"/documents/{doc_id}/convert", params={"to": "html"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/html")
    assert "4,200,000" in r.text
    assert r.headers["content-disposition"].startswith("attachment")


def test_the_offered_formats_are_the_ones_this_install_can_write(client):
    doc_id = _upload_markdown(client)["doc_id"]

    body = client.get(f"/documents/{doc_id}/formats").json()
    assert {f["format"] for f in body["formats"]} == set(FORMATS)
    assert all("available" in f for f in body["formats"]), \
        "a format offered without saying whether it works is a button that fails"


def test_an_unknown_target_format_is_refused_not_guessed(client):
    doc_id = _upload_markdown(client)["doc_id"]

    r = client.get(f"/documents/{doc_id}/convert", params={"to": "wordperfect"})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "unknown_format"


def test_converting_a_document_that_does_not_exist_is_a_404(client):
    r = client.get("/documents/nope/convert", params={"to": "md"})
    assert r.status_code == 404


def test_a_hostile_filename_cannot_forge_a_download_header():
    """The defence, tested where it actually lives.

    The title reaches a Content-Disposition header from an uploaded file's name, so
    it comes from outside. A quote would close the quoted string and a CRLF would end
    the header, letting a caller write their own.

    This asserts on the sanitiser directly rather than through an upload, because an
    HTTP client escapes the filename in the multipart body before it is ever sent —
    so driving it over the wire tests httpx's encoder and quietly proves nothing about
    ours. The connectors reaching `index_text` do not go through a multipart encoder
    at all, which is precisely why this must hold on its own.
    """
    from aughor.routers.knowledge import _safe_download_name

    hostile = _safe_download_name('evil" \r\nX-Injected: yes')
    assert '"' not in hostile
    assert "\r" not in hostile and "\n" not in hostile
    assert ":" not in hostile
    # The words may survive — harmless inside a quoted filename. Header STRUCTURE is
    # what must not.
    assert _safe_download_name("") == "document", "an empty name still needs a filename"
    assert len(_safe_download_name("x" * 500)) <= 120, "an unbounded filename is a header bomb"


def test_the_download_header_stays_well_formed_over_the_wire(client):
    entry = _upload_markdown(client, name="quarterly report.md")

    r = client.get(f"/documents/{entry['doc_id']}/convert", params={"to": "md"})
    disposition = r.headers["content-disposition"]
    assert disposition.count('"') == 2, f"unbalanced quoting: {disposition!r}"
    assert disposition.endswith('.md"')
    assert "\n" not in disposition and "\r" not in disposition


# ── Malformed tables from real converters ─────────────────────────────────────

def test_a_row_wider_than_its_header_keeps_every_cell():
    """Truncating to the header's width silently DELETED data on a real document.

    Converters do not escape pipes inside a cell, so a slide whose row label is
    "Luxury | Mytheresa" emits three cells under a two-cell header. Truncation kept
    "Luxury", dropped "Mytheresa", and threw away the entire bullet list of results
    beside it — measured on a live 40-page investor deck, where the table holding
    every GMV, Net Sales and NPS figure came out as [['Luxury'], ['Luxury'],
    ['Off-price']]. The rendered PDF looked perfectly well-formed with its numbers
    gone, which is the worst shape a failure can take.
    """
    md = ("||Business Highlights|\n"
          "| --- | --- |\n"
          "|Luxury | Mytheresa|GMV +11.3%, NPS 86.8|\n"
          "|Off-price | YOOX|GMV -8.9%, NPS 48.8|\n")
    table = parse_markdown(md, title="t").blocks[0]

    assert table.kind == "table"
    flat = " ".join(" ".join(r) for r in table.rows)
    for kept in ("Mytheresa", "GMV +11.3%", "NPS 86.8", "YOOX", "GMV -8.9%"):
        assert kept in flat, f"{kept!r} was dropped"
    assert all(len(r) == len(table.columns) for r in table.rows), "ragged after widening"


def test_an_empty_leading_cell_is_not_eaten():
    """`str.strip('|')` is greedy: `||Highlights|` lost BOTH pipes and came back one
    cell narrower than the rows beneath it, which is what fed the truncation."""
    md = "||Highlights|\n| --- | --- |\n|a|b|\n"
    table = parse_markdown(md, title="t").blocks[0]

    assert len(table.columns) == 2, f"header parsed as {table.columns}"
    assert table.rows == [["a", "b"]]


def test_the_numbers_survive_a_real_deck_shaped_table():
    """End to end through a renderer, on the shape that lost them."""
    md = ("||Business Highlights|\n| --- | --- |\n"
          "|Luxury | Mytheresa|GMV +11.3% and NPS 86.8|\n")
    text = render(md, "txt", title="Deck")[0].decode()
    assert "Mytheresa" in text and "86.8" in text
