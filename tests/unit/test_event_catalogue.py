"""Phase 7 of the 2027 study, P7-2 — the event catalogue (`aughor/kernel/events.py`) as a measured
ratchet: every kind the source journals is catalogued with what its payload carries.
"""
from __future__ import annotations

import re
from pathlib import Path

from aughor.kernel import events as E

REPO = Path(__file__).resolve().parents[2]
_EMIT = re.compile(r"\.emit\(\s*\"([a-z][a-z0-9_.]*)\"")
_AUDIT = re.compile(r"_AUDIT_KIND\s*=\s*\"([a-z][a-z0-9_.]*)\"")
# A module's local `_emit(...)` / `_journal(...)` helper carries a kind as its first argument only
# when its own signature says so (`def _emit(kind, ...)`); `routers/_shared.py`'s `_emit(step, status)`
# names a birth STEP and journals it under `birth.step`, so its literals are not kinds.
_HELPER_CALL = re.compile(r"\b(?:_emit|_journal)\(\s*\"([a-z][a-z0-9_.]*)\"")
_HELPER_TAKES_KIND = re.compile(r"def (?:_emit|_journal)\(\s*(?:self,\s*)?kind\b")


def emitted_kinds() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in (REPO / "aughor").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(errors="ignore")
        patterns = [_EMIT, _AUDIT] + ([_HELPER_CALL] if _HELPER_TAKES_KIND.search(text) else [])
        for rx in patterns:
            for kind in rx.findall(text):
                found.setdefault(kind, []).append(path.relative_to(REPO).as_posix())
    return found


def test_every_kind_the_source_journals_is_catalogued():
    found = emitted_kinds()
    assert len(found) > 30, f"the scan found only {len(found)} kinds — the walk is broken"
    missing = {k: v for k, v in found.items() if k not in E.CATALOGUE}
    assert not missing, "uncatalogued event kinds (add each to aughor/kernel/events.CATALOGUE with its payload): " + \
        "; ".join(f"{k} ({', '.join(sorted(set(v))[:2])})" for k, v in sorted(missing.items()))


def test_every_row_says_what_it_records_and_what_its_payload_carries():
    for kind, row in E.CATALOGUE.items():
        assert len(row.get("what", "")) > 10, kind
        assert isinstance(row.get("payload"), list), kind
        assert row.get("emitted_by"), kind
    assert set(E.SUBSCRIBABLE) <= set(E.CATALOGUE)
    rows = {r["kind"]: r for r in E.catalogue()}
    assert rows["mcp.tool_call"]["category"] == "data_access" and rows["job.state"]["category"] == "operational"
    assert rows["claim.restated"]["category"] == "record" and rows["claim.restated"]["subscribable"] is True
    assert rows["job.state"]["subscribable"] is False and E.is_catalogued("outcome.booked") and not E.is_catalogued("x.y")
