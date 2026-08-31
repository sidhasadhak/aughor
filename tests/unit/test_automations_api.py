"""Automations API (Wave A) — the flag gate and the CRUD contract.

Two things worth locking at the HTTP boundary: with ``automations.engine`` off the whole surface
404s (so the default install is byte-identical), and a malformed condition/effect is rejected with
a 422 at CREATE — never stored, so a broken automation cannot sit in the DB looking schedulable.

``GET /automations/{id}/runs`` gets its own test because it is the endpoint the subsystem exists
for: the monitor API has no equivalent, since ``monitor_alerts`` records only the ticks that fired.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aughor.api import app
from aughor.automations.models import AutomationRun
from aughor.automations.store import append_run

client = TestClient(app)

BODY = {
    "conn_id": "conn-api",
    "name": "Refund watch",
    "conditions": [{"kind": "schedule", "config": {"cron": "0 8 * * 1"}}],
    "effects": [{"kind": "notify", "config": {"trigger_id": "trig-1"}}],
}


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled",
                        lambda n: n == "automations.engine")


def test_create_list_get_delete_round_trip(flag_on):
    created = client.post("/automations", json=BODY)
    assert created.status_code == 200
    aid = created.json()["id"]
    assert created.json()["name"] == "Refund watch"

    listed = client.get("/automations", params={"conn_id": "conn-api"})
    assert aid in [a["id"] for a in listed.json()["automations"]]

    assert client.get(f"/automations/{aid}").json()["conn_id"] == "conn-api"
    assert client.delete(f"/automations/{aid}").status_code == 200
    assert client.get(f"/automations/{aid}").status_code == 404


@pytest.mark.parametrize("patch", [
    {"conditions": [{"kind": "schedule", "config": {}}]},                    # cron missing
    {"effects": [{"kind": "kinetic_action", "config": {"params": {}}}]},     # action_id missing
    {"conditions": []},                                                      # none at all
])
def test_a_malformed_automation_is_rejected_at_create_and_never_stored(flag_on, patch):
    body = {**BODY, **patch}
    resp = client.post("/automations", json=body)
    assert resp.status_code == 422
    # Nothing was persisted by the rejected call.
    listed = client.get("/automations", params={"conn_id": "conn-api"}).json()["automations"]
    assert all(a["name"] != "Refund watch" or a["conditions"] for a in listed)


def test_pause_and_enable_toggles(flag_on):
    aid = client.post("/automations", json={**BODY, "conn_id": "conn-api-toggle"}).json()["id"]

    paused = client.post(f"/automations/{aid}/pause", json={"until": "2027-01-01T00:00:00Z"})
    assert paused.json()["paused_until"] == "2027-01-01T00:00:00Z"
    assert client.post(f"/automations/{aid}/pause", json={"until": None}).json()["paused_until"] is None

    assert client.post(f"/automations/{aid}/enabled", params={"enabled": False}).json()["enabled"] is False


def test_runs_endpoint_returns_the_ticks_that_did_nothing(flag_on):
    """The reason this API exists — a quiet tick is data, not absence."""
    aid = client.post("/automations", json={**BODY, "conn_id": "conn-api-runs"}).json()["id"]
    append_run(AutomationRun(automation_id=aid, conn_id="conn-api-runs",
                             outcome="gated", reason="muted until 2027-01-01T00:00:00Z"))
    append_run(AutomationRun(automation_id=aid, conn_id="conn-api-runs",
                             outcome="not_fired", reason="metric(mon-7): no alert"))

    runs = client.get(f"/automations/{aid}/runs").json()["runs"]
    assert {r["outcome"] for r in runs} == {"gated", "not_fired"}
    assert any("muted until" in r["reason"] for r in runs)


def test_run_now_returns_the_reason_a_gated_automation_did_nothing(flag_on):
    """An operator asking 'why isn't this firing?' gets the reason, not silence."""
    aid = client.post("/automations", json={
        **BODY, "conn_id": "conn-api-run", "enabled": False}).json()["id"]
    resp = client.post(f"/automations/{aid}/run")
    assert resp.status_code == 200
    assert resp.json()["outcome"] == "gated"
    assert resp.json()["reason"] == "disabled"


def test_run_now_on_an_unknown_automation_is_404(flag_on):
    assert client.post("/automations/nope/run").status_code == 404


# ── W1 · the guard, over the wire ────────────────────────────────────────────────

