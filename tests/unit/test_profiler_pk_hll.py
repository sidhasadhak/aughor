"""Profiler PK detection on LARGE tables (small-polish follow-up).

A big table with a catalog-stat miss used to skip COUNT(DISTINCT) entirely (too costly),
so its single-column primary key went undetected/unverified. build_table_profile now
verifies uniqueness with a HyperLogLog (approx_count_distinct) on DuckDB — one cheap pass —
using a RATIO test (a PK's estimate ≈ row_count; a non-unique key's is far smaller), which is
robust to HLL's magnitude noise. See aughor/tools/profiler.py.
"""
from pathlib import Path

import duckdb
import pytest

import aughor.tools.profiler as profiler
from aughor.db.connection import DuckDBConnection
from aughor.tools.profiler import build_table_profile


def _conn(ddl: str, insert: str):
    c = DuckDBConnection.__new__(DuckDBConnection)
    c._path = Path(":memory:")
    c._conn = duckdb.connect(":memory:")
    c._connection_id = "test"
    c._schema_name = None
    c._conn.execute(ddl)
    c._conn.execute(insert)
    return c


@pytest.fixture(autouse=True)
def _small_threshold(monkeypatch):
    # force the "large table" branch without generating 500k rows
    monkeypatch.setattr(profiler, "_LARGE_TABLE_THRESHOLD", 100)


def test_large_table_pk_detected_via_hll():
    conn = _conn(
        "CREATE TABLE big_orders (order_id BIGINT, customer_id BIGINT, amount DOUBLE)",
        "INSERT INTO big_orders SELECT i, i % 50, i * 1.0 FROM range(2000) t(i)",
    )
    # fast_stats EMPTY → catalog miss → the >threshold HLL path (2000 rows > 100)
    tp = build_table_profile(conn, "big_orders", [("order_id", "BIGINT"),
                             ("customer_id", "BIGINT"), ("amount", "DOUBLE")],
                             fk_cols=set(), fast_stats={}, row_count_hint=2000)
    assert tp.grain_column == "order_id" and tp.grain_verified is True


def test_large_table_non_unique_key_not_falsely_verified():
    # only a non-unique key-ish column → must NOT be verified as a PK (ratio test rejects it)
    conn = _conn(
        "CREATE TABLE events (customer_id BIGINT, amount DOUBLE)",
        "INSERT INTO events SELECT i % 50, i * 1.0 FROM range(2000) t(i)",
    )
    tp = build_table_profile(conn, "events", [("customer_id", "BIGINT"), ("amount", "DOUBLE")],
                             fk_cols=set(), fast_stats={}, row_count_hint=2000)
    assert tp.grain_verified is False
