"""Wave H — deterministic evidence for `agents.user_defined`.

**The claim this flag graduates on.** Not "answers get better" — a persona is a
user's own instruction text, and nothing here can promise it helps. The claim is
narrower and decidable: **turning user-defined agents on is data-gated.** Every
behaviour it adds requires an agent row the user created AND a request that names
it. With neither, the answer path is byte-identical: the prompt gains nothing,
retrieval is scoped to nothing, and a resumed run reads no persona.

Exactly one thing does change on a fresh clone, and this suite measures it rather
than hiding it: **the `/agents/custom` surface stops 404-ing and starts returning
an empty list.** That is the flag's whole observable effect until somebody creates
an agent — which is the honest thing for a graduation to say, so the case is named
`the_crud_surface_is_the_only_fresh_clone_delta` and asserts the delta rather than
asserting there is none.

The other half is what must stay true once agents DO exist, because default-on
means the fail-closed rules are now load-bearing for everyone: an agent bound to
another connection is refused, a disabled agent is refused, an unknown one is
refused, and an active agent's retrieval is restricted to its own documents (with
none bound it sees none — never a silent fall-back to everything).

**Why there is no A/B grid.** The prompt-changing question was asked before any
requests were bought (`grid-budget` rule): `agent_brief_block()` returns `""`
whenever no persona is active, and a persona can only become active by resolving
an `agent_id` off the request. So flag-on and flag-off produce the same prompt
bytes for every question that does not name an agent — decidable by construction,
not by sampling. Like L4, N3 and CR0, this receipt carries no baseline: a claim
with no sampling has no noise floor and so needs none.

The evaluator and ``Comparison`` shape are L4's, imported rather than re-derived.
The behavioural surface (CRUD, binding rules, scoped retrieval) is already pinned
by `tests/unit/test_user_agents.py`; this suite pins the *graduation claim*.

No LLM, no warehouse, no network. Agent rows are created and deleted per scenario.
"""
from __future__ import annotations

from typing import Any, Callable

from aughor.evals.equivalence import Comparison, DeterministicEquivalenceEvaluator
from aughor.evals.evaluator import EvalCase, EvalObservation

#: Suite name — looked up by name so creating the suite is idempotent across runs.
SUITE_NAME = "user-defined agents — data-gated on the answer path (Wave H)"

#: The flag this suite is evidence for.
FLAG = "agents.user_defined"

Scenario = Callable[[], Comparison]
SCENARIOS: dict[str, Scenario] = {}


def scenario(name: str) -> Callable[[Scenario], Scenario]:
    def _register(fn: Scenario) -> Scenario:
        SCENARIOS[name] = fn
        return fn
    return _register


# ── helpers ──────────────────────────────────────────────────────────────────────

def _ask(**kw) -> Any:
    from aughor.routers.investigations import AskRequest
    return AskRequest(question="what moved last month?", **kw)


def _resolve(req, *, flag_on: bool) -> dict:
    """`_resolve_ask_agent` through its PUBLIC seam, as a comparable dict.

    Uses ``ask_agent_refusal`` — the public form the scheduled and kinetic callers
    already use (Wave H1/H5) — so this suite reads the same authority the product
    does rather than reaching into a private function.
    """
    from aughor.kernel.flags import flag_overrides
    from aughor.routers.investigations import ask_agent_refusal
    with flag_overrides({FLAG: flag_on}):
        return {"refusal": ask_agent_refusal(req)}


def _prompt_surface(*, flag_on: bool) -> dict:
    """Everything the persona seams contribute to a run with no agent activated."""
    from aughor.kernel.flags import flag_overrides
    from aughor.user_agents.context import (
        agent_brief_block, agent_doc_ids, agent_pack_ids, current_agent,
    )
    with flag_overrides({FLAG: flag_on}):
        return {
            "brief_block": agent_brief_block(),
            "doc_scope": None if agent_doc_ids() is None else sorted(agent_doc_ids()),
            "pack_ids": agent_pack_ids(),
            "active": current_agent() is not None,
        }


def _agent(**kw):
    from aughor.user_agents import create_agent
    base = dict(name="receipt probe", instructions="Prefer cohort framing.")
    base.update(kw)
    return create_agent(**base)


