"""Runtime feature flags — operator-toggleable, env-var fallback.

A handful of capabilities ship off-by-default because they cost (per-row LLM calls,
per-table version probes). They were previously env-only (`AUGHOR_AI_SQL`,
`AUGHOR_SNAPSHOT_RECEIPTS`), so an operator had to restart the process to flip them.
This stores an override in the kernel ledger kv so the UI can toggle them at runtime;
when no override is set, the env var still decides.

`flag_enabled(name)` is the resolver the feature code calls. The override is read from
SQLite per call (one indexed kv read — negligible; these aren't ultra-hot paths).
"""
from __future__ import annotations

import os

from aughor.kernel.ledger import Ledger

_STORE = "feature_flags"

# Registered flags: logical name → the env var that decides when no override is set.
FLAG_ENV = {
    "ai_sql": "AUGHOR_AI_SQL",
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
    "ada.parallel_lenses": "AUGHOR_ADA_PARALLEL_LENSES",
    "ada.parallel_phases": "AUGHOR_ADA_PARALLEL_PHASES",
    "ada.why_where_interaction": "AUGHOR_ADA_WHY_WHERE_INTERACTION",
    "ada.why_deepen": "AUGHOR_ADA_WHY_DEEPEN",
    "ada.parallel_why_lenses": "AUGHOR_ADA_PARALLEL_WHY_LENSES",
    "preflight.parallel": "AUGHOR_PREFLIGHT_PARALLEL",
    "trust.verify_facade": "AUGHOR_TRUST_FACADE",
    "trust.verify_live": "AUGHOR_TRUST_VERIFY_LIVE",
    "semantic.resolve_live": "AUGHOR_SEMANTIC_RESOLVE_LIVE",
    "semantic.contract_live": "AUGHOR_SEMANTIC_CONTRACT_LIVE",
    "capability.pipeline_live": "AUGHOR_CAPABILITY_PIPELINE_LIVE",
    "ada.premise_check": "AUGHOR_PREMISE_CHECK",
    "ada.causal_drill": "AUGHOR_CAUSAL_DRILL",
    "ada.adversarial_verify": "AUGHOR_ADA_ADVERSARIAL",
    "ada.adversarial_high_stakes": "AUGHOR_ADA_ADVERSARIAL_HIGH_STAKES",
    "ada.pin_canonical_metric": "AUGHOR_ADA_PIN_CANONICAL_METRIC",
    "ada.progress_events": "AUGHOR_ADA_PROGRESS_EVENTS",
    "ada.clarify_gate": "AUGHOR_CLARIFY_GATE",
    "ask.clarify": "AUGHOR_ASK_CLARIFY",
    "ask.resolve_first": "AUGHOR_ASK_RESOLVE_FIRST",
    "ask.conversation_context": "AUGHOR_ASK_CONVERSATION_CONTEXT",
    "ask.brief_context": "AUGHOR_ASK_BRIEF_CONTEXT",
    "closed_loop": "AUGHOR_CLOSED_LOOP",
    "semops.guarded_extract": "AUGHOR_GUARDED_EXTRACT",
    "join.key_reconciliation": "AUGHOR_JOIN_KEY_RECONCILIATION",
    "semops.champion_validate": "AUGHOR_SEMOPS_CHAMPION_VALIDATE",
    "federation.remote_join": "AUGHOR_FEDERATION_REMOTE_JOIN",
    "federation.planner": "AUGHOR_FEDERATION_PLANNER",
    "plan.program": "AUGHOR_PLAN_PROGRAM",
    "capability.contract": "AUGHOR_CAPABILITY_CONTRACT",
    "rbac.row_policy": "AUGHOR_RBAC_ROW_POLICY",
    "obs.mlflow": "AUGHOR_OBS_MLFLOW",
    "obs.task_table": "AUGHOR_OBS_TASK_TABLE",
    "obs.session_log": "AUGHOR_OBS_SESSION_LOG",
    "obs.popularity": "AUGHOR_OBS_POPULARITY",
    "ask.context_receipt": "AUGHOR_ASK_CONTEXT_RECEIPT",
    "ask.stream_text": "AUGHOR_ASK_STREAM_TEXT",
    "ask.overview": "AUGHOR_ASK_OVERVIEW",
    "agents.user_defined": "AUGHOR_USER_AGENTS",
    "search.rrf": "AUGHOR_SEARCH_RRF",
    "explorer.manifest_driven": "AUGHOR_EXPLORER_MANIFEST_DRIVEN",
    "learning.receipt": "AUGHOR_LEARNING_RECEIPT",
    "capabilities.auto": "AUGHOR_CAPABILITIES_AUTO",
    "capabilities.receipt": "AUGHOR_CAPABILITIES_RECEIPT",
    "trust.e1_live": "AUGHOR_TRUST_E1_LIVE",
    "monitors.guarded": "AUGHOR_MONITORS_GUARDED",
    "explorer.continuous": "AUGHOR_EXPLORER_CONTINUOUS",
    "ops.metered_monitors": "AUGHOR_METERED_MONITORS",
    "agui.endpoint": "AUGHOR_AGUI_ENDPOINT",
}

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
    "ada.progress_events": True,   # deep-run dead-air fix (CK-0.4): fine-grained progress beats
    "ask.stream_text": True,       # CK-0.2 dual-emit insight deltas; terminal event stays authoritative
}

