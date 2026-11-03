"""A dashboard from a sheet and a sentence: a person says what it should show, and a model drafts the cards.

**This is the one door where a model writes a card's query.** Everywhere else in Dashboards a drafted card is made from a
record someone approved (`dashboards/propose.py`), and that rule stands. A file somebody has just uploaded has no such record,
so here a model may write a SELECT, on these terms, each enforced by code:

- It reads this sheet's table and nothing else. Any other table refuses the card.
- Every card is run on the sheet before it is offered. A figure a person reads is the run's, never the model's.
- What a card means is said in plain words read off its SQL (`dashboards/definitions.py`), never in the model's words.
- What a person is asked, and what could not be made, is checked for stated figures: the model may not state one.
- A scenario must equal the file at its starting values, or it is refused: a what-if that starts by disagreeing with the data
  is not a what-if.
- Nothing is kept until a person keeps it. What they keep is held to the rules again here, whatever was offered.

The model drafts; the platform lays out. It never writes the dashboard's spec, which is built here, by code, from what was ticked.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from aughor.dashboards import queries
from aughor.dashboards.compose import default_spec
from aughor.dashboards.definitions import definition_of
from aughor.sheets import kinds, model
from aughor.sheets.imports import ident
from aughor.sheets.model import Sheet

#: Steps the model may take: a draft and its repairs.
MAX_STEPS = 5
MAX_CARDS = 12
MAX_FILTERS = 4
MAX_INPUTS = 3
MAX_PRESETS = 4
MAX_WORDS = 800
MAX_TITLE = 80
#: Two figures are the same when they differ by less than this, as money read to the cent.
SAME_FIGURE = 0.01
_KEY = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
#: The values a filter counts, for its preview and for the column it draws.
FILTER_VALUES = 12
DRAWN = ("figure", "bar", "line", "area", "table")


class Refused(ValueError):
    """What was asked cannot be drafted or kept; ``str(exc)`` is the sentence to show."""


SYSTEM = (
    "You draft ONE dashboard from a sheet a person has just uploaded, from what they say it should show. Call propose_dashboard "
    "once, with every card, and stop when it is staged. A card reads this sheet's table and no other, with one DuckDB SELECT. "
    "Write each statement so it returns what the card draws: a figure returns one row, with its value in a column; a chart returns "
    "one row per place along the bottom, with a column per series; a table returns its rows. Use only the columns listed, as "
    "they are spelled. Prefer a plain aggregate with a WHERE, or SUM(CASE WHEN ... THEN ... END) per series: a reader is shown "
    "what each card means in words read off its statement, so a simple statement is one they can check. Bars for change over "
    "time, across for a ranking. State no figure in anything you write: the platform runs each card and shows its number. "
    "When what the person asks for cannot be made from these columns, make no card for it: say so in not_made. When you chose "
    "what a word means (which statuses count as open, say), say so in questions, so the person can correct it. Filters are "
    "columns a reader narrows every card by: their choice columns, or a date by month. A scenario is optional, for a what-if "
    "they ask for: an input starts at the value where the scenario equals the file, and its statement reads each input as "
    "{{name}}. Say how each card's values are written: money, or percent for a share. When a draft is refused, repair every "
    "point and propose it again."
)

_CARD = {
    "type": "object",
    "properties": {
        "key": {"type": "string", "description": "A short name of your own, lower case: kept, came-back."},
        "title": {"type": "string", "description": "What the card is called, in the person's words. It states no figure."},
        "sql": {"type": "string", "description": "One DuckDB SELECT on this sheet's table. An input reads as {{name}}."},
        "as": {"type": "string", "enum": list(DRAWN)},
        "x": {"type": "string", "description": "A chart: the column along the bottom, or down the side when across."},
        "series": {"type": "array", "maxItems": queries.MAX_SERIES, "description": "The columns drawn: one for a figure.",
                   "items": {"type": "object", "required": ["column"], "properties": {
                       "column": {"type": "string"},
                       "label": {"type": "string", "description": "What a reader calls it: Kept, Came back."},
                       "tone": {"type": "string", "enum": ["adverse", "open"], "description": (
                           "adverse: what went wrong (returned, cancelled). open: not known yet (still open). Otherwise none.")}}}},
        "format": {"type": "string", "enum": list(queries.BESIDE_FORMATS), "description": "How its values are written: money, percent for a share (0.25 reads as 25%), or number."},
        "segments": {"type": "string", "enum": list(queries.SEGMENTS), "description": "A chart of several series."},
        "across": {"type": "boolean", "description": "Bars that run sideways: a ranking, or shares per category."},
        "beside": {"type": "object", "required": ["column"], "description": "A figure: a second column of its statement, said small beside it.",
                   "properties": {"column": {"type": "string"}, "words": {"type": "string", "description": "What follows it: of finished."},
                                  "format": {"type": "string", "enum": list(queries.BESIDE_FORMATS)}}},
    },
    "required": ["key", "title", "sql", "as"],
}

_PARAMS = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "The dashboard's name, from the person's words."},
        "cards": {"type": "array", "items": _CARD, "maxItems": MAX_CARDS},
        "filters": {"type": "array", "maxItems": MAX_FILTERS, "items": {"type": "object", "required": ["column"], "properties": {
            "column": {"type": "string"}, "label": {"type": "string"},
            "grain": {"type": "string", "enum": ["month"], "description": "A date column, narrowed by its month."}}}},
        "scenario": {"type": "object", "description": "Only when they ask for a what-if.", "required": ["inputs", "scenario_card", "file_card"], "properties": {
            "inputs": {"type": "array", "maxItems": MAX_INPUTS, "items": {"type": "object", "required": ["name", "label", "start", "min", "max"], "properties": {
                "name": {"type": "string", "description": "As the statement reads it: {{name}}. Lower case."},
                "label": {"type": "string"}, "start": {"type": "number"}, "min": {"type": "number"}, "max": {"type": "number"},
                "step": {"type": "number"}, "unit": {"type": "string", "enum": ["percent", "number"],
                                                     "description": "percent: 0.25 reads as 25%."}}}},
            "presets": {"type": "array", "maxItems": MAX_PRESETS, "items": {"type": "object", "required": ["label", "values"], "properties": {
                "label": {"type": "string"}, "values": {"type": "object", "description": "Input name → value."}}}},
            "scenario_card": {"type": "string", "description": "The key of the figure the inputs change."},
            "file_card": {"type": "string", "description": "The key of the figure it must equal at the starting values."}}},
        "questions": {"type": "array", "maxItems": 4, "items": {"type": "object", "required": ["says"], "properties": {
            "says": {"type": "string", "description": "What you chose: Still open counts Processing and Shipped."},
            "instead": {"type": "object", "required": ["label", "cards"], "description": "The other reading, when there is one.", "properties": {
                "label": {"type": "string", "description": "Its button: Only Processing."},
                "cards": {"type": "object", "description": "Card key → its statement under that reading."}}}}}},
        "not_made": {"type": "array", "maxItems": 4, "items": {"type": "object", "required": ["asked", "why"], "properties": {
            "asked": {"type": "string", "description": "What they asked for: Margin."},
            "why": {"type": "string", "description": "This file has no cost column."}}}},
    },
    "required": ["title", "cards"],
}


def _stated(text: str) -> list[str]:
    from aughor.dashboards.validate import stated_figures
    return stated_figures(text or "")


def _shown_of(raw: dict) -> queries.Shown:
    """How a card the model wrote is drawn: always as its statement returns it. The platform does not sum around a model's SQL."""
    series = [{"column": str(s.get("column") or ""), "agg": "sum", "tone": str(s.get("tone") or ""), "label": str(s.get("label") or "")}
              for s in raw.get("series") or [] if isinstance(s, dict)]
    drawn = str(raw.get("as") or "")
    said: dict[str, Any] = {"as": drawn, "summed": False, "series": series, "x": str(raw.get("x") or ""),
                            "segments": str(raw.get("segments") or "stacked"), "across": bool(raw.get("across")),
                            "label": str(raw.get("title") or "")[:MAX_TITLE],
                            "format": str(raw.get("format") or "")}
    beside = raw.get("beside")
    if drawn == "figure" and isinstance(beside, dict) and beside.get("column"):
        said["beside"] = {"column": str(beside["column"]), "words": str(beside.get("words") or ""), "format": str(beside.get("format") or "number")}
    if drawn == "table":
        said.update(series=[], x="")
    return queries.Shown.model_validate(said)


