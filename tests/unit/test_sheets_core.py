"""Arc SH, SH-1 and SH-2 — sheets kept by Aughor, and the grid that edits them (ROADMAP §3.64).

Run against the real stores — the ledger, the edit layer and the projection — each pointed at a temporary path, so
what is proven is the path a person's typing takes. The two falsifiers are tests here:

- SH-1: the materialized table must equal a fresh rebuild from source plus changes (`projection.check`), after every
  kind of change, and after a long random sequence of them;
- SH-2: an edit made in the grid is what the next read of the same cell through the Sheets connection returns.
"""
from __future__ import annotations

import json
import random

import pytest


ORDERS = """order_id,customer_id,order_status,order_purchase_timestamp,order_estimated_delivery_date,zip,items,price
e481f51c,9ef432eb,delivered,2017-10-02 10:56:33,2017-10-18 00:00:00,01037,1,29.99
53cdb2fc,b0830fb4,delivered,2018-07-24 20:41:37,2018-08-13 00:00:00,13056,2,118.70
47770eb9,41ce2a54,shipped,2018-08-08 08:38:49,2018-09-04 00:00:00,04534,1,159.90
949d5b44,f88197465,canceled,2017-11-18 19:28:06,2017-12-15 00:00:00,89254,3,45.00
ad21c59c,8ab97904,delivered,2018-02-13 21:18:39,2018-02-26 00:00:00,13084,1,19.90
a4591c26,503740e9,shipped,2017-07-09 21:57:05,2017-08-01 00:00:00,08775,1,147.90
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("AUGHOR_SYSTEM_DB", str(tmp_path / "system.db"))
    from aughor.actions import overlay
    monkeypatch.setattr(overlay, "_DB_PATH", tmp_path / "overlay.db")
    from aughor.sheets import projection
    projection.reset()
    yield tmp_path
    projection.reset()


def _orders(env, name="Olist orders"):
    from aughor.sheets import files, service
    path = env / "olist_orders_dataset.csv"
    path.write_text(ORDERS)
    token = files.stage(path, path.name)
    return service.create_from_file(token, name=name, by="user:ana",
                                    chosen={"order_estimated_delivery_date": "date"})


def _cell(sheet, row, name):
    from aughor.sheets import projection
    c = sheet.column(name)
    return (projection.read_row(sheet, row) or {}).get(c.id)


def _same(sheet):
    from aughor.sheets import model, projection
    return projection.check(model.get(sheet.id))


# ── kinds ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_kinds_are_taken_only_where_every_value_reads_back(env):
    from aughor.sheets import files, imports
    path = env / "o.csv"
    path.write_text(ORDERS)
    cols = {c["name"]: c for c in imports.describe(files.staged(files.stage(path, "o.csv")))["columns"]}
    # a zip written with a leading zero is not the number it would become
    assert cols["zip"]["suggested"] == "text" and "number" not in cols["zip"]["offered"]
    assert cols["items"]["suggested"] == "number" and cols["items"]["integer"]
    assert cols["price"]["suggested"] == "money"
    assert cols["order_purchase_timestamp"]["suggested"] == "datetime"
    # every value midnight: a Date, said, so it is compared by day
    assert cols["order_estimated_delivery_date"]["suggested"] == "date"
    assert "midnight" in cols["order_estimated_delivery_date"]["note"]
    assert cols["order_status"]["suggested"] == "choice"


def test_a_kind_some_values_do_not_fit_is_refused_and_nothing_is_made(env):
    from aughor.sheets import files, model, service
    path = env / "o.csv"
    path.write_text(ORDERS)
    with pytest.raises(service.Refused, match="do not read as Number"):
        service.create_from_file(files.stage(path, "o.csv"), name="Bad", by="user:ana", chosen={"zip": "number"})
    assert model.list_sheets() == []


def test_typed_values_are_checked_against_their_kind(env):
    from aughor.sheets import service
    sheet = _orders(env)
    with pytest.raises(service.Refused, match="whole numbers"):
        service.set_cells(sheet, [{"row": 1, "column": "items", "value": "1.5"}], by="user:ana")
    with pytest.raises(service.Refused, match="dates"):
        service.set_cells(sheet, [{"row": 1, "column": "order_estimated_delivery_date", "value": "18/10/2017"}],
                          by="user:ana")
    with pytest.raises(service.Refused, match="to the cent"):
        service.set_cells(sheet, [{"row": 1, "column": "price", "value": "1.005"}], by="user:ana")


# ── SH-1: made, kept, rebuilt ────────────────────────────────────────────────────────────────────────────────────────

def test_a_file_becomes_a_sheet_whose_rows_name_their_file_row(env):
    from aughor.sheets import projection, service
    sheet = _orders(env)
    assert projection.count(sheet) == 6
    assert _cell(sheet, 1, "zip") == "01037"            # as written
    assert _cell(sheet, 2, "price") == "118.70"
    assert _cell(sheet, 1, "order_estimated_delivery_date") == "2017-10-18"
    story = service.cell_history(sheet, 3, "order_status")
    assert story["came_from"] == "imported from olist_orders_dataset.csv, row 3" and story["events"] == []
    assert _same(sheet)["same"]


def test_every_kind_of_change_leaves_the_table_equal_to_its_rebuild(env):
    from aughor.sheets import model, service
    sheet = _orders(env)
    service.set_cells(sheet, [{"row": 2, "column": "order_status", "value": "delivered"},
                              {"row": 3, "column": "price", "value": "160"}], by="user:ana")
    assert _same(sheet)["same"]
    added = service.add_row(sheet, {"order_id": "new1", "order_status": "created", "items": "4"}, by="user:ana")
    assert added["row"] == 7 and _same(sheet)["same"]
    service.remove_rows(sheet, [4], by="user:ana")
    # the oracle compares the table with a rebuild made by the same code, so a removal both forget is invisible to
    # it: the row is asserted gone directly
    assert _cell(sheet, 4, "order_id") is None and _same(sheet)["same"]
    sheet = service.add_column(model.get(sheet.id), name="Followed up", kind="yesno", by="user:ana")
    service.set_cells(sheet, [{"row": 1, "column": "Followed up", "value": "yes"}], by="user:ana")
    assert _same(model.get(sheet.id))["same"]
    sheet = service.update_column(model.get(sheet.id), "order_status", name="status", by="user:ana")
    assert _cell(sheet, 2, "status") == "delivered" and _same(sheet)["same"]


def test_a_long_random_sequence_of_changes_never_drifts_from_the_rebuild(env):
    """The oracle the Grist study proposed: any sequence of changes, applied a row at a time, equals a rebuild."""
    from aughor.sheets import model, service
    sheet = _orders(env)
    rng = random.Random(20261027)
    statuses = ["delivered", "shipped", "canceled", "invoiced", "processing"]
    for step in range(60):
        sheet = model.get(sheet.id)
        live = [r for r in range(1, 30) if _cell(sheet, r, "order_id") is not None]
        act = rng.choice(["set", "set", "set", "add", "remove", "undo", "redo"])
        try:
            if act == "set" and live:
                service.set_cells(sheet, [{"row": rng.choice(live), "column": rng.choice(["order_status", "price"]),
                                           "value": rng.choice(statuses) if rng.random() < .5 else None}],
                                  by="user:ana")
            elif act == "add":
                service.add_row(sheet, {"order_id": f"r{step}", "items": str(rng.randint(1, 9))}, by="user:ana")
            elif act == "remove" and len(live) > 2:
                service.remove_rows(sheet, [rng.choice(live)], by="user:ana")
            elif act == "undo":
                service.undo(sheet, by="user:ana")
            elif act == "redo":
                service.redo(sheet, by="user:ana")
        except service.Refused:
            continue                       # a refused value or "nothing to undo" changes nothing
        now = model.get(sheet.id)
        assert now is not None
        verdict = _same(now)
        assert verdict["same"], f"step {step} ({act}) drifted: {verdict}"


def test_a_restart_rebuilds_a_projection_in_doubt(env):
    from aughor.sheets import files, model, projection, service
    sheet = _orders(env)
    service.set_cells(sheet, [{"row": 1, "column": "price", "value": "10"}], by="user:ana")
    projection.reset()
    files.projection_path().unlink()                     # the projection is gone: missing is in doubt
    assert _cell(model.get(sheet.id), 1, "price") == "10.00"
    # a stamp that disagrees with the stores is in doubt too
    projection.reset()
    marks = files.root() / "projection.marks.json"
    marks.write_text(json.dumps({sheet.id: {"def": 0, "values": "x", "table": sheet.table}}))
    assert projection.reconcile.__name__ and _cell(model.get(sheet.id), 1, "price") == "10.00"


def test_a_removed_sheet_writes_its_tombstone_first_and_stays_removed(env, monkeypatch):
    from aughor.sheets import files, model, projection, service
    sheet = _orders(env)
    order = []
    real_save, real_drop = model.save, projection.drop
    monkeypatch.setattr(model, "save", lambda *a, **k: (order.append(("tombstone", k.get("state"))),
                                                         real_save(*a, **k))[1])
    monkeypatch.setattr(projection, "drop", lambda *a, **k: (order.append(("drop", None)), real_drop(*a, **k))[1])
    # the files fail to go: the tombstone still decides
    monkeypatch.setattr(files, "remove", lambda sheet_id: None)
    service.remove(sheet, by="user:ana")
    assert order[0] == ("tombstone", "archived") and order[1][0] == "drop"
    assert model.get(sheet.id) is None and model.list_sheets() == []
    projection.reset()                                   # a restart: the files are still there
    assert files.source_parquet(sheet.id).exists()
    assert sheet.table not in {r[0] for r in projection.cursor().execute(
        "SELECT table_name FROM duckdb_tables()").fetchall()}


# ── SH-2: the grid, read back through the Sheets connection ──────────────────────────────────────────────────────────

def test_an_edit_in_the_grid_is_what_the_next_read_through_the_connection_returns(env):
    """SH-2's falsifier: the chat reads the sheet through the Sheets connection; it must read what the grid wrote."""
    from aughor.sheets import service
    from aughor.sheets.connection import SheetsConnection
    sheet = _orders(env)
    service.set_cells(sheet, [{"row": 5, "column": "order_status", "value": "returned"}], by="user:ana")
    result = SheetsConnection().execute("t", f"SELECT order_status FROM {sheet.table} WHERE order_id = 'ad21c59c'")
    assert result.error is None, result.error
    assert result.rows == [["returned"]]


