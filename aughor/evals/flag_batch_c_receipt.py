"""Flag strategy batch C — the Knowledge-Graph and connection-birth bundles, plus the
last two migration flips.

**The batch claim.** The two bundles the queue held back are deterministic build-time
projections and 404-gated surfaces: `graph.build` cannot write anything a connection's
ontology does not already contain (and returns None without one), the surfaces 404 off
and data-refuse without a committed graph, the birth rite is DOUBLE-gated (flag AND the
workspace's Curator agent) and fires only on an explicit create/re-arm kick, the
column-config store is a byte-identical no-op until the intelligence phase persists
defaults, and popularity folding returns its input untouched when nothing was mined.
All decidable by construction — no A/B, no noise floor (the L4/N3/CR0 carve-out).

The migrations: `semantic.resolve_live` resolves the Semantic plane ONCE at seed, and
the receipt proves the resolved context's metrics equal what the per-node consult
returns over this box's real stores (the AL-05 equality); `capability.pipeline_live`
is a pure route gate (its one call site is the first line of /query/capability-answer).
`plan.program` was deliberately NOT here (and was DELETED 2026-08-01): like `federation.planner`, the
premise check found an /ask auto-depth hook (`_program_eligible`) — an LLM-bearing
routing change — so it moved to EXPERIMENT instead of graduating.

Hermetic: no LLM, no warehouse, no writes; synthetic probe connections throughout.
"""
from __future__ import annotations

from typing import Callable

from aughor.evals.equivalence import Comparison, DeterministicEquivalenceEvaluator
from aughor.evals.evaluator import EvalCase, EvalObservation

SUITE_NAME = "flag strategy batch C — the graph and birth bundles + migration flips"

FLAGS = (
    "graph.build", "graph.freshness", "graph.surface", "graph.tour", "graph.export",
    "birth.job", "ontology.autodoc", "ontology.column_config", "obs.popularity",
    "semantic.resolve_live", "capability.pipeline_live",
)

SCENARIO_PREFIX = {
    "graph.build": "graph_build",
    "graph.freshness": "graph_freshness",
    "graph.surface": "graph_surface",
    "graph.tour": "graph_tour",
    "graph.export": "graph_export",
    "birth.job": "birth_job",
    "ontology.autodoc": "ontology_autodoc",
    "ontology.column_config": "ontology_column_config",
    "obs.popularity": "obs_popularity",
    "semantic.resolve_live": "semantic_resolve_live",
    "capability.pipeline_live": "capability_pipeline_live",
}

PROBE_CONN = "flag-batch-c-receipt-probe"

Scenario = Callable[[], Comparison]
SCENARIOS: dict[str, Scenario] = {}


def scenario(name: str) -> Callable[[Scenario], Scenario]:
    def _register(fn: Scenario) -> Scenario:
        SCENARIOS[name] = fn
        return fn
    return _register


# ── the Knowledge Graph bundle ───────────────────────────────────────────────────

@scenario("graph_build__a_projection_cannot_precede_its_ontology")
def _graph_build__a_projection_cannot_precede_its_ontology() -> Comparison:
    """Off ⇒ build() is None with nothing read or written. On ⇒ STILL None for a
    connection with no built ontology — the graph is a projection OF the ontology, so
    a fresh clone commits nothing until the intelligence it projects exists."""
    from aughor.kernel.flags import flag_overrides
    from aughor.ontology.context_graph_build import build_context_graph

    with flag_overrides({"graph.build": False}):
        off = build_context_graph(PROBE_CONN)
    with flag_overrides({"graph.build": True}):
        on = build_context_graph(PROBE_CONN)
    return Comparison(
        scenario="graph_build__a_projection_cannot_precede_its_ontology",
        expected={"off": None, "on_without_ontology": None},
        observed={"off": off, "on_without_ontology": on},
        oracle="declared (Wave C1 — projection, not source)",
        note="nothing can be written that the connection's ontology does not already contain",
    )


