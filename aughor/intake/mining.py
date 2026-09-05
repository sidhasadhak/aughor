"""KI-3 (§3.10) — mining Confluence/Notion pages for definition candidates.

The deterministic first cut, exactly as the arc scoped it: TABLES inside pages,
through the SAME dictionary mapper the file and Sheets doors use. Prose mining waits
on the LLM mapper (KI-2's deferred half) — nothing here calls a model, and a table
whose headers don't name a metric column is simply "not a dictionary", never an
error.

The mining pipeline is built ONCE; only the table EXTRACTION is per-format, because
the wire formats genuinely differ: Confluence pages carry storage-format XHTML with
literal ``<table>`` markup, Notion pages carry ``table`` blocks whose rows are
CHILDREN blocks (which the knowledge sync never fetches — a table is entirely
invisible to the document KB today), and a Notion DATABASE is itself the most
dictionary-shaped thing in the product: its page properties ARE the columns.

Nothing here writes to any store. The router stages what this module returns, so a
mined page is just a bundle — human verdicts included, page URL as provenance, and
the content-hash dedupe making a re-mine of an unchanged page propose nothing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterator

Table = tuple[list[str], list[dict]]     # (headers, rows-as-dicts) — read_tabular's shape


@dataclass
class MinedPage:
    url: str
    title: str
    sections: dict = field(default_factory=dict)
    refused: list[str] = field(default_factory=list)
    tables_seen: int = 0
    tables_mapped: int = 0


# ── Confluence: storage-format XHTML tables ──────────────────────────────────────────

_TABLE_RE = re.compile(r"<table[^>]*>(.*?)</table>", re.DOTALL | re.I)
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.I)
_CELL_RE = re.compile(r"<t([hd])[^>]*>(.*?)</t\1>", re.DOTALL | re.I)


def _strip_cell(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    text = (text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " "))
    return re.sub(r"\s+", " ", text).strip()


def tables_from_storage_html(html: str) -> list[Table]:
    """Every ``<table>`` in a Confluence storage-format body, as (headers, rows).

    The header row is the first row whose cells are ``<th>``; a table with no header
    row cannot be column-mapped and is skipped here (counted by the caller). The
    connector's own text-stripper flattens tables to word soup, which is why mining
    reads the RAW body rather than the synced document text."""
    out: list[Table] = []
    for tbl in _TABLE_RE.findall(html or ""):
        rows_raw = []
        header: list[str] | None = None
        for tr in _ROW_RE.findall(tbl):
            cells = _CELL_RE.findall(tr)
            if not cells:
                continue
            values = [_strip_cell(c) for _, c in cells]
            if header is None and all(kind == "h" for kind, _ in cells):
                header = values
                continue
            rows_raw.append(values)
        if not header or not rows_raw:
            continue
        rows = [{h: (r[i] if i < len(r) else "") for i, h in enumerate(header)}
                for r in rows_raw]
        out.append((header, rows))
    return out


# ── Notion: table blocks (rows are CHILDREN) and databases ───────────────────────────


def _plain(rich: list[dict]) -> str:
    return "".join(rt.get("plain_text", "") for rt in (rich or [])).strip()


def tables_from_notion_blocks(blocks: list[dict],
                              fetch_children: Callable[[str], list[dict]]) -> list[Table]:
    """Every ``table`` block's rows, fetched via ``fetch_children`` (the sync's own
    block reader) — the rows are child blocks the text path never requests. A table
    without ``has_column_header`` is skipped: with no header there is nothing to
    column-map, and guessing one would be judgement, which the lane reserves for
    humans."""
    out: list[Table] = []
    for block in blocks or []:
        if block.get("type") != "table":
            continue
        if not (block.get("table") or {}).get("has_column_header"):
            continue
        rows_blocks = [b for b in fetch_children(block.get("id", ""))
                       if b.get("type") == "table_row"]
        if len(rows_blocks) < 2:
            continue
        cells = [[_plain(c) for c in (b.get("table_row") or {}).get("cells") or []]
                 for b in rows_blocks]
        header, body = cells[0], cells[1:]
        if not any(header):
            continue
        rows = [{h: (r[i] if i < len(r) else "") for i, h in enumerate(header)}
                for r in body]
        out.append((header, rows))
    return out


def table_from_notion_database(pages: list[dict]) -> Table | None:
    """A Notion database as ONE table: property names are the headers, each page's
    property values a row. Only plainly-textual property types are read (title,
    rich_text, select, multi_select, number, formula-string) — a property the
    extraction cannot read deterministically is left blank, never guessed."""
    headers: list[str] = []
    rows: list[dict] = []
    for page in pages or []:
        row: dict[str, str] = {}
        for name, prop in (page.get("properties") or {}).items():
            ptype = prop.get("type", "")
            val = ""
            if ptype in ("title", "rich_text"):
                val = _plain(prop.get(ptype) or [])
            elif ptype == "select":
                val = str((prop.get("select") or {}).get("name") or "")
            elif ptype == "multi_select":
                val = ", ".join(str(o.get("name") or "")
                                for o in prop.get("multi_select") or [])
            elif ptype == "number":
                v = prop.get("number")
                val = "" if v is None else str(v)
            elif ptype == "formula":
                f = prop.get("formula") or {}
                val = str(f.get("string") or f.get("number") or "")
            if name not in headers:
                headers.append(name)
            row[name] = val
        if any(row.values()):
            rows.append(row)
    if not headers or not rows:
        return None
    return headers, [{h: r.get(h, "") for h in headers} for r in rows]


# ── The one pipeline: pages with tables → sections per page ──────────────────────────


def _names_a_metric_column(headers: list[str]) -> bool:
    from aughor.intake.mappers import HEADER_ALIASES
    return any(HEADER_ALIASES.get((h or "").strip().lower().replace(" ", "_")) == "name"
               for h in headers)


def _map_tables(page: MinedPage, tables: list[Table]) -> None:
    """Run every table through the dictionary mapper; merge what maps. A table with
    no metric-name column is counted and skipped — a schedule grid is not a
    dictionary, and skipping it is a plan fact, not a swallowed failure — checked
    explicitly rather than by catching the mapper's refusal."""
    from aughor.intake.mappers import map_dictionary_rows

    page.tables_seen += len(tables)
    for headers, rows in tables:
        if not _names_a_metric_column(headers):
            continue
        sections, _ignored, refused = map_dictionary_rows(headers, rows)
        page.tables_mapped += 1
        page.refused.extend(refused)
        for key, entries in sections.items():
            page.sections.setdefault(key, []).extend(entries)