def test_a_stale_edit_is_refused_and_names_who_changed_it(env):
    from aughor.sheets import service
    sheet = _orders(env)
    first = service.set_cells(sheet, [{"row": 1, "column": "order_status", "value": "shipped", "version": 0}],
                              by="user:ana")
    assert first["cells"][0]["version"] == 1
    # SH-8: who changed which cell, by the name they sign in with — and that the change asked for was not made
    with pytest.raises(service.Conflict, match=r"^ana changed order_status in row 1 at \d\d:\d\d UTC, after you read it, "
                                               r"so your change was not made\. The grid now shows ana's value"):
        service.set_cells(sheet, [{"row": 1, "column": "order_status", "value": "canceled", "version": 0}],
                          by="user:bo")
    assert _cell(sheet, 1, "order_status") == "shipped"


def test_undo_and_redo_take_a_change_back_whole(env):
    from aughor.sheets import service
    sheet = _orders(env)
    added = service.add_row(sheet, {"order_id": "x1", "order_status": "created"}, by="user:ana")
    assert _cell(sheet, added["row"], "order_id") == "x1"
    service.undo(sheet, by="user:ana")
    assert _cell(sheet, added["row"], "order_id") is None          # the row and its values went together
    service.redo(sheet, by="user:ana")
    assert _cell(sheet, added["row"], "order_status") == "created"
    assert _same(sheet)["same"]


