"""Arc BG-2 · an edition's checks measured, and the gates every edition's words pass (ROADMAP §3.66, §3.67).

The user, 2026-10-29: *"based on the period selected the LLM figures out which are the most critical
parts or insights or numbers that the user is supposed to know based on their role."*

**Measure (BG-2, no model).** Every check the guide keeps is measured for the range, the range before,
a year earlier and its USUAL RANGE — the ranges before it (eight weeks unless the guide says otherwise),
their mean give or take one standard deviation — in one statement per check (`metric_time.run_measure`,
the measurement every Briefing figure already uses). From the series the code reads how far the figure
sits from usual (``z``), how many ranges in a row it has moved one way (``streak``), and whether it is
the highest or lowest of the ranges read; a check's dimensions break it down, each segment against its
own usual, a segment behind fewer than ``MIN_CELL_ROWS`` rows too few to call. A like-for-like rule
from a PUBLISHED guide (a storefront sold in April) filters the windows before the day it left.

What could not be measured is said: a check that failed now, the guide's notes on what to read with
care, the checks it kept out when it was drafted.

**The gates (BG-3).** A sentence stating a number no measurement holds, or claiming a cause or a forecast, may
not be shown (`unmeasured_numbers`, `held_sentences`). Arc BG's own writer (a headline, a lede and stories in one
call) was retired by Arc BC, whose edition the model composes from blocks after investigating
(`briefing/compose/`); the measurement, the gates, the calendar ahead, the cache key and the reader stay here.
"""
from __future__ import annotations

import re
import statistics
from datetime import date, timedelta
from typing import Any, Callable, Optional


from aughor.briefing.guide import BriefingGuide, Check, Reader, function_groups, measurable
from aughor.semantic import metric_time as mt

#: A segment behind fewer rows than this is too few to call — drawn grey, never headlined.
MIN_CELL_ROWS = 30
#: How many segments of a dimension an edition keeps, furthest from usual first.
MAX_CELLS = 8
#: A usual range needs at least this many earlier ranges with a value.
MIN_USUAL = 3

RunSql = Callable[[str], tuple]


def _get(m: Any, key: str):
    return m.get(key) if isinstance(m, dict) else getattr(m, key, None)


def _period(spec) -> str:
    return spec.period if spec.period in ("day", "week", "month", "year") else "custom"


def usual_windows(spec, n: int) -> list:
    """The ``n`` ranges before ``spec``, oldest first, each read at the range's own age."""
    from aughor.briefing.ranges import earlier_ranges

    age = spec.as_of - spec.end
    return [mt.Window(f"u{i + 1}", s, e, as_of=e + age)
            for i, (s, e) in enumerate(earlier_ranges(spec, n + 1)[:-1])]


def _dated_table(m: Any) -> str:
    col = str(_get(m, "time_column") or "")
    if "." in col:
        return col.split(".", 1)[0]
    tables = list(_get(m, "tables") or [])
    return tables[0] if tables else ""


def _with_filter(m: Any, cond: str) -> Any:
    filters = list(_get(m, "filters") or []) + [cond]
    return {**m, "filters": filters} if isinstance(m, dict) else m.model_copy(update={"filters": filters})


def like_for_like(guide: BriefingGuide, m: Any, *, published: bool) -> Optional[tuple[str, date, str]]:
    """``(condition, until, words)`` when a published guide compares ``m``'s table without a segment
    that left the business; None otherwise. A draft's rule is never applied — it changes a figure."""
    if not published:
        return None
    table = _dated_table(m)
    for comp in guide.comparisons:
        rule = comp.exclude_from_last_year
        if rule is None or "." not in rule.column:
            continue
        rt, col = rule.column.split(".", 1)
        if rt != table or not col.isidentifier():
            continue
        try:
            until = date.fromisoformat(rule.until) if rule.until else date.max
        except ValueError:
            continue
        value = rule.value.replace("'", "''")
        when = f" before {rule.until}" if rule.until else ""
        return f"({col} IS NULL OR {col} <> '{value}')", until, f"without {rule.value}{when}"
    return None


def _measure(m: Any, windows: list, run_sql: RunSql, dialect: str, lfl) -> tuple[dict, str, str]:
    """``({label: row}, why, sql)`` — the windows a like-for-like rule reaches measured with it."""
    if lfl is None:
        rows, why = mt.run_measure(m, windows, run_sql, dialect=dialect)
        sql, _ = mt.measure_sql(m, windows, dialect=dialect)
        return {r["window"]: r for r in rows}, why, sql or ""
    cond, until, _words = lfl
    before = [w for w in windows if w.start < until]
    after = [w for w in windows if w.start >= until]
    out: dict = {}
    sql = ""
    for group, metric in ((after, m), (before, _with_filter(m, cond))):
        if not group:
            continue
        rows, why = mt.run_measure(metric, group, run_sql, dialect=dialect)
        if why:
            return {}, why, ""
        out.update({r["window"]: r for r in rows})
        sql = sql or (mt.measure_sql(metric, group, dialect=dialect)[0] or "")
    return out, "", sql


