"""
The export document model + the report_json → document parsers.

`ExportDoc` is a format-agnostic intermediate: parse a stored report ONCE into an
ordered list of typed `Block`s, then let the PDF and PPTX renderers each walk the
same blocks. Adding a new report kind = one parser; adding a new format = one
renderer. The two never touch each other.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .echarts import render_chart_svg, svg_to_png


# ── Blocks ────────────────────────────────────────────────────────────────────

@dataclass
class KeyNumber:
    label: str
    value: str
    delta: Optional[str] = None
    context: Optional[str] = None


@dataclass
class Block:
    kind: str  # heading | prose | bullets | keynums | chart | table | finding | recs | code
    text: str = ""
    items: list[str] = field(default_factory=list)
    keynums: list[KeyNumber] = field(default_factory=list)
    png: Optional[bytes] = None
    svg: Optional[bytes] = None   # CA-4 one-renderer: the SSR vector; PDF embeds it, PPTX rasterizes
    caption: str = ""
    columns: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    recs: list[dict] = field(default_factory=list)
    confidence: Optional[float] = None
    tag: str = ""


@dataclass
class ExportDoc:
    title: str
    subtitle: str = ""
    meta: list[str] = field(default_factory=list)
    kind: str = ""
    blocks: list[Block] = field(default_factory=list)
    #: Idea 11 — the receipt every figure in this document links back to (the answer's Trust
    #: Receipt id), and the page that shows how its numbers were produced; "" when unknown.
    source_id: str = ""
    source_url: str = ""

    def source_text(self) -> str:
        """The line under each figure: where to see how it was produced. The URL when the
        install knows its web address, the receipt's id when it does not."""
        if not self.source_id:
            return ""
        return f"Source: {self.source_url}" if self.source_url else f"Source: Aughor receipt {self.source_id}"


def receipt_link(receipt_id: str) -> str:
    """Idea 11 — the page that shows how an answer's numbers were produced, ``<web>/receipt/<id>``,
    or "" when the API does not know its public web origin. Opt-in via ``AUGHOR_WEB_URL``, the
    monitors' and departures' rule: empty beats guessed — a document linking to ``localhost`` is
    worse than one that carries the receipt's id alone."""
    base = os.environ.get("AUGHOR_WEB_URL", "").strip().rstrip("/")
    rid = (receipt_id or "").strip()
    if not (base and rid):
        return ""
    from urllib.parse import quote
    return f"{base}/receipt/{quote(rid, safe='')}"


def _receipt_of(inv: dict) -> str:
    """The answer's receipt id: CP-4's envelope carries it on every turn that has one, chat
    and deep alike (`provenance.receipt_id`)."""
    env = (inv.get("report") or {}).get("envelope")
    prov = env.get("provenance") if isinstance(env, dict) else None
    return str((prov or {}).get("receipt_id") or "") if isinstance(prov, dict) else ""


# ── Block constructors (keep the parsers terse) ───────────────────────────────

def _h(text: str) -> Block: return Block("heading", text=text)
def _p(text: str) -> Block: return Block("prose", text=text)
def _bul(items: list[str]) -> Block: return Block("bullets", items=[i for i in items if i])
def _code(text: str, caption: str = "") -> Block: return Block("code", text=text, caption=caption)


def _date(iso: Optional[str]) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%b %-d, %Y")
    except Exception:
        return str(iso)[:10]


def _table_block(columns, rows, *, caption: str, money_symbol: str) -> Block:
    """CP-5 — a data table for the page, cells by the one reader formatter (`answer.exhibit`):
    `54,496.64`, `12.3%`, `$1,820,497.55`, a year left a year — the figures the web table
    shows for the same grid. The row cap stays the caller's: it is this door's encoding."""
    from aughor.answer.exhibit import clean_label, format_rows
    return Block("table", columns=[clean_label(str(c)) for c in columns],
                 rows=format_rows(columns, rows, money_symbol=money_symbol), caption=caption)


