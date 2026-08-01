"""Runtime feature flags — operator-toggleable, env-var fallback.

A handful of capabilities ship off-by-default because they cost (per-table version
probes, prompt-content capture). They were previously env-only (e.g.
`AUGHOR_SNAPSHOT_RECEIPTS`), so an operator had to restart the process to flip them.
This stores an override in the kernel ledger kv so the UI can toggle them at runtime;
when no override is set, the env var still decides.

`flag_enabled(name)` is the resolver the feature code calls. The override is read from
SQLite per call (one indexed kv read — negligible; these aren't ultra-hot paths).
"""
from __future__ import annotations

import contextlib
import contextvars
import os
from typing import Optional

from aughor.kernel.ledger import Ledger

_STORE = "feature_flags"

# Registered flags: logical name → the env var that decides when no override is set.
FLAG_ENV = {
    # "ai_sql" (AUGHOR_AI_SQL) was DELETED 2026-08-01 (flag endgame, verdict sheet
    # Wave 1): off since birth, per-row LLM calls inside SQL are a cost trap, and the
    # guarded semantic operators (aughor/semops/operators.py) cover the need. The
    # prompt()/embedding() UDF module (semops/ai_sql.py) went with it; the generic
    # execution-hook seams it registered into remain.
    "snapshot_receipts": "AUGHOR_SNAPSHOT_RECEIPTS",
    "explorer.synthesis_incremental": "AUGHOR_SYNTHESIS_INCREMENTAL",
    "specialist_packs": "AUGHOR_SPECIALIST_PACKS",
    "explore.parallel_subq": "AUGHOR_EXPLORE_PARALLEL",
    "explore.route_wide": "AUGHOR_EXPLORE_ROUTE_WIDE",
    "starters.library": "AUGHOR_STARTERS_LIBRARY",
    "lens.decision_grade": "AUGHOR_LENS_DECISION_GRADE",
    "report.argument_style": "AUGHOR_REPORT_ARGUMENT_STYLE",
    "chart.exhibit_grammar": "AUGHOR_CHART_EXHIBIT_GRAMMAR",
    "intake.loss_signals": "AUGHOR_INTAKE_LOSS_SIGNALS",
    "ontology.autodoc": "AUGHOR_ONTOLOGY_AUTODOC",
    "ontology.column_config": "AUGHOR_ONTOLOGY_COLUMN_CONFIG",
    "birth.job": "AUGHOR_BIRTH_JOB",
    "deep_analysis.parallel_lenses": "AUGHOR_DEEP_ANALYSIS_PARALLEL_LENSES",
    "deep_analysis.parallel_phases": "AUGHOR_DEEP_ANALYSIS_PARALLEL_PHASES",
    "deep_analysis.why_where_interaction": "AUGHOR_DEEP_ANALYSIS_WHY_WHERE_INTERACTION",
    "deep_analysis.why_deepen": "AUGHOR_DEEP_ANALYSIS_WHY_DEEPEN",
    "deep_analysis.parallel_why_lenses": "AUGHOR_DEEP_ANALYSIS_PARALLEL_WHY_LENSES",
    "preflight.parallel": "AUGHOR_PREFLIGHT_PARALLEL",
    "trust.verify_facade": "AUGHOR_TRUST_FACADE",
    "trust.verify_live": "AUGHOR_TRUST_VERIFY_LIVE",
    "semantic.resolve_live": "AUGHOR_SEMANTIC_RESOLVE_LIVE",
    "semantic.contract_live": "AUGHOR_SEMANTIC_CONTRACT_LIVE",
    "capability.pipeline_live": "AUGHOR_CAPABILITY_PIPELINE_LIVE",
    "deep_analysis.premise_check": "AUGHOR_PREMISE_CHECK",
    "deep_analysis.causal_drill": "AUGHOR_CAUSAL_DRILL",
    # "ada.adversarial_verify" (AUGHOR_ADA_ADVERSARIAL) was DELETED 2026-07-31 (flag
    # strategy §4G): the always-challenge tier was superseded by the materiality-gated
    # auto tier below, had no constituency, and a deleted flag is the only disposition
    # that actually shrinks the registry. One-off audits can reproduce it by asking the
    # question directly; the refuter itself (run_refutation) is unchanged.
    "deep_analysis.adversarial_high_stakes": "AUGHOR_DEEP_ANALYSIS_ADVERSARIAL_HIGH_STAKES",
    "deep_analysis.pin_canonical_metric": "AUGHOR_DEEP_ANALYSIS_PIN_CANONICAL_METRIC",
    "deep_analysis.progress_events": "AUGHOR_DEEP_ANALYSIS_PROGRESS_EVENTS",
    "deep_analysis.clarify_gate": "AUGHOR_CLARIFY_GATE",
    "ask.clarify": "AUGHOR_ASK_CLARIFY",
    "ask.resolve_first": "AUGHOR_ASK_RESOLVE_FIRST",
    "ask.conversation_context": "AUGHOR_ASK_CONVERSATION_CONTEXT",
    "ask.brief_context": "AUGHOR_ASK_BRIEF_CONTEXT",
    "closed_loop": "AUGHOR_CLOSED_LOOP",
    "consistency.divergence": "AUGHOR_CONSISTENCY_DIVERGENCE",  # Wave N1: same question, two answers
    "semops.guarded_extract": "AUGHOR_GUARDED_EXTRACT",
    "join.key_reconciliation": "AUGHOR_JOIN_KEY_RECONCILIATION",
    "semops.champion_validate": "AUGHOR_SEMOPS_CHAMPION_VALIDATE",
    "federation.remote_join": "AUGHOR_FEDERATION_REMOTE_JOIN",
    "federation.planner": "AUGHOR_FEDERATION_PLANNER",
    "plan.program": "AUGHOR_PLAN_PROGRAM",
    "capability.contract": "AUGHOR_CAPABILITY_CONTRACT",
    "rbac.row_policy": "AUGHOR_RBAC_ROW_POLICY",
    # "obs.mlflow" (AUGHOR_OBS_MLFLOW) was DELETED 2026-07-31 (flag strategy §4C):
    # MLflow tracing now self-gates on AUGHOR_MLFLOW_TRACKING_URI being set, like the
    # other env-configured observability backends — a flag that is a no-op without an
    # external server and inert with one configured was two ways to be confused.
    "obs.task_table": "AUGHOR_OBS_TASK_TABLE",
    "obs.session_log": "AUGHOR_OBS_SESSION_LOG",
    "obs.prompt_capture": "AUGHOR_OBS_PROMPT_CAPTURE",
    "obs.popularity": "AUGHOR_OBS_POPULARITY",
    "llm.structured_salvage": "AUGHOR_LLM_STRUCTURED_SALVAGE",
    "llm.bounded_repair": "AUGHOR_LLM_BOUNDED_REPAIR",
    "explore.wandering_detector": "AUGHOR_EXPLORE_WANDERING_DETECTOR",
    "schema.two_tier_catalog": "AUGHOR_SCHEMA_TWO_TIER_CATALOG",
    "deep_analysis.evidence_dedup": "AUGHOR_DEEP_ANALYSIS_EVIDENCE_DEDUP",
    # "deep_analysis.evidence_stubs" (AUGHOR_DEEP_ANALYSIS_EVIDENCE_STUBS) was DELETED
    # 2026-08-01 (flag endgame, verdict sheet Wave 1): it rendered already-scored
    # results as row-capped stubs — deliberately showing the model FEWER rows to save
    # tokens, the opposite of the evidence-budget direction, and its own description
    # forbade graduation without the A/B that was never bought. Its lossless sibling
    # (evidence_dedup) carries the whole win.
    "evals.experiments": "AUGHOR_EVALS_EXPERIMENTS",
    "ask.context_receipt": "AUGHOR_ASK_CONTEXT_RECEIPT",
    "ask.stream_text": "AUGHOR_ASK_STREAM_TEXT",
    "ask.overview": "AUGHOR_ASK_OVERVIEW",
    "agents.user_defined": "AUGHOR_USER_AGENTS",
    # "search.rrf" (AUGHOR_SEARCH_RRF) was DELETED 2026-08-01 (flag endgame, verdict
    # sheet Wave 1): the RRF fusion was MEASURED worse than the α-blend default on the
    # real KB corpus (MRR 0.964 vs 0.977, recall@1 0.931 vs 0.957 — the since-removed
    # evals/rrf_retrieval_eval.py). hybrid_rerank now α-blends unconditionally.
    "explorer.manifest_driven": "AUGHOR_EXPLORER_MANIFEST_DRIVEN",
    "learning.receipt": "AUGHOR_LEARNING_RECEIPT",
    "capabilities.auto": "AUGHOR_CAPABILITIES_AUTO",
    "capabilities.receipt": "AUGHOR_CAPABILITIES_RECEIPT",
    "trust.e1_live": "AUGHOR_TRUST_E1_LIVE",
    "monitors.guarded": "AUGHOR_MONITORS_GUARDED",
    "explorer.continuous": "AUGHOR_EXPLORER_CONTINUOUS",
    "ops.metered_monitors": "AUGHOR_METERED_MONITORS",
    "agui.endpoint": "AUGHOR_AGUI_ENDPOINT",
    "kinetic.actions": "AUGHOR_KINETIC_ACTIONS",  # Wave K: overlay human-declared actions onto the graph
    "kinetic.overlay": "AUGHOR_KINETIC_OVERLAY",  # Wave K3: merge human overlay edits onto query results
    "kinetic.agent_actions": "AUGHOR_KINETIC_AGENT_ACTIONS",  # Wave K4: the agent may PROPOSE declared actions
    "automations.engine": "AUGHOR_AUTOMATIONS_ENGINE",  # Wave A2: the condition→effect heartbeat + API
    "automations.source_probes": "AUGHOR_AUTOMATIONS_SOURCE_PROBES",  # Wave A3: source-version change detection
    "automations.proposals": "AUGHOR_AUTOMATIONS_PROPOSALS",  # Wave A4: resolve-once proposal inbox + standing grants
    "automations.adopt_legacy": "AUGHOR_AUTOMATIONS_ADOPT_LEGACY",  # Wave A5: run monitors+briefs through the engine
    "graph.build": "AUGHOR_GRAPH_BUILD",  # Wave C1: project the ontology into the committed connection knowledge graph
    "graph.readback": "AUGHOR_GRAPH_READBACK",  # Wave C2: grep-the-graph-first — inject the graph slice as a plan-time prior
    "graph.freshness": "AUGHOR_GRAPH_FRESHNESS",  # Wave C3: change-classified, token-proportional graph refresh + staleness
    "graph.surface": "AUGHOR_GRAPH_SURFACE",  # Wave C4: serve + render the connection knowledge graph (anti-hairball surface)
    "graph.tour": "AUGHOR_GRAPH_TOUR",  # Wave C5: the deterministic, LLM-narrated connection tour (a curriculum from topology)
    "graph.export": "AUGHOR_GRAPH_EXPORT",  # Wave C6: export the graph as a self-contained, offline-consumable skills pack
    "graph.consolidate": "AUGHOR_GRAPH_CONSOLIDATE",  # Wave N3: consolidate + age findings BEFORE the cap
    "govern.clearances": "AUGHOR_GOVERN_CLEARANCES",  # Wave G2: governed tags gate retrieval and action
    "govern.usage_caps": "AUGHOR_GOVERN_USAGE_CAPS",  # Wave G4: org/user spend caps, pre-flight only
    "freshness.resolved_rebuild": "AUGHOR_FRESHNESS_RESOLVED_REBUILD",  # Wave V2: rebuild on inputs+logic, not on a timer
    "lifecycle.publish": "AUGHOR_LIFECYCLE_PUBLISH",  # Wave V3: save≠publish, versions, changelog, revert
    "lifecycle.freeze": "AUGHOR_LIFECYCLE_FREEZE",  # Wave V4: live-by-default + explicit freeze; gone data errors loudly
}

# ── Renamed flags (Wave W vocabulary unification) ─────────────────────────────────────
# A flag name is a CONTRACT with three independent holders: an operator's `.env`, a
# persisted runtime override row in the ledger kv, and any script passing the name to
# `flag_overrides`. Renaming the FLAG_ENV key alone silently strands all three — the
# operator's variable stops being read, the stored override stops being found, and the
# script raises UnknownFlagError. `MIGRATION` does not help: it is a disposition
# CATEGORY for two-code-path forks, not a rename facility.
#
# So a rename registers here instead of just editing FLAG_ENV, and every resolution
# path canonicalizes through it. Both maps EMPTY means the layer is inert and flag
# resolution is byte-identical to before it existed (asserted in the ratchet test).
#
# Retiring a name is a one-line move, never a deletion:
#   RENAMED["ada.parallel_lenses"] = "deep_analysis.parallel_lenses"
#   RETIRED_ENV["AUGHOR_ADA_PARALLEL_LENSES"] = "deep_analysis.parallel_lenses"

#: Retired flag name → its current name. Old names keep working; they never re-register
#: in FLAG_ENV (the ratchet asserts this, so a rename cannot be quietly reverted).
RENAMED: dict[str, str] = {
    # Wave W: the `ada.*` family. "ADA" expanded, in its own docstring, to words it does
    # not spell; the feature is "deep analysis" everywhere a human reads it. Call sites
    # may keep passing the old name indefinitely — `_canonical` resolves it.
    "ada.adversarial_high_stakes": "deep_analysis.adversarial_high_stakes",
    "ada.causal_drill": "deep_analysis.causal_drill",
    "ada.clarify_gate": "deep_analysis.clarify_gate",
    "ada.evidence_dedup": "deep_analysis.evidence_dedup",
    "ada.parallel_lenses": "deep_analysis.parallel_lenses",
    "ada.parallel_phases": "deep_analysis.parallel_phases",
    "ada.parallel_why_lenses": "deep_analysis.parallel_why_lenses",
    "ada.pin_canonical_metric": "deep_analysis.pin_canonical_metric",
    "ada.premise_check": "deep_analysis.premise_check",
    "ada.progress_events": "deep_analysis.progress_events",
    "ada.why_deepen": "deep_analysis.why_deepen",
    "ada.why_where_interaction": "deep_analysis.why_where_interaction",
}

#: Retired env var → the flag it now feeds. Consulted only when the current flag's own
#: env var is unset, so an operator who has already migrated is never second-guessed.
RETIRED_ENV: dict[str, str] = {
    # Wave W: `AUGHOR_ADA_*` → `AUGHOR_DEEP_ANALYSIS_*`. An operator's existing .env keeps
    # opting in. (The three `ada.*` flags whose env var never said ADA — PREMISE_CHECK,
    # CAUSAL_DRILL, CLARIFY_GATE — kept their variable and need no entry.)
    "AUGHOR_ADA_ADVERSARIAL_HIGH_STAKES": "deep_analysis.adversarial_high_stakes",
    "AUGHOR_ADA_EVIDENCE_DEDUP": "deep_analysis.evidence_dedup",
    "AUGHOR_ADA_PARALLEL_LENSES": "deep_analysis.parallel_lenses",
    "AUGHOR_ADA_PARALLEL_PHASES": "deep_analysis.parallel_phases",
    "AUGHOR_ADA_PARALLEL_WHY_LENSES": "deep_analysis.parallel_why_lenses",
    "AUGHOR_ADA_PIN_CANONICAL_METRIC": "deep_analysis.pin_canonical_metric",
    "AUGHOR_ADA_PROGRESS_EVENTS": "deep_analysis.progress_events",
    "AUGHOR_ADA_WHY_DEEPEN": "deep_analysis.why_deepen",
    "AUGHOR_ADA_WHY_WHERE_INTERACTION": "deep_analysis.why_where_interaction",
}


