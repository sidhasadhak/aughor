"""Arc AP-4 — a dashboard built from a structure of pieces, as the server holds it (ROADMAP §3.57; the user, 2026-10-11:
"a widget based structure would be really helpful").

A section laid out in columns, rows or tabs of sections of its own, one that says its width among them, one that holds
nothing yet, and one that goes untitled are kept, and the writer of a dashboard is told of them.
"""
from __future__ import annotations

import shutil
import uuid

import pytest

from aughor.dashboards import validate as V, versions
from aughor.dashboards.home import Home
from tests.unit.test_dashboard_canvas import ME, volumes  # noqa: F401 — the fixture, by name

needs_rules = pytest.mark.skipif(shutil.which("node") is None or not V._BUNDLE.exists(),
                                 reason="the dashboard's rules need node + validate.bundle.mjs")


def _split() -> dict:
    """A desk split in two, side by side: its notes, 8 wide, and an empty section, 4 wide."""
    return {"root": "cockpit", "elements": {
        "cockpit": {"type": "Cockpit", "props": {"title": "Desk"}, "children": ["body"]},
        "body": {"type": "Section", "props": {"layout": "columns"}, "children": ["left", "right"]},
        "left": {"type": "Section", "props": {"title": "Today", "grid": 12, "w": 8}, "children": ["note"]},
        "right": {"type": "Section", "props": {"title": "New section", "grid": 12, "w": 4}, "children": []},
        "note": {"type": "Note", "props": {"text": "Oldest first", "w": 6, "h": 3}, "children": []}}}


@needs_rules
def test_the_keep_door_keeps_a_structure(volumes, monkeypatch):  # noqa: F811
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: False)
    tag = uuid.uuid4().hex[:6]
    home = Home(f"struct{tag}", ME, f"desk-{tag}")
    kept = versions.keep(home, _split(), approved_by="user:amit", source="a person's own hand", written_by_model=False)
    assert kept.kept, kept.sentences
    assert versions.latest(home)["spec"]["elements"]["body"]["props"]["layout"] == "columns"


@needs_rules
def test_the_writer_of_a_cockpit_hears_of_the_structure():
    told = V.grammar()
    assert told and "layout (optional, one of: columns, rows, tabs" in told and "It may hold nothing yet." in told
