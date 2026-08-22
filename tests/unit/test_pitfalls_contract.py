"""`report_checks.PITFALLS` and the Enforced table in docs/PITFALLS.md must agree.

Both the module docstring (`report_checks.py`) and the doc claimed this test existed. It did
not — the 2026-08-19 deep dive found the claim without the file. Three readers share one
vocabulary only if the vocabulary is one thing; this keeps it one thing.
"""
from __future__ import annotations

import re
from pathlib import Path

from aughor.agent.report_checks import PITFALLS

_DOC = Path(__file__).resolve().parents[2] / "docs" / "PITFALLS.md"
_ROW_RE = re.compile(r"^\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|")


def _enforced_rows() -> dict[int, str]:
    text = _DOC.read_text(encoding="utf-8")
    enforced = text.split("## Enforced", 1)[1].split("## Advisory", 1)[0]
    rows: dict[int, str] = {}
    for line in enforced.splitlines():
        m = _ROW_RE.match(line.strip())
        if m and m.group(1).isdigit():
            rows[int(m.group(1))] = m.group(2).strip()
    return rows


def test_enforced_table_matches_the_registry():
    rows = _enforced_rows()
    assert rows, "no Enforced rows parsed from docs/PITFALLS.md — the table shape changed"
    assert set(rows) == set(PITFALLS), (
        f"doc enforces {sorted(rows)} but the registry holds {sorted(PITFALLS)}"
    )
    for n, name in PITFALLS.items():
        assert rows[n].lower() == name.lower(), f"#{n}: doc says {rows[n]!r}, registry says {name!r}"
