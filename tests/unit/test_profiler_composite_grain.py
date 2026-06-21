"""Profiler composite-PK detection (ROADMAP infra follow-up).

The profiler verified only SINGLE-column grains, so a fact keyed by a PAIR (order_items at
(order_id, order_item_id), where order_item_id is a 1..N line number) got no verified grain
— the planner couldn't tell its true grain or that the line-number key is not a measure.
build_table_profile now probes key-like candidate PAIRS and records a proven composite grain
in `grain_columns`, surfaced in the data portrait. See aughor/tools/profiler.py.
"""
from pathlib import Path

import duckdb

from aughor.db.connection import DuckDBConnection
from aughor.tools.profiler import build_table_profile, TableProfile


def _conn():
    c = DuckDBConnection.__new__(DuckDBConnection)
    c._path = Path(":memory:")
    c._conn = duckdb.connect(":memory:")
    c._connection_id = "test"
    c._schema_name = None
    c._conn.execute("CREATE TABLE order_items (order_id INT, order_item_id INT, amount DOUBLE)")
    # 6 rows; NO single column is unique, but (order_id, order_item_id) is the PK.
    c._conn.execute(
        "INSERT INTO order_items VALUES "
        "(1,1,10),(1,2,20),(2,1,30),(3,1,40),(3,2,50),(3,3,60)"
    )
    return c


_COLS = [("order_id", "INTEGER"), ("order_item_id", "INTEGER"), ("amount", "DOUBLE")]


def test_composite_grain_detected_when_no_single_pk():
    tp = build_table_profile(_conn(), "order_items", _COLS, fk_cols={"order_id"})
    assert tp.grain_columns is not None
    assert set(tp.grain_columns) == {"order_id", "order_item_id"}   # proven composite PK
    assert tp.grain_verified is False   # no SINGLE column is unique → single-col grain unproven


def test_single_pk_table_gets_no_composite():
    c = DuckDBConnection.__new__(DuckDBConnection)
    c._path = Path(":memory:")
    c._conn = duckdb.connect(":memory:")
    c._connection_id = "test"
    c._schema_name = None
    c._conn.execute("CREATE TABLE orders (order_id INT, amount DOUBLE)")
    c._conn.execute("INSERT INTO orders VALUES (1,10),(2,20),(3,30)")
    tp = build_table_profile(c, "orders", [("order_id", "INTEGER"), ("amount", "DOUBLE")], fk_cols=set())
    assert tp.grain_verified is True and tp.grain_column == "order_id"
    assert tp.grain_columns is None   # single PK found → no composite probe needed


def test_composite_grain_roundtrips_through_dict():
    tp = TableProfile(table="t", row_count=6, grain_columns=["order_id", "order_item_id"])
    back = TableProfile.from_dict(tp.to_dict())
    assert back.grain_columns == ["order_id", "order_item_id"]