def _size_of(shown: queries.Shown) -> str:
    return {"figure": "small", "table": "full"}.get(shown.as_, "wide")


def _starts(scenario: Optional[dict]) -> dict[str, dict]:
    """Each input at its starting value, as a query card's values are sent."""
    return {str(i["name"]): {"kind": "number", "value": i["start"]} for i in (scenario or {}).get("inputs") or []}


def _labels(scenario: Optional[dict]) -> dict[str, str]:
    return {str(i["name"]): f"your {str(i.get('label') or i['name']).lower()}" for i in (scenario or {}).get("inputs") or []}


def _read_card(sheet: Sheet, db: Any, raw: dict, scenario: Optional[dict]) -> tuple[dict, list[str]]:
    """One card as it would be kept, run on the sheet as it stands, or everything that stops it. Holds a model's card and a
    person's choice of one to the same rules."""
    title = str(raw.get("title") or "").strip()[:MAX_TITLE]
    sql = str(raw.get("sql") or "").strip().rstrip(";")
    named = title or str(raw.get("key") or "a card")
    problems: list[str] = []
    if not title:
        problems.append(f"{named} has no title.")
    if _stated(title):
        problems.append(f'“{title}” states a figure. A title says what the card is; the run says how much.')
    if not sql:
        return {}, problems + [f"{named} has no statement."]
    dialect = queries.dialect_of(db)
    read = queries.tables_of(sql, dialect)
    if read != [sheet.table.lower()]:
        problems.append(f"{named} reads {', '.join(read) or 'no table'}. A card reads {sheet.table} and nothing else.")
        return {}, problems
    try:
        shown = _shown_of(raw)
    except ValueError as exc:
        return {}, problems + [f"How {named} is drawn cannot be read: {exc}"]
    run_sql, params = sql, None
    if queries.params_of(sql):
        try:
            run_sql, params = queries.bind(sql, _starts(scenario))
        except queries.Refused as exc:
            return {}, problems + [f"{named}: {exc}"]
    seconds = queries.time_limit(model.SHEETS_CONNECTION)
    probe = queries.probe(db, run_sql, seconds=seconds, params=params)
    if probe["error"]:
        return {}, problems + [f"{named} did not run: {probe['error']}"]
    columns = probe["columns"]
    shown = queries.normalized(shown, columns)
    wrong = queries.check(shown, columns)
    if wrong:
        return {}, problems + [f"{named}: {w}" for w in wrong]
    ran = queries.run(db, run_sql, shown, columns, seconds=seconds, params=params)
    if ran["error"]:
        return {}, problems + [f"{named} did not run: {ran['error']}"]
    shaped = ran["shown"]
    if shaped.get("as") == "figure" and shaped.get("value") is None:
        problems.append(f"{named} returned no value.")
    if shaped.get("as") not in ("figure", "table") and not shaped.get("points"):
        problems.append(f"{named} returned no rows.")
    figure_column = shown.series[0].column if shown.as_ == "figure" and shown.series else None
    words = definition_of(sql, dialect=dialect, values=_labels(scenario), only=figure_column)
    card = {"key": str(raw.get("key") or ""), "title": title, "sql": sql, "shown": shown.said(), "columns": columns,
            "size": _size_of(shown), "definition": words or "", "preview": shaped, "reads": queries.params_of(sql)}
    return card, problems


