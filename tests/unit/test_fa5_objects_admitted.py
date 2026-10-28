"""Arc FA, FA-5 — act on each object a rule admits (ROADMAP §3.60).

Held on the seeded samples warehouse through the real compiler: a rule `pending_orders` (status = pending) is
declared and measured, an automation watches it, and the warehouse is changed between checks — orders made pending
enter, pending orders moved on leave. Every count is held to a hand-written query. The user's two calls (2026-10-26)
are the spine: the first check records who is already in and says so without firing, and the listing runs under the
row policy of the person who saved the automation, what it withholds said.
"""
from __future__ import annotations

import duckdb
import pytest

from aughor.automations import admitted as A
from aughor.automations.dataflow import FanRefused, fan_items, withheld_list
from aughor.automations.models import Automation, Condition, Effect, EffectOutcome, ForEach
from aughor.db.connection import open_connection
from aughor.ontology import overrides as OV
from tests.unit.test_object_bindings import seed
from tests.unit.test_object_processes import _DEADLINES, FULFILMENT, declare, declare_rule, fresh_graph

CONN = "fa5-admitted-t"
PENDING = {"id": "pending_orders", "entity": "Order", "kind": "condition",
           "conditions": [{"path": "status", "op": "=", "value": "pending"}]}


# ── the warehouse, the graph, and the seams the probe reads through ─────────────────────────────────────────────────

@pytest.fixture
def warehouse(tmp_path):
    path = tmp_path / "samples.duckdb"
    seed(path)
    con = duckdb.connect(str(path))
    con.execute(_DEADLINES)                                  # the shipping promise's deadline, as the process tests have it
    con.close()
    return path


#: The automation id each test watches under — fresh per test, because the automations store is the suite's one
#: hermetic database, and a record left by another test would answer "none new" to this one's first check.
_ID: list[str] = ["fa5-auto"]


@pytest.fixture(autouse=True)
def _fresh_id():
    import uuid
    _ID[0] = f"fa5-{uuid.uuid4().hex[:10]}"


def _open(path):
    return open_connection("duckdb", str(path), schema_name="ecommerce", connection_id=CONN)


def sql(path, statement: str) -> list[tuple]:
    con = duckdb.connect(str(path))
    try:
        return con.execute(statement).fetchall()
    finally:
        con.close()


def pending(path) -> set[str]:
    return {r[0] for r in sql(path, "SELECT order_id FROM ecommerce.orders WHERE status = 'pending'")}


@pytest.fixture
def graph(warehouse, tmp_path, monkeypatch):
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")
    monkeypatch.setattr(OV, "_DRAFT_ROOT", tmp_path / "ontology_overrides_draft")
    g = fresh_graph()
    db = _open(warehouse)
    try:
        declare_rule(g, db, PENDING)
    finally:
        db.close()
    monkeypatch.setattr(A, "_graph_for", lambda conn_id, cond: g)
    monkeypatch.setattr(A, "_open_for", lambda conn_id, graph, cond: _open(warehouse))
    monkeypatch.setattr(A, "_edits", lambda conn_id: [])
    with A._STASH_LOCK:
        A._STASH.clear()
    return g


def watch(segment: str = "pending_orders", effects=None, **kw) -> Automation:
    return Automation(id=kw.pop("id", _ID[0]), conn_id=CONN, name="act on pending orders",
                      conditions=[Condition(kind="objects_admitted", config={"entity": "Order", "segment": segment})],
                      effects=effects or [Effect(kind="notify", config={"trigger_id": "t1"})],
                      declared_by=kw.pop("declared_by", "user:ana"), **kw)


def check(automation: Automation):
    return A.evaluate_admitted_condition(automation.conditions[0], automation)


def target(automation: Automation) -> str:
    return A.target_of(automation.conditions[0], CONN)


def make_pending(path, *order_ids: str) -> None:
    ids = ", ".join(f"'{o}'" for o in order_ids)
    sql(path, f"UPDATE ecommerce.orders SET status = 'pending' WHERE order_id IN ({ids})")


def not_pending(path, n: int) -> list[str]:
    return [r[0] for r in sql(path, f"SELECT order_id FROM ecommerce.orders WHERE status = 'delivered' "
                                    f"ORDER BY order_id LIMIT {n}")]