def mine_confluence(syncer) -> Iterator[MinedPage]:
    """Walk the connector's OWN space/page iterators (the fetcher exists; only the
    mining is new) and yield each page that carries at least one table."""
    for space_key in syncer._list_spaces():
        for raw in syncer._iter_pages(space_key):
            html = (raw.get("body") or {}).get("storage", {}).get("value", "")
            tables = tables_from_storage_html(html)
            if not tables:
                continue
            page = MinedPage(
                url=(f"{syncer._base_url}/wiki/spaces/{space_key}"
                     f"/pages/{raw.get('id', '')}"),
                title=str(raw.get("title") or "Untitled"))
            _map_tables(page, tables)
            yield page


def mine_notion(syncer) -> Iterator[MinedPage]:
    """Pages first (table blocks, rows fetched as children), then each configured
    database as one table keyed by the database's own URL."""
    for raw in syncer._search_pages():
        page_id = str(raw.get("id") or "").replace("-", "")
        blocks = syncer._get_page_blocks(page_id)
        tables = tables_from_notion_blocks(blocks, syncer._get_page_blocks)
        if not tables:
            continue
        page = MinedPage(url=str(raw.get("url") or f"notion:{page_id}"),
                         title=syncer._page_title(raw))
        _map_tables(page, tables)
        yield page
    for db_id in getattr(syncer, "_db_ids", []) or []:
        pages = list(syncer._query_database(db_id))
        table = table_from_notion_database(pages)
        if table is None:
            continue
        page = MinedPage(url=f"https://www.notion.so/{db_id.replace('-', '')}",
                         title=f"Notion database {db_id[:8]}")
        _map_tables(page, [table])
        yield page