def _exhibit_key(columns, rows) -> str:
    """A stable key for a grid, for spotting an exhibit the document already drew.

    Deliberately NOT named `*fingerprint*`: this repo ratchets that word to freshness
    checks registered in `kernel.freshness.FINGERPRINTS`, and this is not one. Nothing is
    cached and nothing expires — the key lives for the length of a single export and
    answers "has this already been drawn on this page", not "is this stale".

    Columns are included because the same numbers under different headers are a different
    exhibit; row ORDER is included because a re-sorted ranking reads differently even when
    the set matches. Empty in, empty out — a finding with no grid is never "a repeat".
    """
    import hashlib
    cols, rws = list(columns or []), list(rows or [])
    if not cols or not rws:
        return ""
    payload = repr([[str(c) for c in cols], [[str(v) for v in r] for r in rws]])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _chart_block(columns, rows, chart_type, title, *, units=None,
                 exhibit=None, money_symbol: str = "",
                 drawn_title: Optional[str] = None) -> Optional[Block]:
    """CA-4 one-renderer: the chart comes from the web's own resolver (ECharts
    SSR → SVG). The PDF embeds the vector; the PNG rides along for PPTX when a
    raster backend exists. None when no honest chart exists (→ table).

    ``drawn_title`` is the title drawn INSIDE the figure when it differs from the
    block's caption — "" when the page already printed it above."""
    svg = render_chart_svg(columns or [], rows or [], chart_type or "auto",
                           title if drawn_title is None else drawn_title,
                           units=units, exhibit=exhibit, money_symbol=money_symbol)
    if not svg:
        return None
    return Block("chart", svg=svg.encode("utf-8"), png=svg_to_png(svg), caption=title)


def _chart_or_table(columns, rows, chart_type, title, units=None, exhibit=None,
                    money_symbol: str = "") -> list[Block]:
    """Render a chart if the data supports it; always include the data table too
    (capped) so the document carries the underlying numbers."""
    out: list[Block] = []
    chart = _chart_block(columns, rows, chart_type, title, units=units,
                         exhibit=exhibit, money_symbol=money_symbol)
    if chart:
        out.append(chart)
    if columns and rows:
        out.append(_table_block(columns, rows[:25], caption="" if chart else title,
                                money_symbol=money_symbol))
    return out


def _exhibit_argument(columns, rows, chart_type, title, units=None, exhibit=None,
                      money_symbol: str = "", drawn_title: Optional[str] = None) -> list[Block]:
    """R16 P1 — ONE exhibit per claim, and only when it informs.

    A degenerate result (fewer than two rows: the 1-bar chart, the single-point
    "trend") renders NOTHING — the finding's sentence carries it. Otherwise the
    chart wins; a compact table (≤8 rows) is the fallback when no chart renders.
    Never both — the full grid lives behind the drill/receipt, not in the body."""
    rows = rows or []
    if not columns or len(rows) < 2:
        return []
    if (chart_type or "auto") != "none":
        chart = _chart_block(columns, rows, chart_type, title, units=units,
                             exhibit=exhibit, money_symbol=money_symbol, drawn_title=drawn_title)
        if chart:
            return [chart]
    return [_table_block(columns, rows[:8], caption=title, money_symbol=money_symbol)]


_MD_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_MD_BULLET_RE = re.compile(r"^\s*[-*+•]\s+(.*)$")
_MD_NUMBERED_RE = re.compile(r"^\s*\d{1,2}[.)]\s+\S")
_MD_ITALIC_RE = re.compile(r"(?<![*\w])\*(?!\*)([^*\n]+?)(?<!\*)\*(?![*\w])")


def _plain(text: str) -> str:
    """Single-asterisk emphasis as plain text: an answer is bold or normal, never italic —
    the rule the app's prose follows."""
    return _MD_ITALIC_RE.sub(r"\1", text)