# Human-facing copy for the Settings UI.
FLAG_META = {
    "ai_sql": {
        "label": "In-SQL AI operators",
        "description": "Register the governed prompt()/embedding() UDFs and let the generator use them. Makes per-row LLM calls — enable deliberately.",
    },
    "agui.endpoint": {
        "label": "AG-UI protocol endpoint (POST /agui/run)",
        "description": "Expose an additive AG-UI-compatible translator at POST /agui/run that re-frames the existing /ask event stream (via the shared build_ask_stream factory) into standard AG-UI protocol events (RunStarted / TextMessage* / ToolCall* / Custom / RunError / RunFinished) using the ag-ui-protocol SDK. Purely additive — the legacy /ask, /chat and /investigate emission is byte-identical and the frontend's default transport is unchanged; this is the backend half of the CopilotKit/AG-UI adoption plan's CK-1 seam, letting any AG-UI client (CopilotKit, the @ag-ui/client transport) drive Aughor. Off by default ⇒ the route 404s.",
    },
    "ask.stream_text": {
        "label": "Token-stream the answer narrative",
        "description": "Stream the post-answer insight narrative as it is written (`insight_delta` SSE events carrying the partial text) instead of one late pop-in, then emit the existing full `insight` event as the authoritative terminal value (self-healing: a dropped delta costs nothing). Dual-emit and additive — old clients ignore the unknown delta events; off = byte-identical to the pre-streaming stream. Falls back to the blocking call on any streaming error. CK-0.2 of the CopilotKit/AG-UI adoption plan.",
    },
    "ask.overview": {
        "label": "Interesting-facts overview tour (the default first-look)",
        "description": "Answer the widest-possible question — \"show me interesting facts about this schema\" / \"tell me about this data\" — the way Genie offers by default: a DETERMINISTIC profile of the whole dataset ranked by notability and capped for diversity, not an investigation of one metric. Seven lenses (scale · concentration · outlier · distribution · composition · coverage · relationship) each run a cheap grounded probe (mostly one SUMMARIZE per table, no LLM), then a diverse top-N is selected so the tour spans many tables and fact types. Fires ONLY on an overview-phrased question with no metric/entity/time window named; graduated to Auto (on by default via `capabilities.auto`) because it is bounded and deterministic. An explicit env `=0` disables it.",
    },
    "ask.context_receipt": {
        "label": "Grounding-context receipt (show what the model was grounded on)",
        "description": "Expose the exact grounding block the SQL writer sees — the schema slice chosen, glossary entries, governed-metric bindings, ambiguity-ledger priors applied, value-index literal bindings, dialect rules, and active pack bindings — as JSON + rendered markdown via GET /ask/context and a \"Show grounding\" affordance on the answer. The input-side twin of the Trust Receipt (which covers the output). Assembly is centralised in a pure build_grounding_context() that the answer path and the endpoint share, so the receipt is exactly what the run used (no drift). Off by default = byte-identical (endpoint returns 404, no receipt section). Wave 1 · Rec 5 of the combined platform study.",
    },
    "obs.task_table": {
        "label": "task_history — spans as a queryable table",
        "description": "Sink the kernel ledger's node/tool span events into one append-only task_history table (trace_id, span_id, parent_span_id, task, input, captured_output, timing, error, labels) — the queryable spine of \"what the agent actually did.\" It is a SINK over the spans telemetry already emits, not new instrumentation: MLflow/Langfuse stay the rich-trace backends; this makes the same exhaust answerable with plain SQL, so evals recover generated SQL by querying the table (no log parsing) and Deep Analysis can investigate its own behaviour via the aughor_ops schema. Off by default = byte-identical (no rows written). Wave 2 · Rec 4 of the combined platform study.",
    },
    "obs.session_log": {
        "label": "session_events — the agent-session log",
        "description": "Record one append-only session_events row per agent-session event (user_request · tool_call · tool_call_result · llm_call · final_response · execution_error) with a stable trace id, a monotonic sequence, explicit success/duration/error-class, and the ambient session/user/agent identity. Fills the gap task_history cannot: it mints the trace at the /ask door, so the QUICK answer path — which today creates no trace id at all and whose SQL bypasses the span-emitting executor — becomes reconstructible; it writes tool_call on ENTRY, so a call that hangs or is cancelled still leaves evidence, where a span row only ever appears after the body returns; and it records each LLM call (model, role, tokens, latency, retries, whether the fallback swapped the model mid-run), which today is aggregated into counters and discarded. Queryable as SQL via the aughor_ops schema, and the substrate a later evals harness turns real sessions into test cases from. Retention is enforced on write (AUGHOR_SESSION_LOG_KEEP_DAYS / _MAX_ROWS). Off by default = byte-identical (no rows written). Wave E1.",
    },
    "obs.popularity": {
        "label": "Query popularity as a shared notability signal",
        "description": "Mine real query history (the SQL-examples store + task_history span inputs) into a persisted per-table and per-column usage counter, and let one signal feed four consumers: column-config default protection (a queried column is never default-hidden), doc-tree table facts + ranking, the overview's learned-prior boost, and a most-queried-tables block in /suggestions. Mining runs inside the R12 birth job; deterministic (sqlglot, no model). Off by default = byte-identical — see docs/DATABRICKS_HAR_CANVAS_BIRTH_STUDY_2026-07-16.md (R14).",
    },
    "search.rrf": {
        "label": "Reciprocal Rank Fusion (hybrid retrieval)",
        "description": "Fuse the vector and lexical (BM25) rankings in hybrid_rerank by Reciprocal Rank Fusion (rank-based, k=60) instead of the min-max α-blend. Rank-based fusion is robust to the score-scale mismatch between Qdrant cosine and BM25 that α-blending is sensitive to; it preserves vector order when there is no lexical signal, so it is a safe A/B on the KB-retrieval evals. Off by default = byte-identical (α-blend). Rec 6 of the combined platform study.",
    },
    "explorer.manifest_driven": {
        "label": "Manifest-driven deterministic exploration (Phase 8)",
        "description": "Cover the Phase-8 L2 baseline cells (measure × dimension) with SYNTHESISED SQL from a deterministic coverage manifest — no per-cell generation LLM call — with the existing explorer guards enforcing correctness; the LLM curiosity loop still handles cells/domains the manifest doesn't cover. Deterministic-first: fewer LLM calls, reproducible baseline coverage tracked across re-runs. Fails closed to the LLM loop if the manifest can't build. Off by default = byte-identical (LLM-only exploration). (Was consulted but unregistered — study E3 housekeeping.)",
    },
    "learning.receipt": {
        "label": "Per-run Learning Receipt",
        "description": "Attach a Learning Receipt to each answer — a per-run summary of what the closed loop DID: resolved readings reused (and how many were human corrections), resolutions crystallized this run, and trusted plan-as-programs replayed. Emitted as an SSE `learning` event and stamped on the Trust Receipt so the accumulation the loop already captures is finally visible. Off by default = byte-identical (no event, no receipt section). Wave 1 · E4 of the combined platform study.",
    },
    "capabilities.auto": {
        "label": "Capabilities Auto-mode (self-gating guards decide per run)",
        "description": "Master switch for Auto-mode: with it on, each SELF-GATING capability (a deterministic guard that already only fires on a runtime trigger — premise-check, clarify gate, high-stakes adversarial verify, join key-reconciliation, capability-contract repair, guarded extract) is ENABLED unless the operator explicitly turned it off, and its own trigger decides per run — so you turn on the smart guards with one switch instead of flipping each. An explicit per-capability On/Off always wins; cost-dangerous flags (ai_sql, federation, champion-validate) are NOT auto-eligible. Off by default = byte-identical. Wave 1 · E3 of the combined platform study.",
    },
    "trust.e1_live": {
        "label": "E1 function-semantics checks on live answers",
        "description": "Run the E1 footgun battery (a timestamp bounded by a date-only literal drops that day's later rows; ORDER BY/MIN/MAX over numeric-looking text sorts lexicographically; text↔numeric comparisons) on the FINAL SQL of live answers — the quick/chat headline and every Deep-Analysis phase query — as labelled WARN caveats. Pure AST, deterministic, never rewrites the query (the E1 contract). Previously these checks ran only on /query/validate, never on an answer a user actually saw. Off by default = byte-identical. WP-1e of the 2026-07-12 platform review.",
    },
    "ops.metered_monitors": {
        "label": "Meter background monitors & briefs through the kernel",
        "description": "Route each scheduled monitor tick and brief delivery through the job kernel (as the Watcher / Briefer agents) instead of calling the runner directly on the scheduler thread. The warehouse SQL a monitor/brief runs then joins the same metering as an answer — visible in Fleet/metering, counted toward the agent's per-run token/time budget, and heartbeat-supervised (a run over budget is cancelled). Preserves the tenant re-bind the schedulers already do. Off by default = byte-identical (the direct in-thread path). Gate for turning continuous exploration (`explorer.continuous`) on by default — background cost must be metered before it can re-explore automatically. WP-7 of the 2026-07-12 platform review.",
    },
    "monitors.guarded": {
        "label": "Guarded monitor evaluations",
        "description": "Run the deterministic correctness probes (fan-out/grain, id-arithmetic) on a monitor's SQL at evaluation time and attach any finding as a caveat on the alert — a wrong-grain SUM in a monitor otherwise silently mis-values the metric and then alerts on it. Never rewrites the monitor's SQL; caveat-and-deliver. Off by default = byte-identical. WP-1b of the 2026-07-12 platform review.",
    },
    "explorer.continuous": {
        "label": "Continuous exploration (re-explore on schema change / staleness)",
        "description": "Keep the Scout learning after the first pass: a periodic tick re-arms exploration when the connection's live schema fingerprint no longer matches the one the last run recorded (a table/column was added or removed), or when the last completed run is older than the staleness window (AUGHOR_EXPLORER_REFRESH_DAYS, default 7). Re-runs are incremental — the coverage frontier is recomputed from persisted insights, so only genuinely new cuts spend budget — and still flow through the Scout-governance + AUTO_EXPLORATION gates and the per-run charter budget. Off by default = byte-identical (exploration runs once on connect + on demand). WP-6 of the 2026-07-12 platform review; makes the \"never stops learning\" claim true rather than aspirational.",
    },
    "capabilities.receipt": {
        "label": "Activation Receipt (which guards fired, and why)",
        "description": "Attach an Activation Receipt to each answer — the self-gating guards that actually fired this run and the deterministic trigger that fired them (\"activated premise-check because the question asserts why a metric is high/low\"). Emitted as an SSE `activations` event and stamped on the Trust Receipt, so Auto-mode's per-run decisions are visible instead of implicit. Off by default = byte-identical (no event, no receipt section). Wave 1 · E3 of the combined platform study.",
    },
    "snapshot_receipts": {
        "label": "Snapshot-pinned receipts",
        "description": "Pin every finding to the exact data version it ran against (reproducible-as-of). The version probe touches the DB on each emit.",
    },
    "explorer.synthesis_incremental": {
        "label": "Incremental synthesis",
        "description": "Fire cross-finding synthesis the moment a new finding creates a combinable pair, not only at end-of-run. More 'alive', more compute. Phase 9 always runs at end-of-run regardless.",
    },
    "specialist_packs": {
        "label": "Specialist Agents (Domain Expertise Packs)",
        "description": "Load user-built specialist packs (packs/) and let them steer the engine at intake. Off by default while the subsystem lands — see docs/DOMAIN_EXPERTISE_PACKS.md.",
    },
    "explore.parallel_subq": {
        "label": "Parallel explore sub-questions",
        "description": "Run independent explore sub-questions concurrently in dependency-respecting waves (map-reduce over the operator.add state) instead of one-at-a-time. Cuts wall-clock on multi-cut investigations; multiplies concurrent LLM calls (bounded by the fan-out width cap + the P6 token budget). Off by default — see docs/PARALLEL_MULTIAGENT_GROUNDWORK.md.",
    },
    "explore.route_wide": {
        "label": "Route wide questions to the explore wave",
        "description": "Let the /ask door send a genuinely BROAD 'landscape' question — characterize / profile / map how X varies across the business — to the multi-cut explore subgraph instead of a single Deep-Analysis investigation. A deterministic detector decides (no model in the routing path); it yields to causal/driver 'why' questions, which stay investigations. Unlocks the already-built explore wave from /ask. Off by default.",
    },
    "report.argument_style": {
        "label": "Argument-style report composition",
        "description": "Compose exported deep-analysis reports the way a human analyst argues (the Genie report study): one exhibit per claim (chart OR a small table, never both), no degenerate exhibits (a 1-bar chart or single-point trend becomes a sentence), key numbers bold inline in the prose instead of stat-tile rows, the Question-Intake machinery out of the body (it stays in the Trust Receipt), and the R15 opportunity number promoted to its own Financial impact section. Deterministic re-composition of the SAME report data — no model. Off by default = byte-identical exports — see docs/REPORT_STYLE_STUDY_2026-07-16.md (R16 P1).",
    },
    "intake.loss_signals": {
        "label": "Loss-signal directive at question intake",
        "description": "When the question carries loss intent ('where are we losing money', leakage, waste) a deterministic scan names the loss signals THIS schema carries — contra-revenue columns (refunds, chargebacks, discounts) and capacity/utilization columns — and directs the intake to frame the metric around them: leakage as a rate of gross per segment, sold-vs-capacity with a benchmark gap, revenue ranking as context only. Also forbids the un-computable verdict: without cost data the report may never conclude 'profitable' or 'no losses'. Found by the 2026-07-16 A/B: a revenue ranking answered 'broadly healthy' over 2.4M CHF of refund leakage and a 1.2M CHF utilization gap. No model in the detector; off by default = byte-identical intake prompt.",
    },
    "chart.exhibit_grammar": {
        "label": "Semantic chart grammar (exhibit spec)",
        "description": "Charts encode meaning the way the Genie reports do (the 2026-07-16 chart-grammar study): the model is no longer OFFERED the combo chart (one measure per exhibit; the renderer's deterministic dual-axis gate is the only door to one), a rate/percent ranking carries a severity color ramp (value → hue, red family for cost-like metrics), cross-section findings gain deterministic reference lines (segment-weighted average; the R15 best-peer benchmark), the peer-benchmark lens draws its peer median, and an entity scatter labels its points by ID. All computed from rows already fetched — no model, no extra query; carried as an additive `exhibit` payload on findings/answers. Off by default = byte-identical charts and prompts.",
    },
    "lens.decision_grade": {
        "label": "Decision-grade output lenses",
        "description": "Two deterministic output moves borrowed from the Genie reports' strongest habits: (1) the opportunity-cost lens — for a weak segment in a dimensional scan, benchmark it against its best material peer and quantify gap × volume as one hedged key number ('closing the gap ≈ N', a ceiling not a forecast); (2) the named-outlier-entity lens — the overview tour surfaces the single entity BY ID that towers over its top-10 peers, with a mini-profile and honest 'potential causes' (data artifact vs real whale) plus the drill SQL to verify. No model in the loop; both compute from rows already fetched (plus one bounded probe per table for the entity lens). Off by default = byte-identical — see docs/DATABRICKS_HAR_CANVAS_BIRTH_STUDY_2026-07-16.md (R15).",
    },
    "starters.library": {
        "label": "Named research-starter playbooks",
        "description": "Surface a library of named, deterministic research playbooks (interesting outlier entities, where are we losing money, data quality scan) plus per-space curated questions from the ontology doc tree as one-click starters on /suggestions. Each starter declares its route up front (deep investigation or the explore landscape wave) and carries a purpose tag on the route receipt — templates, no model in the loop. Off by default: /suggestions stays LLM-generated-only — see docs/DATABRICKS_HAR_CANVAS_BIRTH_STUDY_2026-07-16.md (R13).",
    },
    "ontology.autodoc": {
        "label": "Compile ontology docs as a build artifact",
        "description": "After the ontology is built, project it into a persisted, Merkle-checksummed doc tree (column→table→schema→connection) with per-table analyst questions — understanding compiled once and re-read cheaply, rebuilt incrementally as the schema moves. Deterministic (no model); also available on demand via the `aughor ontology-docs` CLI. When an embedder + Qdrant are available the compiled table docs are ALSO embedded into the knowledge store with FQN provenance (R8a), so retrieval can ground on understanding, not just uploads — best-effort, degrades to the YAML artifact alone. Off by default — see docs/DATABRICKS_HAR_SQLX_AUTODOC_STUDY_2026-07-15.md (R8).",
    },
    "birth.job": {
        "label": "Connection/canvas birth as one observable job",
        "description": "Run the 'understand this data' rite as ONE supervised kernel job at connection creation, upload re-arm, and canvas creation: eager intelligence first (profiles → ontology → doc tree → column config), then the exploration handoff — each step a birth.step event on the event spine, governed by the Curator agent's charter. Off by default: exploration alone kicks off and intelligence stays lazy (built on the first question), exactly as before — see docs/DATABRICKS_HAR_CANVAS_BIRTH_STUDY_2026-07-16.md (R12).",
    },
    "ontology.column_config": {
        "label": "Per-column visibility / sampling / indexing config",
        "description": "A persisted, human-editable per-column config with three flags: visible (render the column into agent prompt schemas at all — hiding prunes noise columns from the context), sample (enumerate the column's values in the schema context), and index (build the offline value index over it). Deterministic defaults come from the profiler — entity dimensions index+sample, dead all-null columns and free-text blobs hide; a human edit always wins and survives schema rebuilds. No model in the loop. Off by default — see docs/DATABRICKS_HAR_CANVAS_BIRTH_STUDY_2026-07-16.md (R11).",
    },
    "ada.parallel_lenses": {
        "label": "Parallel Deep-Analysis lenses",
        "description": "For a cross-sectional Deep-Analysis ('why is X high/low'), run independent investigative lenses (segment/where ∥ mechanism/why) concurrently instead of one bundled scan — a deeper, multi-angle answer at ~flat wall-clock. Multiplies concurrent LLM calls (bounded by the P6 token budget). Off by default — see docs/PARALLEL_MULTIAGENT_GROUNDWORK.md.",
    },
    "ada.parallel_phases": {
        "label": "Parallel Deep-Analysis phases",
        "description": "Run the temporal investigation's middle phases (baseline ∥ decomposition ∥ dimensional) as one concurrent wave instead of a serial chain, keeping the serial tier-routers' early-stop semantics post-hoc (anything the serial path would have skipped is dropped from the report). Behavioral stays sequential — it targets the dimensional dominant finding. Cuts deep-run wall-clock; multiplies concurrent LLM calls (bounded by the P6 token budget). Off by default.",
    },
    "ada.why_where_interaction": {
        "label": "WHY×WHERE interaction lens",
        "description": "After the parallel WHERE and WHY lenses, forward-chain one more query crossing the leading return reason with the highest-impact segment — does the cause concentrate where the metric is worst (→ target that segment) or is it uniform (→ a broad problem)? Turns two independent findings into the actionable link. Adds one LLM-planned query per qualifying run; requires 'Parallel Deep-Analysis lenses'. Off by default.",
    },
    "ada.why_deepen": {
        "label": "Deepen the WHY (benchmark + drill)",
        "description": "After the WHY lens finds the leading return reason, forward-chain two more queries: a PEER BENCHMARK (is the reason's share abnormally high for the subject vs its peers, or a brand-wide baseline?) and a SECOND-LEVEL DRILL (which brands/products concentrate the leading reason — the fix target?). Establishes whether the cause is real and where to act. Adds two LLM-planned queries per qualifying run; requires 'Parallel Deep-Analysis lenses'. Off by default.",
    },
    "ada.parallel_why_lenses": {
        "label": "Parallel WHY-deepening lenses",
        "description": "Run the forward-chained WHY lenses (WHY×WHERE interaction ∥ peer benchmark ∥ reason drill) as one concurrent wave instead of a serial chain. Each depends ONLY on the already-computed WHERE/WHY summaries, never on each other, so the merge is byte-identical (fixed spec order, never completion order) — just faster wall-clock when two or more are enabled. Multiplies concurrent LLM calls (bounded by the P6 token budget); requires 'Parallel Deep-Analysis lenses' + the WHY lenses it parallelizes. Off by default.",
    },
    "preflight.parallel": {
        "label": "Parallel plan-time retrievals",
        "description": "Run the plan_queries pre-flight retrievals (relevant-schema ∥ KB planning patterns ∥ causal context ∥ closed-loop corrections) concurrently instead of one-at-a-time. All four are independent, deterministic, non-LLM lookups, so the result is byte-identical — just less wall-clock (a near-free win, no extra model cost). Off by default.",
    },
    "trust.verify_facade": {
        "label": "Unified trust.verify façade",
        "description": "Route SQL validation through the one Trust-plane façade (aughor/trust) — one Verdict composing the read-only/mutation gate, E1 footguns, preflight repair, and value-domain/fan-out probes — instead of a per-path guard subset. Adds the AST read-only gate to the /query/validate surface (closes SEC-02 there). Off by default while the plane lands (AL-01).",
    },
    "trust.verify_live": {
        "label": "Trust plane on the deep answer path",
        "description": "In the Deep-Analysis executor, route every generated SQL through trust.verify before execute — the AST read-only BLOCK the generation path never ran (defence-in-depth; the connection layer is already fail-closed). A blocked statement returns a blocked result instead of executing. Off by default (AL-01 live migration).",
    },
    "semantic.resolve_live": {
        "label": "Semantic plane resolved at the router",
        "description": "Resolve the Semantic plane (metrics · ontology · profile · KB) once when a deep investigation is seeded and attach the SemanticContext to the run state, so every node reads one consistent context instead of re-consulting ad-hoc. Off by default (AL-05 live migration).",
    },
    "semantic.contract_live": {
        "label": "Unified metric contract (planning)",
        "description": "Render the governed-metric grounding block from the one SemanticContract type (catalog ∪ profile north-star ∪ ontology, deduped by precedence) instead of the parallel CanonicalMetric shape. Byte-identical output today — this repoints the planning path at the single metric contract, the 20-year ontology bet's type unification (REC-U10). Off by default while the migration lands.",
    },
    "capability.pipeline_live": {
        "label": "Capability plane answer path",
        "description": "Enable the end-to-end Capability-plane answer path (/query/capability-answer): a data question runs generate → validate (trust.verify) → execute → interpret through the one CapabilityPipeline template. Off by default (AL-02 live migration).",
    },
    "ada.premise_check": {
        "label": "Premise validation",
        "description": "A 'why is X so high/low' investigation validates the premise (subject vs overall/peers) BEFORE explaining it — questioning the question itself instead of assuming it. Adds one comparison query per qualifying run. Off by default.",
    },
    "ada.causal_drill": {
        "label": "Causal-dimension priority + WHERE→WHY drill",
        "description": "The cross-section scan floats diagnostic dimensions (reason/condition/defect) ahead of the descriptive taxonomy so they survive the query cap, and after localising WHERE it auto-drills event-only dims into the WHY composition lens instead of stopping. Only affects the serial scan path (inert when 'Parallel Deep-Analysis lenses' is on, which lands the same idea in-lens). Off by default.",
    },
    "ada.adversarial_verify": {
        "label": "Adversarial verify decision-changing verdicts",
        "description": "ReFoRCE-style confidence-tiered verification: when a deep analysis lands a DECISION-CHANGING verdict (a premise rejection — 'X is not the problem' — or an abstention — 'within normal variance'), spend ONE extra skeptic LLM call to try to REFUTE it before shipping; a survived refutation caps confidence and records the objection. Fires only on the few high-stakes conclusions, never per finding. Off by default (adds an LLM call to those runs).",
    },
    "ada.adversarial_high_stakes": {
        "label": "Adversarial verify — high-stakes only",
        "description": "The cheaper, materiality-gated tier of adversarial verification: challenge a decision-changing verdict (premise rejection / abstention) with one skeptic LLM call ONLY when it is asserted with HIGH confidence — the costly-if-wrong minority, and the only case where the HIGH→MEDIUM confidence cap can bite. Lets the refuter earn a place on the default path without paying an LLM call on the many MEDIUM/LOW verdicts. Off by default; supersedes 'Adversarial verify decision-changing verdicts' (the full tier) for cost.",
    },
    "ada.pin_canonical_metric": {
        "label": "Pin governed metric at Deep-Analysis intake",
        "description": "When a deep investigation parses a metric the connection already GOVERNS (curated catalog / north-star / verified ontology), pin the intake's formula to the governed one so the cross-section scan decomposes on a stable, canonical definition instead of a run-varying LLM guess (the count-vs-value 'refund rate' class that left the breakdown un-decomposable → 'cause remains unidentified'). Deterministic, fail-open: only replaces the LLM formula when a governed metric matches the label, its SQL is a bare substitutable aggregate, and a dry-run confirms it runs over the metric table. Off by default = byte-identical.",
    },
    "ada.clarify_gate": {
        "label": "Interactive metric-ambiguity clarify (Deep-Analysis)",
        "description": "When a deep investigation finds that a metric's GOVERNED reading and the LLM's parsed reading both run but give materially different numbers (the count-vs-value 'refund rate' class), PAUSE before the scan and ask the user which reading they meant — instead of silently choosing one. The choice binds the metric for the run and is crystallized to the Ambiguity Ledger (source=user), so the same question never re-asks on that connection. Mirrors the plan-gate interrupt/resume. Off by default; asks at most once per run, only on a real divergence.",
    },
    "ada.progress_events": {
        "label": "Live per-dimension Deep-Analysis progress",
        "description": "Stream a per-dimension progress event as each query of a Deep-Analysis scan completes, so a long cross-section/decompose phase reports 'scanning brand (3/6)…' DURING execution instead of a multi-minute silent spinner between phase_complete events. Interleaves a lightweight progress marker into the SSE stream via a best-effort in-process sink (no extra model cost, graph events never dropped). Off by default = byte-identical stream.",
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
        "description": "Make the ground-first resolver (ask.resolve_first) conversation-aware so a follow-up doesn't lose the prior turn's grounding — including across a mode switch. When THIS turn is a follow-up (is_followup) it inherits the previous turn's entity/filter (so 'break that down by platform' keeps the earlier 'womenswear' filter), and the resolver never DEAD-ENDS a follow-up with a terminal 'not present in this data' — an entity implicit from the conversation is left to the already history-aware generator instead of a hard abstention. Only affects follow-ups; a fresh question resolves exactly as before. Requires ask.resolve_first. Off by default = byte-identical.",
    },
    "ask.brief_context": {
        "label": "Ask this briefing — ground the answer in the brief on screen",
        "description": "When a question is asked from the Briefing, prepend the brief the user is LOOKING AT (its verdict, synthesis and cited findings) to the quick-answer prompt, so 'why is that?' and 'break that down' have a referent instead of arriving cold. Read SERVER-SIDE from the same conn:schema cache entry the Briefing rendered — never posted up by the client, so it cannot drift from what is on screen or be spoofed into the prompt. CONTEXT ONLY: it resolves references and pins the entities/time window; every number in the answer still comes from the query that runs. Bounded (verdict + up to 8 cited findings + a capped synthesis) and empty when no brief is cached — no context beats invented context. Off by default = byte-identical.",
    },
    "closed_loop": {
        "label": "Closed-loop corrections",
        "description": "Read captured human corrections/verdicts and trusted queries back into the planner as priors, so a corrected mistake isn't repeated. Off by default until its delta is proven on your data.",
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
        "description": "The semantic filter operator runs on the cheap tier; with this on, a small spread sample of its verdicts is re-judged by the strong 'champion' model and the whole batch is escalated to the champion when they disagree beyond a bar — catching cheap-tier errors at the cost of one extra sample call per filter. Off by default = byte-identical (no validation sample). A label-free quality estimator in the Palimpzest/LOTUS lineage.",
    },
    "federation.remote_join": {
        "label": "Cross-source batched-foreach join",
        "description": "Enable POST /query/cross-source-join — join a result from one connection to a table on another, N+1-free (dedup the join keys, one keyed batch query per key-chunk to the right source, hash-join in memory). The correct-by-construction path for true cross-engine joins (Snowflake↔BigQuery↔Postgres) that DuckDB ATTACH can't reach. Off by default → the route 404s. Stage 1 of the cross-source federated planner.",
    },
    "federation.planner": {
        "label": "Cross-source federated planner",
        "description": "Enable POST /query/federated-answer — answer a natural-language question that spans TWO connections. One LLM call grounds both schemas and emits a structured plan (a grounded sub-query per source + the join keys); the plan is validated deterministically (each sub-query executes and outputs its key) and executed through the batched-foreach engine. Plan-then-execute, guarded, inspectable (the plan is returned). Off by default → the route 404s. Stage 3 of cross-source federation.",
    },
    "capability.contract": {
        "label": "Connector-capability contract",
        "description": "When a generated query FAILS on a native-SQL warehouse (BigQuery/Snowflake/MySQL), name the exact unsupported construct (QUALIFY/ILIKE/SAFE_DIVIDE/DATE_TRUNC/…) in the SQL-repair prompt so the regeneration fixes it precisely instead of another blind dry-run. A deterministic per-dialect capability descriptor + AST check; advisory (enriches the existing repair loop only), no LLM. Off by default = no extra hint. Rec 6 of the external-sources study.",
    },
    "rbac.row_policy": {
        "label": "RBAC row-level policy (row filters in the WHERE)",
        "description": "Compile per-role, per-table row-filters into executed SQL (a deterministic AST rewrite wrapping each policied table as a filtered subquery) so a role physically cannot read rows outside its filter. Double-gated like the rest of RBAC (no-op unless identity AND the org's RBAC_SSO capability are on) AND this flag; fails CLOSED (a policy that can't be applied blocks the query). Enforced at every connector's execution gate (DuckDB/Postgres/warehouse/file/API). Off by default. Rec 7 of the external-sources study.",
    },
    "agents.user_defined": {
        "label": "User-defined agents (domain personas)",
        "description": "Create reusable agents that bind standing INSTRUCTIONS + a set of uploaded DOCUMENTS + a CONNECTION into a persona, then answer as that agent via /ask (agent_id). The agent's instructions lead the prompt, document retrieval is restricted to ITS documents (an agent with none sees none — fail-closed), and its connection binding wins (a conflicting explicit connection is rejected). CRUD under /agents/custom. Off by default — routes 404 and the answer path is byte-identical. Part B Phase 1 (slice 1) of docs/DATABRICKS_OSS_AND_AGENTIC_PLATFORM_STUDY_2026-07-11.md.",
    },
    "obs.mlflow": {
        "label": "MLflow tracing (agent observability)",
        "description": "Send every investigation to a self-hosted MLflow server as one inspectable trace tree — graph nodes as spans, LLM calls via LangChain/OpenAI autolog (with token counts), and each guarded SQL execution as a TOOL span — searchable by tags.investigation_id. Point AUGHOR_MLFLOW_TRACKING_URI at the server (`docker compose --profile obs up -d mlflow` starts one on http://localhost:5001) and install the extra (`uv sync --extra observability`). Engineer-facing observability only — answers, receipts and ledgers are unchanged. Off by default = byte-identical.",
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
# flipping each. Cost-dangerous flags (ai_sql, federation.*, semops.champion_validate) are deliberately
# NOT here: running them automatically would be expensive, so they stay manual.
AUTO_ELIGIBLE: frozenset = frozenset({
    "ada.premise_check", "ada.clarify_gate", "ada.adversarial_high_stakes",
    "join.key_reconciliation", "capability.contract", "semops.guarded_extract",
    # Graduated 2026-07-13 (agentic-platform unification): both are deterministic and fail-open —
    # resolve() degrades to `answerable` when nothing binds; metric pinning requires a governed
    # metric match AND a clean dry-run before it does anything.
    "ask.resolve_first", "ada.pin_canonical_metric",
    # Graduated 2026-07-14: the "interesting facts about this schema" tour is fully
    # deterministic (no LLM), bounded, and fires ONLY on a metric/entity/time-free
    # overview-phrased question — the great default first-look, on by default.
    "ask.overview",
})
# Human description of each capability's deterministic trigger — surfaced in the flags API and (later) as
# the "why" on an activation receipt.
CAPABILITY_TRIGGER: dict = {
    "ada.premise_check": "the question asserts why a metric is high or low",
    "ada.clarify_gate": "candidate readings diverge materially on the metric",
    "ada.adversarial_high_stakes": "a high-confidence verdict would change the decision",
    "join.key_reconciliation": "a join's key value-domains mismatch",
    "capability.contract": "a generated query fails on a native-SQL warehouse",
    "semops.guarded_extract": "a typed-field extraction fails",
    "ask.resolve_first": "the question names an entity or time grain the schema resolves deterministically",
    "ada.pin_canonical_metric": "a governed metric matches the question and its canonical SQL dry-runs clean",
    "ask.overview": "the question asks for a broad overview with no metric, entity, or time window",
}


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


def _override(name: str):
    return Ledger.default().kv_get(_STORE, name, None)


def flag_enabled(name: str) -> bool:
    """The effective value: a runtime override wins; otherwise the env var decides."""
    ov = _override(name)
    if ov is not None:
        return bool(ov)
    return _env_resolved(name)


def flag_state(name: str) -> str:
    """Tri-state view for the Capabilities UI: ``"on"`` | ``"off"`` | ``"auto"``.

    ``"auto"`` means the capability is enabled ONLY because the master Auto-mode elevated this self-gating
    guard (its deterministic trigger decides per run) — an explicit operator On/Off always resolves to
    ``"on"``/``"off"``. A display refinement over ``flag_enabled`` (which is True for both on and auto)."""
    ov = _override(name)
    if ov is not None:
        return "on" if ov else "off"
    raw = os.getenv(FLAG_ENV.get(name, ""))
    if raw is not None:
        return "on" if _env_resolved(name) else "off"
    if FLAG_DEFAULT.get(name, False):
        return "on"
    if name in AUTO_ELIGIBLE and _auto_mode_active():
        return "auto"
    return "off"


def set_flag(name: str, value: bool) -> None:
    """Set a runtime override (wins over the env var until cleared)."""
    Ledger.default().kv_put(_STORE, name, bool(value))


def clear_flag(name: str) -> None:
    """Drop the override so the env var decides again."""
    Ledger.default().kv_put(_STORE, name, None)


def list_flags() -> dict:
    """All registered flags with their effective value + source, for the Settings UI."""
    out = {}
    for name, var in FLAG_ENV.items():
        ov = _override(name)
        meta = FLAG_META.get(name, {})
        out[name] = {
            "value": bool(ov) if ov is not None else _env_resolved(name),
            "state": flag_state(name),
            "override": ov,                       # None (no override) | True | False — the UI's tri-state setting
            "auto_eligible": name in AUTO_ELIGIBLE,
            **({"trigger": CAPABILITY_TRIGGER[name]} if name in CAPABILITY_TRIGGER else {}),
            "source": "runtime" if ov is not None else "env",
            "env_var": var,
            "label": meta.get("label", name),
            "description": meta.get("description", ""),
        }
    return out
