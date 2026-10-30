"""Arc BC-1 · what a block may read (ROADMAP §3.67).

A block never holds a number of its own: it names a SOURCE, and the source is a governed query with its rows, its
SQL, what the guards did and its status. Three kinds, each measured by the platform rather than told by the model:

* **check** — one of the guide's checks as Arc BG measured it: the range and the ranges before it, with its usual
  range, change and streak;
* **breakdown** — a check broken down by any low-cardinality column of the table it is dated by, each segment against
  its own usual range — compiled by `metric_time.run_measure(by=…)`, no model and no hand-written SQL;
* **query** — a SELECT the model wrote while investigating, run through the same guarded door the Data Canvas uses
  (`agent/converse_tools.run_sql`: the guard battery, the declared metric filters, the reader's policies, the guard
  receipts). A refusal is kept and said — with the repair the door suggests — never read as an empty result.

Rows are made JSON-safe here once (dates as ISO days, decimals as floats), so the page, the number gate and a send
read the same values.
"""
from __future__ import annotations

import re
import statistics
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

#: The most rows a source keeps. A block draws a handful; the evidence panel shows them all.
MAX_ROWS = 200
#: A segment behind fewer rows than this is too few to call — drawn grey, never headlined.
MIN_CELL_ROWS = 30
#: How many segments a breakdown keeps, furthest from usual first.
MAX_SEGMENTS = 12


class Source(BaseModel):
    id: str
    label: str
    #: check · breakdown · query · drill · answer are measured for the edition; finding · analysis · decision are the
    #: platform's own work it reads — an explorer finding, a deep analysis and its verdict, a decision in the record.
    kind: Literal["check", "breakdown", "query", "drill", "answer", "finding", "analysis", "decision"]
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    sql: str = ""
    #: final | provisional | to_date | refused — said beside every block that reads it
    status: str = "final"
    #: A check's own figures: current, previous, last_year, usual_mean/low/high, z, streak, rel, rel_last_year …
    facts: dict = Field(default_factory=dict)
    receipts: list[dict] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    #: How it was measured, in words a reader can check ("the 8 weeks before as the usual range").
    note: str = ""
    error: str = ""
    #: What the guarded door suggests when a SELECT failed — handed back to the model, never shown as a result.
    repair: dict = Field(default_factory=dict)
    unit: str = ""
    better: str = "none"


def cell(v: Any) -> Any:
    """A value as JSON carries it: an ISO day, a float, a string, or None."""
    if v is None:
        return None
    if isinstance(v, (datetime, date)):
        return v.isoformat()[:10] if isinstance(v, date) and not isinstance(v, datetime) else v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (int, float, str, bool)):
        return v
    return str(v)


def json_rows(rows: list) -> list[list[Any]]:
    """Result rows as JSON carries them, at most :data:`MAX_ROWS`."""
    out = []
    for r in rows[:MAX_ROWS]:
        cells = list(r.values()) if isinstance(r, dict) else list(r)
        out.append([cell(c) for c in cells])
    return out


# ── check ────────────────────────────────────────────────────────────────────────────────────

def from_check(fig: dict, *, period_word: str = "range") -> Source:
    """A measured check (`edition.measure_check`) as a source: one row per range read, the range itself last."""
    u = fig.get("usual") or {}
    facts = {k: fig.get(k) for k in ("current", "previous", "last_year", "rel", "rel_last_year", "z", "streak", "n")}
    facts.update({"usual_mean": u.get("mean"), "usual_low": u.get("low"), "usual_high": u.get("high"),
                  "usual_n": u.get("n")})
    for k in ("current_text", "previous_text", "last_year_text"):
        facts[k] = fig.get(k)
    facts.update({f"usual_{k}_text": u.get(f"{k}_text") for k in ("mean", "low", "high")})
    if fig.get("extreme"):
        facts["extreme"] = fig["extreme"]
    rows = [[p["start"], cell(p["value"]), p["label"] == "current"] for p in fig.get("series") or []]
    note = (f"the {u.get('n')} {period_word}s before as the usual range" if u else "") + \
           (f"; a year earlier read {fig['like_for_like']}" if fig.get("like_for_like") else "")
    return Source(id=fig["id"], label=fig["label"], kind="check", columns=["start", "value", "this_range"], rows=rows,
                  sql=fig.get("sql") or "", status=fig.get("status") or "final", facts=facts, note=note.strip("; "),
                  unit=fig.get("unit") or "", better=fig.get("better") or "none")