def test_a_chain_without_the_trigger_runs_exactly_as_before(graph, monkeypatch):
    """The engine's only new work is a commit that returns at once when no condition is this kind."""
    from aughor.automations.engine import run_automation
    monkeypatch.setattr(A, "_graph_for", lambda *_a: pytest.fail("the ontology was read"))
    for touched in ("add_admitted", "get_admitted_keys", "record_admitted", "drop_admitted"):
        monkeypatch.setattr(f"aughor.automations.store.{touched}", lambda *_a, **_k: pytest.fail("keys were touched"))
    seen: list = []

    def dispatch(effect, automation):
        seen.append(effect.config["trigger_id"])
        return EffectOutcome(kind=effect.kind, target="t1", status="executed")

    auto = Automation(id="fa5-plain", conn_id=CONN, name="plain",
                      conditions=[Condition(kind="schedule", config={"cron": "0 9 * * *"})],
                      effects=[Effect(kind="notify", config={"trigger_id": "t1"})])
    run = run_automation(auto, dispatch=dispatch, persist=False, manual=True)
    assert run.outcome == "fired" and seen == ["t1"]
    assert run.reason == "schedule(0 9 * * *): run now, by hand"


# ── the user's call 1: the first check records, a later one fires ───────────────────────────────────────────────────

def test_the_first_check_records_who_is_already_in_and_says_so_without_firing(graph, warehouse):
    from aughor.automations.store import get_admitted_keys
    auto = watch()
    fired, detail, payload = check(auto)
    want = pending(warehouse)
    assert len(want) > 50                                            # a real population, not a fixture of three
    assert (fired, payload) == (False, {})
    assert f"first check — {len(want):,} already in, none new; recorded, not fired" in detail
    assert get_admitted_keys(auto.id, target(auto)) == want
    fired, detail, _ = check(auto)                                    # nothing entered since
    assert not fired and f"none new ({len(want):,} in)" in detail


def test_an_object_that_enters_afterwards_fires_once_with_its_key(graph, warehouse):
    auto = watch()
    check(auto)
    fresh = not_pending(warehouse, 2)
    make_pending(warehouse, *fresh)
    fired, detail, payload = check(auto)
    assert fired and "2 newly admitted" in detail
    assert payload["admitted"] == sorted(fresh) and payload["count"] == 2 and payload["left"] == 0
    assert payload["entity"] == "order" and payload["segment"] == "pending_orders"
    assert payload["said"].startswith("2 order objects entered pending_orders")
    A.commit_admitted(auto)                                           # what the engine does after a fired tick
    fired, detail, _ = check(auto)
    assert not fired and "none new" in detail


def test_through_the_engine_each_admitted_key_is_one_step_and_the_next_tick_is_quiet(graph, warehouse):
    from aughor.automations.engine import run_automation
    sent: list = []

    def dispatch(effect, automation):
        sent.append(effect.config.get("message"))
        return EffectOutcome(kind=effect.kind, target="t1", status="executed")

    per_key = Effect(kind="notify", config={"trigger_id": "t1", "message": {"$from": "item.value"}},
                     for_each=ForEach(source={"$from": "trigger.admitted"}))
    auto = watch(effects=[per_key])
    first = run_automation(auto, dispatch=dispatch, persist=False)
    assert first.outcome == "not_fired" and "already in, none new" in first.reason and sent == []
    fresh = not_pending(warehouse, 3)
    make_pending(warehouse, *fresh)
    second = run_automation(auto, dispatch=dispatch, persist=False)
    assert second.outcome == "fired", second.reason
    assert sent == sorted(fresh)
    third = run_automation(auto, dispatch=dispatch, persist=False)
    assert third.outcome == "not_fired" and "none new" in third.reason and len(sent) == 3


def test_an_arrival_held_back_by_another_condition_is_not_swallowed(graph, warehouse):
    """`all` with a false second condition: the arrival is seen, not fired, and stays new until a tick fires."""
    from aughor.automations.engine import run_automation
    auto = watch()
    auto = auto.model_copy(update={"conditions": auto.conditions + [
        Condition(kind="webhook", config={})], "condition_logic": "all"})
    run_automation(auto, dispatch=lambda e, a: EffectOutcome(kind=e.kind, status="executed"), persist=False)
    fresh = not_pending(warehouse, 1)
    make_pending(warehouse, *fresh)
    quiet = run_automation(auto, dispatch=lambda e, a: EffectOutcome(kind=e.kind, status="executed"),
                           persist=False)
    assert quiet.outcome == "not_fired"                                # the webhook was not called
    fired, _, payload = check(auto)
    assert fired and payload["admitted"] == fresh                    # still new


# ── withheld, left, capped ──────────────────────────────────────────────────────────────────────────────────────────

