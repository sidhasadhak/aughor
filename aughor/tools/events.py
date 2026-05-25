"""
Events Calendar Tool — Sprint 3.

Loads business calendar events from two sources:
  1. data/events.yaml — static external calendar (promotions, holidays, outages)
  2. DB's own events table (if it exists) — live operational events

Provides get_events_context(question, conn, data_date_range) which:
  - Infers the investigation time window from the question text and/or data date range
  - Filters to overlapping events
  - Returns a compact formatted block to inject into planner prompts

The goal: when the agent investigates anomalies, it can attribute revenue drops/spikes to
known business events rather than fabricating hypotheses about unknown root causes.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from aughor.db.connection import DatabaseConnection

_EVENTS_YAML = Path(__file__).parent.parent.parent / "data" / "events.yaml"

# Month name → number for question parsing
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class CalendarEvent:
    date: date
    end_date: date
    type: str               # promotion | holiday | outage | release | campaign | external
    name: str
    description: str
    expected_impact: str = ""
    tags: list[str] = field(default_factory=list)
    source: str = "yaml"    # "yaml" | "db"


# ── YAML loader ───────────────────────────────────────────────────────────────

def _parse_date(value) -> date:
    if isinstance(value, date):
        return value
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            from datetime import datetime
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {s!r}")


def load_events(path: Optional[Path] = None) -> list[CalendarEvent]:
    """Load events from the YAML calendar file. Returns [] on any failure."""
    p = path or _EVENTS_YAML
    if not p.exists():
        return []
    try:
        import yaml  # PyYAML — already a dep via langchain/langgraph
    except ImportError:
        try:
            import ruamel.yaml as yaml  # type: ignore
        except ImportError:
            return []
    try:
        with open(p) as f:
            raw = yaml.safe_load(f) or {}
    except Exception:
        return []

    events: list[CalendarEvent] = []
    for e in raw.get("events", []):
        try:
            start = _parse_date(e["date"])
            end = _parse_date(e["end_date"]) if "end_date" in e else start
            events.append(CalendarEvent(
                date=start,
                end_date=end,
                type=e.get("type", "external"),
                name=e.get("name", ""),
                description=e.get("description", ""),
                expected_impact=e.get("expected_impact", ""),
                tags=list(e.get("tags", [])),
                source="yaml",
            ))
        except Exception:
            continue
    return events


# ── DB events loader ──────────────────────────────────────────────────────────

def load_events_from_db(conn: "DatabaseConnection") -> list[CalendarEvent]:
    """
    Try to query a DB events table that matches the canonical shape:
      event_type, title/name, description, start_date, end_date,
      affected_region, affected_segment

    Silently returns [] if the table doesn't exist or has a different schema.
    """
    # We try a few common column-name patterns
    _CANDIDATES = [
        # (table, type_col, name_col, desc_col, start_col, end_col, region_col, segment_col)
        ("events", "event_type", "title", "description", "start_date", "end_date", "affected_region", "affected_segment"),
        ("business_events", "type", "name", "description", "start_date", "end_date", "region", "segment"),
        ("calendar_events", "type", "name", "description", "event_date", "end_date", "region", "segment"),
    ]

    for table, tc, nc, dc, sc, ec, rc, sgc in _CANDIDATES:
        sql = (
            f'SELECT {tc}, {nc}, {dc}, '
            f'CAST({sc} AS VARCHAR), CAST({ec} AS VARCHAR), '
            f'{rc}, {sgc} '
            f'FROM "{table}" ORDER BY {sc}'
        )
        try:
            result = conn.execute("__events_scan__", sql)
            if result.error or not result.rows:
                continue
            events: list[CalendarEvent] = []
            for row in result.rows:
                event_type, name, desc, start_str, end_str, region, segment = (
                    row[0], row[1], row[2], row[3], row[4], row[5], row[6]
                )
                try:
                    start = _parse_date(start_str)
                    end = _parse_date(end_str) if end_str else start
                except Exception:
                    continue
                tags = [x for x in [region, segment] if x and str(x).upper() not in ("", "ALL", "NONE", "NULL")]
                events.append(CalendarEvent(
                    date=start,
                    end_date=end,
                    type=(event_type or "external").lower(),
                    name=name or "",
                    description=desc or "",
                    tags=tags,
                    source="db",
                ))
            if events:
                return events
        except Exception:
            continue
    return []


# ── Date-range extraction from question text ──────────────────────────────────

def extract_date_range_from_question(
    question: str,
    ref: Optional[date] = None,
) -> Optional[tuple[date, date]]:
    """
    Parse temporal keywords in a question and return a (start, end) date range.
    Returns None if no clear temporal signal is found.

    Handles: last week / this week / last month / this month / last year /
             this year / Q1–Q4 YYYY / Q1–Q4 (current year) / Month YYYY /
             explicit YYYY-MM-DD dates.
    """
    r = ref or date.today()
    q = question.lower()

    # "last week"
    if re.search(r'\blast\s+week\b', q):
        end = r - timedelta(days=r.weekday() + 1)   # last Sunday
        start = end - timedelta(days=6)
        return start, end

    # "this week"
    if re.search(r'\bthis\s+week\b', q):
        start = r - timedelta(days=r.weekday())
        return start, r

    # "last month"
    if re.search(r'\blast\s+month\b', q):
        first_of_this = r.replace(day=1)
        last_of_prev = first_of_this - timedelta(days=1)
        return last_of_prev.replace(day=1), last_of_prev

    # "this month"
    if re.search(r'\bthis\s+month\b', q):
        return r.replace(day=1), r

    # "last year"
    if re.search(r'\blast\s+year\b', q):
        y = r.year - 1
        return date(y, 1, 1), date(y, 12, 31)

    # "this year"
    if re.search(r'\bthis\s+year\b', q):
        return date(r.year, 1, 1), r

    # "Q1 2024", "q3 2025" etc.
    m = re.search(r'\bq([1-4])\s*(\d{4})\b', q)
    if m:
        q_num, yr = int(m.group(1)), int(m.group(2))
        sm = (q_num - 1) * 3 + 1
        em = q_num * 3
        start = date(yr, sm, 1)
        end = date(yr, em, calendar.monthrange(yr, em)[1])
        return start, end

    # "Q1", "Q2" etc. without year → current year
    m = re.search(r'\bq([1-4])\b', q)
    if m:
        q_num = int(m.group(1))
        yr = r.year
        sm = (q_num - 1) * 3 + 1
        em = q_num * 3
        start = date(yr, sm, 1)
        end = date(yr, em, calendar.monthrange(yr, em)[1])
        return start, end

    # "November 2025", "October 2024" etc.
    month_pattern = "|".join(_MONTHS.keys())
    m = re.search(rf'\b({month_pattern})\b[^\d]*(\d{{4}})\b', q)
    if m:
        mn_num = _MONTHS[m.group(1)]
        yr = int(m.group(2))
        start = date(yr, mn_num, 1)
        end = date(yr, mn_num, calendar.monthrange(yr, mn_num)[1])
        return start, end

    # Explicit YYYY-MM-DD date in question
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', q)
    if m:
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            # Use ±30 days around the mentioned date
            return d - timedelta(days=30), d + timedelta(days=30)
        except ValueError:
            pass

    return None  # No temporal signal found


# ── Filter and render ─────────────────────────────────────────────────────────

def get_events_in_range(
    start: date,
    end: date,
    events: list[CalendarEvent],
) -> list[CalendarEvent]:
    """Return events that overlap with [start, end] (inclusive)."""
    return [e for e in events if e.date <= end and e.end_date >= start]


def render_events_context(events: list[CalendarEvent]) -> str:
    """Format a compact block of calendar events for prompt injection."""
    if not events:
        return ""
    lines: list[str] = []
    for e in sorted(events, key=lambda x: x.date):
        date_str = (
            str(e.date) if e.date == e.end_date
            else f"{e.date} → {e.end_date}"
        )
        scope = f" [{', '.join(e.tags)}]" if e.tags else ""
        impact = f"\n    Impact: {e.expected_impact}" if e.expected_impact else ""
        lines.append(
            f"  {date_str}  [{e.type.upper()}]  {e.name}{scope}\n"
            f"    {e.description}{impact}"
        )
    return "\n".join(lines)


# ── Main entry point ──────────────────────────────────────────────────────────

def get_events_context(
    question: str,
    conn: Optional["DatabaseConnection"] = None,
    data_date_range: Optional[tuple[str, str]] = None,
    events_path: Optional[Path] = None,
) -> str:
    """
    Return a formatted business calendar context string for the given question,
    or "" if no relevant events are found.

    Resolution order:
      1. Query the DB's events table (if conn provided and table exists)
      2. Load from data/events.yaml
      3. Merge and deduplicate by (name, date)
      4. Filter to the investigation's date range (inferred from question and/or data)
      5. Return formatted context

    The date range is determined as:
      - question temporal keywords ("last week", "Q3 2025", "November 2025", …)
      - data_date_range from the schema profiler (min/max dates across all tables)
      - fallback: last 120 days from today
    """
    # ── Build search range ────────────────────────────────────────────────────
    question_range = extract_date_range_from_question(question)

    data_range: Optional[tuple[date, date]] = None
    if data_date_range:
        try:
            data_range = (
                date.fromisoformat(str(data_date_range[0])[:10]),
                date.fromisoformat(str(data_date_range[1])[:10]),
            )
        except Exception:
            pass

    if question_range:
        search_start, search_end = question_range
        # Expand by data range if available (use the broader window)
        if data_range:
            search_start = min(search_start, data_range[0])
            search_end = max(search_end, data_range[1])
    elif data_range:
        search_start, search_end = data_range
    else:
        # No temporal signal — use the last 120 days
        today = date.today()
        search_start = today - timedelta(days=120)
        search_end = today

    # ── Load events from both sources ─────────────────────────────────────────
    all_events: list[CalendarEvent] = []

    # Source 1: live DB events table
    if conn is not None:
        try:
            db_events = load_events_from_db(conn)
            all_events.extend(db_events)
        except Exception:
            pass

    # Source 2: YAML calendar
    try:
        yaml_events = load_events(events_path)
        all_events.extend(yaml_events)
    except Exception:
        pass

    if not all_events:
        return ""

    # ── Filter to range and deduplicate ──────────────────────────────────────
    relevant = get_events_in_range(search_start, search_end, all_events)

    # Deduplicate: DB takes precedence over YAML for same-typed events on the same day.
    # Key is (type, start_date) — e.g. two "holiday" events on 2025-10-26 are the same
    # real-world event regardless of how the name is worded.
    # DB source is sorted first so it wins.
    seen: dict[tuple, CalendarEvent] = {}
    for e in sorted(relevant, key=lambda x: (x.date, x.source != "db")):  # db first
        key = (e.type.lower(), e.date)
        if key not in seen:
            seen[key] = e
    deduped = sorted(seen.values(), key=lambda x: x.date)

    if not deduped:
        return ""

    formatted = render_events_context(deduped)
    return (
        f"BUSINESS CALENDAR — {len(deduped)} event{'s' if len(deduped) != 1 else ''} "
        f"in the investigation window ({search_start} → {search_end}):\n"
        + formatted
    )