# ── breakdown ────────────────────────────────────────────────────────────────────────────────

def segment_rows(m: Any, column: str, windows: list, run_sql, dialect: str) -> tuple[list[list[Any]], str, str]:
    """Each segment of ``column`` for the range (``windows[0]``) against its own mean over the usual windows:
    ``(rows, sql, why)``; rows are ``[segment, this_range, usual, change, change_pct, rows, thin]``, furthest from
    usual first, too-few segments last."""
    from aughor.semantic import metric_time as mt

    if not column.replace("_", "").isalnum():
        return [], "", f"{column!r} is not a column name"
    got, why = mt.run_measure(m, windows, run_sql, dialect=dialect, by=column)
    if why:
        return [], "", why
    sql, _ = mt.measure_sql(m, windows, dialect=dialect, by=column)
    return segments(got, windows[0].label), sql or "", ""


def segments(got: list[dict], current: str = "current") -> list[list[Any]]:
    """Measured rows (`metric_time.measured_rows`) as a breakdown's rows: each group's value in the ``current``
    window against the mean of its other windows."""
    by_group: dict[Any, dict] = {}
    for r in got:
        g = by_group.setdefault(r["group"], {"now": None, "n": 0, "usual": []})
        if r["window"] == current:
            g["now"], g["n"] = r["value"], r["n"]
        elif r["value"] is not None:
            g["usual"].append(r["value"])
    rows = []
    for group, g in by_group.items():
        if g["now"] is None:
            continue
        usual = statistics.fmean(g["usual"]) if g["usual"] else None
        change = None if usual is None else g["now"] - usual
        pct = None if not usual else change / abs(usual)
        rows.append([cell(group), g["now"], usual, change, pct, g["n"], g["n"] < MIN_CELL_ROWS])
    rows.sort(key=lambda r: (r[6], -abs(r[3] or 0)))
    return rows[:MAX_SEGMENTS]


BREAKDOWN_COLUMNS = ["segment", "this_range", "usual", "change", "change_pct", "rows", "too_few"]


def breakdown(source_id: str, label: str, m: Any, column: str, spec, *, usual_n: int, run_sql, dialect: str,
              unit: str = "", better: str = "none", kind: str = "breakdown", check_id: str = "",
              within: Optional[dict] = None) -> Source:
    """A check broken down by ``column``, each segment against its own usual range. ``check_id`` and ``within``
    (the segment a drill narrowed to) are kept in its facts, so a drill can go one level deeper from it."""
    from aughor.briefing.edition import usual_windows

    windows = [spec.windows()[0]] + usual_windows(spec, usual_n)
    rows, sql, why = segment_rows(m, column, windows, run_sql, dialect)
    if why:
        return Source(id=source_id, label=label, kind=kind, status="refused", error=why, unit=unit, better=better)
    word = spec.period if spec.period in ("day", "week", "month", "year") else "range"
    facts = {"check": check_id, "by": column, "within": dict(within or {})}
    return Source(id=source_id, label=label, kind=kind, columns=BREAKDOWN_COLUMNS, rows=rows, sql=sql, facts=facts,
                  note=f"each {column.replace('_', ' ')} against its own usual: the mean of the {usual_n} {word}s "
                       f"before; under {MIN_CELL_ROWS} rows is too few to call",
                  unit=unit, better=better)


