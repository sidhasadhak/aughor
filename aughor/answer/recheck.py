"""Tell people when an answer they were given is no longer true (IDEAS.md 5, PENDING.md item 8).

"On Tuesday we told you 1,744. With the rows that arrived since, it is now 1,802." A product
recall, for numbers.

Measured 2026-09-23 before this was written: nothing re-checked a chat answer, ever. Each
answer's history row already keeps the query that produced it and the rows it returned
(``report.sql`` / ``columns`` / ``rows`` — for a conversational turn too, filed from its
envelope), and a Slack answer's thread is its ``session_id`` (``slack:<channel>:<ts>``). So the
recall needs no new store and no model:

1. **Re-run** the answer's own query, read-only, on its own connection.
2. **Compare** what it returns now with what the person was given — row by row on the
   answer's own labels (the non-numeric columns), number by number, at the departure gate's
   noise band (a move under 5% is not news). A stored table whose columns are not that query's
   result — a table the model wrote into its prose — is NOT compared, and says so.
3. **Say why it moved.** With the source's learned settling lag (idea 4) and a date column in
   the answer: a changed day that was still inside the lag when the answer was given is LATE
   ROWS; a day that had already settled is a RESTATEMENT. Without either, it says it cannot
   tell — never a guess.
4. **Record** the re-check on the answer's own row (``report.rechecks``, appended, never
   rewritten), so the answer and every later reading of it stay side by side.
5. **Tell** the person where they were answered: a Slack answer gets a reply in its own thread,
   through the departure gate like every message that leaves; a web answer shows it on the
   answer. The same change is never told twice.

Off by default (flag ``answers.recheck``). Off → nothing runs, nothing is written, nothing sent.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Optional

FLAG = "answers.recheck"

#: Answers given in the last this-many days are re-checked; older ones are history.
WINDOW_DAYS = 14
#: At most this many answers re-run per daily pass — a bound on warehouse cost, not a sample.
PER_RUN = 40
#: An answer re-checked this recently is skipped by the daily pass (a manual re-check is not).
RECHECK_EVERY_HOURS = 20
#: How many changed numbers a message names before "and N more".
NAMED_CHANGES = 3

RunSql = Callable[[str], tuple]


def enabled() -> bool:
    try:
        from aughor.kernel.flags import flag_enabled
        return flag_enabled(FLAG)
    except Exception:  # noqa: BLE001 — an unreadable flag registry is "off"
        return False


def _noise_rel() -> float:
    from aughor.govern.departure import NOISE_REL
    return NOISE_REL


# ── comparing two results ──────────────────────────────────────────────────────────────────

_DATEISH = re.compile(r"^\d{4}-\d{2}-\d{2}")
_KEY_NAME = re.compile(r"(^|_)(id|date|day|week|month|year|quarter|period|code)$|_at$|_on$", re.I)


def _number(cell) -> Optional[float]:
    if isinstance(cell, bool) or cell is None:
        return None
    if isinstance(cell, (int, float)):
        return float(cell)
    try:
        return float(str(cell).replace(",", ""))
    except ValueError:
        return None


def _roles(columns: list[str], rows: list[list]) -> tuple[list[int], list[int]]:
    """(label columns, measure columns). A column is a measure when every value it holds is
    a number and its name does not read as an id or a date; the rest label the row."""
    labels, measures = [], []
    for i, name in enumerate(columns):
        cells = [r[i] for r in rows if i < len(r) and r[i] is not None]
        numeric = bool(cells) and all(_number(c) is not None for c in cells)
        (measures if numeric and not _KEY_NAME.search(str(name)) else labels).append(i)
    return labels, measures


def _day_of(row: list, labels: list[int]) -> Optional[str]:
    for i in labels:
        if i < len(row) and _DATEISH.match(str(row[i] or "")):
            return str(row[i])[:10]
    return None


def diff_results(old_columns: list, old_rows: list, new_columns: list, new_rows: list) -> dict:
    """What changed between the result a person was given and the same query's result now.
    Pure. ``{"comparable": bool, "reason", "changes": [...], "compared", "missing_rows",
    "new_rows"}``; each change is ``{"label", "column", "old", "new", "rel", "day"}``."""
    norm = [str(c).lower() for c in old_columns or []]
    if norm != [str(c).lower() for c in new_columns or []]:
        return {"comparable": False, "changes": [], "compared": 0, "missing_rows": 0, "new_rows": 0,
                "reason": ("the stored table is not this query's result (its columns differ from "
                           "what the query returns), so there is nothing to compare it with")}
    old_rows = [list(r.values()) if isinstance(r, dict) else list(r) for r in old_rows or []]
    new_rows = [list(r.values()) if isinstance(r, dict) else list(r) for r in new_rows or []]
    labels, measures = _roles(list(old_columns), old_rows)
    if not measures:
        return {"comparable": False, "changes": [], "compared": 0, "missing_rows": 0, "new_rows": 0,
                "reason": "the answer holds no number to re-check"}
    if not labels and not (len(old_rows) == 1 and len(new_rows) == 1):
        return {"comparable": False, "changes": [], "compared": 0, "missing_rows": 0, "new_rows": 0,
                "reason": "its rows have no label to match on, so a changed row cannot be told apart"}

    def key(row):
        return tuple(str(row[i]) if i < len(row) else "" for i in labels)

    fresh = {key(r): r for r in new_rows}
    noise = _noise_rel()
    changes, compared, missing = [], 0, 0
    for row in old_rows:
        now = fresh.get(key(row))
        if now is None:
            missing += 1
            continue
        for i in measures:
            old, new = _number(row[i] if i < len(row) else None), _number(now[i] if i < len(now) else None)
            if old is None or new is None:
                continue
            compared += 1
            base = max(abs(old), abs(new))
            rel = 0.0 if base == 0 else (new - old) / (abs(old) if old else base)
            if base and abs(new - old) / base >= noise:
                changes.append({"label": {str(old_columns[j]): row[j] for j in labels},
                                "column": str(old_columns[i]), "old": old, "new": new,
                                "rel": rel, "day": _day_of(row, labels)})
    known = {key(r) for r in old_rows}
    return {"comparable": True, "reason": "", "changes": changes, "compared": compared,
            "missing_rows": missing, "new_rows": sum(1 for k in fresh if k not in known)}


def classify(changes: list[dict], answered_on: date, lag_days: Optional[int]) -> str:
    """Why the numbers moved: ``late_rows`` — every changed day was still settling when the
    answer was given; ``restated`` — at least one had already settled; ``unknown`` — no
    learned lag, or no date to place the change in. Marks each change with its own cause."""
    if not changes:
        return "none"
    causes = set()
    for c in changes:
        day = c.get("day")
        if lag_days is None or not day:
            c["cause"] = "unknown"
        else:
            settled_by = answered_on - timedelta(days=int(lag_days))
            c["cause"] = "late_rows" if date.fromisoformat(day) > settled_by else "restated"
        causes.add(c["cause"])
    if causes == {"late_rows"}:
        return "late_rows"
    if "restated" in causes:
        return "restated"
    return "unknown"


# ── the sentence ───────────────────────────────────────────────────────────────────────────

def _fmt(v: float) -> str:
    """A number as the reader saw it: whole numbers with separators, fractions to what they
    carry — never "1.19e+06"."""
    if float(v).is_integer():
        return f"{int(v):,}"
    return f"{v:,.2f}" if abs(v) >= 1 else f"{v:.4g}"


def _what(c: dict) -> str:
    label = ", ".join(f"{v}" for v in (c.get("label") or {}).values() if v not in (None, ""))
    return f"{c['column']} for {label}" if label else c["column"]


def _days(days: list[str]) -> str:
    if len(days) == 1:
        return f"the day {days[0]}"
    return "the days " + ", ".join(days[:-1]) + f" and {days[-1]}"


def correction_text(answer: dict, recheck: dict) -> str:
    """The message a person receives. Code-written from the two measurements — no model."""
    when = str(answer.get("completed_at") or "")[:10]
    question = str(answer.get("question") or "").strip()
    changes = recheck.get("changes") or []
    asked = question[:160]
    lines = [f"On {when} you asked: “{asked}”{'' if asked[-1:] in '?.!' else '.'}" if asked
             else f"On {when} we answered you."]
    for c in changes[:NAMED_CHANGES]:
        lines.append(f"We told you {_what(c)} was {_fmt(c['old'])}; it is now {_fmt(c['new'])} "
                     f"({c['rel'] * 100:+.1f}%).")
    if len(changes) > NAMED_CHANGES:
        lines.append(f"{len(changes) - NAMED_CHANGES} more number"
                     f"{'s' if len(changes) - NAMED_CHANGES != 1 else ''} in that answer changed too.")
    cause, lag = recheck.get("cause"), recheck.get("lag_days")
    late = sorted({c["day"] for c in changes if c.get("cause") == "late_rows"})
    restated = sorted({c["day"] for c in changes if c.get("cause") == "restated"})
    if cause == "late_rows":
        lines.append(f"These are late rows: this source's numbers settle after {lag} days, and "
                     f"{_days(late)} {'was' if len(late) == 1 else 'were'} still inside that "
                     "window when we answered.")
    elif cause == "restated":
        if late:
            lines.append(f"{_days(late).capitalize()} {'was' if len(late) == 1 else 'were'} still "
                         f"settling when we answered (this source settles after {lag} days): "
                         "late rows.")
        lines.append(f"{_days(restated).capitalize()} had already settled when we answered, so "
                     "the source has restated its history there — not late rows.")
    elif lag is None:
        lines.append("The platform has not yet learned when this source's numbers settle, so it "
                     "cannot say whether these are late rows or a restatement.")
    else:
        lines.append("The answer has no date column, so the change cannot be placed in time.")
    return "\n".join(lines)


# ── running one re-check ───────────────────────────────────────────────────────────────────

def _open_runner(conn_id: str):
    from aughor.db.connection import open_connection_for
    db = open_connection_for(conn_id)

    def run_sql(sql: str):
        res = db.execute("__answer_recheck__", sql)
        return (list(getattr(res, "columns", []) or []), list(getattr(res, "rows", []) or []),
                getattr(res, "error", None))
    return run_sql


def _answered_on(answer: dict) -> date:
    try:
        return date.fromisoformat(str(answer.get("completed_at") or "")[:10])
    except ValueError:
        return datetime.now(timezone.utc).date()


def measure_answer(answer: dict, *, run_sql: Optional[RunSql] = None,
                   now: Optional[datetime] = None) -> dict:
    """Re-run one answer's query, compare and classify — WITHOUT recording anything. Returns
    the re-check entry. Never raises: a failure is an ``unchecked`` entry with its reason."""
    now = now or datetime.now(timezone.utc)
    report = answer.get("report") or {}
    entry: dict[str, Any] = {"checked_at": now.isoformat().replace("+00:00", "Z"),
                             "status": "unchecked", "reason": "", "changes": [], "compared": 0,
                             "missing_rows": 0, "new_rows": 0, "cause": "none", "lag_days": None}
    sql = str(report.get("sql") or "")
    if not (sql and report.get("columns") and report.get("rows")):
        entry["reason"] = "the answer carries no query result to compare"
        return entry
    try:
        columns, rows, error = (run_sql or _open_runner(answer["connection_id"]))(sql)
    except Exception as exc:  # noqa: BLE001
        columns, rows, error = [], [], f"{type(exc).__name__}: {exc}"
    if error:
        entry["reason"] = f"re-running its query failed: {str(error)[:200]}"
        return entry
    diff = diff_results(report["columns"], report["rows"], columns, rows)
    if not diff["comparable"]:
        entry["reason"] = diff["reason"]
        return entry
    lag = None
    try:
        from aughor.settling.store import learned_lag_days
        lag = learned_lag_days(answer["connection_id"])
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "no learned lag; a change is reported with its cause unknown",
                 counter="answers.recheck.lag")
    changes = diff["changes"]
    entry.update(status="changed" if changes else "unchanged", changes=changes[:10],
                 changed=len(changes), compared=diff["compared"],
                 missing_rows=diff["missing_rows"], new_rows=diff["new_rows"],
                 lag_days=lag, cause=classify(changes, _answered_on(answer), lag))
    return entry


def _record(answer: dict, entry: dict) -> None:
    from aughor.db.history import append_recheck
    append_recheck(answer["id"], entry)
    try:
        from aughor.kernel.ledger import Ledger
        Ledger.default().emit("answer.rechecked",
                              {"investigation_id": answer["id"], "status": entry["status"],
                               "changed": entry.get("changed", 0), "cause": entry["cause"],
                               "told": (entry.get("told") or {}).get("status", "")},
                              conn_id=answer.get("connection_id"))
    except Exception as exc:  # noqa: BLE001 — the spine is observability, never the record
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the re-check is recorded on the answer; only its spine event was lost",
                 counter="answers.recheck.emit")


# ── telling the person ─────────────────────────────────────────────────────────────────────

def slack_thread(session_id: str) -> Optional[tuple[str, str]]:
    """``(channel, thread_ts)`` from a Slack session id ``slack:<channel>:<ts>`` — the id the
    Slack bot gives a thread's conversation (`bots/slack/src/bot.ts`)."""
    m = re.fullmatch(r"slack:([A-Z0-9]+):(\d+\.\d+)", str(session_id or ""))
    return (m.group(1), m.group(2)) if m else None


