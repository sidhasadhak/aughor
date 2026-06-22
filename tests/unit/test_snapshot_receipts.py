"""Snapshot-pinned receipts (the DuckLake +1, spike) — a data-version token pins a finding
to the data it ran against, so re-validate can tell a MOVED dataset apart from a MIS-DERIVED
finding. Hermetic: real DuckDB files, no DuckLake / LLM."""
from __future__ import annotations

import tempfile
from pathlib import Path

import duckdb

from aughor.db import snapshot as snap
from aughor.db.connection import DuckDBConnection
from aughor.explorer.grounding import numeric_cells_block
from aughor.explorer.revalidate import revalidate_finding

SQL = "SELECT SUM(amt) AS total FROM shop_orders"


def _conn_with(insert_sql: str) -> DuckDBConnection:
    p = str(Path(tempfile.mkdtemp()) / "t.duckdb")
    w = duckdb.connect(p)
    w.execute("CREATE TABLE shop_orders(id INT, amt DOUBLE)")
    w.execute(insert_sql)
    w.close()
    return DuckDBConnection(p, connection_id="rv")


# ── the version token ─────────────────────────────────────────────────────────
def test_data_version_is_deterministic():
    c = _conn_with("INSERT INTO shop_orders VALUES (1,10),(2,20)")
    v = snap.data_version(c, ["shop_orders"])
    assert v and v.startswith("fp:")
    assert snap.data_version(c, ["shop_orders"]) == v          # same data → same token


def test_data_version_moves_when_rows_change():
    a = snap.data_version(_conn_with("INSERT INTO shop_orders VALUES (1,10),(2,20)"), ["shop_orders"])
    b = snap.data_version(_conn_with("INSERT INTO shop_orders VALUES (1,10),(2,20),(3,30)"), ["shop_orders"])
    assert a != b                                              # an extra row moves the version


def test_data_version_fail_open_on_missing_table():
    c = _conn_with("INSERT INTO shop_orders VALUES (1,10)")
    assert snap.data_version(c, ["does_not_exist"]) is None    # never raises


def test_flag_off_by_default(monkeypatch):
    monkeypatch.delenv("AUGHOR_SNAPSHOT_RECEIPTS", raising=False)
    assert snap.snapshot_receipts_enabled() is False


def test_as_of_unsupported_on_plain_duckdb():
    assert snap.as_of_supported(_conn_with("INSERT INTO shop_orders VALUES (1,10)")) is False


# ── re-validate disambiguation ─────────────────────────────────────────────────
def _dossier(*, data_version, stored_cells):
    return {"sql": SQL, "finding": "Total is 30", "result_cells": stored_cells,
            "data_version": data_version, "generated_at": "2026-06-01"}


def test_revalidate_stable_when_nothing_changed():
    c = _conn_with("INSERT INTO shop_orders VALUES (1,10),(2,20)")
    stored = numeric_cells_block(c.execute("h", SQL).rows)     # exactly what the SQL returns now
    out = revalidate_finding(_dossier(data_version=snap.data_version(c, ["shop_orders"]), stored_cells=stored), c)
    assert out["cells_changed"] is False and "stable" in out["interpretation"]


def test_revalidate_attributes_a_changed_number_to_moved_data():
    c = _conn_with("INSERT INTO shop_orders VALUES (1,10),(2,20)")
    # pinned to an OLD version (≠ current) + mismatched cells → the number moved BECAUSE data moved
    out = revalidate_finding(_dossier(data_version="fp:0000oldversion", stored_cells="total: 999"), c)
    assert out["cells_changed"] is True and out["data_moved"] is True
    assert "data has moved" in out["interpretation"]


def test_revalidate_flags_mis_derivation_when_data_did_not_move():
    c = _conn_with("INSERT INTO shop_orders VALUES (1,10),(2,20)")
    # pinned to the CURRENT version (data unchanged) but the stored number doesn't reproduce →
    # the finding was mis-derived / non-deterministic, NOT a data update
    out = revalidate_finding(_dossier(data_version=snap.data_version(c, ["shop_orders"]), stored_cells="total: 999"), c)
    assert out["cells_changed"] is True and out["data_moved"] is False
    assert "mis-derived" in out["interpretation"]


def test_revalidate_is_graceful_without_a_pin():
    c = _conn_with("INSERT INTO shop_orders VALUES (1,10)")
    out = revalidate_finding({"sql": SQL, "finding": "x", "result_cells": "total: 999"}, c)
    assert out["data_moved"] is None and "no data-version pin" in out["interpretation"]