def rerun(src: Source, run_sql) -> Optional[Source]:
    """``src`` with its own SQL run again as it stands — a breakdown's or a drill's rows re-derived (each segment's
    change against its usual measured again, not only its cells), a query's rows typed as before. ``None`` when it
    cannot be run now: a line resting only on it holds."""
    from aughor.semantic import metric_time as mt

    if not src.sql or src.status == "refused":
        return None
    cols, rows, error = run_sql(src.sql)
    if error:
        return None
    if src.kind in ("breakdown", "drill"):
        return src.model_copy(update={"rows": segments(mt.measured_rows(rows, by=True))})
    columns = [str(c) for c in cols or []]
    return src.model_copy(update={"columns": columns, "rows": typed(columns, json_rows(list(rows or []))),
                                  "facts": {}})


# ── query ────────────────────────────────────────────────────────────────────────────────────

def query(source_id: str, label: str, conn_id: str, sql: str, *, purpose: str, schema: Optional[str] = None,
          canvas_id: Optional[str] = None, run=None) -> Source:
    """A SELECT the model wrote, run through the Data Canvas's guarded door (`converse_tools.run_sql`) — in a
    canvas's scope when the edition is a canvas's."""
    if run is None:
        from aughor.agent.converse_tools import run_sql as run
    scoped = {"canvas_id": canvas_id} if canvas_id else {}
    out = run(conn_id, {"sql": sql}, user_question=purpose, schema_scope=schema, max_rows=MAX_ROWS, **scoped)
    if out.get("error"):
        return Source(id=source_id, label=label, kind="query", sql=sql, status="refused", error=str(out["error"]),
                      repair=dict(out.get("repair") or {}), receipts=list(out.get("guard_receipts") or []))
    columns = [str(c) for c in out.get("columns") or []]
    return Source(id=source_id, label=label, kind="query", columns=columns,
                  rows=typed(columns, json_rows(list(out.get("rows") or []))), sql=str(out.get("sql") or sql),
                  receipts=list(out.get("guard_receipts") or []), caveats=[str(c) for c in out.get("caveats") or []],
                  note=purpose + (" (more rows than shown)" if out.get("truncated") else ""))


_NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?([eE][-+]?\d+)?$")
_ID_COL_RE = re.compile(r"(^id$|_id$|_key$|^code$|_code$|zip|postal|phone)", re.I)


def typed(columns: list[str], rows: list[list[Any]]) -> list[list[Any]]:
    """Cells the guarded door hands back as text ('243'), as numbers — a column at a time, only when every value in
    it is a plain number and its name is not an identifier's (an order id or a postal code stays text)."""
    if not rows:
        return rows
    out = [list(r) for r in rows]
    for i, name in enumerate(columns):
        if _ID_COL_RE.search(str(name)):
            continue
        vals = [r[i] for r in out if i < len(r) and r[i] not in (None, "", "NULL")]
        if vals and all(isinstance(v, (int, float)) or (isinstance(v, str) and _NUMBER_RE.match(v.strip()))
                        for v in vals):
            for r in out:
                if i < len(r) and isinstance(r[i], str):
                    r[i] = None if r[i].strip() in ("", "NULL") else float(r[i]) if any(c in r[i] for c in ".eE") \
                        else int(r[i])
    return out


def for_model(src: Source, *, max_rows: int = 25) -> dict:
    """What the investigating model is shown of a source: its shape, its first rows, what the guards said."""
    out: dict = {"id": src.id, "label": src.label, "kind": src.kind, "status": src.status}
    if src.error:
        out["error"] = src.error
        if src.repair:
            out["repair"] = src.repair.get("instruction") or src.repair
        return out
    out["columns"] = src.columns
    out["rows"] = src.rows[:max_rows]
    if len(src.rows) > max_rows:
        out["rows_not_shown"] = len(src.rows) - max_rows
    if src.facts:
        out["facts"] = {k: v for k, v in src.facts.items() if v is not None and not k.endswith("_text")}
    if src.caveats:
        out["caveats"] = src.caveats
    if src.note:
        out["note"] = src.note
    return out


# ── what the platform already knows ──────────────────────────────────────────────────────────

#: The kinds of source that are the platform's own work, read — never measured for the edition.
KNOWN = ("finding", "analysis", "decision")
#: The text a known source carries, by field — what the model reads and what a sentence citing it may quote.
KNOWN_TEXT = ("headline", "summary", "closing", "finding", "question", "chosen")
_PREAMBLE_RE = re.compile(r"^\[Scheduled-run context[^\]]*\].*?\n\s*\n", re.S)


