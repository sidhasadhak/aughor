"""What a Slack post's picture is — the step's own settings, read in one place (2026-11-06).

The user, looking at the Daily Briefing's chart: *"User should be able to control everything that
gets posted — the prompt, the picture or not, what kind of picture."* The engine used to decide all
of it: the first result the message's source published, drawn `auto`, titled with the automation's
name. Now a `slack_post` step says, in its config (every key optional; absent is that behaviour):

* ``picture`` — ``none`` · ``table`` · ``chart`` (default ``chart``)
* ``chart_kind`` — one of `KINDS` (default ``auto``: the answer's own decision)
* ``picture_from`` — ``main`` · ``over_time`` · ``every``: a RULE, because the investigation writes
  new results each run (default ``main``)
* ``picture_title`` — ``sentence`` (the result's own claim) · ``name`` · ``custom`` with
  ``picture_title_text`` (default ``sentence``)
* ``picture_names`` — ``{column: name, "axis": name}``: a person's names, applied whenever that
  column comes back; anything else is named from its SQL (`answer/series_names.py`)

The post and the step's preview both plan through `plan()`, so what the preview shows is what posts.
A kind a result cannot take — horizontal bars or a pie over two series, a line with no time column —
falls back to ``auto`` and says why, in the thread and in the preview; it never drops a series.
"""
from __future__ import annotations

import re
from typing import Any, Optional

#: The kinds a Slack picture can be drawn as — what the headless renderer draws — in the order a
#: person meets them, with the word each reads as.
KINDS: dict[str, str] = {"auto": "Auto", "bar": "Bars", "bar_horizontal": "Horizontal bars",
                         "line": "Line", "pie": "Pie", "counter": "Number"}
#: How a kind reads in "Asked for …" when it had to fall back.
_ASKED = {"bar": "bars", "bar_horizontal": "horizontal bars", "line": "a line", "pie": "a pie",
          "counter": "a number"}
PICTURES = ("none", "table", "chart")
SOURCES = ("main", "over_time", "every")
TITLES = ("sentence", "name", "custom")
#: How many pictures `every` posts, and how many rows a table picture shows.
MAX_PICTURES = 4
TABLE_ROWS = 15

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _date_col(values: list) -> bool:
    seen = [v for v in values if v not in (None, "")]
    return bool(seen) and all(_DATE.match(str(v)) for v in seen)


def shape(columns: list[str], rows: list[list]) -> tuple[list[str], list[str], list[str]]:
    """``(dates, measures, dims)`` of a result, read off its values."""
    dates, measures, dims = [], [], []
    for i, c in enumerate(columns):
        vals = [r[i] if i < len(r) else None for r in rows]
        if _date_col(vals):
            dates.append(c)
        elif all(_num(v) is not None for v in vals if v not in (None, "")) and any(v not in (None, "") for v in vals):
            measures.append(c)
        else:
            dims.append(c)
    return dates, measures, dims


def kind_fit(kind: str, columns: list[str], rows: list[list], names: Optional[dict] = None) -> tuple[bool, str]:
    """Whether ``kind`` can draw this result whole, and why not when it cannot."""
    labels = (names or {}).get("labels") or {}
    dates, measures, dims = shape(columns, rows)
    said = lambda cols: ", ".join(labels.get(c, c) for c in cols)            # noqa: E731
    if kind == "auto":
        return True, ""
    if kind not in KINDS:
        return False, "not a kind a Slack picture can be drawn as"
    if not measures:
        return False, "no number in this result to draw"
    if kind == "bar":
        return (True, "") if (dims or dates) else (False, "needs a category or a date to stand on")
    if kind in ("bar_horizontal", "pie") and len(measures) > 1:
        return False, f"one series only, so {said(measures[1:])} would be left out"
    if kind == "bar_horizontal":
        return (True, "") if dims else (False, "needs a category")
    if kind == "line":
        return (True, "") if dates else (False, "no time column in this result")
    if kind == "pie":
        if not dims:
            return False, "needs a category to divide by"
        if any((_num(r[columns.index(measures[0])]) or 0) < 0 for r in rows):
            return False, "cannot show a negative share"
        return True, ""
    if kind == "counter":
        return (True, "") if (len(rows) == 1 and len(measures) == 1) else (False, "needs a single value")
    return True, ""


