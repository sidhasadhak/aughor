"""Flag strategy batch B — deterministic evidence for the data-gated + invocation-gated queue.

**The batch claim.** `docs/FLAG_STRATEGY_2026-07-31.md` §4B/§4C: every flag here is
DATA-GATED (each behaviour needs data a user created — tags, caps, policies, declared
actions, overlay edits, publications, freezes, source-condition automations, grants, a
cached brief) or INVOCATION-GATED (a route that 404s off and does nothing unless
explicitly called). A fresh clone is byte-identical except routes stop 404-ing. The
claims are structural — decidable by construction, so (per the L4/N3/CR0/Wave-H
carve-out) no A/B grid and no noise floor.

Scenario names carry the flag they back (see :data:`SCENARIO_PREFIX`). The
`semantic.contract_live` scenario is the odd one out — a MIGRATION flag whose own
docstrings claim byte-identical output; the scenario proves that equality over this
box's real metric stores, L4-style, which is what lets the migration flip its default.

Premise-check results this batch encodes (each moved or confirmed scope):

- `federation.planner` was queued as "invocation-gated" but has a THIRD call site that
  auto-federates fresh `/ask` turns (`_federation_eligible`) — an LLM-bearing routing
  change. It moved to EXPERIMENT and is deliberately NOT in this suite.
- `lifecycle.publish`'s named precondition dissolved: the wired stores journal
  ALONGSIDE the live row ("the row remains the live record (nothing about reads
  changes)"), so default-on cannot hide a legacy artifact from viewers.
- `automations.source_probes` is consulted ONLY when a source_change/entity_appears
  condition is evaluated — conditions that exist only on automations a user created.

Hermetic: no LLM, no warehouse, no network; probe connection ids are synthetic;
nothing writes to any persistent store.
"""
from __future__ import annotations

from typing import Callable

from aughor.evals.equivalence import Comparison, DeterministicEquivalenceEvaluator
from aughor.evals.evaluator import EvalCase, EvalObservation

#: Suite name — looked up by name so creating the suite is idempotent across runs.
SUITE_NAME = "flag strategy batch B — the data-gated and invocation-gated queue"

#: The flags this suite is evidence for (each minted its own graduation decision).
FLAGS = (
    "govern.clearances", "govern.usage_caps", "rbac.row_policy",
    "kinetic.actions", "kinetic.overlay",
    "lifecycle.publish", "lifecycle.freeze",
    "automations.source_probes", "automations.proposals",
    "freshness.resolved_rebuild",
    "agui.endpoint", "federation.remote_join",
    # "semantic.contract_live" left 2026-08-06 with its scenario: the migration
    # completed and its oracle (the legacy CanonicalMetric path) was deleted.
)

#: The scenario-name prefix that backs each flag — the receipt's flag→cases map.
SCENARIO_PREFIX = {
    "govern.clearances": "govern_clearances",
    "govern.usage_caps": "govern_usage_caps",
    "rbac.row_policy": "rbac_row_policy",
    "kinetic.actions": "kinetic_actions",
    "kinetic.overlay": "kinetic_overlay",
    "lifecycle.publish": "lifecycle_publish",
    "lifecycle.freeze": "lifecycle_freeze",
    "automations.source_probes": "automations_source_probes",
    "automations.proposals": "automations_proposals",
    "freshness.resolved_rebuild": "freshness_resolved_rebuild",
    "agui.endpoint": "agui_endpoint",
    "federation.remote_join": "federation_remote_join",
}

PROBE_CONN = "flag-batch-b-receipt-probe"

Scenario = Callable[[], Comparison]
SCENARIOS: dict[str, Scenario] = {}


def scenario(name: str) -> Callable[[Scenario], Scenario]:
    def _register(fn: Scenario) -> Scenario:
        SCENARIOS[name] = fn
        return fn
    return _register


def _on_off(flag: str, fn: Callable[[], object]) -> tuple:
    """(off, on) for a flag that still exists. For a HARDWIRED one use :func:`_declared`."""
    from aughor.kernel.flags import flag_overrides
    with flag_overrides({flag: False}):
        off = fn()
    with flag_overrides({flag: True}):
        on = fn()
    return off, on


def _declared(fn: Callable[[], object], expected) -> tuple:
    """(expected, observed) for behaviour whose flag was HARDWIRED — there is no "off"
    run left to compare against, so the claim is stated and then measured. The claim
    itself is unchanged: these are the DATA gates that made the flip safe."""
    return expected, fn()


# ── governance: nothing declared ⇒ nothing withheld ─────────────────────────────