def _short(text: Any, n: int) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def known_findings(by_domain: dict, *, tables=(), north_star=(), limit: int = 6) -> list[Source]:
    """The explorer's strongest findings for the dataset — confident, plausible, of some impact by the Briefing's own
    ranking (`knowledge.triage`), a synthesis first — each its own source. In a Data Canvas that names tables, only
    those that read its tables."""
    from aughor.knowledge.triage import impact_score, plausibility
    from aughor.semantic.metric_time import bare_name

    own = {bare_name(str(t)).lower() for t in tables}
    picked = []
    for domain, items in (by_domain or {}).items():
        for f in items or []:
            if not isinstance(f, dict) or not f.get("finding"):
                continue
            impact = f.get("impact")
            if impact is None:
                impact = impact_score(f["finding"], f.get("novelty", 0), f.get("confidence", 0), north_star)
            if float(f.get("confidence") or 0) < 0.6 or float(impact or 0) < 0.3:
                continue
            seems = plausibility(f["finding"], f.get("sql", ""), None)
            if not seems.ok and seems.severity == "implausible":
                continue
            read = {bare_name(str(t)).lower() for t in (f.get("signature") or {}).get("tables") or []}
            if own and not (read and read <= own):
                continue
            picked.append((domain == "Synthesis", float(impact or 0), domain, f))
    picked.sort(key=lambda x: (not x[0], -x[1]))
    out = []
    for n, (_syn, impact, domain, f) in enumerate(picked[:limit]):
        text = _short(f["finding"], 420)
        out.append(Source(id=f"finding_{n + 1}", label=_short(f.get("question") or text, 90), kind="finding",
                          columns=["finding", "domain", "found"], rows=[[text, domain, str(f.get("generated_at") or "")[:10]]],
                          facts={"finding": text, "question": _short(f.get("question"), 200), "domain": domain,
                                 "confidence": f.get("confidence"), "impact": impact, "finding_id": f.get("id")},
                          note="a finding the explorer kept, with the query it rests on", sql=str(f.get("sql") or "")))
    return out


def _analysis_source(source_id: str, run: dict, report: dict) -> Source:
    causal = report.get("causal_checks") if isinstance(report.get("causal_checks"), dict) else {}
    recs = [_short(r.get("action"), 200) for r in report.get("recommendations") or [] if isinstance(r, dict) and r.get("action")]
    question = _short(_PREAMBLE_RE.sub("", str(run.get("question") or "")), 220)
    headline = _short(report.get("headline") or run.get("headline"), 220)
    done = str(run.get("completed_at") or "")[:10]
    return Source(id=source_id, label=headline or question, kind="analysis",
                  columns=["headline", "question", "completed"], rows=[[headline, question, done]],
                  facts={"inv_id": run.get("id"), "question": question, "headline": headline,
                         "summary": _short(report.get("executive_summary"), 700),
                         "closing": _short(report.get("closing_summary"), 400),
                         "confidence": str(report.get("confidence") or ""),
                         "licence": str(causal.get("licence") or ""),
                         "recommendations": recs[:3], "gaps": _short(report.get("gaps"), 300), "completed": done},
                  status="final" if run.get("status") == "complete" else str(run.get("status") or ""),
                  note="a deep analysis the platform ran: its verdict, its confidence and what it can and cannot say")


def known_analyses(conn_id: str, *, limit: int = 6, list_runs=None, get_run=None) -> list[Source]:
    """The connection's latest completed deep analyses, one question each (a question asked again keeps its newest
    answer), each its own source with its verdict, confidence and claim licence."""
    if list_runs is None or get_run is None:
        from aughor.db.history import get_investigation, list_investigations
        list_runs, get_run = list_runs or (lambda: list_investigations(limit=300)), get_run or get_investigation
    seen: set[str] = set()
    out: list[Source] = []
    for run in list_runs():
        if run.get("connection_id") != conn_id or run.get("kind", "investigation") != "investigation":
            continue
        if run.get("status") != "complete" or not run.get("headline"):
            continue
        q = _PREAMBLE_RE.sub("", str(run.get("question") or "")).strip().lower()[:120]
        if q in seen:
            continue
        seen.add(q)
        full = get_run(run["id"]) or {}
        out.append(_analysis_source(f"analysis_{run['id']}", run, full.get("report") or {}))
        if len(out) >= limit:
            break
    return out