def test_more_than_fifty_arrivals_are_withheld_and_their_count_said(graph, warehouse):
    auto = watch()
    check(auto)
    make_pending(warehouse, *not_pending(warehouse, 60))
    fired, _, payload = check(auto)
    assert fired and payload["count"] == 60
    assert isinstance(payload["admitted"], dict) and payload["admitted"]["withheld"] == 60
    assert "more than the 50 a step runs once per, so their keys are withheld" in payload["admitted"]["said"]


def test_a_for_each_over_a_withheld_list_is_refused_with_its_sentence_never_run_as_empty(graph, warehouse):
    from aughor.automations.dataflow import FAN_EMPTY_SKIP
    from aughor.automations.engine import run_automation
    sent: list = []
    per_key = Effect(kind="notify", config={"trigger_id": "t1", "message": {"$from": "item.value"}},
                     for_each=ForEach(source={"$from": "trigger.admitted"}))
    auto = watch(effects=[per_key])
    run_automation(auto, dispatch=lambda e, a: sent.append(e) or EffectOutcome(kind=e.kind, status="executed"),
                   persist=False)
    make_pending(warehouse, *not_pending(warehouse, 60))
    run = run_automation(auto, dispatch=lambda e, a: sent.append(e) or EffectOutcome(kind=e.kind, status="executed"),
                         persist=False)
    assert run.outcome == "fired" and sent == []
    (step,) = run.effects
    assert step.status == "invalid_params" and FAN_EMPTY_SKIP not in step.message
    assert "for_each over a withheld list is refused — 60 order objects entered pending_orders" in step.message


def test_the_dataflow_refuses_a_withheld_list_and_still_runs_a_real_one():
    step = Effect(kind="notify", config={"trigger_id": "t1"}, for_each=ForEach(source={"$from": "trigger.admitted"}))
    with pytest.raises(FanRefused, match="withheld list is refused — 70 arrived"):
        fan_items(step, {"trigger": {"admitted": withheld_list(70, "70 arrived")}})
    assert fan_items(step, {"trigger": {"admitted": ["O1", "O2"]}}) == ["O1", "O2"]
    assert fan_items(step, {"trigger": {"admitted": []}}) == []                    # a real empty list stays one


def test_objects_that_left_are_dropped_and_counted_and_one_that_returns_is_new_again(graph, warehouse):
    from aughor.automations.store import get_admitted_keys
    auto = watch()
    check(auto)
    leaving = sorted(pending(warehouse))[:3]
    ids = ", ".join(f"'{o}'" for o in leaving)
    sql(warehouse, f"UPDATE ecommerce.orders SET status = 'processing' WHERE order_id IN ({ids})")
    fired, detail, _ = check(auto)
    assert not fired and ", 3 left)" in detail
    assert not (set(leaving) & get_admitted_keys(auto.id, target(auto)))
    make_pending(warehouse, leaving[0])
    fired, _, payload = check(auto)
    assert fired and payload["admitted"] == [leaving[0]]


def test_above_the_cap_the_check_says_too_many_to_track_and_records_nothing(graph, warehouse, monkeypatch):
    from aughor.automations.store import get_admitted_keys, get_probe_baseline
    monkeypatch.setattr(A, "MAX_TRACKED", 100)
    auto = watch()
    fired, detail, payload = check(auto)
    n = len(pending(warehouse))
    assert (fired, payload) == (False, {})
    assert f"too many to track ({n:,}) — at most 100 objects are tracked, so nothing fired" in detail
    assert get_probe_baseline(auto.id, target(auto)) is None and get_admitted_keys(auto.id, target(auto)) == set()


# ── the user's call 2: listed as the person who saved it ────────────────────────────────────────────────────────────

@pytest.fixture
def secured(graph, monkeypatch):
    from aughor.ontology.models import RowPolicy
    from aughor.rbac.groups import add_member, upsert_group
    monkeypatch.setenv("AUGHOR_ONTOLOGY_SECURITY", "1")
    upsert_group("default", "cards", "Cards")
    add_member("default", "cards", "user:ana")
    graph.entities["Order"].row_policies = [
        RowPolicy(group="cards", conditions=[{"path": "payment_method", "op": "=", "value": "card"}])]
    return graph


