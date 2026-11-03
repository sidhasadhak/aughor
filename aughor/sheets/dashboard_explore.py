"""A model explores a sheet, when a person asks it to, and says what a dashboard of it should show.

Someone who has just uploaded a file often does not know yet what to ask of it. So they may ask a model to look: it runs its own
queries, reads what comes back, and writes the words a person would otherwise have typed. Those words are a suggestion. They go in
the box for the person to change, or straight on to `dashboard_draft.draft`, whose terms are unchanged.

This spends more than a draft does, so it runs only on a person's demand, and these terms are enforced by code:

- A look reads this sheet's table and nothing else (`queries.reads_beyond`), through the door every person's SQL meets: read-only,
  bounded, stopped after the connection's time limit, redacted.
- It takes at most `MAX_LOOKS` looks and is shown at most `LOOK_ROWS` rows of each, and the page says so before anyone presses it.
- What it writes states no figure. A figure a person reads is a run's, never a model's, here as in the draft.
- It must look before it writes: words about a file it never read are what a person could guess for themselves.
- A person sees each look as it happens, with its query, and leaving stops the spending at the next step.

Nothing is kept here.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import threading
from typing import Any, AsyncIterator, Callable, Optional

from aughor.dashboards import queries
from aughor.sheets import dashboard_draft as drafts
from aughor.sheets import model
from aughor.sheets.model import Sheet

logger = logging.getLogger(__name__)

#: How many queries a run may take, and the rows of each it reads. Said on the page: change them there too.
MAX_LOOKS = 16
LOOK_ROWS = 30
#: Room for what it writes and for repairing it, beyond the looks.
MAX_STEPS = MAX_LOOKS + 4
#: A value in a look, as the model reads it. A long text says little more than its start, and is paid for on every later step.
LOOK_VALUE = 120
MAX_WHY = 120
MAX_BRIEF = 700

SYSTEM = (
    "You explore ONE sheet a person has just uploaded. They want a dashboard from it and have not decided what it should show. "
    "Find out what this file is about and what is worth watching in it, then say so.\n\n"
    "Use look to run queries on this sheet's table. Start with what the rows are: over what dates, what each choice column holds, "
    "what is empty and when. Then follow what you find: how things change over time, which categories differ, what is unusual, and "
    "which columns mean something only together, such as a date promised and a date done. One idea per look. Aggregate: a look "
    f"returns at most {LOOK_ROWS} rows. Stop when another look would change nothing, usually within ten.\n\n"
    "Then call write_brief once. words: what the dashboard should show, as the person might have typed it themselves, in two to "
    "four plain sentences naming the measures and what they are split by, and only what these columns can show. noticed: what you "
    "found that they should know before relying on it, such as a column empty until something happens, months that are thin, or a "
    "value that does not mean what it seems to. Say what is in the file, not how to draw it.\n\n"
    "State no figure in anything you write: the platform runs each card and shows its number. Say what you found without how much: "
    "most orders arrive early, not the percentage."
)

_LOOK = {
    "type": "object",
    "properties": {
        "why": {"type": "string", "description": "What you are checking, in a few plain words, shown to the person: Which statuses exist. It states no figure."},
        "sql": {"type": "string", "description": "One DuckDB SELECT on this sheet's table, and no other."},
    },
    "required": ["why", "sql"],
}

_BRIEF = {
    "type": "object",
    "properties": {
        "words": {"type": "string", "description": "What the dashboard should show, as the person might have typed it. States no figure."},
        "noticed": {"type": "array", "maxItems": drafts.MAX_NOTICED, "items": {"type": "string"},
                    "description": f"What they should know before relying on it. One short sentence each, at most {drafts.MAX_NOTE} characters, stating no figure."},
    },
    "required": ["words"],
}


class _Stopped(Exception):
    """The person left, so no more is spent."""


def _short(value: Any) -> Any:
    return value[:LOOK_VALUE] if isinstance(value, str) else value


def read_look(sheet: Sheet, db: Any, sql: str) -> dict:
    """One look, as the model reads it: its columns and first rows, or why it was refused."""
    sql = (sql or "").strip().rstrip(";")
    if not sql:
        return {"refused": "A look is one SELECT."}
    dialect = queries.dialect_of(db)
    beyond = queries.reads_beyond(sql, sheet.table, dialect)
    if beyond:
        return {"refused": f"That reads {', '.join(beyond)}. Read {sheet.table} and nothing else."}
    if queries.params_of(sql):
        return {"refused": "A look has no {{inputs}}. Write the value it should read."}
    out = queries.probe(db, sql, seconds=queries.time_limit(model.SHEETS_CONNECTION), rows=LOOK_ROWS)
    if out["error"]:
        return {"refused": f"It did not run: {out['error']}"}
    rows = out["rows"]
    return {"columns": [c.get("name") for c in out["columns"]], "rows": [[_short(v) for v in row] for row in rows[:LOOK_ROWS]],
            "more": len(rows) > LOOK_ROWS}


def _read_brief(args: dict, looks: int) -> tuple[Optional[dict], list[str]]:
    """What it wrote, or every fault at once."""
    if not looks:
        return None, ["Look at the file first: run at least one query."]
    words = " ".join(str(args.get("words") or "").split())
    problems: list[str] = []
    if not words:
        problems.append("Say what the dashboard should show.")
    elif len(words) > MAX_BRIEF:
        problems.append(f"Say it in fewer words: at most {MAX_BRIEF} characters.")
    stated = drafts._stated(words)
    if stated:
        problems.append(f"The words state {', '.join(stated)}. Say what to show, not how much it comes to.")
    raw = args.get("noticed") if isinstance(args.get("noticed"), list) else []
    noticed = []
    for said in raw[:drafts.MAX_NOTICED]:
        note = " ".join(str(said).split())
        if len(note) > drafts.MAX_NOTE:     # never cut: a note read to its end says what it meant
            problems.append(f"“{note[:60]}…” is too long. Say it in at most {drafts.MAX_NOTE} characters.")
        elif drafts._stated(note):
            problems.append(f"“{note}” states a figure. Say what you found, not how much.")
        elif note:
            noticed.append(note)
    return (None, problems) if problems else ({"words": words, "noticed": noticed}, [])


def explore(sheet: Sheet, *, focus: str = "", provider: Any = None, on_look: Optional[Callable[[dict], None]] = None,
            stop: Optional[threading.Event] = None) -> dict:
    """⚑ Spends model calls: up to `MAX_STEPS`. What comes back is the words and what was noticed, or the reasons there are none,
    with every look it took. ``on_look`` hears each look as it happens; ``stop``, when set, ends the run at the next step."""
    from aughor.agent.tool_loop import LoopStep, ToolSpec, run_tool_loop
    from aughor.db.connection import open_connection_for

    if provider is None:
        provider, why = drafts.model_that_calls_tools()
        if provider is None:
            return {"explored": False, "sentences": [why], "looks": []}

    db = open_connection_for(model.SHEETS_CONNECTION)
    looks: list[dict] = []
    held: dict[str, Any] = {}
    faults: list[list[str]] = []

    def look(args: dict) -> dict:
        args = args or {}
        if len(looks) >= MAX_LOOKS:
            return {"refused": "That is every look you have. Call write_brief now."}
        sql = str(args.get("sql") or "")
        why = " ".join(str(args.get("why") or "").split())[:MAX_WHY]
        out = read_look(sheet, db, sql)
        looked = {"why": why if why and not drafts._stated(why) else "A query", "sql": sql.strip(),
                  "rows": len(out.get("rows") or []), "more": bool(out.get("more")), "refused": out.get("refused") or ""}
        looks.append(looked)
        if on_look is not None:
            on_look(looked)
        return out

    def write_brief(args: dict) -> dict:
        brief, wrong = _read_brief(args or {}, sum(1 for done in looks if not done["refused"]))
        if brief is None:
            faults.append(wrong)
            return {"written": False, "refused": wrong}
        held["brief"] = brief
        return {"concluded": True, "written": True, "answer": "Written. The person reads it next."}

    def stop_when_asked(_: LoopStep) -> None:
        if stop is not None and stop.is_set():
            raise _Stopped

    tools = [ToolSpec(name="look", description="Run one SELECT on this sheet's table and read what it returns.", parameters=_LOOK, run=look),
             ToolSpec(name="write_brief", description="Say what the dashboard should show, once you have looked. When it is written, you are done.",
                      parameters=_BRIEF, run=write_brief, concludes=True)]
    ask = f"The sheet:\n{json.dumps(drafts._what_the_model_reads(sheet), default=str)}"
    focus = " ".join((focus or "").split())[:drafts.MAX_WORDS]
    if focus:
        ask += f"\n\nThe person has started with these words. Keep what they ask for, and build on it: {focus}"
    try:
        result = run_tool_loop(provider, SYSTEM, ask, tools, max_steps=MAX_STEPS, on_step=stop_when_asked,
                               conn_id=model.SHEETS_CONNECTION, site="sheets.dashboard_explore")
    except _Stopped:
        return {"explored": False, "stopped": True, "sentences": [], "looks": looks}
    if held.get("brief"):
        return {"explored": True, "sheet": sheet.id, "looks": looks, "stop_reason": result.stop_reason, "sentences": [], **held["brief"]}
    sentences = list(faults[-1]) if faults else ["The model looked at the file and wrote nothing, and gave no reason."]
    return {"explored": False, "sentences": sentences, "looks": looks, "stop_reason": result.stop_reason}


def run(sheet: Sheet, *, focus: str, draw: bool, push: Callable[[dict], None], stop: Optional[threading.Event] = None,
        provider: Any = None) -> None:
    """⚑ Explore, say each thing as it happens, and with ``draw`` go on to draft the cards from what was written."""
    out = explore(sheet, focus=focus, provider=provider, stop=stop, on_look=lambda looked: push({"type": "look", **looked}))
    if out.get("stopped"):
        return
    if not out["explored"]:
        push({"type": "failed", "sentences": out["sentences"]})
        return
    push({"type": "explored", "words": out["words"], "noticed": out["noticed"], "looks": out["looks"]})
    if not draw or (stop is not None and stop.is_set()):
        return
    push({"type": "drafting"})
    push({"type": "drafted", "draft": drafts.draft(sheet, out["words"], noticed=out["noticed"], provider=provider)})


async def frames(sheet: Sheet, *, focus: str, draw: bool, provider: Any = None) -> AsyncIterator[str]:
    """`run` as a stream of `data:` records. The run has a thread of its own, reading as the person who asked. When they leave, this
    is cancelled and it stops at its next step. Every stream ends with an ``end`` record, so one cut short can be told from a whole
    one."""
    loop = asyncio.get_running_loop()
    heard: asyncio.Queue[Optional[dict]] = asyncio.Queue()
    stop = threading.Event()
    who = contextvars.copy_context()

    def push(frame: dict) -> None:
        loop.call_soon_threadsafe(heard.put_nowait, frame)

    def work() -> None:
        try:
            run(sheet, focus=focus, draw=draw, push=push, stop=stop, provider=provider)
        except Exception as exc:
            logger.exception("exploring a sheet failed")
            push({"type": "failed", "sentences": [f"The exploring stopped: {str(exc)[:300]}"]})
        finally:
            push({"type": "end"})
            loop.call_soon_threadsafe(heard.put_nowait, None)

    running = asyncio.ensure_future(asyncio.to_thread(who.run, work))
    try:
        while True:
            frame = await heard.get()
            if frame is None:
                break
            yield f"data: {json.dumps(frame, default=str)}\n\n"
        await running
    finally:
        stop.set()
