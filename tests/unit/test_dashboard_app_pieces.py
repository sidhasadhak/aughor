"""Arc AP-4 — the pieces the builder's picker adds, as the server holds them (ROADMAP §3.57;
docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md §4.4).

A list of objects as cards, a map, a timeline, a choose-one and a search are pieces bound to the ontology: a person
places them, a model never adds one, and what each reads is checked through the object door before a dashboard is kept —
compiled over what this connection serves, never run. A map places by numbers and a timeline draws between moments; a
list sorted by a property it does not show has that property listed beside its cards, since the door sorts by a listed
property only.
"""
from __future__ import annotations

import copy
import shutil
import uuid

import pytest

from aughor.dashboards import pieces, validate as V, versions
from aughor.dashboards.home import Home
from tests.unit.test_dashboard_canvas import ME, volumes  # noqa: F401 — the fixture, by name
from tests.unit.test_dashboard_pieces import _graph

needs_rules = pytest.mark.skipif(shutil.which("node") is None or not V._BUNDLE.exists(),
                                 reason="the dashboard's rules need node + validate.bundle.mjs")


def _flags(monkeypatch) -> None:
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: False)


@pytest.fixture
def no_edits(monkeypatch):
    monkeypatch.setattr(pieces, "accepted_edits", lambda conn: [])


#: Each new piece over the test graph's orders and customers — the map placing orders by two of their numbers, since the
#: graph holds no coordinates and the server holds a map to numbers, not to a name.
PROPS = {
    "list": ("ObjectList", {"entity": "order", "title": "status", "figure": "total_amount", "mark": "payment_method",
                            "sort": "order_date", "descending": True}),
    "map": ("ObjectMap", {"entity": "order", "lat": "total_amount", "lng": "item_count", "label": "status"}),
    "timeline": ("ObjectTimeline", {"entity": "order", "start": "order_date", "end": "shipped_at"}),
    "choose": ("ChooseOne", {"entity": "customer", "chooses": "chosen-customer", "label": "full_name"}),
    "search": ("ObjectSearch", {"entity": "customer", "path": "full_name", "label": "Find customers"}),
}


def _desk(keys=tuple(PROPS), **changes) -> dict:
    """A desk holding the new pieces named, each changed as ``changes`` says — ``list={"sort": "x"}``."""
    elements = {
        "cockpit": {"type": "Cockpit", "props": {"title": "Desk"}, "children": ["desk"]},
        "desk": {"type": "Section", "props": {"title": "Desk"}, "children": list(keys)},
    }
    for key in keys:
        kind, props = PROPS[key]
        elements[key] = {"type": kind, "props": {**copy.deepcopy(props), **changes.get(key, {})}, "children": []}
    return {"root": "cockpit", "elements": elements}


# ── what only the platform knows ─────────────────────────────────────────────────────────────

def test_each_new_piece_resolves_when_what_it_reads_is_served(monkeypatch, no_edits):
    _flags(monkeypatch)
    assert pieces.not_resolved("c", _desk(), graph=_graph()) == []


@pytest.mark.parametrize("key, change, says", [
    ("list", {"title": "no_such"}, 'The object list "list" cannot be read:'),
    ("list", {"entity": "warehouse"}, 'The object list "list" cannot be read: no'),
    ("map", {"lat": "status"}, 'The map "map" reads its lat from "status", which holds no number.'),
    ("map", {"lng": "payment_method"}, 'The map "map" reads its lng from "payment_method", which holds no number.'),
    ("timeline", {"end": "status"}, 'The timeline "timeline" reads its end from "status", which holds no moment.'),
    ("timeline", {"start": "total_amount"}, 'reads its start from "total_amount", which holds no moment.'),
    ("choose", {"label": "nickname"}, 'The choose-one "choose" cannot be read:'),
    ("search", {"path": "lifetime_spend"}, "'lifetime_spend' holds no text"),
    ("search", {"path": "nickname"}, 'The search "search" cannot be read:'),
])
def test_a_new_piece_reading_what_this_connection_cannot_serve_is_refused_by_name(monkeypatch, no_edits, key, change,
                                                                                   says):
    _flags(monkeypatch)
    said = pieces.not_resolved("c", _desk(**{key: change}), graph=_graph())
    assert len(said) == 1 and says in said[0], said


def test_a_list_sorted_by_a_property_it_does_not_show_has_it_listed_beside_its_cards(monkeypatch, no_edits):
    """The object door sorts by a listed property only: the list asks for its sort beside what its cards say."""
    _flags(monkeypatch)
    assert pieces.listed_columns("ObjectList", {"title": "status", "sort": "customer_id"}) == ["status", "customer_id"]
    assert pieces.listed_columns("ObjectList", {"title": "status", "figure": "status", "sort": "status"}) == ["status"]
    assert pieces.not_resolved("c", _desk(("list",), list={"sort": "customer_id"}), graph=_graph()) == []


def test_without_a_name_a_list_and_a_timeline_are_called_by_their_key_and_resolve(monkeypatch, no_edits):
    _flags(monkeypatch)
    spec = _desk(("list", "timeline"))
    del spec["elements"]["list"]["props"]["title"]
    assert pieces.listed_columns("ObjectList", spec["elements"]["list"]["props"]) == ["total_amount", "payment_method",
                                                                                      "order_date"]
    assert pieces.not_resolved("c", spec, graph=_graph()) == []


