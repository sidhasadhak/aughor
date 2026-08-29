"""VA-4b — the automation as the graph it actually is.

Today `AutomationsPanel` renders effects as a comma-joined sentence: a list, not a graph.
The user's framing was exact — *"what we have is a flow after the run is done… what you
see from VoltAgent is the whole workflow that gets designed by the user."*

VA-4a made the runtime honour edges; this makes the picture. The properties below are what
keep the picture honest:

* **One authority.** The graph derives from the same `collect_refs` the engine resolves
  against. Two readers deriving the graph differently is how a picture and its run come to
  disagree — and a workflow view with decorative arrows is worse than a list, because a
  list does not claim.
* **Data edges and sequence edges are distinct.** An edge that means output→input is the
  only one carrying meaning; "step 2 runs after step 1" is true and much weaker.
  Conflating them teaches someone a dependency their automation does not have.
* **Structure and Execution are the SAME graph.** Passing a run decorates it; passing none
  describes it. Never two surfaces that can drift.
* **A step's config is not spilled into a label** — it can hold a message body or a
  credential-shaped value.
"""
from __future__ import annotations

from aughor.automations.graph import build_graph, data_edges_only
from aughor.automations.models import Automation, Condition, Effect, EffectOutcome


def _effect(alias="", **config) -> Effect:
    base = {"bot_id": "sb_1", "channel": "C1"}
    base.update(config)
    return Effect(kind="slack_post", alias=alias, config=base)


def _automation(*effects, logic="all") -> Automation:
    return Automation(
        name="Monday briefing", conn_id="conn-a", condition_logic=logic,
        conditions=[Condition(kind="schedule", config={"cron": "0 9 * * 1"})],
        effects=list(effects), max_retries=0,
    )


# ── structure ────────────────────────────────────────────────────────────────────

def test_the_trigger_is_a_node_and_its_conditions_are_legible():
    g = build_graph(_automation(_effect()))
    trigger = g["nodes"][0]
    assert trigger["type"] == "trigger"
    assert "0 9 * * 1" in trigger["detail"]


def test_multiple_conditions_show_their_logic():
    a = Automation(
        name="x", conn_id="c", condition_logic="any",
        conditions=[Condition(kind="schedule", config={"cron": "* * * * *"}),
                    Condition(kind="source_change", config={"table": "orders"})],
        effects=[_effect()], max_retries=0)
    assert " OR " in build_graph(a)["nodes"][0]["detail"]


def test_every_step_is_a_node_named_the_way_a_reference_names_it():
    """The node id IS the alias a `$from` uses. If they differed, an edge could point at
    a node nobody can reference."""
    g = build_graph(_automation(_effect(), _effect(alias="post")))
    ids = [n["id"] for n in g["nodes"] if n["type"] == "effect"]
    assert ids == ["step1", "post"]


def test_a_binding_becomes_a_DATA_edge_labelled_with_the_key_it_carries():
    g = build_graph(_automation(_effect(), _effect(thread_ts={"$from": "step1.ts"})))
    data = data_edges_only(g)
    assert data == [{"from": "step1", "to": "step2", "type": "data", "label": "ts"}]


def test_sequence_edges_are_a_DIFFERENT_kind_from_data_edges():
    """'Runs after' is not 'consumes'. Drawing them the same would let the picture imply
    a dependency the engine does not have."""
    g = build_graph(_automation(_effect(), _effect()))
    kinds = {e["type"] for e in g["edges"]}
    assert kinds == {"sequence"}, "no bindings here, so no data edges"
    assert not data_edges_only(g)


def test_the_first_step_hangs_off_the_trigger():
    g = build_graph(_automation(_effect()))
    seq = [e for e in g["edges"] if e["type"] == "sequence"]
    assert seq[0] == {"from": "trigger", "to": "step1", "type": "sequence"}


def test_a_fan_in_draws_two_data_edges():
    """Merged-data means step 3 can read step 1 — the case a previous-step-only chain
    cannot express, and the one worth SEEING."""
    g = build_graph(_automation(
        _effect(alias="ask"),
        _effect(alias="open"),
        _effect(text={"$from": "ask.answer"}, thread_ts={"$from": "open.ts"}),
    ))
    edges = {(e["from"], e["label"]) for e in data_edges_only(g)}
    assert edges == {("ask", "answer"), ("open", "ts")}


