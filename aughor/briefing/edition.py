"""Arc BG-2/BG-3 · an edition: the guide's checks measured, then written for one reader (ROADMAP §3.66).

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

**Write (BG-3, one model call per reader).** The writer is shown the figures furthest from usual — a
reader's own watch rising within its kind, every FLOOR figure (more than two standard deviations out)
always among them — with the guide's words for the range, the business and the reader, and writes the
headline, the lede, the stories and the steady lines. Then the code decides what may be shown: a
sentence stating a number no measurement holds, or claiming a cause or a forecast, sends the draft back
once with the sentences named; what still breaks a rule is withheld and listed. A floor figure the model
left out is added by code; the calendar ahead, the charts and the sources are code's, never the model's.
Each edition is kept per reader in the Briefing cache and as a version (`versions.record`).
"""
from __future__ import annotations

import re
import statistics
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field

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


# ── BG-3 · the writing ───────────────────────────────────────────────────────────────────────

#: How many measured figures the writer is shown, the floor always among them.
MAX_CANDIDATES = 12
#: Words for a whole edition, by range.
WORDS = {"day": "100-200", "week": "150-300", "month": "200-350", "year": "250-400", "custom": "150-300"}

ORGANISATION = Reader(group_id="", name="The organisation", watches="the business as a whole")


class Story(BaseModel):
    check_ids: list[str] = Field(description="The ids of the figures this story is about")
    reason: str = Field(description="unusual | streak | new_level | watch")
    title: str = Field(description="A plain sentence saying what happened")
    body: str = Field(description="Two to four sentences")


class SteadyLine(BaseModel):
    check_id: str
    line: str = Field(description="One short sentence")


class EditionDraft(BaseModel):
    headline: str = Field(description="Under 12 words: the week's story for this reader")
    lede: str = Field(description="Two or three sentences a reader who stops here still has the edition from")
    stories: list[Story]
    steady: list[SteadyLine] = Field(default_factory=list)


_SYSTEM = """\
You write one edition of a company's Briefing for ONE reader. The figures were measured by code for the
range; you choose what this reader most needs to know and say it plainly.

How to choose:
- News is what left its USUAL RANGE (the ranges before this one, mean give or take one standard
  deviation). |z| is how far outside it sits. A figure inside its usual range is not news, however large
  its change on the range before — give it at most one line under steady.
- Every figure marked floor MUST be the subject of a story, for every reader.
- Lead with what is furthest from usual among what this reader watches; then the rest that is unusual.
- Two to five stories, each about one figure or figures that belong together (check_ids). Say where a move
  sits when the segments show it; a segment marked thin is too few to call — never headline it.
- The lede says what the range was like for this reader in two or three sentences; a reader who stops
  there still has the edition.

Rules:
- Use only the numbers given, written as given (you may round them); never compute a new one.
- Name the range once, with its dates.
- Never write that one thing caused, drove, lifted, hurt or was behind another, and never predict —
  nothing here has tested a cause. Say what moved, where, and alongside what.
- Business language; no SQL, no jargon, no "z".
- Never pad: a quiet range gets a short edition."""


def _pct(v: Optional[float]) -> Optional[str]:
    return None if v is None else f"{v * 100:+.1f}%"


def _words(period: str, n: int) -> str:
    one, many = {"day": ("day", "days"), "week": ("week", "weeks"), "month": ("month", "months"),
                 "year": ("year", "years")}.get(period, ("range", "ranges"))
    return f"{n} {one if n == 1 else many}"


