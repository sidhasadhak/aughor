"""Arc AP-1 — a dashboard built in place, as the server holds it (ROADMAP §3.57; docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md).

What a dashboard built in place says — a section on the twelve-column grid, each element's room in columns and rows, the
filter column's width, a chart's measure and split — is refused while `cockpit.builder` is off, so an install that has
not turned it on keeps the dashboard it had; its writer is told nothing about the grid; and a dashboard that says none of it
keeps exactly as before, whatever the flag says. Resizing a piece on the grid is arrangement, as resizing it by name
was: it neither moves the release the dashboard is pinned to nor counts, in a model's edit, as changing what it reads.
"""
from __future__ import annotations

import json
import shutil
import uuid

import pytest

from aughor.cockpit import builder, cards, pieces, validate as V, versions
from aughor.cockpit.home import Home
from aughor.dashboard.models import DashboardCard
from tests.unit.test_cockpit_canvas import FIXTURE, ME, volumes  # noqa: F401 — the fixture, by name

needs_rules = pytest.mark.skipif(shutil.which("node") is None or not V._BUNDLE.exists(),
                                 reason="the dashboard's rules need node + validate.bundle.mjs")


def _builder(monkeypatch, on: bool) -> None:
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: on and name == builder.FLAG)


def _on_grid(spec: dict) -> dict:
    """The fixture's headline section laid on the grid, each card in a box of its own."""
    out = json.loads(json.dumps(spec))
    sec = out["elements"]["sec-headline"]
    sec["props"] = {"title": sec["props"]["title"], "grid": 12}
    for k in sec["children"]:
        out["elements"][k]["props"].update({"w": 4, "h": 4})
    return out


def _plain() -> dict:
    return json.loads(FIXTURE.read_text())


# ── what only a cockpit built in place says ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind,props,said", [
    ("Section", {"title": "Today", "grid": 12}, True),
    ("Section", {"title": "Today", "grid": None}, False),
    ("Section", {"title": "Today", "columns": 3}, False),
    ("Card", {"card": "c7f3a001", "w": 4, "h": 4}, True),
    ("Card", {"card": "c7f3a001", "size": "wide"}, False),
    ("ObjectFilters", {"entity": "order", "properties": [], "w": 7}, True),
    ("ObjectChart", {"entity": "order", "label": "Orders", "time": "created_at", "split": "status"}, True),
    ("ObjectChart", {"entity": "order", "label": "Orders", "time": "created_at", "agg": "sum", "path": "revenue"}, True),
    ("ObjectChart", {"entity": "order", "label": "Orders", "time": "created_at", "days": 30}, False),
    ("ActionButton", {"action": "open_case", "w": 3}, False),      # a button has no room of its own: not placed
])
def test_each_prop_only_a_cockpit_built_in_place_writes_is_found_and_no_other(kind, props, said):
    spec = {"root": "x", "elements": {"x": {"type": kind, "props": props, "children": []}}}
    assert builder.built_in_place(spec) == (["x"] if said else [])


def test_off_a_cockpit_built_in_place_is_refused_and_says_why(monkeypatch):
    _builder(monkeypatch, False)
    said = builder.refused(_on_grid(_plain()))
    assert len(said) == 1 and "building dashboards in place is off" in said[0] and "4 element(s)" in said[0]


def test_on_it_is_not_refused(monkeypatch):
    _builder(monkeypatch, True)
    assert builder.refused(_on_grid(_plain())) == []


def test_a_cockpit_arranged_by_name_is_never_refused_whatever_the_flag(monkeypatch):
    for on in (False, True):
        _builder(monkeypatch, on)
        assert builder.refused(_plain()) == []
        assert builder.refused(None) == [] and builder.refused({"elements": "nonsense"}) == []