def _read_filter(sheet: Sheet, raw: dict, cur: Any) -> tuple[Optional[dict], list[str]]:
    name = str(raw.get("column") or "")
    column = next((c for c in sheet.columns if c.name == name), None)
    if column is None:
        return None, [f"The filter {name or '(no column)'} is not a column of this sheet."]
    grain = str(raw.get("grain") or "")
    dated = column.kind in (kinds.DATE, kinds.DATETIME)
    if grain and (grain != "month" or not dated):
        return None, [f"A filter reads a date by its month, and {name} is not a date."]
    if dated and not grain:
        grain = "month"
    target = f"strftime({ident(name)}, '%Y-%m')" if grain else ident(name)
    rows = cur.execute(f"SELECT {target} AS v, COUNT(*) AS n FROM {ident(sheet.table)} WHERE {ident(name)} IS NOT NULL "
                       f"GROUP BY 1 ORDER BY {'v' if grain else 'n DESC'} LIMIT {FILTER_VALUES + 1}").fetchall()
    if len(rows) < 2:
        return None, [f"{name} holds one value, so there is nothing to narrow by."]
    if len(rows) > FILTER_VALUES and not grain:
        return None, [f"{name} holds more than {FILTER_VALUES} values, too many for a filter column."]
    return {"column": name, "label": str(raw.get("label") or name.replace("_", " ").capitalize())[:40], "grain": grain,
            "values": [[r[0], int(r[1])] for r in rows[:FILTER_VALUES]]}, []