def _for_model(fig: dict, *, watched: bool, period: str = "custom") -> dict:
    u = fig.get("usual") or {}
    out = {"id": fig["id"], "label": fig["label"], "unit": fig["unit"], "better": fig["better"],
           "why_it_matters": fig.get("why") or "", "this_range": fig.get("current_text"),
           "range_before": fig.get("previous_text"), "change_on_range_before": _pct(fig.get("rel")),
           "a_year_earlier": fig.get("last_year_text"), "change_on_a_year_earlier": _pct(fig.get("rel_last_year")),
           "status": fig.get("status"), "watched_by_this_reader": watched, "floor": fig.get("floor", False)}
    if fig.get("like_for_like"):
        out["a_year_earlier_is"] = fig["like_for_like"]
    if u:
        out["usual_range"] = f"{u.get('low_text')} to {u.get('high_text')} (mean {u.get('mean_text')}, " \
                             f"the {_words(period, int(u.get('n') or 0))} before)"
        out["z"] = None if fig.get("z") is None else round(fig["z"], 1)
    if fig.get("streak"):
        out["in_a_row"] = f"{_words(period, abs(fig['streak']))} in a row {'up' if fig['streak'] > 0 else 'down'}"
    if fig.get("extreme"):
        out["extreme"] = f"the {fig['extreme']['which']} of the last {_words(period, fig['extreme']['of'])}"
    segs = {}
    for dim, got in (fig.get("cells") or {}).items():
        segs[dim] = [{"segment": c["group"], "this_range": c["current_text"], "usual": c["usual_text"],
                      "change_on_usual": _pct(c.get("rel")), "thin": c["thin"]} for c in got.get("cells", [])[:5]]
    if segs:
        out["segments"] = segs
    return out


def candidates(measured: dict, reader: Reader) -> list[dict]:
    """The figures the writer is shown: furthest from usual first, the reader's own watch rising within
    its kind, every floor figure included."""
    watch = set(reader.check_ids)
    figs = sorted(measured["figures"], key=lambda f: -score(f, watched=f["id"] in watch))
    top = figs[:MAX_CANDIDATES]
    for f in figs[MAX_CANDIDATES:]:
        if f["floor"]:
            top.append(f)
    return top


# ── the gates ────────────────────────────────────────────────────────────────────────────────

_MONTHS = ("january|february|march|april|may|june|july|august|september|october|november|december|"
           "jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec")
# An ISO day first: tried after the year, "2026-04-30" lost its year and read "30" as a figure (the live
# LuxExperience edition, 2026-10-29, withheld a true sentence for it).
_DATE_RE = re.compile(rf"\b\d{{4}}-\d{{2}}-\d{{2}}\b|\b\d{{1,2}}(?:\s*[–-]\s*\d{{1,2}})?\s+(?:{_MONTHS})\b"
                      rf"|\b(?:{_MONTHS})\s+\d{{1,2}}\b|\b(?:19|20)\d{{2}}\b", re.I)
_NUM_RE = re.compile(r"(?<![\w.])[-−+]?\d[\d,]*(?:\.\d+)?\s*(?:k|m|bn|%|pts?|pp)?(?![\w])", re.I)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def _allowed(figs: list[dict], usual_n: int) -> list[float]:
    vals: set[float] = {float(usual_n), float(usual_n + 1)}

    def add(v, ratio=False):
        if v is None:
            return
        v = float(v)
        vals.add(v)
        vals.add(abs(v))
        if ratio or abs(v) <= 1:
            vals.add(v * 100)
            vals.add(abs(v * 100))

    for f in figs:
        ratio = "ratio" in str(f.get("unit") or "") or "%" in str(f.get("unit") or "")
        for k in ("current", "previous", "last_year"):
            add(f.get(k), ratio)
        for k in ("rel", "rel_last_year"):
            if f.get(k) is not None:
                add(f[k] * 100)
        if f.get("current") is not None and f.get("previous") is not None:
            add(f["current"] - f["previous"], ratio)
        u = f.get("usual") or {}
        for k in ("mean", "low", "high"):
            add(u.get(k), ratio)
        if u.get("mean") is not None and f.get("current") is not None:
            add(f["current"] - u["mean"], ratio)
            if u["mean"]:
                add((f["current"] - u["mean"]) / abs(u["mean"]) * 100)
        add(f.get("n"))
        if f.get("streak"):
            add(abs(f["streak"]))
        if f.get("extreme"):
            add(f["extreme"]["of"])
        for got in (f.get("cells") or {}).values():
            for c in got.get("cells", []):
                for k in ("current", "usual", "delta", "n"):
                    add(c.get(k), ratio)
                if c.get("rel") is not None:
                    add(c["rel"] * 100)
    return sorted(vals)


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