def test_undo_never_takes_back_someone_elses_change_over_yours(env):
    from aughor.sheets import service
    sheet = _orders(env)
    service.set_cells(sheet, [{"row": 1, "column": "order_status", "value": "shipped"}], by="user:ana")
    service.set_cells(sheet, [{"row": 1, "column": "order_status", "value": "canceled"}], by="user:bo")
    with pytest.raises(service.Refused, match=r"^bo changed order_status in row 1 .*since, so this cannot be undone"):
        service.undo(sheet, by="user:ana")
    assert _cell(sheet, 1, "order_status") == "canceled"


def test_a_cells_story_names_its_file_row_then_who_set_it(env):
    from aughor.sheets import service
    sheet = _orders(env)
    service.set_cells(sheet, [{"row": 2, "column": "order_status", "value": "shipped"}], by="user:ana")
    story = service.cell_history(sheet, 2, "order_status")
    assert story["came_from"].endswith("row 2")
    assert [(e["event"], e["value"], e["previous"], e["by"]) for e in story["events"]] == [
        ("set", "shipped", None, "user:ana")]


def test_undo_of_the_sheets_making_removes_it_whole_only_when_asked_by_name(env):
    from aughor.sheets import model, service
    sheet = _orders(env)
    with pytest.raises(service.Refused, match="would remove the sheet"):
        service.undo(sheet, by="user:ana")
    assert model.get(sheet.id) is not None
    out = service.undo(sheet, by="user:ana", removing=True)
    assert out["removed"] and model.get(sheet.id) is None


