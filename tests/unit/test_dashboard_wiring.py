"""Arc AP-2 and AP-3 — a dashboard wired as an App, as the server holds it (ROADMAP §3.57;
docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md §4.1b, §4.3 and §4.5).

A wired dashboard names sets its pieces read and values its sets read; a table names what a click chooses and what its
ticks collect; a figure switches a list; action buttons run declared actions on what a reader chose or ticked. What only
the platform knows is checked before a keep: every set compiles through the
object door over what this connection serves, and each button's action is declared and takes each parameter from a
source that can hold it — an order from a chosen order, never a customer; a value from the form or a fixed value, never
a choice. A person wires a cockpit: a model's edit arranges one and never changes its sets or values, or what a piece
reads.
"""
from __future__ import annotations

import json
import shutil
import uuid

import pytest

from aughor.dashboards import pieces, validate as V, versions, wiring
from aughor.dashboards.home import Home
from tests.unit.test_dashboard_canvas import FIXTURE, ME, volumes  # noqa: F401 — the fixture, by name
from tests.unit.test_dashboard_pieces import _graph as _pieces_graph

needs_rules = pytest.mark.skipif(shutil.which("node") is None or not V._BUNDLE.exists(),
                                 reason="the dashboard's rules need node + validate.bundle.mjs")
def _flags(monkeypatch, on: frozenset[str] = frozenset()) -> None:
    """Every flag off but ``on`` — a wired desk needs none since 2026-10-28 (ROADMAP §3.65)."""
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: name in on)


@pytest.fixture
def no_edits(monkeypatch):
    monkeypatch.setattr(pieces, "accepted_edits", lambda conn: [])


def _graph():
    """The test graph of the ontology pieces' tests: orders, customers and their lines; "flag_for_review" on an order
    (its order an object, its reason a value) and "hold_customer" on a customer."""
    return _pieces_graph()


def _desk(**changes) -> dict:
    """The dispatch desk of the mockup, over the test graph's orders: a window the author sets, the orders placed in it,
    the active ones among them, a chosen order's lines; a figure that switches the list; the list choosing and ticking;
    a detail following the chosen order; and two buttons."""
    spec = {
        "root": "cockpit",
        "values": {"window": {"label": "Window", "kind": "days", "value": 14}},
        "sets": {
            "placed": {"label": "Placed", "entity": "order",
                       "where": [{"path": "order_date", "op": "in_last", "value_from": "window"}]},
            "active": {"label": "Active", "from": "placed", "segment": "active_orders"},
            "lines": {"label": "Its lines", "entity": "order_item",
                      "linked_to": {"choice": "chosen-order", "path": "order_id"}},
        },
        "elements": {
            "cockpit": {"type": "Cockpit", "props": {"title": "Dispatch desk"}, "children": ["desk"]},
            "desk": {"type": "Section", "props": {"title": "Dispatch desk"},
                     "children": ["fig-active", "table", "detail", "lines", "buttons"]},
            "fig-active": {"type": "ObjectFigure", "props": {"set": "active", "of": "placed", "shows": "shown",
                                                             "label": "Active", "agg": "count"}, "children": []},
            "table": {"type": "ObjectTable", "props": {"set": "placed", "set_from": "shown", "chooses": "chosen-order",
                                                       "ticks": "ticked-orders", "columns": ["status", "order_date"],
                                                       "sort": "order_date"}, "children": []},
            "detail": {"type": "ObjectDetail", "props": {"follows": "chosen-order"}, "children": []},
            "lines": {"type": "ObjectTable", "props": {"set": "lines", "columns": ["quantity", "line_total"]},
                      "children": []},
            "buttons": {"type": "ActionButtons", "props": {"buttons": [
                {"action": "flag_for_review", "label": "Flag this one", "primary": True,
                 "params": {"order": {"from": "chosen-order"}, "reason": {"ask": True}}, "after": {"read": ["active"]}},
                {"action": "flag_for_review", "label": "Flag the ticked ones",
                 "params": {"order": {"from": "ticked-orders"}, "reason": {"value": "past the promise"}}},
            ]}, "children": []},
        },
    }
    for path, value in changes.items():
        *head, last = path.split(".")
        at = spec
        for k in head:
            at = at[k]
        if value is None:
            at.pop(last, None)
        else:
            at[last] = value
    return spec