def _texts(draft: EditionDraft) -> list[str]:
    return [draft.headline, draft.lede] + [t for s in draft.stories for t in (s.title, s.body)] \
        + [line.line for line in draft.steady]


def _withhold(text: str, held: dict[str, str], withheld: list[dict]) -> str:
    kept = []
    for sentence in _SENTENCE_RE.split(text or ""):
        s = sentence.strip()
        if s and s in held:
            withheld.append({"sentence": s, "why": held[s]})
        elif s:
            kept.append(s)
    return " ".join(kept)


def _floor_line(fig: dict) -> str:
    u = fig.get("usual") or {}
    return (f"{fig['label']}: {fig.get('current_text')}, outside its usual range of "
            f"{u.get('low_text')} to {u.get('high_text')}.")


def _coming_up(guide: BriefingGuide, spec, days: int = 45) -> list[dict]:
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


def _user_prompt(guide: BriefingGuide, reader: Reader, block: dict, figs: list[dict], *, period: str,
                 published: bool) -> str:
    import json
    note = getattr(guide.ranges, period, "") or ""
    payload = {
        "range": {"covers": block.get("covers"), "compared_with": block.get("compared_with"),
                  "a_year_earlier": block.get("last_year_label"), "what_this_range_is_for_here": note},
        "the_business": guide.business,
        "reader": {"name": reader.name, "watches": reader.watches},
        "read_with_care": [c.text for c in guide.care],
        "fair_comparisons": [c.text for c in guide.comparisons],
        "figures": [_for_model(f, watched=f["id"] in set(reader.check_ids), period=period) for f in figs],
    }
    words = WORDS.get(period, WORDS["custom"])
    return (f"Write the edition in {words} words in all.\n"
            + ("" if published else "(The guide is still a draft a person has not confirmed.)\n")
            + json.dumps(payload, default=str, ensure_ascii=False))


def write(guide: BriefingGuide, reader: Reader, block: dict, measured: dict, spec, *, published: bool,
          llm=None) -> dict:
    """One model call (two when the first draft states an unmeasured number or a cause), then the gates:
    what still breaks a rule is withheld and said; a floor figure the model left out is added by code."""
    if llm is None:
        from aughor.llm.provider import get_provider
        llm = get_provider("narrator")
    period = _period(spec)
    figs = candidates(measured, reader)
    by_id = {f["id"]: f for f in measured["figures"]}
    allowed = _allowed(measured["figures"], measured.get("usual_n", 0))
    user = _user_prompt(guide, reader, block, figs, period=period, published=published)
    calls = 1
    draft: EditionDraft = llm.complete(system=_SYSTEM, user=user, response_model=EditionDraft, temperature=0.3)
    held = {s: why for t in _texts(draft) for s, why in held_sentences(t, allowed)}
    if held:
        calls += 1
        notes = "\n".join(f"- “{s}”: {why}" for s, why in held.items())
        draft = llm.complete(system=_SYSTEM, user=user + "\n\nYour first draft broke the rules in these sentences; "
                             "write the edition again without them:\n" + notes,
                             response_model=EditionDraft, temperature=0.3)
        held = {s: why for t in _texts(draft) for s, why in held_sentences(t, allowed)}
    withheld: list[dict] = []
    stories = []
    for s in draft.stories:
        ids = [i for i in s.check_ids if i in by_id]
        title = _withhold(s.title, held, withheld)
        body = _withhold(s.body, held, withheld)
        if not (title or body):
            continue
        stories.append({"check_ids": ids, "reason": s.reason, "title": title, "body": body,
                        "figures": [by_id[i] for i in ids]})
    told = {i for s in stories for i in s["check_ids"]}
    also = [{"check_id": f["id"], "line": _floor_line(f)} for f in measured["figures"]
            if f["floor"] and f["id"] not in told]
    # "held steady" is for a figure inside its usual range — never one the model filed there that is not
    steady = [{"check_id": line.check_id, "line": _withhold(line.line, held, withheld)}
              for line in draft.steady
              if line.check_id in by_id and line.check_id not in told and not by_id[line.check_id]["outside"]]
    return {"headline": _withhold(draft.headline, held, withheld) or "",
            "lede": _withhold(draft.lede, held, withheld),
            "stories": stories, "also_unusual": also, "steady": [s for s in steady if s["line"]],
            "coming_up": _coming_up(guide, spec), "withheld": withheld, "model_calls": calls}


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