def _read_scenario(raw: Optional[dict], cards: dict[str, dict]) -> tuple[Optional[dict], list[str]]:
    """A scenario, held to the one rule that makes it trustworthy: at its starting values it says what the file says."""
    if not raw:
        return None, []
    problems: list[str] = []
    inputs = []
    for i in raw.get("inputs") or []:
        name = str(i.get("name") or "")
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", name):
            problems.append(f"An input's name is lower case: “{name}”.")
            continue
        try:
            low, high, start = float(i["min"]), float(i["max"]), float(i["start"])
        except (KeyError, TypeError, ValueError):
            problems.append(f"The input {name} needs a start, a least and a most.")
            continue
        if not low <= start <= high or low == high:
            problems.append(f"The input {name} starts outside what it may be.")
            continue
        unit = "percent" if i.get("unit") == "percent" else "number"
        step = float(i.get("step") or ((high - low) / 100))
        inputs.append({"name": name, "label": str(i.get("label") or name)[:40], "start": start, "min": low, "max": high,
                       "step": step, "unit": unit})
    if not inputs:
        problems.append("A scenario has at least one input.")
    known = {i["name"] for i in inputs}
    presets = []
    for p in raw.get("presets") or []:
        values = {str(k): float(v) for k, v in (p.get("values") or {}).items() if isinstance(v, (int, float)) and str(k) in known}
        label = str(p.get("label") or "")[:40]
        if label and values and not _stated(label):
            presets.append({"label": label, "values": values})
    scenario_key, file_key = str(raw.get("scenario_card") or ""), str(raw.get("file_card") or "")
    scenario_card, file_card = cards.get(scenario_key), cards.get(file_key)
    if not scenario_card or not file_card:
        return None, problems + ["A scenario names its scenario_card and file_card, each a figure among the cards."]
    a, b = (scenario_card.get("preview") or {}).get("value"), (file_card.get("preview") or {}).get("value")
    if a is None or b is None:
        problems.append("A scenario's two cards are figures.")
    elif abs(a - b) > SAME_FIGURE:
        problems.append(f"At its starting values the scenario must equal the file: {scenario_key} and {file_key} differ. "
                        "Start each input where it changes nothing.")
    unread = [n for n in scenario_card.get("reads") or [] if n not in known]
    if unread:
        problems.append(f"{scenario_key} reads {', '.join(unread)}, which is no input of the scenario.")
    return {"inputs": inputs, "presets": presets, "scenario_card": scenario_key, "file_card": file_key}, problems


