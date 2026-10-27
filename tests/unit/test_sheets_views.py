"""Arc SH, SH-3 — a sheet's views: groups with their totals, a board, a calendar, rules, views kept to oneself (§3.64).

The wave's promise is that a view is only a way of laying out the grid's rows, never another count of them: a group, a
lane, a day and a rule each hold exactly the rows the grid shows when filtered to the same thing. Every test below that
reads a count reads it twice — through the view and through the grid's own filter — and they must agree.
"""
from __future__ import annotations

import pytest

from aughor.kernel.flags import flag_overrides

ORDERS = """order_id,customer_id,order_status,order_purchase_timestamp,order_estimated_delivery_date,price,paid
e481f51c,9ef432eb,delivered,2017-10-02 10:56:33,2017-10-18 00:00:00,29.99,yes
53cdb2fc,b0830fb4,delivered,2018-07-24 20:41:37,2018-08-13 00:00:00,118.70,yes
47770eb9,41ce2a54,shipped,2018-08-08 08:38:49,2018-09-04 00:00:00,159.90,no
949d5b44,f88197465,canceled,2017-11-18 19:28:06,2017-12-15 00:00:00,45.00,no
ad21c59c,8ab97904,delivered,2018-02-13 21:18:39,2018-09-04 00:00:00,19.90,yes
a4591c26,503740e9,shipped,2018-09-04 21:57:05,2018-09-26 00:00:00,147.90,yes
136cce7f,ed0271e0,shipped,2018-09-11 12:22:00,,65.95,no
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("AUGHOR_SYSTEM_DB", str(tmp_path / "system.db"))
    from aughor.actions import overlay
    monkeypatch.setattr(overlay, "_DB_PATH", tmp_path / "overlay.db")
    from aughor.sheets import projection
    projection.reset()
    with flag_overrides({"sheets.core": True, "sheets.grid": True, "sheets.views": True}):
        yield tmp_path
    projection.reset()


def _orders(env):
    from aughor.sheets import files, service
    path = env / "orders.csv"
    path.write_text(ORDERS)
    return service.create_from_file(files.stage(path, path.name), name="Olist orders", by="user:ana",
                                    chosen={"order_estimated_delivery_date": "date", "paid": "yesno",
                                            "order_status": "choice"})


def _grid(sheet, *conditions):
    """The grid's own count of the rows meeting these conditions, and its totals over them."""
    from aughor.sheets import projection
    from aughor.sheets.model import Condition
    page = projection.read_rows(sheet, conditions=[Condition(**c) for c in conditions], limit=1)
    return page["total"], page["totals"]


def _fresh(sheet):
    from aughor.sheets import model
    return model.get(sheet.id)


# ── groups ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_each_group_holds_and_totals_the_rows_the_grid_shows_for_its_value(env):
    from aughor.sheets import views
    sheet = _orders(env)
    status, price = sheet.column("order_status").id, sheet.column("price").id
    got = views.groups(sheet, conditions=[], group=status)
    # the largest first; two of a size by their value
    assert [(g["value"], g["rows"]) for g in got["groups"]] == [("delivered", 3), ("shipped", 3), ("canceled", 1)]
    assert got["total"] == 7 and got["groups_total"] == 3 and got["groups_not_listed"] == 0
    for g in got["groups"]:
        rows, totals = _grid(sheet, {"column": status, "op": "is", "value": g["value"]})
        assert g["rows"] == rows
        assert g["totals"][price]["sum"] == totals[price]["sum"]
        assert len(g["shown"]) == min(rows, views.GROUP_ROWS)
        # every row shown under a head holds the head's value
        at = 1 + [c.id for c in sheet.columns].index(status)
        assert {r[at] for r in g["shown"]} == {g["value"]}
    assert got["groups"][0]["totals"][price]["sum"] == "168.59"


def test_a_grouping_says_how_many_groups_it_did_not_list(env, monkeypatch):
    from aughor.sheets import views
    monkeypatch.setattr(views, "MAX_GROUPS", 2)
    sheet = _orders(env)
    got = views.groups(sheet, conditions=[], group=sheet.column("order_id").id)
    assert len(got["groups"]) == 2 and got["groups_total"] == 7 and got["groups_not_listed"] == 5


def test_groups_without_totals_count_the_same_rows(env):
    from aughor.sheets import views
    sheet = _orders(env)
    status = sheet.column("order_status").id
    bare = views.groups(sheet, conditions=[], group=status, with_totals=False)
    full = views.groups(sheet, conditions=[], group=status)
    assert [(g["value"], g["rows"]) for g in bare["groups"]] == [(g["value"], g["rows"]) for g in full["groups"]]
    assert all(g["totals"] == {} for g in bare["groups"])