def _drop(agent) -> None:
    from aughor.user_agents import delete_agent
    delete_agent(agent.id)


# ── the invariants: with no agent named, on == off ───────────────────────────────

@scenario("no_agent_id_resolves_identically")
def _no_agent_id_resolves_identically() -> Comparison:
    """A request that names no agent never reaches the flag at all.

    `_resolve_ask_agent` returns before consulting it, which is why the whole
    surface is data-gated rather than merely quiet.
    """
    req_off, req_on = _ask(), _ask()
    off, on = _resolve(req_off, flag_on=False), _resolve(req_on, flag_on=True)
    return Comparison(
        scenario="no_agent_id_resolves_identically", expected=off, observed=on,
        oracle="flag-off run",
        note="no agent_id ⇒ identical resolution on and off",
    )


@scenario("prompt_is_identical_with_no_persona_active")
def _prompt_is_identical_with_no_persona_active() -> Comparison:
    """THE question a graduation has to answer: does the flag change the prompt?

    It cannot, unless a persona is active — and a persona becomes active only by
    resolving an agent_id the request carried. This is the case that made an A/B
    grid unnecessary: the answer is decidable, so no requests were spent on it.
    """
    off, on = _prompt_surface(flag_on=False), _prompt_surface(flag_on=True)
    return Comparison(
        scenario="prompt_is_identical_with_no_persona_active", expected=off, observed=on,
        oracle="flag-off run",
        note="no active persona ⇒ empty brief block, unrestricted retrieval, on and off",
        detail={"brief_block_len": len(on["brief_block"]), "doc_scope": on["doc_scope"]},
    )


@scenario("an_unreferenced_agent_changes_nothing")
def _an_unreferenced_agent_changes_nothing() -> Comparison:
    """Data-gated means the ROW is not enough — an existing agent nobody asked for
    leaves every answer exactly as it was."""
    agent = _agent(name="unreferenced probe")
    try:
        off, on = _prompt_surface(flag_on=False), _prompt_surface(flag_on=True)
        resolved = _resolve(_ask(), flag_on=True)
    finally:
        _drop(agent)
    return Comparison(
        scenario="an_unreferenced_agent_changes_nothing",
        expected={**off, "refusal": ""}, observed={**on, **resolved},
        oracle="flag-off run",
        note="an agent exists but no request names it ⇒ nothing changes",
    )


@scenario("resume_without_a_persona_is_identical")
def _resume_without_a_persona_is_identical() -> Comparison:
    """A resumed run with no persisted persona reads no persona, on or off.

    The resume path is fail-open by design (a missing checkpoint or an unknown
    agent resumes WITHOUT the persona rather than blocking the run), so flipping
    the default must not start attaching one.
    """
    from aughor.kernel.flags import flag_overrides
    from aughor.routers.investigations import persona_for_investigation

    def read(flag_on: bool):
        with flag_overrides({FLAG: flag_on}):
            return persona_for_investigation("no-such-investigation-receipt-probe")

    off, on = read(False), read(True)
    return Comparison(
        scenario="resume_without_a_persona_is_identical",
        expected={"persona": off}, observed={"persona": on},
        oracle="flag-off run",
        note="no persisted agent_id ⇒ resume attaches no persona either way",
    )


# ── the one delta, named rather than hidden ──────────────────────────────────────

@scenario("the_crud_surface_is_the_only_fresh_clone_delta")
def _the_crud_surface_is_the_only_fresh_clone_delta() -> Comparison:
    """What flipping the default actually changes for someone who has no agents.

    Off, `/agents/custom` 404s. On, it answers. That REACHABILITY is the entire
    observable effect until a user creates something — so the case asserts the
    status delta (404 → 200) instead of pretending the flip is invisible.

    What it deliberately does NOT assert is that the roster comes back empty: that
    is true of a fresh clone and false of any deployment already using the feature
    behind a runtime override (this one has agents, which is how the assertion got
    caught). The count is reported as detail — a receipt that only passes on a
    machine with no data is measuring the machine, not the flag.
    """
    from fastapi import HTTPException
    from aughor.kernel.flags import flag_overrides
    from aughor.routers.agents import list_user_agents

    def probe(flag_on: bool) -> dict:
        with flag_overrides({FLAG: flag_on}):
            try:
                return {"status": 200, "roster": len(list_user_agents())}
            except HTTPException as exc:
                return {"status": exc.status_code, "roster": None}

    off, on = probe(False), probe(True)
    return Comparison(
        scenario="the_crud_surface_is_the_only_fresh_clone_delta",
        expected={"off_status": 404, "on_status": 200},
        observed={"off_status": off["status"], "on_status": on["status"]},
        oracle="declared (Wave H)",
        note="the flip's whole fresh-clone effect: the roster route becomes reachable",
        detail={"roster_size_here": on["roster"],
                "fresh_clone_roster_size": 0},
    )