def _summary_blocks(text: str) -> list[Block]:
    """An executive summary as the blocks it is written in.

    The Agent's describe answers are written in markdown — a heading, a table, a bulleted
    list — and the PDF printed them as one paragraph of raw markup: "### 90-Day Repeat Rate
    by Cohort Month (2025) | Cohort Month | First-Time Customers | … | :--- |" (theLook,
    2026-10-01), where the app renders the same text as a heading and a table. A heading is
    a bold line under "Executive summary", a table a table, a list a list. A summary with
    none of those is the one prose block it always was.
    """
    from aughor.answer.envelope import table_at
    lines = (text or "").split("\n")
    if not any(_MD_HEADING_RE.match(ln) or _MD_BULLET_RE.match(ln) or table_at(lines, i)
               for i, ln in enumerate(lines)):
        return [_p(text)]
    blocks: list[Block] = []
    para: list[str] = []
    items: list[str] = []

    def _end_para() -> None:
        if para:
            blocks.append(_p(_plain(" ".join(para))))
            para.clear()

    def _end_items() -> None:
        if items:
            blocks.append(_bul([_plain(it) for it in items]))
            items.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        found = table_at(lines, i)
        if found:
            _end_para()
            _end_items()
            columns, rows, i = found
            blocks.append(Block("table", columns=[_plain(c).replace("**", "") for c in columns],
                                rows=[[_plain(str(v)).replace("**", "") for v in r] for r in rows]))
            continue
        heading, bullet = _MD_HEADING_RE.match(line), _MD_BULLET_RE.match(line)
        if heading:
            _end_para()
            _end_items()
            blocks.append(_p(f"**{heading.group(1).replace('**', '').strip()}**"))
        elif bullet:
            _end_para()
            items.append(bullet.group(1).strip())
        elif _MD_NUMBERED_RE.match(line):
            # A numbered line keeps its number: the order is usually the ranking.
            _end_para()
            _end_items()
            blocks.append(_p(_plain(line.strip())))
        elif not line.strip():
            _end_para()
            _end_items()
        else:
            _end_items()
            para.append(line.strip())
        i += 1
    _end_para()
    _end_items()
    return blocks


def _same_words(text) -> str:
    return " ".join(str(text or "").replace("*", "").split()).casefold()


# ── Parsers ───────────────────────────────────────────────────────────────────

def _build_chat(inv: dict, money_symbol: str = "") -> ExportDoc:
    """A single Q&A 'Insight' response → an executive one-pager."""
    rep = inv.get("report") or {}
    insight = rep.get("insight") or {}
    headline = rep.get("headline") or inv.get("question") or "Insight"
    meta = [m for m in (
        inv.get("connection_id") or "",
        _date(inv.get("completed_at") or inv.get("started_at")),
        f"trend: {insight['trend']}" if insight.get("trend") else "",
        f"confidence: {insight['confidence']}" if insight.get("confidence") else "",
    ) if m]

    blocks: list[Block] = []
    blocks.append(_h("Summary"))
    blocks.append(_p(insight.get("narrative") or headline))
    if insight.get("anomalies"):
        blocks.append(_h("What stands out"))
        blocks.append(_bul(list(insight["anomalies"])))
    if rep.get("approach"):
        blocks.append(_h("How this was calculated"))
        blocks.append(_bul(list(rep["approach"])))

    blocks.append(_h("Evidence"))
    blocks.extend(_chart_or_table(rep.get("columns"), rep.get("rows"), rep.get("chart_type"), headline,
                                  money_symbol=money_symbol))

    if rep.get("sql"):
        blocks.append(_h("Query"))
        blocks.append(_code(rep["sql"], "The SQL behind this answer"))

    return ExportDoc(title=headline, subtitle=inv.get("question") or "", meta=meta, kind="chat", blocks=blocks)


def _receipt_line(receipt: dict) -> str:
    """One guard receipt as a line: what ran, what it did, what it found."""
    parts = [str(receipt.get(k)) for k in ("guard", "action", "detail") if receipt.get(k)]
    if parts:
        return " — ".join(parts)
    return ", ".join(f"{k}: {v}" for k, v in receipt.items() if k not in ("before", "after"))[:200]