def _read_proposal(sheet: Sheet, args: dict) -> tuple[Optional[dict], list[str]]:
    """Everything the model proposed, read and run: the proposal as a person is shown it, or every fault at once."""
    from aughor.db.connection import open_connection_for
    from aughor.sheets import projection

    problems: list[str] = []
    raw_cards = [c for c in args.get("cards") or [] if isinstance(c, dict)][:MAX_CARDS]
    if not raw_cards:
        return None, ["A dashboard holds at least one card."]
    keys = [str(c.get("key") or "") for c in raw_cards]
    for key in keys:
        if not _KEY.fullmatch(key):
            problems.append(f"A card's key is short and lower case: “{key}”.")
    if len(set(keys)) != len(keys):
        problems.append("Two cards share a key.")
    # The rows are always offered: a person can read what every figure is made from, whether the model thought of it or not.
    if not any(c.get("as") == "table" for c in raw_cards):
        raw_cards = [*raw_cards, {"key": "the-rows", "title": "The rows", "as": "table", "sql": f"SELECT * FROM {ident(sheet.table)}"}]
    raw_scenario = args.get("scenario") if isinstance(args.get("scenario"), dict) else None
    db = open_connection_for(model.SHEETS_CONNECTION)
    cards: dict[str, dict] = {}
    for raw in raw_cards:
        card, wrong = _read_card(sheet, db, raw, raw_scenario)
        problems += wrong
        if card:
            cards[card["key"]] = card
    scenario, wrong = _read_scenario(raw_scenario, cards)
    problems += wrong
    filters = []
    cur = projection.cursor()
    try:
        for raw in [f for f in args.get("filters") or [] if isinstance(f, dict)][:MAX_FILTERS]:
            f, wrong = _read_filter(sheet, raw, cur)
            problems += wrong
            if f:
                filters.append(f)
    finally:
        cur.close()
    questions = []
    for q in [q for q in args.get("questions") or [] if isinstance(q, dict)]:
        says = str(q.get("says") or "").strip()[:240]
        if _stated(says):
            problems.append(f"“{says}” states a figure. Say what you chose, not how much it comes to.")
            continue
        instead = q.get("instead") if isinstance(q.get("instead"), dict) else None
        other = None
        if instead and instead.get("label") and isinstance(instead.get("cards"), dict):
            replaced = {}
            for key, sql in instead["cards"].items():
                base = next((c for c in raw_cards if c.get("key") == key), None)
                if base is None:
                    problems.append(f"The other reading of “{says}” changes {key}, which is not a card.")
                    continue
                card, wrong = _read_card(sheet, db, {**base, "sql": sql}, raw_scenario)
                problems += wrong
                if card:
                    replaced[key] = card
            other = {"label": str(instead["label"])[:40], "cards": replaced}
        if says:
            questions.append({"says": says, "instead": other})
    not_made = []
    for n in [n for n in args.get("not_made") or [] if isinstance(n, dict)]:
        asked, why = str(n.get("asked") or "").strip()[:80], str(n.get("why") or "").strip()[:200]
        if _stated(f"{asked} {why}"):
            problems.append(f"“{asked}: {why}” states a figure.")
        elif asked and why:
            not_made.append({"asked": asked, "why": why})
    if problems:
        return None, problems
    title = str(args.get("title") or sheet.name).strip()[:MAX_TITLE] or sheet.name
    return {"title": title, "cards": list(cards.values()), "filters": filters, "scenario": scenario, "questions": questions,
            "not_made": not_made, "table": sheet.table}, []


def _what_the_model_reads(sheet: Sheet) -> dict:
    """The sheet as the model is told it: the same read the sheet's own chat takes, its columns and a few of their values."""
    from aughor.sheets import chat, projection
    cur = projection.cursor()
    try:
        read = chat._options(sheet, cur)
    finally:
        cur.close()
    read["table"] = sheet.table
    read.pop("other_sheets", None)     # a card reads this sheet alone, so the others are not offered
    return read


def draft(sheet: Sheet, words: str, *, provider: Any = None) -> dict:
    """⚑ Spends model calls: one short run with one tool. What comes back is a proposal, every card already run on the sheet,
    or the reasons there is none. Nothing is kept here."""
    import json

    from aughor.agent.tool_loop import ToolSpec, run_tool_loop

    words = " ".join((words or "").split())[:MAX_WORDS]
    if not words:
        return _nothing("Say what this dashboard should show.")
    if provider is None:
        from aughor.agent.converse_tools import binding_calls_tools
        if not binding_calls_tools():
            return _nothing("The model this install drafts with cannot call tools, so it cannot draft a dashboard. "
                            "Choose one that can in the model settings.")
        from aughor.llm.provider import get_provider
        provider = get_provider("coder")

    held: dict[str, Any] = {}
    faults: list[list[str]] = []

    def propose(args: dict) -> dict:
        proposal, wrong = _read_proposal(sheet, args or {})
        if proposal is None:
            faults.append(wrong)
            return {"staged": False, "refused": wrong}
        held["proposal"] = proposal
        return {"concluded": True, "staged": True, "answer": "Staged. The person checks it."}

    tool = ToolSpec(name="propose_dashboard", description=(
        "Propose the dashboard, whole. Every card is run on the sheet as you call this; every fault comes back at once, to repair "
        "together. When it is staged, you are done."), parameters=_PARAMS, run=propose, concludes=True)
    ask = (f"The sheet:\n{json.dumps(_what_the_model_reads(sheet), default=str)}\n\nThe person asks for: {words}")
    result = run_tool_loop(provider, SYSTEM, ask, [tool], max_steps=MAX_STEPS, conn_id=model.SHEETS_CONNECTION, site="sheets.dashboard_draft")
    if held.get("proposal"):
        return {"drafted": True, "sheet": sheet.id, "connection_id": model.SHEETS_CONNECTION, "words": words,
                "rounds": len(faults) + 1, "stop_reason": result.stop_reason, "sentences": [], **held["proposal"]}
    sentences = list(faults[-1]) if faults else []
    said = (result.answer or "").strip()
    if said and not _stated(said) and not sentences:
        sentences = [said[:400]]
    return {**_nothing(*(sentences or ["The model drafted no dashboard for this, and gave no reason."])),
            "rounds": len(faults), "stop_reason": result.stop_reason}


