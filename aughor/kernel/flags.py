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
    "specialist_packs": "AUGHOR_SPECIALIST_PACKS",
    "explore.parallel_subq": "AUGHOR_EXPLORE_PARALLEL",
    "explore.route_wide": "AUGHOR_EXPLORE_ROUTE_WIDE",
    "starters.library": "AUGHOR_STARTERS_LIBRARY",
    "deep_analysis.parallel_lenses": "AUGHOR_DEEP_ANALYSIS_PARALLEL_LENSES",
    "deep_analysis.parallel_phases": "AUGHOR_DEEP_ANALYSIS_PARALLEL_PHASES",
    "deep_analysis.why_where_interaction": "AUGHOR_DEEP_ANALYSIS_WHY_WHERE_INTERACTION",
    "deep_analysis.why_deepen": "AUGHOR_DEEP_ANALYSIS_WHY_DEEPEN",
    "deep_analysis.parallel_why_lenses": "AUGHOR_DEEP_ANALYSIS_PARALLEL_WHY_LENSES",
    "semantic.resolve_live": "AUGHOR_SEMANTIC_RESOLVE_LIVE",
    "semantic.contract_live": "AUGHOR_SEMANTIC_CONTRACT_LIVE",
    "capability.pipeline_live": "AUGHOR_CAPABILITY_PIPELINE_LIVE",
    "deep_analysis.causal_drill": "AUGHOR_CAUSAL_DRILL",
    # "ada.adversarial_verify" (AUGHOR_ADA_ADVERSARIAL) was DELETED 2026-07-31 (flag
    # strategy §4G): the always-challenge tier was superseded by the materiality-gated
    # auto tier below, had no constituency, and a deleted flag is the only disposition
    # that actually shrinks the registry. One-off audits can reproduce it by asking the
    # question directly; the refuter itself (run_refutation) is unchanged.
    "closed_loop": "AUGHOR_CLOSED_LOOP",
    "consistency.divergence": "AUGHOR_CONSISTENCY_DIVERGENCE",  # Wave N1: same question, two answers
    "semops.champion_validate": "AUGHOR_SEMOPS_CHAMPION_VALIDATE",
    "federation.remote_join": "AUGHOR_FEDERATION_REMOTE_JOIN",
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
    "evals.experiments": "AUGHOR_EVALS_EXPERIMENTS",
    "agents.user_defined": "AUGHOR_USER_AGENTS",
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
    "deep_analysis.clarify_gate": "AUGHOR_CLARIFY_GATE",
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
    "monitors.guarded": "AUGHOR_MONITORS_GUARDED",
    "explorer.continuous": "AUGHOR_EXPLORER_CONTINUOUS",
    "ops.metered_monitors": "AUGHOR_METERED_MONITORS",
    "agui.endpoint": "AUGHOR_AGUI_ENDPOINT",
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
    # (`ada.clarify_gate` stays: its target was restored, see the FLAG_ENV note.)
    # Wave W: the `ada.*` family. "ADA" expanded, in its own docstring, to words it does
    # not spell; the feature is "deep analysis" everywhere a human reads it. Call sites
    # may keep passing the old name indefinitely — `_canonical` resolves it.
    "ada.causal_drill": "deep_analysis.causal_drill",
    "ada.parallel_lenses": "deep_analysis.parallel_lenses",
    "ada.parallel_phases": "deep_analysis.parallel_phases",
    "ada.parallel_why_lenses": "deep_analysis.parallel_why_lenses",
    "ada.why_deepen": "deep_analysis.why_deepen",
    "ada.why_where_interaction": "deep_analysis.why_where_interaction",
}

