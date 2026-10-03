"""DE-5's hygiene (ROADMAP §3.51; the dbx study's finding 10) — an upload keeps leading zeros
and oversized integers as text.

Measured before building (DuckDB 1.5.2): the CSV sniffer typed a 23-digit id column as DOUBLE
before `_suggest_type` ever saw it, so two distinct ids both arrived as 1.2345678901234568e+22
— the loss is at the READER, and no cast after it can undo it. Leading zeros survive the
sniffer for `02134` (VARCHAR) but not for `-00042` (BIGINT -42), and the suggester then offered
BIGINT for the VARCHAR one, which accepting would turn into 2134.

Hermetic: an isolated storage root; the connector is rebuilt fresh to exercise the reload path,
as `test_upload_schema_contract.py` does.
"""
from __future__ import annotations

import json

import duckdb
import pytest

from aughor.connectors.file.local_upload import (
    LocalUploadConnection,
    text_only_columns,
    with_text_columns,
)
from aughor.control_plane import vending

BIG_A = "12345678901234567890123"
BIG_B = "12345678901234567890124"


@pytest.fixture(autouse=True)
def _isolate_uploads(tmp_path, monkeypatch):
    monkeypatch.setattr(vending, "STORAGE_ROOT", tmp_path / "uploads")


def _conn():
    return LocalUploadConnection(connection_id="ws")


def _csv(tmp_path, name="ids.csv"):
    src = tmp_path / name
    src.write_text(
        "zip,big_id,n,price,neg,label\n"
        f"02134,{BIG_A},7,1.5,-00042,x\n"
        f"10001,{BIG_B},8,2.25,-7,y\n"
    )
    return src


def _by_name(analysis):
    return {c["name"]: c for c in analysis["columns"]}


# ── the premise, re-measured where the test runs ─────────────────────────────────

def test_premise_the_sniffer_loses_the_digits_at_the_reader(tmp_path):
    """Without the fix the reader itself types the id column DOUBLE — this is what the wave
    stands on, measured on the engine the test runs against."""
    src = _csv(tmp_path)
    con = duckdb.connect()
    types = {r[0]: str(r[1]) for r in con.execute(
        f"DESCRIBE SELECT * FROM read_csv_auto('{src.as_posix()}')").fetchall()}
    assert types["big_id"] == "DOUBLE"
    assert types["neg"] == "BIGINT"
    assert types["zip"] == "VARCHAR"
    a, b = [r[0] for r in con.execute(
        f"SELECT big_id FROM read_csv_auto('{src.as_posix()}')").fetchall()]
    assert a == b, "two distinct 23-digit ids collapse into one DOUBLE"
    assert con.execute("SELECT try_cast('02134' AS BIGINT)").fetchone()[0] == 2134


# ── the reader expression ────────────────────────────────────────────────────────

def test_with_text_columns_adds_the_readers_own_types_option_and_quotes_names():
    out = with_text_columns("read_csv_auto('/f.csv')", ["it's", "big id"])
    assert out == "read_csv_auto('/f.csv', types={'big id':'VARCHAR', 'it''s':'VARCHAR'})"
    # The encoding fallback's spelling is a CSV reader too.
    assert with_text_columns("read_csv('/f.csv', encoding='latin-1')", ["a"]).endswith(
        ", types={'a':'VARCHAR'})")
    # Not a CSV, or nothing to keep: unchanged.
    assert with_text_columns("read_parquet('/f.parquet')", ["a"]) == "read_parquet('/f.parquet')"
    assert with_text_columns("read_csv_auto('/f.csv')", []) == "read_csv_auto('/f.csv')"


def test_text_only_columns_names_the_column_and_the_reason(tmp_path):
    src = _csv(tmp_path)
    con = duckdb.connect()
    kept = text_only_columns(con, f"read_csv_auto('{src.as_posix()}')")
    assert kept == {"big_id": "integers beyond BIGINT", "neg": "leading zeros"}


def test_a_real_double_column_with_one_oversized_integer_is_left_a_double(tmp_path):
    src = tmp_path / "mixed.csv"
    src.write_text(f"v\n1.5\n{BIG_A}\n")
    con = duckdb.connect()
    assert text_only_columns(con, f"read_csv_auto('{src.as_posix()}')") == {}


# ── analyze: what the import review is told ─────────────────────────────────────