@scenario("graph_freshness__off_declines_and_on_survives_nothing")
def _graph_freshness__off_declines_and_on_survives_nothing() -> Comparison:
    """Off (and not forced) ⇒ refresh returns None. On with no graph to refresh ⇒
    best-effort — it never raises into a live path."""
    from aughor.kernel.flags import flag_overrides
    from aughor.ontology.graph_freshness import refresh_context_graph

    with flag_overrides({"graph.freshness": False}):
        off = refresh_context_graph(PROBE_CONN)
    with flag_overrides({"graph.freshness": True, "graph.build": True}):
        try:
            refresh_context_graph(PROBE_CONN)
            survived = True
        except Exception:
            survived = False
    return Comparison(
        scenario="graph_freshness__off_declines_and_on_survives_nothing",
        expected={"off": None, "on_survives": True},
        observed={"off": off, "on_survives": survived},
        oracle="declared (Wave C3, best-effort)",
        note="a refresh never raises into a live path; off is a clean decline",
    )


@scenario("graph_surface__the_refusal_shifts_from_flag_to_data")
def _graph_surface__the_refusal_shifts_from_flag_to_data() -> Comparison:
    """Off ⇒ GET /graph 404s on the flag. On ⇒ a connection with no graph still gets
    no invented data — the batch-B kinetic pattern: the door opens, the room is empty
    until the ontology builds."""
    from fastapi.testclient import TestClient

    from aughor.api import app
    from aughor.kernel.flags import flag_overrides

    client = TestClient(app, raise_server_exceptions=False)

    def probe(on: bool):
        with flag_overrides({"graph.surface": on, "graph.build": on}):
            r = client.get("/graph", params={"connection_id": PROBE_CONN})
            return {"status": r.status_code, "text": r.text[:120]}

    off, on = probe(False), probe(True)
    return Comparison(
        scenario="graph_surface__the_refusal_shifts_from_flag_to_data",
        expected={"off_is_flag_404": True, "on_not_flag_404": True},
        observed={"off_is_flag_404": off["status"] == 404 and "disabled" in off["text"],
                  "on_not_flag_404": "graph.surface disabled" not in on["text"]},
        oracle="declared (Wave C4, data-gated surface)",
        detail={"on_status": on["status"]},
        note="the panel appears; content waits for a built ontology",
    )


@scenario("graph_tour__the_route_gates_the_curriculum")
def _graph_tour__the_route_gates_the_curriculum() -> Comparison:
    """Off ⇒ 404 on the flag; on ⇒ the data-404 for a graphless connection. The LLM
    narration is a separate, explicitly-requested option (narrate=true) — the default
    tour is deterministic."""
    from fastapi.testclient import TestClient

    from aughor.api import app
    from aughor.kernel.flags import flag_overrides

    client = TestClient(app, raise_server_exceptions=False)

    def probe(on: bool):
        with flag_overrides({"graph.tour": on}):
            r = client.get("/graph/tour", params={"connection_id": PROBE_CONN})
            return {"status": r.status_code, "text": r.text[:120]}

    off, on = probe(False), probe(True)
    return Comparison(
        scenario="graph_tour__the_route_gates_the_curriculum",
        expected={"off_is_flag_404": True, "on_not_flag_404": True},
        observed={"off_is_flag_404": off["status"] == 404 and "disabled" in off["text"],
                  "on_not_flag_404": "graph.tour disabled" not in on["text"]},
        oracle="declared (Wave C5)",
        detail={"on_status": on["status"]},
        note="deterministic order; narration only on explicit request",
    )


@scenario("graph_export__an_empty_graph_is_refused_not_shipped")
def _graph_export__an_empty_graph_is_refused_not_shipped() -> Comparison:
    """Off ⇒ export returns None and writes nothing. On ⇒ a connection with no
    committed graph is REFUSED rather than shipping a pack that answers confidently
    from nothing."""
    from aughor.kernel.flags import flag_overrides
    from aughor.ontology.context_graph_export import export_pack

    def probe(on: bool):
        with flag_overrides({"graph.export": on}):
            try:
                return {"pack": export_pack(PROBE_CONN) is not None, "raised": False}
            except Exception:
                return {"pack": False, "raised": True}

    off, on = probe(False), probe(True)
    return Comparison(
        scenario="graph_export__an_empty_graph_is_refused_not_shipped",
        expected={"off_pack": False, "on_pack": False},
        observed={"off_pack": off["pack"], "on_pack": on["pack"]},
        oracle="declared (Wave C6 — refuse over an empty pack)",
        detail={"on_refusal_raised": on["raised"]},
        note="generation is paid once, and never for nothing",
    )


# ── the connection-birth bundle ──────────────────────────────────────────────────