def _nothing(*sentences: str) -> dict:
    return {"drafted": False, "sentences": list(sentences), "cards": [], "filters": [], "scenario": None, "questions": [], "not_made": []}


# ── what a person keeps ─────────────────────────────────────────────────────

def _section(elements: dict, key: str, title: str, children: list[str], columns: int) -> str:
    elements[key] = {"type": "Section", "props": {"title": title, "columns": max(1, min(columns, 4))}, "children": children}
    return key


def spec_for(title: str, kept: list[dict], *, sheet: Sheet, filters: list[dict], scenario: Optional[dict], add_row: bool) -> dict:
    """The dashboard, written by code from what was ticked: its filter column, then Overview, Rows and What if as each has
    something to hold. ``kept`` is each card with the ``id`` it was kept as."""
    elements: dict[str, dict] = {}
    held = {"figure": [], "chart": [], "table": [], "scenario": []}
    for card in kept:
        key = f"card-{card['key']}"
        elements[key] = {"type": "Card", "props": {"card": card["id"], "size": card["size"]}, "children": []}
        if card.get("scenario_only"):
            continue        # kept for its scenario alone: the person took it off the overview
        if card.get("reads"):
            held["scenario"].append(key)
        elif card["shown"]["as"] == "figure":
            held["figure"].append(key)
        elif card["shown"]["as"] == "table":
            held["table"].append(key)
        else:
            held["chart"].append(key)
    # the figure the scenario is held against stands beside it, on its own tab, as well as in the overview
    if scenario:
        anchor = next((c for c in kept if c["key"] == scenario.get("file_card")), None)
        if anchor is not None:
            twin = f"card-{anchor['key']}-file"
            elements[twin] = {"type": "Card", "props": {"card": anchor["id"], "size": "small"}, "children": []}
            held["scenario"].insert(0, twin)

    overview: list[str] = []
    # the button stands at the top right of whatever the overview opens with: it belongs to the page, not to a section of its own
    leading = ["add-row"] if add_row else []
    if add_row:
        elements["add-row"] = {"type": "AddRow", "props": {"sheet": sheet.id, "size": "full"}, "children": []}
    if held["figure"]:
        overview.append(_section(elements, "sec-figures", "Figures", [*leading, *held["figure"]], len(held["figure"])))
        leading = []
    if held["chart"] or leading:
        overview.append(_section(elements, "sec-pictures", "Pictures", [*leading, *held["chart"]], 2))
    tabs: list[tuple[str, str, list[str]]] = []
    if overview:
        tabs.append(("overview", "Overview", overview))
    if held["table"]:
        tabs.append(("rows", "Rows", [_section(elements, "sec-rows", "The rows", held["table"], 1)]))
    if scenario and held["scenario"]:
        elements["scenario-inputs"] = {"type": "ScenarioInputs", "props": {
            "values": [i["name"] for i in scenario["inputs"]], "presets": scenario.get("presets") or [], "size": "full"}, "children": []}
        tabs.append(("what-if", "What if", [
            _section(elements, "sec-inputs", "A scenario, not your data", ["scenario-inputs"], 1),
            _section(elements, "sec-scenario", "What it comes to", held["scenario"], min(3, len(held["scenario"]))),
        ]))

    # the root's stored name and type are the dashboards' own, so they are taken from where they are kept
    spec: dict[str, Any] = default_spec(title, [])
    spec["elements"].update(elements)
    elements = spec["elements"]
    root_children: list[str] = []
    if filters:
        elements["filters"] = {"type": "QueryFilters", "props": {"table": sheet.table, "columns": [
            {"column": f["column"], "label": f["label"], **({"grain": f["grain"]} if f.get("grain") else {})} for f in filters]}, "children": []}
        root_children.append("filters")
    if len(tabs) > 1:
        tab_keys = []
        for name, label, children in tabs:
            key = f"tab-{name}"
            elements[key] = {"type": "Tab", "props": {"name": name, "label": label}, "children": children}
            tab_keys.append(key)
        elements["tabs"] = {"type": "Tabs", "props": {"value": {"$bindState": "/tab"}}, "children": tab_keys}
        root_children.append("tabs")
        spec["state"] = {"tab": tabs[0][0]}
    else:
        root_children += tabs[0][2] if tabs else []
    elements[spec["root"]]["children"] = root_children
    if scenario:
        spec["values"] = {i["name"]: {"label": i["label"], "kind": "number", "value": i["start"], "from": {
            "by": "reader", "slider": {"min": i["min"], "max": i["max"], "step": i["step"], "unit": i["unit"]}}} for i in scenario["inputs"]}
    return spec