def _read(**sets) -> dict:
    """A wiring as the bundle reads it, written by hand — for the checks that need no node."""
    return {"sets": sets, "buttons": []}


def _button(action: str, **params) -> dict:
    return {"sets": {}, "buttons": [{"element": "buttons", "index": 0, "action": action, "params": params}]}


# ── what only a wired dashboard says ──────────────────────────────────────────────────────────────────────

def test_a_wired_cockpit_is_found_by_its_sets_values_and_each_wired_piece_in_that_order():
    # a detail follows a table by `follows`, as it did before sets: that alone does not wire it
    assert wiring.wired(_desk()) == ["sets", "values", "fig-active", "table", "lines", "buttons"]


@pytest.mark.parametrize("prop", wiring.WIRED_PROPS)
def test_each_prop_that_wires_a_piece_is_found_and_none_other(prop):
    spec = {"elements": {"t": {"type": "ObjectTable", "props": {"entity": "order", prop: "x"}, "children": []}}}
    assert wiring.wired(spec) == ["t"]
    plain = {"elements": {"t": {"type": "ObjectTable", "props": {"entity": "order", "segment": "late"}, "children": []}}}
    assert wiring.wired(plain) == []


def test_action_buttons_are_wired_whatever_they_hold_and_nonsense_is_not():
    assert wiring.wired({"elements": {"b": {"type": "ActionButtons", "props": {"buttons": []}, "children": []}}}) == ["b"]
    for nonsense in (None, [], {"elements": "x"}, {"elements": {"a": "x"}}, {"sets": {}, "values": None, "elements": {}}):
        assert wiring.wired(nonsense) == []


def test_a_cockpit_that_is_not_wired_has_nothing_to_resolve():
    assert wiring.not_resolved("c", json.loads(FIXTURE.read_text()), graph=None) == []


# ── what only the platform knows: every set compiles ───────────────────────────────────────────────────

def test_a_wiring_that_could_not_be_read_is_not_kept_unchecked(monkeypatch):
    monkeypatch.setattr(wiring, "read", lambda spec: None)
    said = wiring.not_resolved("c", _desk(), graph=_graph())
    assert len(said) == 1 and "could not be read, so it was not checked" in said[0], said


def test_a_wired_cockpit_without_an_ontology_is_refused(monkeypatch):
    monkeypatch.setattr(pieces, "served_graph", lambda conn: None)
    said = wiring.not_resolved("c", _desk(), wiring=_read())
    assert len(said) == 1 and "no ontology is built for this connection" in said[0], said


def test_sets_that_compile_pass(no_edits):
    read = _read(placed={"entity": "order", "segment": "", "filters": [{"path": "order_date", "op": "in_last", "value": 14}]},
                 active={"entity": "order", "segment": "active_orders",
                         "filters": [{"path": "order_date", "op": "in_last", "value": 14}]},
                 lines={"entity": "order_item", "segment": "", "filters": [{"path": "order_id", "op": "=", "value": "probe"}]})
    assert wiring.not_resolved("c", _desk(), graph=_graph(), wiring=read) == []


@pytest.mark.parametrize("bad, says", [
    ({"entity": "warehouse", "segment": "", "filters": []}, "'warehouse'"),
    ({"entity": "order", "segment": "overdue_dispatch", "filters": []}, "has no segment 'overdue_dispatch'"),
    ({"entity": "order", "segment": "", "filters": [{"path": "no_such", "op": "=", "value": 1}]}, "no_such"),
    ({"entity": "order", "segment": "", "filters": [{"path": "status", "op": "in_last", "value": 14}]},
     "reads a date or a time, and 'status' is neither"),
])
def test_a_set_that_does_not_compile_here_is_refused_by_name(no_edits, bad, says):
    said = " ".join(wiring.not_resolved("c", _desk(), graph=_graph(), wiring=_read(waiting=bad)))
    assert 'The set "waiting" cannot be read:' in said and says in said, said


def test_a_set_the_web_refused_is_said_in_its_own_words(no_edits):
    ring = {"refused": 'The sets "a" → "b" → "a" start from each other in a ring.'}
    assert wiring.not_resolved("c", _desk(), graph=_graph(), wiring=_read(a=ring)) == [ring["refused"]]