def test_analyze_reads_the_mangled_columns_as_text_and_says_why(tmp_path):
    cols = _by_name(_conn().analyze_file(_csv(tmp_path)))
    assert cols["big_id"]["detected_type"] == "VARCHAR"
    assert cols["big_id"]["kept_as_text"] == "integers beyond BIGINT"
    assert cols["big_id"]["suggested_type"] is None, "never offered as DOUBLE"
    assert cols["neg"]["detected_type"] == "VARCHAR"
    assert cols["neg"]["kept_as_text"] == "leading zeros"
    assert cols["neg"]["suggested_type"] is None
    # The sniffer kept the zip as text on its own; the suggester no longer offers BIGINT for it.
    assert cols["zip"]["detected_type"] == "VARCHAR"
    assert cols["zip"]["kept_as_text"] is None
    assert cols["zip"]["suggested_type"] is None
    # Ordinary numbers are still numbers.
    assert cols["n"]["detected_type"] == "BIGINT"
    assert cols["price"]["detected_type"] == "DOUBLE"
    assert cols["label"]["kept_as_text"] is None


def test_analyze_preview_shows_every_digit(tmp_path):
    a = _conn().analyze_file(_csv(tmp_path))
    idx = a["preview"]["columns"].index("big_id")
    assert [r[idx] for r in a["preview"]["rows"]] == [BIG_A, BIG_B]


# ── the suggester on text the sniffer left as text ───────────────────────────────

def test_suggester_declines_leading_zeros_and_overflow_but_still_tightens_the_rest(tmp_path):
    src = tmp_path / "text.csv"
    src.write_text(
        "ids,zip,big,rating,flag\n"
        f"12,02134,{BIG_A},4.5,true\n"
        f"7,10001,{BIG_B},3,false\n"
    )
    con = duckdb.connect()
    reader = f"read_csv_auto('{src.as_posix()}', all_varchar=true)"
    suggest = LocalUploadConnection._suggest_type
    assert suggest(con, reader, "ids") == "BIGINT"
    assert suggest(con, reader, "rating") == "DOUBLE"
    assert suggest(con, reader, "flag") == "BOOLEAN"
    assert suggest(con, reader, "zip") is None
    assert suggest(con, reader, "big") is None


# ── ingest and reload: the digits survive the round trip ─────────────────────────

def test_ingest_keeps_the_digits_and_pins_text_and_reload_reproduces_it(tmp_path):
    c = _conn()
    c.ingest_file(_csv(tmp_path), table_name="ids", schema="main")
    rows = c._duckdb.execute('SELECT big_id, neg, zip, n FROM "main"."ids" ORDER BY n').fetchall()
    assert rows == [(BIG_A, "-00042", "02134", 7), (BIG_B, "-7", "10001", 8)]
    cfg = json.loads((c._upload_dir / "main" / "ids.csv.import.json").read_text())
    assert cfg["schema_contract"]["big_id"] == "VARCHAR"
    assert cfg["schema_contract"]["neg"] == "VARCHAR"
    assert cfg["schema_contract"]["n"] == "BIGINT"

    # A fresh connector reloads from the pinned contract: the VARCHAR pin is read as the
    # file's text, not as the sniffed DOUBLE cast back to a string.
    c2 = _conn()
    rows2 = c2._duckdb.execute('SELECT big_id, neg FROM "main"."ids" ORDER BY n').fetchall()
    assert rows2 == [(BIG_A, "-00042"), (BIG_B, "-7")]


def test_a_persons_override_to_a_number_is_still_their_call(tmp_path):
    c = _conn()
    c.ingest_file(_csv(tmp_path), table_name="ids", schema="main", column_types={"zip": "BIGINT"})
    types = {r[0]: str(r[1]) for r in c._duckdb.execute('DESCRIBE "main"."ids"').fetchall()}
    assert types["zip"] == "BIGINT"
    assert [r[0] for r in c._duckdb.execute('SELECT zip FROM "main"."ids" ORDER BY n').fetchall()] == [2134, 10001]
    # …and the columns they did not touch are still protected.
    assert types["big_id"] == "VARCHAR"


def test_a_file_with_nothing_to_protect_is_read_exactly_as_before(tmp_path):
    src = tmp_path / "sales.csv"
    src.write_text("sku,price,qty\nA,1.5,3\nB,2.0,4\n")
    cols = _by_name(_conn().analyze_file(src))
    assert {n: c["detected_type"] for n, c in cols.items()} == {"sku": "VARCHAR", "price": "DOUBLE", "qty": "BIGINT"}
    assert all(c["kept_as_text"] is None for c in cols.values())
