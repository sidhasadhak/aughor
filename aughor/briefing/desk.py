"""The Briefing's desk — what the morning paper prints beside its lead story.

The user, 2026-10-12: the Briefing should read "like a newspaper … the synthesis or the interpretation
of the findings … the trends … the gaps … a starting point for my decision-making in the morning".
The lead story is the narrator's (`knowledge/briefing.py`). The three columns beside it are not
written by a model at all: they are what the platform has ALREADY recorded and the Briefing never
read —

* **Trends** — the longer view: investigation answers (an observation booked from an investigation's
  report) and trend findings, newest first.
* **Gaps** — what the paper cannot tell you yet: a question whose runs came back with different
  numbers, a question parked waiting for data, an approved metric with no formula, and a data lag.
* **Decide** — what is waiting on a person: an investigation the platform proposed and never ran,
  a metric proposed and not yet reviewed.

A READ never builds: this only reads the Record and the metric registry — no warehouse query, no
model call. A store that cannot be read is said (`unread`), never shown as an empty column.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Optional

#: Items per column; the rest are counted (`more`), never dropped silently.
PER_COLUMN = 4
#: How far back a trend is still news.
TREND_DAYS = 30
#: A lag the paper says out loud.
LAG_SAID_DAYS = 7
#: Two answers to one question that differ by more than this share disagree. Tight on purpose: two
#: totals of one settled quantity should match exactly (theLook's three 2025 answers differ by 0.28%
#: between two of them — a different definition, not rounding).
DISAGREE = 0.001


def _days_ago(iso: str, now: _dt.datetime) -> Optional[float]:
    try:
        t = _dt.datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=_dt.timezone.utc)
    return (now - t).total_seconds() / 86400


def _split(text: str) -> tuple[str, str]:
    """`"Inventory Sell-Through Rate Trend: The metric exhibits…"` → (title, body); a text with no
    label is all title."""
    head, sep, rest = (text or "").partition(": ")
    if sep and 3 <= len(head) <= 80 and rest:
        return head.strip(), rest.strip()
    return (text or "").strip(), ""


_NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d+)\s?(K|M|B|thousand|million|billion)?(?![\w])", re.I)
_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "b": 1e9, "billion": 1e9}


def answer_figure(text: str) -> Optional[float]:
    """The figure an answer states: its largest number, years (1900–2100 written bare) aside."""
    best: Optional[float] = None
    for raw, unit in _NUM.findall(text or ""):
        if not unit and "," not in raw and "." not in raw and (1900 <= int(raw) <= 2100 or int(raw) < 1000):
            continue                                # a year, or a small count ("3 runs") — not the answer
        v = float(raw.replace(",", "")) * _SCALE.get(unit.lower(), 1.0)
        if best is None or abs(v) > abs(best):
            best = v
    return best


def human(v: float, money: bool = False) -> str:
    sign, a = ("-" if v < 0 else ""), abs(v)
    s = (f"{a/1e9:.2f}B" if a >= 1e9 else f"{a/1e6:.2f}M" if a >= 1e6 else f"{a/1e3:.1f}K" if a >= 1e4
         else f"{a:,.2f}".rstrip("0").rstrip("."))
    return f"{sign}{'$' if money else ''}{s}"


_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2}|(?:January|February|March|April|May|June|July|August|September|October|"
                   r"November|December) \d{1,2},? \d{4})\b")


def disagreeing_answers(runs: list[dict]) -> list[float]:
    """The distinct figures an inquiry's answered runs gave, when they disagree; [] when they agree,
    when fewer than two runs stated one, or when the runs answer different dates — a recurring run
    (a scheduled daily question) reports a new day each time, which is not a contradiction."""
    days = {d for r in runs if r.get("verdict") == "answered" for d in _DATE.findall(r.get("why", ""))}
    if len(days) > 1:
        return []
    figs = [f for f in (answer_figure(r.get("why", "")) for r in runs if r.get("verdict") == "answered") if f is not None]
    figs = figs if len(figs) >= 2 else []
    distinct: list[float] = []
    for f in figs:
        if all(abs(f - d) > DISAGREE * max(abs(f), abs(d), 1e-9) for d in distinct):
            distinct.append(f)
    return sorted(distinct) if len(distinct) >= 2 else []


def _source(kind: str, ref: str, label: str) -> dict:
    return {"kind": kind, "ref": ref, "label": label}


#: Words that say a measure moved — or held — over time: what makes a statement a trend.
_CHANGE = re.compile(r"\b(trend|increas|decreas|rose|risen|fell|fall|grew|grow|declin|drop|climb|surg|jump|slow|"
                     r"stable|steady|flat)\w*", re.I)
_YEAR = re.compile(r"\b(19\d\d|20\d\d)\b")


def _subject(title: str) -> str:
    """What a trend is about, to say each subject once: its first three words."""
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", title.lower()).split()[:3])


def trends(claims: list[Any], now: _dt.datetime) -> list[dict]:
    """Investigation answers and findings that say a measure moved or held, booked in the last
    `TREND_DAYS`, newest first, each subject once. A trend whose latest year is before last year is
    history, not news (theLook's "order volume climbed … 2019 to … 2020")."""
    out, seen = [], set()
    for c in claims:
        text = c.statement.text or ""
        age = _days_ago(c.recorded_at or c.as_of, now)
        if age is None or age > TREND_DAYS:
            continue
        # An observation booked from an investigation's report carries the investigation and its question.
        answer = c.kind == "observation" and bool((c.extra or {}).get("investigation_id")) and bool((c.extra or {}).get("question"))
        title, body = _split(text)
        # An investigation's answer that says a measure moved or held; a finding only when its LABEL
        # names a trend ("Inventory Sell-Through Rate Trend: …") — an investigation's sub-findings are
        # its evidence, and an unlabelled finding that merely says "trend" (LuxExperience: "… should
        # not be read as a like-for-like performance trend") is not one.
        labelled_trend = c.kind == "finding" and bool(body) and re.search(r"\btrend\b", title, re.I)
        if not ((answer and _CHANGE.search(text)) or labelled_trend):
            continue
        years = [int(y) for y in _YEAR.findall(text)]
        if years and max(years) < now.year - 1:
            continue
        if _subject(title) in seen:
            continue
        seen.add(_subject(title))
        question = (c.extra or {}).get("question", "")
        out.append({"id": c.id, "title": title, "text": body, "status": c.status, "as_of": c.as_of,
                    "kind": "answer" if answer else "trend",
                    "source": _source("claim", c.id, f"Investigation · {question}" if answer and question
                                      else f"{'Observation' if c.kind == 'observation' else 'Finding'} · {title}")})
    return out


def by_code(q: Any) -> bool:
    """A question written by code (a scheduled run's context block), not asked by anyone: it is the
    run's instructions, never a story — "[Scheduled-run context — written by code, not inferred]"."""
    head = (q.question or "").lstrip()[:120]
    return head.startswith("[") and "written by code" in head


def gaps(inquiries: list[Any], metrics: list[Any], period: Optional[dict]) -> list[dict]:
    inquiries = [q for q in inquiries if not by_code(q)]
    out: list[dict] = []
    said: set[str] = set()
    for q in inquiries:                                   # one question, different numbers
        runs = [r.model_dump() if hasattr(r, "model_dump") else r for r in q.runs]
        figs = disagreeing_answers(runs)
        if figs:
            money = any(("$" in r.get("why", "") or "USD" in r.get("why", "")) for r in runs)
            said.add(q.id)
            answered = sum(1 for r in runs if r.get("verdict") == "answered")
            out.append({"kind": "disagree", "title": q.question,
                        "text": f"{answered} runs gave {len(figs)} different answers: "
                                f"{', '.join(human(f, money) for f in figs[:-1])} and {human(figs[-1], money)}. "
                                "Don't quote it until one is confirmed.",
                        "action": {"verb": "Settle it", "kind": "inquiry", "ref": q.id},
                        "source": _source("inquiry", q.id, f"Inquiry · {q.question} ({len(runs)} runs)")})
    for m in metrics:                                     # approved, but nothing to measure
        if getattr(m, "status", "") == "approved" and not (getattr(m, "sql", "") or "").strip():
            label = getattr(m, "label", "") or m.name.replace("_", " ")
            out.append({"kind": "unmeasured", "title": f"{label[:1].upper()}{label[1:]} isn't measured",
                        "text": "The metric is approved but has no formula, so every Briefing leaves it out.",
                        "action": {"verb": "Add a formula", "kind": "metric", "ref": m.name},
                        "source": _source("metric", m.name, f"Metric · {label}")})
    undated = [m for m in metrics if getattr(m, "status", "") == "approved" and (getattr(m, "sql", "") or "").strip()
               and not (getattr(m, "time_column", "") or "").strip()]
    if undated:                                           # approved, but no date to cut a period by
        names = [getattr(m, "label", "") or m.name.replace("_", " ") for m in undated]
        out.append({"kind": "undated",
                    "title": f"{len(undated)} approved metric{'s' if len(undated) != 1 else ''} can't be measured for a period",
                    "text": f"{', '.join(names[:4])}{f' and {len(names) - 4} more' if len(names) > 4 else ''}: "
                            f"no date column is set, so every Day, Week and Month edition leaves {'them' if len(undated) != 1 else 'it'} out.",
                    "action": {"verb": "Set dates", "kind": "metric", "ref": undated[0].name},
                    "source": _source("metric", undated[0].name, f"Metrics · {len(undated)} without a date column")})
    for q in inquiries:                                   # parked, waiting for data
        if q.id in said or q.state != "waiting" or not q.open:
            continue
        until = f" It is parked until {q.next_check}." if q.next_check else ""
        out.append({"kind": "waiting", "title": f"Still open: {q.question}",
                    "text": f"{q.open[0].what}{until}",
                    "action": {"verb": "Open", "kind": "inquiry", "ref": q.id},
                    "source": _source("inquiry", q.id, f"Inquiry · {q.question} (waiting for {q.waiting_for or 'data'})")})
    lag = (period or {}).get("lag_days")
    if isinstance(lag, int) and lag >= LAG_SAID_DAYS:
        moving = (period or {}).get("still_moving") or []
        out.append({"kind": "lag", "title": f"The newest settled day is {lag} days old",
                    "text": (f"The data settles {lag} days late" + (f"; {len(moving)} tables are still changing" if moving else "") + "."),
                    "source": _source("range", (period or {}).get("key", ""), "The range's own data horizon")})
    return out


def decide(inquiries: list[Any], metrics: list[Any]) -> list[dict]:
    inquiries = [q for q in inquiries if not by_code(q)]
    out: list[dict] = []
    for q in inquiries:                                   # proposed by the platform, never run
        proposed = (q.extra or {}).get("proposed_run")
        if q.state != "open" or q.runs or not isinstance(proposed, dict):
            continue
        by = q.opened_by.split(":", 1)
        who = f"the {by[1].replace('_', ' ')} watch" if len(by) == 2 and by[0] == "process" else "the platform"
        out.append({"kind": "proposed_run", "title": proposed.get("question") or q.question,
                    "text": f"Flagged by {who}; an investigation is proposed, not run.",
                    "action": {"verb": "Run it", "kind": "inquiry", "ref": q.id},
                    "source": _source("inquiry", q.id, f"Inquiry · {q.question}")})
    for m in metrics:                                     # proposed, not reviewed
        if getattr(m, "status", "") != "proposed":
            continue
        label = getattr(m, "label", "") or m.name.replace("_", " ")
        tables = ", ".join(getattr(m, "tables", None) or []) or "its tables"
        by = getattr(m, "proposed_by", "") or "someone"
        out.append({"kind": "proposed_metric", "title": f"{label[:1].upper()}{label[1:]} is waiting as a metric",
                    "text": f"Proposed by {by} from {tables}; approved, the Briefing measures it every day.",
                    "action": {"verb": "Review", "kind": "metric", "ref": m.name},
                    "source": _source("metric", m.name, f"Metric · {label}")})
    return out


def turned_off(claim: Any, left_out: list[dict], reads_off) -> bool:
    """Whether a claim stands on a table turned off for analysis: an explorer finding the Briefing left out (matched
    by its schema and id — per-schema runs reuse ids), or an investigation's answer whose own query reads one."""
    ex = claim.extra or {}
    if ex.get("writer") == "explorer" and ex.get("finding_id"):
        fid, sch = str(ex["finding_id"]), str(ex.get("schema") or "")
        if any(r["id"] == fid and (not sch or not r.get("schema") or r["schema"] == sch) for r in left_out):
            return True
    return bool(ex.get("sql")) and reads_off(str(ex["sql"]))


def _column(items: list[dict]) -> dict:
    return {"items": items[:PER_COLUMN], "more": max(0, len(items) - PER_COLUMN)}


def desk(connection_id: str, schema: Optional[str] = None, *, period: Optional[dict] = None,
         now: Optional[_dt.datetime] = None, left_out: Optional[list[dict]] = None) -> dict:
    """The three columns for one connection (and schema). Each reads its own store; a store that
    cannot be read leaves its column `unread` with why, and the others still print. ``left_out`` is the
    findings the Briefing left out because they read a table turned off (`visibility.findings_left_out`):
    their claims are not news either."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    unread: dict[str, str] = {}

    def _read(label: str, fn):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — a column the store cannot fill says so
            from aughor.kernel.errors import tolerate
            tolerate(exc, f"the Briefing desk could not read {label}", counter=f"briefing.desk.{label}")
            unread[label] = f"{label} could not be read just now"
            return None

    from aughor.record import claims as C
    from aughor.record import inquiry as I
    from aughor.semantic.metrics import home_schema, list_metrics

    claims = _read("claims", lambda: C.list_claims(conn_id=connection_id, limit=300))
    inquiries = _read("inquiries", lambda: I.list_inquiries(conn_id=connection_id, limit=200))
    # The connection's own definitions (the registry also folds in global ones), in this schema or all.
    metrics = _read("metrics", lambda: [m for m in list_metrics(connection_id=connection_id)
                                        if getattr(m, "connection", "") == connection_id
                                        and (not schema or home_schema(m) in ("", "*", schema))])
    from aughor.ontology.visibility import connection_exclusions, off_read
    if claims and connection_exclusions(connection_id):
        from aughor.trust.lineage_edges import dialect_for_connection
        dialect = dialect_for_connection(connection_id)
        claims = [c for c in claims if not turned_off(
            c, left_out or [], lambda sql: off_read(connection_id, sql, dialect, default_schema=schema) is not None)]
    out = {"connection_id": connection_id, "schema": schema, "as_of": now.isoformat(),
           "trends": _column(trends(claims or [], now)) if claims is not None else None,
           "gaps": _column(gaps(inquiries or [], metrics or [], period)) if inquiries is not None and metrics is not None else None,
           "decide": _column(decide(inquiries or [], metrics or [])) if inquiries is not None and metrics is not None else None,
           "unread": unread}
    return out
