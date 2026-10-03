"""DE-5e (ROADMAP §3.51) — what a cell carries to the grid, and what a column is called there.

Measured first: a DuckDB STRUCT reached the grid as an object (rendered `[object Object]`), bytes as
Python's `b'…'` repr, a Postgres BYTEA as `<memory at 0x…>`; and every warehouse connector named a
GEOGRAPHY, JSON, VARIANT, STRUCT or BYTES column "VARCHAR" (`connectors/base.py stage_type`), so the web
could not tell a shape from a string by its type. These pin the fixes at the cause: a cell is a scalar —
a document is its JSON text, bytes are hex — and a kind keeps its own name.
"""
from __future__ import annotations

import datetime as dt
import decimal
import json

import duckdb
import pytest
from fastapi.testclient import TestClient

from aughor.api import app
from aughor.db import registry

client = TestClient(app)


# ── 1 · a cell is a scalar, and bytes are hex ────────────────────────────────────────────────────

def test_a_structured_value_is_its_json_text_and_bytes_are_hex():
    from aughor.routers.query import _json_cell
    assert _json_cell(b"abc") == "616263"
    assert _json_cell(bytearray(b"\x01\x02")) == "0102"
    assert _json_cell(memoryview(b"\xff")) == "ff"
    assert _json_cell({"x": 1, "y": "two"}) == '{"x": 1, "y": "two"}'
    assert _json_cell([1, 2, 3]) == "[1, 2, 3]"
    # The conversions a cell gets, one level down: a Decimal is a number, a date is ISO text, bytes are hex.
    nested = json.loads(_json_cell({"amount": decimal.Decimal("1.50"), "when": dt.date(2026, 10, 3),
                                    "raw": b"\x00\x01", "tags": ("a", None)}))
    assert nested == {"amount": 1.5, "when": "2026-10-03", "raw": "0001", "tags": ["a", None]}
    assert _json_cell("{\"kept\": true}") == "{\"kept\": true}", "JSON text stays text"
    assert _json_cell(None) is None and _json_cell(True) is True and _json_cell(7) == 7


@pytest.fixture()
def duck(tmp_path):
    db = tmp_path / "de5e.duckdb"
    c = duckdb.connect(str(db))
    c.execute("""
        CREATE TABLE t AS SELECT
            {'x': 1, 'y': 'two'} AS s,
            [1, 2, 3] AS l,
            MAP {'k': 1} AS m,
            '{"a": [1, 2]}'::JSON AS j,
            'abc'::BLOB AS b,
            'POINT (4.9 52.37)' AS wkt
    """)
    c.close()
    cid = registry.add_connection("de5e", "duckdb", str(db))
    yield cid
    registry.delete_connection(cid)


def test_the_typed_run_hands_the_grid_scalars_with_the_engines_own_type_names(duck):
    r = client.post("/query/run", json={"conn_id": duck, "sql": "SELECT * FROM t", "format": "typed",
                                        "source": "query_workbench"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["format"] == "typed" and body["error"] is None
    row = body["rows"][0]
    assert all(v is None or isinstance(v, (str, int, float, bool)) for v in row), "every cell a scalar"
    cells = dict(zip(body["columns"], row))
    assert json.loads(cells["s"]) == {"x": 1, "y": "two"}
    assert json.loads(cells["l"]) == [1, 2, 3]
    assert json.loads(cells["m"]) == {"k": 1}
    assert json.loads(cells["j"]) == {"a": [1, 2]}
    assert cells["b"] == "616263"
    assert cells["wkt"] == "POINT (4.9 52.37)"
    types = {c["name"]: c["type"] for c in body["columns_typed"]}
    assert types["s"].startswith("STRUCT") and types["l"] == "INTEGER[]" and types["m"].startswith("MAP")
    assert types["j"] == "JSON" and types["b"] == "BLOB"


# ── 2 · a kind keeps its own name ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind, named", [
    ("GEOGRAPHY", "GEOGRAPHY"), ("GEOMETRY", "GEOMETRY"), ("JSON", "JSON"), ("VARIANT", "VARIANT"),
    ("OBJECT", "OBJECT"), ("ARRAY", "ARRAY"), ("RECORD", "RECORD"), ("STRUCT", "STRUCT"), ("BYTES", "BYTES"),
    ("BLOB", "BLOB"), ("BINARY", "BINARY"), ("varbinary", "VARBINARY"), ("array(integer)", "ARRAY(INTEGER)"),
    ("row(a integer, b varchar)", "ROW(A INTEGER, B VARCHAR)"), ("STRUCT<a INT64>", "STRUCT<A INT64>"),
    ("LONG_BLOB", "LONG_BLOB"),
    # …and the stage's own names stay the stage's.
    ("INT64", "BIGINT"), ("FLOAT64", "DOUBLE"), ("BOOL", "BOOLEAN"), ("DATETIME", "TIMESTAMP"), ("STRING", "VARCHAR"),
    ("", ""),
])
def test_a_document_shape_or_bytes_kind_keeps_its_name(kind, named):
    from aughor.connectors.base import stage_type
    assert stage_type(kind) == named


def test_the_stage_still_types_an_all_null_column_of_a_kept_kind_as_text():
    pa = pytest.importorskip("pyarrow")
    from aughor.semantic.cross_source import _empty_type
    for kind in ("GEOGRAPHY", "JSON", "STRUCT<A INT64>", "BYTES"):
        assert _empty_type(kind) == pa.string(), kind
