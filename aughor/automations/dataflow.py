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

#: DS-6 — the JOIN's marker: the first of several references that resolves. Written
#: `{"$from_any": ["alerts.ts", "daily.ts"]}` and resolved in AUTHORED order, it is what
#: lets one step run after either branch of a route: the arms are mutually exclusive, so
#: at most one alternative ever resolves, and a step downstream of both reads whichever
#: arm actually ran. Same exact-one-key rule as FROM — and every alternative is validated
#: at save like an ordinary reference, so the join cannot name a step or key the chain
#: does not have. Deliberately NOT a second resolution mechanism: each alternative is an
#: ordinary `alias.key` against the same accumulated context.
FROM_ANY = "$from_any"


class UnresolvedBinding(LookupError):
    """A reference names a step that produced nothing — because it failed, was skipped,
    or produced no such key. The dependent step is skipped rather than run with a hole
    in its params: sending a message with a missing channel is worse than not sending."""


def is_binding(value: Any) -> bool:
    return isinstance(value, dict) and set(value.keys()) == {FROM}


def is_any_binding(value: Any) -> bool:
    """A WELL-FORMED join binding: exactly the one key, and a non-empty list of
    non-empty strings. A dict wearing the key with a malformed value is neither a
    binding nor a payload anyone meant — `validate_chain` refuses it at save and
    :func:`resolve` refuses it at run, so it can never pass silently as a literal."""
    if not (isinstance(value, dict) and set(value.keys()) == {FROM_ANY}):
        return False
    refs = value[FROM_ANY]
    return (isinstance(refs, list) and len(refs) > 0
            and all(isinstance(r, str) and r.strip() for r in refs))


def _wears_any_key(value: Any) -> bool:
    """Exactly the one key — well-formed or not. The malformed case must be REFUSED,
    never recursed into as an ordinary payload (a join that quietly became a literal
    dict would be this plane's worst failure: well-formed and wrong)."""
    return isinstance(value, dict) and set(value.keys()) == {FROM_ANY}


def parse_ref(ref: str) -> tuple[str, str]:
    """``"step1.ts"`` → ``("step1", "ts")``. Splits on the FIRST dot only, so a key may
    contain dots without needing an escape."""
    alias, _, key = str(ref).partition(".")
    return alias.strip(), key.strip()


def collect_refs(params: Any) -> list[str]:
    """Every reference inside `params`, at any depth. Used by validation and by the
    canvas, which needs the same edges the engine will follow — two readers deriving
    the graph differently is how a picture and its run come to disagree.

    DS-6 — a join contributes EVERY alternative: each one must exist to be refused or
    awaited or drawn, even though only one of them will resolve on any given run.
    """
    out: list[str] = []
    if is_binding(params):
        out.append(str(params[FROM]))
    elif is_any_binding(params):
        out.extend(str(r) for r in params[FROM_ANY])
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


def effect_config(effect: Any) -> dict:
    """A step's ``config``, whether it arrived as a model or a raw dict."""
    cfg = effect.get("config") if isinstance(effect, dict) else getattr(effect, "config", None)
    return cfg or {}


