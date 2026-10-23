"""Arc AP-4 — a dashboard built from a structure of pieces, as the server holds it (ROADMAP §3.57; the user, 2026-10-11:
"a widget based structure would be really helpful").

A section laid out in columns, rows or tabs of sections of its own, one that says its width among them, one that holds
nothing yet, and one that goes untitled are refused while `cockpit.app_pieces` is off — an install that has not turned it
on keeps the dashboard it had, and its writer is told nothing of it; a dashboard that says none of it keeps exactly as
before, whatever the flag says.
"""
from __future__ import annotations

import json
import shutil
import uuid

import pytest

from aughor.cockpit import app_pieces, validate as V, versions
from aughor.cockpit.home import Home
from tests.unit.test_cockpit_canvas import FIXTURE, ME, volumes  # noqa: F401 — the fixture, by name

needs_rules = pytest.mark.skipif(shutil.which("node") is None or not V._BUNDLE.exists(),
                                 reason="the dashboard's rules need node + validate.bundle.mjs")


def _flags(monkeypatch, on: set[str]) -> None:
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: name in on)


def _split() -> dict:
    """A desk split in two, side by side: its notes, 8 wide, and an empty section, 4 wide."""
    return {"root": "cockpit", "elements": {
        "cockpit": {"type": "Cockpit", "props": {"title": "Desk"}, "children": ["body"]},
        "body": {"type": "Section", "props": {"layout": "columns"}, "children": ["left", "right"]},
        "left": {"type": "Section", "props": {"title": "Today", "grid": 12, "w": 8}, "children": ["note"]},
        "right": {"type": "Section", "props": {"title": "New section", "grid": 12, "w": 4}, "children": []},
        "note": {"type": "Note", "props": {"text": "Oldest first", "w": 6, "h": 3}, "children": []}}}


def test_only_what_a_structure_says_is_found_and_nothing_else():
    assert app_pieces.structured(_split()) == ["body", "left", "right"]       # laid out; a width; a width and empty
    assert app_pieces.structured(json.loads(FIXTURE.read_text())) == []
    for nonsense in (None, [], {"elements": "x"}, {"elements": {"s": {"type": "Section"}}}):
        assert app_pieces.structured(nonsense) == []
    # each found for its own reason alone: untitled; titled and laid out; titled, empty and of the cockpit's own
    untitled = {"elements": {"s": {"type": "Section", "props": {"columns": 2}, "children": ["c"]}}}
    assert app_pieces.structured(untitled) == ["s"]
    laid_out = {"elements": {"s": {"type": "Section", "props": {"title": "Desk", "layout": "rows"}, "children": ["a"]}}}
    assert app_pieces.structured(laid_out) == ["s"]
    empty = {"elements": {"s": {"type": "Section", "props": {"title": "Later"}, "children": []}}}
    assert app_pieces.structured(empty) == ["s"]


def test_off_a_structured_cockpit_is_refused_and_says_what_on_it_is_not(monkeypatch):
    _flags(monkeypatch, set())
    said = app_pieces.refused_off(_split())
    assert len(said) == 1 and "body, left, right" in said[0] and "splitting a dashboard into sections is off" in said[0], said
    _flags(monkeypatch, {app_pieces.FLAG})
    assert app_pieces.refused_off(_split()) == []


def test_a_cockpit_whose_sections_hold_pieces_is_never_refused_whatever_the_flag(monkeypatch):
    for on in (set(), {app_pieces.FLAG}):
        _flags(monkeypatch, on)
        assert app_pieces.refused_off(json.loads(FIXTURE.read_text())) == []


@needs_rules
def test_the_keep_door_refuses_a_structure_while_off_and_keeps_it_while_on(volumes, monkeypatch):  # noqa: F811
    tag = uuid.uuid4().hex[:6]
    home = Home(f"struct{tag}", ME, f"desk-{tag}")

    def keep(s):
        return versions.keep(home, s, approved_by="user:amit", source="a person's own hand", written_by_model=False)
    _flags(monkeypatch, {"cockpit.builder"})
    off = keep(_split())
    assert off.status == "refused" and "splitting a dashboard into sections is off" in " ".join(off.sentences), off.sentences
    assert versions.latest(home) is None
    _flags(monkeypatch, {"cockpit.builder", app_pieces.FLAG})
    kept = keep(_split())
    assert kept.kept, kept.sentences
    assert versions.latest(home)["spec"]["elements"]["body"]["props"]["layout"] == "columns"


@needs_rules
def test_the_writer_of_a_cockpit_hears_of_the_structure_only_while_it_is_on(monkeypatch):
    _flags(monkeypatch, set())
    off = V.grammar()
    assert off and "layout" not in off and "Holds Card, Note, Image, at least one." in off
    _flags(monkeypatch, {app_pieces.FLAG})
    on = V.grammar()
    assert on and "layout (optional, one of: columns, rows, tabs" in on and "It may hold nothing yet." in on
