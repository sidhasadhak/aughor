"""
Report export — turn a stored `report_json` into a polished PDF or PowerPoint.

    data, filename, media_type = export_report(inv, "pdf")

`inv` is the dict returned by `GET /investigations/{id}` (it carries `kind`,
`report`, `question`, `query_history`, …). The parsing (report_json → an
`ExportDoc`) is shared; only the final render differs per format.
"""
from __future__ import annotations

import re

from .document import ExportDoc, build_export_doc
from .pdf import render_pdf
from .slides import render_pptx

__all__ = ["export_report", "build_export_doc", "ExportDoc"]

_MEDIA = {
    "pdf": "application/pdf",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:60] or "report"


def export_report(inv: dict, fmt: str = "pdf", *, narrate: bool = False) -> tuple[bytes, str, str]:
    """Render `inv` to `fmt` ∈ {pdf, pptx}. Returns (bytes, filename, media_type)."""
    fmt = (fmt or "pdf").lower()
    if fmt not in _MEDIA:
        raise ValueError(f"unsupported export format: {fmt!r} (use pdf or pptx)")
    doc = build_export_doc(inv, narrate=narrate)
    data = render_pdf(doc) if fmt == "pdf" else render_pptx(doc)
    return data, f"{_slug(doc.title)}.{fmt}", _MEDIA[fmt]