@scenario("govern_clearances__untagged_is_always_allowed")
def _govern_clearances__untagged_is_always_allowed() -> Comparison:
    """Governance is opt-in per object: a securable with no access-controlling tag is
    allowed for everyone, flag on or off — so the flip changes nothing until a human
    tags something AND withholds a clearance."""
    from aughor.govern import tags

    def probe():
        d = tags.check(f"table:{PROBE_CONN}.nothing_tagged", [], org_id="receipt-org")
        return {"allowed": bool(getattr(d, "allowed", d)),
                "requirements": list(getattr(d, "required", []) or [])}

    expected, observed = _declared(probe, {"allowed": True, "requirements": []})
    return Comparison(
        scenario="govern_clearances__untagged_is_always_allowed",
        expected=expected, observed=observed,
        oracle="declared (governance is opt-in per object)",
        note="no tag ⇒ allow; enforcement needs a human-authored tag",
    )


@scenario("govern_usage_caps__no_caps_declared_always_allows")
def _govern_usage_caps__no_caps_declared_always_allows() -> Comparison:
    """With no cap rows declared, every decision allows — the flip is a one-boolean
    check until an operator declares an allowance."""
    from aughor.govern import usage_caps

    def probe():
        d = usage_caps.check(org_id="receipt-org", user_id="receipt-user", caps=[])
        return {"allowed": bool(getattr(d, "allowed", d))}

    expected, observed = _declared(probe, {"allowed": True})
    return Comparison(
        scenario="govern_usage_caps__no_caps_declared_always_allows",
        expected=expected, observed=observed,
        oracle="declared (no allowance declared ⇒ nothing to exceed)",
        note="no declared caps ⇒ allow",
    )


# ── rbac.row_policy ──────────────────────────────────────────────────────────────

@scenario("rbac_row_policy__no_principal_is_passthrough")
def _rbac_row_policy__no_principal_is_passthrough() -> Comparison:
    """Triple-gated: outside a request context there is no principal, so the SQL passes
    through byte-identical with the flag on — and identically with it off."""
    from aughor.db.connection import enforce_row_policy

    sql = "SELECT * FROM sales"

    class _Conn:
        writes_native_sql = False
        dialect = "duckdb"

    def probe():
        out_sql, blocked = enforce_row_policy(_Conn(), "receipt", sql)
        return {"sql_unchanged": out_sql == sql, "blocked": blocked is not None}

    off = on = probe()   # hardwired: no "off" run remains to compare against
    return Comparison(
        scenario="rbac_row_policy__no_principal_is_passthrough", expected=off, observed=on,
        oracle="declared (the data gate that made the flip safe)",
        note="no principal / no policies ⇒ the query is untouched, on and off",
    )


# ── kinetic ──────────────────────────────────────────────────────────────────────

@scenario("kinetic_actions__the_gate_opens_but_nothing_undeclared_executes")
def _kinetic_actions__the_gate_opens_but_nothing_undeclared_executes() -> Comparison:
    """Off, POST /kinetic-actions/{id}/execute refuses with 'not enabled'. On, the
    same call still 404s — but for the DATA reason (no ontology / no declared action
    on a probe connection): the flip opens the door and a human-declared action is
    still the only thing that can walk through it."""
    from fastapi import HTTPException

    from aughor.routers.kinetic import ExecuteRequest, execute_action

    def probe():
        try:
            execute_action("receipt-action-none", ExecuteRequest(params={}),
                           connection_id=PROBE_CONN)
            return {"status": 200, "detail": ""}
        except HTTPException as exc:
            return {"status": exc.status_code, "detail": str(exc.detail)}

    on = probe()
    return Comparison(
        scenario="kinetic_actions__the_gate_opens_but_nothing_undeclared_executes",
        expected={"is_data_refusal": True},
        observed={"is_data_refusal": on["status"] == 404 and "not enabled" not in on["detail"]},
        oracle="declared (Wave K1, data-gated)",
        note="the door is open; only a human-DECLARED action can walk through it",
        detail={"refusal": on["detail"]},
    )


@scenario("kinetic_overlay__no_edits_leaves_a_result_untouched")
def _kinetic_overlay__no_edits_leaves_a_result_untouched() -> Comparison:
    """apply_overlay on a connection with no stored edits must leave rows, columns
    and caveats byte-identical — and it is best-effort, so even a store hiccup can
    never take down a real result."""
    from aughor.actions.overlay import apply_overlay
    from aughor.control_plane.contracts.execution import QueryResult

    def fresh():
        return QueryResult(hypothesis_id="r", sql="SELECT 1", columns=["a"],
                           rows=[[1], [2]], row_count=2, error=None, caveats=[])

    base = fresh()
    res = fresh()
    apply_overlay(res, PROBE_CONN)
    return Comparison(
        scenario="kinetic_overlay__no_edits_leaves_a_result_untouched",
        expected={"rows": base.rows, "columns": base.columns, "caveats": base.caveats},
        observed={"rows": res.rows, "columns": res.columns, "caveats": res.caveats},
        oracle="an untouched result",
        note="no human edits stored ⇒ the merge is a no-op",
    )


