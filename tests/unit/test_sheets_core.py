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


# ── the history, value by value, and putting one back ────────────────────────────────────────────────────────────────

def _line(sheet, row, name="", *, change=None):
    """The line for a cell (or a row, with no name) in its own story: the newest, or the one of ``change``."""
    from aughor.sheets import service
    column = sheet.column(name).id if name else ""
    read = service.history(sheet, row=row, column=column)
    for ch in read["changes"]:
        if change is None or ch["id"] == change:
            found = [ln for ln in ch["lines"] if ln["row"] == row and ln["column"] == column]
            if found:
                return ch["id"], found[0]
    raise AssertionError(f"no line for row {row} {name!r}")


def _set(sheet, row, name, value, by="user:ana"):
    from aughor.actions import overlay
    from aughor.sheets import service
    c = sheet.column(name)
    version = overlay.sheet_versions(sheet.id, {row}).get((row, c.id), 0)
    return service.set_cells(sheet, [{"row": row, "column": c.id, "value": value, "version": version}], by=by)["change_id"]


def test_the_history_says_which_cell_changed_from_what_to_what(env):
    from aughor.sheets import service
    sheet = _orders(env)
    cid = _set(sheet, 1, "order_status", "returned", by="user:bo")
    change = next(c for c in service.history(sheet)["changes"] if c["id"] == cid)
    assert change["lines_total"] == 1
    line = change["lines"][0]
    assert (line["kind"], line["row"], line["name"]) == ("cell", 1, "order_status")
    assert (line["from"], line["to"], line["now"], line["stands"]) == ("delivered", "returned", "returned", True)
    assert line["title"] and change["by"] == "user:bo"


def test_a_cell_goes_back_to_any_state_it_held_and_nothing_else_moves(env):
    from aughor.sheets import service
    sheet = _orders(env)
    _set(sheet, 1, "order_status", "invoiced")
    second = _set(sheet, 1, "order_status", "approved")
    third = _set(sheet, 1, "order_status", "returned")
    _set(sheet, 1, "customer_id", "c9")
    _set(sheet, 2, "order_status", "canceled")
    before = {r: dict(service.projection.read_row(sheet, r)) for r in (1, 2, 3)}
    _, line = _line(sheet, 1, "order_status", change=third)
    assert line["from"] == "approved"
    out = service.put_back(sheet, change=third, row=1, column=sheet.column("order_status").id, current=line["current"],
                           by="user:cy")
    assert _cell(sheet, 1, "order_status") == "approved"
    after = {r: dict(service.projection.read_row(sheet, r)) for r in (1, 2, 3)}
    status = sheet.column("order_status").id
    assert {k: v for k, v in after[1].items() if k != status} == {k: v for k, v in before[1].items() if k != status}
    assert after[2] == before[2] and after[3] == before[3]
    assert _same(sheet)["same"]
    # further back, over the put back itself: the second change replaced "invoiced"
    _, line = _line(sheet, 1, "order_status", change=second)
    assert (line["from"], line["stands"], line["now"]) == ("invoiced", False, "approved")
    service.put_back(sheet, change=second, row=1, column=status, current=line["current"], by="user:cy")
    assert _cell(sheet, 1, "order_status") == "invoiced"
    assert _same(sheet)["same"]
    # every state is still in the story, and the put back is a change under the person who made it
    story = service.history(sheet, row=1, column=status)["changes"]
    assert len(story) == 5 and story[0]["by"] == "user:cy" and story[0]["origin"] == f"put_back:{second}"
    assert story[1]["id"] == out["change_id"]


def test_a_cell_goes_back_to_what_its_file_said(env):
    from aughor.sheets import service
    sheet = _orders(env)
    first = _set(sheet, 1, "order_status", "invoiced")
    _set(sheet, 1, "order_status", "returned")
    status = sheet.column("order_status").id
    _, line = _line(sheet, 1, "order_status", change=first)
    assert line["from"] == "delivered"                       # the file's value, read from its source
    service.put_back(sheet, change=first, row=1, column=status, current=line["current"], by="user:ana")
    assert _cell(sheet, 1, "order_status") == "delivered"
    assert service.cell_history(sheet, 1, status)["changed"] is False     # its edit is withdrawn: the file's value stands
    assert _same(sheet)["same"]
    _, line = _line(sheet, 1, "order_status", change=first)
    assert line["same"] is True                              # nothing to put back now, and the line says so


