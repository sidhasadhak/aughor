"""
The export document model + the report_json → document parsers.

`ExportDoc` is a format-agnostic intermediate: parse a stored report ONCE into an
ordered list of typed `Block`s, then let the PDF and PPTX renderers each walk the
same blocks. Adding a new report kind = one parser; adding a new format = one
renderer. The two never touch each other.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

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
    printed table matches the clean numbers on the chart beside it. Non-floats pass through."""
    if isinstance(v, float) and v == v and v not in (float("inf"), float("-inf")):
        r = round(v, 2) if abs(v) >= 1 else round(v, 6)
        return int(r) if r == int(r) else r
    return v


def _chart_or_table(columns, rows, chart_type, title) -> list[Block]:
    """Render a chart if the data supports it; always include the data table too
    (capped) so the document carries the underlying numbers."""
    out: list[Block] = []
    png = render_chart(columns or [], rows or [], chart_type or "auto", title)
    if png:
        out.append(Block("chart", png=png, caption=title))
    if columns and rows:
        table_rows = [[_round_cell(v) for v in row] for row in rows[:25]]
        out.append(Block("table", columns=columns, rows=table_rows, caption="" if png else title))
    return out


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

    for ph in rep.get("phases") or []:
        if ph.get("status") == "skipped" or not ph.get("findings"):
            continue
        blocks.append(_h(str(ph.get("phase_name") or ph.get("phase_id") or "Phase").strip()))
        if ph.get("summary"):
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
            if kns:
                blocks.append(Block("keynums", keynums=[
                    KeyNumber(k.get("label", ""), k.get("value", ""), k.get("delta"), k.get("context"))
                    for k in kns
                ]))
            blocks.extend(_chart_or_table(f.get("columns"), f.get("rows"), f.get("chart_type"), f.get("title") or ""))

    wf = rep.get("attribution_waterfall") or []
    if wf:
        blocks.append(_h("Attribution"))
        png = render_chart(
            ["cause", "share"],
            [[w.get("cause", ""), w.get("pct_of_total", 0)] for w in wf],
            "bar", "Share of total change",
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