def test_the_guard_operators_come_from_the_code(flag_on):
    """FETCHED, never mirrored. A picker that offered an operator the engine cannot
    evaluate would fail on a schedule, at 09:00, with nobody watching — the same
    argument the per-kind ports are fetched by."""
    from aughor.automations.dataflow import GUARD_OPS, UNARY_OPS

    ops = client.get("/automations/vocabulary").json()["guard_ops"]
    assert [o["op"] for o in ops] == list(GUARD_OPS)
    assert {o["op"] for o in ops if o["unary"]} == set(UNARY_OPS)
    # Every operator carries the word it READS as: "is set" is what a person authors
    # against, `truthy` is what the engine evaluates, and only one of them belongs on
    # a surface.
    assert all(o["label"] for o in ops)


def test_a_guarded_step_round_trips_through_create(flag_on):
    """`when` must survive the wire. A field the API drops is a chain that silently
    always fires — the same class of defect as the form that dropped `alias`."""
    body = dict(BODY, effects=[
        {"kind": "investigate", "alias": "numbers", "config": {"question": "how were sales?"}},
        {"kind": "notify", "config": {"trigger_id": "trig-1"},
         "when": [{"left": {"$from": "numbers.answer"}, "op": "truthy"}],
         "when_logic": "any"},
    ])
    created = client.post("/automations", json=body)
    assert created.status_code == 200, created.text
    stored = client.get(f"/automations/{created.json()['id']}").json()
    assert stored["effects"][1]["when"] == [
        {"left": {"$from": "numbers.answer"}, "op": "truthy", "right": None}]
    assert stored["effects"][1]["when_logic"] == "any"
    client.delete(f"/automations/{created.json()['id']}")


def test_a_guard_onto_an_unknown_step_is_422_not_stored(flag_on):
    """The plane's own rule (K1): reject at parse, never surface. A guard naming a step
    that does not exist is refused here, not discovered on a schedule."""
    body = dict(BODY, effects=[
        {"kind": "notify", "config": {"trigger_id": "t"},
         "when": [{"left": {"$from": "ghost.answer"}, "op": "truthy"}]},
    ])
    assert client.post("/automations", json=body).status_code == 422


# ── B2 · the dry run ─────────────────────────────────────────────────────────────

DRY_CHAIN = {
    "conn_id": "conn-dry",
    "name": "Preview me",
    "conditions": [{"kind": "schedule", "config": {"cron": "0 9 * * *"}}],
    "effects": [
        {"kind": "investigate", "alias": "numbers", "config": {"question": "how were sales?"}},
        {"kind": "slack_post", "config": {"bot_id": "b1", "channel": "#ops",
                                          "message": {"$from": "numbers.answer"}},
         "when": [{"left": {"$from": "numbers.answer"}, "op": "truthy"}]},
    ],
}


def test_an_UNSAVED_draft_can_be_previewed(flag_on):
    """The state a design spends all of its life in before it goes live: not stored, not
    armed, not due. A preview that needed any of those would answer nothing."""
    r = client.post("/automations/dry-run", json=DRY_CHAIN)
    assert r.status_code == 200, r.text
    run = r.json()["run"]
    assert run["outcome"] == "fired"
    assert "nothing was sent" in run["reason"]
    assert [e["status"] for e in run["effects"]] == ["executed", "executed"]


def test_the_chain_FLOWS_in_a_preview(flag_on):
    """The measured reason the existing inert dispatcher could not be reused: it
    published nothing, so every step after the first read "upstream data unavailable" —
    a working chain reported as broken."""
    run = client.post("/automations/dry-run", json=DRY_CHAIN).json()["run"]
    assert run["effects"][0]["data"]["answer"] == "«numbers.answer»"
    assert "upstream data unavailable" not in run["effects"][1]["message"]


def test_a_guard_is_REPORTED_never_decided(flag_on):
    """A sample cannot answer "will tomorrow's number clear this threshold". A preview
    that guessed would show a sound design as mostly held."""
    run = client.post("/automations/dry-run", json=DRY_CHAIN).json()["run"]
    step2 = run["effects"][1]
    assert step2["status"] == "executed"
    assert "only if numbers.answer is set — checked when it runs" in step2["message"]


def test_a_draft_that_could_not_be_SAVED_is_not_previewed_either(flag_on):
    """A preview must never be more permissive than the thing it previews, or it teaches
    a design the store would refuse."""
    bad = dict(DRY_CHAIN, effects=[{"kind": "notify", "config": {"trigger_id": "t"},
                                    "when": [{"left": {"$from": "ghost.x"}, "op": "truthy"}]}])
    assert client.post("/automations/dry-run", json=bad).status_code == 422