def _build_envelope(inv: dict, money_symbol: str = "") -> ExportDoc:
    """CP-4 — an answer that carries its envelope: the document takes ALL of it.

    The Slack door takes the headline, the body, the grid once and two caveats; this door
    takes every field — the exhibit, every caveat, the follow-ups, and the provenance
    (query and checks) the thread drops. Same envelope, different selection: nothing here
    re-derives a sentence, and nothing here needs a model.
    """
    rep = inv.get("report") or {}
    env = rep.get("envelope") or {}
    prov = env.get("provenance") or {}
    headline = env.get("headline") or rep.get("headline") or inv.get("question") or "Answer"
    meta = [m for m in (
        inv.get("connection_id") or "",
        _date(inv.get("completed_at") or inv.get("started_at")),
        f"confidence: {prov['confidence']}" if prov.get("confidence") else "",
    ) if m]

    # The body is what follows the headline, never the headline again — so the summary
    # opens with the sentence and continues with the rest.
    body = str(env.get("body") or "").strip()
    blocks: list[Block] = [_h("Summary"), _p(f"{headline}\n\n{body}" if body else headline)]
    grid = env.get("grid") if isinstance(env.get("grid"), dict) else {}
    chart = env.get("chart") if isinstance(env.get("chart"), dict) else {}
    if grid.get("columns") and grid.get("rows"):
        blocks.append(_h("Evidence"))
        blocks.extend(_chart_or_table(grid["columns"], grid["rows"],
                                      chart.get("chart_type") or "auto", headline,
                                      money_symbol=money_symbol))
    if env.get("caveats"):
        blocks.append(_h("Caveats"))
        blocks.append(_bul([str(c) for c in env["caveats"]]))
    if env.get("follow_ups"):
        blocks.append(_h("Questions to ask next"))
        blocks.append(_bul([str(q) for q in env["follow_ups"]]))
    if prov.get("sql"):
        blocks.append(_h("Query"))
        for sql in prov["sql"]:
            blocks.append(_code(str(sql), "The SQL behind this answer"))
    if prov.get("guard_receipts"):
        blocks.append(_h("Checks"))
        blocks.append(_bul([_receipt_line(r) for r in prov["guard_receipts"] if isinstance(r, dict)]))
    return ExportDoc(title=headline, subtitle=env.get("question") or inv.get("question") or "",
                     meta=meta, kind="chat", blocks=blocks)


def _strip_planner_notes(text: str) -> str:
    """Strip the explore wave's internal planner directives from reader-facing prose:
    paragraphs/lines beginning with "→" are forward-chaining notes to the NEXT question
    ("→ Q5 should investigate…") — process, not analysis. Mirrors web/lib/format.ts."""
    kept = []
    for p in re.split(r"\n{2,}", text or ""):
        if p.strip().startswith("→"):
            continue        # a directive paragraph goes whole, wrapped lines included
        lines = [ln for ln in p.split("\n") if not ln.strip().startswith("→")]
        if "\n".join(lines).strip():
            kept.append("\n".join(lines))
    return "\n\n".join(kept).strip()


def _build_explore(inv: dict, money_symbol: str = "") -> ExportDoc:
    """The explore-wave 'landscape' report (R9/R13: narrative → one section per
    sub-question with its own evidence → conclusion → actions).

    This shape had NO builder — it fell through to `_build_chat`, which reads only
    inv-level columns/rows (absent on a wave), so the export dropped every chart and
    shipped a 2-page text note. Found by the W5 chart-grammar A/B: the outlier-entities
    starter routes here, and its reference report is exactly this shape."""
    rep = inv.get("report") or {}
    headline = rep.get("headline") or inv.get("question") or "Exploration"
    answers = rep.get("subq_answers") or []
    # Count what was actually explored, and agree with the body: the section loop below
    # skips errored steps, so counting them here reported "5 questions explored" for a
    # run that showed one. (And "1 questions explored" was the grammar of a report the
    # reader was already losing trust in.)
    _explored = [a for a in answers if not a.get("error")]
    meta = [m for m in (
        inv.get("connection_id") or "",
        _date(inv.get("completed_at") or inv.get("started_at")),
        f"{len(_explored)} question{'' if len(_explored) == 1 else 's'} explored" if _explored else "",
    ) if m]
    _exhibits = _exhibit_argument
    _money_sym = money_symbol

    blocks: list[Block] = []
    if rep.get("narrative"):
        blocks.append(_h("What the exploration found"))
        blocks.append(_p(_strip_planner_notes(rep["narrative"])))
    # An exhibit is drawn ONCE. Two phases reaching the same grid is itself a finding —
    # "the join adds no new signal" — and that finding belongs in the PROSE, which is kept
    # in full. Drawing the identical chart a second time does not report the agreement, it
    # just costs a page: a real report (2026-09-23) carried the category chart twice and
    # the department chart three times, all byte-identical, on a five-page document.
    _drawn: dict[str, str] = {}
    for a in answers:
        if a.get("error"):
            continue
        title = (a.get("question") or "").strip() or "Exploration step"
        blocks.append(_h(title))
        prose = _strip_planner_notes((a.get("insight") or a.get("answer") or "").strip())
        if prose:
            blocks.append(_p(prose))
        fp = _exhibit_key(a.get("columns"), a.get("rows"))
        if fp and fp in _drawn:
            # Named, never silently dropped: a reader who scrolls looking for the picture
            # is told where it is, and the repetition is stated as the result it is.
            blocks.append(_p(f"Same figures as \u201c{_drawn[fp]}\u201d above \u2014 "
                             f"shown once."))
            continue
        if fp:
            _drawn[fp] = title
        blocks.extend(_exhibits(a.get("columns"), a.get("rows"), a.get("chart_type") or "auto",
                                title, units=a.get("column_units"), exhibit=a.get("exhibit"),
                                money_symbol=_money_sym))
    if rep.get("conclusion"):
        blocks.append(_h("Conclusion"))
        blocks.append(_p(rep["conclusion"]))
    if rep.get("recommended_actions"):
        blocks.append(_h("Recommended actions"))
        blocks.append(Block("recs", recs=[{"action": a} for a in rep["recommended_actions"]]))
    dq = rep.get("data_quality_notes") or []
    if dq:
        blocks.append(_h("Data quality notes"))
        blocks.append(_bul([str(n) if not isinstance(n, dict)
                            else f"{n.get('table') or ''}: {n.get('issue') or ''}" for n in dq]))
    return ExportDoc(title=headline, subtitle=inv.get("question") or "", meta=meta,
                     kind="explore", blocks=blocks)