#: Retired env var → the flag it now feeds. Consulted only when the current flag's own
#: env var is unset, so an operator who has already migrated is never second-guessed.
RETIRED_ENV: dict[str, str] = {
    # Wave W: `AUGHOR_ADA_*` → `AUGHOR_DEEP_ANALYSIS_*`. An operator's existing .env keeps
    # opting in. (The three `ada.*` flags whose env var never said ADA — PREMISE_CHECK,
    # CAUSAL_DRILL, CLARIFY_GATE — kept their variable and need no entry.)
    "AUGHOR_ADA_PARALLEL_LENSES": "deep_analysis.parallel_lenses",
    "AUGHOR_ADA_PARALLEL_PHASES": "deep_analysis.parallel_phases",
    "AUGHOR_ADA_PARALLEL_WHY_LENSES": "deep_analysis.parallel_why_lenses",
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
FLAG_DEFAULT = {
    # WP-1f (2026-07-12 platform review) — the trust plane LEVERAGED, not just built.
    # Promoted to default-ON after a live A/B over the workspace + fixture healthy-path
    # corpus (1,837 unique executed statements): `trust.verify_live` produced ZERO
    # false-positive blocks, and once the E1 live checks read real column types
    # (`connection_column_types`) the only false-positive caveat — a DATE column named
    # `*_at`/`*_ts` tripping the name heuristic — disappeared, leaving only genuine
    # timestamp-boundary footguns. An operator can still disable any of these with an
    # explicit env `=0` or a runtime override. See docs/PLATFORM_REVIEW…2026-07-12.md WP-1f.
    # Capability graduation (2026-07-13, agentic-platform unification). Policy: a capability that is
    # (a) self-gating behind a deterministic runtime trigger, or (b) a pure observability/receipt
    # surface with negligible cost, GRADUATES to default-on once BUILT→WIRED→TESTED. The platform
    # decides per run; the operator can still force any flag off (env =0 / runtime override) — an
    # explicit setting always wins over these defaults. This is E3 Phase 1 ("the flag system should
    # decide, with receipts") made the default posture instead of an opt-in.
    # "capabilities.auto" left this set 2026-08-04 with the tier it mastered (Wave 3).
    # Default-ON, and deliberately NOT auto-elevated: pausing to ask which reading the user
    # meant is the interactive product behaviour, and `AUGHOR_CLARIFY_GATE=0` is a real
    # kill switch for a headless deployment that cannot answer an interrupt. See FLAG_ENV.
    "deep_analysis.clarify_gate": True,
    # (The 2026-07-22 flag-drift audit's Batch 1 — intake.loss_signals ·
    # report.argument_style · chart.exhibit_grammar · lens.decision_grade — lived here
    # until Wave 2d hardwired all four. The lesson that outlived them is the one that
    # started the endgame: they had been ON in one developer's runtime ledger for weeks
    # while the code shipped them OFF, so every fresh clone and every CI run validated a
    # configuration nobody actually ran. That is what `override_drift()` now refuses.)
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
    # Default-ON for a reason that only became visible once the transport stack was
    # measured end-to-end: instructor's own default is THREE attempts, and we had never
    # overridden it, so a malformed response already cost 3 full-prompt requests. Wave R1
    # sets that to 1 (`_structured_attempts`) and this flag is what replaces the two we
    # removed — at a fraction of the size, because the repair carries the broken output
    # and the specific error rather than a second copy of the original prompt and its
    # evidence. Off, the ceiling is 1 request per failure and some salvageable answers
    # are lost; on, it is 2 — still below the 3 this wave inherited.
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
    "deep_analysis.clarify_gate": {
        "label": "Ask which reading was meant when a metric is ambiguous",
        "description": "When a deep analysis finds that a metric's governed formula and its parsed reading DIVERGE materially, pause and show both readings with probed previews so the user picks — the run resumes via /feedback. Default-ON: choosing between two defensible readings is a business decision the platform must not make silently. Turn OFF (AUGHOR_CLARIFY_GATE=0) for a headless or batch deployment that cannot answer an interrupt — with it on and nobody to respond, the run emits `clarify_pending` and ends without a report. The ambiguity is detected and recorded either way; this flag only decides whether it INTERRUPTS.",
    },
    "explorer.manifest_driven": {
        "label": "Manifest-driven deterministic exploration",
        "description": "Cover the Phase-8 L2 baseline cells (measure × dimension) with SYNTHESISED SQL from a deterministic coverage manifest — no per-cell generation LLM call — with the existing explorer guards enforcing correctness; the LLM curiosity loop still handles cells/domains the manifest doesn't cover. Deterministic-first: fewer LLM calls, reproducible baseline coverage tracked across re-runs. Fails closed to the LLM loop if the manifest can't build. Off by default = byte-identical (LLM-only exploration). (Was consulted but unregistered — study E3 housekeeping.)",
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
    "snapshot_receipts": {
        "label": "Snapshot-pinned receipts",
        "description": "Pin every finding to the exact data version it ran against (reproducible-as-of), so a re-validate can tell a MOVED dataset apart from a mis-derived finding — the same data_version Wave V4's freeze pins an artifact to. The version probe is one metadata COUNT(*) per finding table (size-independent on DuckDB; the native snapshot id on DuckLake), added at dossier emit off the answer path. Default-ON since the 2026-07-31 flag strategy experiment-queue settle (batch D, receipt `2dee7a36c03f`): measured median ~0.2ms for a 3-table finding against E1's 5ms bar, additive (off ⇒ the dossier's data_version is None, byte-identical otherwise), and fail-open (a probe that cannot run yields None, never blocking the emit). Force off with AUGHOR_SNAPSHOT_RECEIPTS=0 or a runtime override.",
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
    "evals.experiments": {
        "label": "Grid experiments: run-scoped model / temperature / flag overrides",
        "description": "Lets an eval suite run the same cases under several configurations in ONE process, so a variant can be compared against its baseline instead of against a number recorded on a different day under an unrecorded config. Flags resolve through the ledger and the environment, both process-global, so before this two cells of a grid could not disagree; a contextvar consulted ahead of both can, and it reaches worker threads through ContextThreadPoolExecutor like the model pin and the metering hook. The plane is inert unless a run enters it (the contextvars default to unset, so ordinary traffic is byte-identical), and it refuses to measure at all while AUGHOR_FALLBACK_DISABLED is off, because the failover chain would silently finish a run on a different model and the report would attribute the number to the binding that started it. Every cell records the configuration read back through the product's own resolvers rather than the one requested — an override that silently no-ops is indistinguishable from a variant that did not help, and the second reading flatters the harness. First customers: the experiment-queue flags whose exit questions need an A/B. Default-ON since flag strategy batch A (2026-07-31, receipt `1bc0e4690955` — the plane is inert until a run enters it: ambient traffic carries no run-scoped overrides, and with the flag off a grid REFUSES loudly rather than silently running one configuration); force off with AUGHOR_EVALS_EXPERIMENTS=0 or a runtime override.",
    },
    "starters.library": {
        "label": "Named starter questions",
        "description": "Surface a library of named, deterministic starters (interesting outlier entities, where are we losing money, data quality scan) plus per-space curated questions from the ontology doc tree as one-click starters on /suggestions. Each starter declares its route up front (deep analysis or the wide explore wave) and carries a purpose tag on the route receipt — templates, no model in the loop. Default-ON since flag strategy batch A (2026-07-31, receipt `3155c4d9de61` — deterministic payload, purely additive `starters` key on /suggestions); force off with AUGHOR_STARTERS_LIBRARY=0 or a runtime override for LLM-generated-only suggestions — see docs/DATABRICKS_HAR_CANVAS_BIRTH_STUDY_2026-07-16.md (R13).",
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
    "deep_analysis.causal_drill": {
        "label": "Causal-dimension priority + WHERE→WHY drill",
        "description": "The cross-section scan floats diagnostic dimensions (reason/condition/defect) ahead of the descriptive taxonomy so they survive the query cap, and after localising WHERE it auto-drills event-only dims into the WHY composition lens instead of stopping. Only affects the serial scan path (inert when 'Parallel deep-analysis lenses' is on, which lands the same idea in-lens). Off by default.",
    },
    "closed_loop": {
        "label": "Closed-loop corrections",
        "description": "Read captured human corrections/verdicts and trusted queries back into the planner as priors, so a corrected mistake isn't repeated. Off by default until its delta is proven on your data.",
    },
    "consistency.divergence": {
        "label": "Answer-consistency review (same question, two answers)",
        "description": "Surface recurring questions this connection has answered more than one way, so a human can settle which query is correct — and then the existing verified-pattern machinery reuses it. Detection is deterministic and read-only over answer receipts the platform already stores: no LLM, no writes, and cosmetic differences (schema qualification, alias renames, ROUND) are normalised away so only a real difference in what the query COMPUTES is reported. Ranked by whether a variant RECURS, which separates a routine metric with an established answer and a challenger — a decision worth taking — from an open question being explored from new angles, where variety is the point. An optional second stage EXECUTES the variants read-only and reports whether the answers actually differ and by how much; on the reference connection that narrowed 34 textually-contested questions to 12 genuinely divergent ones, the largest pair differing by 1.84M on a revenue question because one variant counted cancelled and test orders and the other did not. The platform never picks the winner: whether a cancelled order is revenue is a business fact, and promoting the most-used variant would launder popularity into correctness — a person pins the answer and it is tagged as human-reviewed, a stronger warrant than the consistency one an eval-promoted entry carries. Default-ON since flag strategy batch A (2026-07-31, receipt `2574532bcbde` — read-only routes, nothing on the answer path); force off with AUGHOR_CONSISTENCY_DIVERGENCE=0 or a runtime override, which returns the routes to 404.",
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
    "agents.user_defined": {
        "label": "Custom agents (your own instructions + documents)",
        "description": "Create reusable agents that bind standing INSTRUCTIONS + a set of uploaded DOCUMENTS + a CONNECTION into one custom agent, then answer as that agent via /ask (agent_id). The agent's instructions lead the prompt, document retrieval is restricted to ITS documents (an agent with none sees none — fail-closed), and its connection binding wins (a conflicting explicit connection is rejected). CRUD under /agents/custom. Default-ON since Wave H, graduated on receipt `df89c044999a` (run `234be1fbb62b` of aughor/evals/user_agents_receipt.py, 9/9 stable over 3 iterations) on a DATA-GATED claim: every behaviour it adds needs an agent you created AND a request naming it, so with none named the prompt block is empty, retrieval stays unrestricted and a resumed run attaches no custom agent — all byte-identical to off. Turning it on does exactly one thing by itself: /agents/custom stops 404-ing and returns an empty roster. Force off with AUGHOR_USER_AGENTS=0 or a runtime override. Part B Phase 1 (slice 1) of docs/DATABRICKS_OSS_AND_AGENTIC_PLATFORM_STUDY_2026-07-11.md.",
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