def _told_before(answer: dict, entry: dict) -> bool:
    """The same numbers, already told — a change is news once."""
    mine = {(c["column"], str(c.get("label")), c["new"]) for c in entry.get("changes") or []}
    for prior in (answer.get("report") or {}).get("rechecks") or []:
        told = prior.get("told") or {}
        if told.get("status") in ("sent", "shown") and prior.get("changes"):
            if mine == {(c["column"], str(c.get("label")), c["new"]) for c in prior["changes"]}:
                return True
    return False


def _bot_for(answer: dict):
    """The Slack bot to reply as: the one bound to the agent that answered, else the only bot
    configured. Two candidates and no binding → none: replying as the wrong bot is worse
    than not replying, and the re-check still shows on the answer."""
    from aughor.slackbots.store import bots_for_agent, get_bot_decrypted, list_bots
    agent = answer.get("agent_id") or ""
    candidates = [b for b in bots_for_agent(agent) if b.enabled] if agent else []
    if not candidates:
        candidates = list_bots(include_disabled=False)
    if len(candidates) != 1:
        return None, ("no Slack bot is configured" if not candidates
                      else "more than one Slack bot, and none is bound to the agent that answered")
    return get_bot_decrypted(candidates[0].id), ""


def tell(answer: dict, entry: dict) -> dict:
    """Tell the person who was given ``answer`` that ``entry`` changed it. A Slack answer gets
    a reply in its own thread, gated like every message that leaves; a web answer shows the
    re-check on the answer. Returns the ``told`` record (also written onto the entry)."""
    if entry.get("status") != "changed":
        return {}
    if _told_before(answer, entry):
        return {"status": "already_told"}
    thread = slack_thread(answer.get("session_id") or "")
    if thread is None:
        return {"door": "web", "status": "shown",
                "note": "shown on the answer; the web keeps no inbox to push it to"}
    channel, thread_ts = thread
    bot, why = _bot_for(answer)
    if bot is None:
        return {"door": "slack", "status": "not_sent", "note": why}
    from aughor.govern.departure import Measurement, gate_departure
    from aughor.org.context import current_org_id
    from aughor.slackbots.post import post_as_bot
    text = correction_text(answer, entry)
    values = [v for c in entry.get("changes") or [] for v in (c["old"], c["new"])]
    verdict = gate_departure(
        kind="answer_correction", org_id=answer.get("org_id") or current_org_id(),
        conn_id=answer.get("connection_id") or "", text=text, target=f"{bot.id}:{channel}",
        actor=f"recheck:{answer['id']}", investigation_id=answer["id"], source_kind="answer",
        source_id=answer["id"], source_name=str(answer.get("question") or "")[:80],
        measurement=Measurement(source="the answer's own query, re-run", values=values,
                                measured_at=entry.get("checked_at", ""),
                                definition="the query the original answer ran"))
    if verdict.held:
        return {"door": "slack", "status": "held", "note": verdict.reason_sentence(),
                "departure_id": verdict.record_id}
    ok, info = post_as_bot(bot.bot_token, channel, f"{text}\n\n{verdict.receipt_line()}",
                           thread_ts=thread_ts)
    return {"door": "slack", "status": "sent" if ok else "failed", "departure_id": verdict.record_id,
            "ts": info.get("ts", ""), "note": "" if ok else str(info.get("error", "unknown"))}


