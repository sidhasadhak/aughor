"""Wave K3 — the edits-as-overlay ledger.

Human annotations/corrections merged onto query results at READ time — never mutating source,
surviving refreshes (the store is independent of the connection cache), with a machine edit never
overriding a human one. Hermetic: the overlay ledger DB is the conftest temp path
(AUGHOR_OVERLAY_LEDGER_DB), so the suite never touches live data/.
"""
from __future__ import annotations

import pytest

from aughor.kinetic import overlay as OV
from aughor.kinetic.overlay import OverlayEdit


class _Result:
    """A minimal QueryResult-shaped object for the merge (columns/rows/sql/caveats/annotations)."""
    def __init__(self, columns, rows, sql=""):
        self.columns = columns
        self.rows = rows
        self.sql = sql
        self.caveats: list = []
        self.annotations: list = []


@pytest.fixture(autouse=True)
def _clean_conn():
    # Each test uses a fresh connection id so the shared temp DB never leaks rows between tests.
    OV.purge_connections(["conn-k3"])
    yield
    OV.purge_connections(["conn-k3"])


def _cell_edit(**kw) -> OverlayEdit:
    base = dict(connection_id="conn-k3", table="orders", column="status",
                key_column="order_id", row_key="8821", kind="annotation",
                body="known test order — exclude from ops metrics", source="user")
    base.update(kw)
    return OverlayEdit(**base)


# ── store: write, authority, list, purge ─────────────────────────────────────────

def test_save_and_read_back():
    OV.save_edit(_cell_edit())
    edits = OV.edits_for_connection("conn-k3")
    assert len(edits) == 1
    assert edits[0].target() == "orders.status#order_id=8821"
    assert edits[0].body.startswith("known test order")


def test_reedit_same_target_is_idempotent():
    OV.save_edit(_cell_edit(body="v1"))
    OV.save_edit(_cell_edit(body="v2"))
    edits = OV.edits_for_connection("conn-k3")
    assert len(edits) == 1 and edits[0].body == "v2"   # same natural key ⇒ one row, updated


def test_machine_never_overrides_human():
    OV.save_edit(_cell_edit(source="user", body="human note"))
    OV.save_edit(_cell_edit(source="machine", body="machine guess"))   # lower authority
    edits = OV.edits_for_connection("conn-k3")
    assert len(edits) == 1 and edits[0].body == "human note" and edits[0].source == "user"


def test_verified_overrides_user():
    OV.save_edit(_cell_edit(source="user", body="user note"))
    OV.save_edit(_cell_edit(source="verified", body="verified correction"))
    assert OV.edits_for_connection("conn-k3")[0].body == "verified correction"


def test_purge_removes_only_that_connection():
    OV.save_edit(_cell_edit())
    OV.save_edit(_cell_edit(connection_id="conn-other"))
    try:
        assert OV.purge_connections(["conn-k3"]) == 1
        assert OV.edits_for_connection("conn-k3") == []
        assert len(OV.edits_for_connection("conn-other")) == 1
    finally:
        OV.purge_connections(["conn-other"])


def test_edits_scoped_by_connection():
    OV.save_edit(_cell_edit())
    assert OV.edits_for_connection("nope") == []


# ── read-time merge ──────────────────────────────────────────────────────────────

def test_cell_annotation_merges_onto_the_right_row():
    OV.save_edit(_cell_edit())
    res = _Result(columns=["order_id", "status"],
                  rows=[["1000", "shipped"], ["8821", "returned"], ["1002", "shipped"]])
    OV.apply_overlay(res, "conn-k3")
    assert len(res.annotations) == 1
    ann = res.annotations[0]
    assert ann["row_index"] == 1 and ann["column"] == "status"
    assert ann["body"].startswith("known test order") and ann["source"] == "user"


def test_cell_annotation_skipped_when_key_column_absent():
    OV.save_edit(_cell_edit())
    res = _Result(columns=["status"], rows=[["returned"]])   # no order_id to identify the row
    OV.apply_overlay(res, "conn-k3")
    assert res.annotations == []


def test_column_annotation_merges_when_column_present():
    OV.save_edit(_cell_edit(row_key="", key_column="", column="refund_eur",
                            body="refund_eur has known data-entry errors before 2024"))
    res = _Result(columns=["category", "refund_eur"], rows=[["bags", "100"]])
    OV.apply_overlay(res, "conn-k3")
    assert len(res.annotations) == 1 and res.annotations[0]["row_index"] is None
    assert res.annotations[0]["column"] == "refund_eur"