def test_the_owner_s_row_policy_holds_and_what_it_withholds_is_said(secured, warehouse, monkeypatch):
    from aughor.automations.store import get_admitted_keys
    monkeypatch.setenv("AUGHOR_LOCAL_USER", "ben")       # the install's operator is someone else — never read as
    auto = watch(declared_by="user:ana")
    fired, detail, _ = check(auto)
    ana = {r[0] for r in sql(warehouse, "SELECT order_id FROM ecommerce.orders "
                                        "WHERE status = 'pending' AND payment_method = 'card'")}
    assert ana and ana < pending(warehouse)
    assert get_admitted_keys(auto.id, target(auto)) == ana
    assert f"{len(ana):,} already in" in detail and "listed as user:ana, who saved it" in detail
    assert "only the Order objects user:ana may see are shown — cards: payment_method = card" in detail
    hidden, shown = (r[0] for r in (
        sql(warehouse, "SELECT order_id FROM ecommerce.orders WHERE status = 'delivered' AND payment_method = 'crypto' "
                       "ORDER BY order_id LIMIT 1")[0],
        sql(warehouse, "SELECT order_id FROM ecommerce.orders WHERE status = 'delivered' AND payment_method = 'card' "
                       "ORDER BY order_id LIMIT 1")[0]))
    make_pending(warehouse, hidden, shown)
    fired, _, payload = check(auto)
    assert fired and payload["admitted"] == [shown]                  # the one ana may not see never reaches her chain
    assert "only the Order objects user:ana may see are shown" in payload["said"]


def test_a_reader_in_no_group_lists_none_and_is_told_which_groups_would(secured, warehouse):
    fired, detail, _ = check(watch(declared_by="user:carl"))
    assert not fired and "0 already in" in detail
    assert "user:carl is in none of its groups (cards)" in detail


def test_an_automation_that_records_no_one_is_listed_as_the_operator_and_says_so(graph, monkeypatch):
    monkeypatch.setenv("AUGHOR_LOCAL_USER", "operator-o")
    _, detail, _ = check(watch(declared_by=""))
    assert "listed as user:operator-o, this install's operator — the automation records no one who saved it" in detail


def test_a_changed_row_policy_records_afresh_instead_of_firing_for_what_became_visible(secured, warehouse):
    auto = watch(declared_by="user:ana")
    check(auto)
    from aughor.ontology.models import RowPolicy
    secured.entities["Order"].row_policies = [
        RowPolicy(group="cards", conditions=[{"path": "payment_method", "op": "in", "values": ["card", "paypal"]}])]
    fired, detail, payload = check(auto)
    assert (fired, payload) == (False, {}) and "who it is listed for changed" in detail and "already in" in detail


# ── what the record is taken against ────────────────────────────────────────────────────────────────────────────────

def test_a_changed_rule_records_afresh_without_firing(graph, warehouse):
    auto = watch()
    check(auto)
    db = _open(warehouse)
    try:
        declare_rule(graph, db, {**PENDING, "conditions": [{"path": "status", "op": "in",
                                                            "values": ["pending", "processing"]}]})
    finally:
        db.close()
    fired, detail, payload = check(auto)
    n = int(sql(warehouse, "SELECT COUNT(*) FROM ecommerce.orders WHERE status IN ('pending', 'processing')")[0][0])
    assert (fired, payload) == (False, {})
    assert f"its segment's definition changed — {n:,} already in, none new; recorded, not fired" in detail


def test_an_overdue_segment_is_defined_by_its_promise_not_by_the_moment_it_was_measured(graph, warehouse):
    db = _open(warehouse)
    try:
        _, process = declare(graph, db, FULFILMENT)
    finally:
        db.close()
    order = graph.entities["Order"]
    before = A.definition_of(graph, order, "overdue_delivery")
    assert before["overdue"] == "order_fulfilment"
    process.stages[2].promise.as_of = "2031-01-01"                    # measured again, later: objects enter
    assert A.definition_of(graph, order, "overdue_delivery") == before
    process.stages[2].promise.within_days = 9                         # the promise itself changed: the rule did
    assert A.definition_of(graph, order, "overdue_delivery") != before


def test_taking_the_trigger_off_takes_its_record_and_deleting_takes_the_rest(graph):
    from aughor.automations.store import (delete_automation, get_admitted_keys, get_probe_baseline,
                                          upsert_automation)
    auto = upsert_automation(watch())
    check(auto)
    assert get_admitted_keys(auto.id, target(auto))
    upsert_automation(auto.model_copy(update={"conditions": [Condition(kind="schedule", config={"cron": "0 9 * * *"})]}))
    assert get_admitted_keys(auto.id, target(auto)) == set() and get_probe_baseline(auto.id, target(auto)) is None
    upsert_automation(auto)
    _, detail, _ = check(auto)
    assert "first check" in detail                                    # put back, it records afresh
    delete_automation(auto.id)
    assert get_admitted_keys(auto.id, target(auto)) == set()


