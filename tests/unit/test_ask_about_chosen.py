"""Arc FA, FA-2 — a choice can leave its piece: ticked objects, or a set a piece reads, as a question's subject.

Held on the seeded samples warehouse through the real listing door (`routers.objects.post_object_listing`) and the real
compiler. Off, a subject is not read and contributes nothing — the prose and the receipt are as before. On, the objects
a reader chose are read again as they may see them: by key and title, at most fifty, a chosen object a row policy
withholds dropped and COUNTED, one no object holds counted apart; a set is read from the dashboard's own definition with
the values the page sent, an author's value the author's whatever is sent, and a set past fifty says how many it holds.
The falsifier: a subject that lists an object its reader may not see.
"""
from __future__ import annotations

import asyncio
import shutil
from types import SimpleNamespace

import pytest

from aughor.agent import ask_subject
from aughor.dashboards import validate as V
from aughor.ontology.models import RowPolicy
from aughor.ontology.object_refs import same_type, split_ref
from aughor.routers.investigations import AskFocus, AskRequest, _ask_subject_for, _focus_prose_for
from tests.unit.test_object_actions import CONN, db, graph  # noqa: F401 — fixtures by name

needs_rules = pytest.mark.skipif(shutil.which("node") is None or not V._BUNDLE.exists(),
                                 reason="the dashboard's rules run on node")
SHIPPED = ("shipped", "delivered")


@pytest.fixture
def served(graph, monkeypatch):  # noqa: F811
    monkeypatch.setattr("aughor.routers.ontology.served_ontology_graph", lambda conn, schema=None: graph)
    monkeypatch.setenv("AUGHOR_CANVAS_ASK_ABOUT_CHOSEN", "1")
    return graph


def _keys(db, status: str, n: int) -> list[str]:  # noqa: F811
    rows = db.execute("t", f"SELECT order_id FROM orders WHERE status = '{status}' ORDER BY order_id LIMIT {n}").rows
    return [str(r[0]) for r in rows]


def _count(db, where: str) -> int:  # noqa: F811
    return int(db.execute("t", f"SELECT COUNT(*) FROM orders WHERE {where}").rows[0][0])


# ── off: nothing is read, nothing is said ────────────────────────────────────────────────────────────────────────────

def test_off_a_subject_is_not_read_and_the_turn_is_as_before(monkeypatch):
    monkeypatch.delenv("AUGHOR_CANVAS_ASK_ABOUT_CHOSEN", raising=False)
    focus = AskFocus(kind="objects", objects=["Order:O000123"])
    req = SimpleNamespace(focus=focus, schema_name=None)
    assert ask_subject.resolve(focus, CONN) is None
    assert asyncio.run(_ask_subject_for(req, CONN, None)) is None
    assert _focus_prose_for(req, CONN) == ""                     # no explain call, no prose: a turn with no focus
    assert _focus_prose_for(SimpleNamespace(focus=None), CONN) == ""


def test_the_ask_body_names_what_a_focus_is_about():
    # SP-15's one object is still named by its id
    assert AskRequest(question="q", focus={"kind": "departure", "id": "d1"}).focus.id == "d1"
    with pytest.raises(ValueError):
        AskRequest(question="q", focus={"kind": "departure"})
    with pytest.raises(ValueError):
        AskRequest(question="q", focus={"kind": "objects"})
    with pytest.raises(ValueError):
        AskRequest(question="q", focus={"kind": "set", "dashboard": "desk"})
    with pytest.raises(ValueError):                              # fifty, the most one subject names
        AskRequest(question="q", focus={"kind": "objects", "objects": [f"Order:{i}" for i in range(51)]})
    asked = AskRequest(question="q", focus={"kind": "set", "dashboard": "desk", "set": "late", "values": {"window": 3}})
    assert asked.focus.set == "late" and asked.focus.values == {"window": 3}


def test_one_parser_reads_a_reference_for_an_action_and_a_subject():
    from aughor.actions.executor import ParamError, object_ref
    param = SimpleNamespace(name="order", object_type="Order")
    assert split_ref("Order:O1") == ("Order", "O1") and split_ref("O1", "Order") == ("Order", "O1")
    assert split_ref({"object_type": "order_item", "pk": 7}) == ("order_item", "7")
    assert same_type("OrderItem", "order_item") and not same_type("Order", "Customer")
    assert object_ref({"pk": "O1"}, param) == "Order:O1"
    with pytest.raises(ParamError, match="takes an object of type Order, not Customer"):
        object_ref("Customer:9", param)
    with pytest.raises(ParamError, match="needs an object key"):
        object_ref("Order:", param)


# ── the door: the receipt says the subject, the conversation is handed it; off, both are as before ─────────────────