def _canonical(name: str) -> str:
    """The current name for a possibly-retired flag name.

    Follows a chain (a flag renamed twice) with a bound, so a mistaken cycle degrades to
    "resolve as far as we got" rather than hanging the answer path.
    """
    seen = name
    for _ in range(4):
        nxt = RENAMED.get(seen)
        if nxt is None or nxt == seen:
            return seen
        seen = nxt
    return seen


def _retired_names(name: str) -> list[str]:
    """Every retired name that now resolves to ``name`` — the keys an override may still
    be persisted under. Computed per call: RENAMED is a handful of entries and this runs
    only when the canonical lookup already missed."""
    return [old for old in RENAMED if _canonical(old) == name and old != name]

# A flag whose env var is UNSET resolves to its default (False unless listed).
# `ask.clarify` shipped default-ON (`os.getenv("AUGHOR_ASK_CLARIFY", "1")` at the
# old call site), so registering it here must not flip the live default.
FLAG_DEFAULT = {
    "ask.clarify": True,
    # WP-1f (2026-07-12 platform review) — the trust plane LEVERAGED, not just built.
    # Promoted to default-ON after a live A/B over the workspace + fixture healthy-path
    # corpus (1,837 unique executed statements): `trust.verify_live` produced ZERO
    # false-positive blocks, and once the E1 live checks read real column types
    # (`connection_column_types`) the only false-positive caveat — a DATE column named
    # `*_at`/`*_ts` tripping the name heuristic — disappeared, leaving only genuine
    # timestamp-boundary footguns. An operator can still disable any of these with an
    # explicit env `=0` or a runtime override. See docs/PLATFORM_REVIEW…2026-07-12.md WP-1f.
    "trust.verify_live": True,     # AST read-only BLOCK on the deep-answer executor path
    "trust.e1_live": True,         # E1 function-semantics WARN caveats on live answers
    "trust.verify_facade": True,   # AST read-only gate on the /query/validate surface (additive field)
    # Capability graduation (2026-07-13, agentic-platform unification). Policy: a capability that is
    # (a) self-gating behind a deterministic runtime trigger, or (b) a pure observability/receipt
    # surface with negligible cost, GRADUATES to default-on once BUILT→WIRED→TESTED. The platform
    # decides per run; the operator can still force any flag off (env =0 / runtime override) — an
    # explicit setting always wins over these defaults. This is E3 Phase 1 ("the flag system should
    # decide, with receipts") made the default posture instead of an opt-in.
    "capabilities.auto": True,     # master: self-gating guards elevate; their triggers gate per run
    "capabilities.receipt": True,  # autonomy requires receipts — record which guard fired and why
    "learning.receipt": True,      # learning visibility: reused/crystallized resolutions per answer
    "ask.context_receipt": True,   # input-side trust: the exact grounding block, inspectable
    "obs.task_table": True,        # the queryable spine — a sink over spans already emitted
    "deep_analysis.progress_events": True,   # deep-run dead-air fix (CK-0.4): fine-grained progress beats
    "ask.stream_text": True,       # CK-0.2 dual-emit insight deltas; terminal event stays authoritative
    # Presentation/intake graduation — Batch 1 of the flag-drift audit (2026-07-22).
    # See docs/FLAG_GRADUATION_AUDIT_2026-07-22.md.
    #
    # These four had been ON in one developer's runtime ledger for weeks while the code
    # shipped them OFF, so every fresh clone, every CI run, and every other user got none of
    # them — and CI was validating a configuration nobody actually ran. They graduate first
    # because they share the property that makes a default flip safe to review: each is
    # DETERMINISTIC (no model in the loop, no extra query) and each is byte-identical when
    # off, so flipping the default cannot change behaviour except along its intended axis.
    # An operator can still force any of them off (env `=0` or a runtime override).
    #
    # `intake.loss_signals` is the load-bearing one: it does not add polish, it fixes a
    # WRONG ANSWER. The 2026-07-16 A/B caught a revenue ranking reporting "broadly healthy"
    # over 2.4M CHF of refund leakage and a 1.2M CHF utilization gap, and it forbids the
    # un-computable verdict ("profitable" / "no losses" without cost data).
    "intake.loss_signals": True,    # deterministic loss-signal scan at question intake
    "report.argument_style": True,  # deterministic re-composition of the SAME report data
    "chart.exhibit_grammar": True,  # exhibit spec computed from rows already fetched
    "lens.decision_grade": True,    # opportunity-cost + named-outlier lenses (one bounded probe)
    # Wave R1 — the structured-call reliability layer. Default-ON deliberately, and the
    # reasoning is narrower than "it seemed safe": this code runs ONLY on a call that has
    # already raised. Today that raise walks the fallback chain, spending a whole extra
    # request against a SECOND provider to re-answer a prompt whose first answer was
    # correct JSON wrapped in a markdown fence. Off, that waste is the default; on, it is
    # deterministic text repair with zero additional requests. Its sibling
    # `llm.bounded_repair` — which does spend a request — stays default-OFF below.
    #
    # The one risk of salvage is accepting a mangled object where a loud failure would
    # have failed over to a better model, so the normalizer is built to be incapable of
    # it: every transform is structural (fences, trailing commas, literal case), and the
    # single judgement call — enum matching — folds case and separators only and refuses
    # anything fuzzy (`reliability._fold`). "HIGH"→"high" is the same token; "hgih" still
    # fails loudly.
    "llm.structured_salvage": True,
    # Default-ON for a reason that only became visible once the transport stack was
    # measured end-to-end: instructor's own default is THREE attempts, and we had never
    # overridden it, so a malformed response already cost 3 full-prompt requests. Wave R1
    # sets that to 1 (`_structured_attempts`) and this flag is what replaces the two we
    # removed — at a fraction of the size, because the repair carries the broken output
    # and the specific error rather than a second copy of the original prompt and its
    # evidence. Off, the ceiling is 1 request per failure and some salvageable answers
    # are lost; on, it is 2 — still below the 3 this wave inherited.
    "llm.bounded_repair": True,
    # Wave L4 (2026-07-27) — graduated on MEASURED equivalence, receipt `65364174a172`, from
    # run `309b715b05c0` of the deterministic suite `aughor/evals/equivalence.py` (9/9 stable
    # passes, 0 errors, 0 flaky, bar 1.0). The evidence is not "the tests are green": the suite
    # runs the legacy monitor loop and the engine loop UNPATCHED against a real DuckDB warehouse
    # and compares the alerts byte-for-byte — severity, message, current value, threshold — plus
    # the anti-flap debounce and the no-double-fire property. A5's unit tests patch `run_monitor`,
    # so they were only ever evidence about the wiring.
    #
    # What flipping this actually changes on a fresh clone: the condition→effect heartbeat starts
    # and the /automations routes stop 404-ing. It does NOT start doing anything on its own — the
    # engine drives only automations an operator explicitly created, so a clone with none behaves
    # as before. Its two siblings stay OFF and hold their own receipts (`e6c39abad50a`,
    # `33fc34ddbd47`): `adopt_legacy` changes the code path that DELIVERS briefs (an outward
    # send), and `source_probes` adds recurring per-tick warehouse aggregates — both are default
    # decisions about cost and outward behaviour, not about whether the equivalence holds.
    "automations.engine": True,
    # Wave N3 (2026-07-28) — graduated on a DETERMINISTIC artifact claim, from run
    # `3dec60f4a580` of the suite `aughor/evals/consolidation.py` (8/8 stable passes, 0
    # errors, 0 flaky, bar 1.0, no baseline — a claim with no sampling has no A/B and so
    # needs no noise floor, the same carve-out L4 used).
    #
    # The suite proves the INVARIANTS hermetically (lossless, never-picks-a-winner,
    # budget respected, stale evicted before live, unknown-ontology expires nothing,
    # flag-off payload identical). The MAGNITUDE was measured separately on the reference
    # connection, because an invariant that holds over a fixture proves correctness, not
    # usefulness — 100 findings before and after, but distinct conclusions 88 → 94 and
    # findings grounded in tables that no longer exist 22 → 0, with 203 older readings
    # folded into their survivors and 9 genuine disagreements LABELLED rather than settled.
    #
    # What flipping this changes on a fresh clone: the next graph build spends its 100-node
    # budget on distinct, still-verifiable findings instead of the 100 most recent receipts.
    # It adds no LLM call, no warehouse query and nothing on the answer path — the extra
    # cost is one bounded read of a local store. It does NOT rewrite any committed artifact;
    # an existing graph changes only when something rebuilds it.
    "graph.consolidate": True,
    # Wave CR0 (2026-07-29) — graduated on a DETERMINISTIC observationally-free claim,
    # receipt `45dcc137f55b`, from run `43bf2bc7182d` of the suite
    # `aughor/evals/session_log_receipt.py` (7/7 stable passes, 0 errors, 0 flaky, bar 1.0,
    # no baseline — the claim has no sampling, the same carve-out L4 and N3 used).
    #
    # The suite proves the INVARIANTS hermetically against throwaway ledgers: the door
    # wrapper yields byte-identical frames flag-on vs flag-off (the only diff is rows in
    # data/system.db), a crashed stream still leaves request/error/final evidence, a
    # broken store never surfaces to the answer path, `obs.prompt_capture` stays
    # independently OFF (content is a separate opt-in with its own blast radius), and
    # retention actually bounds the table by age AND row cap. The write cost was MEASURED:
    # p95 0.078 ms per event against E1's pre-registered 5 ms bar (64x headroom). The
    # magnitude on the real store: 267 rows/active-day observed, which reaches the 200k
    # row cap in ~748 days — the 14-day age prune bounds the table long before that.
    #
    # What flipping this changes on a fresh clone: agent runs become reconstructible —
    # each /ask, /chat and /agui turn mints a trace and appends metadata rows (model,
    # tokens, latency, outcome; never prompt content) that the control room, /usage
    # attribution and per-agent spend read. Answers are byte-identical by construction.
    "obs.session_log": True,
    # Wave H (2026-07-31) — graduated on a DETERMINISTIC data-gated claim, receipt
    # `df89c044999a`, from run `234be1fbb62b` of the suite
    # `aughor/evals/user_agents_receipt.py` (9/9 stable over 3 iterations, 0 errors,
    # 0 flaky, bar 1.0, no baseline — the same carve-out L4, N3 and CR0 used: a claim
    # with no sampling has no noise floor and so needs none).
    #
    # The claim is NOT "answers get better" — a persona is the user's own instruction
    # text and nothing here can promise it helps. It is that the feature is DATA-GATED:
    # every behaviour it adds needs an agent row the user created AND a request naming
    # it. The suite proves that hermetically — with no agent named, the prompt block is
    # empty, retrieval stays unrestricted, resume attaches no persona, and an agent that
    # merely EXISTS changes nothing. `_resolve_ask_agent` returns before it ever reads
    # this flag when there is no `agent_id`, which is why no A/B grid was bought: "does
    # the flag change the prompt?" is decidable by construction, not by sampling.
    #
    # What flipping this changes on a fresh clone: exactly one thing — `/agents/custom`
    # stops 404-ing and returns an empty roster. That is asserted as a DELTA rather than
    # waved away, because it is the honest whole of the effect until somebody creates an
    # agent. The rules that become load-bearing at default-on are pinned alongside: a
    # conflicting connection binding, a disabled agent and an unknown agent are all
    # refused with the authored sentence, and an active agent's retrieval is restricted
    # to its own documents (with none bound it sees none — never a fall-back to all).
    "agents.user_defined": True,
    # Flag strategy batch 1 (2026-07-31) — graduated on a DETERMINISTIC data-gated claim,
    # receipt `452a6fcebba4`, from run `c84f1e75a50c` of the suite
    # `aughor/evals/specialist_packs_receipt.py` (8/8 stable over 3 iterations, 0 errors,
    # 0 flaky, bar 1.0, no baseline — the same carve-out L4, N3, CR0 and Wave H used: a
    # claim with no sampling has no noise floor and so needs none).
    #
    # The claim is NOT "packs make answers better" — a pack is authored domain expertise
    # and nothing here can promise the author was right. It is that steering is DATA-GATED
    # three gates deep: an INSTALLED pack whose manifest says `status: active`, matching
    # the question, with a HUMAN-PINNED deploy binding on the exact connection
    # (`save_binding`'s only product caller is the deploy endpoint behind
    # `govern.guard("pack.bind")`, so a binding row IS a recorded human act). Until all
    # three are earned, `injection_for_question` returns None and the planner context is
    # byte-identical on and off. The repo's one shipped pack is `status: draft`, so a
    # fresh clone holds zero active packs and the flip's whole observable effect is
    # `GET /packs` reporting `enabled: true`.
    #
    # What this default-OFF was silently costing (the defect that ordered the batch):
    # Wave H4's hire-an-analyst flow never consults this flag — hiring from a pack worked
    # on a fresh clone, the pack bound, validation passed — but the steering half returned
    # None, so a hired expert's expertise never injected, with no error anywhere. See
    # docs/FLAG_STRATEGY_2026-07-31.md §2.
    "specialist_packs": True,
    # Flag strategy batch A (2026-07-31) — nine flags graduated together on
    # CONSTRUCTION-DECIDABLE claims: each is deterministic, adds no model call on any
    # default path, and its off-state equivalence (or additive-only delta) is provable
    # hermetically, so no A/B grid was bought for any of them. One suite carries the
    # evidence — `aughor/evals/flag_batch_a_receipt.py`, run `d006bec663a0` (12/12
    # stable over 3 iterations, 0 errors, 0 flaky, bar 1.0, no baseline) — with
    # scenario names prefixed by the flag they back; each flag minted its own
    # graduation decision against that run. See docs/FLAG_STRATEGY_2026-07-31.md §4A.
    #
    # An operator can still force any of them off (env `=0` or a runtime override),
    # and the flip simulation surfaced exactly the expected class of test debt: two
    # tests reaching "off" by never setting the flag (re-pointed to an off flag / an
    # explicit `=0`), and the L4 equivalence suite inheriting the kernel bridge into
    # its legacy oracle (now pinned OFF there — the comparison is between loops, not
    # the bridge).
    "preflight.parallel": True,        # receipt 889789dda475 — same four non-LLM lookups, pooled; byte-identical
    "deep_analysis.evidence_dedup": True,        # receipt 0c96518ab1c4 — lossless collapse; first copy stays full, errors never collapse
    "schema.two_tier_catalog": True,   # receipt 3b3ce99e3f9b — never larger, error-named tables autoloaded with full DDL
    "explore.wandering_detector": True,# receipt 854a1fbb7848 — fail-open brake; repeats reused verbatim
    "monitors.guarded": True,          # receipt 9bf08c312faa — caveat-and-deliver on fired alerts; never rewrites SQL
    "consistency.divergence": True,    # receipt 2574532bcbde — read-only audit routes; nothing on the answer path
    "ops.metered_monitors": True,      # receipt b167bb891764 — same _work closure, now metered; declines cleanly with no loop
    "evals.experiments": True,         # receipt 1bc0e4690955 — inert until a run enters; off was a loud refusal either way
    "starters.library": True,          # receipt 3155c4d9de61 — deterministic starter templates, additive on /suggestions
    # Flag strategy batch B (2026-07-31) — the data-gated and invocation-gated queue,
    # graduated together on STRUCTURAL claims: every behaviour needs data a user created
    # (tags, caps, policies, declared actions, overlay edits, publications, freezes,
    # source-condition automations, grants, a cached brief) or an explicit call to a
    # route that 404s off. One suite carries the evidence —
    # `aughor/evals/flag_batch_b_receipt.py`, run `cbb2e91c7f26` (15/15 stable over 3
    # iterations, 0 errors, 0 flaky, bar 1.0, no baseline) — scenario names prefixed by
    # the flag they back; each flag minted its own graduation decision.
    #
    # Premise checks moved scope twice: `federation.planner` was queued as
    # invocation-gated but ALSO auto-federates fresh /ask turns, so it moved to
    # EXPERIMENT instead of graduating; `lifecycle.publish`'s viewer precondition
    # dissolved on reading the wired stores (they journal ALONGSIDE the live row —
    # reads never route through resolve(), so nothing legacy can be hidden).
    "govern.clearances": True,          # receipt 94d8869fa9ca — untagged ⇒ allowed; a refusal names the tag
    "govern.usage_caps": True,          # receipt 0e5bf079d953 — no caps declared ⇒ every decision allows
    "rbac.row_policy": True,            # receipt 37fa12f2e54a — no principal/policies ⇒ passthrough; fails closed
    "kinetic.actions": True,            # receipt e1514203d474 — only human-DECLARED actions exist to run
    "kinetic.overlay": True,            # receipt af2f7e4dd9c6 — no edits ⇒ the merge is a no-op
    "lifecycle.publish": True,          # receipt 339e77dc3cea — additive journal; the live row stays the record
    "lifecycle.freeze": True,           # receipt 41f41f9d1273 — nothing frozen until a user freezes
    "automations.source_probes": True,  # receipt f526cbf2ac45 — probes only user-created source conditions
    "automations.proposals": True,      # receipt f6c0b3a73690 — executor byte-identical without a minted grant
    "ask.brief_context": True,          # receipt 1277dd3f3f70 — empty until a Briefing rendered for the scope
    "freshness.resolved_rebuild": True, # receipt 442adc34dee9 — never less correct than the TTL it replaces
    "agui.endpoint": True,              # receipt b395745f7771 — the route is the whole surface; calling is consent
    "federation.remote_join": True,     # receipt 41ec864723fb — ditto; unlike .planner it has no /ask hook
    # MIGRATION flip, not a graduation: the REC-U10 byte-equality was proven over this
    # box's real metric stores (canonical_metrics_block AND unified_metric_grounding
    # byte-identical on vs off — receipt e801ff3a4448). The flag's remaining obligation
    # is DELETION: soak default-on, then remove the legacy CanonicalMetric path.
    "semantic.contract_live": True,
    # Flag strategy batch C (2026-07-31) — the two bundles the queue held back, plus the
    # last two migration flips. One suite — `aughor/evals/flag_batch_c_receipt.py`, run
    # `2dbff8c60c10` (11/11 stable over 3 iterations, 0 errors, 0 flaky, bar 1.0, no
    # baseline). The claims are construction-decidable: a graph projection cannot precede
    # its ontology (nothing is written a connection's intelligence does not already
    # contain), the surfaces 404 off and data-refuse empty, the birth rite is
    # DOUBLE-gated (flag AND the workspace's Curator agent) and fires only on an
    # explicit create/re-arm kick, an empty column-config store and an unmined
    # popularity signal are byte-identical no-ops. `plan.program` did NOT flip: its
    # /ask auto-depth hook (`_program_eligible`, mirroring `_federation_eligible`)
    # moved it to EXPERIMENT instead.
    "graph.build": True,               # receipt 1a773d95d0b3 — a projection of the ontology; None without one
    "graph.freshness": True,           # receipt 506ba8c6a163 — change-classified refresh; never raises into a live path
    "graph.surface": True,             # receipt 049ac074f300 — the panel appears; content waits for a built ontology
    "graph.tour": True,                # receipt 68328602e77f — deterministic order; narration only on explicit request
    "graph.export": True,              # receipt adeca7f0fe7d — an empty graph is refused, never shipped
    "birth.job": True,                 # receipt 189fc985e2a0 — kick-scoped AND Curator-governed; no ambient behaviour
    "ontology.autodoc": True,          # receipt 4847eceb9a1f — compiled doc tree; a build artifact, no model
    "ontology.column_config": True,    # receipt 743f540b4d72 — empty store ⇒ byte-identical; human edits always win
    "obs.popularity": True,            # receipt d315c314e558 — nothing mined ⇒ priors untouched
    # MIGRATION flips, not graduations: resolve_live proven equal to the per-node
    # consult over real stores (one context per run — AL-05's whole point); the
    # remaining obligation on both is deleting the legacy path once soaked.
    "semantic.resolve_live": True,     # receipt 49e7af321440
    "capability.pipeline_live": True,  # receipt 0dd2b45930c7 — single route gate; calling is the consent
    # Experiment-queue settle (2026-07-31, batch D) — snapshot_receipts graduated WITHOUT
    # an A/B grid because its exit question was decidable without a model. The cost half:
    # the per-emit probe is one metadata COUNT(*) per finding table, size-independent
    # because DuckDB keeps row counts in metadata — measured median ~0.2ms for a 3-table
    # finding, against E1's pre-registered 5ms bar (run `11de013bb901` of
    # `aughor/evals/snapshot_receipts_receipt.py`, 5/5 stable ×3, receipt `2dee7a36c03f`).
    # The reconcile half ("two pinning mechanisms should be one") was already true by
    # construction: Wave V4's `kernel/freeze.py` imports `data_version` FROM `db/snapshot.py`,
    # so a frozen artifact and a snapshot-pinned finding pin against one function. The
    # on/off delta is a single additive `data_version` token (None when off, fail-open when
    # the probe cannot run), so a fresh clone's dossiers are byte-identical bar that field.
    "snapshot_receipts": True,
}

