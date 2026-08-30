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
    # W1 — `guard` is on every data edge, false here: this one FILLS a field. An edge
    # that decides whether the step runs at all is a different claim about the chain.
    assert data == [{"from": "step1", "to": "step2", "type": "data", "label": "ts",
                     "guard": False}]


def test_a_GUARD_reference_draws_too_and_says_it_is_a_guard():
    """W1 — a guard reads the chain exactly as a param does. An arrow the engine follows
    that the picture omits is the disagreement this module exists to prevent."""
    from aughor.automations.models import Effect
    g = build_graph(_automation(
        Effect(kind="investigate", alias="report", config={"question": "q"}),
        Effect(kind="slack_post", config={"bot_id": "sb_1", "channel": "C1"},
               when=[{"left": {"$from": "report.answer"}, "op": "truthy"}])))
    data = data_edges_only(g)
    assert data == [{"from": "report", "to": "step2", "type": "data", "label": "answer",
                     "guard": True}]


def test_a_step_carries_its_guard_as_sentences_on_the_STRUCTURE_graph():
    """Whether a step will run at all is a DESIGN fact. A canvas that omits it draws a
    chain that always fires."""
    from aughor.automations.models import Effect
    g = build_graph(_automation(
        Effect(kind="investigate", alias="report", config={"question": "q"}),
        Effect(kind="slack_post", config={"bot_id": "sb_1", "channel": "C1"},
               when=[{"left": {"$from": "report.answer"}, "op": "truthy"}])))
    step = [n for n in g["nodes"] if n["id"] == "step2"][0]
    assert step["when"] == ["report.answer is set"]
    assert step["when_logic"] == "all"
    assert g["mode"] == "structure", "no run needed to know the guard exists"


def test_a_guarded_skip_is_MARKED_apart_from_an_upstream_skip():
    """Both are `skipped`, and they mean opposite things: one is the design working, the
    other is something breaking. Read off the engine's own constant, never sniffed."""
    from aughor.automations.dataflow import GUARD_SKIP
    run = _Run([
        EffectOutcome(kind="slack_post", target="a", status="skipped",
                      message=f"{GUARD_SKIP}: report.answer is set"),
        EffectOutcome(kind="slack_post", target="b", status="skipped",
                      message="upstream data unavailable: step 'x' produced nothing"),
    ])
    nodes = [n for n in build_graph(_automation(_effect(), _effect()), run)["nodes"]
             if n["type"] == "effect"]
    assert nodes[0]["guarded"] is True
    assert nodes[1]["guarded"] is False


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
    # `ask` is an investigate step because B1's key validation now refuses, at
    # CONSTRUCTION, a binding onto a key the producer kind cannot publish — and
    # `answer` is investigate's key, not slack_post's. This fixture was the guard's
    # second catch of this suite's own fixtures (the dataflow suite was the first).
    g = build_graph(_automation(
        Effect(kind="investigate", alias="ask", config={"question": "sales?"}),
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


# ── VA-4c: the run canvas — which step was slow, and what fired it ──────────────

def test_a_step_carries_its_own_duration_and_attempts():
    """The run had ONE duration_ms for the whole tick, which cannot answer "which step
    was slow" — the question a run canvas exists to answer."""
    a = _automation(_effect(), _effect())
    run = _Run([EffectOutcome(kind="slack_post", target="t", status="executed",
                              duration_ms=1234.5, attempts=2,
                              started_at="2026-08-29T09:00:00Z"),
                EffectOutcome(kind="slack_post", target="t", status="executed",
                              duration_ms=7.0)])
    steps = [n for n in build_graph(a, run)["nodes"] if n["type"] == "effect"]
    assert steps[0]["duration_ms"] == 1234.5 and steps[0]["attempts"] == 2
    assert steps[1]["duration_ms"] == 7.0
    # Caught live: the outcome carried started_at and the node did not.
    assert steps[0]["started_at"] == "2026-08-29T09:00:00Z"


def test_the_trigger_says_WHAT_FIRED_IT_not_only_what_it_watches():
    """On a run, a trigger showing only its schedule is a design element in a view meant
    to show what happened."""
    class _R(_Run):
        def __init__(self):
            super().__init__([EffectOutcome(kind="slack_post", target="t", status="executed")])
            self.conditions_fired = ["schedule"]
            self.started_at = "2026-08-29T09:00:00Z"
            self.duration_ms = 42
            self.outcome = "fired"

    trigger = build_graph(_automation(_effect()), _R())["nodes"][0]
    assert trigger["fired"] == ["schedule"]
    assert trigger["at"].startswith("2026-08-29")
    assert trigger["status"] == "fired"


def test_a_structure_trigger_claims_no_firing():
    """A design has not fired. Showing a stale 'fired' on it would be a run nobody made."""
    trigger = build_graph(_automation(_effect()))["nodes"][0]
    assert "fired" not in trigger and "at" not in trigger


def test_an_investigate_step_carries_the_run_that_holds_its_spend():
    """Tokens live on the investigation, not on the outcome. Carrying the id lets a node
    reach its own spend without this model growing a usage field the other five effect
    kinds could never fill."""
    a = _automation(_effect())
    run = _Run([EffectOutcome(kind="investigate", target="t", status="executed",
                              investigation_id="inv-77")])
    step = [n for n in build_graph(a, run)["nodes"] if n["type"] == "effect"][0]
    assert step["investigation_id"] == "inv-77"


def test_the_graph_route_offers_the_runs_rail(client):
    from aughor.automations.store import upsert_automation as save_automation
    from aughor.automations.engine import run_automation
    a = save_automation(_automation(_effect()))
    run_automation(a, persist=True, dispatch=lambda e, au: EffectOutcome(
        kind=e.kind, target="t", status="executed"),
        probe=lambda *x, **k: True, sleeper=lambda _s: None, rng=lambda: 0.0)

    body = client.get(f"/automations/{a.id}/graph", params={"run": "latest"}).json()
    assert body["runs"], "a canvas must be able to ask 'which run?' in one request"
    assert {"id", "outcome", "at", "steps", "failed"} <= set(body["runs"][0])
    assert body["run_id"], "and know which one it is currently showing"
