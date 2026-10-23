"""A Question on a dashboard (PENDING 54; design-mockups/dashboard-questions.html, approved 2026-10-23).

A question a person keeps on a dashboard, answered by the agent the Data Canvas uses — on a rhythm, or only when they
ask — and shown as the Data Canvas shows an answer: its headline, figures, summary, why, what it could not see, its
confidence and the period it read, with every earlier answer beside it. Opening a dashboard NEVER asks: it reads the
answers already kept. Asking costs a full agent run, and that is said before a question is kept and beside each answer.

No new store. The rhythm is an AUTOMATION — a schedule and an ``investigate`` step, the machinery theLook's daily
question already runs on, which writes the period into the question by code (the last complete day, week or month at
the connection's settling lag, against the one before) and hands the previous answer over for consistency
(``automations/temporal.py``). "Only when I ask" is the same automation behind a webhook trigger: it never fires on its
own. Every answer is an investigation filed under the question's own session, ``question:<id>``, and read back by that
tag (``history.list_investigations_for_session``) — not from an inquiry, which closes once answered and is re-opened by
subject, so a monthly question's answers would land on a new one each month. A question kept from a Data Canvas
answer starts with that answer (``first``).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

FLAG = "dashboard.questions"
#: How often a question is asked, as the cron its automation runs on: 09:00 UTC, as theLook's daily question is.
#: Weekly asks on Mondays and monthly on the 1st, so each reads the period that has just closed.
RHYTHMS: dict[str, Optional[str]] = {"daily": "0 9 * * *", "weekly": "0 9 * * mon", "monthly": "0 9 1 * *", "ask": None}
RHYTHM_WORDS = {"daily": "Daily · 09:00 UTC", "weekly": "Weekly · Mondays 09:00 UTC",
                "monthly": "Monthly · the 1st, 09:00 UTC", "ask": "Only when asked"}
#: The approved default (the user, 2026-10-23): about four runs a month per question.
DEFAULT_RHYTHM = "weekly"
SESSION_PREFIX = "question:"
NAME_PREFIX = "Dashboard question · "
MAX_QUESTION = 500
#: How many earlier answers a question shows.
MAX_ANSWERS = 24


class QuestionRefused(ValueError):
    """A question that cannot be kept or asked, in words a person can act on."""


def on() -> bool:
    from aughor.kernel.flags import flag_enabled
    return flag_enabled(FLAG)


def _conditions(rhythm: str) -> list[dict]:
    cron = RHYTHMS[rhythm]
    return [{"kind": "schedule", "config": {"cron": cron}}] if cron else [{"kind": "webhook", "config": {}}]


def rhythm_of(automation: Any) -> str:
    """The rhythm an automation runs on, read back from its trigger."""
    for c in getattr(automation, "conditions", None) or []:
        if c.kind == "webhook":
            return "ask"
        if c.kind == "schedule":
            cron = str((c.config or {}).get("cron") or "")
            return next((r for r, x in RHYTHMS.items() if x == cron), "custom")
    return "custom"


def _effect(automation: Any) -> Optional[Any]:
    return next((e for e in getattr(automation, "effects", None) or [] if e.kind == "investigate"), None)


def session_of(automation: Any) -> str:
    eff = _effect(automation)
    return str((eff.config or {}).get("session_id") or "") if eff else ""


def is_question(automation: Any) -> bool:
    return session_of(automation).startswith(SESSION_PREFIX)


def keep(*, connection_id: str, question: str, rhythm: str = DEFAULT_RHYTHM, schema: Optional[str] = None,
         first_run: str = "") -> dict:
    """Keep a question: its automation, born with its rhythm. ``first_run`` — a Data Canvas answer it starts from —
    must be a finished deep run on the same connection. Returns ``{"automation_id", "session", "first", "rhythm"}``."""
    question = " ".join((question or "").split())
    if not question:
        raise QuestionRefused("a question needs its words")
    if len(question) > MAX_QUESTION:
        raise QuestionRefused(f"a question is at most {MAX_QUESTION} characters; this one is {len(question)}")
    if rhythm not in RHYTHMS:
        raise QuestionRefused(f"a question is asked daily, weekly, monthly or only when asked — not {rhythm!r}")
    if not connection_id:
        raise QuestionRefused("a question is asked of a connection; none was named")
    if first_run:
        from aughor.db.history import get_investigation
        rec = get_investigation(first_run)
        if not rec:
            raise QuestionRefused(f"there is no answer {first_run!r} to start from")
        if str(rec.get("connection_id") or "") != connection_id:
            raise QuestionRefused("the answer it starts from was asked of another connection")
        if str(rec.get("status") or "") != "complete":
            raise QuestionRefused("the answer it starts from has not finished")
    qid = uuid.uuid4().hex[:12]
    session = f"{SESSION_PREFIX}{qid}"
    config: dict[str, Any] = {"question": question, "session_id": session}
    if schema:
        config["schema_name"] = schema
    from aughor.routers.automations import CreateAutomationRequest, create
    saved = create(CreateAutomationRequest(
        conn_id=connection_id, name=NAME_PREFIX + question[:80],
        description=("Kept on a dashboard. Each answer re-asks the agent the Data Canvas uses for the last complete "
                     "period against the one before, and is filed under " + session + "."),
        conditions=_conditions(rhythm), effects=[{"kind": "investigate", "config": config}]))
    return {"automation_id": saved["id"], "session": session, "first": first_run, "rhythm": rhythm}


def _get(automation_id: str) -> Any:
    from aughor.automations.store import get_automation
    automation = get_automation(automation_id)
    if automation is None or not is_question(automation):
        raise QuestionRefused("no such question")
    return automation


def set_rhythm(automation_id: str, rhythm: str) -> dict:
    """Change how often a question is asked — its trigger, nothing else."""
    if rhythm not in RHYTHMS:
        raise QuestionRefused(f"a question is asked daily, weekly, monthly or only when asked — not {rhythm!r}")
    from aughor.automations.models import Condition
    from aughor.automations.store import upsert_automation
    automation = _get(automation_id)
    saved = upsert_automation(automation.model_copy(update={
        "conditions": [Condition(**c) for c in _conditions(rhythm)]}))
    return {"automation_id": saved.id, "rhythm": rhythm_of(saved), "next_at": next_at(saved)}


def ask_now(automation_id: str) -> dict:
    """Ask the question now — a full agent run, through the same gates the schedule uses (a person's click)."""
    from aughor.automations.scheduler import trigger_now
    _get(automation_id)
    run = trigger_now(automation_id, via="hand")
    if run is None:
        raise QuestionRefused("no such question")
    step = next((e for e in run.effects if e.kind == "investigate"), None)
    return {"outcome": run.outcome, "reason": run.reason or run.error or "",
            "asked": bool(step and step.status not in ("dispatch_error", "skipped")),
            "message": (getattr(step, "message", "") or "") if step else ""}


def next_at(automation: Any, now: Optional[datetime] = None) -> Optional[str]:
    """When the question is next asked, or None when it is only asked by hand."""
    from aughor.automations.engine import next_fire_utc
    for c in automation.conditions or []:
        if c.kind == "schedule":
            nxt = next_fire_utc(str((c.config or {}).get("cron") or ""), now or datetime.now(timezone.utc),
                                getattr(automation, "timezone", "") or "")
            return nxt.isoformat() if nxt else None
    return None


# ── reading what was answered ─────────────────────────────────────────────────────────────

def _minutes(rec: dict) -> Optional[float]:
    try:
        a = datetime.fromisoformat(str(rec.get("started_at")))
        b = datetime.fromisoformat(str(rec.get("completed_at")))
        return round((b - a).total_seconds() / 60, 1)
    except (TypeError, ValueError):
        return None


def _why(report: dict) -> dict:
    """What moved it, as the answer found it: its attribution when the run measured one (each cause with its amount
    and share), else what its breakdown phases claimed, sentence by sentence. Never written here."""
    drivers = [{"cause": str(w.get("cause") or ""), "amount": str(w.get("amount_label") or ""),
                "share": w.get("pct_of_total")}
               for w in (report.get("attribution_waterfall") or []) if isinstance(w, dict) and w.get("cause")]
    lines: list[str] = []
    for ph in report.get("phases") or []:
        if not isinstance(ph, dict) or str(ph.get("phase_id") or "") not in ("decomposition", "cross_section"):
            continue
        for f in ph.get("findings") or []:
            claim = str((f or {}).get("claim") or "").strip() if isinstance(f, dict) else ""
            if claim and claim not in lines:
                lines.append(claim)
    return {"drivers": drivers[:6], "lines": lines[:4]}


def answer_of(rec: dict) -> dict:
    """One finished answer as a dashboard shows it — the run's own words and figures, each from its report."""
    report = rec.get("report") if isinstance(rec.get("report"), dict) else {}
    figures = [{"label": str(f.get("label") or ""), "value": str(f.get("value") or ""), "note": str(f.get("note") or "")}
               for f in (report.get("figures") or []) if isinstance(f, dict) and f.get("value")]
    gaps = report.get("gaps") or ""
    if not gaps and report.get("data_gaps"):
        gaps = " ".join(str(g) for g in report["data_gaps"][:3])
    return {"id": rec.get("id"), "headline": str(report.get("headline") or rec.get("headline") or ""),
            "summary": str(report.get("executive_summary") or ""), "figures": figures[:4], "why": _why(report),
            "gaps": str(gaps or ""), "confidence": str(report.get("confidence") or ""),
            "period": str(report.get("observation_period") or ""), "against": str(report.get("comparison_basis") or ""),
            "asked_at": rec.get("started_at"), "answered_at": rec.get("completed_at"), "minutes": _minutes(rec)}


def _verdicts(connection_id: str) -> dict[str, str]:
    """Each run's verdict as the Record booked it — "contradicted" when a later reading refuted it."""
    try:
        from aughor.record.inquiry import list_inquiries
        out: dict[str, str] = {}
        for q in list_inquiries(conn_id=connection_id or None, limit=500):
            for r in q.runs:
                out[r.run] = r.verdict
        return out
    except Exception as exc:  # noqa: BLE001 — a verdict that cannot be read is left unsaid, never guessed
        from aughor.kernel.errors import tolerate
        tolerate(exc, "a question's verdicts could not be read", counter="dashboards.question.verdicts")
        return {}


def read(automation_id: str, *, first: str = "", now: Optional[datetime] = None) -> dict:
    """The question as a dashboard shows it. No model call and nothing written: its words and rhythm, when it is next
    asked, the latest finished answer in full, every answer in a line, and what an answer costs on this install."""
    from aughor.db.history import get_investigation, list_investigations_for_session
    automation = _get(automation_id)
    eff = _effect(automation)
    rows = list_investigations_for_session(session_of(automation), limit=MAX_ANSWERS)
    if first and not any(r["id"] == first for r in rows):
        rec = get_investigation(first)
        if rec and str(rec.get("connection_id") or "") == automation.conn_id:
            rows.append({k: rec.get(k) for k in ("id", "question", "connection_id", "started_at", "completed_at",
                                                 "status", "headline")})
    rows.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    verdicts = _verdicts(automation.conn_id)
    answers = [{"id": r["id"], "asked_at": r.get("started_at"), "answered_at": r.get("completed_at"),
                "status": r.get("status"), "headline": str(r.get("headline") or ""),
                "verdict": verdicts.get(r["id"]) or ("answered" if r.get("status") == "complete" else "")}
               for r in rows]
    latest = next((r for r in rows if r.get("status") == "complete"), None)
    full = answer_of(get_investigation(latest["id"]) or {}) if latest else None
    from aughor.record.inquiry import run_cost_estimate
    return {"automation_id": automation.id, "question": str((eff.config or {}).get("question") or "") if eff else "",
            "rhythm": rhythm_of(automation), "rhythm_words": RHYTHM_WORDS.get(rhythm_of(automation), "On its own schedule"),
            "next_at": next_at(automation, now), "enabled": bool(automation.enabled),
            "latest": full, "answers": answers, "running": any(a["status"] == "running" for a in answers),
            "cost": run_cost_estimate(automation.conn_id)}


# ── held to the rules when a dashboard is kept ────────────────────────────────────────────

KIND = "Question"


def held(spec: Any) -> dict[str, dict]:
    """Each Question a spec holds, by element key: its props."""
    elements = spec.get("elements") if isinstance(spec, dict) else None
    return {str(key): dict(el.get("props") or {}) for key, el in (elements if isinstance(elements, dict) else {}).items()
            if isinstance(el, dict) and el.get("type") == KIND}


def refused_off(spec: Any) -> list[str]:
    """The keep is refused when the spec holds a question while questions are off here. Empty when it holds none,
    whatever the flag says — a dashboard without one keeps exactly as before."""
    keys = list(held(spec))
    if not keys or on():
        return []
    return [f"The dashboard holds a question — {', '.join(keys[:6])}{'…' if len(keys) > 6 else ''} — and questions on a "
            "dashboard are off on this install."]


def not_resolved(connection_id: str, spec: Any) -> list[str]:
    """A sentence for each Question that names no question kept on this connection — read from its automation, the
    one place its words, rhythm and session live."""
    from aughor.automations.store import get_automation
    said = []
    for key, props in held(spec).items():
        automation = get_automation(str(props.get("automation") or ""))
        if automation is None or not is_question(automation):
            said.append(f'The question "{key}" names no question that was kept: keep it again from "+ Question".')
        elif automation.conn_id != connection_id:
            said.append(f'The question "{key}" is asked of another connection, not this dashboard\'s.')
    return said


def written(before: Any, after: Any, *, new: bool) -> list[str]:
    """What a model's draft did to a question that only a person may do: add one, or change which question it is.
    Moving, resizing and taking one off are arrangement, and pass."""
    was = {} if new else held(before)
    said = []
    for key, props in held(after).items():
        named = (props.get("automation"), props.get("first"))
        if new:
            said.append(f'The dashboard holds the question "{key}". A new dashboard holds none: a question is the '
                        "person's to keep, by hand — each answer is a run they pay for.")
        elif key not in was:
            said.append(f'The edit adds the question "{key}". A person keeps a question: you may move one, resize it or '
                        "take it off, never add one.")
        elif (was[key].get("automation"), was[key].get("first")) != named:
            said.append(f'The edit changes which question "{key}" is. A person chose it: move it, resize it or take it '
                        "off, never change what it asks.")
    return said


def follow(before: Any, after: Any) -> list[str]:
    """A question taken off a dashboard stops being asked; one put back is asked again. Its automation is DISABLED, not
    deleted — its answers and history stay, and putting the question back brings it back (supersede, never delete).
    Only what changed is touched, so a question a person paused on purpose stays paused across an unrelated edit.
    Returns the automation ids it changed. Never fails the keep it follows: what it could not do is tolerated, said."""
    was = {str(p.get("automation") or "") for p in held(before).values()} - {""}
    now = {str(p.get("automation") or "") for p in held(after).values()} - {""}
    changed: list[str] = []
    try:
        from aughor.automations.store import get_automation, set_automation_enabled
        for aid, enabled in [*((a, False) for a in sorted(was - now)), *((a, True) for a in sorted(now - was))]:
            automation = get_automation(aid)
            if automation is not None and is_question(automation) and automation.enabled != enabled:
                set_automation_enabled(aid, enabled)
                changed.append(aid)
    except Exception as exc:  # noqa: BLE001 — the dashboard is kept; a question it could not stop is said in the log
        from aughor.kernel.errors import tolerate
        tolerate(exc, "a question's automation could not follow its dashboard", counter="dashboards.question.follow")
    return changed
