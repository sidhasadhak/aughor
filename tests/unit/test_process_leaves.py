"""Arc OC-4 — a process says how an object leaves it, and a promise stops counting it as open (ROADMAP §3.56).

Found on theLook's live receipt (2026-10-09): of the 43,777 orders the dispatch promise counted *open and overdue*,
18,726 were Cancelled — they had left the process, and a late dispatch cockpit would have listed them as late. A
process now declares how an object leaves it (`leaves`: a property and the values that mean gone); one that left
still counts toward the stages it reached, and is no longer open or overdue — in the measurement, in the overdue
segment and so on the board and in the table alike. Every number is held to a hand-written query over the seeded
samples warehouse, whose cancelled and refunded orders shipped and were never delivered.
"""
from __future__ import annotations

import copy

import pytest

from aughor.ontology.processes import describe_process, process_entry, process_fields, process_spec_problem, \
    resolve_process
from tests.unit import test_object_listing as _listing
from tests.unit.test_object_listing import listing, run, total
from tests.unit.test_object_processes import FULFILMENT, declare
from tests.unit.test_object_processes import _isolated_overrides  # noqa: F401 — an autouse fixture, by name

db, graph = _listing.db, _listing.graph            # the samples warehouse and its measured graph, as the listing tests have them

GONE = {"property": "status", "values": ["cancelled", "refunded"]}


def _leaving(**over) -> dict:
    spec = copy.deepcopy(FULFILMENT)
    spec["leaves"] = {**GONE, **over}
    return spec


def ints(db, sql: str) -> list[int]:
    return [int(v) for v in run(db, sql)[0]]


def test_who_left_is_counted_and_is_no_longer_open_or_overdue(db, graph, monkeypatch):
    _, before = declare(copy.deepcopy(graph), db, FULFILMENT)
    _, after = declare(graph, db, _leaving())
    left, = ints(db, "SELECT COUNT(*) FROM ecommerce.orders WHERE status IN ('cancelled', 'refunded')")
    assert (after.leaves.left, after.leaves.missing, after.leaves.unknown) == (left, [], 0)
    was, now = before.stages[2].promise, after.stages[2].promise          # delivered within 5 days of shipped
    gone, = ints(db, "SELECT COUNT(*) FROM ecommerce.orders WHERE shipped_at IS NOT NULL AND delivered_at IS NULL "
                     "AND status IN ('cancelled', 'refunded')")
    assert was.open == gone and was.open_overdue == gone                  # every one of them was counted late
    assert (now.open, now.open_overdue) == (0, None)                      # they left: nothing is waiting
    assert (now.reached, now.breached) == (was.reached, was.breached)    # what was reached and broken stands
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: name == "ontology.cockpit_pieces")
    assert total(db, listing(graph, segment="overdue_delivery")) == 0     # the board and the table say the same


def test_a_promise_kept_per_line_reads_leaving_through_the_link_to_its_order(db, graph):
    _, before = declare(copy.deepcopy(graph), db, FULFILMENT)
    _, after = declare(graph, db, _leaving(values=["cancelled", "refunded", "pending"]))
    lines = ("SELECT COUNT(*) FROM ecommerce.order_items i LEFT JOIN ecommerce.orders o ON o.order_id = i.order_id "
             "WHERE o.shipped_at IS NULL AND i.ship_by IS NOT NULL")
    still, = ints(db, lines + " AND o.status NOT IN ('cancelled', 'refunded', 'pending')")
    every, = ints(db, lines)
    assert before.stages[1].promise.open == every and after.stages[1].promise.open == still < every


def test_a_value_no_object_holds_is_said(db, graph):
    _, p = declare(graph, db, _leaving(values=["cancelled", "Cancelled"]))
    assert p.leaves.missing == ["Cancelled"] and "check the spelling the data uses" in p.leaves.note


@pytest.mark.parametrize("leaves, says", [
    ({"values": ["x"]}, "`leaves` names how an object leaves the process"),
    ({"property": "status", "values": []}, "from 1 to 50 values"),
    ({"property": "status", "values": ["x"] * 51}, "from 1 to 50 values"),
])
def test_a_malformed_leaving_is_refused_by_shape(leaves, says):
    spec = copy.deepcopy(FULFILMENT)
    spec["leaves"] = leaves
    assert says in process_spec_problem(spec)


def test_a_leaving_read_from_a_moment_or_nothing_is_refused_against_the_graph(graph):
    for prop, says in (("order_date", "is a moment"), ("no_such", "no property 'no_such'")):
        problem, _ = resolve_process(graph, "order_fulfilment", process_fields(_leaving(property=prop)))
        assert says in problem, problem


def test_a_process_no_object_leaves_is_stored_and_described_exactly_as_before(db, graph):
    fields, p = declare(graph, db, FULFILMENT)
    assert "leaves" not in fields and "leaves" not in process_entry(fields, p)["measured"]
    assert "leaves" not in describe_process(graph, p)
    fields, p = declare(graph, db, _leaving())
    assert fields["leaves"] == GONE and describe_process(graph, p)["leaves"]["left"] == p.leaves.left


# ── through the door ────────────────────────────────────────────────────────────────────────

from tests.unit.test_object_processes import PARAMS, door  # noqa: E402,F401 — the door's fixture, by name


def test_the_door_carries_how_an_object_leaves_and_counts_it(door, client):  # noqa: F811
    """The live receipt sent `leaves` to the door, and the door's request model dropped it: every count stayed as if
    nothing left. The functions were tested; the door was not (the same as `within_hours`, ON-9)."""
    r = client.post("/ontology/processes", params=PARAMS, json=_leaving())
    assert r.status_code == 200, r.text
    process = r.json()["process"]
    assert process["leaves"]["property"] == "status" and process["leaves"]["left"] > 0
    listed = {p["id"]: p for p in client.get("/ontology/processes", params=PARAMS).json()["processes"]}
    assert listed["order_fulfilment"]["leaves"]["values"] == ["cancelled", "refunded"]
    delivery = listed["order_fulfilment"]["stages"][2]["promise"]
    assert delivery["open"] == 0                                         # every shipped-and-undelivered one left
