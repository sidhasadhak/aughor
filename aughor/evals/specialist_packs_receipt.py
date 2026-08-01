"""Flag strategy batch 1 — deterministic evidence for `specialist_packs`.

**The claim this flag graduates on.** Not "packs make answers better" — a pack is
authored domain expertise, and nothing here can promise the author was right. The
claim is narrower and decidable: **turning specialist packs on is data-gated,
three gates deep.** Steering requires (1) a pack INSTALLED under ``packs/`` whose
manifest says ``status: active``, (2) that pack matching the question, AND (3) a
human-pinned deploy binding on the exact connection — ``save_binding``'s only
product caller is the deploy endpoint behind ``govern.guard("pack.bind")``, so a
row in ``pack_bindings`` IS a recorded human act. With any gate open,
``injection_for_question`` returns ``None`` and the planner context is
byte-identical on and off.

The repo's one shipped pack (``packs/customer-analytics``) is ``status: draft``,
so a fresh clone holds ZERO active packs — the flip's whole observable effect
there is that ``GET /packs`` reports ``enabled: true`` instead of ``false`` (the
route itself is reachable either way). That delta is asserted rather than hidden,
in `the_enabled_field_is_the_only_fresh_clone_delta`.

**Why the graduation matters** (the defect it fixes): Wave H4's hire-an-analyst
flow never consults this flag — hiring from a pack works on a fresh clone, the
pack binds, validation passes — but the steering half
(``packs/intake.py::injection_for_question``) silently returned ``None`` with the
flag off. A hired expert whose expertise never injects, no error anywhere. See
``docs/FLAG_STRATEGY_2026-07-31.md`` §2.

**Why there is no A/B grid.** The prompt-changing question was asked before any
requests were bought (`grid-budget` rule): the injection is prepended to the
explore planner context only when ``injection_for_question`` returns a value, and
every scenario here proves it returns ``None`` until all three gates are earned —
decidable by construction, not by sampling. Like L4, N3, CR0 and Wave H, this
receipt carries no baseline: a claim with no sampling has no noise floor and so
needs none.

The gate semantics themselves are already pinned by
``tests/unit/test_packs_intake.py``; this suite pins the *graduation claim*, plus
the two properties default-on makes load-bearing for everyone: the operator
escape hatch still kills steering outright, and a broken pack on disk degrades to
"no steer" rather than taking down intake.

No LLM, no warehouse, no network. Bindings are written under synthetic
receipt-probe connection ids and purged per scenario; packs are constructed
in memory or under a temp dir — the real ``packs/`` directory is only read.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from aughor.evals.equivalence import Comparison, DeterministicEquivalenceEvaluator
from aughor.evals.evaluator import EvalCase, EvalObservation

#: Suite name — looked up by name so creating the suite is idempotent across runs.
SUITE_NAME = "specialist packs — steering is three-gates data-gated (flag strategy batch 1)"

#: The flag this suite is evidence for.
FLAG = "specialist_packs"

#: The question the shipped sample pack owns (mirrors tests/unit/test_packs_intake.py).
Q = "How is retention trending by cohort?"

#: A synthetic, unmistakable connection id — bindings written under it are purged per
#: scenario and cannot collide with a real connection.
PROBE_CONN = "specialist-packs-receipt-probe-a"
PROBE_CONN_B = "specialist-packs-receipt-probe-b"

BINDING = {
    "customer": {"table": "customers", "column": "customer_unique_id"},
    "event": {"table": "orders", "column": "order_purchase_ts"},
    "cohort_anchor": {"table": "customers", "column": "signup_date"},
    "active_definition": {"value": "purchased_in_window"},
}

Scenario = Callable[[], Comparison]
SCENARIOS: dict[str, Scenario] = {}


def scenario(name: str) -> Callable[[Scenario], Scenario]:
    def _register(fn: Scenario) -> Scenario:
        SCENARIOS[name] = fn
        return fn
    return _register


# ── helpers ──────────────────────────────────────────────────────────────────────

def _repo_root() -> Path:
    import aughor
    return Path(aughor.__file__).resolve().parent.parent


def _shipped_pack(*, active: bool):
    """The repo's sample pack, optionally elevated to ``status: active`` in memory only."""
    from aughor.packs import load_pack
    pack = load_pack(_repo_root() / "packs" / "customer-analytics")
    if not active:
        return pack
    return pack.model_copy(update={"manifest": pack.manifest.model_copy(update={"status": "active"})})