def test_totals_are_over_the_rows_the_view_shows(env):
    from aughor.sheets import projection
    from aughor.sheets.model import Condition
    sheet = _orders(env)
    page = projection.read_rows(sheet, conditions=[Condition(column="order_status", op="is", value="delivered")])
    assert page["total"] == 3
    price = sheet.column("price").id
    assert page["totals"][price]["sum"] == "168.59"
    est = sheet.column("order_estimated_delivery_date").id
    assert page["totals"][est]["earliest"] == "2017-10-18" and page["totals"][est]["latest"] == "2018-08-13"


def test_a_comment_on_a_row_is_a_said_claim_in_the_record(env):
    from aughor.record import claims
    from aughor.sheets import record
    sheet = _orders(env)
    record.comment(sheet, 3, "Customer called about this one", by="user:ana")
    got = record.record(sheet, 3)
    assert [c["text"] for c in got["comments"]] == ["Customer called about this one"]
    booked = claims.list_claims(kind="said", about_key=record.row_ref(sheet.id, 3))
    assert booked and booked[0].tier == "said" and booked[0].author == "user:ana"


# ── the Sheets connection ────────────────────────────────────────────────────────────────────────────────────────────

def test_the_sheets_connection_is_always_listed():
    from aughor.db import registry
    assert "sheets" in [c["id"] for c in registry.list_connections()]
    assert registry.get_dsn("sheets") == ("sheets", "sheets://")


def test_writing_the_typed_rows_refuses_a_value_its_kind_would_lose(env):
    """The lossless rule's second check, where the rows are written: a filled value that would be empty once typed is
    refused, and no source is written — even when a caller skipped the first check."""
    from aughor.sheets import files, imports
    path = env / "o.csv"
    path.write_text(ORDERS)
    con, cols = imports.open_file(path)
    try:
        with pytest.raises(imports.ImportRefused, match="do not read as Date"):
            imports.write_source("abcdef0123", con, [{"id": "c1", "raw": "order_status", "kind": "date"}])
    finally:
        con.close()
    assert not files.source_parquet("abcdef0123").exists()


def test_a_sheets_own_values_are_never_merged_onto_a_query_as_annotations(env):
    """They are already IN the table a sheets query reads; merged again they would be noise on every answer."""
    from aughor.actions.overlay import apply_overlay
    from aughor.sheets import service
    from aughor.sheets.connection import SheetsConnection
    sheet = _orders(env)
    service.set_cells(sheet, [{"row": 1, "column": "order_status", "value": "shipped"}], by="user:ana")
    # aliased by the column's id, as the edit names it: the one shape a cell annotation could match on
    cid = sheet.column("order_status").id
    result = SheetsConnection().execute("t", f"SELECT _row, order_status AS {cid} FROM {sheet.table} ORDER BY _row LIMIT 2")
    apply_overlay(result, "sheets")
    assert result.annotations == [] and result.rows[0] == ["1", "shipped"]