def keep(sheet: Sheet, home: Any, *, title: str, cards: list[dict], filters: list[dict], scenario: Optional[dict], add_row: bool,
         approved_by: str, dashboard_id: str) -> dict:
    """Keep what a person ticked, all of it or none: every card held to the rules and run again, kept as a card of theirs, then
    the dashboard, written by code. If the dashboard is refused, the cards made for it are taken away again."""
    from aughor.cards.models import StoredCard
    from aughor.cards.store import delete_card
    from aughor.dashboards import cards as own_cards
    from aughor.dashboards import versions
    from aughor.db.connection import open_connection_for
    from aughor.sheets import projection

    title = (title or "").strip()[:MAX_TITLE]
    if not title:
        raise Refused("A dashboard has a name.")
    if not cards and not filters:
        raise Refused("Nothing is ticked, so there is nothing to keep.")
    db = open_connection_for(model.SHEETS_CONNECTION)
    problems: list[str] = []
    read: list[dict] = []
    for raw in cards:
        shown = raw.get("shown") if isinstance(raw.get("shown"), dict) else {}
        card, wrong = _read_card(sheet, db, {**shown, "key": raw.get("key"), "title": raw.get("title"), "sql": raw.get("sql")}, scenario)
        problems += wrong
        if card:
            read.append({**card, "scenario_only": bool(raw.get("scenario_only"))})
    checked_filters = []
    cur = projection.cursor()
    try:
        for raw in filters[:MAX_FILTERS]:
            f, wrong = _read_filter(sheet, raw, cur)
            problems += wrong
            if f:
                checked_filters.append(f)
    finally:
        cur.close()
    if scenario:
        by_key = {c["key"]: c for c in read}
        scenario, wrong = _read_scenario(scenario, by_key)
        problems += wrong
    if problems:
        raise Refused(" ".join(problems))

    made: list[dict] = []
    try:
        for card in read:
            stored = StoredCard(connection_id=model.SHEETS_CONNECTION, source="authored",
                                kind="kpi" if card["shown"]["as"] == "figure" else "chart", title=card["title"], sql=card["sql"],
                                render={"shown": card["shown"], "columns": card["columns"], "definition": card["definition"],
                                        "drafted_by_model": True, "standing": True})
            saved = own_cards.place(home, stored)
            made.append({**card, "id": saved.id})
        spec = spec_for(title, made, sheet=sheet, filters=checked_filters, scenario=scenario, add_row=add_row)
        kept = versions.keep(home, spec, approved_by=approved_by, also_known=[c["id"] for c in made], written_by_model=True,
                             source=f"Drafted by a model from the sheet {sheet.name}; each card run on it and kept by a person")
        if not kept.kept:
            raise Refused(" ".join(kept.sentences) or "The dashboard could not be kept.")
    except Exception:
        for card in made:
            delete_card(card["id"])
        raise
    return {"connection_id": model.SHEETS_CONNECTION, "dashboard_id": dashboard_id, "title": title, "version": kept.version,
            "cards": len(made)}