# Human-facing copy for the Settings UI.
FLAG_META = {
    "agui.endpoint": {
        "label": "AG-UI protocol endpoint (POST /agui/run)",
        "description": "Expose an additive AG-UI-compatible translator at POST /agui/run that re-frames the existing /ask event stream (via the shared build_ask_stream factory) into standard AG-UI protocol events (RunStarted / TextMessage* / ToolCall* / Custom / RunError / RunFinished) using the ag-ui-protocol SDK. Purely additive — the legacy /ask, /chat and /investigate emission is byte-identical and the frontend's default transport is unchanged; this is the backend half of the AG-UI protocol seam, letting any AG-UI client (for example the @ag-ui/client transport) drive Aughor. Forced off ⇒ the route 404s. Default-ON since flag strategy batch B (2026-07-31, receipt `b395745f7771`); force off with AUGHOR_AGUI_ENDPOINT=0 or a runtime override. See docs/AGENTIC_PLATFORM_UNIFICATION_2026-07-13.md.",
    },
    "kinetic.actions": {
        "label": "Declared actions in the ontology",
        "description": "Overlay human-DECLARED actions from the per-connection ontology overrides onto the graph at read time: typed-parameter operations with submission criteria (whose authored failure messages are shown verbatim to humans and the model) and side effects. Read-only substrate — the actions become visible in the ontology and the API, and running one goes through the governed action executor. Additive: off = the graph's declared-action list stays empty (byte-identical), and a malformed declared action is rejected at overlay, never surfaced. Default-ON since flag strategy batch B (2026-07-31, receipt `e1514203d474`); force off with AUGHOR_KINETIC_ACTIONS=0 or a runtime override.",
    },
    "kinetic.overlay": {
        "label": "Human overlay edits on query results",
        "description": "Merge human annotations and corrections ('this outlier is a known launch-day spike', 'order 8821 is a test order') onto query results at READ time, matched by the columns present in the result — never mutating the source data. Edits live in an independent org+connection-scoped store, so they survive schema refreshes and rebuilds, and a machine-sourced edit never overrides a human one on the same target. Forced off ⇒ results carry no annotations (byte-identical); best-effort so an overlay hiccup never takes down a real result. Default-ON since flag strategy batch B (2026-07-31, receipt `af2f7e4dd9c6`); force off with AUGHOR_KINETIC_OVERLAY=0 or a runtime override.",
    },
    "kinetic.agent_actions": {
        "label": "Agent proposes declared actions",
        "description": "Let the agent PROPOSE declared actions from an analysis — the model returns structured proposals which are dry-run validated (typed params + submission criteria) and STAGED for a human to accept and run through the governed executor. Nothing is executed here; nothing above LOW risk ever auto-fires. Off by default ⇒ the agent never proposes actions (byte-identical) and the proposer makes no LLM call.",
    },
    "automations.engine": {
        "label": "Automations — declared condition → governed effect",
        "description": "One engine binding combinable CONDITIONS (a cron schedule, or a metric condition delegated to an existing monitor) to ordered EFFECTS (run a deep analysis, deliver a briefing, fire a notification, or execute a declared action), with muting, expiry, jittered retries, a fallback effect, and a per-tick history that records the ticks which deliberately did NOTHING — the question monitor_alerts cannot answer, since it stores only alerts that fired. A write effect runs through the one governed action executor, inheriting submission criteria, the graduated-approval gate and the audit trail, so nothing above LOW risk auto-fires from an automation either. Off by default ⇒ the heartbeat never starts and every /automations route 404s (byte-identical); the legacy monitor and briefing schedulers are untouched either way.",
    },
    "automations.source_probes": {
        "label": "Automation change detection — source version probes",
        "description": "Let `source_change` and `entity_appears` automation conditions fire on actual data arrival instead of staleness-days: one bounded aggregate per watched table (COUNT(*) plus MAX of its best change-signal column — never a data scan) computes a version fingerprint, compared by inequality so deletes and backfills register too; `entity_appears` restricts the signal to insertions, so an updated_at touch is not a new entity. Baselines commit only on a tick that actually FIRED, which is what makes a change impossible to consume silently when the other condition of an `all`-logic automation is false. A table the probe cannot READ at all (missing, or not a plain identifier) fails OPEN to 'changed' with the reason recorded on the run — noisy and diagnosable, never silently never-firing. A table that merely lacks a change-signal column is a weaker case, and worth knowing before you point an automation at one: it is versioned by COUNT(*) alone, so inserts and deletes still register, but an in-place UPDATE — or an insert and a delete in the same window — leaves the count unchanged and the condition stays QUIET. Gated separately from automations.engine so an operator can run schedule/metric automations without per-minute warehouse probes; off by default ⇒ source conditions error loudly as unwired (byte-identical otherwise). Default-ON since flag strategy batch B (2026-07-31, receipt `f526cbf2ac45`); force off with AUGHOR_AUTOMATIONS_SOURCE_PROBES=0 or a runtime override.",
    },
    "automations.proposals": {
        "label": "Proposal inbox + standing grants",
        "description": "Make an agent's action proposal DURABLE and resolve-once instead of dying with the HTTP response: a proposed declared action is staged, survives a restart, and is accepted or rejected exactly once (a conditional UPDATE on a pending row — the first responder wins; a second accept is a no-op, never a second dispatch; idempotent by (run_id, call_id) so a replayed run cannot duplicate). Accepting IS the human approval act, so it executes bypassing the approval gate but NEVER the submission criteria. Accepting can also mint a TARGET-BOUND standing grant — 'allow this action → this exact target value', eligible only for a single-parameter action, owned by the automation that minted it (revoked with it), cited by id in the audit ledger on every auto-allowed run — so an UNATTENDED automation can run one pre-authorized target without a blanket allow, and still cannot pass a value the criteria reject. Forced off ⇒ no proposal is staged, no grant is consulted (the executor is byte-identical), and every /kinetic-actions/inbox and /grants route 404s. Default-ON since flag strategy batch B (2026-07-31, receipt `f6c0b3a73690`); force off with AUGHOR_AUTOMATIONS_PROPOSALS=0 or a runtime override.",
    },
    "graph.build": {
        "label": "Build the connection knowledge graph",
        "description": "Project the already-built structural ontology plus the narrative stores (glossary, governed metrics, crystallized ambiguity resolutions, discovered findings) into ONE typed, committed, provenance-complete graph per (org, connection, schema) — the read-back artifact every question will pass through in C2. Deterministic projection: no LLM, no SQL; node summaries/tags are a later narrow emission. Every edge carries real provenance or is not constructible (J4) — a `joins_on` edge carries the join guard's MEASURED value-domain overlap (already probed at ontology-build time; value-disjoint coincidences were dropped upstream), and the self-reported model confidences (EvidenceClaim.confidence, pack_deltas.confidence) are banned as edge evidence. The graph is a git-reviewable file under data/context_graph/, version-bumped on rebuild. Forced off = byte-identical: the projection is never invoked and nothing is written (C1 builds the artifact; nothing reads it back until C2). Default-ON since flag strategy batch C (2026-07-31, receipt `1a773d95d0b3`); force off with AUGHOR_GRAPH_BUILD=0 or a runtime override.",
    },
    "graph.readback": {
        "label": "Grep-the-graph-first read-back",
        "description": "Before generating SQL, match the committed connection knowledge graph against the question, pull the 1-hop subgraph, and inject it as a plan-time prior — the mechanic that finally closes the open feedback loop. The subgraph carries the two node types that were write-only before: `finding` (dossiers and exploration findings) and the `resolves` readings, so a question about a table Aughor already analysed inherits what it learned, with the join guard's measured value-domain overlap surfaced as a number (not the ✓ the prompt path otherwise collapses it to). Every injected line is cited by its node/edge id (the block the context receipt shows names exactly what grounded the plan). Ranked hybrid search: a deterministic lexical floor always runs; the Qdrant vector rank fuses in when reachable (RRF) and NEVER degrades to an unranked fallback. Appended at the one function both live answer paths inject (verify.priors.build_corrections_section), gated independently of `closed_loop`. Off by default = byte-identical (empty string, zero prompt cost). Requires a graph built by `graph.build`; no graph ⇒ no-op. Counter: context_graph.*",
    },
    "graph.freshness": {
        "label": "Graph freshness — change-classified refresh + staleness",
        "description": "Keep the connection knowledge graph fresh at cost proportional to the change, and surface how stale it is. Two fingerprints are split: STRUCTURAL (tables + columns + types) and DATA (row counts, from the ontology fingerprint). The classifier reads SKIP (structure and data unchanged, or a comment-only change → no work), a data-only reload (row counts moved, structure identical → the graph is marked DIRTY but NOT rebuilt — a nightly load is not a schema change), PARTIAL (columns changed on known tables → rebuild, naming the tables), or FULL (tables added/removed → rebuild). Typed staleness states fresh|dirty|stale|unknown drive a UI banner and can gate a briefing built on a stale graph. The read-back slice honours a token-proportional budget. This freshness vocabulary is written to be lifted by Wave V (one dialect for graphs, briefings, profiles, caches). Deterministic; no LLM. Forced off ⇒ refresh_context_graph is a no-op (byte-identical). A rebuild still requires `graph.build`. Default-ON since flag strategy batch C (2026-07-31, receipt `506ba8c6a163`); force off with AUGHOR_GRAPH_FRESHNESS=0 or a runtime override.",
    },
    "graph.surface": {
        "label": "Connection knowledge graph surface",
        "description": "Serve and render the connection knowledge graph as a three-level, anti-hairball surface: domain cluster cards with aggregated cross-domain join counts (level 1) → the tables inside a domain, with their verified joins (level 2) → a table detail panel showing columns, the measured value-domain overlap on each join, the glossary terms, and the PAST FINDINGS that touch the table (level 3 — the dossier system makes those $0). Aggregation at every zoom level makes the hairball structurally impossible rather than stylistically discouraged. Exposes GET /graph (the graph JSON: nodes + edges + provenance) and a Knowledge Graph panel. Forced off ⇒ the route 404s and the panel is hidden (byte-identical). Requires a graph built by `graph.build`; the endpoint builds on demand when that flag is on. This is the J6 seam — an entity page is this surface's table-detail view. Default-ON since flag strategy batch C (2026-07-31, receipt `049ac074f300`); force off with AUGHOR_GRAPH_SURFACE=0 or a runtime override.",
    },
    "graph.tour": {
        "label": "Connection tour — a curriculum from graph topology",
        "description": "A guided tour of a connection, ordered by TOPOLOGY not notability, so it teaches rather than lists. The reading order is computed deterministically from the graph: the highest-join-degree table is the entry (the hub every other table reaches), a breadth-first walk introduces each table right after one it joins to, standalone tables follow the connected core, and the governed metrics come last as the capstone (each tied to the table it derives from). Every step after the first names the prior step it builds on. The LLM only narrates the connective tissue over that already-fixed sequence — a single narrow emission, never the ordering. Exposes GET /graph/tour. Forced off ⇒ the route 404s (byte-identical). Turns the ephemeral 7-lens interesting-facts listicle into an ordered curriculum. Default-ON since flag strategy batch C (2026-07-31, receipt `68328602e77f`); force off with AUGHOR_GRAPH_TOUR=0 or a runtime override.",
    },
    "graph.export": {
        "label": "Graph distribution — the committed artifact + skills pack",
        "description": "Export a connection's knowledge graph as a self-contained pack a teammate consumes with NO LLM, no API key and no Aughor running — generation paid once, consumption free. Writes graph.json (the C1 nodes/edges/provenance re-emitted as id-sorted, pretty-printed, greppable lists inside an envelope carrying the source spine, the graph version and C3's typed freshness state), two markdown skills that run the C2 read-back protocol offline (freshness-check → grep labels/summaries/tags → pull the 1-hop subgraph → answer only from that subgraph, citing tables), a README, and an install.sh that SYMLINKS the skills into agent platforms. The staleness state travels with the data because a consumer offline cannot re-derive it, and a freshness it cannot determine ships as `unknown`, never as a cheerful `fresh`. NO coercive hook injection (the forbidden anti-pattern): install.sh only links files — it registers no hook, no daemon, nothing that speaks for the user, and no skill instructs an agent to hide the freshness state or refuse the reader. Exporting a connection with no committed graph is refused rather than shipping an empty pack that answers confidently from nothing. Forced off ⇒ export_pack returns None and nothing is written (byte-identical). Requires a graph built by `graph.build`. Default-ON since flag strategy batch C (2026-07-31, receipt `adeca7f0fe7d`); force off with AUGHOR_GRAPH_EXPORT=0 or a runtime override.",
    },
    "govern.usage_caps": {
        "label": "Org and per-user usage caps",
        "description": "Refuse to START new model work once an org or a user has exceeded a declared allowance, measured on the same rollup the usage page shows so a cap and a dashboard can never disagree about whether a limit was hit. Caps are declared per (scope, subject, metric, window) over calls, tokens or cost, with an action of `alert` (record and proceed) or `block` (refuse the next start). The algebra is deliberately two rules rather than one clever comparator, because getting either backwards is a real outage or a real overspend: MOST-PERMISSIVE WITHIN a scope, since two rows about one subject and metric are two statements about one allowance and the larger is the operator's latest intent — otherwise raising a limit does nothing until somebody deletes the old row; and MOST-RESTRICTIVE ACROSS scopes, since an org cap and a user cap describe the pool and one person's share of it, both hold at once, and the permissive reading would let one user drain the org. A `block` anywhere in a merged group survives the merge, so raising a limit never silently downgrades the gate to `alert`. Enforcement is PRE-FLIGHT ONLY and there is no abort path: work already running is never killed, because clawing back an in-flight deep analysis destroys work the user already paid for and leaves a partial artifact whose provenance claims it completed. A breach is a typed `budget_exceeded` refusal naming the metric, the limit, the observed value and the window — withhold the work, never the reason. Forced off => every decision allows and the check costs one boolean. Default-ON since flag strategy batch B (2026-07-31, receipt `0e5bf079d953`); force off with AUGHOR_GOVERN_USAGE_CAPS=0 or a runtime override.",
    },
    "govern.clearances": {
        "label": "Clearance enforcement on governed tags",
        "description": "Let governed tags on catalogs, schemas, tables and artifacts gate who may read them. A tag is a namespaced key-value fact recorded with WHO set it and when — `pii=true`, `tier=restricted` — and a small, explicit set of keys is access-controlling while every other tag stays purely descriptive, so adding a `domain=finance` label never silently becomes a lock. A principal holds clearances; a securable whose tags demand one the principal lacks is withheld. This is a THIRD authorization axis composing with AND alongside the licensing capability (what the org's PLAN unlocks) and the RBAC permission (what this USER may do): a role says analysts may run analyses, a clearance says not over the salary table, and neither expresses the other. An untagged securable is always allowed — governance is opt-in per object, because defaulting to deny would make enabling this a platform-wide outage rather than a policy. A refusal NAMES the tag that blocked it and the clearance that would unblock it, and is never an empty result: a silently trimmed answer teaches its reader the data does not exist, which is the pinned anti-pattern (see docs/GENIE_DOCS_TEARDOWN_2026-07-26.md). Nothing infers a tag, and a write with no author is refused outright — J4's provenance discipline reaching past the context graph. Forced off ⇒ every decision is ALLOW with no requirements, so the check can be wired in unconditionally and the off state is byte-identical to not calling it. Default-ON since flag strategy batch B (2026-07-31, receipt `94d8869fa9ca`); force off with AUGHOR_GOVERN_CLEARANCES=0 or a runtime override.",
    },
    "graph.consolidate": {
        "label": "Consolidate the finding corpus before the cap",
        "description": "Spend the graph's 100-finding budget on distinct LIVE knowledge instead of 100 newest receipts. The projection appends one finding per answered question and evicts newest-first, so on the reference connection the committed artifact carried 77 distinct subjects — 59 of them still reachable — out of 274 that exist across 794 receipts. With this on, repeated subjects (same question over the same tables) fold together BEFORE the cap applies, and findings grounded in tables that are no longer in the ontology sort last so the cap evicts what can no longer be verified before it evicts live knowledge. Measured on the reference connection: 100 live distinct subjects instead of 59, same node budget. The platform never picks a winner: a repeat whose SQL is unchanged is simply superseded by the newest reading (the data moved), but a repeat that reached a DIFFERENT conclusion by a DIFFERENT query is marked `contested` and carries the alternative conclusions inline — settling it is a human's decision through the answer-consistency review, not a matter of which run was most recent. Nothing is deleted: every input finding leaves as a survivor, a superseded id, or a contested variant, and the counts are asserted to balance. Deterministic, read-only, no LLM: the added cost is one bounded read of a local store, and nothing runs on the answer path. Default-ON since Wave N3, graduated on run `3dec60f4a580` of the deterministic suite `aughor/evals/consolidation.py` (8/8, bar 1.0). Turning it OFF is byte-identical to the pre-N3 projection — the finding payload carries exactly {generated_at, sql, tables} and the loader is called exactly as before. Flipping this rewrites nothing on its own: a committed graph changes only when something rebuilds it.",
    },
    "freshness.resolved_rebuild": {
        "label": "Staleness-resolved rebuild — inputs + logic, not a timer",
        "description": "Rebuild a cached artifact only when its SOURCE DATA or its PRODUCER LOGIC actually changed, instead of when a wall-clock TTL lapsed. A timer is wrong in both directions at once: the briefing's 2-hour TTL rebuilds a briefing whose inputs never moved (pure cost — and each rebuild is an LLM call, not just CPU) AND serves a briefing for up to two hours after its source table changed (a wrong number, the expensive failure). The input signal is Wave A3's source probe — one bounded aggregate per table (COUNT(*), MAX(signal)), never a scan — making this its second consumer and turning it from an automations feature into a platform primitive; the logic signal is Wave V1's LOGIC_VERSIONS inventory. Three refusals keep it from becoming a worse timer: a table that cannot be versioned FAILS OPEN to the caller's existing TTL decision and says so in the reason (counted, never silently read as 'unchanged' — A3's rule that noisy beats silent); probing is capped and a bitten cap names how many tables were skipped rather than implying full coverage; and state is recorded only AFTER a successful rebuild, because recording on failure would consume a change and make a genuinely stale artifact read fresh. Every decision carries a `resolved` bit so a caller can never claim 'nothing changed' on a probe that did not answer, plus the as-of source view the output was computed on (what Wave V4's freeze will pin against). Forced off ⇒ resolve() returns the caller's own TTL decision unchanged (byte-identical). Default-ON since flag strategy batch B (2026-07-31, receipt `442adc34dee9`); force off with AUGHOR_FRESHNESS_RESOLVED_REBUILD=0 or a runtime override.",
    },
    "lifecycle.publish": {
        "label": "Artifact lifecycle — save≠publish, versions, changelog, revert",
        "description": "Give user-authored artifacts a version and a publication state, so an editor's half-finished edit is no longer what every viewer sees. Saved queries, canvases, dashboard cards and eval cases had NO version at all — update was destructive and 'what did this look like last week' had no answer. Built ON the kernel Ledger rather than beside it: artifact_write already implements supersede-not-delete and artifact_by_id already resolves an exact version (its docstring calls that 'so a receipt link is immutable', which is precisely a pin), so this layer stores nothing of its own. resolve(audience='viewer') returns the newest PUBLISHED version and never a draft; audience='editor' returns the working copy — that one function is save≠publish. Revert restores an earlier version's content as a NEW version, never by rewinding the counter, because a rewind would erase the evidence that the reverted state ever shipped. The changelog reports MOVES as moves: reordering a dashboard's cards is the most common edit there is, and a differ without move detection reports every element from the move point onward as deleted-and-re-added — pages of noise for a four-word change. Convergence of the four pre-existing draft state machines is by PROJECTION (a documented table mapping governance/playbook/packs statuses onto one publication axis), not by forced rewrite: governance's draft→proposed→approved is a review workflow, and pushing a saved query through 'proposed' would invent ceremony nobody wants, while playbook's auto-promotion is a policy that would have to be rewritten to fit. An unknown status projects to `draft`, the conservative direction — a viewer sees nothing rather than something whose state cannot be read. Forced off ⇒ nothing is written and every wired store behaves exactly as before. Default-ON since flag strategy batch B (2026-07-31, receipt `339e77dc3cea`); force off with AUGHOR_LIFECYCLE_PUBLISH=0 or a runtime override.",
    },
    "lifecycle.freeze": {
        "label": "Freeze — live by default, snapshot by choice",
        "description": "Let a user pin an artifact to an exact version AND the data version behind it, with an as-of stamp, and return it to following live on demand. Composes three pins that already existed unconnected: ledger.artifact_by_id (an immutable receipt link), playbook.get_version (frozen past content), and db/snapshot.data_version + execute_as_of (a replayable data version). TWO MODES, named rather than assumed, because a freeze promises 'you will see exactly what I saw' and that is not always deliverable: on version-aware storage (DuckLake) the pinned snapshot id is replayable via AT (VERSION => n) — mode `reproducible`; on a plain DuckDB file the portable fingerprint can only detect that data CHANGED, never reconstruct it — mode `detect_only`. Conflating them would be exactly the safety-by-coincidence this codebase has paid for before, so a detect-only pin never claims reproducibility, and when nothing can be pinned at all the freeze is REFUSED up front (with the reason) instead of accepted and quietly not honoured — a lock icon that guarantees nothing is worse than no lock. Reading a frozen artifact whose pin can no longer be honoured raises FrozenDataGoneError carrying the as-of stamp and the reason; it NEVER falls back to live data, because a frozen label over live numbers is the one outcome worse than an error. Forced off ⇒ nothing can be frozen and every read is live (byte-identical). Default-ON since flag strategy batch B (2026-07-31, receipt `41f41f9d1273`); force off with AUGHOR_LIFECYCLE_FREEZE=0 or a runtime override.",
    },
    "automations.adopt_legacy": {
        "label": "Adopt monitors and briefings onto the automation engine",
        "description": "Run every enabled Monitor and Briefing subscription THROUGH the one automation engine instead of their own near-identical schedulers: each is read on the fly as a virtual automation (a cron `schedule` condition + a faithful effect — a `monitor` effect that replays run_monitor with its anti-flap debounce intact and appends the same alert, or the existing `brief` effect that calls deliver_subscription), so there is one loop, one run history, and one place a tick's reason is recorded. Only takes effect when automations.engine is ALSO on (the heartbeat has to be running to drive them), and while active the legacy monitor and briefing schedulers stand down at FIRE time as well as at start — so a runtime flag flip can never double-fire an alert or, worse, double-DELIVER a briefing (an outward send). Off by default ⇒ the legacy schedulers run exactly as before (byte-identical) and the heartbeat ignores monitors and briefings. No data migration either way; flipping it off restores the legacy path.",
    },
    "ask.stream_text": {
        "label": "Token-stream the answer narrative",
        "description": "Stream the post-answer narrative as it is written (`insight_delta` SSE events carrying the partial text) instead of one late pop-in, then emit the existing full `insight` event as the authoritative terminal value (self-healing: a dropped delta costs nothing). Dual-emit and additive — old clients ignore the unknown delta events; off = byte-identical to the pre-streaming stream. Falls back to the blocking call on any streaming error. See docs/AGENTIC_PLATFORM_UNIFICATION_2026-07-13.md.",
    },
    "ask.overview": {
        "label": "Interesting-facts overview tour (the default first-look)",
        "description": "Answer the widest-possible question — \"show me interesting facts about this schema\" / \"tell me about this data\" — as a first-look tour rather than a deep analysis of one metric: a DETERMINISTIC profile of the whole dataset ranked by notability and capped for diversity. Seven lenses (scale · concentration · outlier · distribution · composition · coverage · relationship) each run a cheap grounded probe (mostly one SUMMARIZE per table, no LLM), then a diverse top-N is selected so the tour spans many tables and fact types. Fires ONLY on an overview-phrased question with no metric/entity/time window named; graduated to Auto (on by default via `capabilities.auto`) because it is bounded and deterministic. An explicit env `=0` disables it.",
    },
    "ask.context_receipt": {
        "label": "Grounding-context receipt (show what the model was grounded on)",
        "description": "Expose the exact grounding block the SQL writer sees — the schema slice chosen, glossary entries, governed-metric bindings, ambiguity-ledger priors applied, value-index literal bindings, dialect rules, and active pack bindings — as JSON + rendered markdown via GET /ask/context and a \"Show grounding\" affordance on the answer. The input-side twin of the Trust Receipt (which covers the output). Assembly is centralised in a pure build_grounding_context() that the answer path and the endpoint share, so the receipt is exactly what the run used (no drift). Off by default = byte-identical (endpoint returns 404, no receipt section). Wave 1 · Rec 5 of the combined platform study.",
    },
    "obs.task_table": {
        "label": "task_history — spans as a queryable table",
        "description": "Sink the kernel ledger's node/tool span events into one append-only task_history table (trace_id, span_id, parent_span_id, task, input, captured_output, timing, error, labels) — the queryable spine of \"what the agent actually did.\" It is a SINK over the spans telemetry already emits, not new instrumentation: MLflow/Langfuse stay the rich-trace backends; this makes the same exhaust answerable with plain SQL, so evals recover generated SQL by querying the table (no log parsing) and a deep analysis can examine the platform's own behaviour via the aughor_ops schema. Off by default = byte-identical (no rows written). Wave 2 · Rec 4 of the combined platform study.",
    },
    "obs.session_log": {
        "label": "session_events — the agent-session log",
        "description": "Record one append-only session_events row per agent-session event (user_request · tool_call · tool_call_result · llm_call · final_response · execution_error) with a stable trace id, a monotonic sequence, explicit success/duration/error-class, and the ambient session/user/agent identity. Fills the gap task_history cannot: it mints the trace at the /ask door, so the QUICK answer path — which today creates no trace id at all and whose SQL bypasses the span-emitting executor — becomes reconstructible; it writes tool_call on ENTRY, so a call that hangs or is cancelled still leaves evidence, where a span row only ever appears after the body returns; and it records each LLM call (model, role, tokens, latency, retries, whether the fallback swapped the model mid-run), which today is aggregated into counters and discarded. Queryable as SQL via the aughor_ops schema, and the substrate a later evals harness turns real sessions into test cases from. Retention is enforced on write (AUGHOR_SESSION_LOG_KEEP_DAYS / _MAX_ROWS). Default-ON since Wave CR0, graduated on receipt `45dcc137f55b` (run `43bf2bc7182d` of aughor/evals/session_log_receipt.py, 7/7): answer frames are byte-identical on vs off, a store failure never reaches the answer path, and the per-event write measured p95 0.078 ms against E1's 5 ms bar. Prompt CONTENT stays a separate opt-in (obs.prompt_capture, still off). Force off with AUGHOR_OBS_SESSION_LOG=0 or a runtime override. Wave E1.",
    },
    "obs.prompt_capture": {
        "label": "Capture prompts and completions on llm_call rows",
        "description": "Store the system prompt, user prompt and model response alongside each llm_call in the session log. SEPARATE from obs.session_log and off by default because the blast radius is entirely different: the rest of the log is metadata (model, tokens, latency, outcome), whereas this writes the actual content of every model call — which for this product means schema, sampled values, glossary text and the user's own question, i.e. potentially the most sensitive material in the deployment. It has no effect unless obs.session_log is also on (nothing writes rows otherwise). Turn it on deliberately, for a bounded window, when you need to reproduce or grade a run — a captured prompt is what lets a recorded session become an eval case or a bug report, rather than a claim about one. Values are capped (AUGHOR_OBS_PROMPT_MAX_CHARS, default 2000) and truncation is marked explicitly, because a silently-shortened prompt reproduces a different call than the one that ran. Consider a retention window (AUGHOR_SESSION_LOG_KEEP_DAYS) and access controls on data/system.db before enabling in production.",
    },
    "obs.popularity": {
        "label": "Query popularity as a shared notability signal",
        "description": "Mine real query history (the SQL-examples store + task_history span inputs) into a persisted per-table and per-column usage counter, and let one signal feed four consumers: column-config default protection (a queried column is never default-hidden), doc-tree table facts + ranking, the overview's learned-prior boost, and a most-queried-tables block in /suggestions. Mining runs inside the R12 birth job; deterministic (sqlglot, no model). Forced off = byte-identical. Default-ON since flag strategy batch C (2026-07-31, receipt `d315c314e558`); force off with AUGHOR_OBS_POPULARITY=0 or a runtime override. See docs/DATABRICKS_HAR_CANVAS_BIRTH_STUDY_2026-07-16.md (R14).",
    },
    "explorer.manifest_driven": {
        "label": "Manifest-driven deterministic exploration",
        "description": "Cover the Phase-8 L2 baseline cells (measure × dimension) with SYNTHESISED SQL from a deterministic coverage manifest — no per-cell generation LLM call — with the existing explorer guards enforcing correctness; the LLM curiosity loop still handles cells/domains the manifest doesn't cover. Deterministic-first: fewer LLM calls, reproducible baseline coverage tracked across re-runs. Fails closed to the LLM loop if the manifest can't build. Off by default = byte-identical (LLM-only exploration). (Was consulted but unregistered — study E3 housekeeping.)",
    },
    "learning.receipt": {
        "label": "Per-run Learning Receipt",
        "description": "Attach a Learning Receipt to each answer — a per-run summary of what the closed loop DID: resolved readings reused (and how many were human corrections), resolutions crystallized this run, and trusted plan-as-programs replayed. Emitted as an SSE `learning` event and stamped on the Trust Receipt so the accumulation the loop already captures is finally visible. Off by default = byte-identical (no event, no receipt section). Wave 1 · E4 of the combined platform study.",
    },
    "capabilities.auto": {
        "label": "Capabilities Auto-mode (self-gating guards decide per run)",
        "description": "Master switch for Auto-mode: with it on, each SELF-GATING capability (a deterministic guard that already only fires on a runtime trigger — premise-check, clarify gate, high-stakes adversarial verify, join key-reconciliation, capability-contract repair, guarded extract) is ENABLED unless the operator explicitly turned it off, and its own trigger decides per run — so you turn on the smart guards with one switch instead of flipping each. An explicit per-capability On/Off always wins; cost-dangerous flags (federation, champion-validate) are NOT auto-eligible. Off by default = byte-identical. Wave 1 · E3 of the combined platform study.",
    },
    "trust.e1_live": {
        "label": "E1 function-semantics checks on live answers",
        "description": "Run the E1 footgun battery (a timestamp bounded by a date-only literal drops that day's later rows; ORDER BY/MIN/MAX over numeric-looking text sorts lexicographically; text↔numeric comparisons) on the FINAL SQL of live answers — the quick/chat headline and every deep-analysis phase query — as labelled WARN caveats. Pure AST, deterministic, never rewrites the query (the E1 contract). Previously these checks ran only on /query/validate, never on an answer a user actually saw. Off by default = byte-identical. WP-1e of the 2026-07-12 platform review.",
    },
    "ops.metered_monitors": {
        "label": "Meter background monitors and briefings through the kernel",
        "description": "Route each scheduled monitor tick and briefing delivery through the job kernel (as the Watcher / Briefer agents) instead of calling the runner directly on the scheduler thread. The warehouse SQL a monitor or briefing runs then joins the same metering as an answer — visible in the Agents workspace metering, counted toward the agent's per-run token/time budget, and heartbeat-supervised (a run over budget is cancelled). Preserves the tenant re-bind the schedulers already do. Default-ON since flag strategy batch A (2026-07-31, receipt `b167bb891764` — the SAME work closure runs on both paths, and with no kernel loop captured the bridge declines cleanly so the legacy in-thread path runs unchanged); force off with AUGHOR_METERED_MONITORS=0 or a runtime override for the direct in-thread path. Unblocks the `explorer.continuous` default decision — background cost is now metered. WP-7 of the 2026-07-12 platform review.",
    },
    "monitors.guarded": {
        "label": "Guarded monitor evaluations",
        "description": "Run the deterministic correctness probes (fan-out/grain, id-arithmetic) on a monitor's SQL at evaluation time and attach any finding as a caveat on the alert — a wrong-grain SUM in a monitor otherwise silently mis-values the metric and then alerts on it. Never rewrites the monitor's SQL; caveat-and-deliver. Default-ON since flag strategy batch A (2026-07-31, receipt `9bf08c312faa` — severity and message byte-identical on vs off, the caveat purely additive, a probe crash leaves the alert untouched); force off with AUGHOR_MONITORS_GUARDED=0 or a runtime override. WP-1b of the 2026-07-12 platform review.",
    },
    "explorer.continuous": {
        "label": "Continuous exploration (re-explore on schema change / staleness)",
        "description": "Keep the Explorer learning after the first pass: a periodic tick re-arms exploration when the connection's live schema fingerprint no longer matches the one the last run recorded (a table/column was added or removed), or when the last completed run is older than the staleness window (AUGHOR_EXPLORER_REFRESH_DAYS, default 7). Re-runs are incremental — the coverage frontier is recomputed from persisted findings, so only genuinely new cuts spend budget — and still flow through the Explorer-governance + AUTO_EXPLORATION gates and the per-run exploration budget. Off by default = byte-identical (exploration runs once on connect + on demand). WP-6 of the 2026-07-12 platform review; makes the \"never stops learning\" claim true rather than aspirational.",
    },
    "capabilities.receipt": {
        "label": "Activation Receipt (which guards fired, and why)",
        "description": "Attach an Activation Receipt to each answer — the self-gating guards that actually fired this run and the deterministic trigger that fired them (\"activated premise-check because the question asserts why a metric is high/low\"). Emitted as an SSE `activations` event and stamped on the Trust Receipt, so Auto-mode's per-run decisions are visible instead of implicit. Off by default = byte-identical (no event, no receipt section). Wave 1 · E3 of the combined platform study.",
    },
    "snapshot_receipts": {
        "label": "Snapshot-pinned receipts",
        "description": "Pin every finding to the exact data version it ran against (reproducible-as-of), so a re-validate can tell a MOVED dataset apart from a mis-derived finding — the same data_version Wave V4's freeze pins an artifact to. The version probe is one metadata COUNT(*) per finding table (size-independent on DuckDB; the native snapshot id on DuckLake), added at dossier emit off the answer path. Default-ON since the 2026-07-31 flag strategy experiment-queue settle (batch D, receipt `2dee7a36c03f`): measured median ~0.2ms for a 3-table finding against E1's 5ms bar, additive (off ⇒ the dossier's data_version is None, byte-identical otherwise), and fail-open (a probe that cannot run yields None, never blocking the emit). Force off with AUGHOR_SNAPSHOT_RECEIPTS=0 or a runtime override.",
    },
    "explorer.synthesis_incremental": {
        "label": "Incremental synthesis",
        "description": "Fire cross-finding synthesis the moment a new finding creates a combinable pair, not only at end-of-run. More 'alive', more compute. Phase 9 always runs at end-of-run regardless.",
    },
    "specialist_packs": {
        "label": "Packs — authored domain bundles that steer the planner",
        "description": "Load user-built packs (packs/) and let them steer the engine at intake — the pack's stance, grounded metric recipes and diagnostic questions prepended to the explore planner context. Steering is data-gated three gates deep: it requires an installed pack whose manifest says status: active, matching the question, AND a human-pinned deploy binding on the exact connection (propose → confirm → pin in the deploy UI; auto-proposals never steer). A custom agent's pack bindings restrict selection to its packs but never bypass the deploy gate. Default-ON since the 2026-07-31 flag-strategy batch 1, graduated on receipt `452a6fcebba4` (run `c84f1e75a50c` of aughor/evals/specialist_packs_receipt.py, 8/8 stable ×3): with no active pack or no pinned deployment the planner context is byte-identical on vs off, and the fresh-clone delta is exactly GET /packs reporting enabled: true (the shipped sample pack is status: draft). Force off with AUGHOR_SPECIALIST_PACKS=0 or a runtime override. See docs/DOMAIN_EXPERTISE_PACKS.md.",
    },
    "explore.parallel_subq": {
        "label": "Parallel explore sub-questions",
        "description": "Run independent explore sub-questions concurrently in dependency-respecting waves (map-reduce over the operator.add state) instead of one-at-a-time. Cuts wall-clock on multi-cut deep analyses; multiplies concurrent LLM calls (bounded by the fan-out width cap + the P6 token budget). Off by default — see docs/PARALLEL_MULTIAGENT_GROUNDWORK.md.",
    },
    "explore.route_wide": {
        "label": "Route wide questions to the explore wave",
        "description": "Let the /ask door send a genuinely BROAD 'landscape' question — characterize / profile / map how X varies across the business — to the multi-cut explore subgraph instead of a single deep analysis. A deterministic detector decides (no model in the routing path); it yields to causal/driver 'why' questions, which stay deep analyses. Unlocks the already-built explore wave from /ask. Off by default.",
    },
    "report.argument_style": {
        "label": "Argument-style report composition",
        "description": "Compose exported deep-analysis reports the way a human analyst argues: one exhibit per claim (chart OR a small table, never both), no degenerate exhibits (a 1-bar chart or single-point trend becomes a sentence), key numbers bold inline in the prose instead of stat-tile rows, the Question-Intake machinery out of the body (it stays in the Trust Receipt), and the R15 opportunity number promoted to its own Financial impact section. Deterministic re-composition of the SAME report data — no model. Off by default = byte-identical exports — see docs/REPORT_STYLE_STUDY_2026-07-16.md (R16 P1).",
    },
    "deep_analysis.evidence_dedup": {
        "label": "Collapse duplicate query results in the synthesis block",
        "description": "When two steps ran the identical query, the synthesis prompt renders the identical table twice. This replaces the second with a one-line pointer to the first. LOSSLESS by construction — the table is still in the block, once — so nothing the narrator could cite disappears. Sees the whole block, so a repeat spread across two hypothesis sections is still caught. No-op below a 24k-char evidence block. Default-ON since flag strategy batch A (2026-07-31, receipt `0c96518ab1c4` — the first copy always renders full and byte-identical; an errored result never collapses); force off with AUGHOR_DEEP_ANALYSIS_EVIDENCE_DEDUP=0 or a runtime override. Counter: deep_analysis.evidence.duplicates.",
    },
    "evals.experiments": {
        "label": "Grid experiments: run-scoped model / temperature / flag overrides",
        "description": "Lets an eval suite run the same cases under several configurations in ONE process, so a variant can be compared against its baseline instead of against a number recorded on a different day under an unrecorded config. Flags resolve through the ledger and the environment, both process-global, so before this two cells of a grid could not disagree; a contextvar consulted ahead of both can, and it reaches worker threads through ContextThreadPoolExecutor like the model pin and the metering hook. The plane is inert unless a run enters it (the contextvars default to unset, so ordinary traffic is byte-identical), and it refuses to measure at all while AUGHOR_FALLBACK_DISABLED is off, because the failover chain would silently finish a run on a different model and the report would attribute the number to the binding that started it. Every cell records the configuration read back through the product's own resolvers rather than the one requested — an override that silently no-ops is indistinguishable from a variant that did not help, and the second reading flatters the harness. First customers: the experiment-queue flags whose exit questions need an A/B. Default-ON since flag strategy batch A (2026-07-31, receipt `1bc0e4690955` — the plane is inert until a run enters it: ambient traffic carries no run-scoped overrides, and with the flag off a grid REFUSES loudly rather than silently running one configuration); force off with AUGHOR_EVALS_EXPERIMENTS=0 or a runtime override.",
    },
    "schema.two_tier_catalog": {
        "label": "Two-tier schema catalog for SQL repair prompts",
        "description": "The SQL repair prompt sends the ENTIRE schema context on every failure, on both the deep-analysis and explore paths — on a wide warehouse the largest prompt the app builds, and almost all of it irrelevant to the one query that broke. Instead: a one-line manifest of every table (so the model still knows what exists and can decide it must join somewhere new) plus full DDL only for the tables the failing SQL references AND any table the ERROR MESSAGE names. That last set is the error-path autoload, and it changes outcomes rather than just cost: a binder error ('no such column x on table y') is unfixable if y's columns are not in front of the model, and schema-linking structurally cannot supply them — it selects from the QUESTION, before the query has failed. Safe direction only: below 12k chars the full schema is returned untouched (byte-identical), and any ambiguity — unparseable schema, empty focus set, narrowing that saves nothing — falls back to sending everything. Default-ON since flag strategy batch A (2026-07-31, receipt `3b3ce99e3f9b`); force off with AUGHOR_SCHEMA_TWO_TIER_CATALOG=0 or a runtime override to always send the full schema. Counters: schema.two_tier.focused / .chars_saved.",
    },
    "explore.wandering_detector": {
        "label": "Stall detector for exploration waves",
        "description": "A deterministic brake on an exploration that has stopped learning. Three signals nothing else catches: a REPEAT (the planner re-emits SQL this run already executed — vetoed before dispatch, the earlier result reused verbatim and marked, saving the scan AND the interpret call), NO PROGRESS (different queries, identical results, three steps running — a repeat counter cannot see this), and CHURN (many distinct queries collapsing onto a couple of distinct results — a streak counter cannot see this either). On repeated vetoes or either progress signal the wave ends GRACEFULLY: it routes to the same synthesis it would have reached at the iteration cap, having spent a planner and an interpret call per redundant step to get there. Reads only the run's own query_history, so no new state and no lock; fail-open everywhere — any error and the query runs exactly as it would have, because a detector that can suppress real evidence is worse than the redundancy it saves. Default-ON since flag strategy batch A (2026-07-31, receipt `854a1fbb7848` — a repeat is reused VERBATIM, marked with a caveat, never silently absorbed); force off with AUGHOR_EXPLORE_WANDERING_DETECTOR=0 or a runtime override. Counters: explore.wandering.*",
    },
    "llm.structured_salvage": {
        "label": "Deterministic salvage of structured LLM responses",
        "description": "When a structured call fails to parse or validate, recover it deterministically before spending another request: strip markdown fences and surrounding prose, repair trailing commas, Python literals and smart quotes, fold enum case, drop schema-forbidden extra keys — then re-validate. Also classifies the failure first, so a response TRUNCATED at the output ceiling fails immediately instead of failing over to a second provider that will hit the same ceiling. Zero additional requests, no model in the loop, and no guessing: enum matching folds case and separators only, so a genuine typo still fails loudly. On by default — off means a stray markdown fence keeps costing a whole extra provider request. Counters at GET /dev/stats (llm.salvage.*, llm.failure.*).",
    },
    "llm.bounded_repair": {
        "label": "One bounded repair request for a salvageable structured response",
        "description": "After deterministic salvage fails, ask the model ONCE to fix its own output — carrying the specific validation error (the field and why) and the original text, at temperature 0 and capped in output tokens. At most one, on the same binding, and never for a truncated, empty or refused response (a second request cannot fix any of those). This REPLACES a larger cost rather than adding one: instructor's default of 3 attempts per structured call was never overridden, so a malformed response already re-sent the whole prompt three times; Wave R1 cuts that to one attempt and spends at most one small repair after it. Turn off for a hard ceiling of one request per structured call, at the cost of losing the answers only a repair recovers. Counters: llm.repair.calls / llm.repair.ok.",
    },
    "intake.loss_signals": {
        "label": "Loss-signal directive at question intake",
        "description": "When the question carries loss intent ('where are we losing money', leakage, waste) a deterministic scan names the loss signals THIS schema carries — contra-revenue columns (refunds, chargebacks, discounts) and capacity/utilization columns — and directs the intake to frame the metric around them: leakage as a rate of gross per segment, sold-vs-capacity with a benchmark gap, revenue ranking as context only. Also forbids the un-computable verdict: without cost data the report may never conclude 'profitable' or 'no losses'. Found by the 2026-07-16 A/B: a revenue ranking answered 'broadly healthy' over 2.4M CHF of refund leakage and a 1.2M CHF utilization gap. No model in the detector; off by default = byte-identical intake prompt.",
    },
    "chart.exhibit_grammar": {
        "label": "Semantic chart grammar (exhibit spec)",
        "description": "Charts encode meaning the way a published analyst exhibit does (the 2026-07-16 chart-grammar study): the model is no longer OFFERED the combo chart (one measure per exhibit; the renderer's deterministic dual-axis gate is the only door to one), a rate/percent ranking carries a severity color ramp (value → hue, red family for cost-like metrics), cross-section findings gain deterministic reference lines (segment-weighted average; the R15 best-peer benchmark), the peer-benchmark lens draws its peer median, and an entity scatter labels its points by ID. All computed from rows already fetched — no model, no extra query; carried as an additive `exhibit` payload on findings/answers. Off by default = byte-identical charts and prompts.",
    },
    "lens.decision_grade": {
        "label": "Decision-grade output lenses",
        "description": "Two deterministic output moves borrowed from the strongest habits of published analyst reports: (1) the opportunity-cost lens — for a weak segment in a dimensional scan, benchmark it against its best material peer and quantify gap × volume as one hedged key number ('closing the gap ≈ N', a ceiling not a forecast); (2) the named-outlier-entity lens — the overview tour surfaces the single entity BY ID that towers over its top-10 peers, with a mini-profile and honest 'potential causes' (data artifact vs real whale) plus the drill SQL to verify. No model in the loop; both compute from rows already fetched (plus one bounded probe per table for the entity lens). Off by default = byte-identical — see docs/DATABRICKS_HAR_CANVAS_BIRTH_STUDY_2026-07-16.md (R15).",
    },
    "starters.library": {
        "label": "Named starter questions",
        "description": "Surface a library of named, deterministic starters (interesting outlier entities, where are we losing money, data quality scan) plus per-space curated questions from the ontology doc tree as one-click starters on /suggestions. Each starter declares its route up front (deep analysis or the wide explore wave) and carries a purpose tag on the route receipt — templates, no model in the loop. Default-ON since flag strategy batch A (2026-07-31, receipt `3155c4d9de61` — deterministic payload, purely additive `starters` key on /suggestions); force off with AUGHOR_STARTERS_LIBRARY=0 or a runtime override for LLM-generated-only suggestions — see docs/DATABRICKS_HAR_CANVAS_BIRTH_STUDY_2026-07-16.md (R13).",
    },
    "ontology.autodoc": {
        "label": "Compile ontology docs as a build artifact",
        "description": "After the ontology is built, project it into a persisted, Merkle-checksummed doc tree (column→table→schema→connection) with per-table analyst questions — understanding compiled once and re-read cheaply, rebuilt incrementally as the schema moves. Deterministic (no model); also available on demand via the `aughor ontology-docs` CLI. When an embedder + Qdrant are available the compiled table docs are ALSO embedded into the knowledge store with FQN provenance (R8a), so retrieval can ground on understanding, not just uploads — best-effort, degrades to the YAML artifact alone. Forced off ⇒ the doc tree is never compiled. Default-ON since flag strategy batch C (2026-07-31, receipt `4847eceb9a1f`); force off with AUGHOR_ONTOLOGY_AUTODOC=0 or a runtime override. See docs/DATABRICKS_HAR_SQLX_AUTODOC_STUDY_2026-07-15.md (R8).",
    },
    "birth.job": {
        "label": "Connection/canvas birth as one observable job",
        "description": "Run the 'understand this data' rite as ONE supervised kernel job at connection creation, upload re-arm, and canvas creation: eager intelligence first (profiles → ontology → doc tree → column config), then the exploration handoff — each step a birth.step event on the event spine, governed by the Curator agent's charter. Forced off: exploration alone kicks off and intelligence stays lazy (built on the first question), exactly as before. Default-ON since flag strategy batch C (2026-07-31, receipt `189fc985e2a0`); force off with AUGHOR_BIRTH_JOB=0 or a runtime override. See docs/DATABRICKS_HAR_CANVAS_BIRTH_STUDY_2026-07-16.md (R12).",
    },
    "ontology.column_config": {
        "label": "Per-column visibility / sampling / indexing config",
        "description": "A persisted, human-editable per-column config with three flags: visible (render the column into agent prompt schemas at all — hiding prunes noise columns from the context), sample (enumerate the column's values in the schema context), and index (build the offline value index over it). Deterministic defaults come from the profiler — entity dimensions index+sample, dead all-null columns and free-text blobs hide; a human edit always wins and survives schema rebuilds. No model in the loop. Forced off ⇒ the config is never consulted for prompts, sampling or indexing. Default-ON since flag strategy batch C (2026-07-31, receipt `743f540b4d72`); force off with AUGHOR_ONTOLOGY_COLUMN_CONFIG=0 or a runtime override. See docs/DATABRICKS_HAR_CANVAS_BIRTH_STUDY_2026-07-16.md (R11).",
    },
    "deep_analysis.parallel_lenses": {
        "label": "Parallel deep-analysis lenses",
        "description": "For a cross-sectional deep analysis ('why is X high/low'), run independent lenses (segment/where ∥ mechanism/why) concurrently instead of one bundled scan — a deeper, multi-angle answer at ~flat wall-clock. Multiplies concurrent LLM calls (bounded by the P6 token budget). Off by default — see docs/PARALLEL_MULTIAGENT_GROUNDWORK.md.",
    },
    "deep_analysis.parallel_phases": {
        "label": "Parallel deep-analysis phases",
        "description": "Run a temporal deep analysis's middle phases (baseline ∥ decomposition ∥ dimensional) as one concurrent wave instead of a serial chain, keeping the serial tier-routers' early-stop semantics post-hoc (anything the serial path would have skipped is dropped from the report). Behavioral stays sequential — it targets the dimensional dominant finding. Cuts deep-run wall-clock; multiplies concurrent LLM calls (bounded by the P6 token budget). Off by default.",
    },
    "deep_analysis.why_where_interaction": {
        "label": "WHY×WHERE interaction lens",
        "description": "After the parallel WHERE and WHY lenses, forward-chain one more query crossing the leading return reason with the highest-impact segment — does the cause concentrate where the metric is worst (→ target that segment) or is it uniform (→ a broad problem)? Turns two independent findings into the actionable link. Adds one LLM-planned query per qualifying run; requires 'Parallel deep-analysis lenses'. Off by default.",
    },
    "deep_analysis.why_deepen": {
        "label": "Deepen the WHY (benchmark + drill)",
        "description": "After the WHY lens finds the leading return reason, forward-chain two more queries: a PEER BENCHMARK (is the reason's share abnormally high for the subject vs its peers, or a brand-wide baseline?) and a SECOND-LEVEL DRILL (which brands/products concentrate the leading reason — the fix target?). Establishes whether the cause is real and where to act. Adds two LLM-planned queries per qualifying run; requires 'Parallel deep-analysis lenses'. Off by default.",
    },
    "deep_analysis.parallel_why_lenses": {
        "label": "Parallel WHY-deepening lenses",
        "description": "Run the forward-chained WHY lenses (WHY×WHERE interaction ∥ peer benchmark ∥ reason drill) as one concurrent wave instead of a serial chain. Each depends ONLY on the already-computed WHERE/WHY summaries, never on each other, so the merge is byte-identical (fixed spec order, never completion order) — just faster wall-clock when two or more are enabled. Multiplies concurrent LLM calls (bounded by the P6 token budget); requires 'Parallel deep-analysis lenses' + the WHY lenses it parallelizes. Off by default.",
    },
    "preflight.parallel": {
        "label": "Parallel plan-time retrievals",
        "description": "Run the plan_queries pre-flight retrievals (relevant-schema ∥ KB planning patterns ∥ causal context ∥ closed-loop corrections) concurrently instead of one-at-a-time. All four are independent, deterministic, non-LLM lookups, so the result is byte-identical — just less wall-clock (a near-free win, no extra model cost). Default-ON since flag strategy batch A (2026-07-31, receipt `889789dda475`); force off with AUGHOR_PREFLIGHT_PARALLEL=0 or a runtime override for the serial path.",
    },
    "trust.verify_facade": {
        "label": "Unified trust.verify façade",
        "description": "Route SQL validation through the one Trust-plane façade (aughor/trust) — one Verdict composing the read-only/mutation gate, E1 footguns, preflight repair, and value-domain/fan-out probes — instead of a per-path guard subset. Adds the AST read-only gate to the /query/validate surface (closes SEC-02 there). Off by default while the plane lands (AL-01).",
    },
    "trust.verify_live": {
        "label": "Trust plane on the deep answer path",
        "description": "In the deep-analysis executor, route every generated SQL through trust.verify before execute — the AST read-only BLOCK the generation path never ran (defence-in-depth; the connection layer is already fail-closed). A blocked statement returns a blocked result instead of executing. Off by default (AL-01 live migration).",
    },
    "semantic.resolve_live": {
        "label": "Semantic plane resolved at the router",
        "description": "Resolve the Semantic plane (metrics · ontology · profile · KB) once when a deep analysis is seeded and attach the SemanticContext to the run state, so every node reads one consistent context instead of re-consulting ad-hoc. Forced off (AL-05 live migration). Default-ON since flag strategy batch C (2026-07-31, receipt `49e7af321440`); force off with AUGHOR_SEMANTIC_RESOLVE_LIVE=0 or a runtime override.",
    },
    "semantic.contract_live": {
        "label": "Unified metric contract (planning)",
        "description": "Render the governed-metric grounding block from the one SemanticContract type (catalog ∪ profile north-star ∪ ontology, deduped by precedence) instead of the parallel CanonicalMetric shape. Byte-identical output today — this repoints the planning path at the single metric contract, the 20-year ontology bet's type unification (REC-U10). Forced off while the migration lands. Default-ON since flag strategy batch B (2026-07-31, receipt `e801ff3a4448` — the metric blocks proved byte-identical over real stores); the remaining obligation is deleting the legacy CanonicalMetric path. Force off with AUGHOR_SEMANTIC_CONTRACT_LIVE=0 or a runtime override.",
    },
    "capability.pipeline_live": {
        "label": "Capability plane answer path",
        "description": "Enable the end-to-end Capability-plane answer path (/query/capability-answer): a data question runs generate → validate (trust.verify) → execute → interpret through the one CapabilityPipeline template. Forced off (AL-02 live migration). Default-ON since flag strategy batch C (2026-07-31, receipt `0dd2b45930c7`); force off with AUGHOR_CAPABILITY_PIPELINE_LIVE=0 or a runtime override.",
    },
    "deep_analysis.premise_check": {
        "label": "Premise validation",
        "description": "A 'why is X so high/low' deep analysis validates the premise (subject vs overall/peers) BEFORE explaining it — questioning the question itself instead of assuming it. Adds one comparison query per qualifying run. Off by default.",
    },
    "deep_analysis.causal_drill": {
        "label": "Causal-dimension priority + WHERE→WHY drill",
        "description": "The cross-section scan floats diagnostic dimensions (reason/condition/defect) ahead of the descriptive taxonomy so they survive the query cap, and after localising WHERE it auto-drills event-only dims into the WHY composition lens instead of stopping. Only affects the serial scan path (inert when 'Parallel deep-analysis lenses' is on, which lands the same idea in-lens). Off by default.",
    },
    "deep_analysis.adversarial_high_stakes": {
        "label": "Adversarial verify — high-stakes only",
        "description": "The materiality-gated tier of adversarial verification: challenge a decision-changing verdict (premise rejection / abstention) with one skeptic LLM call ONLY when it is asserted with HIGH confidence — the costly-if-wrong minority, and the only case where the HIGH→MEDIUM confidence cap can bite. Lets the refuter earn a place on the default path without paying an LLM call on the many MEDIUM/LOW verdicts. The always-challenge full tier (`deep_analysis.adversarial_verify`) was deleted 2026-07-31 (flag strategy §4G) — this is the one refuter gate.",
    },
    "deep_analysis.pin_canonical_metric": {
        "label": "Pin the governed metric at deep-analysis intake",
        "description": "When a deep analysis parses a metric the connection already GOVERNS (curated catalog / north-star / verified ontology), pin the intake's formula to the governed one so the cross-section scan decomposes on a stable, canonical definition instead of a run-varying LLM guess (the count-vs-value 'refund rate' class that left the breakdown un-decomposable → 'cause remains unidentified'). Deterministic, fail-open: only replaces the LLM formula when a governed metric matches the label, its SQL is a bare substitutable aggregate, and a dry-run confirms it runs over the metric table. Off by default = byte-identical.",
    },
    "deep_analysis.clarify_gate": {
        "label": "Interactive metric-ambiguity clarify (deep analysis)",
        "description": "When a deep analysis finds that a metric's GOVERNED reading and the LLM's parsed reading both run but give materially different numbers (the count-vs-value 'refund rate' class), PAUSE before the scan and ask the user which reading they meant — instead of silently choosing one. The choice binds the metric for the run and is crystallized to the Ambiguity Ledger (source=user), so the same question never re-asks on that connection. Mirrors the plan-gate interrupt/resume. Off by default; asks at most once per run, only on a real divergence.",
    },
    "deep_analysis.progress_events": {
        "label": "Live per-dimension deep-analysis progress",
        "description": "Stream a per-dimension progress event as each query of a deep-analysis scan completes, so a long cross-section/decompose phase reports 'scanning brand (3/6)…' DURING execution instead of a multi-minute silent spinner between phase_complete events. Interleaves a lightweight progress marker into the SSE stream via a best-effort in-process sink (no extra model cost, graph events never dropped). Off by default = byte-identical stream.",
    },
    "ask.clarify": {
        "label": "Ask-vs-guess clarification",
        "description": "When a fresh question is materially ambiguous, ask ONE targeted clarifying question instead of guessing (deterministic under-spec + value-term detection; budget one ask per turn). ON by default — disable to always answer immediately.",
    },
    "ask.resolve_first": {
        "label": "Ground-first answer resolution",
        "description": "Before the model writes SQL, decide ONCE and deterministically whether the question is answerable as asked: resolve the named entity against the data (bind the real value, or — if a bounded existence probe confirms it is absent — abstain honestly with what IS present, instead of running an empty filter and narrating around the emptiness), and reconcile the requested time grain against the finest grain the measure's table supports. The single verdict is handed to the generator as hard constraints (so it can't silently downgrade grain or guess a value) and drives one coherent caveat, replacing several post-hoc guards that each re-decide the same thing. Off by default = byte-identical (no resolution runs). The ground-first direction from the 2026-07-13 design discussion.",
    },
    "ask.conversation_context": {
        "label": "Conversation-aware resolution (follow-ups inherit context)",
        "description": "Make the ground-first resolver (ask.resolve_first) conversation-aware so a follow-up doesn't lose the prior turn's grounding — including across a mode switch. When THIS turn is a follow-up (is_followup) it inherits the previous turn's entity/filter (so 'break that down by platform' keeps the earlier 'womenswear' filter), and the resolver never DEAD-ENDS a follow-up with a terminal 'not present in this data' — an entity implicit from the conversation is left to the already history-aware generator instead of a hard abstention. Only affects follow-ups; a fresh question resolves exactly as before. Requires ask.resolve_first. AUTO-ELIGIBLE since flag strategy batch B (2026-07-31): both call sites are guarded by the deterministic is_followup detector, so under Auto-mode the trigger decides per turn; an explicit On/Off always wins.",
    },
    "ask.brief_context": {
        "label": "Ask this briefing — ground the answer in the briefing on screen",
        "description": "When a question is asked from the Briefing, prepend the briefing the user is LOOKING AT (its verdict, synthesis and cited findings) to the quick-answer prompt, so 'why is that?' and 'break that down' have a referent instead of arriving cold. Read SERVER-SIDE from the same conn:schema cache entry the Briefing rendered — never posted up by the client, so it cannot drift from what is on screen or be spoofed into the prompt. CONTEXT ONLY: it resolves references and pins the entities/time window; every number in the answer still comes from the query that runs. Bounded (verdict + up to 8 cited findings + a capped synthesis) and empty when no briefing is cached — no context beats invented context. Forced off = byte-identical. Default-ON since flag strategy batch B (2026-07-31, receipt `1277dd3f3f70`); force off with AUGHOR_ASK_BRIEF_CONTEXT=0 or a runtime override.",
    },
    "closed_loop": {
        "label": "Closed-loop corrections",
        "description": "Read captured human corrections/verdicts and trusted queries back into the planner as priors, so a corrected mistake isn't repeated. Off by default until its delta is proven on your data.",
    },
    "consistency.divergence": {
        "label": "Answer-consistency review (same question, two answers)",
        "description": "Surface recurring questions this connection has answered more than one way, so a human can settle which query is correct — and then the existing verified-pattern machinery reuses it. Detection is deterministic and read-only over answer receipts the platform already stores: no LLM, no writes, and cosmetic differences (schema qualification, alias renames, ROUND) are normalised away so only a real difference in what the query COMPUTES is reported. Ranked by whether a variant RECURS, which separates a routine metric with an established answer and a challenger — a decision worth taking — from an open question being explored from new angles, where variety is the point. An optional second stage EXECUTES the variants read-only and reports whether the answers actually differ and by how much; on the reference connection that narrowed 34 textually-contested questions to 12 genuinely divergent ones, the largest pair differing by 1.84M on a revenue question because one variant counted cancelled and test orders and the other did not. The platform never picks the winner: whether a cancelled order is revenue is a business fact, and promoting the most-used variant would launder popularity into correctness — a person pins the answer and it is tagged as human-reviewed, a stronger warrant than the consistency one an eval-promoted entry carries. Default-ON since flag strategy batch A (2026-07-31, receipt `2574532bcbde` — read-only routes, nothing on the answer path); force off with AUGHOR_CONSISTENCY_DIVERGENCE=0 or a runtime override, which returns the routes to 404.",
    },
    "semops.guarded_extract": {
        "label": "Guarded extraction (validate + re-extract)",
        "description": "When the semantic extract operator pulls a typed value (year/date/email/number) out of free text, validate each value against its type and re-extract the off-type cells with targeted feedback (a bounded gleaning loop). Off-type values are surfaced and kept, never dropped. Adds a re-extract LLM call only when a typed field fails validation. Off by default — turns text extraction from regex-fragile into a guarded, self-correcting step.",
    },
    "join.key_reconciliation": {
        "label": "Ill-formatted join-key reconciliation",
        "description": "When a join's two keys have low value overlap, try deterministic normalizations (trim/case, digits-only, strip prefix, strip leading zeros) and, if one lifts overlap over a bar, surface the exact expression to join on — distinguishing 'same entity, different format' (bid_123 vs bref_123) from genuinely different entities. Only runs when a value-domain mismatch already fired (rare); deterministic, fail-open, no LLM. Off by default = byte-identical (the mismatch warning is unchanged).",
    },
    "semops.champion_validate": {
        "label": "Champion cascade on semantic filter",
        "description": "The semantic filter operator runs on the cheap tier; with this on, a small spread sample of its verdicts is re-judged by the strong 'champion' model and the whole batch is escalated to the champion when they disagree beyond a bar — catching cheap-tier errors at the cost of one extra sample call per filter. Off by default = byte-identical (no validation sample). A label-free quality estimator: disagreement between the two tiers is the signal, so no ground-truth labels are needed.",
    },
    "federation.remote_join": {
        "label": "Cross-source batched-foreach join",
        "description": "Enable POST /query/cross-source-join — join a result from one connection to a table on another, N+1-free (dedup the join keys, one keyed batch query per key-chunk to the right source, hash-join in memory). The correct-by-construction path for true cross-engine joins (Snowflake↔BigQuery↔Postgres) that DuckDB ATTACH can't reach. Forced off → the route 404s. Stage 1 of the cross-source federated planner. Default-ON since flag strategy batch B (2026-07-31, receipt `41ec864723fb`); force off with AUGHOR_FEDERATION_REMOTE_JOIN=0 or a runtime override.",
    },
    "federation.planner": {
        "label": "Cross-source federated planner",
        "description": "Enable POST /query/federated-answer — answer a natural-language question that spans TWO connections. One LLM call grounds both schemas and emits a structured plan (a grounded sub-query per source + the join keys); the plan is validated deterministically (each sub-query executes and outputs its key) and executed through the batched-foreach engine. Plan-then-execute, guarded, inspectable (the plan is returned). Off by default → the route 404s. Stage 3 of cross-source federation. ⚠️ NOT purely invocation-gated: with the flag on, a fresh /ask turn at auto depth may AUTO-FEDERATE (see _federation_eligible) — an LLM-bearing routing change, which is why this stays an EXPERIMENT (flag strategy batch B premise check) until that delta is measured.",
    },
    "capability.contract": {
        "label": "Connector-capability contract",
        "description": "When a generated query FAILS on a native-SQL warehouse (BigQuery/Snowflake/MySQL), name the exact unsupported construct (QUALIFY/ILIKE/SAFE_DIVIDE/DATE_TRUNC/…) in the SQL-repair prompt so the regeneration fixes it precisely instead of another blind dry-run. A deterministic per-dialect capability descriptor + AST check; advisory (enriches the existing repair loop only), no LLM. Off by default = no extra hint. Rec 6 of the external-sources study.",
    },
    "rbac.row_policy": {
        "label": "RBAC row-level policy (row filters in the WHERE)",
        "description": "Compile per-role, per-table row-filters into executed SQL (a deterministic AST rewrite wrapping each policied table as a filtered subquery) so a role physically cannot read rows outside its filter. Double-gated like the rest of RBAC (no-op unless identity AND the org's RBAC_SSO capability are on) AND this flag; fails CLOSED (a policy that can't be applied blocks the query). Enforced at every connector's execution gate (DuckDB/Postgres/warehouse/file/API). Forced off. Rec 7 of the external-sources study. Default-ON since flag strategy batch B (2026-07-31, receipt `37fa12f2e54a`); force off with AUGHOR_RBAC_ROW_POLICY=0 or a runtime override.",
    },
    "agents.user_defined": {
        "label": "Custom agents (your own instructions + documents)",
        "description": "Create reusable agents that bind standing INSTRUCTIONS + a set of uploaded DOCUMENTS + a CONNECTION into one custom agent, then answer as that agent via /ask (agent_id). The agent's instructions lead the prompt, document retrieval is restricted to ITS documents (an agent with none sees none — fail-closed), and its connection binding wins (a conflicting explicit connection is rejected). CRUD under /agents/custom. Default-ON since Wave H, graduated on receipt `df89c044999a` (run `234be1fbb62b` of aughor/evals/user_agents_receipt.py, 9/9 stable over 3 iterations) on a DATA-GATED claim: every behaviour it adds needs an agent you created AND a request naming it, so with none named the prompt block is empty, retrieval stays unrestricted and a resumed run attaches no custom agent — all byte-identical to off. Turning it on does exactly one thing by itself: /agents/custom stops 404-ing and returns an empty roster. Force off with AUGHOR_USER_AGENTS=0 or a runtime override. Part B Phase 1 (slice 1) of docs/DATABRICKS_OSS_AND_AGENTIC_PLATFORM_STUDY_2026-07-11.md.",
    },
    "plan.program": {
        "label": "Plan-as-program executor",
        "description": "Enable POST /query/plan-run + /query/plan-answer — turn a question into a deterministic typed PROGRAM over ONE database. One LLM call emits an ordered list of DATA (grounded SQL) + SEMOP (semantic-operator) steps over named artifacts; the program is validated deterministically and run step-by-step through the guard battery, threading each step's result as a named, versioned ledger artifact. Plan-then-execute, guarded, inspectable + replayable (the plan + artifacts are returned). Off by default → the routes 404. Rec 4 (plan-as-program), Stage 2–3.",
    },
}