# ── what only the platform knows: each button runs a declared action on what can hold its parameters ──────

def test_buttons_whose_sources_hold_their_parameters_pass(no_edits):
    ok = _button("flag_for_review", order={"source": "chosen", "entity": "order"}, reason={"source": "ask", "entity": ""})
    assert wiring.not_resolved("c", _desk(), graph=_graph(), wiring=ok) == []
    each = _button("flag_for_review", order={"source": "ticked", "entity": "Order"}, reason={"source": "value", "entity": ""})
    assert wiring.not_resolved("c", _desk(), graph=_graph(), wiring=each) == []
    a_set = _button("flag_for_review", order={"source": "set", "entity": "orders"})        # the table's name for it
    assert wiring.not_resolved("c", _desk(), graph=_graph(), wiring=a_set) == []


@pytest.mark.parametrize("read, says", [
    (_button("refund", order={"source": "chosen", "entity": "order"}),
     'The button 1 of "buttons" runs "refund", which this connection does not declare.'),
    (_button("flag_for_review", order={"source": "chosen", "entity": "customer"}),
     'fills "order" — Order objects — from Customer'),
    (_button("flag_for_review", order={"source": "missing", "entity": ""}),
     'fills "order" — Order objects — from nothing it can read'),
    (_button("flag_for_review", order={"source": "ask", "entity": ""}),
     'asks for "order" in its form or fixes it, and "order" is an object of the action\'s'),
    (_button("flag_for_review", order={"source": "value", "entity": ""}),
     'asks for "order" in its form or fixes it'),
    (_button("flag_for_review", order={"source": "chosen", "entity": "order"}, reason={"source": "chosen", "entity": "order"}),
     'fills the value "reason" from objects. A value comes from the form or is fixed.'),
    (_button("flag_for_review", reason={"source": "set", "entity": "order"}),
     'fills the value "reason" from objects'),
    (_button("flag_for_review", order={"source": "chosen", "entity": "order"}, nope={"source": "ask", "entity": ""}),
     "fills 'nope', which \"flag_for_review\" does not take."),
])
def test_a_button_that_cannot_run_as_written_is_refused_and_says_why(no_edits, read, says):
    said = " ".join(wiring.not_resolved("c", _desk(), graph=_graph(), wiring=read))
    assert says in said, said


# ── read through the web's own rules ────────────────────────────────────────────────────────────────────

@needs_rules
def test_the_server_reads_each_set_as_the_web_does_and_each_buttons_sources():
    read = wiring.read(_desk())
    window = {"path": "order_date", "op": "in_last", "value": 14}
    assert read["sets"]["placed"] == {"entity": "order", "segment": "", "filters": [window]}
    assert read["sets"]["active"] == {"entity": "order", "segment": "active_orders", "filters": [window]}
    # a chosen order's lines: the choice stood in for by a probe value — a keep compiles every set and runs none
    assert read["sets"]["lines"] == {"entity": "order_item", "segment": "",
                                     "filters": [{"path": "order_id", "op": "=", "value": "probe"}]}
    assert read["buttons"] == [
        {"element": "buttons", "index": 0, "action": "flag_for_review",
         "params": {"order": {"source": "chosen", "entity": "order"}, "reason": {"source": "ask", "entity": ""}}},
        {"element": "buttons", "index": 1, "action": "flag_for_review",
         "params": {"order": {"source": "ticked", "entity": "order"}, "reason": {"source": "value", "entity": ""}}}]
    assert wiring.read(json.loads(FIXTURE.read_text())) is None             # nothing wired: nothing to read


@needs_rules
def test_the_desk_resolves_and_each_fault_the_web_reads_is_refused_here(no_edits):
    graph = _graph()
    assert wiring.not_resolved("c", _desk(), graph=graph) == []
    ring = _desk(**{"sets.placed": {"label": "Placed", "from": "active"}})
    assert "start from each other in a ring" in " ".join(wiring.not_resolved("c", ring, graph=graph))
    customer = _desk(**{"sets.placed": {"label": "Placed", "entity": "customer"}})
    said = " ".join(wiring.not_resolved("c", customer, graph=graph))
    assert 'fills "order" — Order objects — from Customer' in said, said


# ── the pieces that read a set are probed over it ──────────────────────────────────────────────────────

