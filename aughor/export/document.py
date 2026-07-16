"""
The export document model + the report_json → document parsers.

`ExportDoc` is a format-agnostic intermediate: parse a stored report ONCE into an
ordered list of typed `Block`s, then let the PDF and PPTX renderers each walk the
same blocks. Adding a new report kind = one parser; adding a new format = one
renderer. The two never touch each other.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .charts import render_chart


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


def _round_cell(v):
    """Trim floating-point display noise in a table cell (39.97968526236183 -> 39.98) so the
    printed table matches the clean numbers on the chart beside it. Handles float, Decimal, and
    pure-numeric strings — DuckDB returns DECIMAL columns as Decimal/str, which a float-only check
    misses (the '711231.2900000175' the dimensional tables still showed). Non-numeric passes through."""
    import re as _re
    from decimal import Decimal
    if isinstance(v, bool):
        return v
    if isinstance(v, Decimal):
        v = float(v)
    if isinstance(v, float) and v == v and v not in (float("inf"), float("-inf")):
        r = round(v, 2) if abs(v) >= 1 else round(v, 6)
        return int(r) if r == int(r) else r
    if isinstance(v, str) and _re.fullmatch(r'-?\d+\.\d{4,}', v.strip()):
        f = float(v.strip())
        r = round(f, 2) if abs(f) >= 1 else round(f, 6)
        return int(r) if r == int(r) else r
    return v


def _chart_or_table(columns, rows, chart_type, title, units=None, exhibit=None) -> list[Block]:
    """Render a chart if the data supports it; always include the data table too
    (capped) so the document carries the underlying numbers."""
    out: list[Block] = []
    png = render_chart(columns or [], rows or [], chart_type or "auto", title,
                       units=units, exhibit=exhibit)
    if png:
        out.append(Block("chart", png=png, caption=title))
    if columns and rows:
        table_rows = [[_round_cell(v) for v in row] for row in rows[:25]]
        out.append(Block("table", columns=columns, rows=table_rows, caption="" if png else title))
    return out


def _exhibit_argument(columns, rows, chart_type, title, units=None, exhibit=None) -> list[Block]:
    """R16 P1 — ONE exhibit per claim, and only when it informs.

    A degenerate result (fewer than two rows: the 1-bar chart, the single-point
    "trend") renders NOTHING — the finding's sentence carries it. Otherwise the
    chart wins; a compact table (≤8 rows) is the fallback when no chart renders.
    Never both — the full grid lives behind the drill/receipt, not in the body."""
    rows = rows or []
    if not columns or len(rows) < 2:
        return []
    if (chart_type or "auto") != "none":
        png = render_chart(columns, rows, chart_type or "auto", title, units=units, exhibit=exhibit)
        if png:
            return [Block("chart", png=png, caption=title)]
    table_rows = [[_round_cell(v) for v in row] for row in rows[:8]]
    return [Block("table", columns=columns, rows=table_rows, caption=title)]


# ── Parsers ───────────────────────────────────────────────────────────────────

def _build_chat(inv: dict) -> ExportDoc:
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
    blocks.extend(_chart_or_table(rep.get("columns"), rep.get("rows"), rep.get("chart_type"), headline))

    if rep.get("sql"):
        blocks.append(_h("Query"))
        blocks.append(_code(rep["sql"], "The SQL behind this answer"))

    return ExportDoc(title=headline, subtitle=inv.get("question") or "", meta=meta, kind="chat", blocks=blocks)


def _build_explore(inv: dict) -> ExportDoc:
    """The explore-wave 'landscape' report (R9/R13: narrative → one section per
    sub-question with its own evidence → conclusion → actions).

    This shape had NO builder — it fell through to `_build_chat`, which reads only
    inv-level columns/rows (absent on a wave), so the export dropped every chart and
    shipped a 2-page text note. Found by the W5 chart-grammar A/B: the outlier-entities
    starter routes here, and its Databricks reference report is exactly this shape."""
    rep = inv.get("report") or {}
    headline = rep.get("headline") or inv.get("question") or "Exploration"
    answers = rep.get("subq_answers") or []
    meta = [m for m in (
        inv.get("connection_id") or "",
        _date(inv.get("completed_at") or inv.get("started_at")),
        f"{len(answers)} questions explored" if answers else "",
    ) if m]
    from aughor.kernel.flags import flag_enabled
    _argument = flag_enabled("report.argument_style")
    _exhibits = _exhibit_argument if _argument else _chart_or_table

    blocks: list[Block] = []
    if rep.get("narrative"):
        blocks.append(_h("What the exploration found"))
        blocks.append(_p(rep["narrative"]))
    for a in answers:
        if a.get("error"):
            continue
        title = (a.get("question") or "").strip() or "Exploration step"
        blocks.append(_h(title))
        prose = (a.get("insight") or a.get("answer") or "").strip()
        if prose:
            blocks.append(_p(prose))
        blocks.extend(_exhibits(a.get("columns"), a.get("rows"), a.get("chart_type") or "auto",
                                title, units=a.get("column_units"), exhibit=a.get("exhibit")))
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


def _build_ada(inv: dict) -> ExportDoc:
    """The structured 'Deep Analysis' report (ADA: metric → phases → findings →
    attribution → recommendations). Charts live right on each finding."""
    rep = inv.get("report") or {}
    headline = rep.get("headline") or inv.get("question") or "Deep Analysis"
    conf = (rep.get("confidence") or "").upper()
    meta = [m for m in (
        inv.get("connection_id") or "",
        _date(inv.get("completed_at") or inv.get("started_at")),
        f"confidence: {conf}" if conf else "",
    ) if m]

    blocks: list[Block] = []
    if rep.get("executive_summary"):
        blocks.append(_h("Executive summary"))
        blocks.append(_p(rep["executive_summary"]))

    # The metric-at-a-glance line (what changed, over what period, by how much).
    glance = [x for x in (
        rep.get("metric"), rep.get("observation_period"),
        rep.get("total_change_label"), rep.get("comparison_basis"),
    ) if x]
    if glance:
        blocks.append(Block("prose", text="   ·   ".join(str(g) for g in glance), tag="At a glance"))

    # R16 P1 (flag `report.argument_style`) — compose the body the way an analyst
    # argues: intake machinery out (it stays in the Trust Receipt), key numbers
    # bold inline in prose instead of tile rows, one informative exhibit per
    # claim, and the R15 opportunity number promoted to a Financial impact
    # section. Flag off → the legacy composition, byte-identical.
    from aughor.kernel.flags import flag_enabled
    _argument = flag_enabled("report.argument_style")
    _nm = lambda s: (s or "").replace("*", "")  # noqa: E731 — strip model markdown
    opportunities: list[dict] = []

    for ph in rep.get("phases") or []:
        if ph.get("status") == "skipped" or not ph.get("findings"):
            continue
        if _argument and (ph.get("phase_id") or "") == "intake":
            continue
        blocks.append(_h(str(ph.get("phase_name") or ph.get("phase_id") or "Phase").strip()))
        # The deterministic synthesis fallback STITCHES phase summaries into the executive
        # summary — re-printing one here reads the same paragraph twice. Skip what the head
        # already carries (whitespace/emphasis-insensitive containment).
        _n = lambda s: re.sub(r"\s+", " ", re.sub(r"\*+", "", s or "")).strip()
        if ph.get("summary") and _n(ph["summary"]) not in _n(rep.get("executive_summary") or ""):
            blocks.append(_p(ph["summary"]))
        for f in ph["findings"]:
            if f.get("error"):
                continue
            blocks.append(Block(
                "finding",
                caption=f.get("title") or "",
                text=f.get("interpretation") or "",
                tag=(f.get("stat_note") or "") if f.get("is_significant") else "",
            ))
            kns = f.get("key_numbers") or []
            if kns and _argument:
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
            elif kns:
                # Strip any **markdown** the model wrapped a figure in — the export renders these as
                # plain text, so "**57.8%**" would otherwise print literal asterisks.
                blocks.append(Block("keynums", keynums=[
                    KeyNumber(_nm(k.get("label", "")), _nm(k.get("value", "")), _nm(k.get("delta")) or None, _nm(k.get("context")) or None)
                    for k in kns
                ]))
            # The finding's own display contract travels with it: `column_units` so a rate
            # prints "74.5%" in the PDF exactly as on screen, and the chart-grammar `exhibit`
            # (severity ramp · reference lines · point labels). Both absent → unchanged output.
            _u, _x = f.get("column_units"), f.get("exhibit")
            if _argument:
                blocks.extend(_exhibit_argument(f.get("columns"), f.get("rows"), f.get("chart_type"),
                                                f.get("title") or "", units=_u, exhibit=_x))
            else:
                blocks.extend(_chart_or_table(f.get("columns"), f.get("rows"), f.get("chart_type"),
                                              f.get("title") or "", units=_u, exhibit=_x))

    # R16 P1 — the decision paragraph: gap-to-benchmark × volume, in prose,
    # right where a reader decides (before Recommendations).
    if _argument and opportunities:
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
        png = render_chart(
            ["cause", "share"],
            [[w.get("cause", ""), w.get("pct_of_total", 0)] for w in wf],
            "bar", "Share of total change",
            units={"share": "percent"}, exhibit={"color": {"mode": "sign"}},
        )
        if png:
            blocks.append(Block("chart", png=png, caption="Share of the total change, by cause"))
        blocks.append(_bul([
            f"{w.get('cause', '')}: {w.get('amount_label', '')} "
            f"({w.get('pct_of_total', 0):+.0f}% of total"
            + (", controllable" if w.get("controllable") else "")
            + (", structural" if w.get("structural") else "") + ")"
            for w in wf
        ]))

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
    headline = rep.get("headline") or inv.get("question") or "Deep Analysis"
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
            png = render_chart(cols, rows, q.get("chart_type"), q.get("purpose") or q.get("question") or "")
            if png:
                blocks.append(Block("chart", png=png, caption=q.get("purpose") or q.get("question") or ""))
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


def build_export_doc(inv: dict, *, narrate: bool = False) -> ExportDoc:
    """Dispatch on the report's actual shape → an ExportDoc.

    The stored `kind` is a coarse hint; the report dict's own `_report_type` /
    field set is authoritative (a 'investigation' row often holds an ADA report)."""
    rep = inv.get("report") or {}
    if rep.get("_report_type") == "investigate" or "phases" in rep:
        builder = _build_ada
    elif rep.get("_report_type") == "explore" or "subq_answers" in rep:
        builder = _build_explore
    elif "verdict" in rep or "key_findings" in rep:
        builder = _build_analysis
    elif (inv.get("kind") or "chat") == "chat":
        builder = _build_chat
    else:
        builder = _build_chat
    doc = builder(inv)
    if narrate:
        summary = _llm_executive_summary(inv, doc)
        if summary:
            ai_block = Block("prose", text=summary, tag="AI executive summary")
            # Avoid TWO "Executive summary" sections: if the builder already led with one
            # (from the report's executive_summary), REPLACE its prose with the AI-authored
            # version rather than inserting a duplicate heading + paragraph above it.
            if (len(doc.blocks) >= 2 and doc.blocks[0].kind == "heading"
                    and "executive summary" in (doc.blocks[0].text or "").lower()
                    and doc.blocks[1].kind == "prose"):
                doc.blocks[1] = ai_block
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