def guard_clauses(effect: Any) -> list:
    clauses = effect.get("when") if isinstance(effect, dict) else getattr(effect, "when", None)
    return list(clauses or [])


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
    refs = collect_refs(effect_config(effect))
    for clause in guard_clauses(effect):
        refs.extend(collect_refs(_clause_side(clause, "left")))
        refs.extend(collect_refs(_clause_side(clause, "right")))
    # W2 — and the LIST it fans out over, for the same three readers: a `for_each`
    # bound to a deleted step must be refused at save, the step it reads must be
    # awaited (an `investigate` feeding a fan-out would otherwise hand it a job id),
    # and the canvas must draw the edge the engine follows.
    refs.extend(collect_refs(fan_source(effect)))
    # `item.*` is resolved per ITERATION against the item, not against the chain, so it
    # is not a chain reference at all. Filtered here rather than at each caller: three
    # readers walking this list would otherwise each have to know about the loop, and
    # the one that forgot would report the item as an unknown step.
    return [r for r in refs if parse_ref(r)[0] != ITEM_ALIAS]


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
    if is_any_binding(params):
        # DS-6 — the first alternative that resolves wins, in AUTHORED order. Down a
        # route the arms are mutually exclusive so at most one can; outside one this is
        # an honest preference order, and the drawn edges show every candidate either
        # way. Only when NONE resolves is the step skipped — which is what "no branch
        # was taken" must read as, not run-with-a-hole.
        refs = [str(r) for r in params[FROM_ANY]]
        for ref in refs:
            alias, key = parse_ref(ref)
            produced = context.get(alias)
            if produced is not None and key in produced:
                return produced[key]
        raise UnresolvedBinding(
            f"none of {', '.join(refs)} produced a value to read")
    if _wears_any_key(params):
        # Refused at save; refused again here so a malformed join that somehow reaches
        # a run can never pass downstream as a literal dict.
        raise UnresolvedBinding(
            f"'{FROM_ANY}' needs a non-empty list of \"step.key\" references")
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

#: DS-6 — the prefix a route's untaken arm carries. Its own constant, not a GUARD_SKIP
#: variant, because they are different facts a reader needs told apart at 09:00: "held ·
#: condition not met" is a step whose own guard said no; "not taken" is the OTHER path
#: of a decision that went the first way — the design working, one branch over. Same
#: one-writer rule: `graph.py` reads this constant, never the prose.
BRANCH_SKIP = "branch not taken"


def else_target(effect: Any) -> str:
    """DS-6 — the step this one runs OTHERWISE of, or ``"" `` when it is unrouted.

    Reads models and raw dicts alike, like :func:`fan_source` and for the same reason:
    the graph and the routers hand this module unvalidated payloads from the authoring
    surface, and a picture that could only be drawn for a saved automation is drawn too
    late.
    """
    val = (effect.get("else_of") if isinstance(effect, dict)
           else getattr(effect, "else_of", ""))
    return str(val or "").strip()


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
        if is_any_binding(value):
            # The join, as the reader authored it: every candidate, oldest first. The
            # sentence stays paths-only like the rest of this renderer.
            return " or ".join(str(r) for r in value[FROM_ANY])
        # An empty literal must still OCCUPY the sentence. Found live: a guard written
        # against `""` rendered as "condition not met:  is set" — a hole where the
        # subject belongs, which reads as a bug in the renderer rather than as the
        # comparison someone wrote.
        if value is None:
            return "nothing"
        if value == "":
            return '""'
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


