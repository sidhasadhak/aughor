"""Arc BG-1 · the Briefing guide (ROADMAP §3.66, §6 item 58).

The user, 2026-10-29: *"a good prompt for each connection which will be built by the LLM itself as
a part of the exploration phase. Because in exploration phase it understand what business it is
what are the matrix? What is the data saying so and so forth, then why should it not also marry
the way in which the briefing should turn out for that connection."*

Until now every range Briefing ran one fixed recipe per horizon (`recipes.py`): the same sections
and the same words for an airline and a fashion group. The guide is that judgement written down
once per connection and dataset, from what the Explorer learned — the business, what a week, a month
and a year are for HERE, what counts as news, which comparisons are fair (a storefront sold in
April is compared without it), the calendar, what to read with care (a table whose data ended),
the readers this business has and what each watches — and the CHECKS an edition measures.

**Judgement, never a figure.** The guide states no number an edition prints: an edition measures
every check against its range (`edition.py`), and the guide only says what to measure and how to
read it. A check is an approved metric by name, or an aggregate the drafter wrote AND ran once
over the last complete week — one that fails is kept out, with why, never silently dropped.

**A draft until a person publishes it.** Each version is a Ledger artifact through
`kernel/lifecycle.py` (supersede, never delete). The Explorer's draft is used by editions, which
say so; a published version is what editions read once there is one, and a later draft never
replaces it — a re-exploration cannot overwrite what a person confirmed. A rule that changes a
figure (a like-for-like exclusion) applies only from a published version.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

KIND = "briefing_guide"
#: The kernel job kind an exploration's draft runs as — the Briefer's (`kernel/agents.py`).
JOB_KIND = "briefing_guide"
#: How many checks a guide keeps: an edition measures every one, one statement each.
MAX_CHECKS = 24


# ── the guide ────────────────────────────────────────────────────────────────────────────────

class Check(BaseModel):
    """One thing an edition measures. Either ``metric`` — an approved metric's name, measured by its
    own definition — or ``sql``: an aggregate expression over ``tables[0]`` (``SUM(refund_eur)``),
    or a whole SELECT when a join cannot be avoided, with the date that places its rows in a range."""
    id: str = Field(description="snake_case, unique in the guide, e.g. 'refunds_received'")
    label: str = Field(description="What a reader calls it, e.g. 'Refunds paid on returns received'")
    metric: str = Field(default="", description="An approved metric's exact name; leave sql empty then")
    sql: str = Field(default="", description="An aggregate expression over ONE table, e.g. 'SUM(refund_eur)'; "
                                             "a whole SELECT only when a join is unavoidable")
    tables: list[str] = Field(default_factory=list, description="The table(s) sql reads, the dated one first")
    filters: list[str] = Field(default_factory=list, description="WHERE conditions always applied, e.g. "
                                                                 "\"reason = 'size_fit'\"")
    time_column: str = Field(default="", description="table.column that places a row in a range")
    time_kind: Literal["flow", "stock", "cohort"] = "flow"
    unit: str = Field(default="", description="EUR, %, count, days, ratio …")
    better: Literal["up", "down", "none"] = Field(default="none", description="Which way is good")
    dimensions: list[str] = Field(default_factory=list,
                                  description="Low-cardinality columns of the dated table to break it down by")
    why: str = Field(default="", description="Why it matters for this business, one line")
    evidence: str = Field(default="", description="The table, finding or metric this rests on")


class LikeForLike(BaseModel):
    """A segment a year earlier is compared without: ``column`` = ``value`` before ``until``."""
    column: str = Field(description="table.column, e.g. 'orders.platform'")
    value: str
    until: str = Field(default="", description="ISO date the segment left the business")


class Comparison(BaseModel):
    text: str
    exclude_from_last_year: Optional[LikeForLike] = None
    evidence: str = ""


class CalendarDay(BaseModel):
    name: str
    when: str = Field(description="An ISO date, or a yearly day as MM-DD")
    source: Literal["data", "calendar"] = Field(description="'data' when the data's own calendar marks it")
    evidence: str = ""


class CareNote(BaseModel):
    text: str
    tables: list[str] = Field(default_factory=list)
    evidence: str = ""


class Reader(BaseModel):
    """Who an edition is written for: a function group (``group_id``), or the organisation ("")."""
    group_id: str = ""
    name: str
    watches: str = Field(description="What this reader watches and decides, in plain words")
    check_ids: list[str] = Field(default_factory=list)


class RangeNotes(BaseModel):
    """What each range is for at THIS business, one or two sentences each."""
    week: str = ""
    month: str = ""
    year: str = ""
    custom: str = ""
    day: str = ""


class NewsRule(BaseModel):
    """What counts as news: outside the usual range — the mean of the ranges before, give or take
    ``outside_sd`` standard deviations; beyond ``floor_sd`` it appears for every reader."""
    usual_week: int = 8
    usual_month: int = 6
    usual_year: int = 3
    usual_day: int = 8
    usual_custom: int = 6
    outside_sd: float = 1.0
    floor_sd: float = 2.0

    def usual_for(self, period: str) -> int:
        return int(getattr(self, f"usual_{period}", None) or self.usual_custom)


class DroppedCheck(BaseModel):
    id: str
    label: str
    reason: str


class BriefingGuide(BaseModel):
    business: str = ""
    ranges: RangeNotes = Field(default_factory=RangeNotes)
    news: NewsRule = Field(default_factory=NewsRule)
    comparisons: list[Comparison] = Field(default_factory=list)
    calendar: list[CalendarDay] = Field(default_factory=list)
    care: list[CareNote] = Field(default_factory=list)
    checks: list[Check] = Field(default_factory=list)
    #: Checks the drafter proposed that could not be measured — said, never silently dropped.
    dropped: list[DroppedCheck] = Field(default_factory=list)
    readers: list[Reader] = Field(default_factory=list)
    #: Readers this business seems to have and the organisation has not added yet; a person adds them.
    proposed_readers: list[Reader] = Field(default_factory=list)

    def check(self, check_id: str) -> Optional[Check]:
        return next((c for c in self.checks if c.id == check_id), None)

    def reader(self, group_id: str) -> Optional[Reader]:
        return next((r for r in self.readers if r.group_id == group_id), None)


class _Draft(BaseModel):
    """What the model writes. The news rule, the readers people added and the verification are the
    code's and a person's, never the model's."""
    business: str = Field(description="Two or three sentences: what this business is and how it makes money")
    ranges: RangeNotes
    comparisons: list[Comparison] = Field(default_factory=list)
    calendar: list[CalendarDay] = Field(default_factory=list)
    care: list[CareNote] = Field(default_factory=list)
    checks: list[Check] = Field(default_factory=list)
    readers: list[Reader] = Field(default_factory=list,
                                  description="Three to six readers this business has, each with the check ids "
                                              "it watches")


