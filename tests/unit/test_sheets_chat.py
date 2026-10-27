"""Arc SH, SH-4 — the chat beside a sheet (ROADMAP §3.64).

The model is the repo's faux backend, scripted call by call: no credentials, no network, no spend. What is asserted is
what the platform did with what the model asked for — and the falsifier: the view the chat is handed counts the same
rows as the grid, and the filter it is handed, run through the Sheets connection, returns that count.
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
o6,shipped,2018-09-30 10:00:00,2018-10-25 00:00:00,
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("AUGHOR_SYSTEM_DB", str(tmp_path / "system.db"))
    monkeypatch.delenv("AUGHOR_TOOL_LOOP_STEPS", raising=False)
    from aughor.actions import overlay
    monkeypatch.setattr(overlay, "_DB_PATH", tmp_path / "overlay.db")
    from aughor.sheets import projection
    projection.reset()
    with flag_overrides({"sheets.core": True, "sheets.grid": True, "sheets.chat": True, "sheets.combine": True}):
        yield tmp_path
    projection.reset()


@pytest.fixture
def faux():
    from aughor.llm.provider import LLMProvider
    return LLMProvider(backend="faux", role="coder")


def _call(tool="propose_sheet_changes", **args):
    from aughor.llm.faux import FauxToolCall
    return FauxToolCall(payload=args, name=tool)


def _orders(env):
    from aughor.sheets import files, service
    path = env / "olist_orders_dataset.csv"
    path.write_text(ORDERS)
    return service.create_from_file(files.stage(path, path.name), name="Olist orders", by="user:ana",
                                    chosen={"order_estimated_delivery_date": "date"})


OPEN = [{"column": "order_status", "op": "not_in", "value": ["delivered", "canceled"]},
        {"column": "order_estimated_delivery_date", "op": "before", "value": "2018-10-17"}]


def test_the_view_the_chat_is_handed_counts_the_rows_the_grid_shows(env):
    """SH-4's falsifier: the grid's count, the grounding's count and the grounding's filter run as SQL agree."""
    from aughor.sheets import chat, projection, service
    from aughor.sheets.connection import SheetsConnection
    from aughor.sheets.model import Condition, View
    sheet = _orders(env)
    view = View(id="", name="Overdue, still open",
                filter=[Condition(column=sheet.column(c["column"]).id, op=c["op"], value=c["value"]) for c in OPEN])
    sheet = service.save_view(sheet, view, by="user:ana")
    kept = sheet.views[-1]
    grid = projection.read_rows(sheet, conditions=kept.filter)["total"]
    told = chat.explain_sheet(f"{sheet.id}:{kept.id}")
    assert told["found"] and told["view"]["rows"] == grid == 2          # o3, o4: open and past their estimate
    run = SheetsConnection().execute("t", f"SELECT COUNT(*) FROM {told['table']} WHERE {told['view']['where']}")
    assert run.error is None, run.error
    assert int(run.rows[0][0]) == grid
    assert "by calendar day" in next(c for c in told["columns"] if c["name"] == "order_estimated_delivery_date")[
        "compare"]


def test_a_computed_column_is_an_expression_over_the_rows_own_values_only(env):
    from aughor.sheets import chat
    sheet = _orders(env)
    ok = chat.check_expression(sheet, "date_diff('day', \"order_estimated_delivery_date\", DATE '2018-10-17')")
    assert "DATE_DIFF" in ok.upper()
    for bad, why in [("(SELECT COUNT(*) FROM olist_orders)", "not allowed"),
                     ("read_csv('/etc/passwd')", "not a function"),
                     ("getenv('HOME')", "not a function"),
                     ('"no_such_column" + 1', "not a column"),
                     ("x.order_id", "not a column")]:
        with pytest.raises(chat.ChangeRefused, match=why):
            chat.check_expression(sheet, bad)


def test_a_proposal_is_checked_and_counted_then_applied_in_part_as_one_change(env, faux):
    from aughor.llm.faux import set_responses
    from aughor.sheets import chat, model, projection, service
    sheet = _orders(env)
    changes = [
        {"type": "view", "name": "Overdue, still open", "filter": OPEN},
        {"type": "computed_column", "name": "Days overdue",
         "expression": "date_diff('day', \"order_estimated_delivery_date\", DATE '2018-10-17')"},
        {"type": "column", "name": "Followed up", "kind": "yesno"},
    ]
    set_responses([_call(op="options"), _call(op="propose", changes=changes), "Proposed."])
    out = chat.propose(sheet, "Flag the ones that still need following up.", by="user:ana", provider=faux)
    assert out["staged"], out
    p = out["proposal"]
    assert [c["type"] for c in p["changes"]] == ["view", "computed_column", "column"]
    assert p["changes"][0]["rows"] == 2                                 # counted by the platform, not said by a model
    assert model.get(sheet.id).columns == sheet.columns                  # nothing changed yet
    applied = chat.apply(p["id"], [0, 1], by="user:ana")
    now = model.get(sheet.id)
    assert [v.name for v in now.views][-1] == "Overdue, still open" and now.column("Followed up") is None
    days = now.column("Days overdue")
    assert days.role == "computed" and days.made_by == "the assistant"
    assert now.change.origin == f"proposal:{p['id']}" and now.change.by == "user:ana"
    assert (projection.read_row(now, 4) or {})[days.id] == 715           # 2016-11-01 → 2018-10-17
    assert chat.proposal(p["id"])["state"] == "applied"
    with pytest.raises(service.Refused, match="not waiting"):
        chat.apply(p["id"], None, by="user:ana")
    service.undo(now, by="user:ana")
    back = model.get(sheet.id)
    assert back.column("Days overdue") is None and len(back.views) == 1
    assert applied["change_id"] and projection.check(back)["same"]


def test_a_refused_change_goes_back_to_the_model_and_is_repaired(env, faux):
    from aughor.llm.faux import set_responses
    from aughor.sheets import chat
    sheet = _orders(env)
    set_responses([_call(op="options"),
                   _call(op="propose", changes=[{"type": "computed_column", "name": "Bad",
                                                 "expression": "read_csv('x.csv')"}]),
                   _call(op="propose", changes=[{"type": "column", "name": "Checked", "kind": "yesno"}]),
                   "Done."])
    out = chat.propose(sheet, "add a check box", by="user:ana", provider=faux)
    assert out["staged"] and out["rounds"] == 2


def test_when_nothing_is_staged_the_reasons_are_the_platforms(env, faux):
    from aughor.llm.faux import set_responses
    from aughor.sheets import chat
    sheet = _orders(env)
    set_responses([_call(op="options"), "About 40% of these are late, nothing to add."])
    out = chat.propose(sheet, "what should I change", by="user:ana", provider=faux)
    assert not out["staged"]
    assert out["sentences"] == ["The model proposed no change for this, and gave no reason."]


def test_a_dropped_file_becomes_one_proposal_and_undo_removes_the_sheet_whole(env, faux):
    from aughor.llm.faux import set_responses
    from aughor.sheets import chat, files, model, service
    path = env / "olist_order_reviews.csv"
    path.write_text("review_id,order_id,review_score,review_comment_message\nr1,o1,1,late\nr2,o2,5,\n"
                    "r3,o3,2,broken\nr4,o4,4,\n")
    token = files.stage(path, path.name)
    set_responses([_call(tool="propose_sheet", op="options"),
                   _call(tool="propose_sheet", op="propose", name="Olist reviews", changes=[
                       {"type": "view", "name": "Needs a reply",
                        "filter": [{"column": "review_score", "op": "lte", "value": 2},
                                   {"column": "review_comment_message", "op": "not_empty"}]}]),
                   "Proposed."])
    out = chat.propose_new_sheet(token, "make this a sheet I can follow up complaints from", by="user:ana",
                                 provider=faux)
    p = out["proposal"]
    assert p["new_sheet"] and p["name"] == "Olist reviews" and p["changes"][0]["rows"] == 2
    assert model.list_sheets() == []                                     # nothing made yet
    made = chat.apply(p["id"], None, by="user:ana")
    sheet = model.get(made["sheet"])
    assert [v.name for v in sheet.views] == ["All reviews", "Needs a reply"]
    service.undo(sheet, by="user:ana", removing=True)
    assert model.get(made["sheet"]) is None


def test_off_the_chat_explains_nothing_and_answers_no_route(env):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from aughor.agent.spotlight_explain import KINDS, explain_object
    from aughor.routers import sheets as sheets_router
    sheet = _orders(env)
    assert "sheet" not in KINDS                       # the explain tool a model calls reads as it did
    with flag_overrides({"sheets.chat": False}):
        assert explain_object("sheets", {"kind": "sheet", "id": sheet.id})["found"] is False
        app = FastAPI()
        app.include_router(sheets_router.router)
        client = TestClient(app)
        assert client.post(f"/sheets/{sheet.id}/propose", json={"words": "x"}).status_code == 404
        assert client.get(f"/sheets/{sheet.id}/grounding").status_code == 404
