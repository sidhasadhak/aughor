"""
Report export — turn a stored `report_json` into a polished PDF or PowerPoint.

    data, filename, media_type = export_report(inv, "pdf")

`inv` is the dict returned by `GET /investigations/{id}` (it carries `kind`,
`report`, `question`, `query_history`, …). The parsing (report_json → an
`ExportDoc`) is shared; only the final render differs per format.
"""
from __future__ import annotations

import re

# The renderers carry the heavy end of the dependency tree — reportlab, python-pptx and
# matplotlib — and none of it is on the request path until someone actually asks for a
# file. They ship as the `export` extra so a serving deployment need not carry them
# (measured 2026-08-05; see docs/VERCEL_PLATFORM_DESIGN_2026-08-05.md).
#
# Imported here rather than inside export_report so the cost is paid once, and the
# absence is reported as a MISSING FEATURE with the command that fixes it — an
# ImportError traceback out of a router tells the operator nothing actionable.
#
# `.document` belongs INSIDE this guard, not above it: it imports `.charts`, which
# imports matplotlib at module scope. Sitting above, it raised ModuleNotFoundError
# before the guard could run, so a serving install answered the export route with 500
# and a traceback — the exact outcome the guard exists to prevent.
try:
    from .document import ExportDoc, build_export_doc
    from .pdf import render_pdf
    from .slides import render_pptx
    EXPORT_AVAILABLE = True
    _EXPORT_IMPORT_ERROR = ""
except ImportError as _exc:                       # pragma: no cover — depends on install
    ExportDoc = build_export_doc = None           # type: ignore[assignment,misc]
    render_pdf = render_pptx = None               # type: ignore[assignment]
    EXPORT_AVAILABLE = False
    _EXPORT_IMPORT_ERROR = str(_exc)


class ExportUnavailable(RuntimeError):
    """Raised when a report export is requested without the `export` extra installed."""


__all__ = ["export_report", "build_export_doc", "ExportDoc",
           "EXPORT_AVAILABLE", "ExportUnavailable"]

_MEDIA = {
    "pdf": "application/pdf",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:60] or "report"


def export_report(inv: dict, fmt: str = "pdf", *, narrate: bool = False,
                  money_symbol: str = "") -> tuple[bytes, str, str]:
    """Render `inv` to `fmt` ∈ {pdf, pptx}. Returns (bytes, filename, media_type).

    `money_symbol` is the connection's effective currency symbol, resolved by the
    CALLER (the router owns that lookup — the platform-side export must not import
    agent-side settings/profile modules): money-named chart figures without an
    explicit currency unit carry it, matching the web's fallback."""
    fmt = (fmt or "pdf").lower()
    if fmt not in _MEDIA:
        raise ValueError(f"unsupported export format: {fmt!r} (use pdf or pptx)")
    if not EXPORT_AVAILABLE:
        raise ExportUnavailable(
            "Report export needs the 'export' extra (reportlab, python-pptx, "
            "matplotlib). Install it with:  uv sync --extra export   —  "
            f"underlying import error: {_EXPORT_IMPORT_ERROR}")
    doc = build_export_doc(inv, narrate=narrate, money_symbol=money_symbol)
    data = render_pdf(doc) if fmt == "pdf" else render_pptx(doc)
    return data, f"{_slug(doc.title)}.{fmt}", _MEDIA[fmt]