def _build_ada(inv: dict, money_symbol: str = "") -> ExportDoc:
    """The structured deep-analysis report (metric → phases → findings →
    attribution → recommendations). Charts live right on each finding."""
    rep = inv.get("report") or {}
    headline = rep.get("headline") or inv.get("question") or "Deep analysis"
    conf = (rep.get("confidence") or "").upper()
    meta = [m for m in (
        inv.get("connection_id") or "",
        _date(inv.get("completed_at") or inv.get("started_at")),
        f"confidence: {conf}" if conf else "",
    ) if m]

    blocks: list[Block] = []
    # Degraded-report notice FIRST: the specimen PDF's only admission that synthesis
    # failed sat inside confidence_justification on the last page.
    if rep.get("degraded"):
        # No claim here about whether the QUERIES ran: this banner is a fixed string, and
        # the fixed string it used to carry ("The queries ran") is false for a report whose
        # phases all failed at planning. Whether any SQL executed is authored once, by the
        # report itself, and rendered below as `confidence_justification` — one place that
        # can actually count, instead of two surfaces asserting it from memory.
        blocks.append(Block(
            "prose", tag="Note",
            text=("⚠ Narrative synthesis was unavailable — this report is assembled "
                  "directly from the phase findings; the framing is provisional."),
        ))
    if rep.get("executive_summary"):
        blocks.append(_h("Executive summary"))
        blocks.extend(_summary_blocks(rep["executive_summary"]))

    # The metric-at-a-glance line (what changed, over what period, by how much).
    glance = [x for x in (
        rep.get("metric"), rep.get("observation_period"),
        rep.get("total_change_label"), rep.get("comparison_basis"),
    ) if x]
    if glance:
        blocks.append(Block("prose", text="   ·   ".join(str(g) for g in glance), tag="At a glance"))

    # R16 P1 — the body is composed the way an analyst argues: intake machinery out
    # (it stays in the Trust Receipt), key numbers bold inline in prose instead of
    # tile rows, one informative exhibit per claim, and the R15 opportunity number
    # promoted to a Financial impact section.
    _money_sym = money_symbol
    _nm = lambda s: (s or "").replace("*", "")  # noqa: E731 — strip model markdown
    opportunities: list[dict] = []

    for ph in rep.get("phases") or []:
        if ph.get("status") == "skipped" or not ph.get("findings"):
            continue
        if (ph.get("phase_id") or "") == "intake":
            continue
        # A result a corrected re-run replaced is kept in the run, not on the page: the app
        # hides it, and the PDF printed it under the right one — the fulfilment answer's
        # flagged first query, ship times pulled to ~12 hours, beside the 35 it was replaced by.
        if ph.get("_hidden"):
            continue
        _heading = str(ph.get("phase_name") or ph.get("phase_id") or "Phase").strip()
        blocks.append(_h(_heading))
        # A title is printed ONCE. An Agent query's phase, finding and chart all carry the
        # same name, and the PDF printed it three times over every chart — as the section
        # heading, as the finding's caption and inside the figure (theLook, 2026-10-01).
        _printed = {_same_words(_heading)}
        # The deterministic synthesis fallback STITCHES phase summaries into the executive
        # summary — re-printing one here reads the same paragraph twice. Skip what the head
        # already carries (whitespace/emphasis-insensitive containment).
        _n = lambda s: re.sub(r"\s+", " ", re.sub(r"\*+", "", s or "")).strip()
        if ph.get("summary") and _n(ph["summary"]) not in _n(rep.get("executive_summary") or ""):
            blocks.append(_p(ph["summary"]))
        for _cav in ph.get("caveats") or []:
            blocks.append(Block("prose", tag="Caveat", text=f"⚠ {_cav}"))
        for f in ph["findings"]:
            if f.get("error"):
                continue
            _caption = f.get("claim") or f.get("title") or ""
            if _same_words(_caption) in _printed:
                _caption = ""
            _printed.add(_same_words(_caption))
            blocks.append(Block(
                "finding",
                # CA-4 title = claim: the finding leads with the claim it proves;
                # the query's descriptive name stays as the chart caption below.
                caption=_caption,
                text=f.get("interpretation") or "",
                # Gated on the PRESENCE of a stat note, not on `is_significant` — the rule
                # `web/components/brief/StatBadge.tsx` already states for the same field on
                # the same findings. The two are orthogonal: `is_significant` is about
                # whether a CHANGE cleared a threshold, while a stat note also carries
                # whether the data behind it is COMPLETE. Gating on significance suppressed
                # every "PARTIAL FINAL PERIOD" warning on a finding whose change happened
                # not to be significant — which is precisely when a reader is most likely to
                # read a partial month's smaller total as a decline.
                tag=(f.get("stat_note") or ""),
            ))
            kns = f.get("key_numbers") or []
            if kns:
                # Numbers live in the sentence, not in tiles. The R15 opportunity
                # key number is held back for its own Financial impact section.
                opportunities += [k for k in kns
                                  if _nm(k.get("label", "")).startswith("Opportunity:")]
                inline = [k for k in kns
                          if not _nm(k.get("label", "")).startswith("Opportunity:")]
                if inline:
                    blocks.append(_p("   ·   ".join(
                        f"**{_nm(k.get('label', ''))}: {_nm(k.get('value', ''))}**"
                        + (f" ({_nm(k.get('delta'))})" if k.get("delta") else "")
                        for k in inline)))
            # A suppressed finding's rows ARE the corrupt artifact (a fanned/conditioned
            # ratio) — its interpretation sentence already says so; rendering the rows as a
            # clean table prints exactly the numbers we suppressed ("intercontinental 55.73"
            # beside a "2.8%" headline). The sentence carries it; no chart, no table. The
            # flag is set on new reports; the signature also catches reports stored before it.
            _interp_lc = (f.get("interpretation") or "").lower()
            if f.get("_suppressed") or (
                (f.get("chart_type") == "none")
                and not (f.get("key_numbers"))
                and ("could not be computed reliably" in _interp_lc
                     or "computation artifact" in _interp_lc
                     or "fan-out artifact" in _interp_lc
                     # the dedup collapses a repeated suppression interpretation to this
                     # back-reference, which loses the signature above — catch it too.
                     or "see the note above" in _interp_lc)):
                continue
            # The finding's own display contract travels with it: `column_units` so a rate
            # prints "74.5%" in the PDF exactly as on screen, and the chart-grammar `exhibit`
            # (severity ramp · reference lines · point labels). Both absent → unchanged output.
            _u, _x = f.get("column_units"), f.get("exhibit")
            _title = f.get("title") or ""
            blocks.extend(_exhibit_argument(f.get("columns"), f.get("rows"), f.get("chart_type"),
                                            _title, units=_u, exhibit=_x,
                                            money_symbol=_money_sym,
                                            drawn_title="" if _same_words(_title) in _printed else None))

    # R16 P1 — the decision paragraph: gap-to-benchmark × volume, in prose,
    # right where a reader decides (before Recommendations).
    if opportunities:
        blocks.append(_h("Financial impact"))
        for k in opportunities:
            line = f"**{_nm(k.get('label', ''))}: {_nm(k.get('value', ''))}**"
            if k.get("delta"):
                line += f" ({_nm(k.get('delta'))})"
            if k.get("context"):
                line += f". {_nm(k.get('context'))}"
            blocks.append(_p(line))

    wf = rep.get("attribution_waterfall") or []
    if wf:
        blocks.append(_h("Attribution"))
        # A waterfall entry's share is SIGNED (what pushed the metric up vs down), and the
        # web already colours it by sign — the PDF used to flatten every cause to one hue,
        # so a reader couldn't tell a driver from an offset without reading the bullets.
        chart = _chart_block(
            ["cause", "share"],
            [[w.get("cause", ""), w.get("pct_of_total", 0)] for w in wf],
            "change", "Share of total change",
            units={"share": "percent"}, exhibit={"color": {"mode": "sign"}},
        )
        if chart:
            chart.caption = "Share of the total change, by cause"
            blocks.append(chart)
        blocks.append(_bul([
            f"{w.get('cause', '')}: {w.get('amount_label', '')} "
            f"({w.get('pct_of_total', 0):+.0f}% of total"
            + (", controllable" if w.get("controllable") else "")
            + (", structural" if w.get("structural") else "") + ")"
            for w in wf
        ]))

    # IP-1 — the Verifier's rule-outs, where the web report puts them: before the actions.
    rule_outs = rep.get("rule_outs") or {}
    if rule_outs.get("items"):
        blocks.append(_h("Rule out first"))
        blocks.append(_p(rule_outs.get("lead") or "Not checked against your data."))
        blocks.append(_bul([i.get("cause", "") + (f" — fix: {i['fix']}" if i.get("fix") else "")
                            for i in rule_outs["items"]]))

    recs = rep.get("recommendations") or []
    if recs:
        blocks.append(_h("Recommendations"))
        blocks.append(Block("recs", recs=[
            {"action": r.get("action", ""), "expected_impact": r.get("expected_impact", ""),
             "owner": r.get("owner", ""), "timeline": r.get("timeline", "")}
            for r in recs
        ]))

    if rep.get("data_gaps"):
        blocks.append(_h("Data gaps"))
        blocks.append(_bul(list(rep["data_gaps"])))

    if rep.get("confidence_justification"):
        blocks.append(_h("Confidence"))
        blocks.append(_p(f"{conf or 'Assessed'} — {rep['confidence_justification']}"))

    return ExportDoc(title=headline, subtitle=inv.get("question") or "", meta=meta, kind="ada", blocks=blocks)