# ── Capabilities Auto-mode (Wave 1 · E3) ────────────────────────────────────
# SELF-GATING capabilities: a deterministic runtime trigger already decides whether they fire, so the
# flag is just a master enable. Under `capabilities.auto`, an unset one is treated as ENABLED (its own
# trigger then gates it per run) — the operator turns on the smart guards with one switch instead of
# flipping each. Cost-dangerous flags (federation.*, semops.champion_validate) are deliberately
# NOT here: running them automatically would be expensive, so they stay manual.
AUTO_ELIGIBLE: frozenset = frozenset({
    "deep_analysis.premise_check", "deep_analysis.clarify_gate", "deep_analysis.adversarial_high_stakes",
    "join.key_reconciliation", "capability.contract", "semops.guarded_extract",
    # Graduated 2026-07-13 (agentic-platform unification): both are deterministic and fail-open —
    # resolve() degrades to `answerable` when nothing binds; metric pinning requires a governed
    # metric match AND a clean dry-run before it does anything.
    "ask.resolve_first", "deep_analysis.pin_canonical_metric",
    # Graduated 2026-07-14: the "interesting facts about this schema" tour is fully
    # deterministic (no LLM), bounded, and fires ONLY on a metric/entity/time-free
    # overview-phrased question — the great default first-look, on by default.
    "ask.overview",
    # Converted 2026-07-31 (flag strategy batch B): both call sites are guarded by
    # `is_followup(question)` — a deterministic detector — so a fresh question is
    # byte-identical by construction and only a follow-up turn can differ. Requires
    # ask.resolve_first, which is already auto.
    "ask.conversation_context",
})
# Human description of each capability's deterministic trigger — surfaced in the flags API and (later) as
# the "why" on an activation receipt.
CAPABILITY_TRIGGER: dict = {
    "deep_analysis.premise_check": "the question asserts why a metric is high or low",
    "deep_analysis.clarify_gate": "candidate readings diverge materially on the metric",
    "deep_analysis.adversarial_high_stakes": "a high-confidence verdict would change the decision",
    "join.key_reconciliation": "a join's key value-domains mismatch",
    "capability.contract": "a generated query fails on a native-SQL warehouse",
    "semops.guarded_extract": "a typed-field extraction fails",
    "ask.resolve_first": "the question names an entity or time grain the schema resolves deterministically",
    "deep_analysis.pin_canonical_metric": "a governed metric matches the question and its canonical SQL dry-runs clean",
    "ask.overview": "the question asks for a broad overview with no metric, entity, or time window",
    "ask.conversation_context": "the turn is a follow-up to an earlier question",
}