# ── where it is kept ─────────────────────────────────────────────────────────────────────────

def natural_key(conn_id: str, schema: Optional[str] = None) -> str:
    return f"{KIND}:{conn_id}|{schema or ''}"


def _parse(body: dict) -> Optional[BriefingGuide]:
    try:
        return BriefingGuide.model_validate(body or {})
    except Exception as exc:  # noqa: BLE001 — a version that no longer parses is said, not raised
        from aughor.kernel.errors import tolerate
        tolerate(exc, "a kept guide version no longer parses; it is read as absent",
                 counter="briefing.guide.parse")
        return None


def versions(conn_id: str, schema: Optional[str] = None, *, limit: int = 50) -> list:
    """Every kept version, newest first (`lifecycle.Revision`)."""
    from aughor.kernel import lifecycle
    return lifecycle.history(KIND, natural_key(conn_id, schema), limit=limit)


def current(conn_id: str, schema: Optional[str] = None) -> tuple[Optional[BriefingGuide], Optional[Any]]:
    """The guide an edition reads, and its version: the newest PUBLISHED version once there is one —
    a later draft never replaces what a person confirmed — else the newest draft."""
    revs = versions(conn_id, schema)
    rev = next((r for r in revs if r.is_published), None) or (revs[0] if revs else None)
    return (_parse(rev.body), rev) if rev else (None, None)


def working_copy(conn_id: str, schema: Optional[str] = None) -> tuple[Optional[BriefingGuide], Optional[Any]]:
    """The newest version of any state — what an editor edits."""
    revs = versions(conn_id, schema, limit=1)
    return (_parse(revs[0].body), revs[0]) if revs else (None, None)