def test_a_detail_following_a_list_holds_buttons_on_the_objects_it_lists(monkeypatch, no_edits):
    _flags(monkeypatch)
    spec = _desk(("list",))
    spec["elements"]["detail"] = {"type": "ObjectDetail", "props": {"follows": "list"}, "children": ["flag"]}
    spec["elements"]["flag"] = {"type": "ActionButton", "props": {"action": "flag_for_review"}, "children": []}
    spec["elements"]["desk"]["children"].append("detail")
    assert pieces.not_resolved("c", spec, graph=_graph()) == []
    spec["elements"]["flag"]["props"]["action"] = "hold_customer"
    assert pieces.not_resolved("c", spec, graph=_graph()) == [
        'The action button "flag" runs "hold_customer" on Customer, and the detail it sits in shows Order objects.']


def test_a_list_that_cannot_be_read_adds_no_second_sentence_for_the_detail_that_follows_it(monkeypatch, no_edits):
    _flags(monkeypatch)
    spec = _desk(("list",), list={"title": "no_such"})
    spec["elements"]["detail"] = {"type": "ObjectDetail", "props": {"follows": "list"}, "children": ["flag"]}
    spec["elements"]["flag"] = {"type": "ActionButton", "props": {"action": "flag_for_review"}, "children": []}
    spec["elements"]["desk"]["children"].append("detail")
    said = pieces.not_resolved("c", spec, graph=_graph())
    assert len(said) == 1 and said[0].startswith('The object list "list" cannot be read'), said


def test_what_the_new_pieces_read_is_what_a_release_tracks():
    spec = _desk(list={"segment": "active_orders"})
    reads = pieces.depends(spec, _graph())
    assert sorted(reads[("entity", "Order")]) == ["list", "map", "timeline"]
    assert sorted(reads[("entity", "Customer")]) == ["choose", "search"]
    assert [k for (kind, _), keys in reads.items() if kind != "entity" for k in keys] == ["list"]   # its segment's source


def test_a_person_places_the_new_pieces_and_a_model_never_adds_one():
    before = _desk(("list",))
    after = _desk(("list", "map"))
    assert pieces.pieces_written(before, after, new=False) == [
        'The edit adds the map "map". A person places a piece bound to the ontology: you may move one, resize it or '
        "take it off, never add one."]
    moved = copy.deepcopy(before)
    moved["elements"]["list"]["props"]["w"] = 6
    assert pieces.pieces_written(before, moved, new=False) == []
    renamed = _desk(("list",), list={"title": "payment_method"})
    assert "changes what the object list" in pieces.pieces_written(before, renamed, new=False)[0]


def test_an_approver_reads_each_new_piece_by_what_it_reads():
    assert [pieces.title_of(k, p) for k, p in PROPS.values()] == [
        "Object list · order", "Map · order", "Timeline · order", "Choose-one · customer", "Search · Find customers"]


def _drawn() -> dict:
    """A desk whose list chooses an order, and a drawer that opens on it holding the order's detail."""
    spec = _desk(("list",), list={"chooses": "chosen-order"})
    spec["elements"]["cockpit"]["children"].append("drawer")
    spec["elements"]["drawer"] = {"type": "Drawer", "props": {"title": "The order", "opens_on": "chosen-order"},
                                  "children": ["detail"]}
    spec["elements"]["detail"] = {"type": "ObjectDetail", "props": {"follows": "chosen-order"}, "children": []}
    return spec


def test_a_drawer_is_a_persons_wired_by_the_choice_it_opens_on_and_named_by_its_title(monkeypatch, no_edits):
    from aughor.dashboards import wiring
    spec = _drawn()
    assert "drawer" in wiring.wired(spec)
    assert pieces.title_of("Drawer", spec["elements"]["drawer"]["props"]) == "Drawer · The order"
    _flags(monkeypatch)
    assert pieces.not_resolved("c", spec, graph=_graph()) == []
    said = pieces.pieces_written(_desk(("list",), list={"chooses": "chosen-order"}), spec, new=False)
    assert any('adds the drawer "drawer"' in s for s in said), said


@needs_rules
def test_the_keep_door_keeps_a_new_piece_and_refuses_one_reading_what_is_not_there(volumes, monkeypatch, no_edits):  # noqa: F811
    tag = uuid.uuid4().hex[:6]
    home = Home(f"pieces{tag}", ME, f"desk-{tag}")
    graph = _graph()
    monkeypatch.setattr(pieces, "served_graph", lambda conn: graph)

    def keep(s):
        return versions.keep(home, s, approved_by="user:amit", source="a person's own hand", written_by_model=False)
    spec = _desk(("list", "map", "timeline", "search"))
    _flags(monkeypatch)
    wrong = keep(_desk(("map",), map={"lat": "status"}))
    assert not wrong.kept and 'which holds no number' in " ".join(wrong.sentences), wrong.sentences
    kept = keep(spec)
    assert kept.kept, kept.sentences
    assert versions.latest(home)["spec"]["elements"]["map"]["props"]["lat"] == "total_amount"