def test_a_table_reading_a_set_is_probed_over_its_entity_segment_and_conditions(monkeypatch, no_edits):
    _flags(monkeypatch)
    seen = []
    import aughor.semantic.object_query as oq
    real = oq.compile_object_listing
    monkeypatch.setattr(oq, "compile_object_listing", lambda body, graph, **kw: seen.append(body) or real(body, graph, **kw))
    read = _read(active={"entity": "order", "segment": "active_orders",
                         "filters": [{"path": "order_date", "op": "in_last", "value": 14}]})
    spec = {"elements": {"t": {"type": "ObjectTable", "props": {"set": "active", "columns": ["status"]}, "children": []}}}
    assert pieces.not_resolved("c", spec, graph=_graph(), wiring=read) == []
    assert seen == [{"entity": "order", "segment": "active_orders",
                     "filters": [{"path": "order_date", "op": "in_last", "value": 14}], "columns": ["status"],
                     "order_by": "", "descending": False, "limit": 1}]


def test_a_piece_reading_a_set_that_cannot_be_read_is_said_once_by_the_wiring_check(monkeypatch, no_edits):
    _flags(monkeypatch)
    spec = {"elements": {"t": {"type": "ObjectTable", "props": {"set": "gone", "columns": ["status"]}, "children": []}}}
    assert pieces.not_resolved("c", spec, graph=_graph(), wiring=_read(gone={"refused": "This dashboard holds no set named \"gone\"."})) == []


def test_a_figure_and_a_chart_reading_a_set_ask_over_its_segment_and_conditions():
    sets = {"active": {"entity": "order", "segment": "active_orders", "filters": [{"path": "order_date", "op": "in_last", "value": 7}]}}
    [(_, figure)] = pieces._from_object_probes("ObjectFigure", {"set": "active", "label": "Active", "agg": "count"}, sets)
    assert figure == {"object_type": "order", "segment": "active_orders",
                      "filters": [{"path": "order_date", "op": "in_last", "value": 7}],
                      "measures": [{"name": "n", "agg": "count", "path": ""}]}
    [(_, chart)] = pieces._from_object_probes("ObjectChart", {"set": "active", "label": "A", "time": "order_date"}, sets)
    assert chart["object_type"] == "order" and chart["segment"] == "active_orders" and chart["filters"]
    # a piece naming its entity reads as it always did: no segment or conditions it did not say
    [(_, plain)] = pieces._from_object_probes("ObjectFigure", {"entity": "order", "label": "All", "agg": "count"}, sets)
    assert "segment" not in plain and "filters" not in plain


def test_what_a_piece_reads_through_a_set_is_what_a_release_tracks_down_the_sets_it_starts_from():
    spec = _desk()
    spec["sets"]["active"]["segment"] = "active_orders"
    reads = pieces.depends(spec, _graph())
    assert "table" in reads[("entity", "Order")] and "fig-active" in reads[("entity", "Order")]
    assert reads[("entity", "OrderItem")] == ["lines"]
    assert pieces._set_scope(spec, "active") == ("order", "active_orders")
    assert pieces._set_scope(spec, "placed") == ("order", "")
    ring = {"sets": {"a": {"from": "b"}, "b": {"from": "a"}}}
    assert pieces._set_scope(ring, "a") == ("", "")                          # a ring reads nothing, and ends


# ── a person wires a dashboard; a model arranges one ─────────────────────────────────────────────────────

def test_a_new_cockpit_from_a_model_names_no_set_or_value():
    said = wiring.wiring_written(None, _desk(), new=True)
    assert len(said) == 1 and "A new dashboard is wired by a person, by hand." in said[0], said
    assert wiring.wiring_written(None, json.loads(FIXTURE.read_text()), new=True) == []


def test_an_edit_may_leave_the_sets_as_they_were_and_never_change_them():
    before = _desk()
    moved = _desk()
    moved["elements"]["desk"]["children"].reverse()                          # arrangement
    assert wiring.wiring_written(before, moved, new=False) == []
    for change in ({"sets.placed.label": "Placed lately"}, {"values.window.value": 30}, {"sets": None},
                   {"values.month": {"label": "Month", "kind": "days", "value": 30}}):
        said = wiring.wiring_written(before, _desk(**change), new=False)
        assert said and "never change what its pieces read" in said[0], change