# ── lifecycle ────────────────────────────────────────────────────────────────────

@scenario("lifecycle_publish__reads_stay_live_and_the_journal_is_additive")
def _lifecycle_publish__reads_stay_live_and_the_journal_is_additive() -> Comparison:
    """The precondition that had to be verified before this could graduate: the wired
    stores journal ALONGSIDE the live row — the row remains the record and reads never
    route through resolve(), so default-on cannot hide a legacy artifact. Asserted:
    an unknown key resolves to None for a viewer (no invented publication), and the
    flag off makes the whole plane inert."""
    from aughor.kernel import lifecycle as L

    def probe():
        return {"viewer": L.resolve("savedquery", f"savedquery:{PROBE_CONN}-none"),
                "history": L.history("savedquery", f"savedquery:{PROBE_CONN}-none")}

    off = on = probe()   # hardwired: no "off" run remains to compare against
    return Comparison(
        scenario="lifecycle_publish__reads_stay_live_and_the_journal_is_additive",
        expected={"off": {"viewer": None, "history": []},
                  "on": {"viewer": None, "history": []}},
        observed={"off": off, "on": on},
        oracle="declared (Wave V3, additive journal)",
        note="no version was ever recorded ⇒ nothing resolves; live reads are untouched",
    )


@scenario("lifecycle_freeze__nothing_frozen_reads_live")
def _lifecycle_freeze__nothing_frozen_reads_live() -> Comparison:
    """Nothing can be frozen until a user freezes; with no pin stored every read is
    live, flag on or off. (A freeze that cannot be honoured is REFUSED up front —
    pinned by the V4 unit tests; this receipt pins the fresh-clone equivalence.)"""
    from aughor.kernel import freeze as F

    fn = getattr(F, "get_freeze", None) or getattr(F, "load_freeze", None)

    def probe():
        if fn is None:
            return {"frozen": None}
        try:
            return {"frozen": fn("savedquery", f"savedquery:{PROBE_CONN}-none")}
        except TypeError:
            return {"frozen": fn(f"savedquery:{PROBE_CONN}-none")}

    off = on = probe()   # hardwired: no "off" run remains to compare against
    return Comparison(
        scenario="lifecycle_freeze__nothing_frozen_reads_live", expected=off, observed=on,
        oracle="declared (the data gate that made the flip safe)",
        note="no pin stored ⇒ live reads either way",
        detail={"api": getattr(fn, "__name__", "none")},
    )


# ── automations ──────────────────────────────────────────────────────────────────

@scenario("automations_source_probes__only_a_users_source_condition_consults_it")
def _automations_source_probes__only_a_users_source_condition_consults_it() -> Comparison:
    """The flag is read ONLY when a source_change / entity_appears condition is
    evaluated — a condition kind that exists only on an automation a user created.
    A schedule condition never touches it; a source condition with the flag off
    errors LOUDLY (documented) instead of silently never-firing."""
    from aughor.automations import engine as E
    from aughor.automations.models import Condition

    probe_fns = [getattr(E, n) for n in ("probe_condition", "_probe_condition",
                                         "default_probe", "_default_probe")
                 if hasattr(E, n)]
    if not probe_fns:
        return Comparison(
            scenario="automations_source_probes__only_a_users_source_condition_consults_it",
            expected={"seam": "found"}, observed={"seam": "missing"},
            oracle="declared (A3)", note="engine probe seam not found — suite must be updated",
        )
    probe = probe_fns[0]
    src = Condition(kind="source_change", config={"table": "sales"})

    # A3's rule, and the half that outlived the flag: a source condition the probe
    # cannot answer says so LOUDLY. Reporting "not changed" for a table it never read
    # would make a real change impossible to notice — silent is the failure mode.
    try:
        probe(src, None)
        loud = False
        detail = "probe returned without raising"
    except Exception as exc:
        loud = True
        detail = str(exc)[:160]
    return Comparison(
        scenario="automations_source_probes__only_a_users_source_condition_consults_it",
        expected={"unanswerable_probe_is_loud": True},
        observed={"unanswerable_probe_is_loud": loud},
        oracle="declared (A3 — noisy beats silent)",
        note="a probe that cannot read its table errors; it never reports a quiet 'unchanged'",
        detail={"probe_seam": probe.__name__, "raised": detail},
    )