def save(conn_id: str, schema: Optional[str], guide: BriefingGuide, *, by: str, note: str = "",
         publish: bool = False):
    """Keep ``guide`` as a new version — a draft, or published. ``by`` is required: the Explorer's
    draft says so, and a person's edit names the person (provenance, AGENTS.md)."""
    if not by:
        raise ValueError("a guide version needs who wrote it")
    from aughor.kernel import lifecycle
    return lifecycle.record(KIND, natural_key(conn_id, schema), guide.model_dump(mode="json"),
                            "published" if publish else "draft", by=by, note=note, conn_id=conn_id)


def publish(conn_id: str, schema: Optional[str], *, by: str, version: Optional[int] = None):
    """Publish a version (the newest, unless named) by writing it forward as published under ``by``."""
    from aughor.kernel import lifecycle
    revs = versions(conn_id, schema)
    src = next((r for r in revs if r.version == version), None) if version is not None else (revs[0] if revs else None)
    if src is None:
        return None
    guide = _parse(src.body)
    if guide is None:
        return None
    return lifecycle.record(KIND, natural_key(conn_id, schema), guide.model_dump(mode="json"), "published",
                            by=by, note=f"published version {src.version}", conn_id=conn_id)


# ── checks: what can be measured ─────────────────────────────────────────────────────────────

_ID_RE = re.compile(r"[^a-z0-9_]+")


def _slug(s: str) -> str:
    return _ID_RE.sub("_", str(s or "").strip().lower()).strip("_")[:60] or "check"


def measurable(check: Check, metrics_by_name: dict) -> tuple[Optional[Any], str]:
    """What `metric_time.run_measure` measures for ``check``: the approved metric's own definition, or
    the check's aggregate as a metric-like dict. ``(None, why)`` when neither can be measured."""
    if check.metric:
        m = metrics_by_name.get(check.metric)
        return (m, "") if m is not None else (None, f"no approved metric is named {check.metric}")
    if not check.sql.strip():
        return None, "it names neither an approved metric nor an aggregate"
    if not check.time_column or "." not in check.time_column:
        return None, "it names no date (table.column) to place its rows in a range"
    tables = list(check.tables) or [check.time_column.split(".", 1)[0]]
    return {"name": check.id, "label": check.label, "sql": check.sql, "tables": tables,
            "filters": list(check.filters), "time_column": check.time_column,
            "time_kind": check.time_kind, "unit": check.unit, "dimensions": list(check.dimensions)}, ""


def verify_checks(checks: list[Check], *, metrics_by_name: dict, run_sql, dialect: str,
                  windows: list) -> tuple[list[Check], list[DroppedCheck]]:
    """Each check measured once over ``windows`` (the last complete week and the one before): one that
    cannot be built, fails, or reads no rows in either is kept out with its reason."""
    from aughor.semantic import metric_time as mt

    kept: list[Check] = []
    dropped: list[DroppedCheck] = []
    seen: set[str] = set()
    for c in checks:
        c = c.model_copy(update={"id": _slug(c.id or c.label)})
        if c.id in seen:
            c = c.model_copy(update={"id": f"{c.id}_{len(seen)}"})
        m, why = measurable(c, metrics_by_name)
        if m is None:
            dropped.append(DroppedCheck(id=c.id, label=c.label, reason=why))
            continue
        rows, why = mt.run_measure(m, windows, run_sql, dialect=dialect)
        if why:
            dropped.append(DroppedCheck(id=c.id, label=c.label, reason=why))
            continue
        if not any(r.get("n") and r.get("value") is not None for r in rows):
            dropped.append(DroppedCheck(id=c.id, label=c.label,
                                        reason="it read no rows in the last two complete weeks"))
            continue
        seen.add(c.id)
        kept.append(c)
        if len(kept) >= MAX_CHECKS:
            break
    return kept, dropped


# ── the draft ────────────────────────────────────────────────────────────────────────────────