# ── the doors ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_withdrawing_a_watched_rule_segment_process_or_entity_is_refused(graph, warehouse):
    from aughor.ontology.compatibility import classify
    from aughor.ontology.dependents import dependents_of, refusal
    from aughor.ontology.models import Segment
    db = _open(warehouse)
    try:
        declare(graph, db, FULFILMENT)
    finally:
        db.close()
    graph.entities["Order"].segments["big"] = Segment(id="big", display_name="Big orders",
                                                      filter_sql="total_amount > 400", verified=True)
    autos = [watch(id="on-rule"), watch("Big orders", id="on-segment"), watch("overdue_delivery", id="on-process")]
    rows = dependents_of(graph, CONN, "rule", "pending_orders", automations=autos)
    assert [r["id"] for r in rows] == ["on-rule"]
    assert rows[0]["how"] == "its trigger acts on the Order objects 'pending_orders' admits"
    assert "rule 'pending_orders' is not withdrawn" in refusal("rule", "pending_orders", rows)
    assert classify("rule", {"entity": "Order"}, None, dependents=rows)[0] == "ERR"
    assert [r["id"] for r in dependents_of(graph, CONN, "object_set", "Order::big", automations=autos)] == ["on-segment"]
    assert "on-process" in [r["id"] for r in dependents_of(graph, CONN, "process", "order_fulfilment",
                                                           automations=autos)]
    on_entity = {r["id"] for r in dependents_of(graph, CONN, "entity", "Order", automations=autos)}
    assert {"on-rule", "on-segment", "on-process"} <= on_entity
    assert dependents_of(graph, CONN, "rule", "some_other_rule", automations=autos) == []


def test_the_save_door_refuses_a_segment_it_cannot_list(graph, client):
    body = {"conn_id": CONN, "name": "act", "effects": [{"kind": "notify", "config": {"trigger_id": "t1"}}],
            "conditions": [{"kind": "objects_admitted", "config": {"entity": "Order", "segment": "pending_orders"}}]}
    unknown = {**body, "conditions": [{"kind": "objects_admitted",
                                       "config": {"entity": "Order", "segment": "no_such_rule"}}]}
    refused = client.post("/automations", json=unknown)
    assert refused.status_code == 422 and "has no segment 'no_such_rule'" in refused.text
    made = client.post("/automations", json=body)
    assert made.status_code == 200, made.text
    assert client.delete(f"/automations/{made.json()['id']}").status_code == 200


def test_the_palette_offers_it_ready_only_where_a_segment_can_be_watched(monkeypatch):
    from aughor.automations.palette import NEEDS_SETUP, READY, entries
    monkeypatch.setattr(A, "watchable_segments", lambda conn_id: 1)
    row = next(r for r in entries("c1") if r["kind"] == "objects_admitted")
    assert (row["group"], row["label"], row["availability"]) == ("trigger", "Objects admitted", READY)
    monkeypatch.setattr(A, "watchable_segments", lambda conn_id: 0)
    row = next(r for r in entries("c1") if r["kind"] == "objects_admitted")
    assert row["availability"] == NEEDS_SETUP and "No rule or segment" in row["reason"]


def test_the_client_offers_the_same_words_and_the_canvas_names_the_trigger():
    from pathlib import Path

    from aughor.automations.graph import condition_label
    from aughor.automations.palette import ENTRIES
    web = Path(__file__).resolve().parents[2] / "web"
    rows = (web / "components" / "automations" / "AutomationRows.tsx").read_text()
    entry = next(e for e in ENTRIES if e.kind == "objects_admitted")
    assert f'value: "{entry.kind}", label: "{entry.label}"' in rows
    assert condition_label(watch().conditions[0]) == "objects_admitted · Order · pending_orders"
    assert watch().conditions[0].describe() == "objects_admitted(Order.pending_orders)"


def test_the_trigger_publishes_its_keys_and_a_typo_is_refused_at_save():
    ok = watch(effects=[Effect(kind="notify", config={"trigger_id": "t1", "message": {"$from": "trigger.said"}})])
    assert ok.effects[0].config["message"] == {"$from": "trigger.said"}
    with pytest.raises(Exception, match="trigger publishes"):
        watch(effects=[Effect(kind="notify", config={"trigger_id": "t1", "message": {"$from": "trigger.keys"}})])
    with pytest.raises(Exception, match="requires config key"):
        Condition(kind="objects_admitted", config={"entity": "Order"})
