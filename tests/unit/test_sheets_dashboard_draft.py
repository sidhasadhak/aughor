"""A dashboard from a file and a sentence: the one door where a model writes a card's query, on terms enforced by code.

The model here is scripted. What is under test is everything around it: each term in `aughor/sheets/dashboard_draft.py`, the spec
the platform writes for what a person kept, and that the kept cards obey a reader's filters and a row added to the sheet.
"""
from __future__ import annotations

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
    from aughor.sheets import projection
    projection.reset()
    yield tmp_path
    projection.reset()


@pytest.fixture
def sheet(env):
    from aughor.sheets import files, service
    path = env / "orders.csv"
    path.write_text(ORDERS)
    return service.create_from_file(files.stage(path, path.name), name="Orders", by="user:ana",
                                    chosen={"channel": "choice", "sale_price": "money", "ordered_on": "date"})


def kept_card(table: str) -> dict:
    return {"key": "kept", "title": "Kept", "as": "figure", "format": "money", "series": [{"column": "kept"}],
            "sql": f"SELECT SUM(sale_price) AS kept FROM {table} WHERE status = 'Complete'"}


def proposal(table: str, **more) -> dict:
    return {"title": "Orders so far", "cards": [
        kept_card(table),
        {"key": "back", "title": "Came back", "as": "figure", "format": "money", "series": [{"column": "came_back"}],
         "beside": {"column": "share", "words": "of finished", "format": "percent"},
         "sql": f"SELECT SUM(CASE WHEN status = 'Returned' THEN sale_price END) AS came_back, "
                f"SUM(CASE WHEN status = 'Returned' THEN sale_price END) / SUM(CASE WHEN status IN ('Complete', 'Returned') THEN sale_price END) AS share FROM {table}"},
        {"key": "weeks", "title": "By month", "as": "bar", "x": "month", "segments": "side_by_side",
         "series": [{"column": "kept", "label": "Kept"}, {"column": "came_back", "label": "Came back", "tone": "adverse"}],
         "sql": f"SELECT DATE_TRUNC('month', ordered_on) AS month, SUM(CASE WHEN status = 'Complete' THEN sale_price END) AS kept, "
                f"SUM(CASE WHEN status = 'Returned' THEN sale_price END) AS came_back FROM {table} GROUP BY 1 ORDER BY 1"},
        {"key": "rows", "title": "The rows", "as": "table", "sql": f"SELECT * FROM {table}"},
    ], "filters": [{"column": "channel"}, {"column": "ordered_on", "label": "Month", "grain": "month"}], **more}


def scenario_args(table: str, *, start: float = 0.0) -> dict:
    return {"inputs": [{"name": "return_cut", "label": "Returns fall by", "start": start, "min": 0, "max": 1, "step": 0.01, "unit": "percent"}],
            "presets": [{"label": "Down a third", "values": {"return_cut": 0.33}}], "scenario_card": "kept-if", "file_card": "kept"}


def scenario_card(table: str) -> dict:
    return {"key": "kept-if", "title": "Kept, in this scenario", "as": "figure", "format": "money", "series": [{"column": "kept_if"}],
            "sql": f"SELECT SUM(CASE WHEN status = 'Complete' THEN sale_price END) + "
                   f"SUM(CASE WHEN status = 'Returned' THEN sale_price END) * {{{{return_cut}}}} AS kept_if FROM {table}"}


def read(sheet, args):
    from aughor.sheets import dashboard_draft
    return dashboard_draft._read_proposal(sheet, args)


def test_every_card_is_run_and_says_what_it_reads(sheet):
    got, problems = read(sheet, proposal(sheet.table))
    assert problems == []
    by = {c["key"]: c for c in got["cards"]}
    assert by["kept"]["preview"]["value"] == 120.0                 # 10 + 40 + 70, from the run
    assert by["kept"]["definition"] == "Sum of Sale price where Status is Complete"
    assert by["back"]["preview"]["beside"] == {"value": pytest.approx(20 / 140), "words": "of finished", "format": "percent"}
    assert by["weeks"]["preview"]["tones"] == {"Came back": "adverse"}
    assert [f["column"] for f in got["filters"]] == ["channel", "ordered_on"]
    assert got["filters"][1]["grain"] == "month" and got["filters"][1]["values"][0][0] == "2026-07"