def evaluate_guard_verdict(effect: Any, context: dict[str, dict]) \
        -> tuple[Optional[bool], str]:
    """``(verdict, why not)`` for one effect's ``when`` guard — three-valued.

    ``True`` runs the step, ``False`` holds it, and ``None`` means the comparison could
    not be MADE (``"n/a" > 5``). The three-way split exists for DS-6: a route sends the
    OTHERWISE arm down exactly the ``False`` path, and folding "cannot compare" into it
    would turn an unevaluable guard into a decision — running the branch the guard's
    author reserved for "the condition did not hold", on a morning when nothing was
    decided at all. Skipped-never-guessed, W1's own rule, extended to the route.

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
            return None, f"{render_clause(clause)} — cannot compare ({exc})"
        results.append((held, render_clause(clause)))
    if logic == "any":
        if any(held for held, _ in results):
            return True, ""
        return False, " or ".join(text for _, text in results)
    failed = [text for held, text in results if not held]
    if failed:
        return False, " and ".join(failed)
    return True, ""


def evaluate_guard(effect: Any, context: dict[str, dict]) -> tuple[bool, str]:
    """``(should this step run, why not)`` — the two-valued reading every pre-DS-6
    caller keeps: unevaluable HOLDS the step, exactly as W1 shipped it."""
    verdict, why_not = evaluate_guard_verdict(effect, context)
    return verdict is True, why_not


# ── W2: the fan-out ──────────────────────────────────────────────────────────────
#
# The engine ran a strictly sequential list — one step, one dispatch — so "post a
# summary per region" was written as three near-identical steps or not automated. W2
# binds one step to a list and runs it once per item.
#
# It is deliberately the SAME dataflow, not a second one: the item is published under
# a reserved alias into the same accumulated context every binding already resolves
# against, so `resolve` needed no change, the canvas draws the source as an ordinary
# edge, and the engine awaits a producer feeding a fan-out for the same reason it
# awaits one feeding a param (VA-13's rule, one field over).

#: The alias each iteration publishes its item under. A dict item is read field-wise
#: (`{"$from": "item.channel"}`); a scalar arrives as `{"$from": "item.value"}`, so the
#: two shapes are one shape by the time a param resolves.
ITEM_ALIAS = "item"

#: The key a scalar item is published under. Named rather than positional because
#: `{"$from": "item"}` alone cannot say "the whole item" in a syntax whose every
#: reference is `alias.key`.
ITEM_VALUE = "value"

#: The most items one step may fan out over. A cap on SENDS, not on compute: these
#: steps post messages and write to systems, and an unbounded fan-out is how one
#: automation becomes an incident. Exceeding it REFUSES the step — never truncates it,
#: because posting the first N of a longer list and dropping the rest silently is the
#: failure a cap exists to prevent.
MAX_FAN_OUT = 50

#: What a fanned step publishes into the chain, whatever its kind: how many iterations
#: executed. Its per-item values are NOT bindable — there are N of them and a
#: downstream `{"$from": "step2.ts"}` could only mean one, which is exactly the kind of
#: silent hole this plane refuses at save.
FAN_PUBLISHED: tuple[str, ...] = ("count",)

#: The prefix a fan-out skip carries when the list is empty. One writer, read by
#: surfaces rather than sniffed for — a matching key that stops matching is how a
#: reader goes quietly blind (GUARD_SKIP's lesson, same file).
FAN_EMPTY_SKIP = "nothing to iterate"


def fan_source(effect: Any) -> Any:
    """The list a step runs once per item of, or ``None`` when it runs exactly once.

    Reads models and raw dicts alike: `graph.py` and the routers hand this module
    unvalidated payloads from the authoring surface, and a picture that could only be
    drawn for a saved automation is a picture drawn too late.
    """
    fe = effect.get("for_each") if isinstance(effect, dict) else getattr(effect, "for_each", None)
    if fe is None:
        return None
    return fe.get("source") if isinstance(fe, dict) else getattr(fe, "source", None)


def is_fanned(effect: Any) -> bool:
    return fan_source(effect) is not None


def item_context(item: Any) -> dict[str, Any]:
    """One iteration's item, as a context entry. A dict is itself; anything else is
    published under :data:`ITEM_VALUE`."""
    return dict(item) if isinstance(item, dict) else {ITEM_VALUE: item}


class FanRefused(ValueError):
    """A ``for_each`` source this engine will not iterate.

    Two cases, and both are the step's own fault rather than an upstream absence — which
    is why they read as ``invalid_params`` and not as ``skipped``: a source that is not a
    list (iterating ``"EMEA"`` would send four messages, one per character), and one
    longer than :data:`MAX_FAN_OUT`.
    """


def fan_items(effect: Any, context: dict[str, dict], *,
              dry_item: Optional[dict] = None) -> Optional[list]:
    """The items a step runs once per, or ``None`` when it runs exactly once.

    A literal list passes through :func:`resolve` like any other params structure, so a
    list may itself hold bindings (``["EMEA", {"$from": "step1.answer"}]``) without this
    function knowing anything new.

    ``dry_item`` is B2's lesson one field over: a preview's context holds SAMPLE strings,
    never the list tomorrow will produce, so resolving a BOUND source under a dry run
    would report a sound design as "for_each needs a list". Given one, a preview walks a
    single representative iteration instead; a LITERAL source is walked for real, because
    the items are known now and "would post 3 messages: EMEA, NA, APAC" is the answer a
    preview exists to give.
    """
    src = fan_source(effect)
    if src is None:
        return None
    if dry_item is not None and is_binding(src):
        return [dry_item]
    items = resolve(src, context)
    if isinstance(items, str) or not isinstance(items, list):
        got = type(items).__name__
        detail = " (a string runs once per character)" if isinstance(items, str) else ""
        raise FanRefused(f"for_each needs a list to run over — got {got}{detail}")
    if len(items) > MAX_FAN_OUT:
        raise FanRefused(
            f"for_each over {len(items)} items exceeds the {MAX_FAN_OUT}-item cap — "
            "refused rather than truncated, because a partial send reads as a whole one")
    return items


def item_refs(effect: Any) -> list[str]:
    """The step's references to its own iteration item — legal only when it is fanned."""
    refs = collect_refs(effect_config(effect))
    for clause in guard_clauses(effect):
        refs.extend(collect_refs(_clause_side(clause, "left")))
        refs.extend(collect_refs(_clause_side(clause, "right")))
    return [r for r in refs if parse_ref(r)[0] == ITEM_ALIAS]


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
    # `answer` is the run's headline — a title. `summary` is the report's executive
    # summary — the trust warnings and the numbers. A briefing chain wants the second;
    # both keep the absent-when-empty rule, so binding to either on a run that produced
    # neither skips the dependent step with a reason instead of posting "".
    "investigate":    ("investigation_id", "answer", "summary"),
    "slack_post":     ("ts", "channel"),
    "kinetic_action": None,
    "notify":         (),
    "brief":          (),
    "monitor":        (),
    "agent_alert":    (),
    # DS-9 — what a nested chain tells the steps after it. Facts ABOUT the child run, not
    # the child's own step outputs: a chain publishes no single value (it may have five
    # steps), and inventing one would make `{"$from": "sub.answer"}` mean whichever step
    # the child happened to end on. `executed` is the count a guard can read — "post the
    # summary only if the shared subchain actually did something".
    "subchain":       ("run_id", "outcome", "executed"),
    # DS-11 — ``None`` at the KIND level because the honest answer is per OPERATION: a
    # step that lists Gmail messages publishes `items`/`count`, one that reads a message
    # publishes `snippet`. `published_keys(effect)` below returns that closed set, and it
    # is what every validator reads; this entry is the fallback for a step whose operation
    # is not (yet) in the roster.
    "integration_call": None,
    # DS-12 — a governed number, its unit and its label. Closed, because unlike an
    # operation roster there is exactly one shape: every metric answers with a value.
    "metric_value":   ("value", "unit", "label"),
    # DS-12 — and the first CLOSED set in this plane that contains a LIST. `rows` is
    # what a `for_each` fans over; `columns` and `count` describe it without anyone
    # having to iterate to find out. See LIST_PUBLISHED below — declaring the key is
    # not enough on its own, because a closed set is otherwise refused as a fan source.
    "trusted_query":  ("rows", "columns", "count"),
    # VA-9d — a foreign tool's TEXT, plus whether we had to cut it. Closed and small on
    # purpose: this slice carries only text blocks (an image flattened into a chain context
    # is a megabyte no downstream step can read), and `truncated` is published rather than
    # implied so a step reading `text` can tell a whole answer from half of one.
    "mcp_call":       ("text", "truncated"),
}