@needs_rules
def test_the_keep_door_refuses_a_grid_while_off_and_keeps_it_while_on(volumes, monkeypatch):  # noqa: F811
    tag = uuid.uuid4().hex[:6]
    home = Home(f"grid{tag}", ME, f"orders-{tag}")
    rate, net = f"rate{tag}", f"net{tag}"
    for cid, title in ((rate, "Return rate"), (net, "Net revenue")):
        cards.place(home, DashboardCard(id=cid, kind="kpi", title=title, sql="SELECT 1"))
    spec = _on_grid(json.loads(FIXTURE.read_text().replace("c7f3a001", rate).replace("c91b2002", net)))

    def keep(s):
        return versions.keep(home, s, approved_by="user:amit", source="a person's own hand", written_by_model=False)
    _builder(monkeypatch, False)
    off = keep(spec)
    assert off.status == "refused" and "building dashboards in place is off" in " ".join(off.sentences)
    assert versions.latest(home) is None                                     # nothing was kept
    _builder(monkeypatch, True)
    assert keep(spec).kept
    assert versions.latest(home)["spec"]["elements"]["sec-headline"]["props"]["grid"] == 12


# ── what its writer is told ─────────────────────────────────────────────────────────────────────────────

@needs_rules
def test_the_writer_of_a_cockpit_is_told_of_the_grid_only_while_the_builder_is_on(monkeypatch):
    _builder(monkeypatch, False)
    off = V.grammar()
    assert off and "grid" not in off
    _builder(monkeypatch, True)
    on = V.grammar()
    assert on and 'grid (optional: 12)' in on and 'In a section with "grid": 12' in on
    # the grid is all that is added: the text off is the text on with the two grid fragments taken out
    assert on.replace(", grid (optional: 12)", "").split(' In a section with "grid": 12')[0] in off


# ── resizing on the grid is arrangement ─────────────────────────────────────────────────────────────────

def _table_spec(**room) -> dict:
    props = {"entity": "order", "columns": ["status"], **room}
    return {"root": "c", "elements": {
        "c": {"type": "Cockpit", "props": {"title": "Orders"}, "children": ["s"]},
        "s": {"type": "Section", "props": {"title": "Orders", "grid": 12}, "children": ["t"]},
        "t": {"type": "ObjectTable", "props": props, "children": []}}}


def test_a_model_may_resize_a_piece_on_the_grid_and_may_not_change_what_it_reads():
    before = _table_spec(w=8, h=8)
    assert pieces.pieces_written(before, _table_spec(w=12, h=11), new=False) == []
    changed = _table_spec(w=8, h=8)
    changed["elements"]["t"]["props"]["columns"] = ["status", "created_at"]
    assert "never change what it reads" in " ".join(pieces.pieces_written(before, changed, new=False))


def test_resizing_a_piece_on_the_grid_keeps_the_release_it_is_pinned_to(monkeypatch):
    from aughor.ontology import release
    monkeypatch.setattr(release, "enabled", lambda: True)
    monkeypatch.setattr(release, "current_id_for_connection", lambda conn: "rel@9")
    before = {"spec": _table_spec(w=8, h=8), "ontology_release": "rel@3"}
    assert pieces.pin_for("c1", before, _table_spec(w=12, h=14)) == "rel@3"        # arrangement reads nothing new
    reread = _table_spec(w=8, h=8)
    reread["elements"]["t"]["props"]["sort"] = "created_at"
    assert pieces.pin_for("c1", before, reread) == "rel@9"                         # what it reads changed: pinned now


# ── a chart's measure and split are compiled before it is kept ──────────────────────────────────────────

def test_a_chart_is_probed_with_its_measure_and_its_split():
    [(what, body)] = pieces._from_object_probes("ObjectChart", {
        "entity": "order", "label": "Revenue", "time": "created_at", "agg": "sum", "path": "revenue", "split": "status"})
    assert body["measures"] == [{"name": "n", "agg": "sum", "path": "revenue"}]
    assert body["by"] == ["status"] and body["time"] == "created_at" and body["grain"] == "day"
    [(_, plain)] = pieces._from_object_probes("ObjectChart", {"entity": "order", "label": "Orders", "time": "created_at"})
    assert plain["measures"] == [{"name": "n", "agg": "count", "path": ""}] and "by" not in plain