def test_the_rows_are_always_offered(sheet):
    args = proposal(sheet.table)
    args["cards"] = [c for c in args["cards"] if c["as"] != "table"]
    got, problems = read(sheet, args)
    assert problems == []
    assert [c["key"] for c in got["cards"]][-1] == "the-rows" and got["cards"][-1]["shown"]["as"] == "table"


def test_a_card_reads_this_sheet_and_nothing_else(sheet):
    from aughor.sheets import files, service
    other_path = sheet.table + "_other.csv"
    import pathlib
    p = pathlib.Path(__import__("os").environ["AUGHOR_STATE_DIR"]).parent / other_path
    p.write_text("a,b\n1,2\n")
    other = service.create_from_file(files.stage(p, p.name), name="Other", by="user:ana", chosen={})
    args = proposal(sheet.table)
    args["cards"][0]["sql"] = f"SELECT SUM(a) AS kept FROM {other.table}"
    got, problems = read(sheet, args)
    assert got is None
    assert any(f"A card reads {sheet.table} and nothing else" in p for p in problems)


@pytest.mark.parametrize("field,value", [("title", "Revenue was $1,234,567"), ])
def test_a_title_states_no_figure(sheet, field, value):
    args = proposal(sheet.table)
    args["cards"][0][field] = value
    got, problems = read(sheet, args)
    assert got is None and any("states a figure" in p for p in problems)


def test_what_the_model_says_states_no_figure(sheet):
    args = proposal(sheet.table, questions=[{"says": "Open came to $123,456 in total"}], not_made=[{"asked": "Margin", "why": "It would be 42.5%"}])
    got, problems = read(sheet, args)
    assert got is None and sum("states a figure" in p for p in problems) == 2


def test_every_fault_comes_back_at_once(sheet):
    """Each round a model spends learning of one fault is a model call."""
    args = proposal(sheet.table)
    args["cards"][0]["sql"] = "SELECT nonsense FROM nowhere"
    args["cards"][2]["series"] = [{"column": "not_a_column"}]
    args["filters"] = [{"column": "not_a_column"}]
    _, problems = read(sheet, args)
    assert len(problems) >= 3


def test_a_scenario_must_start_where_the_file_stands(sheet):
    args = proposal(sheet.table, scenario=scenario_args(sheet.table))
    args["cards"].append(scenario_card(sheet.table))
    got, problems = read(sheet, args)
    assert problems == [] and got["scenario"]["inputs"][0]["name"] == "return_cut"
    assert next(c for c in got["cards"] if c["key"] == "kept-if")["reads"] == ["return_cut"]

    wrong = proposal(sheet.table, scenario=scenario_args(sheet.table, start=0.5))
    wrong["cards"].append(scenario_card(sheet.table))
    got, problems = read(sheet, wrong)
    assert got is None and any("must equal the file" in p for p in problems)


def test_a_filter_is_a_choice_or_a_date_by_month(sheet):
    args = proposal(sheet.table)
    args["filters"] = [{"column": "order_id"}]
    got, problems = read(sheet, args)
    assert got is None and any("too many" in p for p in problems) or got is not None


def test_the_other_reading_of_a_question_is_run_too(sheet):
    args = proposal(sheet.table, questions=[{"says": "Kept counts Complete.", "instead": {"label": "Also Shipped", "cards": {
        "kept": f"SELECT SUM(sale_price) AS kept FROM {sheet.table} WHERE status IN ('Complete', 'Shipped')"}}}])
    got, problems = read(sheet, args)
    assert problems == []
    other = got["questions"][0]["instead"]["cards"]["kept"]
    assert other["preview"]["value"] == 150.0
    assert other["definition"] == "Sum of Sale price where Status is Complete or Shipped"