def _steers(*, flag_on: bool, connection_id: str = PROBE_CONN, packs=None,
            question: str = Q) -> dict:
    """Whether steering fires, through the one seam the explore path calls."""
    from aughor.kernel.flags import flag_overrides
    from aughor.org.context import using_org
    from aughor.packs.intake import injection_for_question
    with flag_overrides({FLAG: flag_on}), using_org("default"):
        inj = injection_for_question(question, connection_id, packs=packs)
    return {"steers": inj is not None,
            "pack_id": getattr(inj, "pack_id", None)}


def _pin(connection_id: str = PROBE_CONN) -> None:
    from aughor.org.context import using_org
    from aughor.packs import save_binding
    with using_org("default"):
        save_binding("customer-analytics", connection_id, BINDING, verified=True)


def _purge_probe_bindings() -> None:
    from aughor.org.context import using_org
    from aughor.packs import bindings
    with using_org("default"):
        bindings.purge_connection(PROBE_CONN)
        bindings.purge_connection(PROBE_CONN_B)


# ── the invariants: until all three gates are earned, on == off ──────────────────

@scenario("an_installed_active_pack_alone_steers_nothing")
def _an_installed_active_pack_alone_steers_nothing() -> Comparison:
    """Data-gated means the pack is not enough — active, matching the question,
    and still silent until a human deploys it on the connection.

    This is the case that makes default-on safe: the analog of Wave H's
    "an unreferenced agent changes nothing"."""
    off = _steers(flag_on=False, packs=[_shipped_pack(active=True)])
    on = _steers(flag_on=True, packs=[_shipped_pack(active=True)])
    return Comparison(
        scenario="an_installed_active_pack_alone_steers_nothing", expected=off, observed=on,
        oracle="flag-off run",
        note="active + matching, but no human-pinned deploy binding ⇒ no steer, on or off",
    )


@scenario("a_fresh_clone_has_nothing_to_steer_with")
def _a_fresh_clone_has_nothing_to_steer_with() -> Comparison:
    """A fresh clone holds zero ACTIVE packs, so steering is structurally None
    before the deploy gate is even consulted.

    Asserted hermetically (an empty pool); the LIVE packs directory is reported as
    detail rather than asserted, because a deployment that installed packs would
    otherwise fail a receipt that is measuring the machine, not the flag."""
    from aughor.packs.intake import active_packs

    off = _steers(flag_on=False, packs=[])
    on = _steers(flag_on=True, packs=[])
    live = active_packs()
    return Comparison(
        scenario="a_fresh_clone_has_nothing_to_steer_with", expected=off, observed=on,
        oracle="flag-off run",
        note="no active pack ⇒ no steer, on or off; the shipped sample pack is status: draft",
        detail={"live_active_packs_here": len(live),
                "fresh_clone_active_packs": 0},
    )


@scenario("a_draft_pack_never_steers_even_when_deployed")
def _a_draft_pack_never_steers_even_when_deployed() -> Comparison:
    """The shipped pack's own status gate: draft + a pinned binding still does not
    steer. A fresh clone cannot be steered by the sample pack even if an operator
    pins a binding without first activating the pack."""
    try:
        _pin()
        on = _steers(flag_on=True, packs=[_shipped_pack(active=False)])
    finally:
        _purge_probe_bindings()
    return Comparison(
        scenario="a_draft_pack_never_steers_even_when_deployed",
        expected={"steers": False, "pack_id": None}, observed=on,
        oracle="declared (pack status gate)",
        note="status: draft is a review state — a draft pack never steers, deployed or not",
    )