_SYSTEM = """\
You write the BRIEFING GUIDE for one company's data: how its periodic Briefing should be written. You
have explored the data; now write down the judgement a good analyst at this company would use.

Write:
- business: what the company is and how it makes money, in two or three sentences.
- ranges: what a week, a month, a year and a custom range are FOR here — what each can and cannot show
  (e.g. a week is too short to read an outcome that settles over weeks).
- comparisons: what makes a comparison fair here. When the data shows a segment that LEFT the business
  (a storefront, a region, a product line with no rows after a date), say so and fill
  exclude_from_last_year with its column (table.column), value and the ISO date it left.
- calendar: the days that move this business. Use the data's own calendar columns where the schema has
  them (source "data"); otherwise well-known days for this kind of business (source "calendar").
- care: what to read with care — tables whose data ended (the context lists each table's last day),
  outcomes that arrive late, values a column never takes, money that is recorded at another scale.
- checks: 10 to 20 things an edition should measure, the ones that matter most here. Prefer an APPROVED
  METRIC by its exact name (listed in the context). For what no metric covers, write sql as an aggregate
  expression over ONE table (e.g. "SUM(refund_eur)" with tables ["returns"] and time_column
  "returns.return_date"), with filters for a slice; a whole SELECT only when a join is unavoidable. Give
  each check 0-2 dimensions: low-cardinality columns of its dated table that would show WHERE a move
  sits (a storefront, a device, a reason). Never a check on a table whose data has ended.
- readers: three to six readers this company has — leadership, finance, and the functions its data
  covers — each with what they watch in plain words and the check ids they watch. When the context lists
  the organisation's groups, use their names and ids.

Rules:
- Judgement only. Quote a number only when it appears in the context given to you (a table's last day,
  the settling lag); never invent, estimate or recall one.
- Use the real table and column names from the schema; never invent one.
- Say nothing about causes.
"""


def _context(conn_id: str, schema: Optional[str], *, today: date) -> str:
    """Everything the drafter reads, in words: the schema with the exploration's annotations, the
    profile, the approved metrics, where each table's data ends, the settling lag, the fiscal year and
    the organisation's groups."""
    from aughor.business_profile import store as profile_store
    from aughor.business_profile.infer import gather_context
    from aughor.briefing import ranges
    from aughor.kernel.errors import tolerate

    parts: list[str] = []
    schema_text, domains = gather_context(conn_id, schema)
    raw = profile_store.load_raw(conn_id, schema) or {}
    prof = raw.get("profile") or {}
    if prof:
        parts.append("BUSINESS PROFILE (the Explorer's):\n" + json.dumps(
            {k: prof.get(k) for k in ("industry", "business_model", "summary", "currency_code", "key_questions")},
            default=str)[:4000])
    metrics = ranges.governed_metrics(conn_id, schema)
    if metrics:
        lines = [f"- {m.name}: {m.label} · unit {m.unit or '-'} · dated by {m.time_column or 'NOT SET'} · "
                 f"dimensions {', '.join(m.dimensions) or '-'}" for m in metrics]
        parts.append("APPROVED METRICS:\n" + "\n".join(lines))
    try:
        edge = ranges.data_edge(conn_id, schema, today=today)
        tables = edge.get("tables") or {}
        if tables:
            parts.append("EACH TABLE'S LAST DAY OF DATA (today is " + today.isoformat() + "):\n"
                         + "\n".join(f"- {t}: {d}" for t, d in sorted(tables.items())))
    except Exception as exc:  # noqa: BLE001
        tolerate(exc, "the data's edge could not be read for the guide", counter="briefing.guide.edge")
    try:
        from aughor.settling.store import connection_lag
        lag = connection_lag(conn_id)
        if lag.get("days") is not None:
            parts.append(f"SETTLING LAG: {lag['days']} days ({lag.get('source')}); still moving: "
                         f"{', '.join(lag.get('still_moving') or []) or 'none'}")
    except Exception as exc:  # noqa: BLE001
        tolerate(exc, "the settling lag could not be read for the guide", counter="briefing.guide.lag")
    try:
        from aughor.orgsettings import effective_settings
        parts.append(f"FISCAL YEAR STARTS IN MONTH {int(getattr(effective_settings(None), 'fiscal_year_start_month', 1) or 1)}")
    except Exception as exc:  # noqa: BLE001
        tolerate(exc, "org settings unreadable for the guide", counter="briefing.guide.fiscal")
    groups = function_groups()
    if groups:
        parts.append("THE ORGANISATION'S GROUPS:\n" + "\n".join(f"- {g['id']}: {g['name']} — {g['description']}"
                                                                for g in groups))
    parts.append(f"DOMAINS: {', '.join(domains) or 'none'}")
    parts.append("SCHEMA (with what the exploration learned):\n" + schema_text)
    return "\n\n".join(parts)