# ── a board ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_lane_holds_the_rows_the_grid_shows_for_its_value_and_what_the_filter_left_out_is_said(env):
    from aughor.sheets import views
    sheet = _orders(env)
    status = sheet.column("order_status").id
    still_open = [{"column": status, "op": "not_in", "value": ["delivered", "canceled"]}]
    from aughor.sheets.model import Condition
    got = views.board(sheet, conditions=[Condition(**c) for c in still_open], column=status)
    lanes = {lane["value"]: lane["rows"] for lane in got["lanes"]}
    assert lanes == {"shipped": 3}
    for value, n in lanes.items():
        assert n == _grid(sheet, *still_open, {"column": status, "op": "is", "value": value})[0]
    assert {x["value"]: x["rows"] for x in got["not_shown"]} == {"delivered": 3, "canceled": 1}
    assert got["total"] == 3 and got["movable"]


def test_a_card_moved_to_another_lane_is_an_edit_kept_with_who_and_when(env):
    from aughor.sheets import service, views
    sheet = _orders(env)
    status = sheet.column("order_status").id
    service.set_cells(sheet, [{"row": 3, "column": status, "value": "delivered", "version": 0}], by="user:bo")
    got = views.board(_fresh(sheet), conditions=[], column=status)
    lanes = {lane["value"]: lane["rows"] for lane in got["lanes"]}
    assert lanes["delivered"] == 4 and lanes["shipped"] == 2
    story = service.cell_history(_fresh(sheet), 3, status)
    assert story["events"][0]["by"] == "user:bo" and story["events"][0]["value"] == "delivered"


def test_a_choice_no_row_holds_is_an_empty_lane_a_card_can_be_moved_into(env):
    from aughor.sheets import views
    sheet = _orders(env)
    c = sheet.column("order_status")
    c.choices = [*c.choices, "approved"]
    got = views.board(sheet, conditions=[], column=c.id)
    assert {"value": "approved", "rows": 0, "cards": []} in got["lanes"]


def test_a_board_reads_a_yes_no_column_as_two_lanes(env):
    from aughor.sheets import views
    sheet = _orders(env)
    got = views.board(sheet, conditions=[], column=sheet.column("paid").id)
    assert [(lane["value"], lane["rows"]) for lane in got["lanes"]] == [(True, 4), (False, 3)]


# ── a calendar ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_day_holds_the_rows_the_grid_shows_on_that_day_and_rows_with_no_date_are_counted(env):
    from aughor.sheets import views
    sheet = _orders(env)
    est = sheet.column("order_estimated_delivery_date").id
    got = views.calendar(sheet, conditions=[], column=est)
    assert got["month"] == "2018-09"                       # where the rows end
    assert got["days"] == [{"day": "2018-09-04", "rows": 2}, {"day": "2018-09-26", "rows": 1}]
    assert got["undated"] == 1 and got["month_rows"] == 3 and got["total"] == 7
    for d in got["days"]:
        assert d["rows"] == _grid(sheet, {"column": est, "op": "on", "value": d["day"]})[0]


def test_a_calendar_by_a_date_and_time_places_each_row_on_its_day(env):
    from aughor.sheets import views
    sheet = _orders(env)
    bought = sheet.column("order_purchase_timestamp").id
    got = views.calendar(sheet, conditions=[], column=bought, month="2018-09")
    assert got["days"] == [{"day": "2018-09-04", "rows": 1}, {"day": "2018-09-11", "rows": 1}]
    assert _grid(sheet, {"column": bought, "op": "on", "value": "2018-09-04"})[0] == 1


# ── rules ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_rule_marks_exactly_the_rows_a_view_with_its_conditions_shows(env):
    from aughor.sheets import service, views
    from aughor.sheets.model import Condition, Rule
    sheet = _orders(env)
    price, status = sheet.column("price").id, sheet.column("order_status").id
    conditions = [{"column": price, "op": "gt", "value": "100"}, {"column": status, "op": "is_not", "value": "delivered"}]
    sheet = service.save_rule(sheet, Rule(id="", name="Dear and open", conditions=[Condition(**c) for c in conditions]),
                              by="user:ana")
    rule = sheet.rules[0]
    expected = _grid(sheet, *conditions)[0]
    assert expected == 2
    assert views.rule_rows(sheet) == {rule.id: expected}
    assert _grid(sheet, {"column": "", "op": "marked", "value": rule.id})[0] == expected
    assert _grid(sheet, {"column": "", "op": "not_marked", "value": rule.id})[0] == 7 - expected
    assert sorted(views.marks(sheet, set(range(1, 8)))) == ["3", "6"]