# ── what must stay true once agents DO exist ─────────────────────────────────────

@scenario("a_conflicting_connection_binding_is_refused")
def _a_conflicting_connection_binding_is_refused() -> Comparison:
    """Default-on makes the fail-closed binding rules load-bearing for everyone."""
    agent = _agent(name="bound probe", connection_id="conn-a")
    try:
        got = _resolve(_ask(agent_id=agent.id, connection_id="conn-b"), flag_on=True)
        refused = bool(got["refusal"]) and "conn-a" in got["refusal"]
    finally:
        _drop(agent)
    return Comparison(
        scenario="a_conflicting_connection_binding_is_refused",
        expected={"refused": True}, observed={"refused": refused},
        oracle="declared (Wave H)",
        note="an agent bound elsewhere is refused, never silently re-pointed",
        detail={"sentence": got["refusal"]},
    )


@scenario("a_disabled_or_unknown_agent_is_refused")
def _a_disabled_or_unknown_agent_is_refused() -> Comparison:
    from aughor.user_agents import update_agent
    agent = _agent(name="disabled probe")
    update_agent(agent.id, enabled=False)
    try:
        disabled = _resolve(_ask(agent_id=agent.id), flag_on=True)["refusal"]
        unknown = _resolve(_ask(agent_id="ua_does_not_exist"), flag_on=True)["refusal"]
    finally:
        _drop(agent)
    return Comparison(
        scenario="a_disabled_or_unknown_agent_is_refused",
        expected={"disabled_refused": True, "unknown_refused": True},
        observed={"disabled_refused": bool(disabled), "unknown_refused": bool(unknown)},
        oracle="declared (Wave H)",
        note="a persona that cannot run says so; it never degrades to an anonymous answer",
        detail={"disabled": disabled, "unknown": unknown},
    )


@scenario("an_active_agent_sees_only_its_own_documents")
def _an_active_agent_sees_only_its_own_documents() -> Comparison:
    """Fail-closed retrieval, the promise in the flag's own description: an agent
    with no bound documents sees NONE — never a fall-back to everything."""
    from aughor.user_agents.context import activate_agent, agent_doc_ids, release_agent

    bound = _agent(name="scoped probe", doc_ids=["doc-1", "doc-2"])
    empty = _agent(name="unscoped probe", doc_ids=[])
    try:
        tok = activate_agent(bound)
        scoped = agent_doc_ids()
        release_agent(tok)
        tok = activate_agent(empty)
        none_bound = agent_doc_ids()
        release_agent(tok)
        unrestricted = agent_doc_ids()
    finally:
        _drop(bound)
        _drop(empty)
    return Comparison(
        scenario="an_active_agent_sees_only_its_own_documents",
        expected={"scoped": ["doc-1", "doc-2"], "none_bound": [], "no_agent": None},
        observed={"scoped": sorted(scoped or []), "none_bound": sorted(none_bound or []),
                  "no_agent": unrestricted},
        oracle="declared (Wave H)",
        note="an agent with no documents sees none; with no agent, retrieval is unrestricted",
    )


