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


def _clause_side(clause: Any, side: str) -> Any:
    """One side of a guard clause, whether it arrived as a model or a raw dict."""
    return clause.get(side) if isinstance(clause, dict) else getattr(clause, side, None)


def guard_clauses(effect: Any) -> list:
    return list(getattr(effect, "when", None) or [])


def effect_refs(effect: Any) -> list[str]:
    """Every reference ONE STEP makes — its bound config AND its ``when`` guard.

    W1 — **a guard is dataflow too.** Three readers derive the chain from references and
    each would answer differently if the guard's path were walked by only some of them:

    * ``validate_chain`` — is this sound? A guard onto a deleted step would save fine.
    * ``_downstream_binds`` — must this step be waited FOR? An ``investigate`` consumed
      only by a downstream guard would hand it a *job id* instead of an answer, and the
      guard would read a truthy string forever.
    * ``build_graph`` — what does the canvas draw? An arrow the engine follows and the
      picture omits is the disagreement VA-4a exists to prevent.

    So they all read this, and the guard cannot become a fourth, invisible dataflow.
    """
    refs = collect_refs(getattr(effect, "config", {}) or {})
    for clause in guard_clauses(effect):
        refs.extend(collect_refs(_clause_side(clause, "left")))
        refs.extend(collect_refs(_clause_side(clause, "right")))
    return refs


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


# ── W1: the guard ────────────────────────────────────────────────────────────────
#
# Until now a step could only be skipped by an ABSENCE — a binding that would not
# resolve. "Post it only if there is something worth posting" was not expressible, so
# a chain either sent an empty report every morning or was not automated at all.
#
# A guard is a small STRUCTURAL predicate over the same context bindings read from,
# never an expression string. The reasons are this module's own, unchanged: a string
# would need a parser (an injection surface), could not be validated at save, and
# could not be drawn. `{"left": {"$from": "step1.answer"}, "op": "truthy"}` is all
# three — checkable, inert, and an edge on the canvas.

#: The closed set of comparisons, and how each READS on a surface. Exposed through
#: `/automations/vocabulary` so the authoring UI offers exactly what the engine can
#: evaluate: a hand-copied mirror of this list would rot in the worst direction —
#: an operator the picker offers and the engine refuses.
GUARD_OPS: dict[str, str] = {
    "truthy":   "is set",
    "falsy":    "is empty",
    "eq":       "is",
    "ne":       "is not",
    "gt":       ">",
    "gte":      "≥",
    "lt":       "<",
    "lte":      "≤",
    "contains": "contains",
}

#: Operators that read ONE side. `right` is ignored for these rather than rejected:
#: an authoring UI that switches op on a filled-in form should not have to erase a
#: field to stay valid.
UNARY_OPS: tuple[str, ...] = ("truthy", "falsy")

#: The prefix every guard skip carries. One writer (the engine), and `graph.py` reads
#: THIS constant rather than sniffing for the words — a matching key that stops
#: matching is how a guard goes quietly blind.
GUARD_SKIP = "condition not met"


class GuardUnevaluable(ValueError):
    """The comparison cannot be made — ``"n/a" > 5``, or ``contains`` on a number.

    Skipped, never guessed. Treating an unevaluable guard as *false* would silently
    stop a chain, and as *true* would run the step the guard exists to prevent; both
    look identical in run history to a guard that simply did not match.
    """


def _numeric(value: Any) -> Optional[float]:
    """A number, or None. A warehouse column arrives as a string often enough that
    refusing ``"12" > 5`` would make the guard useless on real data — but `bool` is
    an `int` in Python, and `True > 0` is a comparison nobody wrote on purpose."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def render_clause(clause: Any) -> str:
    """A clause as a short sentence — reference PATHS and authored literals only.

    Never a resolved value. A guard may read a message body, a thread id or whatever
    an action published, and this string is written into run history and drawn on the
    canvas; `graph.py` carries a no-spill test for exactly that reason. "step1.answer
    is empty" says which clause held without saying what it read.
    """
    def side(value: Any) -> str:
        if is_binding(value):
            return str(value[FROM])
        text = str(value)
        return text if len(text) <= 40 else text[:39] + "…"

    op = _clause_side(clause, "op") or ""
    label = GUARD_OPS.get(str(op), str(op))
    left = side(_clause_side(clause, "left"))
    if op in UNARY_OPS:
        return f"{left} {label}"
    return f"{left} {label} {side(_clause_side(clause, 'right'))}"


def _clause_holds(op: str, left: Any, right: Any) -> bool:
    if op == "truthy":
        return bool(left)
    if op == "falsy":
        return not bool(left)
    if op == "eq":
        return left == right
    if op == "ne":
        return left != right
    if op == "contains":
        if isinstance(left, str):
            return str(right) in left
        if isinstance(left, (list, tuple, dict, set)):
            return right in left
        raise GuardUnevaluable(f"{type(left).__name__} does not contain things")
    a, b = _numeric(left), _numeric(right)
    if a is None or b is None:
        raise GuardUnevaluable(f"'{op}' needs two numbers")
    return {"gt": a > b, "gte": a >= b, "lt": a < b, "lte": a <= b}[op]


def evaluate_guard(effect: Any, context: dict[str, dict]) -> tuple[bool, str]:
    """``(should this step run, why not)`` for one effect's ``when`` guard.

    An empty guard runs — which is every automation written before W1, byte for byte.

    Raises :class:`UnresolvedBinding` when a clause reads a step that produced nothing,
    deliberately sharing the params path's outcome: the step is skipped and the message
    names the missing upstream. A guard is not a place to be lenient about absence — the
    steps behind it send messages and write to systems.
    """
    clauses = guard_clauses(effect)
    if not clauses:
        return True, ""
    logic = str(getattr(effect, "when_logic", "") or "all")
    results: list[tuple[bool, str]] = []
    for clause in clauses:
        op = str(_clause_side(clause, "op") or "")
        left = resolve(_clause_side(clause, "left"), context)
        right = None if op in UNARY_OPS else resolve(_clause_side(clause, "right"), context)
        try:
            held = _clause_holds(op, left, right)
        except GuardUnevaluable as exc:
            # Unevaluable is a HOLD, and says so in its own words: "cannot compare" is a
            # different fix from "did not match", and a reader who is told the wrong one
            # goes looking at the wrong step.
            return False, f"{render_clause(clause)} — cannot compare ({exc})"
        results.append((held, render_clause(clause)))
    if logic == "any":
        if any(held for held, _ in results):
            return True, ""
        return False, " or ".join(text for _, text in results)
    failed = [text for held, text in results if not held]
    if failed:
        return False, " and ".join(failed)
    return True, ""


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
        # W1 — `effect_refs`, not `collect_refs(config)`: a guard reads the context too,
        # and a guard onto a step that does not exist must be refused at SAVE like any
        # other reference. Before this, `when` was the one dataflow path nothing checked.
        for ref in effect_refs(effect):
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
