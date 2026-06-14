"""report_json (parsed to an ExportDoc) → a polished PDF, via reportlab Platypus."""
from __future__ import annotations

import io
import re

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    HRFlowable,
    Image,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .document import Block, ExportDoc

_INDIGO = colors.HexColor("#4f46e5")
_INK = colors.HexColor("#18181b")
_BODY = colors.HexColor("#3f3f46")
_MUTED = colors.HexColor("#71717a")
_LINE = colors.HexColor("#e4e4e7")
_BG = colors.HexColor("#f4f4f5")

_CONTENT_W = A4[0] - 36 * mm  # page width minus L+R margins (18mm each)


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["BodyText"]
    mk = lambda **k: ParagraphStyle(parent=base, **k)
    return {
        "title": mk(name="t", fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=_INK, spaceAfter=4),
        "subtitle": mk(name="s", fontName="Helvetica", fontSize=10.5, leading=14, textColor=_MUTED, spaceAfter=2),
        "meta": mk(name="m", fontName="Helvetica", fontSize=8.5, leading=12, textColor=_MUTED),
        "h": mk(name="h", fontName="Helvetica-Bold", fontSize=12.5, leading=15, textColor=_INDIGO, spaceBefore=14, spaceAfter=5),
        "body": mk(name="b", fontName="Helvetica", fontSize=10, leading=15, textColor=_BODY, spaceAfter=4),
        "claim": mk(name="c", fontName="Helvetica-Bold", fontSize=10.5, leading=14, textColor=_INK, spaceBefore=4, spaceAfter=1),
        "kpi": mk(name="kpi", fontName="Helvetica-Bold", fontSize=15, leading=17, textColor=_INDIGO),
        "kpil": mk(name="kpil", fontName="Helvetica", fontSize=7.5, leading=10, textColor=_MUTED),
        "small": mk(name="sm", fontName="Helvetica", fontSize=8, leading=11, textColor=_MUTED),
        "tag": mk(name="tg", fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=_INDIGO, spaceAfter=2),
        "bullet": mk(name="bu", fontName="Helvetica", fontSize=10, leading=14, textColor=_BODY, leftIndent=10, bulletIndent=0, spaceAfter=2),
        "cell": mk(name="cl", fontName="Helvetica", fontSize=8, leading=10, textColor=_BODY),
        "cellh": mk(name="ch", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=_INK),
        "caption": mk(name="cap", fontName="Helvetica-Oblique", fontSize=8, leading=11, textColor=_MUTED, spaceBefore=2, spaceAfter=8),
    }


def _esc(s) -> str:
    return (str(s or "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _rich(s) -> str:
    """Escape, then convert **markdown bold** → reportlab <b> markup (the report
    prose embeds `**…**` around key numbers)."""
    out = _esc(s)
    out = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out)
    return out


def _image(png: bytes, max_w: float = _CONTENT_W):
    ir = ImageReader(io.BytesIO(png))
    iw, ih = ir.getSize()
    w = min(max_w, iw * 0.5)
    h = w * ih / iw
    return Image(io.BytesIO(png), width=w, height=h)


def _table(columns, rows, S):
    cols = columns[:7]
    ncol = len(cols)
    body_rows = rows[:20]
    data = [[Paragraph(_esc(c), S["cellh"]) for c in cols]]
    for r in body_rows:
        cells = []
        for i in range(ncol):
            v = r[i] if i < len(r) else ""
            cells.append(Paragraph(_esc(v)[:60], S["cell"]))
        data.append(cells)
    t = Table(data, colWidths=[_CONTENT_W / ncol] * ncol, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _BG),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, _LINE),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, _LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def _keynums(kns, S):
    kns = kns[:5]
    n = len(kns)
    vals = [Paragraph(_esc(k.value), S["kpi"]) for k in kns]
    labs = [Paragraph(_esc(k.label) + (f" &nbsp;{_esc(k.delta)}" if k.delta else ""), S["kpil"]) for k in kns]
    t = Table([vals, labs], colWidths=[_CONTENT_W / n] * n)
    t.setStyle(TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def _confidence_chip(conf: float) -> str:
    pct = int(round(conf * 100))
    label = "High" if conf >= 0.75 else "Medium" if conf >= 0.5 else "Low"
    return f"confidence: {label} ({pct}%)"


def _flow(block: Block, S) -> list:
    out: list = []
    if block.kind == "heading":
        out.append(Paragraph(_esc(block.text), S["h"]))
    elif block.kind == "prose":
        if block.tag:
            out.append(Paragraph(_esc(block.tag).upper(), S["tag"]))
        out.append(Paragraph(_rich(block.text), S["body"]))
    elif block.kind == "bullets":
        for it in block.items:
            out.append(Paragraph(f"•&nbsp;&nbsp;{_rich(it)}", S["bullet"]))
    elif block.kind == "finding":
        if block.caption:
            out.append(Paragraph(_rich(block.caption), S["claim"]))
        if block.text:
            out.append(Paragraph(_rich(block.text), S["body"]))
        if block.confidence is not None:
            out.append(Paragraph(_confidence_chip(block.confidence), S["small"]))
        out.append(Spacer(1, 4))
    elif block.kind == "recs":
        for i, r in enumerate(block.recs, 1):
            line = f"<b>{i}.</b>&nbsp;&nbsp;{_rich(r.get('action'))}"
            extra = [x for x in (
                f"impact: {_esc(r['expected_impact'])}" if r.get("expected_impact") else "",
                f"owner: {_esc(r['owner'])}" if r.get("owner") else "",
                f"by {_esc(r['timeline'])}" if r.get("timeline") else "",
            ) if x]
            out.append(Paragraph(line, S["bullet"]))
            if extra:
                out.append(Paragraph(" · ".join(extra), S["small"]))
    elif block.kind == "keynums" and block.keynums:
        out.append(_keynums(block.keynums, S))
        out.append(Spacer(1, 4))
    elif block.kind == "chart" and block.png:
        out.append(_image(block.png))
        if block.caption:
            out.append(Paragraph(_esc(block.caption), S["caption"]))
    elif block.kind == "table" and block.columns:
        out.append(_table(block.columns, block.rows, S))
        if block.caption:
            out.append(Paragraph(_esc(block.caption), S["caption"]))
        out.append(Spacer(1, 6))
    elif block.kind == "code" and block.text:
        code_style = ParagraphStyle(name="code", fontName="Courier", fontSize=8, leading=11,
                                    textColor=_BODY, backColor=_BG, borderPadding=8,
                                    leftIndent=2, spaceBefore=2, spaceAfter=6)
        out.append(Preformatted(block.text.strip(), code_style))
        if block.caption:
            out.append(Paragraph(_esc(block.caption), S["caption"]))
    return out


def render_pdf(doc: ExportDoc) -> bytes:
    S = _styles()
    buf = io.BytesIO()
    pdf = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title=doc.title, author="Aughor",
    )
    story: list = [Paragraph(_esc(doc.title), S["title"])]
    if doc.subtitle and doc.subtitle != doc.title:
        story.append(Paragraph(_esc(doc.subtitle), S["subtitle"]))
    if doc.meta:
        story.append(Paragraph("&nbsp;&nbsp;·&nbsp;&nbsp;".join(_esc(m) for m in doc.meta), S["meta"]))
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=1, color=_LINE, spaceBefore=4, spaceAfter=2))

    for b in doc.blocks:
        story.extend(_flow(b, S))

    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=0.5, color=_LINE))
    story.append(Paragraph("Generated by Aughor", S["small"]))

    pdf.build(story)
    buf.seek(0)
    return buf.read()