def _unit(declared: str, values: list) -> str:
    """The unit a figure is worded in. A metric declared "ratio 0-1 (…)" whose values sit in 0..1 is a
    share and reads as a percentage — LuxExperience's conversion read "0.02" for 2.05% (2026-10-29)."""
    if declared.strip().lower().startswith("ratio") and all(v is None or 0 <= v <= 1 for v in values):
        return "ratio 0..1"
    return declared


def _text(value: Optional[float], name: str, unit: str, currency: str) -> Optional[str]:
    from aughor.briefing.ranges import figure_text
    if unit == "ratio 0..1" and value is not None and abs(value) < 0.1:
        return f"{value * 100:.2f}%"                     # a small share keeps its second decimal: 2.05%, not 2.0%
    out = figure_text(value, name, unit, currency)
    if out and unit.strip().lower() in ("%", "percent", "pct") and not out.endswith("%"):
        out += "%"
    return out


def _rel(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b in (None, 0):
        return None
    return (a - b) / abs(b)


def _streak(series: list[Optional[float]]) -> int:
    """Signed count of ranges in a row the figure moved one way, ending at the last: -3 = fell three
    times running. Zero when the last move was flat or unknown."""
    vals = [v for v in series if v is not None]
    n = 0
    for a, b in zip(reversed(vals[:-1]), reversed(vals[1:])):
        step = (b > a) - (b < a)
        if step == 0 or (n and (step > 0) != (n > 0)):
            break
        n += step
    return n


def _cells(m: Any, check: Check, windows: list, run_sql: RunSql, dialect: str, *, name: str, unit: str,
           currency: str) -> dict[str, dict]:
    """Each dimension's segments against their own usual: ``{dim: {"cells": [...], "why": ""}}``."""
    from aughor.semantic.metric_statement import is_statement

    out: dict[str, dict] = {}
    current = windows[0]
    for dim in check.dimensions[:2]:
        if is_statement(str(_get(m, "sql") or "")):
            out[dim] = {"cells": [], "why": "a whole query is not broken down by segment"}
            continue
        rows, why = mt.run_measure(m, windows, run_sql, dialect=dialect, by=dim)
        if why:
            out[dim] = {"cells": [], "why": why}
            continue
        by_group: dict[Any, dict] = {}
        for r in rows:
            g = by_group.setdefault(r["group"], {"current": None, "n": 0, "usual": []})
            if r["window"] == current.label:
                g["current"], g["n"] = r["value"], r["n"]
            elif r["value"] is not None:
                g["usual"].append(r["value"])
        cells = []
        for group, g in by_group.items():
            if g["current"] is None:
                continue
            u = statistics.fmean(g["usual"]) if g["usual"] else None
            delta = None if u is None else g["current"] - u
            cells.append({"group": "" if group is None else str(group), "current": g["current"], "usual": u,
                          "delta": delta, "rel": _rel(g["current"], u), "n": g["n"],
                          "thin": g["n"] < MIN_CELL_ROWS,
                          "current_text": _text(g["current"], name, unit, currency),
                          "usual_text": _text(u, name, unit, currency)})
        cells.sort(key=lambda c: (c["thin"], -abs(c["delta"] or 0)))
        out[dim] = {"cells": cells[:MAX_CELLS], "why": ""}
    return out


def measure_check(check: Check, m: Any, spec, *, guide: BriefingGuide, published: bool, run_sql: RunSql,
                  dialect: str, currency: str) -> tuple[Optional[dict], str]:
    """One check as an edition figure, or ``(None, why)``."""
    news = guide.news
    usual_w = usual_windows(spec, news.usual_for(_period(spec)))
    windows = spec.windows() + usual_w
    lfl = like_for_like(guide, m, published=published)
    got, why, sql = _measure(m, windows, run_sql, dialect, lfl)
    if why:
        return None, why
    cur = got.get("current") or {}
    if cur.get("value") is None or not cur.get("n"):
        return None, "it read no rows in this range"
    value = cur["value"]
    previous = (got.get("previous") or {}).get("value")
    last_year = (got.get("last_year") or {}).get("value")
    series = [{"label": w.label, "start": w.start.isoformat(), "value": (got.get(w.label) or {}).get("value")}
              for w in usual_w] + [{"label": "current", "start": spec.start.isoformat(), "value": value}]
    usual_vals = [p["value"] for p in series[:-1] if p["value"] is not None]
    name = check.label
    unit = _unit(check.unit or str(_get(m, "unit") or ""),
                 [value, previous, last_year] + usual_vals)
    fig: dict = {
        "id": check.id, "label": check.label, "metric": check.metric or None, "unit": unit,
        "better": check.better, "why": check.why, "time_kind": _get(m, "time_kind"),
        "current": value, "previous": previous, "last_year": last_year,
        "rel": _rel(value, previous), "rel_last_year": _rel(value, last_year),
        "n": cur.get("n", 0), "series": series, "sql": sql,
        "like_for_like": lfl[2] if lfl else "",
        "status": mt.figure_status(m, windows[0], as_of=spec.as_of, lag_days=spec.lag_days),
        "usual": None, "z": None, "outside": False, "floor": False,
        "streak": _streak([p["value"] for p in series]), "extreme": None,
    }
    if len(usual_vals) >= MIN_USUAL:
        mean = statistics.fmean(usual_vals)
        sd = statistics.stdev(usual_vals)
        fig["usual"] = {"mean": mean, "low": mean - sd, "high": mean + sd, "n": len(usual_vals),
                        "mean_text": _text(mean, name, unit, currency),
                        "low_text": _text(mean - sd, name, unit, currency),
                        "high_text": _text(mean + sd, name, unit, currency)}
        if sd > 0:
            z = (value - mean) / sd
            fig["z"] = z
            fig["outside"] = abs(z) >= news.outside_sd
            fig["floor"] = abs(z) >= news.floor_sd and fig["status"] != "to_date"
        everything = usual_vals + [value]
        if value >= max(everything):
            fig["extreme"] = {"which": "highest", "of": len(everything)}
        elif value <= min(everything):
            fig["extreme"] = {"which": "lowest", "of": len(everything)}
    for k in ("current", "previous", "last_year"):
        fig[f"{k}_text"] = _text(fig[k], name, unit, currency)
    fig["cells"] = _cells(m, check, [windows[0]] + usual_w, run_sql, dialect, name=name, unit=unit,
                          currency=currency) if check.dimensions else {}
    return fig, ""


def score(fig: dict, *, watched: bool) -> float:
    """How far from usual, then a reader's own watch: an unusual figure outranks a usual one whatever
    it is; a figure the reader watches rises within its kind."""
    z = abs(fig.get("z") or 0.0)
    return z + (0.75 if watched else 0.0) + (0.25 * min(abs(fig.get("streak") or 0), 4) if z >= 1 else 0.0)


def measure_edition(conn_id: str, spec, guide: BriefingGuide, *, published: bool, run_sql: RunSql,
                    dialect: str, schema: Optional[str] = None, currency: str = "") -> dict:
    """Every check of ``guide`` measured for ``spec``. No model call."""
    from aughor.briefing import ranges

    metrics_by_name = {m.name: m for m in ranges.governed_metrics(conn_id, schema)}
    figures: list[dict] = []
    unmeasured: list[dict] = []
    for check in guide.checks:
        m, why = measurable(check, metrics_by_name)
        if m is None:
            unmeasured.append({"id": check.id, "label": check.label, "reason": why})
            continue
        try:
            fig, why = measure_check(check, m, spec, guide=guide, published=published, run_sql=run_sql,
                                     dialect=dialect, currency=currency)
        except Exception as exc:  # noqa: BLE001 — one check that breaks never costs the others
            from aughor.kernel.errors import tolerate
            tolerate(exc, "an edition check could not be measured; the others stand",
                     counter="briefing.edition.check")
            fig, why = None, f"its measurement failed ({type(exc).__name__})"
        if fig is None:
            unmeasured.append({"id": check.id, "label": check.label, "reason": why})
        else:
            figures.append(fig)
    not_read = ([{"label": c.text, "reason": "", "tables": c.tables} for c in guide.care]
                + [{"label": u["label"], "reason": u["reason"], "tables": []} for u in unmeasured]
                + [{"label": d.label, "reason": d.reason, "tables": []} for d in guide.dropped])
    return {"figures": figures, "unmeasured": unmeasured, "not_read": not_read,
            "floor": [f["id"] for f in figures if f["floor"]],
            "usual_n": guide.news.usual_for(_period(spec))}


# ── who an edition is written for ────────────────────────────────────────────────────────────

ORGANISATION = Reader(group_id="", name="The organisation", watches="the business as a whole")


# ── the gates ────────────────────────────────────────────────────────────────────────────────

_MONTHS = ("january|february|march|april|may|june|july|august|september|october|november|december|"
           "jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec")
# An ISO day first: tried after the year, "2026-04-30" lost its year and read "30" as a figure (the live
# LuxExperience edition, 2026-10-29, withheld a true sentence for it).
_DATE_RE = re.compile(rf"\b\d{{4}}-\d{{2}}-\d{{2}}\b|\b\d{{1,2}}(?:\s*[–-]\s*\d{{1,2}})?\s+(?:{_MONTHS})\b"
                      rf"|\b(?:{_MONTHS})\s+\d{{1,2}}\b|\b(?:19|20)\d{{2}}\b", re.I)
_NUM_RE = re.compile(r"(?<![\w.])[-−+]?\d[\d,]*(?:\.\d+)?\s*(?:k|m|bn|%|pts?|pp)?(?![\w])", re.I)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def _read_number(token: str) -> tuple[Optional[float], float]:
    """``(value, tolerance)`` of a written number: €167.0k → 167000 ± 50; 5.1% → 5.1 ± 0.05."""
    t = token.strip().lower().replace("−", "-").replace(",", "")
    mult = 1.0
    for suffix, m in (("bn", 1e9), ("k", 1e3), ("m", 1e6)):
        if t.endswith(suffix):
            t, mult = t[: -len(suffix)].strip(), m
            break
    t = re.sub(r"(%|pts?|pp)$", "", t).strip()
    try:
        v = float(t)
    except ValueError:
        return None, 0.0
    decimals = len(t.split(".", 1)[1]) if "." in t else 0
    return v * mult, 0.5 * (10 ** -decimals) * mult


def unmeasured_numbers(text: str, allowed: list[float]) -> list[str]:
    """Every number in ``text`` that no measured figure, band edge, change or count accounts for —
    dates and years excepted. A number is accounted for when it rounds to one (within its own last
    written digit, or 0.6% of the figure)."""
    stripped = _DATE_RE.sub(" ", text or "")
    misses = []
    for m in _NUM_RE.finditer(stripped):
        v, tol = _read_number(m.group(0))
        if v is None:
            continue
        if not any(abs(abs(v) - a) <= max(tol, 0.006 * abs(a)) for a in allowed):
            misses.append(m.group(0).strip())
    return misses


def held_sentences(text: str, allowed: list[float]) -> list[tuple[str, str]]:
    """``(sentence, why)`` for each sentence that may not be shown: one stating a number the measurement
    does not hold, or one claiming a cause or a forecast (`agent/claim_type.sentence_claims`)."""
    from aughor.agent.claim_type import sentence_claims

    out = []
    claims = {s: (kind, verb) for s, kind, verb in sentence_claims(text or "") if kind in ("causal", "predictive")}
    for sentence in _SENTENCE_RE.split(text or ""):
        s = sentence.strip()
        if not s:
            continue
        misses = unmeasured_numbers(s, allowed)
        if misses:
            out.append((s, f"it states {', '.join(misses)}, which was not measured"))
        elif s in claims:
            kind, verb = claims[s]
            out.append((s, f"it claims a {'cause' if kind == 'causal' else 'forecast'} (“{verb}”)"))
    return out


def coming_up(guide: BriefingGuide, spec, days: int = 45) -> list[dict]:
    """The guide's calendar days in the weeks after the range — written by code, never by the model."""
    out = []
    start = spec.end
    for day in guide.calendar:
        when = None
        try:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day.when):
                when = date.fromisoformat(day.when)
            elif re.fullmatch(r"\d{2}-\d{2}", day.when):
                mm, dd = (int(x) for x in day.when.split("-"))
                when = date(start.year, mm, dd)
                if when < start:
                    when = date(start.year + 1, mm, dd)
        except ValueError:
            when = None
        if when and start <= when < start + timedelta(days=days):
            out.append({"name": day.name, "date": when.isoformat(),
                        "line": f"{day.name}, {when.strftime('%A')} {when.day} {when.strftime('%B')}.",
                        "source": day.source})
    return sorted(out, key=lambda d: d["date"])


# ── the edition, kept per reader ─────────────────────────────────────────────────────────────

def cache_key(scope_key: str, spec, reader_id: str) -> str:
    return f"{scope_key}#{spec.key}@{reader_id or '_organisation'}"


def resolve_reader(guide: BriefingGuide, reader_id: str) -> Reader:
    """The guide's reader for a group, or the organisation's when the group has none in the guide."""
    if reader_id:
        found = guide.reader(reader_id)
        if found:
            return found
        name = next((g["name"] for g in function_groups() if g["id"] == reader_id), reader_id)
        return Reader(group_id=reader_id, name=name, watches="")
    return ORGANISATION
