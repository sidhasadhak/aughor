"""Custom instructions — user-authored steering text, per connection and per Canvas.

Two levels, two stores (deliberately separate since Sprint 53): connection-level
instructions apply to every question on the connection; Canvas-level instructions
let two Canvases scoped to the same connection carry distinct business rules.
Written via ``PUT /connections/{id}/instructions`` and ``PUT /canvases/{id}/
instructions`` (the Canvas Configure panel's Instructions tab is the live editor).

Consumed by the ``instructions`` grounding block (``aughor/agent/grounding.py``)
— the free-text steering lever a data team reaches for before it has structured
KB entries: "fiscal year starts in February", "exclude test accounts", "revenue
means net_revenue". Unlike the connection KB, nothing here is question-matched;
what the user wrote is injected verbatim on every ask against the scope.

Storage: ``data/instructions.json`` / ``data/canvas_instructions.json``, keyed by
connection / canvas id. Paths are resolved PER CALL (not captured at import) so
the conftest's ``AUGHOR_INSTRUCTIONS_FILE`` / ``AUGHOR_CANVAS_INSTRUCTIONS_FILE``
overrides — and a test's ``monkeypatch.setenv`` — always win without a module
reload.
"""
from __future__ import annotations

import json
from pathlib import Path

from aughor.db.sqlite_util import resolve_db_path

_CONN_DEFAULT = Path(__file__).parent.parent.parent / "data" / "instructions.json"
_CANVAS_DEFAULT = Path(__file__).parent.parent.parent / "data" / "canvas_instructions.json"


def _conn_file() -> Path:
    return resolve_db_path("AUGHOR_INSTRUCTIONS_FILE", _CONN_DEFAULT)


def _canvas_file() -> Path:
    return resolve_db_path("AUGHOR_CANVAS_INSTRUCTIONS_FILE", _CANVAS_DEFAULT)


def _load(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}
    return {}


def _save(path: Path, key: str, text: str) -> None:
    data = _load(path)
    data.setdefault(key, {})["text"] = text
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def connection_instructions(conn_id: str) -> str:
    return _load(_conn_file()).get(conn_id, {}).get("text", "")


def set_connection_instructions(conn_id: str, text: str) -> None:
    _save(_conn_file(), conn_id, text)


def canvas_instructions(canvas_id: str) -> str:
    return _load(_canvas_file()).get(canvas_id, {}).get("text", "")


def set_canvas_instructions(canvas_id: str, text: str) -> None:
    _save(_canvas_file(), canvas_id, text)


def build_instructions_block(connection_id: str, canvas_id: str = "") -> str:
    """The prompt block for one (connection, canvas) — '' when nothing is stored,
    so the prompt stays byte-identical for everyone who never wrote instructions.

    Canvas text renders AFTER connection text and is labelled as taking precedence:
    the Canvas is the narrower scope, and Sprint 53 split the stores precisely so a
    Canvas could sharpen (or contradict) the connection-wide rules.
    """
    conn_text = connection_instructions(connection_id).strip() if connection_id else ""
    canvas_text = canvas_instructions(canvas_id).strip() if canvas_id else ""
    if not conn_text and not canvas_text:
        return ""
    lines = ["CUSTOM INSTRUCTIONS (user-authored; follow them when writing SQL and presenting results):"]
    if conn_text:
        lines.append(conn_text)
    if canvas_text:
        if conn_text:
            lines.append("")
            lines.append("For this Canvas specifically (takes precedence on conflict):")
        lines.append(canvas_text)
    return "\n".join(lines) + "\n\n"