def test_table_annotation_becomes_a_caveat_when_sql_references_it():
    OV.save_edit(_cell_edit(column="", row_key="", key_column="",
                            body="orders backfilled from a legacy system in 2023"))
    res = _Result(columns=["n"], rows=[["5"]], sql="SELECT COUNT(*) AS n FROM orders")
    OV.apply_overlay(res, "conn-k3")
    assert any("orders backfilled" in c for c in res.caveats)
    res2 = _Result(columns=["n"], rows=[["5"]], sql="SELECT COUNT(*) AS n FROM customers")
    OV.apply_overlay(res2, "conn-k3")
    assert res2.caveats == []          # unrelated table ⇒ no caveat


def test_merge_is_noop_without_edits():
    res = _Result(columns=["a"], rows=[["1"]])
    OV.apply_overlay(res, "conn-k3")
    assert res.annotations == [] and res.caveats == []


def test_merge_survives_a_rebuilt_result():
    # The point of the ledger: an edit written once re-applies on a FRESH result (post-refresh).
    OV.save_edit(_cell_edit())
    for _ in range(2):                 # two independent "reads" of freshly-built results
        res = _Result(columns=["order_id", "status"], rows=[["8821", "returned"]])
        OV.apply_overlay(res, "conn-k3")
        assert len(res.annotations) == 1


def test_merge_never_raises_on_bad_result():
    OV.save_edit(_cell_edit())
    broken = _Result(columns=["order_id", "status"], rows=[None, ["8821"]])  # ragged/None rows
    OV.apply_overlay(broken, "conn-k3")   # must not raise
    assert isinstance(broken.annotations, list)


# ── wiring: the merge rides a real execute_guarded result ────────────────────────

def test_end_to_end_through_execute_guarded(monkeypatch):
    # Locks the WIRING (the org-stamp bug the demo caught would have failed here): a saved edit
    # merges onto a REAL execute_guarded result when the flag is on, and off = byte-identical.
    import duckdb
    from pathlib import Path
    from aughor.db.connection import DuckDBConnection
    from aughor.sql.executor import execute_guarded
    import aughor.kernel.flags as F

    conn = DuckDBConnection.__new__(DuckDBConnection)
    conn._path = Path(":memory:")
    conn._conn = duckdb.connect(":memory:")
    conn._connection_id = "conn-k3"
    conn._schema_name = None
    conn._conn.execute("CREATE TABLE orders(order_id VARCHAR, status VARCHAR)")
    conn._conn.execute("INSERT INTO orders VALUES ('1000','shipped'),('8821','returned')")
    OV.save_edit(_cell_edit())

    monkeypatch.setenv("AUGHOR_KINETIC_OVERLAY", "1")
    F.clear_flag("kinetic.overlay")
    r = execute_guarded(conn, "SELECT order_id, status FROM orders", query_id="p1")
    assert len(r.annotations) == 1 and r.annotations[0]["row_index"] == 1

    monkeypatch.setenv("AUGHOR_KINETIC_OVERLAY", "0")
    F.clear_flag("kinetic.overlay")
    r2 = execute_guarded(conn, "SELECT order_id, status FROM orders", query_id="p2")
    assert r2.annotations == []          # flag off ⇒ byte-identical


# ── the K2 → K3 seam: an annotate action writes an overlay edit ──────────────────

def test_annotate_action_writes_an_edit(monkeypatch):
    monkeypatch.delenv("AUGHOR_ACTION_APPROVAL", raising=False)
    from aughor.kinetic.executor import execute_kinetic_action
    from aughor.ontology.models import ActionParameter, KineticAction

    action = KineticAction(
        id="flag_outlier", kind="annotate", risk="low",
        params=[ActionParameter(name="table"), ActionParameter(name="column"),
                ActionParameter(name="key_column"), ActionParameter(name="row_key"),
                ActionParameter(name="body")],
        submission_criteria=[])
    r = execute_kinetic_action(action, {
        "table": "orders", "column": "status", "key_column": "order_id",
        "row_key": "8821", "body": "known test order"}, scope="conn-k3")

    assert r.ok and r.status == "executed"
    assert r.outcome["annotation"] == "orders.status#order_id=8821"
    edits = OV.edits_for_connection("conn-k3")
    assert len(edits) == 1 and edits[0].body == "known test order" and edits[0].source == "user"