def build(conn_id: str, spec, *, scope_key: str, schema: Optional[str] = None, reader_id: str = "",
          runner=None, llm=None) -> dict:
    """Measure the guide's checks for ``spec`` and write the edition for one reader; keep it in the
    Briefing cache and as a version. Raises LookupError when the connection has no guide yet."""
    from aughor.briefing import guide as G
    from aughor.briefing import ranges, versions
    from aughor.knowledge import period_brief
    from aughor.knowledge.briefing import keep_entry
    from aughor.orgsettings import figure_currency

    guide, rev = G.current(conn_id, schema)
    if guide is None:
        raise LookupError("this dataset has no Briefing guide yet — draft it first")
    published = bool(rev and rev.is_published)
    reader = resolve_reader(guide, reader_id)
    block = ranges.range_block(spec)
    currency = figure_currency(conn_id, schema)
    with (runner or (lambda: period_brief.connection_runner(conn_id)))() as (run_sql, dialect):
        measured = measure_edition(conn_id, spec, guide, published=published, run_sql=run_sql,
                                   dialect=dialect, schema=schema, currency=currency)
    for f in measured["figures"]:
        f["name"] = f["label"]                      # the kept version compares figures by name
    if measured["figures"]:
        written = write(guide, reader, block, measured, spec, published=published, llm=llm)
    else:
        written = {"headline": "", "lede": "", "stories": [], "also_unusual": [], "steady": [],
                   "coming_up": _coming_up(guide, spec), "withheld": [], "model_calls": 0}
    entry = {"edition": True, **written,
             "reader": {"group_id": reader.group_id, "name": reader.name},
             "guide": {"version": rev.version if rev else None, "state": rev.state if rev else None},
             "period": {**block, "measured": measured["figures"]},
             "not_read": measured["not_read"], "floor": measured["floor"],
             "generated_at": datetime.now(timezone.utc).isoformat(), "currency_code": currency}
    key = cache_key(scope_key, spec, reader.group_id)
    keep_entry(key, entry)
    kept = versions.record(conn_id, entry, scope_key=scope_key, range_key=spec.key,
                           recipe=f"edition@{reader.group_id or '_organisation'}")
    entry["version"] = kept
    return entry


def sheet_lines(entry: dict) -> list[tuple[str, list[str]]]:
    """An edition as the sections a send departs with, each line judged at the departure gate: its prose
    against the queries re-run at the send (`ranges.fresh_measurement` reads each figure's own SQL)."""
    prose = [p for p in (entry.get("headline"), entry.get("lede")) if p]
    prose += [f"{s['title']} {s['body']}".strip() for s in entry.get("stories") or []]
    lines = [a["line"] for a in entry.get("also_unusual") or []] + [s["line"] for s in entry.get("steady") or []]
    out = []
    if prose:
        out.append(("narrative", prose))
    if lines:
        out.append(("measured", lines))
    return out