def test_a_rule_is_refused_when_it_reads_no_column_or_another_rule(env):
    from aughor.sheets import service
    from aughor.sheets.model import Condition, Rule
    sheet = _orders(env)
    with pytest.raises(service.Refused, match="not a column"):
        service.save_rule(sheet, Rule(id="", name="x", conditions=[Condition(column="nope", op="is", value="a")]),
                          by="user:ana")
    with pytest.raises(service.Refused, match="at least one condition"):
        service.save_rule(sheet, Rule(id="", name="x"), by="user:ana")
    with pytest.raises(service.Refused, match="not of other rules"):
        service.save_rule(sheet, Rule(id="", name="x", conditions=[Condition(column="", op="marked", value="r")]),
                          by="user:ana")


# ── views: kinds and who sees them ───────────────────────────────────────────────────────────────────────────────────

def test_a_board_needs_a_choice_column_and_a_calendar_a_date(env):
    from aughor.sheets import service
    from aughor.sheets.model import View
    sheet = _orders(env)
    with pytest.raises(service.Refused, match="choice or a yes/no"):
        service.save_view(sheet, View(id="", name="b", kind="board", group=sheet.column("price").id), by="user:ana")
    with pytest.raises(service.Refused, match="places rows by a date"):
        service.save_view(sheet, View(id="", name="c", kind="calendar", date=sheet.column("price").id), by="user:ana")
    kept = service.save_view(sheet, View(id="", name="By status", kind="board",
                                         group=sheet.column("order_status").id), by="user:ana")
    assert kept.views[-1].kind == "board" and kept.views[-1].owner == "user:ana"


def test_a_view_kept_to_its_maker_is_seen_and_changed_by_them_only_and_its_name_stays_out_of_the_history(env):
    from aughor.sheets import service
    from aughor.sheets.model import View
    sheet = _orders(env)
    sheet = service.save_view(sheet, View(id="", name="My late ones", shared=False), by="user:ana")
    mine = sheet.views[-1]
    assert mine.owner == "user:ana"
    assert mine in sheet.views_for("user:ana") and mine not in sheet.views_for("user:bo")
    with pytest.raises(service.Refused, match="no view"):
        service.save_view(sheet, View(id=mine.id, name="Taken over", shared=True), by="user:bo")
    with pytest.raises(service.Refused, match="no view"):
        service.remove_view(sheet, mine.id, by="user:bo")
    whats = [c["what"] for c in service.changes(_fresh(sheet))]
    assert "a view of their own kept" in whats and not any("My late ones" in w for w in whats)


def test_only_its_maker_keeps_a_shared_view_to_themselves_and_one_shared_view_always_stands(env):
    from aughor.sheets import service
    from aughor.sheets.model import View
    sheet = _orders(env)
    sheet = service.save_view(sheet, View(id="", name="Open"), by="user:ana")
    shared = sheet.views[-1]
    with pytest.raises(service.Refused, match="only the person who made"):
        service.save_view(sheet, shared.model_copy(update={"shared": False}), by="user:bo")
    sheet = service.save_view(sheet, shared.model_copy(update={"shared": False}), by="user:ana")
    assert not sheet.views[-1].shared
    # the first view, from the import, is now the only shared one: it stays
    with pytest.raises(service.Refused, match="at least one shared view"):
        service.remove_view(sheet, sheet.views[0].id, by="user:ana")


def test_taking_a_column_off_takes_it_out_of_every_view_and_rule(env):
    from aughor.sheets import service
    from aughor.sheets.model import Condition, Rule, View
    sheet = _orders(env)
    status, price = sheet.column("order_status").id, sheet.column("price").id
    sheet = service.save_view(sheet, View(id="", name="Board", kind="board", group=status, card=[price]), by="user:ana")
    sheet = service.save_rule(sheet, Rule(id="", name="Dear", conditions=[Condition(column=price, op="gt", value="100")]),
                              by="user:ana")
    sheet = service.remove_column(sheet, status, by="user:ana")
    board = sheet.views[-1]
    assert board.kind == "grid" and board.group == ""
    sheet = service.remove_column(sheet, price, by="user:ana")
    assert sheet.rules == [] and sheet.views[-1].card == []
    assert "rule Dear went with it" in service.changes(_fresh(sheet))[0]["what"]


def test_a_view_shows_its_count_in_the_definition(env):
    from aughor.sheets import service, views
    from aughor.sheets.model import Condition, View
    sheet = _orders(env)
    status = sheet.column("order_status").id
    sheet = service.save_view(sheet, View(id="", name="Shipped",
                                          filter=[Condition(column=status, op="is", value="shipped")]), by="user:ana")
    counts = views.view_rows(sheet, sheet.views)
    assert counts[sheet.views[0].id] == 7 and counts[sheet.views[-1].id] == 3


