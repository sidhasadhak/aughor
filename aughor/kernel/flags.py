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
    # HARDWIRED 2026-08-01 (flag endgame Wave 2, trust/observability/LLM group) — each
    # graduated with a receipt and is now unconditional product behaviour, its flag and
    # off-path deleted: trust.verify_live · trust.verify_facade · trust.e1_live ·
    # obs.session_log · obs.task_table · ask.stream_text · ask.context_receipt ·
    # capabilities.receipt · learning.receipt · deep_analysis.progress_events ·
    # llm.structured_salvage · llm.bounded_repair.
    # HARDWIRED 2026-08-02 (flag endgame Wave 2, graph/ontology group) — same rule,
    # same deletion: graph.build · graph.freshness · graph.surface · graph.tour ·
    # graph.export · graph.consolidate · ontology.autodoc · ontology.column_config ·
    # obs.popularity · birth.job. (graph.readback stays — it is an EXPERIMENT.)
    # HARDWIRED 2026-08-02 (Wave 2d, the ask/deep answer path) — each is now unconditional,
    # its flag and off-path deleted: ask.clarify · ask.brief_context ·
    # deep_analysis.evidence_dedup · intake.loss_signals · report.argument_style ·
    # chart.exhibit_grammar · lens.decision_grade · preflight.parallel ·
    # schema.two_tier_catalog · explore.wandering_detector.
    # `ada.evidence_dedup` and AUGHOR_ADA_EVIDENCE_DEDUP went with evidence_dedup: an alias
    # is required to resolve to a REGISTERED flag, so it cannot outlive its target.
    # ask.clarify is the one entry here with no measured receipt — it shipped default-ON
    # from birth (`os.getenv("AUGHOR_ASK_CLARIFY", "1")` at the original call site), so the
    # off path was never anyone's behaviour. The per-turn `skip_clarify` bypass, which is
    # what actually suppresses the gate in practice, is untouched.
    # The legacy chart vocabulary survives deliberately: CHAT_SQL_SYSTEM still feeds the
    # benchmark and custom-agent quality paths, which this flag never gated.
    # HARDWIRED 2026-08-02 (Wave 2, govern/automations/lifecycle group): govern.clearances ·
    # govern.usage_caps · rbac.row_policy · freshness.resolved_rebuild · kinetic.actions ·
    # kinetic.overlay · lifecycle.publish · lifecycle.freeze · automations.engine ·
    # automations.source_probes · automations.proposals. Each stays DATA-gated — an untagged
    # securable, an org with no caps, a deployment with no identity, a connection with no
    # declared actions and a user who has frozen nothing all behave exactly as before.
    # "explorer.synthesis_incremental" (AUGHOR_SYNTHESIS_INCREMENTAL) was DELETED
    # 2026-08-01 (flag endgame, verdict sheet Wave 1): mid-run synthesis spent extra
    # model calls for a "more alive" cadence the chat UI now provides for free, and
    # the end-of-run Phase 9 synthesis always ran regardless.
    # The four Group-E parallelism flags ("explore.parallel_subq" / AUGHOR_EXPLORE_PARALLEL,
    # "deep_analysis.parallel_lenses" / AUGHOR_DEEP_ANALYSIS_PARALLEL_LENSES,
    # "deep_analysis.parallel_phases" / AUGHOR_DEEP_ANALYSIS_PARALLEL_PHASES,
    # "deep_analysis.parallel_why_lenses" / AUGHOR_DEEP_ANALYSIS_PARALLEL_WHY_LENSES)
    # were DELETED 2026-08-06 (flag endgame Wave 6, verdict sheet 2026-08-01): hardwiring
    # them ON broke the rate-capped free transport, OFF threw away wall-clock on capable
    # ones — neither default was honest, so there is no switch. The always-on behaviour is
    # "as parallel as the bound transport's declared rate budget allows", derived in
    # aughor/llm/profile.py (`parallel_waves_enabled`; AUGHOR_LLM_RPM still wins in both
    # directions, and an OpenRouter `:free` binding counts as its documented 20 RPM).
    # Flag endgame Wave 2 FINAL GROUP (2026-08-06) — the 14 remaining default-ONs
    # became unconditional and left this registry with their env vars:
    # AUGHOR_SNAPSHOT_RECEIPTS · AUGHOR_SPECIALIST_PACKS · AUGHOR_STARTERS_LIBRARY ·
    # AUGHOR_SEMANTIC_RESOLVE_LIVE · AUGHOR_SEMANTIC_CONTRACT_LIVE (the legacy
    # CanonicalMetric path went with it) · AUGHOR_CAPABILITY_PIPELINE_LIVE ·
    # AUGHOR_CONSISTENCY_DIVERGENCE · AUGHOR_FEDERATION_REMOTE_JOIN ·
    # AUGHOR_EVALS_EXPERIMENTS · AUGHOR_AGENTS_USER_DEFINED · AUGHOR_MONITORS_GUARDED ·
    # AUGHOR_METERED_MONITORS · AUGHOR_AGUI_ENDPOINT — and AUGHOR_CLARIFY_GATE, whose
    # deployment posture DISSOLVED into the per-request `allow_clarify` field (the
    # honest home: whether a run may pause is a property of the caller, not the env).
    # Receipts on the FLAG_DEFAULT tombstone below.
    "explore.route_wide": "AUGHOR_EXPLORE_ROUTE_WIDE",
    "deep_analysis.why_where_interaction": "AUGHOR_DEEP_ANALYSIS_WHY_WHERE_INTERACTION",
    "deep_analysis.why_deepen": "AUGHOR_DEEP_ANALYSIS_WHY_DEEPEN",
    "deep_analysis.causal_drill": "AUGHOR_CAUSAL_DRILL",
    # "ada.adversarial_verify" (AUGHOR_ADA_ADVERSARIAL) was DELETED 2026-07-31 (flag
    # strategy §4G): the always-challenge tier was superseded by the materiality-gated
    # auto tier below, had no constituency, and a deleted flag is the only disposition
    # that actually shrinks the registry. One-off audits can reproduce it by asking the
    # question directly; the refuter itself (run_refutation) is unchanged.
    "closed_loop": "AUGHOR_CLOSED_LOOP",
    "semops.champion_validate": "AUGHOR_SEMOPS_CHAMPION_VALIDATE",
    "federation.planner": "AUGHOR_FEDERATION_PLANNER",
    # "plan.program" (AUGHOR_PLAN_PROGRAM) was DELETED 2026-08-01 (flag endgame, verdict
    # sheet Wave 1): a SECOND answer path (typed program executor) with a standing
    # adopt-or-kill question. One brain, one answer path — the benchmarking arc measured
    # the lean path plus deterministic guards winning. /query/plan-run, /query/plan-answer,
    # program_planner.py, the trusted-programs store and the /ask auto-route hook all went.
    # "obs.mlflow" (AUGHOR_OBS_MLFLOW) was DELETED 2026-07-31 (flag strategy §4C):
    # MLflow tracing now self-gates on AUGHOR_MLFLOW_TRACKING_URI being set, like the
    # other env-configured observability backends — a flag that is a no-op without an
    # external server and inert with one configured was two ways to be confused.
    # "obs.prompt_capture" (AUGHOR_OBS_PROMPT_CAPTURE) was DELETED 2026-08-01 (flag
    # endgame, verdict sheet Wave 1). The capability stays — it is how a recorded run
    # becomes a reproducible bug report — but a standing switch over the most sensitive
    # content this product writes is a control that depends on somebody remembering to
    # close it. Replaced by a self-expiring WINDOW (aughor/obs/prompt_window.py,
    # POST/GET/DELETE /obs/prompt-capture) bounded by a call budget AND a clock.
    # "deep_analysis.evidence_stubs" (AUGHOR_DEEP_ANALYSIS_EVIDENCE_STUBS) was DELETED
    # 2026-08-01 (flag endgame, verdict sheet Wave 1): it rendered already-scored
    # results as row-capped stubs — deliberately showing the model FEWER rows to save
    # tokens, the opposite of the evidence-budget direction, and its own description
    # forbade graduation without the A/B that was never bought. Its lossless sibling
    # (evidence_dedup) carries the whole win.
    # "search.rrf" (AUGHOR_SEARCH_RRF) was DELETED 2026-08-01 (flag endgame, verdict
    # sheet Wave 1): the RRF fusion was MEASURED worse than the α-blend default on the
    # real KB corpus (MRR 0.964 vs 0.977, recall@1 0.931 vs 0.957). The instrument was
    # `aughor/evals/rrf_retrieval_eval.py`, removed with the flag because it toggled the
    # flag to build its two arms and cannot run without it. It is RECOVERABLE at
    # `git show e094603:aughor/evals/rrf_retrieval_eval.py` (branch
    # worktree-flag-experiment-queue) — naming the commit rather than only the deletion
    # is what keeps a settled decision re-checkable by somebody who doubts it later.
    # hybrid_rerank now α-blends unconditionally.
    # RESTORED 2026-08-04, after Wave 3's adversarial review. This one was NOT redundant
    # with its trigger, and the difference is the whole lesson: the trigger answers a DATA
    # question ("do the two readings of this metric diverge?"), while the flag answers a
    # DEPLOYMENT question ("does this deployment want to be interrupted about it?").
    # Unwrapped, a divergent ratio metric pauses the run — `_stream_investigation` emits
    # `clarify_pending`, calls `pause_investigation` and returns WITH NO REPORT — so a
    # headless or batch consumer that never POSTs /feedback got a truncated run where it
    # previously got an answer. Nine of the ten guards only added cost when elevated; this
    # one blocks. Default-ON (the interactive product behaviour), operator can opt out.
    # DELETED 2026-08-04 (flag endgame Wave 3) — the NINE AUTO_ELIGIBLE self-gating guards
    # that WERE redundant with their own triggers, now unconditional. The AUTO_ELIGIBLE
    # tombstone carries the reasoning. Retired variables:
    #   deep_analysis.premise_check  (AUGHOR_PREMISE_CHECK)
    #   deep_analysis.adversarial_high_stakes  (AUGHOR_DEEP_ANALYSIS_ADVERSARIAL_HIGH_STAKES)
    #   deep_analysis.pin_canonical_metric  (AUGHOR_DEEP_ANALYSIS_PIN_CANONICAL_METRIC)
    #   join.key_reconciliation  (AUGHOR_JOIN_KEY_RECONCILIATION)
    #   capability.contract  (AUGHOR_CAPABILITY_CONTRACT)
    #   semops.guarded_extract  (AUGHOR_GUARDED_EXTRACT)
    #   ask.resolve_first  (AUGHOR_ASK_RESOLVE_FIRST)
    #   ask.overview  (AUGHOR_ASK_OVERVIEW)
    #   ask.conversation_context  (AUGHOR_ASK_CONVERSATION_CONTEXT)
    "explorer.manifest_driven": "AUGHOR_EXPLORER_MANIFEST_DRIVEN",
    # "capabilities.auto" (AUGHOR_CAPABILITIES_AUTO) was DELETED 2026-08-04 (flag endgame
    # Wave 3): it was a master switch over the ten AUTO_ELIGIBLE guards, and those are
    # unconditional now, so it governed nothing. See the AUTO_ELIGIBLE tombstone.
    "explorer.continuous": "AUGHOR_EXPLORER_CONTINUOUS",
    "kinetic.agent_actions": "AUGHOR_KINETIC_AGENT_ACTIONS",  # Wave K4: the agent may PROPOSE declared actions
    "automations.adopt_legacy": "AUGHOR_AUTOMATIONS_ADOPT_LEGACY",  # Wave A5: run monitors+briefs through the engine
    "graph.readback": "AUGHOR_GRAPH_READBACK",  # Wave C2: grep-the-graph-first — inject the graph slice as a plan-time prior
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
    # Three `ada.*` aliases left this map 2026-08-04: their targets
    # (deep_analysis.{premise_check, adversarial_high_stakes, pin_canonical_metric}) were
    # DELETED by flag endgame Wave 3, and an alias only means something while its target
    # lives — `_canonical` would resolve the old name to a flag no longer in FLAG_ENV, so
    # the alias adds a second dead name beside the dead one.
    #
    # Note what the hazard is NOT: an operator whose `.env` still exports the retired
    # variable gets `False`, not an exception. `UnknownFlagError` comes only from
    # `flag_overrides()`, which env vars never reach. The real risk runs the other way —
    # `flag_enabled` on an unregistered name silently returns False — which is why the
    # deletion sweep greps live CALL SITES, not just the registry.
    # (The clarify-gate alias left 2026-08-06: its restored target dissolved into
    #  the `allow_clarify` request posture — flag endgame Wave 2.)
    # Wave W: the `ada.*` family. "ADA" expanded, in its own docstring, to words it does
    # not spell; the feature is "deep analysis" everywhere a human reads it. Call sites
    # may keep passing the old name indefinitely — `_canonical` resolves it.
    # Three more `ada.*` aliases left 2026-08-06: their targets
    # (deep_analysis.{parallel_lenses, parallel_phases, parallel_why_lenses}) were
    # deleted by flag endgame Wave 6 (transport-derived parallelism) — same rule as
    # the Wave 3 removals above: an alias only means something while its target lives.
    "ada.causal_drill": "deep_analysis.causal_drill",
    "ada.why_deepen": "deep_analysis.why_deepen",
    "ada.why_where_interaction": "deep_analysis.why_where_interaction",
}