@scenario("the_fleet_does_not_advertise_unopenable_personas")
def _the_fleet_does_not_advertise_unopenable_personas() -> Comparison:
    """The honesty fix Wave CR made: with the flag off the CRUD routes 404, so a
    fleet table listing persona rows would be two views disagreeing about what
    exists. Persona rows follow the flag."""
    from aughor.kernel.flags import flag_overrides
    from aughor.routers.control_room import fleet_overview

    agent = _agent(name="fleet probe")
    try:
        def personas(flag_on: bool) -> int:
            with flag_overrides({FLAG: flag_on}):
                rows = fleet_overview().get("rows") or []
                return sum(1 for r in rows if r.get("kind") == "persona")
        off, on = personas(False), personas(True)
    finally:
        _drop(agent)
    return Comparison(
        scenario="the_fleet_does_not_advertise_unopenable_personas",
        expected={"off_lists_personas": False, "on_lists_personas": True},
        observed={"off_lists_personas": off > 0, "on_lists_personas": on > 0},
        oracle="declared (Wave CR)",
        note="persona rows appear only while their CRUD routes do",
        detail={"off_rows": off, "on_rows": on},
    )


# ── the magnitude, measured on the real store ────────────────────────────────────

def measured_effect() -> dict[str, Any]:
    """What flipping the default costs and reaches HERE — an invariant that holds
    over fixtures proves safety, not what enabling it does.

    Reported, never asserted: the numbers describe this deployment on the day the
    receipt was minted, and a fresh clone's are all zero by construction.
    """
    from aughor.user_agents import list_agents

    agents = list_agents()
    return {
        "agents_defined": len(agents),
        "agents_enabled": sum(1 for a in agents if a.enabled),
        "agents_connection_bound": sum(1 for a in agents if a.connection_id),
        "agents_with_documents": sum(1 for a in agents if a.doc_ids),
        "agents_with_a_pass_chip": sum(1 for a in agents if a.last_eval),
        # The fresh-clone delta is exactly one route family becoming reachable.
        "fresh_clone_delta": "GET/POST /agents/custom 404 → 200 with an empty roster",
        "answer_path_delta": "none until a request carries an agent_id",
    }


# ── the target, suite and graduation ─────────────────────────────────────────────

def receipt_target() -> Callable[[EvalCase], EvalObservation]:
    """Run the scenario named in ``case.expected["scenario"]``; unknown is an ERROR."""
    def target(case: EvalCase) -> EvalObservation:
        name = str((case.expected or {}).get("scenario") or case.id)
        fn = SCENARIOS.get(name)
        if fn is None:
            return EvalObservation(error=f"unknown user-agents scenario: {name!r}")
        comparison = fn()
        return EvalObservation(narrative=comparison.note, meta=comparison.to_meta())

    return target


def ensure_suite() -> str:
    """Create the suite (idempotent by name) with one case per scenario; return its id."""
    from aughor.evals import store

    existing = next((s for s in store.list_suites(200) if s["name"] == SUITE_NAME), None)
    if existing is None:
        existing = store.create_suite(
            SUITE_NAME,
            description=("Wave H — `agents.user_defined` claims to be DATA-GATED: with no "
                         "agent named on a request the prompt, retrieval scope and resume "
                         "path are byte-identical on and off, and the flip's only "
                         "fresh-clone effect is that /agents/custom returns an empty roster "
                         "instead of 404. The fail-closed rules that become load-bearing at "
                         "default-on (conflicting binding, disabled/unknown agent, "
                         "documents-or-none) are asserted alongside. Hermetic: no LLM, no "
                         "warehouse; agent rows are created and deleted per case."),
            target="user_agents_receipt")
    suite_id = existing["id"]

    have = {(c.get("expected") or {}).get("scenario") for c in store.list_cases(suite_id)}
    missing = [n for n in SCENARIOS if n not in have]
    if missing:
        store.add_cases(suite_id, [
            {"question": f"Does {n} hold?", "expected": {"scenario": n},
             "tags": ["wave-h", "user_agents"]}
            for n in missing
        ])
    return suite_id


def run_suite(*, iterations: int = 1, persist: bool = True):
    """Run every scenario and return the :class:`~aughor.evals.runner.RunSummary`."""
    from aughor.evals import runner
    from aughor.evals.registry import get_evaluator, register_evaluator

    if get_evaluator(DeterministicEquivalenceEvaluator.name) is None:
        register_evaluator(DeterministicEquivalenceEvaluator())

    suite_id = ensure_suite()
    return runner.run_suite(
        suite_id, receipt_target(), iterations=iterations, persist=persist,
        evaluators=[DeterministicEquivalenceEvaluator.name])