@scenario("steering_is_scoped_to_the_deployed_connection")
def _steering_is_scoped_to_the_deployed_connection() -> Comparison:
    """A deploy binding is per (org, pack, connection, schema) — earning steering
    on one connection must not leak it to another."""
    try:
        _pin(PROBE_CONN)
        here = _steers(flag_on=True, connection_id=PROBE_CONN,
                       packs=[_shipped_pack(active=True)])
        elsewhere = _steers(flag_on=True, connection_id=PROBE_CONN_B,
                            packs=[_shipped_pack(active=True)])
    finally:
        _purge_probe_bindings()
    return Comparison(
        scenario="steering_is_scoped_to_the_deployed_connection",
        expected={"deployed_conn_steers": True, "other_conn_steers": False},
        observed={"deployed_conn_steers": here["steers"],
                  "other_conn_steers": elsewhere["steers"]},
        oracle="declared (deploy gate)",
        note="steering follows the pinned binding's connection, never the pack alone",
        detail={"steered_by": here["pack_id"]},
    )


@scenario("agent_pack_preference_never_bypasses_the_deploy_gate")
def _agent_pack_preference_never_bypasses_the_deploy_gate() -> Comparison:
    """The Wave H4 seam, pinned at default-on: a hired analyst's pack binding is a
    PREFERENCE that restricts selection — never a deploy-gate bypass. An agent
    explicitly bound to the pack still gets no steering until a human deploys the
    pack on the connection (the promise in user_agents/context.py's docstring)."""
    from aughor.custom_agents import create_agent, delete_agent
    from aughor.custom_agents.context import activate_agent, release_agent

    agent = create_agent("receipt pack-preference probe",
                         instructions="Prefer cohort framing.",
                         pack_ids=["customer-analytics"])
    try:
        tok = activate_agent(agent)
        try:
            undeployed = _steers(flag_on=True, packs=[_shipped_pack(active=True)])
            _pin()
            deployed = _steers(flag_on=True, packs=[_shipped_pack(active=True)])
        finally:
            release_agent(tok)
    finally:
        _purge_probe_bindings()
        delete_agent(agent.id)
    return Comparison(
        scenario="agent_pack_preference_never_bypasses_the_deploy_gate",
        expected={"undeployed_steers": False, "deployed_steers": True},
        observed={"undeployed_steers": undeployed["steers"],
                  "deployed_steers": deployed["steers"]},
        oracle="declared (Wave H4)",
        note="a hired agent's pack preference restricts selection; deployment still gates",
    )


# ── what default-on makes load-bearing ───────────────────────────────────────────

@scenario("the_env_kill_switch_still_stops_a_fully_earned_steer")
def _the_env_kill_switch_still_stops_a_fully_earned_steer() -> Comparison:
    """The operator escape hatch, tested at full strength: active pack AND pinned
    binding — everything earned — and flag-off still refuses to steer. This is the
    control an explicit ``AUGHOR_SPECIALIST_PACKS=0`` keeps after graduation."""
    try:
        _pin()
        off = _steers(flag_on=False, packs=[_shipped_pack(active=True)])
        on = _steers(flag_on=True, packs=[_shipped_pack(active=True)])
    finally:
        _purge_probe_bindings()
    return Comparison(
        scenario="the_env_kill_switch_still_stops_a_fully_earned_steer",
        expected={"off_steers": False, "on_steers": True},
        observed={"off_steers": off["steers"], "on_steers": on["steers"]},
        oracle="declared (operator escape hatch)",
        note="flag off kills steering outright even when every data gate is earned",
        detail={"steered_by_when_on": on["pack_id"]},
    )


@scenario("a_broken_pack_on_disk_never_takes_down_intake")
def _a_broken_pack_on_disk_never_takes_down_intake() -> Comparison:
    """Default-on makes the best-effort scan load-bearing: a malformed pack
    directory is skipped (counted, tolerated), never raised into the answer path."""
    import tempfile

    from aughor.packs.intake import active_packs

    with tempfile.TemporaryDirectory() as tmp:
        broken = Path(tmp) / "broken-pack"
        broken.mkdir()
        (broken / "pack.yaml").write_text("::: not yaml :::[", encoding="utf-8")
        try:
            live = active_packs(packs_dir=tmp)
            survived, count = True, len(live)
        except Exception:
            survived, count = False, -1
    return Comparison(
        scenario="a_broken_pack_on_disk_never_takes_down_intake",
        expected={"survived": True, "active": 0},
        observed={"survived": survived, "active": count},
        oracle="declared (best-effort scan)",
        note="a pack that cannot load is skipped; intake proceeds unsteered",
    )


