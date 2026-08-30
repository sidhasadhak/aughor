"""VA-4a — one effect's output becomes another's input.

The gap this closes, measured 2026-08-29 before any of it was written:

* ``engine.py`` ran effects as a **list comprehension** — every effect received only
  ``(effect, automation, dispatch)``, so no effect ever saw a prior effect's output.
* ``EffectOutcome`` carried no data at all, so there was nothing to pass even if we
  passed it — though every dispatcher already HELD the data and discarded it here.
* Params were literals; nothing interpolated.

Three gaps, one missing idea: a chain. This module is the consumer half — how a later
step names an earlier step's output.

**Explicit binding, not string templating.** A reference is ``{"$from": "step1.ts"}``,
resolved structurally, never by splicing text into a string. Three reasons, in order of
how much they matter:

1. **It is validated at construction.** Does that step exist, and does it run *before*
   this one? A forward or self reference is rejected when the automation is saved, not
   discovered at 03:00 — this plane's own rule, inherited from K1: reject at parse,
   never surface.
2. **It is not an injection surface.** Interpolating text into a webhook body or a SQL
   parameter is how a value becomes a command.
3. **It draws.** ``step1.ts → step2.thread_ts`` is an edge a canvas can render. A
   template string embedded in prose is not, and VA-4b needs the graph to be real.

**Merged-data, à la `andThen`.** A step sees the accumulated output of EVERY prior step,
not just its immediate predecessor — which is what makes a fan-in ("post the answer from
step 1 into the thread step 2 opened") expressible without threading values by hand.
"""
from __future__ import annotations

from typing import Any, Optional

#: The marker that makes a param a reference rather than a literal. A dict with exactly
#: this one key is a binding; anything else is a value, so a payload that merely happens
#: to contain the string is untouched.
FROM = "$from"


class UnresolvedBinding(LookupError):
    """A reference names a step that produced nothing — because it failed, was skipped,
    or produced no such key. The dependent step is skipped rather than run with a hole
    in its params: sending a message with a missing channel is worse than not sending."""


def is_binding(value: Any) -> bool:
    return isinstance(value, dict) and set(value.keys()) == {FROM}


def parse_ref(ref: str) -> tuple[str, str]:
    """``"step1.ts"`` → ``("step1", "ts")``. Splits on the FIRST dot only, so a key may
    contain dots without needing an escape."""
    alias, _, key = str(ref).partition(".")
    return alias.strip(), key.strip()


def collect_refs(params: Any) -> list[str]:
    """Every reference inside `params`, at any depth. Used by validation and by the
    canvas, which needs the same edges the engine will follow — two readers deriving
    the graph differently is how a picture and its run come to disagree."""
    out: list[str] = []
    if is_binding(params):
        out.append(str(params[FROM]))
    elif isinstance(params, dict):
        for v in params.values():
            out.extend(collect_refs(v))
    elif isinstance(params, (list, tuple)):
        for v in params:
            out.extend(collect_refs(v))
    return out


def resolve(params: Any, context: dict[str, dict]) -> Any:
    """Replace every binding in `params` with its value from `context`.

    Raises :class:`UnresolvedBinding` when a reference cannot be satisfied. Raising
    rather than substituting a default is deliberate: a default would let a step run
    with a silently wrong value, and these steps send messages and write to systems.
    """
    if is_binding(params):
        alias, key = parse_ref(params[FROM])
        produced = context.get(alias)
        if produced is None:
            raise UnresolvedBinding(f"step '{alias}' produced nothing to read")
        if key not in produced:
            raise UnresolvedBinding(f"step '{alias}' has no '{key}' (it produced: "
                                    f"{', '.join(sorted(produced)) or 'nothing'})")
        return produced[key]
    if isinstance(params, dict):
        return {k: resolve(v, context) for k, v in params.items()}
    if isinstance(params, list):
        return [resolve(v, context) for v in params]
    return params