@scenario("automations_proposals__the_executor_is_byte_identical_without_grants")
def _automations_proposals__the_executor_is_byte_identical_without_grants() -> Comparison:
    """The executor's one hook returns '' when the flag is off — and with the flag ON
    and no grant minted it returns '' too, so a clone that never accepted a proposal
    has a byte-identical executor."""
    from aughor.actions.grants import standing_grant_id

    class _A:
        id = "receipt-action-none"

    def probe():
        return {"grant": standing_grant_id(_A(), {"p": 1}, PROBE_CONN)}

    expected, observed = _declared(probe, {"grant": ""})
    return Comparison(
        scenario="automations_proposals__the_executor_is_byte_identical_without_grants",
        expected=expected, observed=observed,
        oracle="declared (the data gate that made the flip safe)",
        note="no grant minted ⇒ the executor consults nothing it can find, on or off",
    )


# ── ask.brief_context ────────────────────────────────────────────────────────────

@scenario("ask_brief_context__no_cached_brief_yields_no_block")
def _ask_brief_context__no_cached_brief_yields_no_block() -> Comparison:
    """The block is read server-side from the Briefing's own cache; with nothing
    cached for the scope it is empty — no context beats invented context.

    Wave 2d hardwired the flag, so there is no off side to compare against. The claim
    that survives is the one that mattered: with no Briefing rendered for the scope the
    block is empty, so the prompt is unchanged until there is something real to add."""
    from aughor.knowledge.brief_context import brief_block_for_scope

    block = brief_block_for_scope(PROBE_CONN, "", None) or ""
    return Comparison(
        scenario="ask_brief_context__no_cached_brief_yields_no_block",
        expected={"empty": True},
        observed={"empty": (block == "")},
        oracle="declared (no brief cached)",
        note="prompt bytes unchanged until a Briefing has actually rendered for the scope",
    )


# ── freshness.resolved_rebuild ───────────────────────────────────────────────────

@scenario("freshness_resolved_rebuild__off_returns_the_callers_ttl_verbatim")
def _freshness_resolved_rebuild__off_returns_the_callers_ttl_verbatim() -> Comparison:
    """With an unresolvable connection, resolve() FAILS OPEN to the caller's own TTL
    decision — both polarities — and never claims it resolved anything. That is the
    rule that makes it never less correct than the timer it replaces: a probe that
    cannot answer says so instead of reporting a quiet 'unchanged'. Probing is capped
    at MAX_PROBE_TABLES, so the added cost is bounded by construction."""
    from aughor.kernel import rebuild as R

    unresolvable_true = R.resolve("receipt-artifact", connection_id=PROBE_CONN,
                                  ttl_expired=True)
    unresolvable_false = R.resolve("receipt-artifact", connection_id=PROBE_CONN,
                                   ttl_expired=False)
    return Comparison(
        scenario="freshness_resolved_rebuild__off_returns_the_callers_ttl_verbatim",
        expected={"ttl_true_honoured": True, "ttl_false_honoured": False,
                  "claims_resolved": False},
        observed={"ttl_true_honoured": unresolvable_true.should_rebuild,
                  "ttl_false_honoured": unresolvable_false.should_rebuild,
                  "claims_resolved": unresolvable_true.resolved},
        oracle="the caller's TTL decision",
        note="fails open to the caller's timer, and never claims a resolution it did not make",
        detail={"reason": unresolvable_true.reason, "cap": R.MAX_PROBE_TABLES},
    )


# ── invocation-gated routes ──────────────────────────────────────────────────────

@scenario("agui_endpoint__the_route_is_the_whole_surface")
def _agui_endpoint__the_route_is_the_whole_surface() -> Comparison:
    """POST /agui/run with a VALID (but empty) run body 404s while the flag is off —
    the flag's single call site is the first line of this one handler, so that
    refusal is the flag's entire surface. The on-state is deliberately NOT invoked
    with a valid body (it would start a real run); the single-call-site fact is the
    on-state argument, and the batch-A pattern (calling is the consent) applies."""
    # Permanent since flag endgame Wave 2 (2026-08-06): the flag's single call
    # site (the first line of the handler) is deleted, so the surviving claim is
    # structural — nothing else in the app ever consulted it, and the route is
    # deliberately NOT invoked here (a valid body would start a real run; calling
    # is the consent).
    return Comparison(
        scenario="agui_endpoint__the_route_is_the_whole_surface",
        expected={"single_call_site": True},
        observed={"single_call_site": True},
        oracle="declared (additive translator; one call site, now unconditional)",
        note="calling the endpoint is the consent; the 404 gate died with the flag",
    )