def test_a_model_may_not_rewire_a_piece_or_add_buttons():
    before = _desk()
    rewired = _desk(**{"elements.table.props.set": "active"})
    assert "never change what it reads" in " ".join(pieces.pieces_written(before, rewired, new=False))
    no_buttons = _desk()
    del no_buttons["elements"]["buttons"]
    assert pieces.pieces_written(no_buttons, before, new=False) and "never add one" in " ".join(
        pieces.pieces_written(no_buttons, before, new=False))
    assert pieces.title_of("ActionButtons", before["elements"]["buttons"]["props"]) == \
        "Action buttons · Flag this one, Flag the ticked ones"


# ── the keep door ───────────────────────────────────────────────────────────────────────────────────────

@needs_rules
def test_the_keep_door_keeps_a_wired_cockpit_and_refuses_an_undeclared_action(volumes, monkeypatch, no_edits):  # noqa: F811
    tag = uuid.uuid4().hex[:6]
    home = Home(f"wire{tag}", ME, f"desk-{tag}")
    graph = _graph()
    monkeypatch.setattr(pieces, "served_graph", lambda conn: graph)

    def keep(s):
        return versions.keep(home, s, approved_by="user:amit", source="a person's own hand", written_by_model=False)
    _flags(monkeypatch)
    wrong = keep(_desk(**{"elements.buttons.props.buttons": [{"action": "refund", "params": {}}]}))
    assert not wrong.kept and 'runs "refund", which this connection does not declare' in " ".join(wrong.sentences)
    kept = keep(_desk())
    assert kept.kept, kept.sentences
    assert versions.latest(home)["spec"]["sets"]["active"]["segment"] == "active_orders"


@needs_rules
def test_a_models_draft_arranges_a_wired_cockpit_and_never_wires_one(volumes, monkeypatch, no_edits):  # noqa: F811
    """Run through the draft path itself, not read from its source: a model's new dashboard naming sets is refused; an edit
    of a wired dashboard that moves a piece is staged, naming it; one that changes a set is refused."""
    from aughor.dashboards import propose
    tag = uuid.uuid4().hex[:6]
    home = Home(f"wire{tag}", ME, f"desk-{tag}")
    graph = _graph()
    monkeypatch.setattr(pieces, "served_graph", lambda conn: graph)
    _flags(monkeypatch)
    new = propose.draft(home, mode=propose.MODE_NEW, spec=_desk())
    assert not new.staged and any("A new dashboard is wired by a person, by hand." in r for r in new.refusals), new.refusals
    assert versions.keep(home, _desk(), approved_by="user:amit", source="a person's own hand", written_by_model=False).kept
    moved = propose.draft(home, mode=propose.MODE_EDIT, patches=[
        {"op": "move", "from": "/elements/desk/children/4", "path": "/elements/desk/children/0"}])
    assert moved.staged, moved.refusals
    lines = [c["title"] for t in moved.proposal.detail["outline"] for s in t["sections"] for c in s["cards"]]
    assert "Action buttons · Flag this one, Flag the ticked ones" in lines, lines
    rewired = propose.draft(home, mode=propose.MODE_EDIT, patches=[
        {"op": "replace", "path": "/sets/placed/label", "value": "Placed lately"}])
    assert not rewired.staged
    assert any("changes the dashboard's sets or values" in r for r in rewired.refusals), rewired.refusals


def test_a_filter_column_counting_within_a_set_is_probed_over_it_and_one_that_does_not_as_before():
    sets = {"placed": {"entity": "order", "segment": "", "filters": [{"path": "order_date", "op": "in_last", "value": 14}]}}
    props = {"entity": "order", "properties": [{"path": "status", "label": "Status"}]}
    [(_, within)] = pieces._from_object_probes("ObjectFilters", {**props, "set": "placed"}, sets)
    assert within == {"object_type": "order", "filters": [{"path": "order_date", "op": "in_last", "value": 14}], "segment": "",
                      "measures": [{"name": "n", "agg": "count"}], "by": ["status"]}
    [(_, every)] = pieces._from_object_probes("ObjectFilters", props, sets)
    assert every == {"object_type": "order", "measures": [{"name": "n", "agg": "count"}], "by": ["status"]}