def test_the_graph_and_the_engine_derive_the_SAME_edges():
    """The one that keeps the picture honest. Both read `collect_refs`; if the graph ever
    grew its own parser, a drawn arrow could stop matching a resolved one."""
    from aughor.automations.dataflow import collect_refs
    effect = _effect(alias="two", thread_ts={"$from": "one.ts"},
                     nested={"deep": [{"$from": "one.channel"}]})
    a = _automation(_effect(alias="one"), effect)
    drawn = {e["label"] for e in data_edges_only(build_graph(a))}
    resolved = {r.split(".", 1)[1] for r in collect_refs(effect.config)}
    assert drawn == resolved == {"ts", "channel"}


def test_a_label_never_spills_the_config():
    """A step's config can hold a message body or a credential-shaped value."""
    g = build_graph(_automation(_effect(message="secret sauce", bot_token="xoxb-oops")))
    blob = str(g)
    assert "xoxb-oops" not in blob and "secret sauce" not in blob


# ── execution: the same graph, decorated ─────────────────────────────────────────

class _Run:
    def __init__(self, effects):
        self.effects = effects


def test_passing_a_run_decorates_the_same_nodes():
    a = _automation(_effect(), _effect(thread_ts={"$from": "step1.ts"}))
    run = _Run([EffectOutcome(kind="slack_post", target="t", status="executed",
                              data={"ts": "1788.1", "channel": "C1"}),
                EffectOutcome(kind="slack_post", target="t", status="skipped",
                              message="upstream data unavailable")])
    structure, execution = build_graph(a), build_graph(a, run)

    assert structure["mode"] == "structure" and execution["mode"] == "execution"
    assert [n["id"] for n in structure["nodes"]] == [n["id"] for n in execution["nodes"]], \
        "Structure and Execution must be the SAME graph, not two surfaces"
    assert structure["edges"] == execution["edges"]

    steps = [n for n in execution["nodes"] if n["type"] == "effect"]
    assert steps[0]["status"] == "executed"
    assert steps[0]["produced"] == ["channel", "ts"]
    assert steps[1]["status"] == "skipped"


def test_produced_keys_make_a_data_edge_checkable_by_eye():
    """An edge claims to carry `ts`; the upstream node lists what it produced. Either the
    key is there or the edge is lying, and that is visible without reading the engine."""
    a = _automation(_effect(), _effect(thread_ts={"$from": "step1.ts"}))
    run = _Run([EffectOutcome(kind="slack_post", target="t", status="executed",
                              data={"ts": "1788.1"}),
                EffectOutcome(kind="slack_post", target="t", status="executed")])
    g = build_graph(a, run)
    upstream = next(n for n in g["nodes"] if n["id"] == "step1")
    carried = data_edges_only(g)[0]["label"]
    assert carried in upstream["produced"]


def test_a_structure_graph_carries_no_status_at_all():
    """A design has not happened yet. Showing a stale status on it would be a run
    someone did not make."""
    g = build_graph(_automation(_effect()))
    assert all("status" not in n for n in g["nodes"])


# ── the route ────────────────────────────────────────────────────────────────────

def test_graph_route_returns_structure_by_default(client):
    from aughor.automations.store import upsert_automation as save_automation
    a = save_automation(_automation(_effect(), _effect(thread_ts={"$from": "step1.ts"})))
    body = client.get(f"/automations/{a.id}/graph").json()
    assert body["mode"] == "structure"
    assert len([e for e in body["edges"] if e["type"] == "data"]) == 1


def test_graph_route_for_an_automation_that_never_ran_is_an_honest_empty(client):
    """Not a 404: the automation exists and its structure is exactly what the caller asked
    to see decorated. Refusing the whole graph would hide the thing they came to look at."""
    from aughor.automations.store import upsert_automation as save_automation
    a = save_automation(_automation(_effect()))
    body = client.get(f"/automations/{a.id}/graph", params={"run": "latest"}).json()
    assert body.get("run_missing") is True
    assert body["mode"] == "structure" and body["nodes"]


def test_unknown_automation_is_404(client):
    assert client.get("/automations/nope/graph").status_code == 404