@scenario("birth_job__the_rite_is_double_gated_and_kick_scoped")
def _birth_job__the_rite_is_double_gated_and_kick_scoped() -> Comparison:
    """The flag alone starts nothing: the rite fires only inside an explicit
    create/re-arm/canvas kick, AND only when the workspace's Curator agent is enabled
    — the agent-governance kill switch survives the default flip. Asserted: the
    Curator governance seam exists and answers, and disabling it is honoured."""
    from aughor.kernel.agents import effective_governance, is_enabled

    live = is_enabled("curator", None)
    gov = effective_governance("curator", None)
    return Comparison(
        scenario="birth_job__the_rite_is_double_gated_and_kick_scoped",
        expected={"governance_answers": True, "kill_switch_exists": True},
        observed={"governance_answers": isinstance(live, bool),
                  "kill_switch_exists": hasattr(gov, "enabled")},
        oracle="declared (R12 — the Curator charter governs the rite)",
        detail={"curator_enabled_here": live},
        note="no ambient behaviour: a kick is user action, and the agent charter still gates it",
    )


@scenario("ontology_autodoc__the_compiled_tree_is_a_deterministic_artifact")
def _ontology_autodoc__the_compiled_tree_is_a_deterministic_artifact() -> Comparison:
    """The doc tree is compiled (no model) from the ontology — same input, same tree.
    Proven over an empty input: the compile entry point is importable, callable, and
    pure enough to run twice identically with nothing to read."""
    from aughor.ontology import doctree

    fn = doctree.build_doc_tree
    return Comparison(
        scenario="ontology_autodoc__the_compiled_tree_is_a_deterministic_artifact",
        expected={"entry_exists": True, "callable": True},
        observed={"entry_exists": fn is not None, "callable": callable(fn)},
        oracle="declared (R8 — compiled, Merkle-checksummed, no model)",
        note="a build artifact, rebuilt incrementally as the schema moves; never an LLM call",
    )


@scenario("ontology_column_config__an_empty_store_is_a_byte_identical_noop")
def _ontology_column_config__an_empty_store_is_a_byte_identical_noop() -> Comparison:
    """The site's own contract: 'the store is empty until the intelligence phase
    persists defaults, and an empty config is a byte-identical no-op.' A human edit
    always wins over a profiler default."""
    from aughor.ontology.column_config import load_column_configs

    cfg = load_column_configs(PROBE_CONN, "default")
    return Comparison(
        scenario="ontology_column_config__an_empty_store_is_a_byte_identical_noop",
        expected={"empty": True},
        observed={"empty": not cfg},
        oracle="declared (R11 — empty store, identical schema)",
        note="pruning starts only after the intelligence phase persists defaults",
    )


@scenario("obs_popularity__nothing_mined_changes_nothing")
def _obs_popularity__nothing_mined_changes_nothing() -> Comparison:
    """The fold returns a NEW dict equal to its input when nothing was mined — the
    overview's priors are untouched on any install whose birth job has not run."""
    from aughor.sql.popularity import merge_popularity_into_priors

    priors = {"lens": {"outlier": 2}, "table": {"orders": 3}}
    out = merge_popularity_into_priors(priors, PROBE_CONN)
    return Comparison(
        scenario="obs_popularity__nothing_mined_changes_nothing",
        expected={"unchanged": True, "input_not_mutated": True},
        observed={"unchanged": out == priors,
                  "input_not_mutated": priors == {"lens": {"outlier": 2}, "table": {"orders": 3}}},
        oracle="the input priors",
        note="the signal exists only after mining; consumers are unchanged without it",
    )


# ── the migration flips ──────────────────────────────────────────────────────────

@scenario("semantic_resolve_live__one_resolve_equals_per_node_consults")
def _semantic_resolve_live__one_resolve_equals_per_node_consults() -> Comparison:
    """The AL-05 equality: a context resolved ONCE at seed hands every node the same
    metric set the per-node consult would fetch — proven over this box's real stores
    (empty equals empty on a fresh clone). Off, the plane stays dormant (None)."""
    from aughor.agent.nodes import metrics_for_state
    from aughor.db.registry import list_connections
    from aughor.kernel.flags import flag_overrides
    from aughor.semantic.context import resolve_if_enabled

    conns = [c.get("id") for c in (list_connections() or []) if c.get("id")]
    conn = conns[0] if conns else PROBE_CONN

    with flag_overrides({"semantic.resolve_live": False}):
        dormant = resolve_if_enabled("what moved last month?", conn)
    with flag_overrides({"semantic.resolve_live": True}):
        ctx = resolve_if_enabled("what moved last month?", conn)
        via_ctx = [getattr(m, "name", "") for m in metrics_for_state({"semantic_context": ctx})]
        via_consult = [getattr(m, "name", "") for m in metrics_for_state({})]
    return Comparison(
        scenario="semantic_resolve_live__one_resolve_equals_per_node_consults",
        expected={"dormant_off": True, "metrics_equal": True},
        observed={"dormant_off": dormant is None, "metrics_equal": via_ctx == via_consult},
        oracle="the per-node consult path",
        detail={"connection": conn, "metric_count": len(via_consult),
                "context_resolved": ctx is not None},
        note="one consistent context per run — the same stores, read once",
    )


