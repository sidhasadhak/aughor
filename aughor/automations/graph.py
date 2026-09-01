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
    BRANCH_SKIP, FAN_PUBLISHED, GUARD_SKIP, alias_for, collect_refs, effect_refs,
    else_target, fan_source, guard_clauses, is_binding, parse_ref, render_clause, FROM,
)


def condition_label(cond: Any) -> str:
    """One condition, in the words the canvas uses.

    Public since B2: a dry run describes conditions instead of evaluating them, and the
    trigger node and the preview must not word the same condition differently.
    """
    kind = getattr(cond, "kind", "")
    cfg = getattr(cond, "config", {}) or {}
    if kind == "schedule":
        return f"schedule · {cfg.get('cron', '')}".strip(" ·")
    if kind == "metric":
        return f"metric · monitor {cfg.get('monitor_id', '')}".strip(" ·")
    if kind in ("source_change", "entity_appears"):
        return f"{kind} · {cfg.get('table', '')}".strip(" ·")
    return kind or "condition"


def fan_label(effect: Any) -> str:
    """How a step's fan-out READS on a canvas: ``"rows.items"`` or ``"EMEA, NA, APAC"``.

    Authored literals are shown for the same reason W1 shows them in a guard — the author
    typed them, and a canvas that said only "3 items" would be a picture you cannot check
    against the design. Resolved values are never shown (there are none yet on a structure
    graph, and this module's standing rule is that only the allowlist may label). Dict
    items are counted rather than rendered: their fields are a payload, not a label.
    """
    src = fan_source(effect)
    if src is None:
        return ""
    if is_binding(src):
        return str(src[FROM])
    if not isinstance(src, list):
        return ""
    scalars = [i for i in src if not isinstance(i, (dict, list))]
    if len(scalars) != len(src):
        return f"{len(src)} items"
    shown = [str(i)[:24] for i in scalars[:3]]
    more = len(scalars) - len(shown)
    return ", ".join(shown) + (f" +{more} more" if more else "")


def group_outcomes(effects: list, outcomes: list) -> list[list]:
    """The outcomes belonging to each effect, in order.

    W2 broke a load-bearing assumption of this module, which used to read
    ``outcomes[i]``: the engine appended **exactly one outcome per effect**, so position
    was identity. A fanned step appends one per ITEM, which would have shifted every node
    after it onto another step's status — a picture that is wrong rather than missing,
    and the failure this module exists to prevent.

    ``fan_count`` is how many an iteration says its step produced; a fan-out refused
    before it ran (an unusable source, an empty list) appends a single outcome with 0,
    like any ordinary step.
    """
    groups: list[list] = []
    cursor = 0
    for _effect in effects:
        if cursor >= len(outcomes):
            groups.append([])
            continue
        take = max(1, int(getattr(outcomes[cursor], "fan_count", 0) or 0))
        groups.append(list(outcomes[cursor:cursor + take]))
        cursor += take
    return groups


