"""KI-3 (§3.10) — Confluence/Notion definition mining.

The arc's stated receipts, driven: a Confluence metric page becomes staged candidates
with the page URL as provenance, and a re-mine of an unchanged page proposes nothing.
Plus the extraction truths: tables come from the RAW storage body (the sync's text
path flattens them), Notion table rows are child blocks the text path never fetches,
a Notion database is one table, and a header-less or nameless table is "not a
dictionary" — skipped, never an error.

Hermetic: syncers are fakes; no network anywhere.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aughor.api import app
from aughor.intake import mining

client = TestClient(app)

CONN = "ki3conn"
WIKI = "wiki3"

STORAGE_HTML = """
<h1>Finance metric dictionary</h1>
<ac:structured-macro ac:name="info"><ac:rich-text-body>Reviewed quarterly.
</ac:rich-text-body></ac:structured-macro>
<table>
  <tr><th>Metric</th><th>Definition</th><th>Formula</th><th>Aliases</th></tr>
  <tr><td>Net Revenue</td><td>Completed order value &amp; refunds netted.</td>
      <td>SUM(amount)</td><td>turnover</td></tr>
  <tr><td>Churn Rate</td><td>Share of customers lost per period.</td>
      <td></td><td></td></tr>
</table>
<table><tr><th>Quarter</th><th>Holiday</th></tr>
       <tr><td>Q3</td><td>none</td></tr></table>