def alias_for(effect: Any, index: int) -> str:
    """A step's name: its own `alias`, else its 1-based position (`step1`, `step2`, …).

    Positional by default so an automation written before VA-4a gains referable steps
    without being rewritten, and so a reference reads the way a person counts.
    """
    return (getattr(effect, "alias", "") or "").strip() or f"step{index + 1}"


#: B1 — what each effect kind PUBLISHES into the chain context, DECLARED.
#:
#: `EffectOutcome.data` is what a step actually published; this is what a step MAY.
#: The split exists because the design surface needs an answer before any run has
#: happened — the execution graph's `produced` is real but arrives too late to draw a
#: port on an unsaved step. ``None`` means an OPEN set: a declared-action step
#: publishes whatever that action's outcome carries, which this module cannot
#: enumerate, so bindings onto it are accepted unchecked rather than wrongly refused.
#:
#: A kind mapped to ``()`` publishes nothing — measured off the dispatchers, which is
#: the only honest source: `notify`/`brief`/`monitor`/`agent_alert` return outcomes
#: with no ``data`` at all, so a binding onto them can never resolve and is refused at
#: SAVE (the whole point of B1: the unknown KEY used to surface at 09:00 as a skipped
#: step, a stack of honest machinery adding up to a silent no-op).
PUBLISHED_KEYS: dict[str, Optional[tuple[str, ...]]] = {
    "investigate":    ("investigation_id", "answer"),
    "slack_post":     ("ts", "channel"),
    "kinetic_action": None,
    "notify":         (),
    "brief":          (),
    "monitor":        (),
    "agent_alert":    (),
}

#: B1 — the config fields a step may BIND (`{"$from": …}`) per kind: the input ports.
#: Only fields whose consumption is a string the dispatcher reads; enumerated rather
#: than "any field", because an edge onto a field nothing reads is a picture of
#: dataflow the engine does not have.
BINDABLE_FIELDS: dict[str, tuple[str, ...]] = {
    "investigate":    ("question",),
    "slack_post":     ("message", "thread_ts", "channel"),
    "notify":         ("message",),
    "brief":          (),
    "kinetic_action": ("params",),
    "monitor":        (),
    "agent_alert":    (),
}


def validate_chain(effects: list) -> Optional[str]:
    """The error message for an unsatisfiable chain, or None when it is sound.

    Checked at CONSTRUCTION, which is the whole point: an automation whose step 2 reads
    a step that does not exist must be refused when it is saved, not discovered on a
    schedule with nobody watching.

    Two failures are distinguished because they are different mistakes:
      * **unknown step** — a typo, or a step someone deleted;
      * **forward/self reference** — a chain that would need to run backwards. Naming a
        LATER step is not a missing value, it is an impossible order, and saying so is
        the difference between a user fixing a name and a user fixing their mental model.
    """
    seen: dict[str, str] = {}   # alias → effect kind, for the key check above
    for i, effect in enumerate(effects):
        alias = alias_for(effect, i)
        for ref in collect_refs(getattr(effect, "config", {}) or {}):
            target, _ = parse_ref(ref)
            if target == alias:
                return f"step '{alias}' refers to itself ({ref})"
            if target in seen:
                # B1 — the KEY, not only the step. An unknown key used to pass every
                # save-time check and surface at 09:00 as a skipped step. Checked only
                # for kinds with a CLOSED declared set; `None` (the declared-action kind) stays
                # unchecked because its keys are the action's own outcome shape.
                producer = seen[target]
                declared = PUBLISHED_KEYS.get(producer)
                key = parse_ref(ref)[1]
                if declared is not None and key not in declared:
                    have = f" — it publishes {', '.join(declared)}" if declared else                         " — it publishes nothing"
                    return (f"step '{alias}' binds to '{ref}', but a "
                            f"{producer} step has no '{key}'{have}")
                continue
            later = {alias_for(e, j) for j, e in enumerate(effects) if j > i}
            if target in later:
                return (f"step '{alias}' refers to '{ref}', which runs AFTER it — "
                        f"a chain cannot run backwards")
            return f"step '{alias}' refers to unknown step '{target}' ({ref})"
        seen[alias] = getattr(effect, "kind", "")
    return None
