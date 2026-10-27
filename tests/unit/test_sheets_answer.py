"""Arc SH, SH-4 — the rows a question asked beside a sheet is about, put on the grid (``aughor/sheets/answer.py``).

Live, asked "Which records do not have order delivered carrier date?", the chat answered with a breakdown and a chart,
no count of the rows asked about, and one of its own query's seven groups left out (trace d77fd873). What is asserted
here: ``show_rows`` counts exactly the rows the grid's own filter holds, says the filter as the grid's filter box does,
refuses what the grid could not show with a sentence the model can repair from, and is offered only to a question
summoned from a sheet while the chat beside a sheet is on — every other turn's tools are unchanged.
"""
from __future__ import annotations

import pytest

from aughor.kernel.flags import flag_overrides

ORDERS = """order_id,order_status,order_purchase_timestamp,order_estimated_delivery_date,order_delivered_customer_date
o1,delivered,2018-08-01 10:00:00,2018-08-20 00:00:00,2018-08-19 12:00:00
o2,delivered,2018-08-02 10:00:00,2018-08-10 00:00:00,2018-08-15 09:30:00
o3,shipped,2018-07-03 10:00:00,2018-07-25 00:00:00,
o4,processing,2016-10-05 10:00:00,2016-11-01 00:00:00,
o5,canceled,2018-01-04 10:00:00,2018-01-30 00:00:00,
o6,delivered,2018-09-30 10:00:00,2018-10-25 00:00:00,
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("AUGHOR_SYSTEM_DB", str(tmp_path / "system.db"))
    from aughor.actions import overlay
    monkeypatch.setattr(overlay, "_DB_PATH", tmp_path / "overlay.db")
    from aughor.sheets import projection
    projection.reset()
    with flag_overrides({"sheets.core": True, "sheets.grid": True, "sheets.chat": True, "sheets.views": True}):
        yield tmp_path
    projection.reset()


def _orders(env):
    from aughor.sheets import files, service
    path = env / "olist_orders_dataset.csv"
    path.write_text(ORDERS)
    return service.create_from_file(files.stage(path, path.name), name="Olist orders", by="user:ana",
                                    chosen={"order_estimated_delivery_date": "date"})


def _show(ref, **args):
    from aughor.sheets.answer import show_rows
    frames: list = []
    out = show_rows(ref, args, emit=lambda name, payload: frames.append((name, payload)))
    return out, frames


EMPTY = [{"column": "order_delivered_customer_date", "op": "empty"}]


def test_the_rows_asked_about_are_counted_as_the_grid_counts_them(env):
    from aughor.sheets import projection
    sheet = _orders(env)
    out, frames = _show(sheet.id, conditions=EMPTY, about="Orders not delivered")
    assert out["shown"] and out["rows"] == 4 and out["of"] == 6, out          # o3, o4, o5 — and o6, delivered
    assert out["filter_said"] == "order_delivered_customer_date is empty"
    [(name, card)] = frames
    assert name == "sheet_rows" and card["about"] == "Orders not delivered" and card["share"] == 66.7
    from aughor.sheets.model import Condition
    grid = projection.read_rows(sheet, conditions=[Condition(**c) for c in card["filter"]])["total"]
    assert card["rows"] == grid == 4                                            # the card's filter IS the grid's
    assert card["filter"][0]["column"] == sheet.column("order_delivered_customer_date").id


def test_these_means_the_rows_of_the_view_on_screen(env):
    from aughor.sheets import service
    from aughor.sheets.model import Condition, View
    sheet = _orders(env)
    status = sheet.column("order_status").id
    sheet = service.save_view(sheet, View(id="", name="Delivered", filter=[
        Condition(column=status, op="is", value="delivered")]), by="user:ana")
    view = sheet.views[-1]
    out, [(_, card)] = _show(f"{sheet.id}:{view.id}", within_view=True, about="Delivered late",
                             conditions=[{"column": "order_delivered_customer_date", "op": "empty"}])
    assert (out["rows"], out["of"]) == (1, 3) and "the view Delivered" in out["out_of"], out   # o6, of o1 o2 o6
    assert card["within_view"] and [c["column"] for c in card["filter"]][0] == status        # the view's own first
    plain, _ = _show(f"{sheet.id}:{view.id}", conditions=EMPTY, about="x")
    assert (plain["rows"], plain["of"]) == (4, 6)                               # not asked "of these": the sheet


def test_what_the_grid_could_not_show_is_refused_with_a_sentence_to_repair_from(env):
    sheet = _orders(env)
    out, frames = _show(sheet.id, conditions=[{"column": "carrier", "op": "empty"}], about="x")
    assert not out["shown"] and "not a column of Olist orders" in out["refused"]
    assert "order_delivered_customer_date" in out["refused"] and frames == []   # the columns named, nothing shown
    out, _ = _show(sheet.id, conditions=[{"column": "order_status", "op": "like", "value": "d%"}], about="x")
    assert "not one of the grid's operators" in out["refused"]
    out, _ = _show(sheet.id, conditions=[], about="x")
    assert "at least one condition" in out["refused"]
    out, _ = _show(sheet.id, conditions=[{"column": "order_estimated_delivery_date", "op": "before",
                                          "value": "not a day"}], about="x")
    assert not out["shown"] and out["refused"]


def test_a_rule_is_named_by_its_name(env):
    from aughor.sheets import service
    from aughor.sheets.model import Condition, Rule
    sheet = _orders(env)
    sheet = service.save_rule(sheet, Rule(name="Not delivered", conditions=[
        Condition(column=sheet.column("order_delivered_customer_date").id, op="empty")]), by="user:ana")
    out, [(_, card)] = _show(sheet.id, conditions=[{"column": "", "op": "marked", "value": "not delivered"}],
                             about="x")
    assert out["rows"] == 4 and card["filter"] == [{"column": "", "op": "marked", "value": sheet.rules[0].id}]
    assert out["filter_said"] == "marked Not delivered"


def test_only_a_question_asked_beside_a_sheet_gets_the_tool_and_only_with_the_chat_on(env):
    from aughor.agent.converse_tools import converse_tools
    from aughor.sheets.answer import sheet_tools
    sheet = _orders(env)
    plain = [t.name for t in converse_tools("sheets")]
    beside = [t.name for t in converse_tools("sheets", sheet=sheet.id)]
    assert "show_rows" not in plain and beside == plain + ["show_rows"]
    assert sheet_tools("") == []
    with flag_overrides({"sheets.chat": False}):
        assert sheet_tools(sheet.id) == []


def test_the_sheet_tells_the_conversation_how_to_answer_before_its_columns(env):
    from aughor.sheets import chat
    sheet = _orders(env)
    told = chat.explain_sheet(sheet.id)
    keys = list(told)
    assert keys.index("how_to_answer") < keys.index("columns")       # a wide sheet's columns cannot cut it off
    rules = " ".join(told["how_to_answer"])
    assert "show_rows" in rules and "of what whole" in rules and "every group" in rules
    assert "orders" in rules                                           # the sheet's own word for its rows


def test_the_counts_on_the_card_are_citable_by_the_answer(env):
    """The numbers check holds the prose to the turn's cells; the card's counts are pooled with them, so an answer
    that says what the card says is not rewritten."""
    from aughor.agent.converse_tools import ground_answer_numbers
    answer = "3 of 6 orders have no delivered date — 50.0% of the sheet."
    kept, receipt = ground_answer_numbers(answer, [[3, 6, 50.0]], question="which orders were not delivered?")
    assert kept == answer and receipt is None


def test_the_stream_hands_the_sheet_to_the_conversation_and_the_card_to_the_numbers_check(monkeypatch):
    """Driven through the REAL `_stream_converse`, `converse()` stubbed: the sheet on screen reaches the tools, the
    card's frame reaches the page, and its counts reach the check the closing prose is held to."""
    import asyncio
    import json
    import types

    from aughor.routers import investigations as inv
    monkeypatch.setattr(inv, "build_history_section", lambda h: "")
    monkeypatch.setattr(inv, "build_prior_answers_section", lambda a: "")
    monkeypatch.setattr(inv, "resolve_prior_answers", lambda *a, **k: [])
    held: dict = {}

    def _ground(answer, rows, question=""):
        held["rows"] = rows
        return answer, None
    monkeypatch.setattr("aughor.agent.converse_tools.ground_answer_numbers", _ground)
    card = {"sheet": "s1", "rows": 4, "of": 6, "share": 66.7, "filter": [], "said": "x is empty", "about": "x"}

    def _converse(conn, q, *, tool_emit=None, sheet="", **k):
        held["sheet"] = sheet
        tool_emit("sheet_rows", card)
        return types.SimpleNamespace(answer="4 of 6 orders.", steps=[], stop_reason="answered",
                                     injected_chars=0, reinjection_ratio=0.0)
    monkeypatch.setattr("aughor.agent.converse_tools.converse", _converse)

    async def _go():
        return [json.loads(c.split("data: ", 1)[1]) async for c in inv._stream_converse(
            "which orders?", "sheets", [], session_id="sheet-test", sheet="s1:v1") if c.startswith("data: ")]
    frames = asyncio.run(_go())
    assert held["sheet"] == "s1:v1" and [4, 6, 66.7] in held["rows"]
    assert any(f["type"] == "sheet_rows" and f["rows"] == 4 for f in frames)
    focus = types.SimpleNamespace(focus=types.SimpleNamespace(kind="sheet", id="s1:v1"))
    assert inv._sheet_ref(focus) == "s1:v1"
    assert inv._sheet_ref(types.SimpleNamespace(focus=types.SimpleNamespace(kind="metric", id="m"))) == ""
    assert inv._sheet_ref(types.SimpleNamespace(focus=None)) == ""
