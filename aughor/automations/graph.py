"""VA-4b — the automation, as the graph it actually is.

Derived on the SERVER, from the same `collect_refs` the engine resolves against. That is
the whole point: a picture drawn by a second reader is a picture that can disagree with
the run, and a workflow view whose arrows are decorative is worse than a list — a list at
least does not claim.

Two edge kinds, drawn differently on purpose:

* **``data``** — a real ``{"$from": "step1.ts"}`` binding. Output → input. This is the
  edge that carries meaning, and the reason a canvas is worth having at all: the standing
  ReactFlow verdict refused a canvas for *agent creation* precisely because an agent is
  one record with "no producer/consumer relation between its parts, so there is no second
  node for an edge to terminate on". Automations now have that relation. The refusal's own
  argument is what licenses this.
* **``sequence``** — step N runs before step N+1. True, and much weaker. Conflating the
  two would let a picture imply a dependency the engine does not have, which is how a
  diagram teaches someone the wrong model of their own automation.

**Structure vs Execution is the same graph, twice.** Passing a run decorates the nodes
with what happened; passing none describes what is designed. One derivation, two readings
— never two surfaces that drift.
"""
from __future__ import annotations

from typing import Any

from aughor.automations.dataflow import (
    GUARD_SKIP, alias_for, collect_refs, effect_refs, guard_clauses, parse_ref,
    render_clause,
)


def _condition_label(cond: Any) -> str:
    kind = getattr(cond, "kind", "")
    cfg = getattr(cond, "config", {}) or {}
    if kind == "schedule":
        return f"schedule · {cfg.get('cron', '')}".strip(" ·")
    if kind == "metric":
        return f"metric · monitor {cfg.get('monitor_id', '')}".strip(" ·")
    if kind in ("source_change", "entity_appears"):
        return f"{kind} · {cfg.get('table', '')}".strip(" ·")
    return kind or "condition"