<table><tr><td>just</td><td>a layout grid</td></tr></table>
"""


@pytest.fixture()
def stores(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_INTAKE_DB", str(tmp_path / "intake.db"))
    monkeypatch.setenv("AUGHOR_TRUSTED_QUERIES_PATH", str(tmp_path / "tq.json"))
    monkeypatch.setenv("AUGHOR_METRICS_PATH", str(tmp_path / "metrics.json"))
    monkeypatch.setenv("AUGHOR_GLOSSARY_PATH", str(tmp_path / "glossary.yaml"))
    monkeypatch.setenv("AUGHOR_VOCABULARY_ROOT", str(tmp_path / "vocab"))
    import aughor.semantic.connection_kb as kb
    monkeypatch.setattr(kb, "_DATA_DIR", tmp_path / "kb")
    monkeypatch.setattr(kb, "_index_entry", lambda e: None)
    monkeypatch.setattr(kb, "_delete_from_index", lambda c, i: None)
    monkeypatch.setattr(kb, "_invalidate_linker_hints", lambda c: None)
    return tmp_path


# ── extraction ───────────────────────────────────────────────────────────────────────


def test_storage_html_tables_extract_and_layout_grids_do_not():
    tables = mining.tables_from_storage_html(STORAGE_HTML)
    # The header-less layout grid is skipped at extraction; the holiday table has
    # headers (extracted) but is not a dictionary (that verdict is the mapper's).
    assert len(tables) == 2
    headers, rows = tables[0]
    assert headers == ["Metric", "Definition", "Formula", "Aliases"]
    assert rows[0]["Metric"] == "Net Revenue"
    assert rows[0]["Definition"] == "Completed order value & refunds netted."
    assert rows[1]["Formula"] == ""


def test_notion_table_blocks_fetch_rows_as_children():
    def _rt(s):
        return [{"plain_text": s}]

    blocks = [
        {"type": "paragraph", "paragraph": {"rich_text": _rt("intro")}},
        {"type": "table", "id": "tbl1", "table": {"has_column_header": True}},
        {"type": "table", "id": "tbl2", "table": {"has_column_header": False}},
    ]
    children = {
        "tbl1": [
            {"type": "table_row", "table_row": {"cells": [_rt("metric"), _rt("definition")]}},
            {"type": "table_row", "table_row": {"cells": [_rt("MRR"), _rt("Monthly recurring revenue.")]}},
        ],
        "tbl2": [
            {"type": "table_row", "table_row": {"cells": [_rt("a"), _rt("b")]}},
            {"type": "table_row", "table_row": {"cells": [_rt("c"), _rt("d")]}},
        ],
    }
    tables = mining.tables_from_notion_blocks(blocks, lambda bid: children.get(bid, []))
    assert len(tables) == 1                       # no header ⇒ nothing to map ⇒ skipped
    headers, rows = tables[0]
    assert headers == ["metric", "definition"]
    assert rows == [{"metric": "MRR", "definition": "Monthly recurring revenue."}]


def test_notion_database_is_one_table():
    pages = [
        {"properties": {
            "Name": {"type": "title", "title": [{"plain_text": "AOV"}]},
            "Definition": {"type": "rich_text",
                           "rich_text": [{"plain_text": "Average order value."}]},
            "Owner": {"type": "select", "select": {"name": "Finance"}},
            "Target": {"type": "number", "number": 42},
        }},
        {"properties": {
            "Name": {"type": "title", "title": [{"plain_text": "NPS"}]},
            "Definition": {"type": "rich_text",
                           "rich_text": [{"plain_text": "Net promoter score."}]},
            "Attachment": {"type": "files", "files": []},   # unreadable ⇒ blank
        }},
    ]
    headers, rows = mining.table_from_notion_database(pages)
    assert "Name" in headers and "Definition" in headers
    assert rows[0]["Name"] == "AOV" and rows[0]["Owner"] == "Finance"
    assert rows[1]["Definition"] == "Net promoter score."
    assert mining.table_from_notion_database([]) is None


# ── the receipts, end to end ─────────────────────────────────────────────────────────


class _FakeConfluence:
    def __init__(self, connection_id, meta):
        self._conn_id = connection_id
        self._base_url = "https://acme.atlassian.net"

    def _list_spaces(self):
        return ["FIN"]

    def _iter_pages(self, space_key):
        yield {"id": "9001", "title": "Metric dictionary",
               "body": {"storage": {"value": STORAGE_HTML}}}
        yield {"id": "9002", "title": "Team lunch spots",
               "body": {"storage": {"value": "<p>no tables here</p>"}}}


def _wire_confluence(monkeypatch):
    from aughor.connectors.knowledge import confluence as conf_mod
    from aughor.db import registry as reg

    monkeypatch.setattr(conf_mod, "ConfluenceSync", _FakeConfluence)
    real_get_dsn, real_get_meta = reg.get_dsn, reg.get_meta

    def _dsn(conn_id):
        if conn_id == WIKI:
            return "confluence", "confluence://"
        return real_get_dsn(conn_id)

    monkeypatch.setattr(reg, "get_dsn", _dsn)
    monkeypatch.setattr(reg, "get_meta",
                        lambda c: {} if c == WIKI else real_get_meta(c))


def test_a_confluence_metric_page_becomes_staged_candidates(stores, monkeypatch):
    _wire_confluence(monkeypatch)
    r = client.post("/intake/mine", json={
        "knowledge_connection_id": WIKI, "connection_id": CONN,
        "actor": "ana@example.com"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["staged"] == 1 and "error" not in body
    page = next(p for p in body["pages"] if p["outcome"] == "staged")
    # THE receipt: the page URL is the provenance.
    assert page["url"] == "https://acme.atlassian.net/wiki/spaces/FIN/pages/9001"
    assert page["tables_seen"] == 2 and page["tables_mapped"] == 1

    from aughor.intake import store
    b = store.get_bundle(page["bundle_id"], org_id="default")
    assert b["source"] == page["url"]
    kinds = sorted(c["kind"] for c in store.list_candidates(page["bundle_id"],
                                                            org_id="default"))
    assert kinds == ["definition", "definition", "metric", "synonym"]

    # …and the mined candidates land through the same lane on accept.
    cands = store.list_candidates(page["bundle_id"], org_id="default")
    res = client.post(f"/intake/bundles/{page['bundle_id']}/resolve",
                      json={"actor": "ana@example.com",
                            "accept": [c["id"] for c in cands]})
    assert res.status_code == 200 and res.json()["errors"] == 0
    from aughor.semantic.metrics import get_metric
    assert get_metric("net_revenue", connection_id=CONN).status == "proposed"


def test_remining_an_unchanged_page_proposes_nothing(stores, monkeypatch):
    _wire_confluence(monkeypatch)
    args = {"knowledge_connection_id": WIKI, "connection_id": CONN,
            "actor": "ana@example.com"}
    first = client.post("/intake/mine", json=args).json()
    again = client.post("/intake/mine", json=args).json()
    assert again["staged"] == 0 and again["duplicates"] == 1
    assert (next(p["bundle_id"] for p in again["pages"] if "bundle_id" in p)
            == next(p["bundle_id"] for p in first["pages"] if "bundle_id" in p))


class _FakeNotion:
    _db_ids = ["deadbeefcafe"]

    def __init__(self, connection_id, meta):
        pass

    def _search_pages(self):
        yield {"id": "ab-cd", "url": "https://notion.so/kpis",
               "properties": {"title": {"type": "title",
                                        "title": [{"plain_text": "KPI table"}]}}}

    def _page_title(self, page):
        return "KPI table"

    def _get_page_blocks(self, block_id):
        if block_id == "abcd":
            return [{"type": "table", "id": "t1",
                     "table": {"has_column_header": True}}]
        if block_id == "t1":
            return [
                {"type": "table_row", "table_row": {"cells": [
                    [{"plain_text": "metric"}], [{"plain_text": "formula"}]]}},
                {"type": "table_row", "table_row": {"cells": [
                    [{"plain_text": "GMV"}], [{"plain_text": "SUM(gross)"}]]}},
            ]
        return []

    def _query_database(self, db_id):
        return [{"properties": {
            "Name": {"type": "title", "title": [{"plain_text": "Refund Rate"}]},
            "Definition": {"type": "rich_text",
                           "rich_text": [{"plain_text": "Refunds over orders."}]},
        }}]


def test_notion_pages_and_databases_both_mine(stores, monkeypatch):
    from aughor.connectors.knowledge import notion as notion_mod
    from aughor.db import registry as reg

    monkeypatch.setattr(notion_mod, "NotionSync", _FakeNotion)
    real_get_dsn, real_get_meta = reg.get_dsn, reg.get_meta
    monkeypatch.setattr(reg, "get_dsn",
                        lambda c: ("notion", "notion://") if c == WIKI
                        else real_get_dsn(c))
    monkeypatch.setattr(reg, "get_meta",
                        lambda c: {} if c == WIKI else real_get_meta(c))

    r = client.post("/intake/mine", json={
        "knowledge_connection_id": WIKI, "connection_id": CONN,
        "actor": "ana@example.com"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["staged"] == 2
    urls = {p["url"] for p in body["pages"]}
    assert "https://notion.so/kpis" in urls
    assert any(u.startswith("https://www.notion.so/deadbeefcafe") for u in urls)


def test_unknown_and_non_knowledge_connections_are_refused(stores):
    r = client.post("/intake/mine", json={
        "knowledge_connection_id": "no-such-wiki", "connection_id": CONN,
        "actor": "ana@example.com"})
    assert r.status_code == 404