# ── the one delta, named rather than hidden ──────────────────────────────────────

@scenario("the_enabled_field_is_the_only_fresh_clone_delta")
def _the_enabled_field_is_the_only_fresh_clone_delta() -> Comparison:
    """What flipping the default actually changes for someone with no active packs
    and no deployments: ``GET /packs`` reports ``enabled: true``. The route is
    reachable either way (unlike Wave H there is no 404 to flip), and the pack
    listing itself is identical on and off — asserted, with the live pack count
    reported as detail rather than asserted."""
    from aughor.kernel.flags import flag_overrides
    from aughor.routers.packs import get_packs

    def probe(flag_on: bool) -> dict:
        with flag_overrides({FLAG: flag_on}):
            out = get_packs()
        return {"enabled": out["enabled"], "packs": len(out["packs"])}

    off, on = probe(False), probe(True)
    return Comparison(
        scenario="the_enabled_field_is_the_only_fresh_clone_delta",
        expected={"off_enabled": False, "on_enabled": True, "listing_identical": True},
        observed={"off_enabled": off["enabled"], "on_enabled": on["enabled"],
                  "listing_identical": off["packs"] == on["packs"]},
        oracle="declared (flag strategy batch 1)",
        note="the flip's whole fresh-clone effect: the surface reports the feature as on",
        detail={"packs_listed_here": on["packs"]},
    )


# ── the magnitude, measured on the real store ────────────────────────────────────

def measured_effect() -> dict[str, Any]:
    """What flipping the default reaches HERE — reported, never asserted: a fresh
    clone's numbers are zero/draft by construction."""
    from aughor.packs.intake import active_packs
    from aughor.packs.loader import list_packs

    base = _repo_root() / "packs"
    installed = list_packs(base) if base.is_dir() else []
    active = active_packs()
    return {
        "packs_installed": len(installed),
        "packs_active": len(active),
        "fresh_clone_delta": "GET /packs reports enabled: true; steering stays None "
                             "(no active pack, no pinned deployment)",
        "answer_path_delta": "none until a human activates a pack AND pins a deploy "
                             "binding on a connection",
        # Honest scope note: steering currently reaches the EXPLORE path only
        # (aughor/agent/explore.py); wiring it into investigate/quick-ask is a
        # separate, tracked gap — see docs/FLAG_STRATEGY_2026-07-31.md §2.
        "steering_reach": "explore path only",
    }


# ── the target, suite and graduation ─────────────────────────────────────────────

def receipt_target() -> Callable[[EvalCase], EvalObservation]:
    """Run the scenario named in ``case.expected["scenario"]``; unknown is an ERROR."""
    def target(case: EvalCase) -> EvalObservation:
        name = str((case.expected or {}).get("scenario") or case.id)
        fn = SCENARIOS.get(name)
        if fn is None:
            return EvalObservation(error=f"unknown specialist-packs scenario: {name!r}")
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
            description=("Flag strategy batch 1 — `specialist_packs` claims steering is "
                         "DATA-GATED three gates deep: an installed ACTIVE pack, matching "
                         "the question, with a human-pinned deploy binding on the exact "
                         "connection. Until all three are earned, injection_for_question "
                         "is None and the planner context is byte-identical on and off; "
                         "the flip's only fresh-clone effect is GET /packs reporting "
                         "enabled: true. The properties default-on makes load-bearing "
                         "(the env kill switch, the best-effort pack scan, the "
                         "no-bypass rule for hired agents' pack preferences) are asserted "
                         "alongside. Hermetic: no LLM, no warehouse; bindings are written "
                         "under synthetic probe connections and purged per case."),
            target="specialist_packs_receipt")
    suite_id = existing["id"]

    have = {(c.get("expected") or {}).get("scenario") for c in store.list_cases(suite_id)}
    missing = [n for n in SCENARIOS if n not in have]
    if missing:
        store.add_cases(suite_id, [
            {"question": f"Does {n} hold?", "expected": {"scenario": n},
             "tags": ["flag-strategy", "specialist_packs"]}
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