#: DS-12 — the published keys that are LISTS, and may therefore be fanned over.
#:
#: §3.2 carried this as an honest limit for three waves: "NOTHING in this plane
#: publishes a list", so a `for_each` source could only be a literal list or a binding
#: onto the one OPEN published set. That was not a policy — it was an inventory, and
#: `validate_chain` encoded it by refusing every closed set as a fan source, correctly,
#: because every closed set in this plane was strings.
#:
#: A trusted query publishes rows. Rather than reopen the set — which would give up the
#: save-time refusal that makes an unknown key a design error instead of a 09:00
#: surprise — the LIST-ness is declared beside the keys, so a fan over `q.rows` is
#: accepted and a fan over `q.count` is still refused.
#:
#: DS-11 closed the same limit from the other side, per OPERATION, and its
#: `list_published_keys()` is the one function every validator asks. This table is that
#: function's answer for the kinds whose list-ness is a property of the KIND rather than
#: of an operation — read BY it, never beside it, because two places that both say which
#: keys are lists is two places that will disagree.
LIST_PUBLISHED: dict[str, tuple[str, ...]] = {
    "trusted_query": ("rows",),
}


def publishes_list(kind: str, key: str) -> bool:
    """Is ``kind``'s published ``key`` a list a step may run once per item of?"""
    return key in LIST_PUBLISHED.get(kind, ())

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
    # DS-9 — nothing. A child chain has no input port to bind INTO: it reads its own
    # config, and there is no mechanism by which a parent's value would reach one of its
    # steps. Declaring a bindable field here would draw an edge the engine does not
    # follow, which is the exact picture B1 exists to prevent.
    "subchain":       (),
    # DS-11 — the params bag, exactly as `kinetic_action` carries it: the individual
    # inputs are the OPERATION's (a channel, a message id, a body), so the port a chain
    # binds into is a key inside `params` and `collect_refs` walks it. Naming the inputs
    # here instead would be a second, per-kind copy of a per-operation fact.
    "integration_call": ("params",),
    # DS-12 — neither takes an input. Both name a governed object and read it; there is
    # no field an upstream value could reach, which is the point: a metric a chain could
    # re-point at runtime would not be the governed metric any more.
    "metric_value":   (),
    "trusted_query":  (),
    # VA-9d — the arguments bag, exactly as `integration_call` carries its `params`: the
    # individual inputs are the TOOL's (its own JSON Schema), so the port a chain binds
    # into is a key inside `arguments` and `collect_refs` walks it.
    #
    # ⚠️ `server_id` and `tool` are deliberately NOT bindable, and this is the DS-11 trap
    # restated: `BINDABLE_FIELDS` DECLARES the input ports, but `resolve()` walks the WHOLE
    # config, so every kind in this plane will happily substitute a binding into a field
    # its tuple omits. Harmless on a channel name; not harmless on the two fields that
    # choose WHICH third party gets called — an upstream value reaching them would turn a
    # named destination back into an arbitrary one. Refused on the model, where a save
    # actually fails.
    "mcp_call":       ("arguments",),
}