def test_a_preview_leaves_NO_run_in_the_history(flag_on):
    """`Activity` reads runs. A preview that appeared there is a run that happened."""
    created = client.post("/automations", json=DRY_CHAIN)
    aid = created.json()["id"]
    before = len(client.get(f"/automations/{aid}/runs").json()["runs"])
    assert client.post(f"/automations/{aid}/dry-run").status_code == 200
    assert len(client.get(f"/automations/{aid}/runs").json()["runs"]) == before
    client.delete(f"/automations/{aid}")


def test_a_DISABLED_automation_still_previews_and_says_so(flag_on):
    """You dry-run precisely because it is not armed yet. Gating on `enabled` would
    answer "disabled" to every question a preview exists to ask — but hiding that it is
    disabled would be its own lie."""
    created = client.post("/automations", json=dict(DRY_CHAIN, enabled=False))
    aid = created.json()["id"]
    run = client.post(f"/automations/{aid}/dry-run").json()["run"]
    assert run["outcome"] == "fired"
    assert "disabled" in run["reason"]
    client.delete(f"/automations/{aid}")


def test_the_preview_returns_the_graph_an_execution_view_reads(flag_on):
    """A dry run is never stored, so there is no id for the graph route to look up.
    Returning both is what let the canvas render a preview with no second drawing path."""
    g = client.post("/automations/dry-run", json=DRY_CHAIN).json()["graph"]
    assert g["mode"] == "execution" and g["dry_run"] is True
    steps = [n for n in g["nodes"] if n["type"] == "effect"]
    assert [n["status"] for n in steps] == ["executed", "executed"]


# ── W2 · the fan-out, over the wire ──────────────────────────────────────────────

def test_the_fan_out_vocabulary_comes_from_the_code(flag_on):
    """Third fetched vocabulary, same argument: the cap is enforced by the model and the
    engine, and a form carrying its own copy would offer a list the save then refuses."""
    from aughor.automations.dataflow import (
        FAN_PUBLISHED, ITEM_ALIAS, ITEM_VALUE, MAX_FAN_OUT,
    )

    vocab = client.get("/automations/vocabulary").json()["for_each"]
    assert vocab["max_items"] == MAX_FAN_OUT
    assert vocab["item_alias"] == ITEM_ALIAS
    assert vocab["item_value_key"] == ITEM_VALUE
    assert vocab["publishes"] == list(FAN_PUBLISHED)


def test_a_fanned_step_round_trips_through_create(flag_on):
    """`for_each` must survive the wire. A field the API drops is a chain that silently
    sends once where it was designed to send per item."""
    body = dict(BODY, effects=[
        {"kind": "notify", "alias": "tell", "config": {"trigger_id": "trig-1",
                                                       "message": {"$from": "item.value"}},
         "for_each": {"source": ["EMEA", "NA"]}},
    ])
    created = client.post("/automations", json=body)
    assert created.status_code in (200, 201), created.text
    stored = client.get(f"/automations/{created.json()['id']}").json()
    assert stored["effects"][0]["for_each"] == {"source": ["EMEA", "NA"]}


def test_an_unsound_fan_out_is_refused_at_save(flag_on):
    """`slack_post` publishes two strings; neither is a list. Refused when it is saved,
    not discovered at 09:00 as "cannot iterate a str"."""
    body = dict(BODY, effects=[
        {"kind": "notify", "alias": "first", "config": {"trigger_id": "trig-1"}},
        {"kind": "notify", "config": {"trigger_id": "trig-2",
                                      "message": {"$from": "item.value"}},
         "for_each": {"source": {"$from": "first.message"}}},
    ])
    refused = client.post("/automations", json=body)
    assert refused.status_code == 422, refused.text


def test_update_keeps_what_the_authoring_body_does_not_carry(flag_on):
    """A save must not erase the fields the engine owns.

    `PUT` rebuilds the record from `CreateAutomationRequest`, which is the AUTHORING
    shape — it has no field for the agent binding, the last run, or its outcome, because
    a person does not type those. Carrying only `id` and `created_at` forward meant every
    save reset them: the automation card went back to reading "never run" the moment
    somebody renamed it, and `Automation.agent_id` — which the engine reads to decide who
    a step runs AS — went back to empty.

    This is the third of its family in this subsystem (a `conn_id` left out of the
    upsert's DO UPDATE SET, an `agent_id` with no column at all), which is why the rule
    is now a test and not a comment: **read the row back after changing it.**
    """
    aid = client.post("/automations", json={**BODY, "conn_id": "conn-api-carry"}).json()["id"]

    # What the ENGINE writes, through its own path — not hand-set, so the test breaks if
    # that path changes too.
    append_run(AutomationRun(automation_id=aid, conn_id="conn-api-carry",
                             outcome="fired", reason="schedule(0 8 * * 1)"))
    before = client.get(f"/automations/{aid}").json()
    assert before["last_status"] == "fired", "precondition: the run did not record"
    assert before["last_run_at"], "precondition: the run did not stamp a time"

    renamed = client.put(f"/automations/{aid}", json={**BODY, "conn_id": "conn-api-carry",
                                                     "name": "Refund watch (renamed)"})
    assert renamed.status_code == 200
    after = client.get(f"/automations/{aid}").json()

    assert after["name"] == "Refund watch (renamed)", "the edit itself must still land"
    assert after["last_status"] == "fired"
    assert after["last_run_at"] == before["last_run_at"]
    assert after["created_at"] == before["created_at"]