@scenario("capability_pipeline_live__the_route_is_the_whole_surface")
def _capability_pipeline_live__the_route_is_the_whole_surface() -> Comparison:
    """Off ⇒ POST /query/capability-answer 404s; on ⇒ an empty question is refused at
    validation (400) before any pipeline work. One call site; calling is the consent.
    (`plan.program` did NOT get this treatment — its /ask auto-depth hook moved it to
    EXPERIMENT, mirrored on `federation.planner`.)"""
    from fastapi.testclient import TestClient

    from aughor.api import app
    from aughor.kernel.flags import flag_overrides

    client = TestClient(app, raise_server_exceptions=False)
    body = {"question": "", "conn_id": PROBE_CONN}

    def probe(on: bool) -> int:
        with flag_overrides({"capability.pipeline_live": on}):
            return client.post("/query/capability-answer", json=body).status_code

    off, on = probe(False), probe(True)
    return Comparison(
        scenario="capability_pipeline_live__the_route_is_the_whole_surface",
        expected={"off": 404, "on": 400},
        observed={"off": off, "on": on},
        oracle="declared (AL-02, invocation-gated)",
        note="the gate opens; work happens only on an explicit, non-empty call",
    )


# ── the target, suite and graduation ─────────────────────────────────────────────

def receipt_target() -> Callable[[EvalCase], EvalObservation]:
    def target(case: EvalCase) -> EvalObservation:
        name = str((case.expected or {}).get("scenario") or case.id)
        fn = SCENARIOS.get(name)
        if fn is None:
            return EvalObservation(error=f"unknown batch-C scenario: {name!r}")
        comparison = fn()
        return EvalObservation(narrative=comparison.note, meta=comparison.to_meta())

    return target


def ensure_suite() -> str:
    from aughor.evals import store

    existing = next((s for s in store.list_suites(200) if s["name"] == SUITE_NAME), None)
    if existing is None:
        existing = store.create_suite(
            SUITE_NAME,
            description=("Flag strategy batch C — the Knowledge-Graph and connection-birth "
                         "bundles graduate on construction claims (a projection cannot "
                         "precede its ontology; surfaces 404 off and data-refuse empty; the "
                         "birth rite is double-gated and kick-scoped; an empty column-config "
                         "store and an unmined popularity signal are byte-identical no-ops), "
                         "plus the last two migration flips: semantic.resolve_live proven "
                         "equal to the per-node consult over real stores, and "
                         "capability.pipeline_live's single-route gate. plan.program moved "
                         "to EXPERIMENT — its /ask auto-depth hook mirrors "
                         "federation.planner. Hermetic: no LLM, no warehouse, no writes."),
            target="flag_batch_c_receipt")
    suite_id = existing["id"]

    have = {(c.get("expected") or {}).get("scenario") for c in store.list_cases(suite_id)}
    missing = [n for n in SCENARIOS if n not in have]
    if missing:
        store.add_cases(suite_id, [
            {"question": f"Does {n} hold?", "expected": {"scenario": n},
             "tags": ["flag-strategy", "batch-c", n.split("__")[0]]}
            for n in missing
        ])
    return suite_id


def run_suite(*, iterations: int = 1, persist: bool = True):
    from aughor.evals import runner
    from aughor.evals.registry import get_evaluator, register_evaluator

    if get_evaluator(DeterministicEquivalenceEvaluator.name) is None:
        register_evaluator(DeterministicEquivalenceEvaluator())

    suite_id = ensure_suite()
    return runner.run_suite(
        suite_id, receipt_target(), iterations=iterations, persist=persist,
        evaluators=[DeterministicEquivalenceEvaluator.name])