def effect_kind(effect: Any) -> str:
    """A step's ``kind``, whether it arrived as a model or a raw dict."""
    return str((effect.get("kind") if isinstance(effect, dict)
                else getattr(effect, "kind", "")) or "")


def _operation_of(effect: Any):
    """The declared operation an ``integration_call`` step names, or None.

    Imported inside the function so the automation vocabulary can be read without
    dragging the integrations plane into memory — the containment `palette._prereqs`
    already uses on its stores, for the same reason.
    """
    from aughor.integrations.operations import get_operation
    return get_operation(str(effect_config(effect).get("operation", "")))


def published_keys(effect: Any) -> Optional[tuple[str, ...]]:
    """What ONE STEP publishes: a closed tuple, or ``None`` for the open set.

    DS-11 made this a function rather than a dict lookup. Every kind before it published
    the same keys on every instance, so a table keyed by kind WAS the answer; an
    integration step's keys are its operation's, which is a per-instance fact known at
    save time. That is a strict gain, not a complication: `integration_call` is the first
    kind whose remote outputs B1 can refuse an unknown key against, where the open-set
    treatment (`kinetic_action`) has to accept anything.

    An operation the roster does not know falls back to the OPEN set rather than to
    "publishes nothing", so one refusal is reported once — `validate_chain` names the
    unknown operation itself — instead of as a cascade of bindings onto a step that
    "publishes nothing".
    """
    if effect_kind(effect) == "integration_call":
        op = _operation_of(effect)
        return op.publishes if op is not None else None
    return PUBLISHED_KEYS.get(effect_kind(effect))