# ── The disposition ratchet (flag strategy §5.1, 2026-07-31) ─────────────────────
# Every registered flag lives in EXACTLY ONE disposition — FLAG_DEFAULT (graduated),
# AUTO_ELIGIBLE (self-gating), or one of the declared sets below — and
# tests/unit/test_flag_dispositions.py enforces the partition. This converts "off"
# from an accident into a decision: a new flag that declares no exit fails CI, which
# is what stops the registry regrowing past human comprehension (it hit 91 before
# the 2026-07-31 study; ~1/day through July). A flag is a loan, not an asset.

#: Deliberately OFF, forever or until the named condition — the only category that
#: should stay a raw manual toggle.
INTENTIONALLY_OFF: dict = {
    # "ai_sql" left this set 2026-08-01: DELETED outright (see the FLAG_ENV tombstone).
    "obs.prompt_capture": "captures prompt CONTENT — the most sensitive material in a "
                          "deployment; deliberate, bounded-window use only",
    "automations.adopt_legacy": "changes an outward-send path (brief delivery); adopt "
                                "deliberately after the engine soaks, then DELETE the "
                                "legacy schedulers — the win is one loop, not a flag",
    "explorer.continuous": "recurring background spend; revisit now that "
                           "ops.metered_monitors (its declared gate) is default-ON",
    # "search.rrf" left this set 2026-08-01: DELETED outright (see the FLAG_ENV
    # tombstone) — the flag endgame has no "measured worse, kept anyway" state.
}