# ── off ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_off_no_board_calendar_or_rule_answers_and_no_such_view_is_kept(env):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from aughor.routers import sheets as sheets_router
    sheet = _orders(env)
    status = sheet.column("order_status").id
    app = FastAPI()
    app.include_router(sheets_router.router)
    client = TestClient(app)
    with flag_overrides({"sheets.views": False}):
        assert client.get(f"/sheets/{sheet.id}/board", params={"column": status}).status_code == 404
        assert client.get(f"/sheets/{sheet.id}/calendar", params={"column": status}).status_code == 404
        assert client.put(f"/sheets/{sheet.id}/rules", json={"rule": {"id": "", "name": "x"}}).status_code == 404
        refused = client.put(f"/sheets/{sheet.id}/views", json={"view": {"name": "b", "kind": "board", "group": status}})
        assert refused.status_code == 404
        # a grouping still reads, without its totals
        got = client.get(f"/sheets/{sheet.id}/groups", params={"group": status}).json()
        assert all(g["totals"] == {} for g in got["groups"]) and "marks" not in got
        assert "marks" not in client.get(f"/sheets/{sheet.id}/rows").json()
    assert [v.kind for v in _fresh(sheet).views] == ["grid"]
    with flag_overrides({"sheets.views": True}):
        assert client.get(f"/sheets/{sheet.id}/board", params={"column": status}).status_code == 200


def test_a_new_view_is_kept_through_the_route_without_an_id(env):
    """The grid keeps a new view by its name alone; the id is the keeping's to give (it was refused as missing)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from aughor.routers import sheets as sheets_router
    sheet = _orders(env)
    app = FastAPI()
    app.include_router(sheets_router.router)
    got = TestClient(app).put(f"/sheets/{sheet.id}/views", json={"view": {"name": "Open", "filter": []}})
    assert got.status_code == 200, got.text
    kept = got.json()["views"][-1]
    assert kept["name"] == "Open" and kept["id"] and kept["shared"]
    assert got.json()["view_rows"][kept["id"]] == 7


def test_a_calendar_opens_where_the_rows_end_not_on_a_straggler(env):
    """Olist: 2,001 orders estimated for September 2018 and one for November — the calendar opens on September."""
    from aughor.sheets import files, service, views
    lines = ["order_id,due"] + [f"o{i},2018-09-{1 + i % 28:02d}" for i in range(120)] + ["late,2018-11-12"]
    path = env / "due.csv"
    path.write_text("\n".join(lines) + "\n")
    sheet = service.create_from_file(files.stage(path, path.name), name="Due", by="user:ana", chosen={"due": "date"})
    due = sheet.column("due").id
    got = views.calendar(sheet, conditions=[], column=due)
    assert got["month"] == got["where_rows_end"] == "2018-09" and got["latest"] == "2018-11-12"
    asked = views.calendar(sheet, conditions=[], column=due, month="2018-11")
    assert asked["days"] == [{"day": "2018-11-12", "rows": 1}] and asked["where_rows_end"] == "2018-09"


def test_a_row_a_rules_condition_cannot_read_is_not_marked_and_is_counted_as_not_marked(env):
    """A row with no estimated date cannot be "before" anything: it is not marked, so it is among the not-marked —
    never dropped from both."""
    from aughor.sheets import service
    from aughor.sheets.model import Condition, Rule
    sheet = _orders(env)
    est = sheet.column("order_estimated_delivery_date").id
    sheet = service.save_rule(sheet, Rule(name="Due before September",
                                          conditions=[Condition(column=est, op="before", value="2018-09-01")]),
                              by="user:ana")
    rule = sheet.rules[0].id
    marked = _grid(sheet, {"column": "", "op": "marked", "value": rule})[0]
    unmarked = _grid(sheet, {"column": "", "op": "not_marked", "value": rule})[0]
    assert marked == 3 and unmarked == 4 and marked + unmarked == 7


def test_groups_under_a_filter_hold_only_the_rows_the_filter_shows(env):
    from aughor.sheets import views
    from aughor.sheets.model import Condition
    sheet = _orders(env)
    status, price = sheet.column("order_status").id, sheet.column("price").id
    dear = {"column": price, "op": "gt", "value": "50"}
    got = views.groups(sheet, conditions=[Condition(**dear)], group=status)
    assert got["total"] == _grid(sheet, dear)[0] == 4
    for g in got["groups"]:
        assert g["rows"] == _grid(sheet, dear, {"column": status, "op": "is", "value": g["value"]})[0]