def choose(results: list[dict], rule: str) -> tuple[list[int], str]:
    """Which results the rule picks (indexes into ``results``, the main first), and a note when the
    rule found nothing of its kind and fell back to the main result."""
    if not results:
        return [], ""
    if rule == "every":
        return list(range(min(len(results), MAX_PICTURES))), ""
    if rule == "over_time":
        for i, r in enumerate(results):
            if shape(r["columns"], r["rows"])[0]:
                return [i], ""
        return [0], "no result this run had a time column, so the main result is drawn"
    return [0], ""


def merged_names(result: dict, settings: dict, *, sqls: list[str], connection_id: str) -> dict:
    """The names one result is drawn with: the person's (from the step), over the result's own,
    over what its SQL reads as for a result from before names were recorded."""
    own = dict(((result.get("chart_config") or {}).get("names")) or {})
    if not own:
        from aughor.answer.series_names import connection_metrics, cryptic, names_for
        if any(cryptic(c) for c in result["columns"]) and sqls:
            own = names_for(result["columns"], sqls, metrics=connection_metrics(connection_id))
    labels = dict(own.get("labels") or {})
    person = {str(k): str(v).strip() for k, v in (settings.get("picture_names") or {}).items()
              if isinstance(v, str) and v.strip()}
    axis = person.pop("axis", "") or own.get("y_title") or ""
    labels.update({k: v for k, v in person.items() if k in result["columns"]})
    out: dict = {}
    if labels:
        out["labels"] = labels
    if axis:
        out["y_title"] = axis
    return out


def plan(settings: dict, source: dict, *, automation_name: str, connection_id: str = "") -> list[dict]:
    """The pictures one post carries — each ``{as, kind, asked, title, columns, rows, names, note,
    result}`` — from the step's settings and what the source step published (`engine.chart_grid`)."""
    picture = str(settings.get("picture") or "chart")
    results = list(source.get("results") or []) or (
        [{"claim": "", "columns": source["columns"], "rows": source["rows"],
          "chart_type": source.get("chart_type") or "auto", "chart_config": source.get("chart_config") or {}}]
        if source.get("columns") and source.get("rows") else [])
    if picture == "none" or not results:
        return []
    picked, fell_back = choose(results, str(settings.get("picture_from") or "main"))
    asked = str(settings.get("chart_kind") or "auto")
    titling = str(settings.get("picture_title") or "sentence")
    out: list[dict] = []
    for i in picked:
        r = results[i]
        names = merged_names(r, settings, sqls=list(source.get("sql") or []), connection_id=connection_id)
        if titling == "custom" and str(settings.get("picture_title_text") or "").strip():
            title = str(settings["picture_title_text"]).strip()
        elif titling == "name" or not r.get("claim"):
            title = automation_name
        else:
            title = r["claim"]
        notes = [fell_back] if fell_back else []
        kind = asked
        if picture == "chart":
            ok, why = kind_fit(asked, r["columns"], r["rows"], names)
            if not ok:
                kind = "auto"
                notes.append(f"Asked for {_ASKED.get(asked, asked)}: {why} — drawn as auto")
            if kind == "auto":
                kind = str(r.get("chart_type") or "auto")
            elif kind == "bar" and len(shape(r["columns"], r["rows"])[1]) > 1:
                # The renderer's plain bar draws ONE measure (horizontally, at a few categories),
                # so "Bars" over two series drew one and dropped the other — seen in the step's own
                # preview on the 09:00 run. Several series are the grouped form of bars.
                kind = "grouped_bar"
        out.append({"as": picture, "kind": kind, "asked": asked, "title": title, "columns": r["columns"],
                    "rows": r["rows"], "names": names, "note": "; ".join(notes), "result": i})
    return out