def _group_status(group: list) -> str:
    """One status for a step that may have run N times.

    A failure ANYWHERE is the headline — "2 of 3 posted" with a green node is how a
    partial send reads as a whole one. Otherwise an executed iteration wins over a held
    one, because the step did run; all-held reads as `skipped`, which is what it is.
    """
    statuses = [getattr(o, "status", "") for o in group]
    for status in statuses:
        if status not in ("executed", "skipped"):
            return status
    if "executed" in statuses:
        return "executed"
    return statuses[0] if statuses else ""


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
            condition_label(c) for c in conditions) or "manual",
    })

    outcomes = list(getattr(run, "effects", []) or []) if run is not None else []
    effects = list(getattr(automation, "effects", []) or [])
    groups = group_outcomes(effects, outcomes)

    # DS-7 — under parallel scheduling the chain-of-sequence spine would be a LIE: step
    # N+1 does not run after step N unless an arrow says so. The spine then connects the
    # trigger to each ROOT (a step no other step feeds) and nothing else — every other
    # ordering claim on the picture is a data or route edge the engine actually honours.
    # The dependency set is the engine's own: `effect_refs` plus the `else_of` target.
    parallel = getattr(automation, "scheduling", "ordered") == "parallel"
    known = {alias_for(e, n) for n, e in enumerate(effects)}
    fed = {alias_for(e, n): ({parse_ref(r)[0] for r in effect_refs(e)}
                             | ({else_target(e)} if else_target(e) else set())) & known
           for n, e in enumerate(effects)}

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
            "detail": effect_detail(effect),
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
        # DS-6 — the route, a design fact like the guard above: WHEN this step runs is
        # part of what it is, and a canvas that omitted "otherwise of s2" would draw an
        # arm as a step that always fires.
        route_from = else_target(effect)
        if route_from:
            node["else_of"] = route_from
        acting = (getattr(effect, "agent_id", "") or getattr(automation, "agent_id", "") or "")
        if acting:
            node["agent_id"] = acting
            node["delegated"] = bool(getattr(effect, "agent_id", ""))
        # W2 — a design fact like the guard above: does this step run once, or once per
        # item of a list? A canvas that omitted it would draw one send where N happen.
        fanned_over = fan_label(effect)
        if fanned_over:
            node["for_each"] = fanned_over
        group = groups[i] if i < len(groups) else []
        if group:
            o = group[0]
            node["status"] = _group_status(group)
            node["message"] = getattr(o, "message", "")
            # W1 — WHICH KIND of skip. A step held back by its own guard is the design
            # working; a step skipped for missing upstream data is something breaking,
            # and they are the same `skipped` status. Read off the GUARD_SKIP constant
            # the engine writes rather than sniffed out of the prose: a matching key
            # that quietly stops matching is how a guard goes blind.
            if node["status"] == "skipped":
                node["guarded"] = all(
                    str(getattr(x, "message", "")).startswith(GUARD_SKIP)
                    for x in group if getattr(x, "status", "") == "skipped")
                # DS-6 — the route's untaken arm, read off BRANCH_SKIP the same way and
                # for the same reason: "not taken" is the design working, one branch
                # over, and the dim `skipped` grey is the colour of something wrong.
                node["not_taken"] = all(
                    str(getattr(x, "message", "")).startswith(BRANCH_SKIP)
                    for x in group if getattr(x, "status", "") == "skipped")
            # VA-4c — which step was slow, and how many attempts it took. The run's single
            # duration could not answer either. W2 — summed and maxed across the
            # iterations: a fanned step's cost is what all of them cost, and its worst
            # attempt count is the one worth seeing.
            node["duration_ms"] = round(
                sum(getattr(x, "duration_ms", 0.0) or 0.0 for x in group), 1)
            node["attempts"] = max(int(getattr(x, "attempts", 1) or 1) for x in group)
            # The outcome carried this and the node did not — caught live, by reading a
            # real run rather than a constructed one.
            node["started_at"] = getattr(o, "started_at", "") or ""
            # Only when there is exactly one: a fanned `investigate` produces one
            # investigation per item, and linking the node to an arbitrary one of them
            # would be a receipt for work the reader did not click on.
            if len(group) == 1 and getattr(o, "investigation_id", ""):
                node["investigation_id"] = o.investigation_id
            if int(getattr(o, "fan_count", 0) or 0):
                ran = sum(1 for x in group if getattr(x, "status", "") == "executed")
                node["fan"] = {"count": len(group), "executed": ran,
                               "skipped": sum(1 for x in group
                                              if getattr(x, "status", "") == "skipped")}
                # The headline a reader needs at 09:00 is how many of them went, and the
                # first thing that did not — not the first iteration's message, which on
                # a healthy fan-out says nothing at all.
                bad = next((x for x in group
                            if getattr(x, "status", "") != "executed"), None)
                node["message"] = (f"{ran} of {len(group)} ran"
                                   + (f" · {getattr(bad, 'message', '')}" if bad else ""))
            # What the step PRODUCED, named. In Execution mode this is what makes a
            # data edge checkable by eye: the key an edge claims to carry is either in
            # this list or the edge is lying. A fanned step publishes its COUNT and
            # nothing else — its per-item values are N values, not one.
            node["produced"] = (
                (list(FAN_PUBLISHED) if node["status"] == "executed" else [])
                if node.get("fan") else
                sorted((getattr(o, "data", None) or {}).keys()))
        nodes.append(node)

        # sequence: the trigger starts the first step; each step precedes the next.
        # DS-7 — on a parallel automation, only the trigger→root spine survives (see
        # above): a sequence arrow between two independent steps would claim an order
        # the frontier does not keep.
        if not parallel:
            edges.append({"from": trigger_id if i == 0 else alias_for(effects[i - 1], i - 1),
                          "to": alias, "type": "sequence"})
        elif not fed[alias]:
            edges.append({"from": trigger_id, "to": alias, "type": "sequence"})

        # DS-6 — the route, drawn. A third edge kind on purpose: it carries no value
        # (that is `data`) and claims more than order (that is `sequence`) — it DECIDES
        # whether the arm runs at all, off the deciding step's guard verdict.
        if route_from:
            edges.append({"from": route_from, "to": alias, "type": "route",
                          "label": "otherwise"})

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
        # DS-7 — how the steps are scheduled, so a canvas can SAY it ("in parallel —
        # as the arrows allow") instead of leaving a spine-less picture to explain
        # itself.
        "scheduling": getattr(automation, "scheduling", "ordered") or "ordered",
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


def effect_detail(effect: Any) -> str:
    """A short, honest label for what this step targets — never the whole config, which
    can carry a message body or a credential-shaped value.

    Public since B2: a dry run reports what each step WOULD target, and this allowlist is
    the vetted way to name it. A second labeller would be a second chance to spill.
    """
    cfg = getattr(effect, "config", {}) or {}
    # DS-11 — the OPERATION, not the grant. Found by drawing the canvas: two integration
    # steps, one reading Gmail and one posting to Slack, rendered as two nodes both
    # labelled "Use an integration" with nothing to tell them apart. The operation is safe
    # to show by CONSTRUCTION — it is an id from the closed roster, never authored text —
    # while the grant would put an account's email address on a picture that is read on
    # screen and exported, which is exactly what this allowlist exists to stop.
    for key in ("action_id", "operation", "question", "subscription_id", "monitor_id",
                "rule_id", "trigger_id", "channel"):
        val = cfg.get(key)
        if isinstance(val, str) and val:
            return val if len(val) <= 80 else val[:80] + "…"
    return ""


def data_edges_only(graph: dict) -> list[dict]:
    """The edges that carry a value. The sequence scaffolding is not the point."""
    return [e for e in graph.get("edges", []) if e.get("type") == "data"]