def function_groups() -> list[dict]:
    """The organisation's function groups — the readers a guide can name."""
    try:
        from aughor.org.context import current_org_id
        from aughor.rbac.groups import list_groups
        return [{"id": g.id, "name": g.name, "description": g.description or ""}
                for g in list_groups(current_org_id() or "default")]
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "function groups unreadable; the guide proposes readers by name only",
                 counter="briefing.guide.groups")
        return []


def _place_readers(drafted: list[Reader], previous: Optional[BriefingGuide],
                   check_ids: set[str]) -> tuple[list[Reader], list[Reader]]:
    """(readers, proposed): readers a person already had stay as they were; a drafted reader whose
    group exists becomes one of them, the rest are proposals a person adds."""
    groups = {g["id"] for g in function_groups()}
    kept = list(previous.readers) if previous else []
    have = {r.group_id for r in kept}
    proposed: list[Reader] = []
    for r in drafted:
        r = r.model_copy(update={"check_ids": [c for c in r.check_ids if c in check_ids]})
        if r.group_id and r.group_id in groups:
            if r.group_id not in have:
                kept.append(r)
                have.add(r.group_id)
        else:
            proposed.append(r.model_copy(update={"group_id": ""}))
    return kept, proposed


def draft_guide(conn_id: str, schema: Optional[str] = None, *, today: Optional[date] = None,
                by: str = "explorer", runner=None, llm=None):
    """Draft the guide from what the exploration learned — one model call — verify each check over
    the last complete week, and keep it as a new DRAFT version. Returns the kept revision."""
    from aughor.briefing import ranges
    from aughor.knowledge import period_brief

    today = today or datetime.now(timezone.utc).date()
    if llm is None:
        from aughor.llm.provider import get_provider
        llm = get_provider("coder")
    draft: _Draft = llm.complete(system=_SYSTEM, user=_context(conn_id, schema, today=today),
                                 response_model=_Draft, temperature=0.2)
    spec, why = ranges.resolve_for(conn_id, "last_week", schema=schema, today=today)
    if spec is None:
        raise ValueError(f"the last complete week could not be resolved: {why}")
    metrics_by_name = {m.name: m for m in ranges.governed_metrics(conn_id, schema)}
    with (runner or (lambda: period_brief.connection_runner(conn_id)))() as (run_sql, dialect):
        checks, dropped = verify_checks(draft.checks, metrics_by_name=metrics_by_name, run_sql=run_sql,
                                        dialect=dialect, windows=spec.windows()[:2])
    previous, _rev = current(conn_id, schema)
    readers, proposed = _place_readers(draft.readers, previous, {c.id for c in checks})
    guide = BriefingGuide(business=draft.business, ranges=draft.ranges,
                          news=previous.news if previous else NewsRule(),
                          comparisons=draft.comparisons, calendar=draft.calendar, care=draft.care,
                          checks=checks, dropped=dropped, readers=readers, proposed_readers=proposed)
    return save(conn_id, schema, guide, by=by,
                note=f"drafted from the exploration; {len(checks)} checks measured, {len(dropped)} kept out")


async def submit_draft(conn_id: str, schema: Optional[str], *, fingerprint: str = "") -> Optional[str]:
    """Hand the draft to the kernel as the Briefer's job, keyed on the schema fingerprint so an
    unchanged schema re-explored drafts nothing twice. Returns the job id."""
    import asyncio

    from aughor.kernel.jobs import kernel

    async def _work():
        rev = await asyncio.to_thread(draft_guide, conn_id, schema)
        return {"version": getattr(rev, "version", None)}

    return await kernel().submit(
        JOB_KIND, _work, conn_id=conn_id,
        idempotency_key=f"{JOB_KIND}:{conn_id}:{schema or ''}:{fingerprint or 'unfingerprinted'}")