def _turn(monkeypatch, focus: dict) -> tuple[dict, list[str]]:
    """One `/ask` turn through `_stream_ask` with its bodies stood in for: the route receipt, and the prose the
    conversation was handed."""
    import json

    from aughor.routers import investigations as inv
    handed: list[str] = []
    route = SimpleNamespace(depth="quick", forced=None, mode="", shape="describe",
                            to_event=lambda: {"depth": "quick", "why": "asked quickly"})
    monkeypatch.setattr("aughor.agent.ask_router.decide_ask_route", lambda *a, **k: route)
    monkeypatch.setattr(inv, "_converse_eligible", lambda req, r: True)
    monkeypatch.setattr(inv, "_analyst_eligible", lambda req, r: False)
    monkeypatch.setattr(inv, "_federation_eligible", lambda req: False)
    monkeypatch.setattr(inv, "_overview_eligible", lambda req: False)
    monkeypatch.setattr(inv, "_insight_budget", lambda conn: None)

    async def metered(gen, budget=None):
        async for ev in gen:
            yield ev

    async def converse(question, conn, history, **kw):
        handed.append(kw.get("origin_prose", ""))
        yield inv._sse("headline", {"headline": "ok"})
    monkeypatch.setattr(inv, "_metered_stream", metered)
    monkeypatch.setattr(inv, "_stream_converse", converse)
    req = AskRequest(question="what do these have in common?", connection_id=CONN, depth="quick", focus=focus)

    async def run() -> list[str]:
        return [ev async for ev in inv._stream_ask(req, None, CONN)]
    frames = [json.loads(ev[6:]) for ev in asyncio.run(run()) if ev.startswith("data: ")]
    return next(f for f in frames if f["type"] == "route"), handed


def test_the_turn_says_its_subject_on_the_receipt_and_hands_it_to_the_conversation(served, db, monkeypatch):  # noqa: F811
    keys = _keys(db, "shipped", 2)
    receipt, handed = _turn(monkeypatch, {"kind": "objects", "objects": [f"Order:{k}" for k in keys]})
    assert receipt["subject"] == {"kind": "objects", "said": "About the 2 orders chosen", "shown": 2, "withheld": 0,
                                  "carried": True}
    assert handed[0].startswith("## On screen") and all(k in handed[0] for k in keys)


def test_a_deep_turn_hands_the_subject_to_the_analyst_beside_its_memory(monkeypatch):
    from aughor.routers import investigations as inv
    seen: list = []

    def analyst(conn, question, **kw):
        seen.append(kw.get("extra_context"))
        return SimpleNamespace(report=None, answer="ok", stop_reason="done", steps=[], investigation_id=None,
                               injected_chars=0, reinjection_ratio=0.0, context_timings={})
    monkeypatch.setattr("aughor.agent.analyst.run_analyst", analyst)
    monkeypatch.setattr(inv, "resolve_prior_answers", lambda *a, **k: [])

    async def run(prose: str) -> list[str]:
        return [ev async for ev in inv._stream_analyst("why these?", CONN, [], subject_prose=prose)]
    asyncio.run(run("## On screen\nthe subject"))
    asyncio.run(run(""))
    assert seen[0] == "## On screen\nthe subject"
    assert seen[1] is None                                       # no subject: the analyst's context as before


def test_off_the_turn_is_byte_identical_to_one_with_no_focus(served, db, monkeypatch):  # noqa: F811
    monkeypatch.delenv("AUGHOR_CANVAS_ASK_ABOUT_CHOSEN")
    with_subject, handed = _turn(monkeypatch, {"kind": "objects", "objects": [f"Order:{k}" for k in _keys(db, "shipped", 2)]})
    plain, plain_handed = _turn(monkeypatch, None)
    assert "subject" not in with_subject and handed == plain_handed == [""]
    assert {k: v for k, v in with_subject.items() if k != "trace_id"} == {k: v for k, v in plain.items() if k != "trace_id"}


# ── on: the objects chosen, read again as the reader may see them ────────────────────────────────────────────────────

def test_chosen_objects_are_named_by_key_and_one_that_is_not_there_is_counted(served, db):  # noqa: F811
    keys = _keys(db, "shipped", 3)
    subject = ask_subject.resolve(AskFocus(kind="objects", objects=[f"Order:{k}" for k in keys] + ["order:NOPE"],
                                           label="Late dispatch"), CONN)
    [part] = subject.parts
    assert [o["key"] for o in part.objects] == keys
    assert (part.asked, part.withheld, part.missing) == (4, 0, 1)
    assert subject.words() == "About 3 of the 4 orders chosen · from Late dispatch · 1 is not found"
    prose = subject.prose()
    assert prose.startswith("## On screen") and all(k in prose for k in keys) and "NOPE" not in prose
    assert subject.receipt(carried=True) == {"kind": "objects", "said": subject.words(), "shown": 3, "withheld": 0,
                                             "carried": True}