#: Retired env var → the flag it now feeds. Consulted only when the current flag's own
#: env var is unset, so an operator who has already migrated is never second-guessed.
RETIRED_ENV: dict[str, str] = {
    # Wave W: `AUGHOR_ADA_*` → `AUGHOR_DEEP_ANALYSIS_*`. An operator's existing .env keeps
    # opting in. (The three `ada.*` flags whose env var never said ADA — PREMISE_CHECK,
    # CAUSAL_DRILL, CLARIFY_GATE — kept their variable and need no entry.)
    # The three AUGHOR_ADA_PARALLEL_* entries left 2026-08-06 with their targets
    # (flag endgame Wave 6).
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
FLAG_DEFAULT: dict = {
    # EMPTY as of flag endgame Wave 2 (2026-08-06): every graduated default-ON became
    # UNCONDITIONAL — the flags, their env vars and their off-paths are deleted; the
    # receipts that graduated each one are preserved on the tombstones in FLAG_ENV and
    # at the former guard sites. The set stays declared so `flag_disposition`, the
    # `_env_resolved` default-on semantics and the disposition ratchet keep their
    # shape, and an empty set proves nothing quietly re-enters "default_on":
    #   trust/obs/LLM group — hardwired by Wave 2 group 1 (2c981ea1);
    #   graph/ontology group — group 2 (f2dfa99f); govern/automations — group 3 (cbbf6927);
    #   the final 14 (this wave): snapshot_receipts 2dee7a36c03f · specialist_packs
    #   452a6fcebba4 · starters.library 3155c4d9de61 · semantic.resolve_live
    #   49e7af321440 · semantic.contract_live e801ff3a4448 (legacy CanonicalMetric
    #   path DELETED with it) · capability.pipeline_live 0dd2b45930c7 ·
    #   consistency.divergence 2574532bcbde · federation.remote_join 41ec864723fb ·
    #   evals.experiments 1bc0e4690955 · agents.user_defined df89c044999a ·
    #   monitors.guarded 9bf08c312faa · ops.metered_monitors b167bb891764 ·
    #   agui.endpoint b395745f7771 · deep_analysis.clarify_gate DISSOLVED into the
    #   request posture `allow_clarify` (a headless caller opts out per request —
    #   the deployment-env kill switch a flag provided is now the caller's own field).
}

# Human-facing copy for the Settings UI.
FLAG_META = {
    "kinetic.agent_actions": {
        "label": "Agent proposes declared actions",
        "description": "Let the agent PROPOSE declared actions from an analysis — the model returns structured proposals which are dry-run validated (typed params + submission criteria) and STAGED for a human to accept and run through the governed executor. Nothing is executed here; nothing above LOW risk ever auto-fires. Off by default ⇒ the agent never proposes actions (byte-identical) and the proposer makes no LLM call.",
    },
    "graph.readback": {
        "label": "Grep-the-graph-first read-back",
        "description": "Before generating SQL, match the committed connection knowledge graph against the question, pull the 1-hop subgraph, and inject it as a plan-time prior — the mechanic that finally closes the open feedback loop. The subgraph carries the two node types that were write-only before: `finding` (dossiers and exploration findings) and the `resolves` readings, so a question about a table Aughor already analysed inherits what it learned, with the join guard's measured value-domain overlap surfaced as a number (not the ✓ the prompt path otherwise collapses it to). Every injected line is cited by its node/edge id (the block the context receipt shows names exactly what grounded the plan). Ranked hybrid search: a deterministic lexical floor always runs; the Qdrant vector rank fuses in when reachable (RRF) and NEVER degrades to an unranked fallback. Appended at the one function both live answer paths inject (verify.priors.build_corrections_section), gated independently of `closed_loop`. Off by default = byte-identical (empty string, zero prompt cost). Requires a graph built by `graph.build`; no graph ⇒ no-op. Counter: context_graph.*",
    },
    "automations.adopt_legacy": {
        "label": "Adopt monitors and briefings onto the automation engine",
        "description": "Run every enabled Monitor and Briefing subscription THROUGH the one automation engine instead of their own near-identical schedulers: each is read on the fly as a virtual automation (a cron `schedule` condition + a faithful effect — a `monitor` effect that replays run_monitor with its anti-flap debounce intact and appends the same alert, or the existing `brief` effect that calls deliver_subscription), so there is one loop, one run history, and one place a tick's reason is recorded. Only takes effect when automations.engine is ALSO on (the heartbeat has to be running to drive them), and while active the legacy monitor and briefing schedulers stand down at FIRE time as well as at start — so a runtime flag flip can never double-fire an alert or, worse, double-DELIVER a briefing (an outward send). Off by default ⇒ the legacy schedulers run exactly as before (byte-identical) and the heartbeat ignores monitors and briefings. No data migration either way; flipping it off restores the legacy path.",
    },
    "explorer.manifest_driven": {
        "label": "Manifest-driven deterministic exploration",
        "description": "Cover the Phase-8 L2 baseline cells (measure × dimension) with SYNTHESISED SQL from a deterministic coverage manifest — no per-cell generation LLM call — with the existing explorer guards enforcing correctness; the LLM curiosity loop still handles cells/domains the manifest doesn't cover. Deterministic-first: fewer LLM calls, reproducible baseline coverage tracked across re-runs. Fails closed to the LLM loop if the manifest can't build. Off by default = byte-identical (LLM-only exploration). (Was consulted but unregistered — study E3 housekeeping.)",
    },
    "explorer.continuous": {
        "label": "Continuous exploration (re-explore on schema change / staleness)",
        "description": "Keep the Explorer learning after the first pass: a periodic tick re-arms exploration when the connection's live schema fingerprint no longer matches the one the last run recorded (a table/column was added or removed), or when the last completed run is older than the staleness window (AUGHOR_EXPLORER_REFRESH_DAYS, default 7). Re-runs are incremental — the coverage frontier is recomputed from persisted findings, so only genuinely new cuts spend budget — and still flow through the Explorer-governance + AUTO_EXPLORATION gates and the per-run exploration budget. Off by default = byte-identical (exploration runs once on connect + on demand). WP-6 of the 2026-07-12 platform review; makes the \"never stops learning\" claim true rather than aspirational.",
    },
    "explore.route_wide": {
        "label": "Route wide questions to the explore wave",
        "description": "Let the /ask door send a genuinely BROAD 'landscape' question — characterize / profile / map how X varies across the business — to the multi-cut explore subgraph instead of a single deep analysis. A deterministic detector decides (no model in the routing path); it yields to causal/driver 'why' questions, which stay deep analyses. Unlocks the already-built explore wave from /ask. Off by default.",
    },
    "deep_analysis.why_where_interaction": {
        "label": "WHY×WHERE interaction lens",
        "description": "After the parallel WHERE and WHY lenses, forward-chain one more query crossing the leading return reason with the highest-impact segment — does the cause concentrate where the metric is worst (→ target that segment) or is it uniform (→ a broad problem)? Turns two independent findings into the actionable link. Adds one LLM-planned query per qualifying run; requires the parallel lens wave, which runs whenever the transport allows it (A1 ModelProfile). Off by default.",
    },
    "deep_analysis.why_deepen": {
        "label": "Deepen the WHY (benchmark + drill)",
        "description": "After the WHY lens finds the leading return reason, forward-chain two more queries: a PEER BENCHMARK (is the reason's share abnormally high for the subject vs its peers, or a brand-wide baseline?) and a SECOND-LEVEL DRILL (which brands/products concentrate the leading reason — the fix target?). Establishes whether the cause is real and where to act. Adds two LLM-planned queries per qualifying run; requires the parallel lens wave, which runs whenever the transport allows it (A1 ModelProfile). Off by default.",
    },
    "deep_analysis.causal_drill": {
        "label": "Causal-dimension priority + WHERE→WHY drill",
        "description": "The cross-section scan floats diagnostic dimensions (reason/condition/defect) ahead of the descriptive taxonomy so they survive the query cap, and after localising WHERE it auto-drills event-only dims into the WHY composition lens instead of stopping. Only affects the serial scan path (inert when 'Parallel deep-analysis lenses' is on, which lands the same idea in-lens). Off by default.",
    },
    "closed_loop": {
        "label": "Closed-loop corrections",
        "description": "Read captured human corrections/verdicts and trusted queries back into the planner as priors, so a corrected mistake isn't repeated. Off by default until its delta is proven on your data.",
    },
    "semops.champion_validate": {
        "label": "Champion cascade on semantic filter",
        "description": "The semantic filter operator runs on the cheap tier; with this on, a small spread sample of its verdicts is re-judged by the strong 'champion' model and the whole batch is escalated to the champion when they disagree beyond a bar — catching cheap-tier errors at the cost of one extra sample call per filter. Off by default = byte-identical (no validation sample). A label-free quality estimator: disagreement between the two tiers is the signal, so no ground-truth labels are needed.",
    },
    "federation.planner": {
        "label": "Cross-source federated planner",
        "description": "Enable POST /query/federated-answer — answer a natural-language question that spans TWO connections. One LLM call grounds both schemas and emits a structured plan (a grounded sub-query per source + the join keys); the plan is validated deterministically (each sub-query executes and outputs its key) and executed through the batched-foreach engine. Plan-then-execute, guarded, inspectable (the plan is returned). Off by default → the route 404s. Stage 3 of cross-source federation. ⚠️ NOT purely invocation-gated: with the flag on, a fresh /ask turn at auto depth may AUTO-FEDERATE (see _federation_eligible) — an LLM-bearing routing change, which is why this stays an EXPERIMENT (flag strategy batch B premise check) until that delta is measured.",
    },
}


# ── Capabilities Auto-mode (Wave 1 · E3) ────────────────────────────────────
# SELF-GATING capabilities: a deterministic runtime trigger already decides whether they fire, so the
# flag is just a master enable. Under `capabilities.auto`, an unset one is treated as ENABLED (its own
# trigger then gates it per run) — the operator turns on the smart guards with one switch instead of
# flipping each. Cost-dangerous flags (federation.*, semops.champion_validate) are deliberately
# NOT here: running them automatically would be expensive, so they stay manual.
AUTO_ELIGIBLE: frozenset = frozenset()
# DISSOLVED 2026-08-04 (flag endgame Wave 3). The ten self-gating guards that lived here
# — deep_analysis.{premise_check, clarify_gate, adversarial_high_stakes,
# pin_canonical_metric} · join.key_reconciliation · capability.contract ·
# semops.guarded_extract · ask.{resolve_first, overview, conversation_context} — are now
# UNCONDITIONAL, because their triggers were always the real gate: an is_followup()
# detector, a governed-metric match that must dry-run clean, a decision-changing
# materiality test, a failing repair path. A flag on top of a deterministic trigger only
# ever re-answers a question the trigger has already answered, and it does so from a
# different source of truth (an env var) than the one that decides (the data).
#
# The set stays declared and EMPTY rather than deleted: `flag_disposition` and the
# disposition ratchet both still reference it, and an empty set makes the elevation
# branch inert by construction — which is what lets the ratchet keep proving that no new
# flag quietly rejoins this tier.
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
    # "obs.prompt_capture" left this set 2026-08-01: DELETED outright (see the FLAG_ENV
    # tombstone) — "bounded-window use only" is now enforced by the window, not by a note.
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
    # "plan.program" left this set 2026-08-01: DELETED outright (see the FLAG_ENV
    # tombstone) — the adopt-or-kill question was settled as KILL, not measured.
    "closed_loop": "does reading captured corrections back into the planner improve "
                   "answers on your data? (its own description names this exit)",
    "graph.readback": "does the injected graph slice improve plans enough to pay its "
                      "prompt cost?",
    "explore.route_wide": "do landscape questions answer better through the explore wave?",
    # "explorer.synthesis_incremental" left this set 2026-08-01: DELETED outright (see
    # the FLAG_ENV tombstone) — its question was settled by the chat-UI liveliness work.
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

#: Group E — wall-clock vs concurrent-request trades. EMPTY as of flag endgame Wave 6
#: (2026-08-06): the four parallelism flags were deleted for a transport-derived
#: decision in `aughor/llm/profile.py` (`parallel_waves_enabled` — "as parallel as the
#: bound transport's declared rate budget allows"; the exit the verdict sheet named).
#: The set stays declared and EMPTY like AUTO_ELIGIBLE: `flag_disposition` and the
#: disposition ratchet still reference it, and an empty set proves nothing rejoins
#: the tier.
COST_LATENCY_PROFILE: frozenset = frozenset()

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
    distinction is load-bearing: whenever something ELSE would turn a flag on — an env var
    today, Auto-mode elevation until Wave 3 dissolved it — an override pinning it ``False``
    IS drift even though it matches ``FLAG_DEFAULT.get(name, False)``. Predicting the
    effect of a clear from ``FLAG_DEFAULT`` alone got three flags wrong on exactly that.

    ⚠️ It only reports overrides for REGISTERED flags. A row left behind for a deleted
    flag is invisible here and dormant — until that name is ever re-registered, when it
    would come back to life. A flag deletion that expects to strand overrides should clear
    them, the same way :func:`set_flag` drops rows held under a renamed-from name.

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
    """The Capabilities UI's view of a flag: ``"on"`` or ``"off"``.

    Was tri-state until Wave 3 dissolved Auto-mode. ``"auto"`` meant "enabled only because
    the master switch elevated this self-gating guard"; those guards are unconditional
    now, so the third state has nothing left to describe. The signature is unchanged, so
    every caller keeps working — it simply never returns ``"auto"``."""
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
            # Always False since Wave 3 dissolved the tier. Kept in the payload so an
            # older client reading this field still parses; it has no live producer.
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