#: Group D — adds LLM calls (or changes prompts/routing) for a claimed quality gain;
#: the E4 grid is the exit. Each entry names the question that settles it. Pre-check
#: "does the flag change the prompt?" before buying any grid.
EXPERIMENT: dict = {
    # Moved here from the graduation queue by batch B's premise check: queued as
    # "invocation-gated route", but `_federation_eligible` ALSO auto-federates fresh
    # /ask auto-depth turns — an LLM-bearing routing change nothing has measured.
    "federation.planner": "does auto-federating fresh /ask turns improve cross-source "
                          "answers enough to pay its planning call?",
    # Moved from MIGRATION by batch C's premise check — the same disease as
    # federation.planner: `_program_eligible` auto-routes fresh /ask auto-depth turns
    # through plan-as-program. The adopt-or-kill decision IS this measurement.
    "plan.program": "does answering fresh /ask auto turns via plan-as-program match "
                    "quick-path quality (and settle adopt-or-kill)?",
    "closed_loop": "does reading captured corrections back into the planner improve "
                   "answers on your data? (its own description names this exit)",
    "graph.readback": "does the injected graph slice improve plans enough to pay its "
                      "prompt cost?",
    "explore.route_wide": "do landscape questions answer better through the explore wave?",
    "explorer.synthesis_incremental": "is mid-run synthesis worth the extra LLM calls?",
    "deep_analysis.why_where_interaction": "does the WHY×WHERE cross query change conclusions?",
    "deep_analysis.why_deepen": "do the peer-benchmark + drill queries change the fix target?",
    "deep_analysis.causal_drill": "serial-path twin of the parallel lenses — delete it if the "
                        "performance profile makes parallel the default",
    # "deep_analysis.evidence_stubs" left this set 2026-08-01: DELETED outright (see
    # the FLAG_ENV tombstone) — it dropped rows, the opposite of the evidence direction.
    "explorer.manifest_driven": "does deterministic coverage match LLM-loop quality?",
    "kinetic.agent_actions": "does the action proposer earn its LLM call?",
    "semops.champion_validate": "does champion validation catch enough cheap-tier "
                                "errors to pay one extra sample call per filter?",
    # snapshot_receipts SETTLED 2026-07-31 (batch D) and moved to FLAG_DEFAULT — its exit
    # was decidable without a grid: cost measured sub-ms (receipt 2dee7a36c03f), reconcile
    # already one mechanism (freeze.py reuses snapshot.data_version).
}