def render(p: dict, *, money_symbol: str = "") -> Optional[bytes]:
    """One planned picture as a PNG, or None when it has no honest picture in it."""
    from aughor.export.echarts import render_chart_svg, svg_to_png
    if p["as"] == "table":
        return svg_to_png(table_svg(p["columns"], p["rows"], p["title"], p["names"]))
    svg = render_chart_svg(p["columns"], p["rows"], p["kind"], p["title"],
                           chart_config={"names": p["names"]} if p["names"] else None,
                           money_symbol=money_symbol)
    return svg_to_png(svg) if svg else None


# ── a table, drawn ──────────────────────────────────────────────────────────────────────────

def _esc(s: Any) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def _cell(v: Any) -> str:
    n = _num(v)
    if n is None:
        return "" if v is None else str(v)
    return f"{int(n):,}" if float(n).is_integer() else f"{n:,.2f}"


def _wrap(text: str, per_line: int) -> list[str]:
    lines, line = [], ""
    for word in str(text or "").split():
        if line and len(line) + 1 + len(word) > per_line:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        lines.append(line)
    return lines[:3]


def table_svg(columns: list[str], rows: list[list], title: str, names: Optional[dict] = None,
              *, width: int = 760) -> str:
    """The result as a picture of a table: its title, the named header, the first `TABLE_ROWS` rows
    with numbers right-aligned, and how many more there were."""
    labels = (names or {}).get("labels") or {}
    head = [labels.get(c) or re.sub(r"_+", " ", c) for c in columns]
    head = [h[:1].upper() + h[1:] for h in head]
    shown = rows[:TABLE_ROWS]
    numeric = [all(_num(r[i]) is not None for r in shown if i < len(r) and r[i] not in (None, ""))
               for i in range(len(columns))]
    title_lines = _wrap(title, max(24, width // 9))
    pad, row_h, top = 12, 26, 14 + 22 * len(title_lines) + 8
    col_w = (width - 2 * pad) / max(1, len(columns))
    more = len(rows) - len(shown)
    height = int(top + row_h * (len(shown) + 1) + (24 if more > 0 else 8) + 8)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'font-family="Helvetica, Arial, sans-serif">',
           f'<rect width="{width}" height="{height}" fill="#ffffff"/>']
    for n, line in enumerate(title_lines):
        out.append(f'<text x="{pad}" y="{30 + 22 * n}" font-size="16" font-weight="600" fill="#1d1c1d">{_esc(line)}</text>')
    def x_of(i: int) -> tuple[float, str]:
        return ((pad + col_w * (i + 1) - 8, "end") if numeric[i] else (pad + col_w * i + 8, "start"))
    y = top
    out.append(f'<rect x="{pad}" y="{y}" width="{width - 2 * pad}" height="{row_h}" fill="#f4f4f4"/>')
    for i, h in enumerate(head):
        x, anchor = x_of(i)
        out.append(f'<text x="{x:.0f}" y="{y + 17}" font-size="12.5" font-weight="600" fill="#454245" '
                   f'text-anchor="{anchor}">{_esc(h)}</text>')
    for r in shown:
        y += row_h
        out.append(f'<line x1="{pad}" x2="{width - pad}" y1="{y}" y2="{y}" stroke="#e8e8e8"/>')
        for i in range(len(columns)):
            x, anchor = x_of(i)
            out.append(f'<text x="{x:.0f}" y="{y + 17}" font-size="12.5" fill="#1d1c1d" '
                       f'text-anchor="{anchor}">{_esc(_cell(r[i] if i < len(r) else None))}</text>')
    if more > 0:
        out.append(f'<text x="{pad + 8}" y="{y + row_h + 16}" font-size="11.5" fill="#616061">'
                   f'and {more:,} more row{"s" if more != 1 else ""}</text>')
    out.append("</svg>")
    return "".join(out)
