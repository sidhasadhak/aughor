"""Native snapshot-pinned receipts on a DuckLake-backed connection — the EXACT half: a
finding gets a real ``dl:<catalog>:<id>`` version and re-validate PROVES correct-as-computed
vs mis-derived by reproducing the SQL ``AT (VERSION => n)``. Skipped where the DuckLake
extension can't load (e.g. offline CI)."""
from __future__ import annotations

import duckdb
import pytest

from aughor.db import snapshot as snap
from aughor.explorer.grounding import numeric_cells_block
from aughor.explorer.revalidate import revalidate_finding

SQL = "SELECT SUM(amt) AS total FROM orders"


def _ducklake_available() -> bool:
    try:
        c = duckdb.connect(":memory:")
        c.execute("INSTALL ducklake")
        c.execute("LOAD ducklake")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _ducklake_available(), reason="ducklake extension unavailable")


def _conn(tmp_path):
    from aughor.db.ducklake import DuckLakeConnection
    c = DuckLakeConnection(str(tmp_path / "cat.ducklake"), connection_id="dl")
    c._conn.execute("CREATE TABLE orders(id INT, amt DOUBLE)")
    c._conn.execute("INSERT INTO orders VALUES (1,10),(2,20)")   # snapshot here: total = 30
    return c


def test_native_version_is_exact_and_as_of_supported(tmp_path):
    c = _conn(tmp_path)
    v = snap.data_version(c, ["orders"])
    assert v and v.startswith("dl:lake:")                       # an exact snapshot id, not a fingerprint
    assert snap.native_version_id(v) is not None
    assert snap.as_of_supported(c) is True


def test_execute_as_of_reproduces_a_past_snapshot(tmp_path):
    c = _conn(tmp_path)
    vid = snap.native_version_id(snap.data_version(c, ["orders"]))
    c._conn.execute("INSERT INTO orders VALUES (3,30)")          # data moves: total → 60
    assert float(c.execute("h", SQL).rows[0][0]) == 60.0               # live
    assert float(snap.execute_as_of(c, SQL, vid).rows[0][0]) == 30.0   # time-travel reproduces old total


def test_revalidate_proves_correct_when_finding_reproduces(tmp_path):
    c = _conn(tmp_path)
    pin = snap.data_version(c, ["orders"])
    stored = numeric_cells_block(c.execute("h", SQL).rows)       # cells AT the pin (total = 30)
    c._conn.execute("INSERT INTO orders VALUES (3,30)")          # the world moves on
    out = revalidate_finding(
        {"sql": SQL, "finding": "Total is 30", "result_cells": stored,
         "data_version": pin, "generated_at": "2026-06-01"}, c)
    assert out["cells_changed"] is True and out["reproduced"] is True
    assert "CONFIRMED correct" in out["interpretation"]


def test_revalidate_proves_misderivation_when_not_reproducible(tmp_path):
    c = _conn(tmp_path)
    pin = snap.data_version(c, ["orders"])                       # data does NOT move after this
    out = revalidate_finding(
        {"sql": SQL, "finding": "Total is 999", "result_cells": "total: 999.0",
         "data_version": pin, "generated_at": "x"}, c)
    assert out["reproduced"] is False                            # 999 never existed at the pinned snapshot
    assert "does NOT reproduce" in out["interpretation"]
