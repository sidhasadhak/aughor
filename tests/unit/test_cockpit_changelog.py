"""Arc AP-6 — a changelog in words (ROADMAP §3.57; the study's §4.7).

History said "2 added · 1 changed" — the spec's keys, counted. Each version now says what it changed as a person reads
it: what was added, taken off, moved, set up anew, resized, and which sets and values were named, changed or taken off;
read from the two versions the ledger keeps, so a version kept before this says its changes too.
"""
from __future__ import annotations

import copy

from aughor.cockpit import changelog


def _desk() -> dict:
    return {"root": "cockpit", "elements": {
        "cockpit": {"type": "Cockpit", "props": {"title": "Desk"}, "children": ["today", "later"]},
        "today": {"type": "Section", "props": {"title": "Today", "grid": 12}, "children": ["note", "list"]},
        "later": {"type": "Section", "props": {"title": "Waiting", "grid": 12}, "children": ["map"]},
        "note": {"type": "Note", "props": {"text": "Oldest first", "w": 6, "h": 3}, "children": []},
        "list": {"type": "ObjectList", "props": {"entity": "order", "title": "status", "w": 6, "h": 8}, "children": []},
        "map": {"type": "ObjectMap", "props": {"entity": "distribution_center", "lat": "latitude", "lng": "longitude",
                                               "w": 6, "h": 9}, "children": []},
    }}


def test_a_first_version_says_it_started_the_cockpit():
    assert changelog.said(None, _desk()) == ["Started the cockpit"]


def test_each_change_is_said_by_what_the_element_is_and_names():
    before, after = _desk(), _desk()
    after["elements"]["map"]["props"]["w"] = 8                                       # resized
    after["elements"]["today"]["children"].remove("note")                            # moved
    after["elements"]["later"]["children"].append("note")
    after["elements"]["list"]["props"]["title"] = "created_at"                       # set up anew
    assert changelog.said(before, after) == [
        "Moved a note to the section Waiting", "Changed what the object list · order shows",
        "Resized the map · distribution center"]


def test_what_was_added_and_taken_off_is_said_once_with_what_it_holds():
    before, after = _desk(), _desk()
    del after["elements"]["map"]
    after["elements"]["later"]["children"] = ["drawer"]
    after["elements"]["drawer"] = {"type": "Drawer", "props": {"title": "The order", "opens_on": "chosen-order"},
                                   "children": ["detail"]}
    after["elements"]["detail"] = {"type": "ObjectDetail", "props": {"follows": "chosen-order"}, "children": []}
    lines = changelog.said(before, after)
    assert lines == ["Added the drawer · The order", "Took off the map · distribution center"], lines


def test_a_rename_says_the_new_name_and_the_sets_and_values_are_said_by_their_labels():
    before, after = _desk(), _desk()
    after["elements"]["later"]["props"]["title"] = "Past the promise"
    after["sets"] = {"late": {"label": "Shipped late", "entity": "order", "segment": "late_dispatch"}}
    after["values"] = {"window": {"label": "Window", "kind": "days", "value": 14}}
    assert changelog.said(before, after) == [
        "Renamed the section Waiting to Past the promise", "Named the set Shipped late", "Named the value Window"]
    later = copy.deepcopy(after)
    later["values"]["window"]["value"] = 7
    del later["sets"]["late"]
    assert changelog.said(after, later) == ["Took off the set Shipped late", "Changed the value Window"]


def test_many_changes_say_the_first_and_count_the_rest():
    before, after = _desk(), _desk()
    for i in range(6):
        after["elements"]["today"]["children"].append(f"n{i}")
        after["elements"][f"n{i}"] = {"type": "Note", "props": {"text": str(i)}, "children": []}
    lines = changelog.said(before, after)
    assert len(lines) == changelog.MAX_LINES and lines[-1] == f"and {6 - (changelog.MAX_LINES - 1)} more", lines


def test_an_unchanged_spec_says_nothing():
    assert changelog.said(_desk(), _desk()) == []


def test_a_piece_reading_a_set_is_said_by_the_sets_label():
    before, after = _desk(), _desk()
    after["sets"] = {"its-lines": {"label": "Its lines", "entity": "order_item",
                                   "linked_to": {"choice": "chosen-order", "path": "order_id"}}}
    after["elements"]["today"]["children"].append("lines")
    after["elements"]["lines"] = {"type": "ObjectTable", "props": {"set": "its-lines"}, "children": []}
    assert changelog.said(before, after) == ["Added the objects table · Its lines", "Named the set Its lines"]


def test_a_card_is_said_by_its_title_and_a_changed_query_card_by_what_it_shows():
    before = _desk()
    before["elements"]["today"]["children"].append("c")
    before["elements"]["c"] = {"type": "Card", "props": {"card": "k1"}, "children": []}
    after = copy.deepcopy(before)
    after["elements"]["c"]["props"]["card"] = "k2"
    titles = {"k1": "Sales by month", "k2": "Sales by month"}
    assert changelog.said(_desk(), before, titles) == ["Added the card Sales by month"]
    assert changelog.said(before, after, titles) == ["Changed what the card Sales by month shows"]
    assert changelog.said(_desk(), before) == ["Added the card k1"]               # a server with no title says the id