def test_run_now_uses_the_run_id_the_caller_supplied(flag_on):
    """DS-3 — a run is watchable only if its id exists before it finishes.

    Every step writes a span under `trace_id == run_id` WHILE the chain runs, but this
    request does not return until the chain has finished — so a caller that cannot name
    the run in advance can only ever be told about it afterwards. Supplying the id is the
    whole difference between watching a run and being notified about one.

    The effect here names a notification trigger that does not exist, so the step records
    a failure and nothing outward is reached — the contract under test is the id.
    """
    aid = client.post("/automations", json={**BODY, "conn_id": "conn-api-runid"}).json()["id"]

    res = client.post(f"/automations/{aid}/run", json={"run_id": "run-chosen-by-caller"})
    assert res.status_code == 200
    assert res.json()["id"] == "run-chosen-by-caller"

    # And it is the id the run was STORED under — the trace a watcher would subscribe to.
    runs = client.get(f"/automations/{aid}/runs").json()["runs"]
    assert [r["id"] for r in runs] == ["run-chosen-by-caller"]


def test_run_now_still_mints_an_id_when_none_is_offered(flag_on):
    """The old contract is untouched: no body, or no `run_id`, and the engine names it."""
    aid = client.post("/automations", json={**BODY, "conn_id": "conn-api-mint"}).json()["id"]
    res = client.post(f"/automations/{aid}/run")
    assert res.status_code == 200
    assert res.json()["id"]


# ── DS-2 · run to here ────────────────────────────────────────────────────────

CHAIN = {
    "conn_id": "conn-api-until",
    "name": "Three steps",
    "conditions": [{"kind": "schedule", "config": {"cron": "0 8 * * 1"}}],
    "effects": [
        {"kind": "notify", "alias": "one", "config": {"trigger_id": "t1"}},
        {"kind": "notify", "alias": "two", "config": {"trigger_id": "t2"}},
        {"kind": "notify", "alias": "three", "config": {"trigger_id": "t3"}},
    ],
}


def _steps(body: dict) -> list[tuple[str, str]]:
    """Each effect node as `(alias, status)` — the graph is what a reader looks at, and
    the alias only exists there: an outcome's `target` is what the step DISPATCHES to."""
    return [(n["id"], n.get("status") or "") for n in body["graph"]["nodes"]
            if n["type"] == "effect"]


def test_dry_run_walks_only_as_far_as_the_named_step(flag_on):
    """DS-2 — a preview you can stop.

    A whole-chain preview answers "what would all of this do"; the question a person
    actually has while building is "what does the step I am looking at receive". Walking
    past it costs the reader that answer among four others.
    """
    res = client.post("/automations/dry-run?until=two", json=CHAIN)
    assert res.status_code == 200
    assert len(res.json()["run"]["effects"]) == 2
    assert res.json()["until"] == "two"


def test_the_steps_beyond_the_cut_are_DRAWN_but_untouched(flag_on):
    """"Not asked" and "did nothing" are different pictures.

    `build_graph` is given the whole automation, so every node exists and only the walked
    ones carry a status. A graph truncated to the walk would look like a chain that ends
    where the reader stopped looking.
    """
    assert _steps(client.post("/automations/dry-run?until=one", json=CHAIN).json()) == [
        ("one", "executed"), ("two", ""), ("three", ""),
    ]


def test_an_unknown_frontier_walks_the_whole_chain(flag_on):
    """A frontier nobody can find is the caller's mistake; answering it with an empty
    preview would look like a chain that does nothing."""
    body = client.post("/automations/dry-run?until=no-such-step", json=CHAIN).json()
    assert len(body["run"]["effects"]) == 3


def test_omitting_the_frontier_is_the_whole_chain_exactly_as_before(flag_on):
    body = client.post("/automations/dry-run", json=CHAIN).json()
    assert len(body["run"]["effects"]) == 3
    assert body["until"] == ""
