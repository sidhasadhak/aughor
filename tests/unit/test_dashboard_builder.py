"""Arc AP-1 — a dashboard built in place, as the server holds it (ROADMAP §3.57; docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md).

What a dashboard built in place says — a section on the twelve-column grid, each element's room in columns and rows, the
filter column's width, a chart's measure and split — is kept, and its writer is told of the grid. Resizing a piece on the
grid is arrangement, as resizing it by name was: it neither moves the release the dashboard is pinned to nor counts, in a
model's edit, as changing what it reads.
"""
from __future__ import annotations

import json
import shutil
import uuid

import pytest

from aughor.dashboards import cards, pieces, validate as V, versions
from aughor.dashboards.home import Home
from aughor.cards.models import StoredCard
from tests.unit.test_dashboard_canvas import FIXTURE, ME, volumes  # noqa: F401 — the fixture, by name

needs_rules = pytest.mark.skipif(shutil.which("node") is None or not V._BUNDLE.exists(),
                                 reason="the dashboard's rules need node + validate.bundle.mjs")


def _on_grid(spec: dict) -> dict:
    """The fixture's headline section laid on the grid, each card in a box of its own."""
    out = json.loads(json.dumps(spec))
    sec = out["elements"]["sec-headline"]
    sec["props"] = {"title": sec["props"]["title"], "grid": 12}
    for k in sec["children"]:
        out["elements"][k]["props"].update({"w": 4, "h": 4})
    return out


# ── a dashboard built in place is kept ──────────────────────────────────────────────────────────────────

@needs_rules
def test_the_keep_door_keeps_a_grid(volumes, monkeypatch):  # noqa: F811
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: False)
    tag = uuid.uuid4().hex[:6]
    home = Home(f"grid{tag}", ME, f"orders-{tag}")
    rate, net = f"rate{tag}", f"net{tag}"
    for cid, title in ((rate, "Return rate"), (net, "Net revenue")):
        cards.place(home, StoredCard(id=cid, kind="kpi", title=title, sql="SELECT 1"))
    spec = _on_grid(json.loads(FIXTURE.read_text().replace("c7f3a001", rate).replace("c91b2002", net)))

    def keep(s):
        return versions.keep(home, s, approved_by="user:amit", source="a person's own hand", written_by_model=False)
    assert keep(spec).kept
    assert versions.latest(home)["spec"]["elements"]["sec-headline"]["props"]["grid"] == 12


# ── what its writer is told ─────────────────────────────────────────────────────────────────────────────

@needs_rules
def test_the_writer_of_a_cockpit_is_told_of_the_grid():
    told = V.grammar()
    assert told and 'grid (optional: 12)' in told and 'In a section with "grid": 12' in told


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