def test_a_cell_an_undo_put_back_is_changed_again_at_the_version_its_page_reads(env):
    """A cell set and then undone holds no edit but keeps its version: the page says that version, a change made at it
    is kept, and one made at 0 — what a page that knew only the cells holding an edit sent — is refused as stale."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from aughor.routers import sheets as sheets_router
    from aughor.sheets import model, service
    sheet = _orders(env)
    status = sheet.column("order_status").id
    service.set_cells(sheet, [{"row": 3, "column": status, "value": "delivered", "version": 0}], by="user:ana")
    service.undo(model.get(sheet.id), by="user:ana")
    app = FastAPI()
    app.include_router(sheets_router.router)
    page = TestClient(app).get(f"/sheets/{sheet.id}/rows").json()
    assert "3" not in page["changed"]                                  # the source's value stands again
    assert page["versions"]["3"][status] == 2                          # set, then put back
    with pytest.raises(service.Conflict, match="^You changed order_status in row 3 .*after this page read it"):
        service.set_cells(model.get(sheet.id), [{"row": 3, "column": status, "value": "canceled", "version": 0}],
                          by="user:ana")
    service.set_cells(model.get(sheet.id), [{"row": 3, "column": status, "value": "canceled", "version": 2}],
                      by="user:ana")
    assert _cell(model.get(sheet.id), 3, "order_status") == "canceled"


# ── a column moved (the grid's header dragged) ──────────────────────────────────────────────────────────────────────

def test_a_column_moved_is_the_sheets_order_and_undo_puts_it_back(env):
    """Dragging a header moves the column for everyone, as a spreadsheet's column order is — one change in the history,
    undone whole; the rows still read under their own columns, and the table needs no rebuild for it."""
    from aughor.sheets import model, projection, service
    sheet = _orders(env)
    names = lambda: [c.name for c in model.get(sheet.id).columns]          # noqa: E731
    before = names()
    price = sheet.column("price")
    status = sheet.column("order_status")
    first = (_cell(sheet, 1, "price"), _cell(sheet, 1, "order_status"))
    service.update_column(sheet, price.id, by="user:ana", before=status.id)
    now = names()
    assert now.index("price") == now.index("order_status") - 1 and len(now) == len(before)
    moved = model.get(sheet.id)
    assert moved.change.what == "price moved before order_status"
    page = projection.read_rows(moved, limit=1)
    at = [c.id for c in moved.columns].index(price.id) + 1                             # after the row's number
    assert page["rows"][0][at] == first[0]                                             # read under its own column
    assert (_cell(moved, 1, "price"), _cell(moved, 1, "order_status")) == first
    assert _same(moved)["same"]
    service.update_column(moved, price.id, by="user:ana", before="")
    assert names()[-1] == "price"
    service.undo(model.get(sheet.id), by="user:ana")
    assert names() == now                                                               # the move to the end undone
    service.undo(model.get(sheet.id), by="user:ana")
    assert names() == before                                                            # and the first, after it
    with pytest.raises(service.Refused, match="no column 'nope'"):
        service.update_column(model.get(sheet.id), price.id, by="user:ana", before="nope")
    unchanged = model.get(sheet.id)
    service.update_column(unchanged, price.id, by="user:ana", before=price.id)            # in front of itself: nothing
    assert names() == before and model.get(sheet.id).change.what == unchanged.change.what



# ── undo, several changes to a definition in a row ──────────────────────────────────────────────────────────────────

def test_undo_steps_back_through_several_changes_to_a_definition_and_redo_forward_again(env):
    """Two renames in a row: the second undo was refused, "undo that first", when the first had been undone — the
    guard asked which version was newest, and an undo is a newer version holding an older definition. It asks now
    whether the definition is still what the change left."""
    from aughor.sheets import model, service
    sheet = _orders(env)
    col = sheet.column("price").id
    name = lambda: model.get(sheet.id).column(col).name                                # noqa: E731
    service.update_column(sheet, col, by="user:ana", name="price2")
    service.update_column(model.get(sheet.id), col, by="user:ana", name="price3")
    service.undo(model.get(sheet.id), by="user:ana")
    assert name() == "price2"
    service.undo(model.get(sheet.id), by="user:ana")
    assert name() == "price"
    service.redo(model.get(sheet.id), by="user:ana")
    assert name() == "price2"
    service.redo(model.get(sheet.id), by="user:ana")
    assert name() == "price3"
    assert _same(sheet)["same"]


def test_undo_takes_back_definitions_and_values_in_turn_whatever_their_mix(env):
    from aughor.sheets import model, service
    sheet = _orders(env)
    col = sheet.column("price")
    status = sheet.column("order_status")
    order = lambda: [c.name for c in model.get(sheet.id).columns]                       # noqa: E731
    before_order, before_cell = order(), _cell(sheet, 2, "order_status")
    service.update_column(sheet, col.id, by="user:ana", name="Paid")                   # a definition
    service.set_cells(model.get(sheet.id), [{"row": 2, "column": status.id, "value": "canceled"}], by="user:ana")
    service.update_column(model.get(sheet.id), col.id, by="user:ana", before=status.id)  # a definition again
    for _ in range(3):
        service.undo(model.get(sheet.id), by="user:ana")
    now = model.get(sheet.id)
    assert order() == before_order and _cell(now, 2, "order_status") == before_cell
    assert _same(now)["same"]


def test_a_change_still_standing_over_yours_keeps_yours_from_being_undone(env):
    """The guard is kept where it guards: someone else's change to the definition, not undone, stands over yours —
    putting back the definition from before yours would throw theirs away."""
    from aughor.sheets import model, service
    sheet = _orders(env)
    col = sheet.column("price").id
    service.update_column(sheet, col, by="user:ana", name="price2")
    service.update_column(model.get(sheet.id), sheet.column("zip").id, by="user:bo", name="postcode")
    with pytest.raises(service.Refused, match="postcode by user:bo"):
        service.undo(model.get(sheet.id), by="user:ana")
    assert model.get(sheet.id).column(col).name == "price2"