def recheck_and_tell(answer: dict, *, run_sql: Optional[RunSql] = None,
                     now: Optional[datetime] = None, notify: bool = True) -> dict:
    """One answer, end to end: re-run and compare, tell the person when it changed (unless
    ``notify`` is off — a person re-checking on screen is already looking), then record the
    entry, told outcome and all, on the answer. Returns the recorded entry."""
    entry = measure_answer(answer, run_sql=run_sql, now=now)
    if notify and entry.get("status") == "changed":
        entry["told"] = tell(answer, entry)
    _record(answer, entry)
    return entry


# ── the daily pass ─────────────────────────────────────────────────────────────────────────

_last_run_day: Optional[str] = None


def run_rechecks_daily(*, force: bool = False, now: Optional[datetime] = None,
                       runner: Optional[Callable[[str], RunSql]] = None) -> dict:
    """Re-check the recent answers once a UTC day, from the heartbeat. Off → nothing. Returns
    ``{"checked", "changed", "told", "skipped"}``."""
    global _last_run_day
    if not enabled():
        return {"skipped": "off"}
    now = now or datetime.now(timezone.utc)
    today = now.date().isoformat()
    if _last_run_day == today and not force:
        return {"skipped": "already ran today"}
    _last_run_day = today
    from aughor.db.history import recent_chat_answers
    since = (now - timedelta(days=WINDOW_DAYS)).isoformat()
    due = []
    for answer in recent_chat_answers(since, limit=PER_RUN * 5):
        last = ((answer.get("report") or {}).get("rechecks") or [{}])[-1].get("checked_at", "")
        if last and last > (now - timedelta(hours=RECHECK_EVERY_HOURS)).isoformat():
            continue
        due.append(answer)
    due = due[:PER_RUN]
    runners: dict[str, RunSql] = {}
    summary = {"checked": 0, "changed": 0, "told": 0}
    for answer in due:
        conn = answer["connection_id"]
        try:
            run_sql = runners.get(conn) or (runner or _open_runner)(conn)
            runners[conn] = run_sql
        except Exception as exc:  # noqa: BLE001 — one unreachable connection skips its answers
            from aughor.kernel.errors import tolerate
            tolerate(exc, "an answer's connection could not be opened for its re-check",
                     counter="answers.recheck.open", conn_id=conn)
            continue
        entry = recheck_and_tell(answer, run_sql=run_sql, now=now)
        summary["checked"] += 1
        summary["changed"] += entry.get("status") == "changed"
        summary["told"] += (entry.get("told") or {}).get("status") in ("sent", "shown")
    return summary