def test_one_removed_row_comes_back_and_the_others_stay_removed(env):
    from aughor.sheets import service
    sheet = _orders(env)
    _set(sheet, 2, "order_status", "canceled")
    gone = service.remove_rows(sheet, [1, 2, 3], by="user:ana")["change_id"]
    assert service.projection.read_row(sheet, 2) is None
    assert next(c for c in service.history(sheet)["changes"] if c["id"] == gone)["what"] == "3 rows removed"
    _, line = _line(sheet, 2, change=gone)
    assert (line["kind"], line["what"], line["same"]) == ("row", "removed", False) and line["title"]
    service.put_back(sheet, change=gone, row=2, column="", current=line["current"], by="user:ana")
    assert _cell(sheet, 2, "order_status") == "canceled"     # back, with the value someone had set on it
    assert service.projection.read_row(sheet, 1) is None and service.projection.read_row(sheet, 3) is None
    assert _same(sheet)["same"]


def test_a_row_added_comes_out_alone_and_goes_back_in_with_its_values(env):
    from aughor.sheets import service
    sheet = _orders(env)
    added = service.add_row(sheet, {"order_id": "x1", "order_status": "created"}, by="user:ana")
    other = service.add_row(sheet, {"order_id": "x2"}, by="user:ana")["row"]
    n = added["row"]
    change = next(c for c in service.history(sheet)["changes"] if c["id"] == added["change_id"])
    assert change["lines_total"] == len(change["lines"]) == 1    # the row, its values folded inside it
    assert change["lines"][0]["what"] == "added"
    assert change["lines"][0]["values"] == {"order_id": "x1", "order_status": "created"}
    out = service.put_back(sheet, change=added["change_id"], row=n, column="", current=change["lines"][0]["current"],
                           by="user:ana")
    assert service.projection.read_row(sheet, n) is None and service.projection.read_row(sheet, other) is not None
    assert _same(sheet)["same"]
    _, line = _line(sheet, n, change=out["change_id"])
    assert line["what"] == "removed"
    service.put_back(sheet, change=out["change_id"], row=n, column="", current=line["current"], by="user:ana")
    assert _cell(sheet, n, "order_id") == "x1"
    assert _same(sheet)["same"]


def test_a_change_that_wrote_a_cell_twice_goes_back_to_what_stood_before_its_first_write(env):
    from aughor.sheets import service
    sheet = _orders(env)
    status = sheet.column("order_status").id
    service.set_cells(sheet, [{"row": 1, "column": status, "value": "invoiced"}], by="user:ana", cid="onechange")
    service.set_cells(sheet, [{"row": 1, "column": status, "value": "returned"}], by="user:ana", cid="onechange")
    change = next(c for c in service.history(sheet)["changes"] if c["id"] == "onechange")
    assert change["lines_total"] == 1
    line = change["lines"][0]
    assert (line["from"], line["to"]) == ("delivered", "returned")
    service.put_back(sheet, change="onechange", row=1, column=status, current=line["current"], by="user:ana")
    assert _cell(sheet, 1, "order_status") == "delivered"
    assert _same(sheet)["same"]


def test_a_whole_change_goes_back_except_what_was_changed_since_which_is_named(env):
    from aughor.sheets import service
    sheet = _orders(env)
    status = sheet.column("order_status").id
    cid = service.set_cells(sheet, [{"row": r, "column": status, "value": "held"} for r in (1, 2, 3)], by="user:ana")["change_id"]
    _set(sheet, 2, "order_status", "returned", by="user:bo")
    out = service.put_back(sheet, change=cid, by="user:ana")
    assert out["put_back"] == 2 and [(x["row"], x["name"], x["by"]) for x in out["left"]] == [(2, "order_status", "user:bo")]
    assert "changed since left as it is" in out["said"]
    assert _cell(sheet, 1, "order_status") == "delivered" and _cell(sheet, 3, "order_status") == "shipped"
    assert _cell(sheet, 2, "order_status") == "returned"     # bo's newer decision stands
    assert _same(sheet)["same"]
    with pytest.raises(service.Refused, match="nothing of it to put back"):
        service.put_back(sheet, change=cid, by="user:ana")