def list_published_keys(effect: Any) -> tuple[str, ...]:
    """Which of a step's published keys are LISTS — the ones `for_each` may fan over.

    Empty for every kind that existed before DS-11, which is W2's measured premise
    restated as code: *nothing in this plane published a list*, so a fan source could
    only ever be a literal list or a binding onto the one open-set kind. A remote read
    is the first honest list, and it says so here rather than by being open-set — an
    open set would let a fan-out onto `snippet` through as well.
    """
    if effect_kind(effect) == "integration_call":
        op = _operation_of(effect)
        return op.list_keys if op is not None else ()
    # DS-12 — a trusted query's `rows`. Answered here rather than from a second table
    # keyed by kind: two places that both say which keys are lists is two places that
    # will disagree, and this one is already what every validator reads.
    return LIST_PUBLISHED.get(effect_kind(effect), ())


def _malformed_any(value: Any) -> Optional[str]:
    """The first malformed join binding anywhere in `value`, as a sentence — or None.

    A dict wearing exactly the `$from_any` key with anything but a non-empty list of
    reference strings is refused at SAVE: recursing into it as an ordinary payload would
    let a mistyped join pass every check and arrive at 09:00 as a literal dict in a
    message body — well-formed, wrong, and silent.
    """
    if _wears_any_key(value):
        if not is_any_binding(value):
            return (f"'{FROM_ANY}' needs a non-empty list of \"step.key\" references — "
                    f"got {type(value[FROM_ANY]).__name__}")
        return None
    if isinstance(value, dict):
        for v in value.values():
            problem = _malformed_any(v)
            if problem:
                return problem
    elif isinstance(value, (list, tuple)):
        for v in value:
            problem = _malformed_any(v)
            if problem:
                return problem
    return None


def _mcp_problem(effect: Any, alias: str) -> Optional[str]:
    """A ``mcp_call`` step naming a server or tool this deployment cannot use, as a
    sentence — or None. Non-MCP steps are always fine here.

    Four refusals, all at SAVE, and all of them things the engine would otherwise discover
    at 07:00 against somebody else's machine.

    The first is the DS-11 trap restated, and it matters MORE here than it did there.
    `BINDABLE_FIELDS` declares `arguments` as this kind's only input port, but it DECLARES —
    `resolve()` walks the whole config — so a `{"$from": …}` on `server_id` would be
    substituted at run time and the step would call whichever third party an upstream value
    happened to name. That is not a worse version of the existing behaviour; it is an
    arbitrary-destination call wearing a named one's clothes, which is exactly what the
    allowlist exists to prevent.
    """
    if effect_kind(effect) != "mcp_call":
        return None
    from aughor.mcpservers import store as mcp_store
    from aughor.mcpservers.discover import tool_named
    from aughor.mcpservers.models import CALLABLE, GRANT_ACTIVE, GRANT_STALE, grant_verdict

    cfg = effect_config(effect)
    for field in ("server_id", "tool"):
        if not isinstance(cfg.get(field), str):
            return (f"step '{alias}' binds '{field}' — which server a step calls and which "
                    f"tool it calls there must be written, not read from an earlier step")

    server_id = str(cfg.get("server_id", ""))
    server = mcp_store.get_server(server_id)
    if server is None:
        known = ", ".join(s.name or s.id for s in mcp_store.list_servers())
        return (f"step '{alias}' names MCP server '{server_id}', which is not on this "
                f"deployment's allowlist — it has {known or 'no servers registered'}")

    tool_name = str(cfg.get("tool", ""))
    tool = tool_named(server_id, tool_name)
    if tool is None:
        return (f"step '{alias}' names tool '{tool_name}' on '{server.name or server_id}', "
                f"which its discovered roster does not have — run Discover if the server "
                f"has changed")
    if tool.disposition != CALLABLE:
        # Not callable on the server's word — so the step is legal only if a person granted
        # this tool. Checked at SAVE for the same reason as everything else here: a chain
        # that would always refuse at 07:00 is one that "looks schedulable", which is K1's
        # expensive kind of broken. The door checks again; this is the early sentence.
        state, why = grant_verdict(tool, mcp_store.get_grant(server_id, tool_name))
        if state == GRANT_STALE:
            return (f"step '{alias}' calls '{tool_name}', and its grant no longer covers "
                    f"what that tool declares: {why}")
        if state != GRANT_ACTIVE:
            # The roster's own sentence, at save.
            return (f"step '{alias}' calls '{tool_name}', which this deployment refuses: "
                    f"{tool.reason}")
    return None


