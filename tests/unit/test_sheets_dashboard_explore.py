"""A model explores a sheet on a person's demand, and writes what a dashboard of it should show, on terms enforced by code.

The model here is scripted. What is under test is everything around it: what a look may read on the real engine, the budget, that
what it writes states no figure, that leaving stops the spending, and the two paths out, words to change and cards straight away.
A card a person changes while checking a draft is here too: it asks no model, and is held to the same rules.
"""
from __future__ import annotations

import json

import pytest

ORDERS = """order_id,ordered_on,status,channel,sale_price
1,2026-07-01,Complete,Search,10.00
2,2026-07-02,Returned,Search,20.00
3,2026-07-15,Shipped,Email,30.00
4,2026-08-03,Complete,Email,40.00
5,2026-08-04,Processing,Search,50.00
6,2026-09-05,Cancelled,Search,60.00
7,2026-09-06,Complete,Email,70.00
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("AUGHOR_SYSTEM_DB", str(tmp_path / "system.db"))
    from aughor.actions import overlay
    monkeypatch.setattr(overlay, "_DB_PATH", tmp_path / "overlay.db")
    from aughor.llm import faux
    from aughor.sheets import projection
    projection.reset()
    faux.reset()
    yield tmp_path
    faux.reset()
    projection.reset()


def _make(env, name: str, text: str, **chosen):
    from aughor.sheets import files, service
    path = env / f"{name}.csv"
    path.write_text(text)
    return service.create_from_file(files.stage(path, path.name), name=name.capitalize(), by="user:ana", chosen=chosen)


@pytest.fixture
def sheet(env):
    return _make(env, "orders", ORDERS, channel="choice", sale_price="money", ordered_on="date")


@pytest.fixture
def db(sheet):
    from aughor.db.connection import open_connection_for
    from aughor.sheets import model
    return open_connection_for(model.SHEETS_CONNECTION)


def faux_model():
    from aughor.llm.provider import LLMProvider
    return LLMProvider(backend="faux", role="coder")


def look(sql: str, why: str = "Which statuses exist"):
    from aughor.llm.faux import FauxToolCall
    return FauxToolCall(payload={"why": why, "sql": sql}, name="look")


def brief(words: str = "What we sold and what came back, by month and by channel.", noticed=("Cancelled orders still carry a price.",)):
    from aughor.llm.faux import FauxToolCall
    return FauxToolCall(payload={"words": words, "noticed": list(noticed)}, name="write_brief")


def by_status(table: str) -> str:
    return f"SELECT status, COUNT(*) AS n FROM {table} GROUP BY 1 ORDER BY 2 DESC"


# ── what a statement may read, on the real engine ────────────────────────────

@pytest.mark.parametrize("escape", [
    "SELECT * FROM {t}, query_table('{o}')",
    "SELECT * FROM {t}, query('SELECT * FROM {o}')",
    "SELECT * FROM query('SELECT content FROM read_text(''{f}'')')",
    "SELECT * FROM {t}, query('SELECT content FROM read_text(''{f}'')')",
    "SELECT (SELECT string_agg(table_name, ',') FROM duckdb_tables()) AS x FROM {t}",
    "SELECT (SELECT MAX(value) FROM duckdb_settings()) AS x FROM {t}",
    "SELECT (SELECT string_agg(name, ',') FROM pragma_table_info('{o}')) AS x FROM {t}",
    "SELECT (SELECT content FROM read_text('{f}')) AS x FROM {t}",
    "SELECT * FROM {t}, '{f}'",
    "SELECT * FROM {o}",
    "SELECT * FROM {t} JOIN {o} USING (order_id)",
    "SELECT * FROM main.{o}, {t}",
    "SELECT * FROM information_schema.{t}",     # the last part of its name is this sheet's: another schema is still another table
    "SELECT (SELECT MAX(table_name) FROM information_schema.tables) AS x FROM {t}",
    "WITH x AS (SELECT * FROM {o}) SELECT * FROM x, {t}",
    "WITH x AS (SELECT 1 AS one) SELECT * FROM x",
    "SELECT 1 AS one",
])
def test_a_look_and_a_card_read_this_sheet_and_nothing_else(env, sheet, db, escape):
    from aughor.sheets import dashboard_draft, dashboard_explore
    other = _make(env, "other", "order_id,secret\n1,hush\n")
    outside = env / "outside.txt"
    outside.write_text("on disk\n")
    sql = escape.format(t=sheet.table, o=other.table, f=outside)
    out = dashboard_explore.read_look(sheet, db, sql)
    assert "refused" in out and "rows" not in out, out
    assert "hush" not in json.dumps(out) and "on disk" not in json.dumps(out)
    card, problems = dashboard_draft._read_card(sheet, db, {"key": "x", "title": "X", "as": "table", "sql": sql}, None)
    assert card == {} and any("nothing else" in p for p in problems), problems


def test_a_statement_in_a_string_is_refused_at_the_door_every_connection_shares(env, sheet, db):
    """`query()` holds a statement in a string, where no check can read it: it read a file past the denylist."""
    from aughor.dashboards import queries
    outside = env / "outside.txt"
    outside.write_text("on disk\n")
    for sql in (f"SELECT * FROM query('SELECT content FROM read_text(''{outside}'')')", f"SELECT * FROM query_table('{sheet.table}')"):
        out = queries.probe(db, sql, seconds=5)
        assert out["error"] and "BLOCKED" in out["error"] and out["rows"] == []


@pytest.mark.parametrize("fine", [
    "SELECT status, COUNT(*) AS n FROM {t} GROUP BY 1",
    "WITH done AS (SELECT * FROM {t} WHERE status = 'Complete') SELECT COUNT(*) AS n FROM done",
    "SELECT d.day, COUNT(o.order_id) AS n FROM generate_series(DATE '2026-07-01', DATE '2026-07-03', INTERVAL 1 DAY) AS d(day) LEFT JOIN {t} o ON o.ordered_on = d.day GROUP BY 1",
    "SELECT COUNT(*) AS n FROM {t} WHERE order_id IN (SELECT order_id FROM {t} WHERE status = 'Returned')",
])
def test_what_a_look_may_do_with_this_sheet(sheet, db, fine):
    from aughor.sheets import dashboard_explore
    out = dashboard_explore.read_look(sheet, db, fine.format(t=sheet.table))
    assert "refused" not in out, out
    assert out["rows"]


def test_a_look_reads_a_few_rows_and_says_there_are_more(env, db):
    from aughor.sheets import dashboard_explore
    rows = "\n".join(f"{i},{'x' * 500}" for i in range(dashboard_explore.LOOK_ROWS + 10))
    long = _make(env, "long", f"id,note\n{rows}\n")
    out = dashboard_explore.read_look(long, db, f"SELECT id, note FROM {long.table}")
    assert len(out["rows"]) == dashboard_explore.LOOK_ROWS and out["more"] is True
    assert len(out["rows"][0][1]) == dashboard_explore.LOOK_VALUE


# ── exploring ────────────────────────────────────────────────────────────────

def test_it_looks_and_then_writes_the_words(sheet):
    from aughor.llm.faux import calls, set_responses
    from aughor.sheets import dashboard_explore
    set_responses([look(by_status(sheet.table)), look(f"SELECT channel, SUM(sale_price) AS s FROM {sheet.table} GROUP BY 1", "How channels compare"), brief()])
    heard: list[dict] = []
    out = dashboard_explore.explore(sheet, provider=faux_model(), on_look=heard.append)
    assert out["explored"] is True and out["stop_reason"] == "concluded"
    assert out["words"] == "What we sold and what came back, by month and by channel."
    assert out["noticed"] == ["Cancelled orders still carry a price."]
    assert [h["why"] for h in heard] == ["Which statuses exist", "How channels compare"]
    assert heard[0]["sql"] == by_status(sheet.table) and heard[0]["rows"] == 5 and heard[0]["refused"] == ""
    assert out["looks"] == heard
    assert len(calls()) == 3


def test_what_a_person_started_with_goes_to_the_model(sheet):
    from aughor.llm.faux import calls, set_responses
    from aughor.sheets import dashboard_explore
    set_responses([look(by_status(sheet.table)), brief()])
    dashboard_explore.explore(sheet, focus="What came back, by channel", provider=faux_model())
    assert "What came back, by channel" in calls()[0].user


def test_it_must_look_before_it_writes(sheet):
    from aughor.llm.faux import set_responses
    from aughor.sheets import dashboard_explore
    set_responses([brief(), look(by_status(sheet.table)), brief()])
    out = dashboard_explore.explore(sheet, provider=faux_model())
    assert out["explored"] is True and len(out["looks"]) == 1


def test_a_refused_look_is_not_a_look_at_the_file(env, sheet):
    from aughor.llm.faux import set_responses
    from aughor.sheets import dashboard_explore
    other = _make(env, "other", "a,b\n1,2\n")
    set_responses([look(f"SELECT * FROM {other.table}"), brief(), look(by_status(sheet.table)), brief()])
    out = dashboard_explore.explore(sheet, provider=faux_model())
    assert out["explored"] is True
    assert out["looks"][0]["refused"] and out["looks"][0]["rows"] == 0 and not out["looks"][1]["refused"]


@pytest.mark.parametrize("words,noticed", [("Revenue reached $1,234,567 this year.", []), ("What we sold.", ["Most orders, 92%, arrive early."])])
def test_what_it_writes_states_no_figure(sheet, words, noticed):
    from aughor.llm.faux import set_responses
    from aughor.sheets import dashboard_explore
    set_responses([look(by_status(sheet.table)), brief(words, noticed), brief()])
    out = dashboard_explore.explore(sheet, provider=faux_model())
    assert out["explored"] is True and out["words"].startswith("What we sold and")


def test_a_note_too_long_is_sent_back_rather_than_cut(sheet):
    """A real model wrote a fifth note that a cut at the limit ended mid-word: "and deliver"."""
    from aughor.llm.faux import set_responses
    from aughor.sheets import dashboard_draft, dashboard_explore
    fine = "Late deliveries cluster in some months."
    set_responses([look(by_status(sheet.table)), brief(noticed=[fine, "x" * (dashboard_draft.MAX_NOTE + 1)]), brief(noticed=[fine, "Short."])])
    out = dashboard_explore.explore(sheet, provider=faux_model())
    assert out["explored"] is True and out["noticed"] == [fine, "Short."]


def test_a_look_that_states_a_figure_is_shown_plainly(sheet):
    from aughor.llm.faux import set_responses
    from aughor.sheets import dashboard_explore
    set_responses([look(by_status(sheet.table), "Whether 92% arrive early"), brief()])
    assert dashboard_explore.explore(sheet, provider=faux_model())["looks"][0]["why"] == "A query"


def test_it_has_a_budget_and_says_when_it_writes_nothing(sheet):
    from aughor.llm.faux import calls, set_responses
    from aughor.sheets import dashboard_explore
    set_responses([look(by_status(sheet.table))] * dashboard_explore.MAX_STEPS + ["I looked at it."])
    out = dashboard_explore.explore(sheet, provider=faux_model())
    assert out["explored"] is False and out["sentences"]
    assert len(out["looks"]) == dashboard_explore.MAX_LOOKS       # refused past it, and not run
    assert len(calls()) <= dashboard_explore.MAX_STEPS + 1


def test_leaving_stops_the_spending_at_the_next_step(sheet):
    import threading

    from aughor.llm.faux import calls, pending, set_responses
    from aughor.sheets import dashboard_explore
    set_responses([look(by_status(sheet.table)), look(by_status(sheet.table)), look(by_status(sheet.table)), brief()])
    stop = threading.Event()
    out = dashboard_explore.explore(sheet, provider=faux_model(), stop=stop, on_look=lambda _: stop.set())
    assert out["explored"] is False and out["stopped"] is True
    assert len(calls()) == 1 and pending() == 3


def test_a_person_leaving_the_stream_stops_the_spending(sheet):
    """What the door does when a browser goes away: Starlette closes the stream, and the run stops at its next step."""
    import asyncio
    import time

    from aughor.llm.faux import calls, pending, set_responses
    from aughor.sheets import dashboard_explore
    set_responses([look(by_status(sheet.table))] * 6 + [brief()])

    async def leave_after_the_first() -> str:
        stream = dashboard_explore.frames(sheet, focus="", draw=True, provider=faux_model())
        first = await stream.__anext__()
        await stream.aclose()
        return first
    assert '"type": "look"' in asyncio.run(leave_after_the_first())
    made = -1
    for _ in range(50):         # the run has a thread of its own, which notices at its next step
        if len(calls()) == made:
            break
        made = len(calls())
        time.sleep(0.05)
    assert made < 7 and pending() > 0


# ── the two paths out, through the door ──────────────────────────────────────

def _frames(sheet, body: dict) -> list[dict]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from aughor.routers.sheets import router
    app = FastAPI()
    app.include_router(router)
    got = TestClient(app).post(f"/sheets/{sheet.id}/dashboard/explore", json=body)
    assert got.status_code == 200 and got.headers["content-type"].startswith("text/event-stream")
    return [json.loads(line[len("data: "):]) for line in got.text.split("\n\n") if line.startswith("data: ")]


def _card(table: str) -> dict:
    return {"key": "kept", "title": "Kept", "as": "figure", "format": "money", "series": [{"column": "kept"}],
            "sql": f"SELECT SUM(sale_price) AS kept FROM {table} WHERE status = 'Complete'"}


@pytest.fixture
def faux_coder(monkeypatch):
    from aughor.sheets import dashboard_draft
    monkeypatch.setattr(dashboard_draft, "model_that_calls_tools", lambda: (faux_model(), None))


def test_the_door_hands_back_words_to_change_and_drafts_nothing(sheet, faux_coder):
    from aughor.llm.faux import calls, set_responses
    set_responses([look(by_status(sheet.table)), brief()])
    frames = _frames(sheet, {"focus": "", "draw": False})
    assert [f["type"] for f in frames] == ["look", "explored", "end"]
    assert frames[1]["words"].startswith("What we sold") and frames[1]["looks"][0]["rows"] == 5
    assert len(calls()) == 2


def test_the_door_draws_it_right_away_from_what_it_found(sheet, faux_coder):
    from aughor.llm.faux import FauxToolCall, calls, set_responses
    draft = {"title": "Orders so far", "cards": [_card(sheet.table)]}
    set_responses([look(by_status(sheet.table)), brief(), FauxToolCall(payload=draft, name="propose_dashboard")])
    frames = _frames(sheet, {"focus": "", "draw": True})
    assert [f["type"] for f in frames] == ["look", "explored", "drafting", "drafted", "end"]
    drafted = frames[3]["draft"]
    assert drafted["drafted"] is True and drafted["words"].startswith("What we sold")
    by = {c["key"]: c for c in drafted["cards"]}
    assert by["kept"]["preview"]["value"] == 120.0                 # from the run on the file
    asked = calls()[-1].user
    assert "What we sold and what came back" in asked and "Cancelled orders still carry a price." in asked


def test_the_door_says_why_when_it_could_not_explore(sheet, monkeypatch):
    from aughor.sheets import dashboard_draft
    monkeypatch.setattr(dashboard_draft, "model_that_calls_tools", lambda: (None, "This install cannot."))
    frames = _frames(sheet, {"focus": "", "draw": True})
    assert frames == [{"type": "failed", "sentences": ["This install cannot."]}, {"type": "end"}]


def test_a_failure_partway_is_said_and_the_stream_still_ends(sheet, monkeypatch):
    from aughor.sheets import dashboard_draft
    def broken():
        raise RuntimeError("the model is away")
    monkeypatch.setattr(dashboard_draft, "model_that_calls_tools", broken)
    frames = _frames(sheet, {"focus": "", "draw": False})
    assert [f["type"] for f in frames] == ["failed", "end"] and "the model is away" in frames[0]["sentences"][0]


def test_a_draft_says_when_the_words_are_too_long_rather_than_cutting_them(sheet):
    """The change asked for last is what a cut would lose."""
    from aughor.llm.faux import calls
    from aughor.sheets import dashboard_draft
    out = dashboard_draft.draft(sheet, "x " * dashboard_draft.MAX_WORDS, provider=faux_model())
    assert out["drafted"] is False and "fewer" in out["sentences"][0]
    assert calls() == ()


def test_what_was_noticed_is_read_again_before_a_model_sees_it(sheet):
    from aughor.sheets import dashboard_draft
    assert dashboard_draft.notes_of(["Fine.", "Most orders, 92%, arrive early.", "", 7, *["Again."] * 9]) == ["Fine.", "7", *["Again."] * 3]
    assert dashboard_draft.notes_of("not a list") == []


# ── a card a person changes ──────────────────────────────────────────────────

def drafted_card(sheet, key="kept") -> dict:
    from aughor.sheets import dashboard_draft
    got, problems = dashboard_draft._read_proposal(sheet, {"title": "T", "cards": [
        _card(sheet.table),
        {"key": "months", "title": "By month", "as": "bar", "x": "month", "series": [{"column": "sold", "label": "Sold"}, {"column": "back", "label": "Came back", "tone": "adverse"}],
         "sql": f"SELECT DATE_TRUNC('month', ordered_on) AS month, SUM(sale_price) AS sold, SUM(CASE WHEN status = 'Returned' THEN sale_price END) AS back FROM {sheet.table} GROUP BY 1 ORDER BY 1"},
    ]})
    assert problems == []
    card = next(c for c in got["cards"] if c["key"] == key)
    return {k: card[k] for k in ("key", "title", "sql", "shown")}


def test_a_changed_query_runs_and_says_what_it_now_means_with_no_model(sheet):
    from aughor.llm.faux import calls
    from aughor.sheets import dashboard_draft
    card = {**drafted_card(sheet), "title": "Kept or shipped",
            "sql": f"SELECT SUM(sale_price) AS kept FROM {sheet.table} WHERE status IN ('Complete', 'Shipped')"}
    out = dashboard_draft.check_card(sheet, card)
    assert out["sentences"] == []
    assert out["card"]["title"] == "Kept or shipped" and out["card"]["preview"]["value"] == 150.0
    assert out["card"]["definition"] == "Sum of Sale price where Status is Complete or Shipped"
    assert calls() == ()


def test_a_query_that_returns_another_column_still_draws(sheet):
    from aughor.sheets import dashboard_draft
    card = {**drafted_card(sheet), "sql": f"SELECT SUM(sale_price) AS total FROM {sheet.table}"}
    out = dashboard_draft.check_card(sheet, card)
    assert out["card"]["shown"]["series"][0]["column"] == "total" and out["card"]["preview"]["value"] == 280.0
    assert out["card"]["shown"]["format"] == ""        # it was money; what this value is written as is not known


def test_a_changed_query_keeps_how_its_value_is_written_while_it_is_the_same_value(sheet):
    from aughor.sheets import dashboard_draft
    card = {**drafted_card(sheet), "sql": f"SELECT SUM(sale_price) AS kept FROM {sheet.table} WHERE status = 'Shipped'"}
    assert dashboard_draft.check_card(sheet, card)["card"]["shown"]["format"] == "money"


def test_a_chart_keeps_its_labels_and_draws_a_column_added_to_it(sheet):
    from aughor.sheets import dashboard_draft
    card = drafted_card(sheet, "months")
    card["sql"] = (f"SELECT DATE_TRUNC('month', ordered_on) AS month, SUM(sale_price) AS sold, SUM(CASE WHEN status = 'Returned' THEN sale_price END) AS back, "
                   f"COUNT(*) AS items FROM {sheet.table} GROUP BY 1 ORDER BY 1")
    out = dashboard_draft.check_card(sheet, card)
    series = {s["column"]: s for s in out["card"]["shown"]["series"]}
    assert list(series) == ["sold", "back", "items"]
    assert series["sold"]["label"] == "Sold" and series["back"]["tone"] == "adverse"


def test_a_chart_whose_columns_all_changed_is_refit_to_them(sheet):
    from aughor.sheets import dashboard_draft
    card = {**drafted_card(sheet, "months"), "sql": f"SELECT channel, SUM(sale_price) AS total FROM {sheet.table} GROUP BY 1 ORDER BY 1"}
    out = dashboard_draft.check_card(sheet, card)
    assert out["card"]["shown"]["x"] == "channel" and [s["column"] for s in out["card"]["shown"]["series"]] == ["total"]


@pytest.mark.parametrize("change,says", [
    (lambda t: {"sql": "SELECT 1 AS kept FROM elsewhere"}, "nothing else"),
    (lambda t: {"sql": f"SELECT * FROM {t}, query_table('{t}')"}, "nothing else"),
    (lambda t: {"sql": f"SELECT no_such_column FROM {t}"}, "did not run"),
    (lambda t: {"sql": f"SELECT status FROM {t} LIMIT 1"}, "number"),
    (lambda t: {"title": ""}, "no title"),
    (lambda t: {"title": "Revenue was $1,234,567"}, "states a figure"),
    (lambda t: {"sql": ""}, "no statement"),
])
def test_a_changed_card_meets_the_same_rules(sheet, change, says):
    from aughor.sheets import dashboard_draft
    out = dashboard_draft.check_card(sheet, {**drafted_card(sheet), **change(sheet.table)})
    assert out["card"] is None and any(says in s for s in out["sentences"]), out


def test_a_changed_query_reading_a_value_no_scenario_has_is_refused_and_said(sheet):
    from aughor.sheets import dashboard_draft
    card = {**drafted_card(sheet), "sql": f"SELECT SUM(sale_price) * {{{{nothing}}}} AS kept FROM {sheet.table}"}
    out = dashboard_draft.check_card(sheet, card)
    assert out["card"] is None and out["sentences"] and "Kept" in out["sentences"][0]


def test_a_change_that_breaks_a_scenario_is_said_at_once(sheet):
    from aughor.sheets import dashboard_draft
    t = sheet.table
    scenario = {"inputs": [{"name": "cut", "label": "Cut", "start": 0, "min": 0, "max": 1, "step": 0.01, "unit": "percent"}], "presets": [], "scenario_card": "kept-if", "file_card": "kept"}
    twin = {"key": "kept-if", "title": "Kept if", "sql": f"SELECT SUM(CASE WHEN status = 'Complete' THEN sale_price END) + {{{{cut}}}} * 10 AS kept_if FROM {t}",
            "shown": {"as": "figure", "series": [{"column": "kept_if"}], "format": "money"}}
    fine = dashboard_draft.check_card(sheet, drafted_card(sheet), scenario=scenario, twin=twin)
    assert fine["card"] is not None
    moved = {**drafted_card(sheet), "sql": f"SELECT SUM(sale_price) AS kept FROM {t}"}
    out = dashboard_draft.check_card(sheet, moved, scenario=scenario, twin=twin)
    assert out["card"] is None and any("must equal the file" in s for s in out["sentences"])


def test_a_kept_card_remembers_a_person_changed_it(sheet, env):
    from aughor.dashboards import cards
    from aughor.dashboards.home import Home
    from aughor.sheets import dashboard_draft
    home = Home("sheets", "ana", "d-changed")
    changed = dashboard_draft.check_card(sheet, {**drafted_card(sheet), "title": "Kept by us"})["card"]
    out = dashboard_draft.keep(sheet, home, title="Orders", filters=[], scenario=None, add_row=False, approved_by="user:ana", dashboard_id="d-changed", cards=[
        {"key": changed["key"], "title": changed["title"], "sql": changed["sql"], "shown": changed["shown"], "edited": True}, drafted_card(sheet, "months")])
    assert out["cards"] == 2
    held = {c.title: c for c in cards.cards_of(home)}
    assert held["Kept by us"].render["changed_by_person"] is True and held["Kept by us"].render["drafted_by_model"] is True
    assert "changed_by_person" not in held["By month"].render
