"""KI-2 (§3.10) — the deterministic file mappers.

Receipts: the same Sheet-shaped CSV yields the same candidate set twice (the
deterministic path is deterministic); a real-world header vocabulary maps (Metric /
Definition / Formula / Aliases…); rows without a formula still carry their prose
definition into the lane; a dbt manifest maps through the SAME parser the
env-configured layer uses; and the file door feeds the SAME lane — a mapped file is
just a bundle, human verdicts included.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aughor.api import app
from aughor.intake import mappers

client = TestClient(app)

CONN = "ki2conn"

CSV = (
    "Metric,Definition,Formula,Unit,Owner,Aliases,Notes\n"
    "Net Revenue,All completed order value net of refunds.,SUM(amount),EUR,"
    "Finance,\"turnover; sales\",Excludes gift cards\n"
    "Churn Rate,Share of customers lost in a period.,,,,attrition,\n"
    ",orphan row without a name,,,,,\n"
)


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


# ── the mapper itself ────────────────────────────────────────────────────────────────


def test_dictionary_mapping_is_deterministic_and_complete():
    headers, rows = mappers.read_tabular("dict.csv", CSV.encode())
    first = mappers.map_dictionary_rows(headers, rows)
    second = mappers.map_dictionary_rows(headers, rows)
    assert first == second   # the receipt: same bytes, same candidates

    sections, ignored, refused = first
    assert ignored == []
    # Row with a formula → a governed-metric candidate, fields mapped.
    m = sections["metrics"][0]
    assert m["name"] == "net_revenue" and m["label"] == "Net Revenue"
    assert m["sql"] == "SUM(amount)" and m["unit"] == "EUR"
    assert m["owner"] == "Finance" and m["caveats"] == "Excludes gift cards"
    # BOTH rows carry their prose definition; the formula-less one is not lost.
    titles = [d["title"] for d in sections["definitions"]]
    assert titles == ["Net Revenue", "Churn Rate"]
    # Aliases fan out, split on ; and ,.
    syns = {(s["subject_id"], s["synonym"]) for s in sections["synonyms"]}
    assert syns == {("net_revenue", "turnover"), ("net_revenue", "sales"),
                    ("churn_rate", "attrition")}
    # The orphan row is refused with its row number, not silently dropped.
    assert any("row 4" in r for r in refused)


def test_bom_and_tsv_and_unknown_headers():
    bom_csv = "﻿name,definition,mystery\nMRR,Monthly recurring revenue.,x\n"
    headers, rows = mappers.read_tabular("d.csv", bom_csv.encode())
    sections, ignored, refused = mappers.map_dictionary_rows(headers, rows)
    assert headers[0] == "name"          # BOM stripped, not glued to the header
    assert ignored == ["mystery"] and refused == []
    assert sections["definitions"][0]["title"] == "MRR"

    tsv = "metric\tformula\nAOV\tAVG(order_total)\n"
    h2, r2 = mappers.read_tabular("d.tsv", tsv.encode())
    s2, _, _ = mappers.map_dictionary_rows(h2, r2)
    assert s2["metrics"][0]["name"] == "aov"


def test_missing_name_column_and_unsupported_type_are_refused():
    with pytest.raises(ValueError, match="metric-name column"):
        h, r = mappers.read_tabular("d.csv", b"definition,unit\nfoo,EUR\n")
        mappers.map_dictionary_rows(h, r)
    with pytest.raises(ValueError, match="unsupported file type"):
        mappers.read_tabular("dict.parquet", b"")


def test_xlsx_reads_through_duckdbs_excel_extension(tmp_path, duckdb_extension):
    duckdb_extension("excel")
    import xlsxwriter
    p = tmp_path / "dict.xlsx"
    wb = xlsxwriter.Workbook(str(p))
    ws = wb.add_worksheet()
    for col, h in enumerate(["Metric", "Formula", "Definition"]):
        ws.write(0, col, h)
    ws.write(1, 0, "Gross Margin")
    ws.write(1, 1, "SUM(revenue - cogs) / SUM(revenue)")
    ws.write(1, 2, "Share of revenue kept after direct costs.")
    wb.close()

    headers, rows = mappers.read_tabular("dict.xlsx", p.read_bytes())
    sections, _, refused = mappers.map_dictionary_rows(headers, rows)
    assert refused == []
    assert sections["metrics"][0]["name"] == "gross_margin"
    assert sections["definitions"][0]["title"] == "Gross Margin"


def test_dbt_manifest_maps_through_the_shared_parser():
    manifest = {
        "metadata": {"dbt_version": "1.8.0"},
        "nodes": {
            "model.shop.orders": {
                "name": "orders", "schema": "analytics",
                "description": "One row per order.",
                "columns": {"Amount": {"description": "Order total, EUR."}},
                "config": {"materialized": "table"},
            },
            "model.shop.tmp": {"name": "tmp", "schema": "analytics",
                               "config": {"materialized": "ephemeral"},
                               "description": "never appears"},
        },
        "sources": {},
    }
    sections = mappers.map_dbt_manifest(manifest)
    entries = sections["glossary"]
    assert len(entries) == 1                       # the ephemeral model is skipped
    assert entries[0]["table"] == "analytics.orders"
    assert entries[0]["columns"]["amount"]["description"] == "Order total, EUR."


# ── the file door feeds the same lane ────────────────────────────────────────────────


def test_csv_file_door_stages_and_accepts_into_the_stores(stores):
    r = client.post("/intake/files",
                    files={"file": ("acme.csv", CSV.encode(), "text/csv")},
                    data={"connection_id": CONN, "actor": "ana@example.com"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["mapped"]["file"] == "acme.csv"
    assert any("row 4" in x for x in body["refused"])
    kinds = sorted(c["kind"] for c in body["candidates"])
    assert kinds == ["definition", "definition", "metric",
                     "synonym", "synonym", "synonym"]

    res = client.post(f"/intake/bundles/{body['bundle']['id']}/resolve",
                      json={"actor": "ana@example.com",
                            "accept": [c["id"] for c in body["candidates"]]})
    assert res.status_code == 200 and res.json()["errors"] == 0

    from aughor.semantic.metrics import get_metric
    m = get_metric("net_revenue", connection_id=CONN)
    assert m is not None and m.status == "proposed"
    from aughor.semantic.connection_kb import load_entries
    defs = {e.title for e in load_entries(CONN) if e.kind == "metric"}
    assert defs == {"Net Revenue", "Churn Rate"}
    from aughor.ontology.vocabulary import synonyms_for
    assert {s.synonym for s in synonyms_for(CONN)} >= {"turnover", "attrition"}

    # Same file again: content-hash dedupe, nothing re-staged.
    again = client.post("/intake/files",
                        files={"file": ("acme.csv", CSV.encode(), "text/csv")},
                        data={"connection_id": CONN, "actor": "ana@example.com"})
    assert again.json()["duplicate"] is True
    assert again.json()["bundle"]["id"] == body["bundle"]["id"]


def test_dbt_manifest_file_door(stores):
    import json
    manifest = {"metadata": {}, "sources": {}, "nodes": {
        "model.shop.customers": {"name": "customers", "schema": "",
                                 "description": "One row per customer.",
                                 "columns": {}, "config": {}}}}
    r = client.post("/intake/files",
                    files={"file": ("manifest.json",
                                    json.dumps(manifest).encode(), "application/json")},
                    data={"connection_id": CONN, "actor": "ana@example.com"})
    assert r.status_code == 201, r.text
    cands = r.json()["candidates"]
    assert [c["kind"] for c in cands] == ["glossary"]

    client.post(f"/intake/bundles/{r.json()['bundle']['id']}/resolve",
                json={"actor": "ana@example.com", "accept": [cands[0]["id"]]})
    from aughor.semantic.glossary import load_glossary
    assert (load_glossary()["tables"]["customers"]["description"]
            == "One row per customer.")


def test_sheets_definitions_mode_feeds_the_same_lane(stores, monkeypatch):
    """KI-3's Sheets mode: the fetch is patched (unit tests stay off the network);
    everything after the fetch is the SAME mapper and the SAME lane."""
    from aughor.intake import mappers

    fetched: dict = {}

    def _fake_fetch(spreadsheet, sheet=""):
        fetched["args"] = (spreadsheet, sheet)
        return CSV.encode()

    monkeypatch.setattr(mappers, "fetch_gsheet_csv", _fake_fetch)
    r = client.post("/intake/sheets", json={
        "spreadsheet": "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjK/edit",
        "sheet": "KPIs", "connection_id": CONN, "actor": "ana@example.com"})
    assert r.status_code == 201, r.text
    assert fetched["args"][1] == "KPIs"
    kinds = sorted(c["kind"] for c in r.json()["candidates"])
    assert kinds == ["definition", "definition", "metric",
                     "synonym", "synonym", "synonym"]
    assert r.json()["bundle"]["source"].startswith("gsheet:")


def test_sheets_mode_reports_a_private_sheet_plainly(stores, monkeypatch):
    from aughor.intake import mappers

    def _login_page(spreadsheet, sheet=""):
        raise ValueError("the sheet is not link-shared — Google answered with a "
                         "login page. Share it as 'Anyone with the link can view'.")

    monkeypatch.setattr(mappers, "fetch_gsheet_csv", _login_page)
    r = client.post("/intake/sheets", json={
        "spreadsheet": "1AbCdEfGhIjK", "connection_id": CONN,
        "actor": "ana@example.com"})
    assert r.status_code == 422 and "link-shared" in r.json()["detail"]


def test_sheet_id_validation_refuses_junk():
    from aughor.intake.mappers import fetch_gsheet_csv
    with pytest.raises(ValueError, match="spreadsheet id"):
        fetch_gsheet_csv("not a sheet!!")


def test_file_door_refuses_what_it_cannot_map(stores):
    r = client.post("/intake/files",
                    files={"file": ("notes.json", b"{\"hello\": 1}", "application/json")},
                    data={"connection_id": CONN, "actor": "ana@example.com"})
    assert r.status_code == 422 and "dbt" in r.json()["detail"]
    r2 = client.post("/intake/files",
                     files={"file": ("dict.csv", b"definition\nfoo\n", "text/csv")},
                     data={"connection_id": CONN, "actor": "ana@example.com"})
    assert r2.status_code == 422 and "metric-name column" in r2.json()["detail"]