#: Group E — wall-clock vs concurrent-request trades. The exit is ONE performance
#: profile (Conservative / Balanced / Fast) that sets these together; under a 20 RPM
#: free-tier transport, defaulting them on individually is actively wrong today.
COST_LATENCY_PROFILE: frozenset = frozenset({
    "explore.parallel_subq", "deep_analysis.parallel_lenses", "deep_analysis.parallel_phases",
    "deep_analysis.parallel_why_lenses",
})

#: Group F — a fork of two maintained code paths with a completion obligation: flip,
#: soak, then DELETE the flag and the losing path. A migration flag with no completion
#: date is a permanent fork.
MIGRATION: dict = {
    # EMPTY as of batch C (2026-07-31): contract_live, resolve_live and pipeline_live
    # all flipped default-ON on proven claims and live in FLAG_DEFAULT (their remaining
    # obligation — deleting each legacy path once soaked — is noted at their entries);
    # plan.program moved to EXPERIMENT when its /ask auto-depth hook surfaced. A future
    # migration flag declares itself here with a completion obligation, or fails CI.
}

GRADUATION_QUEUE: dict = {
    # EMPTY as of batch C (2026-07-31): the Knowledge-Graph and connection-birth
    # bundles graduated on construction claims (a projection cannot precede its
    # ontology; the rite is kick-scoped and Curator-governed; empty stores are
    # byte-identical no-ops). A future flag queued to graduate declares itself here
    # with its receipt shape, or fails CI.
}