def _build_analysis(inv: dict) -> ExportDoc:
    """The hypothesis-driven AnalysisReport shape (verdict + key_findings + …)."""
    rep = inv.get("report") or {}
    headline = rep.get("headline") or inv.get("question") or "Deep analysis"
    findings = rep.get("key_findings") or []
    meta = [m for m in (
        inv.get("connection_id") or "",
        _date(inv.get("completed_at") or inv.get("started_at")),
        f"{len(findings)} key findings" if findings else "",
    ) if m]

    blocks: list[Block] = []
    if rep.get("verdict"):
        blocks.append(_h("Verdict"))
        blocks.append(_p(rep["verdict"]))
    if findings:
        blocks.append(_h("Key findings"))
        for f in findings:
            blocks.append(Block("finding", caption=f.get("claim") or "",
                                text=f.get("evidence") or "", confidence=f.get("confidence")))
    for q in (inv.get("query_history") or [])[:6]:
        cols, rows = q.get("columns"), q.get("rows")
        if cols and rows and len(rows) >= 2:
            chart = _chart_block(cols, rows, q.get("chart_type"), q.get("purpose") or q.get("question") or "")
            if chart:
                chart.caption = q.get("purpose") or q.get("question") or ""
                blocks.append(chart)
    if rep.get("what_is_not_the_cause"):
        blocks.append(_h("Ruled out"))
        blocks.append(_bul(list(rep["what_is_not_the_cause"])))
    if rep.get("risks"):
        blocks.append(_h("Risks"))
        blocks.append(_bul(list(rep["risks"])))
    if rep.get("recommended_actions"):
        blocks.append(_h("Recommended actions"))
        blocks.append(Block("recs", recs=[{"action": a} for a in rep["recommended_actions"]]))
    dq = rep.get("data_quality_notes") or []
    if dq:
        blocks.append(_h("Data quality notes"))
        blocks.append(_bul([
            f"{(n.get('table') or '')}{('.' + n['column']) if n.get('column') else ''}: {n.get('issue') or ''}"
            + (f" — fix: {n['recommended_fix']}" if n.get('recommended_fix') else "")
            for n in dq
        ]))
    return ExportDoc(title=headline, subtitle=inv.get("question") or "", meta=meta, kind="investigation", blocks=blocks)