def test_a_chosen_object_a_row_policy_withholds_is_dropped_and_said_never_listed(served, db, monkeypatch):  # noqa: F811
    from aughor.rbac.groups import add_member, upsert_group
    monkeypatch.setenv("AUGHOR_ONTOLOGY_SECURITY", "1")
    upsert_group("default", "fulfilment", "Fulfilment")
    add_member("default", "fulfilment", "user:ana")
    served.entities["Order"].row_policies = [
        RowPolicy(group="fulfilment", conditions=[{"path": "status", "op": "in", "values": list(SHIPPED)}])]
    monkeypatch.setenv("AUGHOR_LOCAL_USER", "ana")
    hers, not_hers = _keys(db, "shipped", 2), _keys(db, "cancelled", 2)
    subject = ask_subject.resolve(AskFocus(kind="objects", objects=[f"Order:{k}" for k in hers + not_hers]), CONN)
    [part] = subject.parts
    assert [o["key"] for o in part.objects] == hers
    assert (part.withheld, part.missing) == (2, 0)               # withheld, not missing: they exist
    assert subject.words() == "About 2 of the 4 orders chosen · 2 of the 4 are withheld from you"
    prose = subject.prose()
    assert not any(k in prose for k in not_hers)                  # the falsifier: never listed, only counted
    assert any("user:ana" in c for c in subject.said)             # the door's own words for the policy
    # with row policies off, a key the reader cannot list is not there — nothing is said to be withheld
    monkeypatch.delenv("AUGHOR_ONTOLOGY_SECURITY")
    assert ask_subject.resolve(AskFocus(kind="objects", objects=["Order:NOPE"]), CONN).parts[0].withheld == 0


def test_an_entity_the_ontology_does_not_hold_is_said(served):
    subject = ask_subject.resolve(AskFocus(kind="objects", objects=["Widget:1"]), CONN)
    assert subject.parts[0].refused and "Widget" in subject.words()


# ── on: a set, read from the dashboard's own definition ─────────────────────────────────────────────────────────────

def _desk() -> dict:
    # what a set reads, and nothing else a spec holds: the sets and the values
    return {
        "values": {"status": {"label": "Status", "kind": "text", "value": "shipped", "from": {"by": "reader"}},
                   "fixed": {"label": "Fixed", "kind": "text", "value": "delivered"}},
        "sets": {"by_status": {"label": "By status", "entity": "Order",
                               "where": [{"path": "status", "op": "=", "value_from": "status"}]},
                 "delivered": {"label": "Delivered", "entity": "Order",
                               "where": [{"path": "status", "op": "=", "value_from": "fixed"}]},
                 "lines": {"label": "Its lines", "entity": "Order",
                           "linked_to": {"choice": "chosen-customer", "path": "customer_id"}}},
        "elements": {},
    }


@pytest.fixture
def desk(served, monkeypatch):
    from aughor.dashboards import versions
    from aughor.dashboards.home import Home
    mine = Home(CONN, "default", "desk")
    monkeypatch.setattr(versions, "latest", lambda home: {"spec": _desk(), "retired": False} if home == mine else None)
    return served


@needs_rules
def test_a_set_is_read_with_the_readers_value_and_past_fifty_says_how_many_it_holds(desk, db):  # noqa: F811
    focus = AskFocus(kind="set", dashboard="desk", set="by_status", values={"status": "cancelled"})
    subject = ask_subject.resolve(focus, CONN, person="default")
    [part] = subject.parts
    held = _count(db, "status = 'cancelled'")
    assert held > 50 and part.total == held and len(part.objects) == 50
    assert subject.read["filters"] == [{"path": "status", "op": "=", "value": "cancelled"}]
    assert subject.words() == f"About By status · {held:,} orders · the first 50 named"
    # the reader's own filters narrow it, and it says so
    narrowed = ask_subject.resolve(focus.model_copy(update={"filters": [{"path": "payment_method", "op": "=",
                                                                         "value": "card"}]}), CONN, person="default")
    assert narrowed.narrowed and narrowed.words().endswith("narrowed by your filters")
    assert narrowed.parts[0].total == _count(db, "status = 'cancelled' AND payment_method = 'card'")


@needs_rules
def test_an_authors_value_is_the_authors_whatever_a_page_sends(desk, db):  # noqa: F811
    subject = ask_subject.resolve(AskFocus(kind="set", dashboard="desk", set="delivered", values={"fixed": "cancelled"}),
                                  CONN, person="default")
    assert subject.read["filters"] == [{"path": "status", "op": "=", "value": "delivered"}]
    assert subject.parts[0].total == _count(db, "status = 'delivered'")


@needs_rules
def test_a_set_that_cannot_be_read_says_why(desk):
    waits = ask_subject.resolve(AskFocus(kind="set", dashboard="desk", set="lines"), CONN, person="default")
    assert waits.refused == "the set waits on the chosen customer, and the page sent none"
    assert waits.words().startswith("The subject could not be read")
    gone = ask_subject.resolve(AskFocus(kind="set", dashboard="desk", set="nothing"), CONN, person="default")
    assert "holds no set named" in gone.refused
    theirs = ask_subject.resolve(AskFocus(kind="set", dashboard="other", set="by_status"), CONN, person="default")
    assert theirs.refused == "this dashboard is not one you can read, or it was retired"