def flag_disposition(name: str) -> str:
    """The declared disposition for a registered flag — the UI's grouping key."""
    if name in FLAG_DEFAULT:
        return "default_on"
    if name in AUTO_ELIGIBLE:
        return "auto"
    if name in INTENTIONALLY_OFF:
        return "intentionally_off"
    if name in EXPERIMENT:
        return "experiment"
    if name in COST_LATENCY_PROFILE:
        return "performance_profile"
    if name in MIGRATION:
        return "migration"
    if name in GRADUATION_QUEUE:
        return "graduation_queue"
    return "undispositioned"   # the ratchet test fails on this


def _auto_mode_active() -> bool:
    """Whether the master Capabilities Auto-mode switch is on (default-off → byte-identical).

    Safe from recursion: `capabilities.auto` is not itself auto-eligible, so resolving it never re-enters
    the Auto-mode elevation branch below."""
    return flag_enabled("capabilities.auto")


def _env_resolved(name: str) -> bool:
    """Env-var value with the flag's default semantics.

    Default-off (the norm): unset ⇒ False, set ⇒ must be an explicit truthy value.
    Default-on (FLAG_DEFAULT): unset ⇒ True, set ⇒ off only on an explicit falsy
    value — preserving the old `os.getenv(var, "1") not in (off-list)` call sites
    byte-for-byte.
    """
    var = FLAG_ENV.get(name, "")
    raw = os.getenv(var)
    if raw is None:
        # A retired variable still in the operator's .env — honoured only while the
        # current one is unset, so migrating is a strict upgrade and never a surprise.
        for old_var, target in RETIRED_ENV.items():
            if target == name:
                raw = os.getenv(old_var)
                if raw is not None:
                    break
    if raw is None:
        if FLAG_DEFAULT.get(name, False):
            return True
        # Capabilities Auto-mode: an unset auto-eligible guard is enabled (its own trigger then decides)
        # when the master switch is on. The master defaults off, so this is byte-identical to before.
        if name in AUTO_ELIGIBLE and _auto_mode_active():
            return True
        return False
    if FLAG_DEFAULT.get(name, False):
        return raw.strip().lower() not in ("0", "false", "no", "off")
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_present(name: str) -> bool:
    """Whether an env var actually sets this flag — its own, or one it was renamed from.

    `flag_state` and `list_flags` report `source: "env"` from this rather than from
    `os.getenv(FLAG_ENV[name])` alone, so a retired variable can never make them disagree
    with `flag_enabled` (which would read "off" beside a live-on flag).
    """
    if os.getenv(FLAG_ENV.get(name, "")) is not None:
        return True
    return any(os.getenv(old) is not None
               for old, target in RETIRED_ENV.items() if target == name)


def _override(name: str):
    """The persisted runtime override, looked up under the current name and then under any
    name it was renamed from — an operator's existing override must survive a rename."""
    val = Ledger.default().kv_get(_STORE, name, None)
    if val is not None:
        return val
    for old in _retired_names(name):
        val = Ledger.default().kv_get(_STORE, old, None)
        if val is not None:
            return val
    return None


def override_drift() -> dict[str, dict]:
    """Runtime overrides that CHANGE what this process does versus a fresh clone.

    The count that matters is not "how many overrides exist" — it is how many *contradict*
    what the flag would resolve to without them. Measured 2026-07-31 on the reference box:
    **15 of 16 overrides were inert restatements of the default**, so an audit that counts
    overrides reports 16 problems where there is 1.

    The comparison is against :func:`_env_resolved`, NOT ``FLAG_DEFAULT``, and that
    distinction is load-bearing: an ``AUTO_ELIGIBLE`` flag with no default still resolves
    ON while Auto-mode is active, so an override pinning it ``False`` IS drift even though
    it matches ``FLAG_DEFAULT.get(name, False)``. Predicting the effect of a clear from
    ``FLAG_DEFAULT`` alone got three flags wrong on exactly that point.

    Returns ``{flag: {"override": bool, "without_override": bool}}`` — empty when this
    process resolves every flag the way a fresh clone would.
    """
    drift: dict[str, dict] = {}
    for name in FLAG_ENV:
        ov = _override(name)
        if ov is None:
            continue
        clean = _env_resolved(name)
        if bool(ov) != clean:
            drift[name] = {"override": bool(ov), "without_override": clean}
    return drift


# ── Run-scoped overrides (Wave E4) ────────────────────────────────────────────────────
# Both layers above are process-global: the ledger override is persistent and the env var
# needs a restart. Neither can express "run THIS cell of the grid with the flag on" while a
# sibling cell runs it off in the same process. A contextvar can, and it propagates into
# worker threads through `ContextThreadPoolExecutor` — the same mechanism `set_run_model`,
# metering and the parallel-safety refusal already rely on.
_run_overrides: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar(
    "aughor_flag_overrides", default=None
)


class UnknownFlagError(KeyError):
    """An override named a flag that is not registered.

    Loud on purpose. An experiment whose override silently no-ops is indistinguishable
    from an experiment whose variant did not help — the exact confusion
    `verify-features-actually-ran` exists to prevent, and a typo in a dotted flag name
    is the easiest way to produce it.
    """


def active_flag_overrides() -> dict:
    """The run-scoped overrides in force right now (empty when there are none).

    The runner records this so a report states what the run was actually configured with,
    rather than what the caller asked for.
    """
    return dict(_run_overrides.get() or {})


@contextlib.contextmanager
def flag_overrides(mapping: Optional[dict] = None, **kw: bool):
    """Force specific flags for the duration of the block, for this context only.

    Dotted names (`deep_analysis.parallel_lenses`) cannot be keyword arguments, so the mapping form
    is the primary one; kwargs are accepted for the handful of undotted flags. Nested use
    merges, so an inner block can vary one axis of an outer configuration.

    ⚠️ **Graph-topology flags are read at COMPILE time**, not at run time — see
    `agent/graph.py` lines 128/140/229, which sit inside `_compile()`. For those the block
    must wrap `build_graph_generic(...)`, not merely the graph's invocation. Wrapping only
    the run leaves the topology at whatever the process-global layers said, and the
    override looks like it did nothing. `tests/unit/test_flag_overrides.py` pins this.
    """
    requested = {_canonical(n): v for n, v in {**(mapping or {}), **kw}.items()}
    unknown = sorted(n for n in requested if n not in FLAG_ENV)
    if unknown:
        raise UnknownFlagError(
            f"unregistered flag(s) {unknown}; registered names live in FLAG_ENV "
            f"(aughor/kernel/flags.py). An override on an unknown name would silently "
            f"do nothing and read downstream as 'the variant did not help'."
        )
    merged = {**(_run_overrides.get() or {}), **{n: bool(v) for n, v in requested.items()}}
    token = _run_overrides.set(merged)
    try:
        yield merged
    finally:
        _run_overrides.reset(token)


def flag_enabled(name: str) -> bool:
    """The effective value: a run-scoped override wins, then a runtime override, then env."""
    name = _canonical(name)
    run = _run_overrides.get()
    if run is not None and name in run:
        return bool(run[name])
    ov = _override(name)
    if ov is not None:
        return bool(ov)
    return _env_resolved(name)


def flag_state(name: str) -> str:
    """Tri-state view for the Capabilities UI: ``"on"`` | ``"off"`` | ``"auto"``.

    ``"auto"`` means the capability is enabled ONLY because the master Auto-mode elevated this self-gating
    guard (its deterministic trigger decides per run) — an explicit operator On/Off always resolves to
    ``"on"``/``"off"``. A display refinement over ``flag_enabled`` (which is True for both on and auto)."""
    name = _canonical(name)
    run = _run_overrides.get()
    if run is not None and name in run:
        return "on" if run[name] else "off"
    ov = _override(name)
    if ov is not None:
        return "on" if ov else "off"
    if _env_present(name):
        return "on" if _env_resolved(name) else "off"
    if FLAG_DEFAULT.get(name, False):
        return "on"
    if name in AUTO_ELIGIBLE and _auto_mode_active():
        return "auto"
    return "off"


def set_flag(name: str, value: bool) -> None:
    """Set a runtime override (wins over the env var until cleared).

    Writes under the CURRENT name, and drops any row still held under a name this flag
    was renamed from — otherwise the legacy row would outlive the setting that replaced
    it and resurface the moment the new one is cleared.
    """
    name = _canonical(name)
    led = Ledger.default()
    led.kv_put(_STORE, name, bool(value))
    for old in _retired_names(name):
        if led.kv_get(_STORE, old, None) is not None:
            led.kv_put(_STORE, old, None)


def clear_flag(name: str) -> None:
    """Drop the override so the env var decides again — under every name it may be
    stored as, or a retired row would silently keep overriding."""
    name = _canonical(name)
    led = Ledger.default()
    led.kv_put(_STORE, name, None)
    for old in _retired_names(name):
        led.kv_put(_STORE, old, None)


def list_flags() -> dict:
    """All registered flags with their effective value + source, for the Settings UI."""
    out = {}
    run = _run_overrides.get() or {}
    for name, var in FLAG_ENV.items():
        ov = _override(name)
        meta = FLAG_META.get(name, {})
        # `value` must agree with `flag_enabled` — a receipt rendered inside an experiment
        # cell that reported the operator's setting instead of the run's would attribute the
        # measurement to the wrong configuration.
        out[name] = {
            "value": bool(run[name]) if name in run
                     else bool(ov) if ov is not None else _env_resolved(name),
            "state": flag_state(name),
            "override": ov,                       # None (no override) | True | False — the UI's tri-state setting
            "auto_eligible": name in AUTO_ELIGIBLE,
            **({"trigger": CAPABILITY_TRIGGER[name]} if name in CAPABILITY_TRIGGER else {}),
            # "env" used to be the catch-all tail, so a flag that was on purely because of
            # its CODE default reported `source: "env"` and sent an operator hunting for a
            # variable nobody had set. That gets more misleading with every graduation, so
            # the two are distinguished: "env" means the variable is actually present.
            "source": ("run" if name in run else "runtime" if ov is not None
                       else "env" if _env_present(name) else "default"),
            "env_var": var,
            "label": meta.get("label", name),
            "description": meta.get("description", ""),
            # The declared disposition (flag strategy §5.1) — lets the Settings UI
            # group by KIND instead of rendering one flat list of toggles.
            "disposition": flag_disposition(name),
            # Names this flag used to have. Present so an operator searching the docs or
            # their own .env for the old name can see where it went; empty for almost
            # every flag, and omitted entirely when there is nothing to say.
            **({"renamed_from": _retired_names(name)} if _retired_names(name) else {}),
            **({"disposition_note": INTENTIONALLY_OFF.get(name)
                                    or EXPERIMENT.get(name)
                                    or MIGRATION.get(name)
                                    or GRADUATION_QUEUE.get(name)}
               if flag_disposition(name) in ("intentionally_off", "experiment",
                                             "migration", "graduation_queue") else {}),
        }
    return out