def build_export_doc(inv: dict, *, narrate: bool = False, money_symbol: str = "") -> ExportDoc:
    """Dispatch on the report's actual shape → an ExportDoc.

    The stored `kind` is a coarse hint; the report dict's own `_report_type` /
    field set is authoritative (an 'investigation' row often holds a deep-analysis report)."""
    rep = inv.get("report") or {}
    if rep.get("_report_type") == "investigate" or "phases" in rep:
        builder = _build_ada
    elif rep.get("_report_type") == "explore" or "subq_answers" in rep:
        builder = _build_explore
    elif "verdict" in rep or "key_findings" in rep:
        builder = _build_analysis
    elif isinstance(rep.get("envelope"), dict) and (
            rep["envelope"].get("headline") or rep["envelope"].get("body")):
        # CP-4 — a turn that carries its envelope exports EVERY field of it; the deep and
        # explore shapes above keep their richer builders (phases, waterfalls, sub-questions).
        builder = _build_envelope
    elif (inv.get("kind") or "chat") == "chat":
        builder = _build_chat
    else:
        builder = _build_chat
    # `money_symbol` (caller-resolved: the connection's effective currency, matching the
    # web's fallback) reaches every builder that renders a chart or a data table — the platform-side
    # export never resolves it itself (Platform must not import Agent; the caller injects).
    doc = (builder(inv, money_symbol)
           if builder in (_build_ada, _build_explore, _build_envelope, _build_chat) else builder(inv))
    doc.source_id = _receipt_of(inv)
    doc.source_url = receipt_link(doc.source_id)
    if narrate:
        summary = _llm_executive_summary(inv, doc)
        if summary:
            ai_block = Block("prose", text=summary, tag="AI executive summary")
            # Avoid TWO "Executive summary" sections: if the builder already led with one
            # (from the report's executive_summary), REPLACE its prose with the AI-authored
            # version rather than inserting a duplicate heading + paragraph above it.
            if (len(doc.blocks) >= 2 and doc.blocks[0].kind == "heading"
                    and "executive summary" in (doc.blocks[0].text or "").lower()
                    and (doc.blocks[1].kind == "prose" or builder is _build_ada)):
                # A deep report's summary written in markdown is several blocks
                # (`_summary_blocks`); the AI summary replaces all of them, up to the section
                # after it, or the reader gets it followed by the old table and lists.
                end = 2
                if builder is _build_ada:
                    while (end < len(doc.blocks) and doc.blocks[end].kind != "heading"
                           and doc.blocks[end].tag != "At a glance"):
                        end += 1
                doc.blocks[1:end] = [ai_block]
            else:
                doc.blocks.insert(0, ai_block)
                doc.blocks.insert(0, _h("Executive summary"))
    return doc


def _llm_executive_summary(inv: dict, doc: ExportDoc) -> Optional[str]:
    """Best-effort: a polished 2-3 sentence executive paragraph for the document.
    Degrades silently — a slow or failing model never blocks the export."""
    try:
        from aughor.llm.provider import get_provider
        from pydantic import BaseModel, Field

        class _Sum(BaseModel):
            summary: str = Field(description="2-3 sentence executive summary for a printed brief; business language, lead with the number that matters.")

        context = "\n".join(
            b.text for b in doc.blocks if b.kind in ("prose", "finding") and b.text
        )[:2500]
        provider = get_provider("narrator")
        out = provider.complete(
            system="You write the opening executive summary of a formal business analysis document. Be concise, concrete, and lead with the most important finding.",
            user=f"TITLE: {doc.title}\nQUESTION: {doc.subtitle}\n\nFINDINGS:\n{context}\n\nWrite the executive summary.",
            response_model=_Sum,
            temperature=0.3,
        )
        return (out.summary or "").strip() or None
    except Exception:
        return None
