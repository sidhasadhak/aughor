"""R2 — the inferred schema is PINNED as a contract at ingest (Databricks'
schemaHints analog), with provenance, and reload reproduces it deterministically
instead of blindly re-sniffing the file.

Hermetic: an isolated storage root; the connector is rebuilt fresh (as it is
per-request in the app) to exercise the reload path.
"""
from __future__ import annotations

import json

import pytest

from aughor.connectors.file.local_upload import LocalUploadConnection, _is_pinnable_type
from aughor.platform import vending


@pytest.fixture(autouse=True)
def _isolate_uploads(tmp_path, monkeypatch):
    monkeypatch.setattr(vending, "STORAGE_ROOT", tmp_path / "uploads")


def _conn():
    return LocalUploadConnection(connection_id="ws")


def _coltype(c, schema, table, col):
    rows = c._duckdb.execute(f'DESCRIBE "{schema}"."{table}"').fetchall()
    return {r[0]: str(r[1]) for r in rows}[col]


def _sidecar(c, schema, filename):
    return c._upload_dir / schema / f"{filename}{'.import.json'}"


def test_ingest_pins_full_contract_and_provenance(tmp_path):
    src = tmp_path / "sales.csv"
    src.write_text("sku,price,qty\nA,1.5,3\nB,2.0,4\n")
    c = _conn()
    c.ingest_file(src, table_name="sales", schema="main")

    cfg = json.loads(_sidecar(c, "main", "sales.csv").read_text())
    # The whole table's effective types are pinned — not just overrides.
    assert set(cfg["schema_contract"]) == {"sku", "price", "qty"}
    assert cfg["schema_contract"]["sku"] == "VARCHAR"
    assert cfg["schema_contract"]["price"] in ("DOUBLE", "FLOAT", "DECIMAL")
    assert cfg["schema_contract"]["qty"] == "BIGINT"
    # Provenance recorded.
    assert cfg["created_by"] == "upload"
    assert cfg["source_file"] == "sales.csv"
    assert cfg["format"] == "csv"
    assert cfg["created_at"]  # ISO timestamp present

    # …and surfaced through list_files (→ ontology / Hub).
    lf = {f["table_name"]: f for f in c.list_files()}["sales"]
    assert lf["created_by"] == "upload"
    assert lf["schema_contract"]["qty"] == "BIGINT"


def test_reload_reproduces_pinned_types_immune_to_resniff(tmp_path):
    """The determinism proof: the contract — not a fresh re-sniff — drives reload."""
    src = tmp_path / "nums.csv"
    src.write_text("id,amount\n1,10\n2,20\n3,30\n")
    c1 = _conn()
    c1.ingest_file(src, table_name="nums", schema="main")
    assert _coltype(c1, "main", "nums", "amount") == "BIGINT"

    # Pin `amount` as text in the contract — standing in for a curated decision or
    # a DuckDB version that would otherwise re-sniff it differently.
    sc = _sidecar(c1, "main", "nums.csv")
    cfg = json.loads(sc.read_text())
    assert set(cfg["schema_contract"]) == {"id", "amount"}
    cfg["schema_contract"]["amount"] = "VARCHAR"
    sc.write_text(json.dumps(cfg))

    # A fresh connector reloads from disk and honours the pinned contract.
    c2 = _conn()
    assert _coltype(c2, "main", "nums", "amount") == "VARCHAR"
    assert _coltype(c2, "main", "nums", "id") == "BIGINT"


def test_reload_falls_back_when_no_contract(tmp_path):
    """A pre-R2 sidecar (no schema_contract) still loads by re-sniffing."""
    src = tmp_path / "old.csv"
    src.write_text("a,b\n1,x\n2,y\n")
    c1 = _conn()
    c1.ingest_file(src, table_name="old", schema="main")

    sc = _sidecar(c1, "main", "old.csv")
    sc.write_text(json.dumps({"table_name": "old", "schema": "main", "column_types": {}}))

    c2 = _conn()
    assert _coltype(c2, "main", "old", "a") == "BIGINT"
    assert _coltype(c2, "main", "old", "b") == "VARCHAR"


def test_user_override_applies_and_is_captured_in_contract(tmp_path):
    src = tmp_path / "ov.csv"
    src.write_text("code,n\n7,1\n42,2\n")
    c = _conn()
    c.ingest_file(src, table_name="ov", schema="main", column_types={"code": "VARCHAR"})
    assert _coltype(c, "main", "ov", "code") == "VARCHAR"

    cfg = json.loads(_sidecar(c, "main", "ov.csv").read_text())
    assert cfg["schema_contract"]["code"] == "VARCHAR"  # override folded into the pin

    # …and the override survives reload via the contract.
    c2 = _conn()
    assert _coltype(c2, "main", "ov", "code") == "VARCHAR"


@pytest.mark.parametrize("t,ok", [
    ("BIGINT", True),
    ("VARCHAR", True),
    ("DOUBLE", True),
    ("DECIMAL(18,3)", True),
    ("TIMESTAMP", True),
    ("TIMESTAMP WITH TIME ZONE", True),
    ("STRUCT(a INTEGER)", False),
    ("INTEGER[]", False),
    ("MAP(VARCHAR, INTEGER)", False),
    ("VARCHAR; DROP TABLE t", False),
    ("FOO", False),
    ("", False),
])
def test_is_pinnable_type_allowlist(t, ok):
    assert _is_pinnable_type(t) is ok