def test_someone_who_changed_a_cell_after_you_read_it_stops_your_put_back(env):
    from aughor.sheets import service
    sheet = _orders(env)
    status = sheet.column("order_status").id
    cid = _set(sheet, 1, "order_status", "invoiced")
    _, line = _line(sheet, 1, "order_status", change=cid)
    _set(sheet, 1, "order_status", "returned", by="user:bo")
    with pytest.raises(service.Conflict, match="after you read it"):
        service.put_back(sheet, change=cid, row=1, column=status, current=line["current"], by="user:ana")
    assert _cell(sheet, 1, "order_status") == "returned"


def test_a_put_back_is_undone_like_any_other_change(env):
    from aughor.sheets import service
    sheet = _orders(env)
    status = sheet.column("order_status").id
    cid = _set(sheet, 1, "order_status", "invoiced", by="user:bo")
    _, line = _line(sheet, 1, "order_status", change=cid)
    service.put_back(sheet, change=cid, row=1, column=status, current=line["current"], by="user:ana")
    done, _ = service.stacks(sheet, "user:ana")
    assert done[-1]["what"] == "order_status in row 1 put back to delivered"
    service.undo(sheet, by="user:ana")
    assert _cell(sheet, 1, "order_status") == "invoiced"
    assert _same(sheet)["same"]


def test_a_cell_whose_row_or_column_went_says_why_it_cannot_go_back(env):
    from aughor.sheets import service
    sheet = _orders(env)
    status = sheet.column("order_status").id
    cid = _set(sheet, 1, "order_status", "invoiced")
    current = _line(sheet, 1, "order_status", change=cid)[1]["current"]
    service.remove_rows(sheet, [1], by="user:ana")
    assert "put the row back first" in _line(sheet, 1, "order_status", change=cid)[1]["blocked"]
    with pytest.raises(service.Refused, match="put the row back first"):
        service.put_back(sheet, change=cid, row=1, column=status, current=current, by="user:ana")


def test_a_change_of_many_cells_lists_a_few_and_counts_them_all(env, monkeypatch):
    from aughor.sheets import service
    sheet = _orders(env)
    sheet = service.add_column(sheet, name="note", kind="text", by="user:ana")
    note = sheet.column("note").id
    written = service.set_cells(sheet, [{"row": r, "column": note, "value": f"n{r}"} for r in (1, 2, 3, 4, 5, 6)], by="user:ana")
    change = next(c for c in service.history(sheet)["changes"] if c["id"] == written["change_id"])
    assert change["lines_total"] == 6 and len(change["lines"]) == service.LINES_SHOWN
    assert len(service.change_lines(sheet, written["change_id"])["lines"]) == 6
    monkeypatch.setattr(service, "CHANGE_READ", 3)      # a change bigger than one reading still counts every cell
    change = next(c for c in service.history(sheet)["changes"] if c["id"] == written["change_id"])
    assert change["lines_total"] == 6 and len(change["lines"]) == 3


def test_what_was_changed_never_touches_the_file_it_came_from(env):
    from aughor.sheets import files, service
    sheet = _orders(env)
    original = files.sheet_dir(sheet.id) / "original.csv"
    source = files.source_parquet(sheet.id)
    before = (original.read_bytes(), source.read_bytes())
    cid = _set(sheet, 1, "order_status", "invoiced")
    service.remove_rows(sheet, [2], by="user:ana")
    service.add_row(sheet, {"order_id": "x1"}, by="user:ana")
    _, line = _line(sheet, 1, "order_status", change=cid)
    service.put_back(sheet, change=cid, row=1, column=sheet.column("order_status").id, current=line["current"], by="user:ana")
    assert (original.read_bytes(), source.read_bytes()) == before