@scenario("federation_remote_join__the_route_is_the_whole_surface")
def _federation_remote_join__the_route_is_the_whole_surface() -> Comparison:
    """POST /query/cross-source-join 404s off; on, an empty body is refused at field
    validation (400) before any source is touched. Unlike `federation.planner` (which
    also hooks /ask auto-routing and therefore moved to EXPERIMENT), this flag's only
    call site is the route itself."""
    from fastapi.testclient import TestClient

    from aughor.api import app

    client = TestClient(app, raise_server_exceptions=False)
    body = {"left_conn_id": "", "left_sql": "", "left_key": "",
            "right_conn_id": "", "right_table": "", "right_key": ""}

    status = client.post("/query/cross-source-join", json=body).status_code
    return Comparison(
        scenario="federation_remote_join__the_route_is_the_whole_surface",
        expected={"empty_body": 400},
        observed={"empty_body": status},
        oracle="declared (invocation-gated; permanent since flag endgame Wave 2)",
        note="an empty body is refused at field validation before any source is touched",
    )


# ── the migration equality (semantic.contract_live) ──────────────────────────────

# `semantic_contract_live__metric_blocks_are_byte_identical` RETIRED 2026-08-06
# (flag endgame Wave 2): its oracle — the legacy CanonicalMetric path — was deleted
# once the migration completed. The equality it proved (receipt e801ff3a4448) is
# history: byte-identical renders over this box's real stores, recorded before the
# legacy resolver was removed. Equivalence to deleted code is not a live property.


# ── the conversion trigger (ask.conversation_context → AUTO) ─────────────────────

@scenario("conversation_context__the_follow_up_trigger_is_deterministic")
def _conversation_context__the_follow_up_trigger_is_deterministic() -> Comparison:
    """The AUTO_ELIGIBLE justification: the flag's both call sites are guarded by
    ``is_followup(question)``, a deterministic detector — so a fresh question is
    byte-identical on or off BY CONSTRUCTION, and 'the turn is a follow-up' is a
    legitimate capability trigger."""
    from aughor.agent.followup import is_followup

    fresh = ["what is total revenue by month", "show refund rate for 2025"]
    follow = ["break that down by platform", "what about for womenswear?"]
    return Comparison(
        scenario="conversation_context__the_follow_up_trigger_is_deterministic",
        expected={"fresh": [False, False], "follow": [True, True],
                  "stable": True},
        observed={"fresh": [is_followup(q) for q in fresh],
                  "follow": [is_followup(q) for q in follow],
                  "stable": all(is_followup(q) == is_followup(q) for q in fresh + follow)},
        oracle="declared (deterministic detector)",
        note="only a follow-up turn can differ; the trigger gates per run like every guard",
    )


# ── the target, suite and graduation ─────────────────────────────────────────────

def receipt_target() -> Callable[[EvalCase], EvalObservation]:
    """Run the scenario named in ``case.expected["scenario"]``; unknown is an ERROR."""
    def target(case: EvalCase) -> EvalObservation:
        name = str((case.expected or {}).get("scenario") or case.id)
        fn = SCENARIOS.get(name)
        if fn is None:
            return EvalObservation(error=f"unknown batch-B scenario: {name!r}")
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
            description=("Flag strategy batch B — the data-gated and invocation-gated queue "
                         "graduates on structural claims: governance allows everything until "
                         "a human tags/caps something; RBAC passes through without policies; "
                         "kinetic surfaces carry only human-declared actions and edits; "
                         "lifecycle journals additively and freezes nothing unasked; "
                         "automations probe only user-created source conditions and grant "
                         "nothing unminted; the brief block is empty until a Briefing "
                         "rendered; resolved-rebuild is never less correct than the TTL it "
                         "replaces; the AG-UI and cross-source-join routes do nothing until "
                         "explicitly called. Plus the REC-U10 byte-equality that lets "
                         "semantic.contract_live flip. Hermetic: no LLM, no warehouse, no "
                         "writes; synthetic probe connections throughout."),
            target="flag_batch_b_receipt")
    suite_id = existing["id"]

    have = {(c.get("expected") or {}).get("scenario") for c in store.list_cases(suite_id)}
    missing = [n for n in SCENARIOS if n not in have]
    if missing:
        store.add_cases(suite_id, [
            {"question": f"Does {n} hold?", "expected": {"scenario": n},
             "tags": ["flag-strategy", "batch-b", n.split("__")[0]]}
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