def build_graph(automation: Any, run: Any = None) -> dict:
    """``{"nodes": [...], "edges": [...], "mode": "structure"|"execution"}``.

    ``run`` is an :class:`~aughor.automations.models.AutomationRun`; when given, each
    effect node carries the status and message from that run. Outcomes are matched
    POSITIONALLY, which is what the engine produces — it appends exactly one outcome per
    effect in order, including the skipped ones, before any fallback. Matching on
    ``target`` instead would silently mis-pair two steps that dispatch the same action.
    """
    nodes: list[dict] = []
    edges: list[dict] = []

    trigger_id = "trigger"
    conditions = list(getattr(automation, "conditions", []) or [])
    logic = getattr(automation, "condition_logic", "all")
    nodes.append({
        "id": trigger_id,
        "type": "trigger",
        "label": "When",
        "detail": f" {'AND' if logic == 'all' else 'OR'} ".join(
            _condition_label(c) for c in conditions) or "manual",
    })

    outcomes = list(getattr(run, "effects", []) or []) if run is not None else []
    effects = list(getattr(automation, "effects", []) or [])

    for i, effect in enumerate(effects):
        alias = alias_for(effect, i)
        node = {
            "id": alias,
            "type": "effect",
            "kind": getattr(effect, "kind", ""),
            "label": alias,
            # NEVER `getattr(effect, "target", ...)`: `Effect.target` is a METHOD, and a
            # bound method is truthy — so an `or` fallback silently never ran and the
            # method's repr carried the whole config, `bot_token` included, into a UI
            # payload. Caught by the no-spill test. Only the allowlist below may label.
            "detail": _effect_detail(effect),
        }
        # VA-9b — whose work this step is. On the STRUCTURE graph too, because "which
        # agent will act" is part of the design, not only of a run.
        # W1 — the guard, as sentences. On the structure graph too: whether a step will
        # run at all is a design fact, and a canvas that omits it draws a chain that
        # always fires. `render_clause` renders reference PATHS and authored literals
        # only, never a resolved value — the no-spill rule this module already keeps.
        clauses = guard_clauses(effect)
        if clauses:
            node["when"] = [render_clause(c) for c in clauses]
            node["when_logic"] = getattr(effect, "when_logic", "all") or "all"
        acting = (getattr(effect, "agent_id", "") or getattr(automation, "agent_id", "") or "")
        if acting:
            node["agent_id"] = acting
            node["delegated"] = bool(getattr(effect, "agent_id", ""))
        if i < len(outcomes):
            o = outcomes[i]
            node["status"] = getattr(o, "status", "")
            node["message"] = getattr(o, "message", "")
            # W1 — WHICH KIND of skip. A step held back by its own guard is the design
            # working; a step skipped for missing upstream data is something breaking,
            # and they are the same `skipped` status. Read off the GUARD_SKIP constant
            # the engine writes rather than sniffed out of the prose: a matching key
            # that quietly stops matching is how a guard goes blind.
            if node["status"] == "skipped":
                node["guarded"] = str(node["message"]).startswith(GUARD_SKIP)
            # VA-4c — which step was slow, and how many attempts it took. The run's single
            # duration could not answer either.
            node["duration_ms"] = getattr(o, "duration_ms", 0.0) or 0.0
            node["attempts"] = getattr(o, "attempts", 1) or 1
            # The outcome carried this and the node did not — caught live, by reading a
            # real run rather than a constructed one.
            node["started_at"] = getattr(o, "started_at", "") or ""
            if getattr(o, "investigation_id", ""):
                node["investigation_id"] = o.investigation_id
            # What the step PRODUCED, named. In Execution mode this is what makes a
            # data edge checkable by eye: the key an edge claims to carry is either in
            # this list or the edge is lying.
            node["produced"] = sorted((getattr(o, "data", None) or {}).keys())
        nodes.append(node)

        # sequence: the trigger starts the first step; each step precedes the next.
        edges.append({"from": trigger_id if i == 0 else alias_for(effects[i - 1], i - 1),
                      "to": alias, "type": "sequence"})

        # data: one edge per binding, labelled with the key it carries.
        #
        # W1 — `effect_refs`, so a guard's references draw too. A guard reads the chain
        # exactly as a param does, and an arrow the engine follows that the picture omits
        # is the disagreement this module exists to prevent. Marked `guard` so the canvas
        # can say WHICH: this edge decides whether the step runs, it does not fill a field.
        param_refs = collect_refs(getattr(effect, "config", {}) or {})
        for n, ref in enumerate(effect_refs(effect)):
            source, key = parse_ref(ref)
            edges.append({"from": source, "to": alias, "type": "data", "label": key,
                          "guard": n >= len(param_refs)})

    out = {
        "nodes": nodes,
        "edges": edges,
        "mode": "execution" if run is not None else "structure",
        "automation_id": getattr(automation, "id", ""),
        "name": getattr(automation, "name", ""),
        "agent_id": getattr(automation, "agent_id", "") or "",
    }
    if run is not None:
        # VA-4c — the trigger node says WHAT fired it and when, not only what it watches.
        # A trigger that shows its schedule but not its firing is a design element in a
        # view that is supposed to be showing a run.
        nodes[0]["fired"] = list(getattr(run, "conditions_fired", []) or [])
        nodes[0]["at"] = getattr(run, "started_at", "")
        nodes[0]["duration_ms"] = getattr(run, "duration_ms", 0) or 0
        nodes[0]["status"] = getattr(run, "outcome", "")
        # WHY this run decorated nothing. Found by driving it: a `not_fired` or `gated`
        # tick carries zero effect outcomes, so Execution mode rendered a graph identical
        # to Structure with nothing to say for itself — the viewer cannot tell whether the
        # run did nothing or the view is broken. The engine already records the reason
        # ("schedule(0 9 * * 1): next due …"); it just was not being carried.
        out["run_outcome"] = getattr(run, "outcome", "")
        out["run_reason"] = getattr(run, "reason", "")
        out["run_at"] = getattr(run, "started_at", "")
    return out


def _effect_detail(effect: Any) -> str:
    """A short, honest label for what this step targets — never the whole config, which
    can carry a message body or a credential-shaped value."""
    cfg = getattr(effect, "config", {}) or {}
    for key in ("action_id", "question", "subscription_id", "monitor_id", "rule_id",
                "trigger_id", "channel"):
        val = cfg.get(key)
        if isinstance(val, str) and val:
            return val if len(val) <= 80 else val[:80] + "…"
    return ""


def data_edges_only(graph: dict) -> list[dict]:
    """The edges that carry a value. The sequence scaffolding is not the point."""
    return [e for e in graph.get("edges", []) if e.get("type") == "data"]