def _integration_problem(effect: Any, alias: str) -> Optional[str]:
    """An ``integration_call`` step naming something the roster does not have, as a
    sentence — or None. Non-integration steps are always fine here.

    Two refusals, both at SAVE: an unknown OPERATION (the reference the whole kind is
    built on), and an undeclared INPUT. The second is the same refusal `build_request`
    makes at run time, moved to where it costs nothing: a param named `cc` that no
    operation reads is a message the author believes was copied to someone.
    """
    if effect_kind(effect) != "integration_call":
        return None
    from aughor.integrations.operations import OPERATIONS, get_operation

    cfg = effect_config(effect)
    # WHICH connection and WHICH operation are authored decisions, refused here when they
    # are not. `BINDABLE_FIELDS` declares `params` as this kind's only input port, but it
    # DECLARES — `resolve()` walks the whole config, so a `{"$from": …}` on `connection_id`
    # would be substituted at 07:00 and the step would spend whatever grant an upstream
    # value happened to name. Harmless on an org-scoped `bot_id`; not harmless on a
    # credential selector, which is why it is refused where a save actually fails.
    for field in ("connection_id", "operation"):
        if not isinstance(cfg.get(field), str):
            return (f"step '{alias}' binds '{field}' — which account a step spends and "
                    f"what it spends it on must be written, not read from an earlier step")
    op_id = str(cfg.get("operation", ""))
    op = get_operation(op_id)
    if op is None:
        known = ", ".join(o.id for o in OPERATIONS)
        return (f"step '{alias}' names integration operation '{op_id}', which this "
                f"deployment does not have — it offers {known}")
    params = cfg.get("params")
    if isinstance(params, dict):
        declared = {p.name for p in op.params}
        for key in params:
            if key not in declared:
                return (f"step '{alias}' sets '{key}', but '{op.id}' has no such input — "
                        f"it takes {', '.join(sorted(declared)) or 'no inputs'}")
    return None


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
    # DS-11 — alias → the EFFECT, not its kind. The key check reads `published_keys`,
    # which is per-step now that an integration step's outputs are its operation's.
    seen: dict[str, Any] = {}
    fanned: set[str] = set()    # W2 — aliases that run once per item
    guarded: set[str] = set()   # DS-6 — aliases with a non-empty `when`, routable-from
    for i, effect in enumerate(effects):
        alias = alias_for(effect, i)
        # DS-6 — a malformed join must not recurse past as an ordinary payload.
        for candidate in ([effect_config(effect), fan_source(effect)]
                          + [_clause_side(c, s) for c in guard_clauses(effect)
                             for s in ("left", "right")]):
            problem = _malformed_any(candidate)
            if problem:
                return f"step '{alias}': {problem}"
        # DS-11 — the OPERATION is a reference like any other, so it is refused at save.
        # An unknown one used to be unreachable (there was no such kind); leaving it
        # unchecked would make it the one reference in this plane that surfaces at 09:00
        # as a provider's 404 — K1's rule inverted, and B1's whole argument one field over.
        problem = _integration_problem(effect, alias)
        if problem:
            return problem
        # VA-9d — the same argument, across a boundary that leaves the platform. A step
        # naming a server nobody allowlisted, or a tool this deployment refuses, is refused
        # at save rather than at 07:00 against a third party's machine.
        problem = _mcp_problem(effect, alias)
        if problem:
            return problem
        # DS-6 — the route. "Otherwise of s2" runs exactly when s2's guard was evaluated
        # and did NOT hold, so the target must exist, run earlier, and carry a guard
        # whose verdict is ONE verdict:
        #   * a target with no `when` always runs — its otherwise-arm is dead at birth,
        #     and an automation that can never do what it draws is refused, not stored;
        #   * a fanned target evaluates its guard PER ITEM — N verdicts are not a route.
        target = else_target(effect)
        if target:
            if target == alias:
                return f"step '{alias}' is the otherwise of itself"
            if target not in seen:
                later = {alias_for(e, j) for j, e in enumerate(effects) if j > i}
                if target in later:
                    return (f"step '{alias}' is the otherwise of '{target}', which runs "
                            f"AFTER it — a chain cannot run backwards")
                return f"step '{alias}' is the otherwise of unknown step '{target}'"
            if target in fanned:
                return (f"step '{alias}' is the otherwise of '{target}', which runs once "
                        f"per item — a per-item guard is many verdicts, not one route")
            if target not in guarded:
                return (f"step '{alias}' is the otherwise of '{target}', which has no "
                        f"'Only if' — it always runs, so its otherwise could never")
        # W2 — `item.*` means "this iteration's item", so it is only a name on a step
        # that HAS iterations. On any other step it would read as an unknown step, and
        # "unknown step 'item'" sends someone hunting for a step they never wrote.
        stray = item_refs(effect)
        if stray and not is_fanned(effect):
            return (f"step '{alias}' reads '{stray[0]}', but it does not run for each "
                    f"item — give it a `for_each` list, or bind to a step instead")
        # W2 — the SOURCE must be able to be a list. A closed published set is a
        # measured fact about a kind (`slack_post` publishes two strings), so fanning
        # over one is refused here rather than discovered as "cannot iterate a str" on
        # the morning it runs.
        source_refs = set(collect_refs(fan_source(effect)))
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
                producer_step = seen[target]
                producer = effect_kind(producer_step)
                # W2 — a fanned producer publishes `count`, whatever its kind: there are
                # N per-item values and `{"$from": "step2.ts"}` could only mean one of
                # them. Refusing beats picking the last silently.
                fanning = target in fanned
                declared = FAN_PUBLISHED if fanning else published_keys(producer_step)
                key = parse_ref(ref)[1]
                # DS-11 — a closed set may now CONTAIN a list. Before it, no kind
                # published one, so "closed" and "not iterable" were the same fact and
                # the check could be written as one. A remote read publishes `items`, so
                # the question is which KEY was named, not which kind produced it.
                lists = () if fanning else list_published_keys(producer_step)
                if ref in source_refs and declared is not None and key not in lists:
                    return (f"step '{alias}' fans out over '{ref}', but a {producer} step "
                            f"publishes {', '.join(declared) or 'nothing'} — "
                            + (f"only {', '.join(lists)} is a list"
                               if lists else "none of it is a list")
                            + "; fan out over a literal list instead")
                if target in fanned and key not in FAN_PUBLISHED:
                    return (f"step '{alias}' binds to '{ref}', but step '{target}' runs "
                            f"once per item — it publishes only "
                            f"{', '.join(FAN_PUBLISHED)}, not one value to read")
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
        seen[alias] = effect
        if is_fanned(effect):
            fanned.add(alias)
        if guard_clauses(effect):
            guarded.add(alias)
    return None