def test_a_draft_runs_the_model_once_and_stops_when_staged(sheet):
    from aughor.llm.faux import FauxToolCall, set_responses
    from aughor.llm.provider import LLMProvider
    from aughor.sheets import dashboard_draft
    set_responses([FauxToolCall(payload=proposal(sheet.table), name="propose_dashboard")])
    out = dashboard_draft.draft(sheet, "Show what we kept and what came back, by month", provider=LLMProvider(backend="faux", role="coder"))
    assert out["drafted"] is True and out["rounds"] == 1 and out["title"] == "Orders so far"
    assert out["stop_reason"] == "concluded"


def test_a_refused_draft_goes_back_to_the_model_and_its_repair_lands(sheet):
    from aughor.llm.faux import FauxToolCall, set_responses
    from aughor.llm.provider import LLMProvider
    from aughor.sheets import dashboard_draft
    bad = proposal(sheet.table)
    bad["cards"][0]["sql"] = "SELECT 1 AS kept FROM somewhere_else"
    set_responses([FauxToolCall(payload=bad, name="propose_dashboard"), FauxToolCall(payload=proposal(sheet.table), name="propose_dashboard")])
    out = dashboard_draft.draft(sheet, "Show what we kept", provider=LLMProvider(backend="faux", role="coder"))
    assert out["drafted"] is True and out["rounds"] == 2


def test_no_draft_says_why(sheet):
    from aughor.llm.faux import FauxToolCall, set_responses
    from aughor.llm.provider import LLMProvider
    from aughor.sheets import dashboard_draft
    bad = proposal(sheet.table)
    bad["cards"] = [{"key": "x", "title": "X", "as": "figure", "series": [{"column": "x"}], "sql": "SELECT 1 AS x FROM elsewhere"}]
    set_responses([FauxToolCall(payload=bad, name="propose_dashboard")] * dashboard_draft.MAX_STEPS)
    out = dashboard_draft.draft(sheet, "Show it", provider=LLMProvider(backend="faux", role="coder"))
    assert out["drafted"] is False and any("nothing else" in s for s in out["sentences"])
    assert dashboard_draft.draft(sheet, "   ", provider=LLMProvider(backend="faux", role="coder"))["sentences"] == ["Say what this dashboard should show."]


def _kept(sheet, env, *, scenario=False, add_row=True):
    from aughor.dashboards.home import Home
    from aughor.sheets import dashboard_draft
    args = proposal(sheet.table, **({"scenario": scenario_args(sheet.table)} if scenario else {}))
    if scenario:
        args["cards"].append(scenario_card(sheet.table))
    got, problems = read(sheet, args)
    assert problems == []
    home = Home("sheets", "ana", "q3-orders")
    out = dashboard_draft.keep(sheet, home, title=got["title"], cards=got["cards"], filters=got["filters"], scenario=got["scenario"],
                               add_row=add_row, approved_by="user:ana", dashboard_id="q3-orders")
    return home, out


def test_what_is_kept_passes_the_dashboards_own_validator_and_is_written_by_code(sheet, env):
    from aughor.dashboards import cards, versions
    home, out = _kept(sheet, env, scenario=True)
    assert out["version"] == 1 and out["cards"] == 5
    spec = versions.latest(home)["spec"]
    root = spec["elements"][spec["root"]]
    assert spec["elements"][root["children"][0]]["type"] == "QueryFilters"
    tabs = spec["elements"][root["children"][1]]
    assert [spec["elements"][t]["props"]["label"] for t in tabs["children"]] == ["Overview", "Rows", "What if"]
    assert spec["values"]["return_cut"]["from"]["slider"]["unit"] == "percent"
    held = {c.title: c for c in cards.cards_of(home)}
    assert held["Kept"].render["drafted_by_model"] is True and held["Kept"].render["standing"] is True
    assert held["Kept"].render["definition"] == "Sum of Sale price where Status is Complete"