def known_decisions(conn_id: str, spec, *, limit: int = 6, list_fn=None) -> list[Source]:
    """Decisions in the record that bear on the range — taken by its end and not reviewed and closed before it began —
    one per decision (the record keeps every version), the soonest review first. Each its own source."""
    from datetime import timedelta

    if list_fn is None:
        from aughor.record.decisions import list_decisions
        list_fn = lambda: [d.model_dump(mode="json") for d in list_decisions(conn_id=conn_id)]  # noqa: E731
    start, end = spec.start.isoformat(), (spec.end - timedelta(days=1)).isoformat()
    picked: dict[tuple, dict] = {}
    for d in list_fn():
        if d.get("superseded_by") or (d.get("source") or {}).get("kind") == "approval":
            continue
        decided, review = str(d.get("decided_at") or "")[:10], str(d.get("review_on") or "")[:10]
        if not decided or decided > end or (review and review < start and d.get("outcome")):
            continue
        picked.setdefault((d.get("question"), d.get("chosen")), d)
    rows = sorted(picked.values(), key=lambda d: str(d.get("review_on") or ""))[:limit]
    out = []
    for d in rows:
        review = str(d.get("review_on") or "")[:10]
        state = ("reviewed: " + str(d.get("outcome_verdict"))) if d.get("outcome_verdict") else (
            "due for review " + review if review else "no review date")
        out.append(Source(id=f"decision_{str(d.get('id') or '')[:12]}", label=_short(d.get("question"), 120),
                          kind="decision", columns=["decision", "chosen", "decided", "review"],
                          rows=[[_short(d.get("question"), 200), _short(d.get("chosen"), 160),
                                 str(d.get("decided_at") or "")[:10], state]],
                          facts={"decision_id": d.get("id"), "question": _short(d.get("question"), 240),
                                 "chosen": _short(d.get("chosen"), 200), "decided": str(d.get("decided_at") or "")[:10],
                                 "review_on": review, "outcome": str(d.get("outcome_verdict") or ""), "state": state},
                          note="a decision in the record: what was chosen, when it is reviewed, and what the review found"))
    return out


def started_analysis(source_id: str, question: str, session: str) -> Source:
    """A deep analysis this edition started — running until a read finds it finished (`refreshed`)."""
    return Source(id=source_id, label=_short(question, 120), kind="analysis", status="running",
                  columns=["headline", "question", "completed"], rows=[["", _short(question, 220), ""]],
                  facts={"question": _short(question, 220), "session": session, "headline": "", "summary": "",
                         "licence": "", "started_by_edition": True},
                  note="a deep analysis this edition started; it runs in the background")


def refreshed(src: Source, *, runs_for=None, get_run=None) -> Source:
    """A running deep analysis as it stands now: finished — with its verdict — or still running. A read: nothing kept."""
    if src.kind != "analysis" or src.status != "running" or not src.facts.get("session"):
        return src
    if runs_for is None or get_run is None:
        from aughor.db.history import get_investigation, list_investigations_for_session
        runs_for, get_run = runs_for or list_investigations_for_session, get_run or get_investigation
    runs = runs_for(src.facts["session"])
    if not runs:
        return src
    run = runs[0]
    if run.get("status") != "complete":
        return src.model_copy(update={"facts": {**src.facts, "inv_id": run.get("id"),
                                                 "state": str(run.get("status") or "running")}})
    done = _analysis_source(src.id, run, (get_run(run["id"]) or {}).get("report") or {})
    return done.model_copy(update={"facts": {**done.facts, "started_by_edition": True}})