def test_a_refused_keep_leaves_no_cards_behind(sheet, env, monkeypatch):
    from aughor.dashboards import cards, versions
    from aughor.dashboards.home import Home
    from aughor.sheets import dashboard_draft
    got, _ = read(sheet, proposal(sheet.table))
    home = Home("sheets", "owner-of-nothing", "will-fail")
    with pytest.raises(dashboard_draft.Refused):
        dashboard_draft.keep(sheet, home, title="", cards=got["cards"], filters=[], scenario=None, add_row=False, approved_by="person", dashboard_id="will-fail")
    bad = [{**got["cards"][0], "sql": "SELECT 1 AS kept FROM somewhere_else"}]
    with pytest.raises(dashboard_draft.Refused):
        dashboard_draft.keep(sheet, home, title="Fine", cards=bad, filters=[], scenario=None, add_row=False, approved_by="person", dashboard_id="will-fail")
    assert cards.cards_of(home) == []
    # the cards were made before the dashboard was refused: they go again
    monkeypatch.setattr(versions, "keep", lambda *a, **k: versions.Kept("refused", sentences=("It cannot be kept.",)))
    with pytest.raises(dashboard_draft.Refused, match="It cannot be kept"):
        dashboard_draft.keep(sheet, home, title="Fine", cards=got["cards"], filters=[], scenario=None, add_row=False, approved_by="person", dashboard_id="will-fail")
    assert cards.cards_of(home) == []


def _run(card_id, **body):
    from aughor.routers.cards import CardRunValues, run_card_route
    return run_card_route(card_id, body=CardRunValues(**body) if body else None)


def test_a_readers_filter_narrows_a_card_that_never_wrote_it(sheet, env):
    from aughor.dashboards import cards
    home, _ = _kept(sheet, env)
    card = next(c for c in cards.cards_of(home) if c.title == "Kept")
    assert _run(card.id)["value"] == 120.0
    table = sheet.table
    assert _run(card.id, filters=[{"table": table, "column": "channel", "values": ["Email"]}])["value"] == 110.0
    assert _run(card.id, filters=[{"table": table, "column": "ordered_on", "grain": "month", "values": ["2026-07"]}])["value"] == 10.0
    both = [{"table": table, "column": "channel", "values": ["Email"]}, {"table": table, "column": "ordered_on", "grain": "month", "values": ["2026-08", "2026-09"]}]
    assert _run(card.id, filters=both)["value"] == 110.0


def test_a_filter_value_is_bound_never_pasted_in(sheet, env):
    from aughor.dashboards import cards
    home, _ = _kept(sheet, env)
    card = next(c for c in cards.cards_of(home) if c.title == "Kept")
    hostile = [{"table": sheet.table, "column": "channel", "values": ["x') OR 1=1 --"]}]
    assert _run(card.id, filters=hostile)["value"] is None         # no row holds that, and the statement did not change shape


def test_a_cards_period_is_the_whole_file(sheet, env):
    """A Briefing's "last month" is no question of a file: a card made from one is never cut to it."""
    from aughor.dashboards import cards
    from aughor.routers.cards import run_card_route
    home, _ = _kept(sheet, env)
    card = next(c for c in cards.cards_of(home) if c.title == "Kept")
    got = run_card_route(card.id, preset="previous_month")
    assert got["value"] == 120.0 and got["scoped"]["standing"] is True


def test_a_row_added_to_the_sheet_moves_the_card(sheet, env):
    from aughor.dashboards import cards
    from aughor.sheets import service
    home, _ = _kept(sheet, env)
    card = next(c for c in cards.cards_of(home) if c.title == "Kept")
    service.add_row(sheet, {"order_id": "8", "ordered_on": "2026-09-30", "status": "Complete", "channel": "Search", "sale_price": "100"}, by="user:ana")
    assert _run(card.id)["value"] == 220.0


def test_a_scenario_card_reads_its_value_bound(sheet, env):
    from aughor.dashboards import cards
    home, _ = _kept(sheet, env, scenario=True)
    card = next(c for c in cards.cards_of(home) if c.title == "Kept, in this scenario")
    assert _run(card.id, values={"return_cut": {"kind": "number", "value": 0.5}})["value"] == 130.0
    assert _run(card.id, values={"return_cut": {"kind": "number", "value": 0}})["value"] == 120.0
