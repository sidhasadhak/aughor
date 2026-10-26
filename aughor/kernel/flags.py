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
    # AUGHOR_ASK_RESUME_STREAM retired 2026-08-28: ask.resume_stream (FL-1b)
    # graduated — mirror + endpoint hardwired, flag and off-path deleted.
    # Receipt on the GRADUATION_QUEUE tombstone below.
    "ask.converse": "AUGHOR_ASK_CONVERSE",
    # "ask.query_objects" (AUGHOR_ASK_QUERY_OBJECTS) was DELETED 2026-10-04 with its tool —
    # kill 8 of the 2027 study (ROADMAP §4.9; §6 item 39(b)). Parked 2026-09-11 on a measured
    # regression (1/14 and 3/12 against raw 14/14 and 12/12) and never reopened; the compiler
    # behind the object pages and `/objects/query` stays. An operator's env var is ignored.
    # AO-2b (2026-10-03): the API spawns, watches and restarts the Slack supervisor.
    "slack.managed_supervisor": "AUGHOR_SLACK_MANAGED_SUPERVISOR",
    # AO-6 (2026-10-03): the agents' testing centre — drafted questions, the nightly run.
    "agents.testing_centre": "AUGHOR_AGENTS_TESTING_CENTRE",
    # AO-7 (2026-10-03): one closed learning loop per custom agent.
    "agents.learning_loop": "AUGHOR_AGENTS_LEARNING_LOOP",
    # Arc TC-1 (ROADMAP §3.59, the incorporation study of 2026-10-24). ON: every receipt a custom agent produced
    # and every chat turn it answered carry the agent's `config_rev` as `rev` beside its id and name — the revision of the
    # configuration the answer ran under — and the doors that change an agent's configuration (PATCH and restore) refuse
    # with 409, naming both revisions, when the caller sends the `expected_rev` it read and the agent has moved since.
    # OFF: a receipt names the agent by id and name, a turn carries no stamp, and `expected_rev` is ignored, as before.
    "agents.revision_on_answers": "AUGHOR_AGENTS_REVISION_ON_ANSWERS",
    "explore.route_wide": "AUGHOR_EXPLORE_ROUTE_WIDE",
    # "framing.choice_confidence" (AUGHOR_FRAMING_CHOICE_CONFIDENCE) was DELETED 2026-10-04 —
    # kill 6 of the 2027 study (ROADMAP §4.9): its grid was blocked on a corpus that never
    # existed, and CP-2's receipt (a model right 61% of the time at a stated confidence of
    # about 1.0) is the evidence its run would have produced. The second response model went
    # with it (`agent/framing.py`). An operator's env var is ignored.
    "semops.banded_cascade": "AUGHOR_SEMOPS_BANDED_CASCADE",
    "semops.jev_cheap_tier": "AUGHOR_SEMOPS_JEV_CHEAP_TIER",
    "judgment.shadow_treatment": "AUGHOR_JUDGMENT_SHADOW_TREATMENT",
    "grounding.full_schema_first": "AUGHOR_GROUNDING_FULL_SCHEMA_FIRST",
    "briefing.by_period": "AUGHOR_BRIEFING_BY_PERIOD",
    "briefing.ranges": "AUGHOR_BRIEFING_RANGES",
    # P1 of the canvas-output study (docs/CANVAS_OUTPUT_STUDY_2026-10-14.md), 2026-10-14. ON gives the
    # analyst a `conclude` tool: its answer ends with a headline, prose and the results it cites, and
    # the canvas draws each cited result once. OFF → the answer's first sentence is cut as the headline
    # and every result is drawn, byte-identical.
    "analyst.conclude": "AUGHOR_ANALYST_CONCLUDE",
    # Arc CT-4 (ROADMAP §3.50). ON adds a Dashboards tab to the Data Canvas: the canvas's own cards,
    # arranged by a kept spec — tabs, sections, cards shown by a condition. No model call: the
    # tab draws what was approved. OFF → the Data Canvas has its three tabs and the dashboard's
    # routes answer 404, exactly as before.
    "dashboard.composed": "AUGHOR_DASHBOARD_COMPOSED",
    # Arc OC-0 (ROADMAP §3.56). ON: once a day the ontology census — what every built scope declares, what the
    # data verified of it, and what leans on it — is journaled as `ontology.census`, so a later wave reads its
    # before and after from the journal. OFF: nothing is read or written; GET /ontology/census still reads live.
    "ontology.census": "AUGHOR_ONTOLOGY_CENSUS",
    "actions.outbox": "AUGHOR_ACTIONS_OUTBOX",
    "ontology.builder_doors": "AUGHOR_ONTOLOGY_BUILDER_DOORS",
    "ontology.security": "AUGHOR_ONTOLOGY_SECURITY",
    # Arc ED, ED-1 (ROADMAP §3.58). ON (with ontology.security): a connection's door applies the released ontology's row
    # policies and sensitive properties to every statement a request runs — narrowed to the reader's objects, a masked
    # property refused. OFF: only the object doors apply them, and every statement reads as before.
    "ontology.security_sql": "AUGHOR_ONTOLOGY_SECURITY_SQL",
    # Arc ED, ED-2 (ROADMAP §3.58). ON: GET /ledger/v1/principals/service/me answers for a presented service principal, so the MCP
    # server lets an HTTP caller in as itself — each call made as it, its tools listed by its own grant. OFF: the route
    # says it is off and every HTTP client shares the server's token, as before.
    "mcp.caller_principals": "AUGHOR_MCP_CALLER_PRINCIPALS",
    # Arc ED, ED-2. ON: a service principal's grant — areas, entities, declared actions, connections — narrows what the
    # agent policy allows it on every request, and its contract is cut to it. OFF: the policy alone holds it.
    "security.principal_scopes": "AUGHOR_SECURITY_PRINCIPAL_SCOPES",
    # Arc ED, ED-3 (ROADMAP §3.58). ON: an automation's expectations step measures a table read-only and records each
    # verdict in the quality plane, which answers, the MCP table-health tool and the Briefing already read. OFF: the step
    # is skipped and says so; the plane reads "not checked" as before.
    "quality.expectations": "AUGHOR_QUALITY_EXPECTATIONS",
    # Arc ED, ED-4 (ROADMAP §3.58; the user, 2026-10-24: readers see the last published version). ON: a keep on a
    # dashboard is a draft, and an App's readers read the version last published until its owner publishes again.
    # OFF: readers read every version the moment it is kept, as before.
    "dashboard.app_versions": "AUGHOR_DASHBOARD_APP_VERSIONS",
    # Arc ED, ED-5 (ROADMAP §3.58; the user, 2026-10-24: "Impacts are the one store"). ON: what one promise does to
    # another is read from the declared impacts only — the alert summary words them, and the model's proposed causes
    # are neither asked for nor kept. OFF: the causal-graph files are read and written, as before.
    "ontology.impacts_only": "AUGHOR_ONTOLOGY_IMPACTS_ONLY",
    # Arc ED, ED-6 (ROADMAP §3.58). ON: every object door's answer says how complete its read is — complete, truncated
    # at the connection's cap, withheld by a row policy or a masked property, or refused — and how long it took; the
    # contract describes it. OFF: each door answers as before.
    "objects.completeness": "AUGHOR_OBJECTS_COMPLETENESS",
    # Arc FA, FA-1 (ROADMAP §3.60). ON: the published declarations — segments, computed properties, processes, rules,
    # impacts, actions and links — become `declaration` nodes of the connection graph, so the graph search, the read-back
    # and the knowledge door find them, withheld wherever their entity's tables are; publishing a release rebuilds the
    # graph. OFF: the graph is projected without them, byte-identical, and a publish leaves it as it was.
    "graph.declarations": "AUGHOR_GRAPH_DECLARATIONS",
    # Arc FA, FA-1. ON: POST /objects/find looks for an object by its title across the served entities, capped and
    # saying how many entities it searched and why it skipped each other one; ⌘K shows what it found. OFF: the door
    # answers 404 and ⌘K searches exactly what it did.
    "objects.find": "AUGHOR_OBJECTS_FIND",
    # Arc FA, FA-1. ON: when the embedder cannot embed a question and the vector store is up, the documents are ranked
    # by their words (BM25) instead, each hit marked matched by words, and every caller says so. OFF: a failed embed
    # makes the document search unavailable, as before.
    "knowledge.hybrid_documents": "AUGHOR_KNOWLEDGE_HYBRID_DOCUMENTS",
    # Arc OC-1 (ROADMAP §3.56). ON: every save and withdrawal of an ontology declaration is also kept as a version
    # (lifecycle kind `ontology_declaration`), and a withdrawal something depends on is refused with a 409 naming it.
    # OFF: the declaration store reads and writes exactly as before; the history and dependents doors still answer.
    "ontology.history": "AUGHOR_ONTOLOGY_HISTORY",
    # Arc OC-2 (ROADMAP §3.56). ON: a change to the ontology waits in a draft and reaches the agent, the Briefing,
    # metrics and automations only when a person publishes it as a release; claims pin the release they were computed
    # under, and a release that changes a definition's meaning restates them. OFF: a declaration is served the
    # moment it is saved, exactly as before.
    "ontology.release": "AUGHOR_ONTOLOGY_RELEASE",
    # Arc OC-3 (ROADMAP §3.56). ON: an approved metric a person keyed to an entity is read by the object door as its
    # whole statement over any set of that entity's objects, and the question frame may resolve to it. OFF: the
    # object door and the frame read exactly as before; the key is still kept and counted.
    "ontology.keyed_metrics": "AUGHOR_ONTOLOGY_KEYED_METRICS",
    # Arc OC-4 (ROADMAP §3.56). ON: a dashboard may hold pieces bound to the ontology — a process board, an objects table
    # over an entity or a segment, an object detail that follows the table, and a button that runs a declared action —
    # and the object door resolves each promise's overdue segment (`overdue_<noun>`). OFF: the dashboard vocabulary
    # refuses those pieces and the compiler resolves exactly the names it did; POST /objects/list still lists.
    "ontology.dashboard_pieces": "AUGHOR_ONTOLOGY_DASHBOARD_PIECES",
    # The dashboard started from an object (2026-10-10, design-mockups/cockpit-from-object.html). ON: a dashboard may hold
    # a filter column over an entity's categories, figures and a chart of its objects, every piece narrowed by the
    # reader's own filters; and a person may start a dashboard from an object, its pieces proposed from what the object
    # holds. OFF: the dashboard vocabulary refuses those three pieces and nothing is proposed.
    "ontology.object_dashboards": "AUGHOR_ONTOLOGY_OBJECT_DASHBOARDS",
    # ROADMAP §6 item 53 (2026-10-25, the look study): what an entity is used by, on its own page. ON: the entity
    # panel's Overview reads one door that composes the dependents index (Arc OC-1), every dashboard whose pieces read
    # the entity, and how many audited statements named its tables in each of the last twelve months. OFF: the door
    # says it is off and the panel shows what it showed — metrics and actions.
    "ontology.entity_usage": "AUGHOR_ONTOLOGY_ENTITY_USAGE",
    # Arc AP-1 (ROADMAP §3.57, docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md). ON: a dashboard opens to be read, and Edit
    # shows it between its layout and the setup of the piece chosen — sizes one grade at a time on a section's grid, and
    # every piece set up there, never typed as a spec. OFF: a dashboard is arranged by its six sizes and Arrange, the
    # server refuses a section on the grid, and the writer of a dashboard is told nothing about the grid.
    "dashboard.builder": "AUGHOR_DASHBOARD_BUILDER",
    # Arc AP-2 and AP-3 (ROADMAP §3.57). ON: a dashboard may name sets and values its pieces read, a table may name what a
    # click chooses and ticks collect, a figure may switch a list, and action buttons run declared actions on what a
    # reader chose or ticked, on a set, or with what they fill in. OFF: the server refuses a spec that says any of it,
    # and the builder offers none of it.
    "dashboard.wiring": "AUGHOR_DASHBOARD_WIRING",
    "dashboard.app_pieces": "AUGHOR_DASHBOARD_APP_PIECES",
    "dashboard.shapes": "AUGHOR_DASHBOARD_SHAPES",
    # Arc AP-7 (ROADMAP §3.57). ON: a card on a dashboard may read a person's own SQL — one table, several, another schema —
    # shown as a table, a figure or a chart set up as they choose, each run stopped after the connection's time limit.
    # OFF: the builder offers no query of your own, the doors answer 404, and every card runs as it always did.
    "dashboard.queries": "AUGHOR_DASHBOARD_QUERIES",
    # Arc AP-8 (ROADMAP §3.57). ON: a dashboard's value may come from the reader on the page, a set's count or the object a
    # reader chose; a set compares any value; a query of your own reads one as a bound parameter. OFF: a value is the
    # author's and only days reach a set, as before; the server refuses a spec that says more.
    "dashboard.variables": "AUGHOR_DASHBOARD_VARIABLES",
    # PENDING 54 (2026-10-23, design-mockups/dashboard-questions.html). ON: a dashboard may hold a Question — asked by
    # the agent the Data Canvas uses, on a rhythm (daily, weekly, monthly) or only when a person asks, its answers kept
    # and shown as the Data Canvas shows one; opening the dashboard never asks. OFF: the vocabulary refuses a Question
    # and the question routes answer 404.
    "dashboard.questions": "AUGHOR_DASHBOARD_QUESTIONS",
    # PENDING 57 (2026-10-24, docs/DECISION_LOOP_STUDY_2026-10-24.md, D-1 to D-3). ON: a decision is booked in full where
    # it is made (Home's Decide cites its finding and may state an expectation; "Not worth it" books not acting; a
    # recommendation keeps its report's other actions as alternatives and marks what was recommended), every decision
    # that expected something is reviewed on its date, and an outcome is scored against what would have happened anyway
    # (a comparison group for a segment of a metric that adds up; "cannot tell" where the metric's own history band
    # misses one way). OFF: decisions are booked, reviewed and scored as before.
    "record.decision_loop": "AUGHOR_RECORD_DECISION_LOOP",
    # The decision-framework study §3.2 (the user's call, 2026-10-27: email reopened for ARRIVALS only). ON: each
    # decision has an address on the install's inbound domain; a mail a provider posts to `POST /doors/email` with the
    # inbound secret becomes an approval (a named approver, verified), a dissent, or evidence. OFF: the door answers 404
    # and a decision shows no address. The platform never sends a mail either way.
    "arrivals.email": "AUGHOR_ARRIVALS_EMAIL",
    # The decision-framework study §3.2 (the user's call, 2026-10-27). ON: a person names one Google file on a decision
    # and its comments are read onto it as later evidence through their own Google grant. OFF: the door answers 404.
    "arrivals.google_comments": "AUGHOR_ARRIVALS_GOOGLE_COMMENTS",
    # Arc TC, TC-2 (ROADMAP §3.59). ON: every edit's history row, every action-audit row and every action's ledger entry
    # names the run it was made through (a question asked, an automation, a monitor, an agent's job) and its trace, and
    # an object's changes door reads them oldest first with each run's metered cost. OFF: they record who
    # made them, as before, and the changes door answers 404.
    "actions.run_attribution": "AUGHOR_ACTIONS_RUN_ATTRIBUTION",
    # Arc TC, TC-4 (ROADMAP §3.59). ON: the first check back within its limit after an alert writes one *recovered*
    # alert naming the alert it closes, when, and the value that came back; the alert lists and the Monitors page read
    # that alert as closed; a check says "within its limit" apart from "suppressed by its grace period"; and a recovery
    # ends the grace period, so the next alert opens a new one. A recovery is recorded and listed in alert summaries,
    # never sent as an alert. OFF: an alert stays open until a person acknowledges it, and a quiet check says "no alert"
    # whichever it was.
    "monitors.recovery": "AUGHOR_MONITORS_RECOVERY",
    # Arc TC, TC-3 (ROADMAP §3.59, 2026-10-26). ON: every save of an automation or a monitor keeps the definition it
    # replaces as a numbered version in the ledger (superseded, never deleted) with who saved it and when; every
    # recorded run keeps beside its row the version it ran under and its trigger as received (the payload capped at
    # 16 KB, the cap said); a past run replays as a dry run of its own version against its kept trigger. OFF: a save
    # replaces the definition, runs keep neither, and the version and replay doors answer 404.
    "automations.versions": "AUGHOR_AUTOMATIONS_VERSIONS",
    # Arc TC, TC-5 (ROADMAP §3.59). ON: each automation and monitor on the hub map says how often its runs failed over a
    # window (seven days unless asked), counted at the run store: "no runs" where none ran, never 0%, and "not permitted"
    # where the reader may not see its runs, never left off. OFF: the map carries no failure rate.
    "hub.failure_rate": "AUGHOR_HUB_FAILURE_RATE",
    # Arc TC, TC-5. ON: GET /obs/logs searches the lines the journal kept for every run over the last thirty days — words,
    # level, the kind of run — newest first from a cursor, saying how many runs it searched and how old its oldest line is.
    # OFF: the route answers 404 and a run's lines are read one trace at a time (`/traces/{id}/logs`).
    "obs.log_search": "AUGHOR_OBS_LOG_SEARCH",
    # Arc TC, TC-5 (§6 item 4, "a reason recorded"). ON: the governance feed takes since, until and an opaque cursor and
    # exports as CSV or JSON lines; reading a run's payload and exporting the ledger need a reason, refused by name without
    # one, and each such read is journaled once as `access.justified`. OFF: the feed reads its newest thousand, and a
    # payload read records who read it but not why.
    "govern.justifications": "AUGHOR_GOVERN_JUSTIFICATIONS",
    "grounding.data_profiles": "AUGHOR_GROUNDING_DATA_PROFILES",
    "answers.recheck": "AUGHOR_ANSWERS_RECHECK",
    # Phase 7 of the 2027 study (§Q, §W). ON: the install's aggregate priors — pack records, play base
    # rates, normal ranges for share metrics, method backtests, never a connection id or a claim's text —
    # may LEAVE the install through POST /ledger/v1/aggregates/export. OFF (the default; the user's
    # call): the export door refuses and says so; GET /ledger/v1/aggregates still reads it locally.
    "aggregates.share": "AUGHOR_AGGREGATES_SHARE",
    "ontology.explore_on_connect": "AUGHOR_ONTOLOGY_EXPLORE_ON_CONNECT",
    "chat.buttons_reach_agent": "AUGHOR_CHAT_BUTTONS_REACH_AGENT",
    # "ada.adversarial_verify" (AUGHOR_ADA_ADVERSARIAL) was DELETED 2026-07-31 (flag
    # strategy §4G): the always-challenge tier was superseded by the materiality-gated
    # auto tier below, had no constituency, and a deleted flag is the only disposition
    # that actually shrinks the registry. One-off audits can reproduce it by asking the
    # question directly; the refuter itself (run_refutation) is unchanged.
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
    # "capabilities.auto" (AUGHOR_CAPABILITIES_AUTO) was DELETED 2026-08-04 (flag endgame
    # Wave 3): it was a master switch over the ten AUTO_ELIGIBLE guards, and those are
    # unconditional now, so it governed nothing. See the AUTO_ELIGIBLE tombstone.
    # "explorer.continuous" (AUGHOR_EXPLORER_CONTINUOUS) turned ON and was DELETED
    # 2026-08-06 (flag endgame Wave 4, user-approved 2026-08-01): the continuous tick
    # always runs on an always-on process — spend is governed by the per-connection
    # decision in explorer/continuous.py (governance + AUTO_EXPLORATION gates, the
    # staleness window, the per-run exploration budget), which is where a cost control
    # belongs; a boolean over a governed loop was a second, blunter budget. Under
    # VERCEL the loop does not start at all (api.py) — a warm serverless instance is
    # not a clock, and a spawned exploration would die with it.
    # "automations.adopt_legacy" (AUGHOR_AUTOMATIONS_ADOPT_LEGACY) turned ON and was
    # DELETED 2026-08-06 (flag endgame Wave 4, user-approved 2026-08-01): monitors and
    # brief subscriptions run through the ONE automation engine — the legacy per-object
    # APScheduler cron paths were deleted in the same change, so there is nothing left
    # for the flag to stand down. The L4 equivalence receipt (65364174a172, 9/9 stable
    # ×3: alerts byte-for-byte, anti-flap and no-double-fire held) is what made the
    # flip safe; adoption_active() survives as the single consult point, hardwired True.
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
    # The LAST three `ada.*` aliases (causal_drill, why_deepen, why_where_interaction)
    # left 2026-08-06 with their targets — flag endgame Wave 5 hardwired all three.
    # The map stays declared (empty) because `_canonical` is still the resolution
    # seam any future rename must pass through.
    # 2026-10-23 — dashboards were renamed Dashboards (PENDING 54; the user: "rename dashboards entirely as Dashboards -
    # externally and internally"). Every old name keeps resolving: an operator's override row, a script, a call site.
    "cockpit.composed": "dashboard.composed",
    "cockpit.builder": "dashboard.builder",
    "cockpit.wiring": "dashboard.wiring",
    "cockpit.app_pieces": "dashboard.app_pieces",
    "cockpit.shapes": "dashboard.shapes",
    "cockpit.queries": "dashboard.queries",
    "cockpit.variables": "dashboard.variables",
    "ontology.cockpit_pieces": "ontology.dashboard_pieces",
    "ontology.object_cockpits": "ontology.object_dashboards",
}

#: Retired env var → the flag it now feeds. Consulted only when the current flag's own
#: env var is unset, so an operator who has already migrated is never second-guessed.
RETIRED_ENV: dict[str, str] = {
    # Wave W: `AUGHOR_ADA_*` → `AUGHOR_DEEP_ANALYSIS_*`. An operator's existing .env keeps
    # opting in. (The three `ada.*` flags whose env var never said ADA — PREMISE_CHECK,
    # CAUSAL_DRILL, CLARIFY_GATE — kept their variable and need no entry.)
    # The three AUGHOR_ADA_PARALLEL_* entries left 2026-08-06 with their targets
    # (flag endgame Wave 6), and the last two (WHY_DEEPEN, WHY_WHERE_INTERACTION)
    # left the same day with Wave 5 — their flags are permanent behaviour now.
    # 2026-10-23 — `AUGHOR_COCKPIT_*` → `AUGHOR_DASHBOARD_*`: an operator's .env (and the restart script's) keeps working.
    "AUGHOR_COCKPIT_COMPOSED": "dashboard.composed",
    "AUGHOR_COCKPIT_BUILDER": "dashboard.builder",
    "AUGHOR_COCKPIT_WIRING": "dashboard.wiring",
    "AUGHOR_COCKPIT_APP_PIECES": "dashboard.app_pieces",
    "AUGHOR_COCKPIT_SHAPES": "dashboard.shapes",
    "AUGHOR_COCKPIT_QUERIES": "dashboard.queries",
    "AUGHOR_COCKPIT_VARIABLES": "dashboard.variables",
    "AUGHOR_ONTOLOGY_COCKPIT_PIECES": "ontology.dashboard_pieces",
    "AUGHOR_ONTOLOGY_OBJECT_COCKPITS": "ontology.object_dashboards",
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
    # NO LONGER EMPTY — "ask.converse" entered 2026-09-16 (SP-14, §6 item 22(d), the
    # user's "Graduate as-is" with SP-M's numbers on the table). It takes this
    # disposition rather than deletion because its off-path is ALIVE: the deterministic
    # quick body is still what an ineligible turn runs, so the flag remains an operator
    # kill switch while fresh installs get authoring out of the box.
    # Arc OC graduated 2026-10-10 (§3.56, the user's call: "those with receipts met"). Each off-path is ALIVE and
    # byte-identical, so each is a graduation with a kill switch (its env var = 0), not a deletion; each entry is the
    # receipt that graduated it and the falsifier that turns it back off. `ontology.security` stays queued until
    # sign-in, `ontology.census` until seven daily readings are read.
    "ontology.history": "OC-1, live on theLook 2026-10-09: a declaration read back as four versions with what changed "
                        "and who, as-of answered both ways; the withdrawal refused over a dependent stands on the "
                        "scratch receipt (nothing on theLook depends on one). Falsifier: what *late* meant on a past "
                        "day cannot be answered from it",
    "ontology.release": "OC-2, live on theLook 2026-10-09: draft isolation, a SAFE change published as release 2, the "
                        "promise moved 2 → 3 days classed MEANING with the published one unchanged, discard; replayed "
                        "over the live history, no change that moved a consumer classed SAFE. Falsifier: one past "
                        "change that broke a consumer classed SAFE or MEANING",
    "ontology.dashboard_pieces": "OC-4, live on theLook 2026-10-09: the Late dispatch board's open-and-overdue count "
                               "(25,051) opened a table of exactly that many; an object flagged from the dashboard showed "
                               "in the table, the detail and its page. Falsifier: the census does not move in the "
                               "weeks after (armed: read on 2026-11-07)",
    "actions.outbox": "OC-6, live 2026-10-10: a delivered call checked, a no-answer call reconciled by the action's "
                      "check and never sent twice, a refused call queued and delivered on its retry, a guard-refused "
                      "one waiting under Sends for a person. Falsifier: a send left `unknown` after reconciliation "
                      "that a person cannot resolve from the screen",
    "ontology.builder_doors": "OC-8, live on theLook 2026-10-10: a program outside the platform launched the MCP "
                              "server, read 24,872 overdue objects through `list_objects` and proposed Open a "
                              "case through `propose_open_case`; the proposal waited in the Actions inbox and nothing "
                              "ran. Falsifier: a contract a program cannot act on without reading the platform's code",
    "ask.converse": "SP-14 (2026-09-16): 26/26 staged drafts honest across SP-M's two "
                    "recordings; 81% of real asks behaved correctly on the richer "
                    "fixture; the residual is the step-budget knob, accepted as-is.",
    # Same shape as ask.converse — the off-path (the sampled cascade) is ALIVE, so this is
    # a graduation with a kill switch (AUGHOR_SEMOPS_BANDED_CASCADE=0), not a deletion.
    "semops.banded_cascade": "JD-3 (2026-09-21, the user's flip on the receipts): banded "
                             "+2.4/+3.6 points over sampled on both recorded setups (95% "
                             "CIs excluding zero), a third the champion calls, and after "
                             "the seam slim ~0.92x sampled's total prompt tokens "
                             "(docs/JEV_LIVE_RECEIPT_2026-09-21.md; "
                             "evals/semops_band_decision.json).",
    # The four below entered 2026-09-24 on the user's call ("Four flags - turn them on..
    # Explorer default-on") with NO eval receipt: each was built and checked on the samples
    # warehouse without a model, and none has been measured live. Every off-path is ALIVE,
    # so each is a graduation with a kill switch (its env var = 0), not a deletion; the
    # falsifier each carried as an EXPERIMENT is still the condition that turns it off.
    "briefing.by_period": "The user's call (2026-09-24), no eval receipt: period briefs, and "
                          "subscriptions that send them monthly or yearly, are on for every "
                          "install. Kill: a reader given the weekly brief and the standing "
                          "brief for the same week cannot name a move only the weekly one "
                          "carries (ROADMAP §3.27).",
    "answers.recheck": "The user's call (2026-09-24), no eval receipt: the daily re-check of "
                       "chat answers from the last 14 days runs, and a 5%+ move is sent "
                       "through the departure gate. Kill: a month on a real connection with "
                       "no correction acted on and the corrections muted (ROADMAP §3.28).",
    "ontology.explore_on_connect": "The user's call (2026-09-24), taken over the explorer's "
                                   "unrun paid quality re-check (its one live run fused two "
                                   "groups): a new scope runs the business explorer once. "
                                   "Proposals stay PROPOSED until a person confirms. Kill: "
                                   "people withdraw most of what it proposes (ROADMAP §3.31).",
    "chat.buttons_reach_agent": "The user's call (2026-09-24), no eval receipt: Quick and "
                                "Agent reach /ask at quick and deep depth, ~20k tokens a "
                                "turn. Kill: shadow-labelled turns (CP-1) judge the agent's "
                                "answers no better than /chat's and /investigate's "
                                "(ROADMAP §3.33).",
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

# Human-facing copy for Settings → System. Three layers, each for one reader:
#   label   — what it is, a few words;
#   summary — what the person gets, always visible: two sentences at most, 20 words each;
#   facts   — what it costs and touches, drawn as chips: model · free · schedule · sends ·
#             warehouse · needs · private · route;
#   description — the rest, behind "Details": plain sentences, what Off means last.
# No route, arc or wave id, ROADMAP section, function name or decision date in any of them:
# that history lives in the comments and dispositions above and below, where engineers read
# it. tests/unit/test_flag_copy.py holds the line (house style, PLATFORM text-density pilot).
FLAG_META = {
    "aggregates.share": {
        "label": "Share summary statistics with other installs",
        "summary": "Allows exporting summary statistics, like how often each pack's claims held here. "
                   "Names, ids and raw values never leave.",
        "facts": [{"kind": "sends", "text": "Data leaves this install"}],
        "description": "The export holds pack success rates, learned play success rates, normal ranges "
                       "for share metrics and method test results. A check refuses any export with a "
                       "connection id, claim text, name or absolute metric value. Off: export is refused "
                       "and says so, and the statistics can still be read here.",
    },
    "agents.testing_centre": {
        "label": "Test custom agents every night",
        "summary": "Drafts test questions for each custom agent from its approved metrics. "
                   "A person checks each one with SQL, then it runs every night.",
        "facts": [{"kind": "schedule", "text": "Nightly"},
                  {"kind": "model", "text": "1 call per draft batch"},
                  {"kind": "model", "text": "1 call per test run"}],
        "description": "Draft questions is on the agent's Quality tab and asks for up to six. The model "
                       "never writes the answer. Each night the tab shows which checked questions now "
                       "pass or fail. Off: you write test questions by hand and run them on a click.",
    },
    "agents.learning_loop": {
        "label": "Let custom agents learn from reviews",
        "summary": "When a reviewer corrects an agent's answer, the agent sees that correction next time. "
                   "Nothing a model writes is saved as fact.",
        "facts": [{"kind": "model", "text": "Re-tests after every 5 reviews"}],
        "description": "The agent keeps its last three corrections. An accepted answer becomes a test "
                       "question for a person to check with SQL. The Quality tab shows what the agent "
                       "learned and its pass rate before and after. Off: reviews are recorded and the "
                       "agent does not change.",
    },
    "agents.revision_on_answers": {
        "label": "Name the agent's revision on its answers",
        "summary": "Each answer a custom agent gives names the revision of its setup that gave it. "
                   "A save made against an older revision is refused.",
        "facts": [{"kind": "free", "text": "No model calls"},
                  {"kind": "private", "text": "Changes only custom agents"}],
        "description": "A revision changes when the agent's instructions, data, documents, packs or allowed actions "
                       "change; a rename does not. It is kept on the answer's receipt and on its chat turn. A save "
                       "that says which revision it read is refused if the agent changed since. Off: answers name "
                       "the agent only, and every save is taken.",
    },
    "slack.managed_supervisor": {
        "label": "Start the Slack bot automatically",
        "summary": "Aughor starts the Slack bot when it boots and restarts it if it stops. "
                   "No terminal needed.",
        "facts": [{"kind": "needs", "text": "Needs Node.js"},
                  {"kind": "free", "text": "No model calls"}],
        "description": "Integrations → Slack shows whether the bot is running, with a Restart button. "
                       "The installer adds what the bot needs when this is on. Off: start the bot by "
                       "hand from a terminal.",
    },
    "grounding.data_profiles": {
        "label": "Show the SQL writer what the data holds",
        "summary": "Adds a short data profile to the quick answer prompt: row counts, date ranges, "
                   "common values and null rates.",
        "facts": [{"kind": "free", "text": "No extra queries"},
                  {"kind": "model", "text": "Slightly longer prompts"}],
        "description": "Profiles come from the cache, so no question waits for profiling. The profile "
                       "stays under 2,400 characters and names any table it leaves out. Off: the prompt "
                       "holds the schema only.",
    },
    "chat.buttons_reach_agent": {
        "label": "Send chat buttons to the conversation agent",
        "summary": "The Quick and Agent buttons go to the conversation agent, which can look up "
                   "objects in the ontology.",
        "facts": [{"kind": "model", "text": "About 20k tokens a turn"}],
        "description": "Quick runs the agent at quick depth and Agent runs it at deep depth. Off: the "
                       "two buttons use the older direct paths.",
    },
    "ontology.explore_on_connect": {
        "label": "Propose business terms for a new connection",
        "summary": "When you add a connection, Aughor proposes its entities, links, processes "
                   "and rules. Nothing is used until a person confirms it.",
        "facts": [{"kind": "model", "text": "1 model call per connection"}],
        "description": "This is the same as Explore on the Ontology tab. Each proposal is checked "
                       "against the data first. A connection already explored is skipped, so a restart "
                       "costs nothing. Off: a new connection gets no business terms until someone "
                       "presses Explore.",
    },
    "answers.recheck": {
        "label": "Tell people when their answer changes",
        "summary": "Aughor re-runs the answers from the last 14 days. If a number changes "
                   "by 5% or more, it tells the person who asked.",
        "facts": [{"kind": "schedule", "text": "Daily"},
                  {"kind": "warehouse", "text": "Queries your warehouse"},
                  {"kind": "sends", "text": "Replies in Slack and the web"}],
        "description": "The notice gives the old number, the new one, and the reason: rows that "
                       "arrived late, or a restatement. A Slack reply passes the same checks as any "
                       "other message. Off: nothing is run again or sent.",
    },
    "ontology.dashboard_pieces": {
        "label": "Build dashboards from the ontology",
        "summary": "Adds dashboard pieces that read the ontology: a process board, an objects table, "
                   "an object detail and an action button.",
        "facts": [{"kind": "free", "text": "No model calls"}],
        "description": "The process board shows each stage and how often each promise is broken. The "
                       "table can list the objects past a promise. An action that needs approval is "
                       "proposed, not run. A piece whose source is gone says so. Off: these pieces "
                       "cannot be added.",
    },
    "ontology.object_dashboards": {
        "label": "Start a dashboard from an object",
        "summary": "Pick an object and get a dashboard of its filters, figures, a daily chart and its "
                   "objects. A click on a filter narrows every piece.",
        "facts": [{"kind": "free", "text": "No model calls"},
                  {"kind": "warehouse", "text": "Queries your warehouse"}],
        "description": "The pieces are proposed from what the object holds, and you tick the ones you "
                       "want. Filters are each reader's own and never change the dashboard. Saved cards "
                       "beside them say they are not filtered. Off: these pieces cannot be added.",
    },
    "ontology.entity_usage": {
        "label": "What uses an entity",
        "summary": "An entity's page lists the dashboards, automations, processes and rules that use it. "
                   "It also counts the queries that read its tables, by month.",
        "facts": [{"kind": "free", "text": "No model calls"},
                  {"kind": "warehouse", "text": "Reads the query log only"}],
        "description": "Each use says how it depends, so you know what a change would touch. The monthly count "
                       "comes from the platform's own log of statements run, never from your warehouse. "
                       "Off: the page lists its metrics and actions, as before.",
    },
    "dashboard.wiring": {
        "label": "Wire a dashboard's pieces and actions",
        "summary": "Pieces read named sets, and a row chosen in one is read by the others. Buttons run actions on "
                   "the chosen or ticked rows.",
        "facts": [{"kind": "free", "text": "No model calls"},
                  {"kind": "warehouse", "text": "Queries your warehouse"}],
        "description": "A set is a named group of objects, such as the ones waiting past a promise. A button runs a "
                       "declared action, with its own checks and approvals, once per chosen or ticked row. Off: a "
                       "dashboard's pieces read only their own entity.",
    },
    "dashboard.app_pieces": {
        "label": "Split dashboards into sections and add more pieces",
        "summary": "A section splits into columns, rows or tabs, and an empty one offers a piece. The picker "
                   "places every piece by hand.",
        "facts": [{"kind": "free", "text": "No model calls"},
                  {"kind": "private", "text": "Changes only your own dashboards"}],
        "description": "A section holds pieces on its twelve columns, or is split into sections of its own. Sections "
                       "side by side take widths one column at a time. An empty section offers a piece or a split, and a "
                       "reader is drawn nothing there. Off: a dashboard's sections hold pieces only.",
    },
    "dashboard.shapes": {
        "label": "Start a dashboard from a shape",
        "summary": "Starting from an object offers the shapes its ontology fits, and says why. A queue, a map, one "
                   "object, a timeline or an overview.",
        "facts": [{"kind": "free", "text": "No model calls"},
                  {"kind": "private", "text": "Changes only your own dashboards"}],
        "description": "A queue fits what waits past a promise with actions on it. A map fits a latitude and a "
                       "longitude, and a timeline two moments on each object. One object fits a name and several kinds "
                       "of objects linking to it. One to three are offered, the best first, each with a sentence of why "
                       "from the data. Off: every object starts one way.",
    },
    "dashboard.queries": {
        "label": "Your own query on a dashboard",
        "summary": "Write SQL over one table, several or another schema. Show it as a table, a figure or a chart "
                   "set up as you choose.",
        "facts": [{"kind": "free", "text": "No model calls"},
                  {"kind": "private", "text": "Changes only your own dashboards"}],
        "description": "Choose what runs along the bottom and in what buckets, what is summed, and what splits it — "
                       "stacked, side by side or as shares. Your query runs read-only and stops after the connection's "
                       "time limit. Off: a card is drawn by the shape of its result.",
    },
    "dashboard.variables": {
        "label": "Variables on a dashboard",
        "summary": "A value may come from the reader, a set's count or the object chosen. Sets and your own queries read it.",
        "facts": [{"kind": "free", "text": "No model calls"},
                  {"kind": "private", "text": "Changes only your own dashboards"}],
        "description": "A reader changes a value on the page, kept in their browser and never in the dashboard. A set "
                       "compares any value, and a query of your own reads one as a bound parameter, never pasted in. "
                       "Off: a value is set once by its author.",
    },
    "arrivals.google_comments": {
        "label": "Comments on a Google file, read onto a decision",
        "summary": "A person names one Sheet, Slides deck or Doc on a decision, and its comments are kept there as "
                   "evidence.",
        "facts": [{"kind": "free", "text": "No model calls"},
                  {"kind": "private", "text": "Reads only the file named"},
                  {"kind": "route", "text": "Needs the Google Drive comments card"}],
        "description": "Each comment is kept in its author's name, with the cell, slide or text it points at. "
                       "Reading the file again adds only what is new. No other file is listed or read. Off: the "
                       "door is closed.",
    },
    "arrivals.email": {
        "label": "Decisions by email, inbound only",
        "summary": "Each decision has an address. A mail to it is kept as evidence, a named approver's approval, or "
                   "a dissent.",
        "facts": [{"kind": "free", "text": "No model calls"},
                  {"kind": "private", "text": "Never sends a mail"},
                  {"kind": "route", "text": "Needs an inbound domain and secret"}],
        "description": "A mail provider posts each mail sent to a decision's address. An approval counts only from an "
                       "approver the decision names, with the sender verified; anything else is kept as evidence and "
                       "says why. Nothing reads a mailbox. Off: decisions have no address.",
    },
    "record.decision_loop": {
        "label": "Decisions reviewed honestly",
        "summary": "A decision keeps its evidence, options and expectation, and is reviewed on its date against what "
                   "would have happened anyway.",
        "facts": [{"kind": "free", "text": "No model calls"},
                  {"kind": "warehouse", "text": "Reads each due metric once"},
                  {"kind": "schedule", "text": "Checks hourly for due reviews"}],
        "description": "Deciding on a finding cites it and may say what you expect; setting one aside records the choice "
                       "not to act. On its review date a decision is measured over the thirty days after it, against "
                       "its group or its own past. Where that past itself drifts, it says it cannot tell. Off: "
                       "decisions are kept and reviewed as before.",
    },
    "actions.run_attribution": {
        "label": "Which run made each change",
        "summary": "Every edit and action on an object records the run that made it. An object's changes say who "
                   "changed it, through which run, at what cost.",
        "facts": [{"kind": "free", "text": "No model calls"},
                  {"kind": "route", "text": "Adds an object's changes"}],
        "description": "An edit or action made inside a question asked, an automation, a monitor or an agent's work "
                       "keeps that run and its trace. One made by a person outside any run says so. An object's "
                       "changes list every edit and action on it, oldest first, with the run's model cost when it was "
                       "metered. Off: changes record who made them, as before.",
    },
    "monitors.recovery": {
        "label": "Alerts that close when a metric recovers",
        "summary": "The first check back within its limit after an alert closes that alert. A check also says "
                   "whether its grace period held an alert back.",
        "facts": [{"kind": "free", "text": "No model calls"},
                  {"kind": "private", "text": "A recovery is never sent alone"}],
        "description": "The recovery names the alert it closes, when it fired and the value that came back. A second "
                       "quiet check writes nothing more, and the next alert after a recovery opens a new one. A "
                       "recovery is shown here and in alert summaries, never sent as an alert. Off: an alert stays "
                       "open until someone acknowledges it.",
    },
    "automations.versions": {
        "label": "Versions and replays for automations",
        "summary": "Each save of an automation or a monitor keeps the one before it as a version. Each run "
                   "names its version and keeps what started it.",
        "facts": [{"kind": "free", "text": "No model calls"},
                  {"kind": "private", "text": "Nothing is deleted"}],
        "description": "A version says who saved it and when. A run keeps what started it, up to 16 KB, and says "
                       "when it kept less. A past run can be replayed: its own version walks what started it, and "
                       "nothing is sent, run or asked of a model. Off: a save replaces the definition, and a run "
                       "keeps neither.",
    },
    "hub.failure_rate": {
        "label": "Failure rate on the hub map",
        "summary": "Each automation and monitor says how often its runs failed over the last week. One that did not "
                   "run says no runs.",
        "facts": [{"kind": "free", "text": "No model calls"},
                  {"kind": "private", "text": "Says when you may not see"}],
        "description": "A run failed when it broke, or when one of its steps failed. A node with no runs in the window "
                       "says no runs, never 0%. One whose runs you may not see says not permitted. Off: the map "
                       "shows no failure rate.",
    },
    "obs.log_search": {
        "label": "Search logs across runs",
        "summary": "Search the lines every run wrote over the last thirty days. It says how many runs it searched.",
        "facts": [{"kind": "free", "text": "No model calls"},
                  {"kind": "private", "text": "For people who manage the organisation"}],
        "description": "Words match a line as it was kept. You may narrow by level, error, warning or info, and by the "
                       "kind of run. The newest lines come first, a page at a time. It says how old the oldest line "
                       "searched is, since the log may keep fewer days. Off: a run's lines are read one run at a time.",
    },
    "govern.justifications": {
        "label": "A reason to read a run's payload",
        "summary": "Reading what a run was sent and said, or exporting the ledger, asks for a reason. The governance "
                   "feed pages back by date.",
        "facts": [{"kind": "free", "text": "No model calls"},
                  {"kind": "private", "text": "Refusals say why"}],
        "description": "Without a reason the read is refused, and says what is missing. Each read is recorded once with "
                       "who read it, whose run it was and the reason. The governance feed takes a first and last date, "
                       "pages past its newest thousand and exports as a file. Off: a payload read records who read it, "
                       "not why.",
    },
    "dashboard.questions": {
        "label": "Questions on a dashboard",
        "summary": "A question the agent answers on a rhythm, weekly by default. Each answer shows its figures, "
                   "summary and why.",
        "facts": [{"kind": "model", "text": "A full run per answer"},
                  {"kind": "schedule", "text": "Weekly by default; never on open"},
                  {"kind": "private", "text": "Changes only your own dashboards"}],
        "description": "Each answer re-asks the agent for the last complete period against the one before; opening "
                       "the dashboard shows the answers already kept and never asks. Off: a dashboard holds no question.",
    },
    "dashboard.builder": {
        "label": "Build dashboards in place",
        "summary": "A dashboard opens to be read, and Edit shows it between its outline and the setup of what you "
                   "pick. Every size moves one step at a time.",
        "facts": [{"kind": "free", "text": "No model calls"},
                  {"kind": "private", "text": "Changes only your own dashboards"}],
        "description": "A table's columns and sort, a figure's calculation and a chart's measure and split are "
                       "chosen in the setup, never typed. Each change is kept as a version you can go back to. "
                       "Off: a dashboard is arranged by its six sizes and Arrange.",
    },
    "ontology.keyed_metrics": {
        "label": "Compute approved metrics for any segment",
        "summary": "Link a metric to the entity it measures. Then its approved definition is used "
                   "for any segment of that entity.",
        "facts": [{"kind": "free", "text": "No model calls"},
                  {"kind": "route", "text": "Changes what answers compute"}],
        "description": "Link a metric in the Semantic Layer. A segment, a rule, or a filter through a "
                       "link then reads the approved definition. Off: a metric is computed only as "
                       "written.",
    },
    "ontology.release": {
        "label": "Publish ontology changes as releases",
        "summary": "Ontology changes wait in a draft until a person publishes them. Until then, "
                   "everything keeps reading the last release.",
        "facts": [{"kind": "free", "text": "No model calls"}],
        "description": "Each change is rated: breaks something, changes a meaning, worth a look, or safe. "
                       "It lists the automations, claims and cards it touches. A change that would "
                       "break something is refused. When a meaning changes, claims made under the old "
                       "one say so. Off: a change applies as soon as it is saved.",
    },
    "ontology.history": {
        "label": "Keep ontology history",
        "summary": "Keeps every version of each entity, link, process, rule and action, with who "
                   "changed it and when. Blocks a removal that something depends on.",
        "facts": [{"kind": "free", "text": "No model calls"}],
        "description": "You can read what a promise said on any past day. A refused removal names each "
                       "automation, process, rule or action that depends on it. Off: a change replaces "
                       "the old version, and nothing is refused.",
    },
    "ontology.census": {
        "label": "Count the ontology once a day",
        "summary": "Records what every ontology declares, what the data confirmed, and what "
                   "depends on it.",
        "facts": [{"kind": "schedule", "text": "Daily"},
                  {"kind": "free", "text": "No model calls or queries"}],
        "description": "It counts entities, links, processes, promises, rules, segments and actions, and "
                       "the automations and claims that use them. It reads saved ontologies only. Off: "
                       "nothing is recorded, and a count is still available on request.",
    },
    "actions.outbox": {
        "label": "Send action calls through an outbox",
        "summary": "Calls a declared action makes to other systems are queued and retried by a worker. "
                   "A call that landed is never sent twice.",
        "facts": [{"kind": "sends", "text": "Calls other systems"},
                  {"kind": "free", "text": "No model calls"}],
        "description": "A failed call is retried by why it failed; a refusal is never retried. A call with "
                       "no answer is checked with the action's verification read before any resend. An "
                       "undeliverable call waits under Actions → Sends for a person. An action may also "
                       "require one call to succeed before its edits are written. Off: calls go out once, "
                       "inline, as before.",
    },
    "ontology.builder_doors": {
        "label": "Let outside programs read the ontology",
        "summary": "Outside programs can read your objects and their types, and propose an action for "
                   "a person to approve. Nothing runs from outside.",
        "facts": [{"kind": "free", "text": "No model calls"},
                  {"kind": "route", "text": "Also offered over MCP"}],
        "description": "Programs read a versioned contract: a schema per object and per declared action, "
                       "also as TypeScript types. They can list objects or a segment. A proposed action "
                       "waits for a person and never runs from there. Off: an outside program is told "
                       "these doors are off.",
    },
    "ontology.security": {
        "label": "Limit who sees which objects and properties",
        "summary": "Each reader sees only the objects their groups may see. Sensitive properties are "
                   "masked for everyone else.",
        "facts": [{"kind": "free", "text": "No model calls"},
                  {"kind": "private", "text": "Readers are told what is hidden"}],
        "description": "A row policy names a group and the conditions its objects meet. A sensitive "
                       "property names the groups that may read it; others see it empty, with the reason, "
                       "and it cannot shape an answer. An agent acting for a person reads only what both "
                       "may. It applies to dashboards, object pages and outside programs. Off: every reader "
                       "sees every object and property.",
    },
    "mcp.caller_principals": {
        "label": "Outside programs connect as themselves",
        "summary": "A program can connect to the MCP server with its own service principal. Each call then runs "
                   "as that program, not as the server.",
        "facts": [{"kind": "free", "text": "No model calls"},
                  {"kind": "needs", "text": "Needs a minted principal"}],
        "description": "Over HTTP, a program presents its principal's name and key instead of the server's shared "
                       "token. The server checks them with the platform, lists only the tools that program may "
                       "use, and makes every call as it. Off: every HTTP client shares the server's token and "
                       "acts as the server.",
    },
    "quality.expectations": {
        "label": "Measure what tables must meet",
        "summary": "An automation can measure a table's expectations and record each result as its health. "
                   "Answers about the table then say when one is not met.",
        "facts": [{"kind": "free", "text": "No model calls"},
                  {"kind": "warehouse", "text": "Queries the warehouse when run"},
                  {"kind": "schedule", "text": "Runs on its automation's schedule"}],
        "description": "An expectation says what a table's data must meet: a column never empty, a key never "
                       "repeated, the newest row recent enough. Each is counted read-only, never copying rows. "
                       "One that cannot be measured is said, not counted as failing. Off: the step is skipped, "
                       "and table health reads not checked.",
    },
    "objects.completeness": {
        "label": "Every object read says how complete it is",
        "summary": "Each object read says whether it is complete, cut short, narrowed for you, or refused. It also "
                   "says how long it took.",
        "facts": [{"kind": "free", "text": "No model calls"},
                  {"kind": "private", "text": "Says what is withheld from you"}],
        "description": "A read can stop at the connection's limit of rows, and then it says there are more. A row "
                       "policy or a masked property is named. Outside programs read the same field, described in "
                       "their contract. Off: a cut read can look complete.",
    },
    "graph.declarations": {
        "label": "Search what the ontology declares",
        "summary": "Published segments, processes, rules, impacts, actions and links can be found by search. "
                   "Answers see them beside the tables they are about.",
        "facts": [{"kind": "free", "text": "No model calls"},
                  {"kind": "private", "text": "Withheld with their tables"}],
        "description": "Each published declaration is added to the connection's graph with its name, its "
                       "description and its entity. Only what a release published is read, never a draft. A "
                       "declaration over a table you may not see is withheld with it, and counted. Publishing "
                       "rebuilds the graph. Off: search finds tables, metrics, terms and findings only.",
    },
    "objects.find": {
        "label": "Find an object by its name",
        "summary": "The command bar finds an object by the name it goes by, whatever its entity. It says how many "
                   "entities it searched.",
        "facts": [{"kind": "free", "text": "No model calls"},
                  {"kind": "warehouse", "text": "Queries the warehouse as you type"},
                  {"kind": "private", "text": "Reads only what you may see"}],
        "description": "Each entity whose objects are named by a text property is searched for the words typed, a "
                       "few objects each and up to twelve entities. An entity it did not search is listed with why: "
                       "no name to match, a masked name, or the cap. Row policies apply. Off: the command bar finds "
                       "pages, runs and tables only.",
    },
    "knowledge.hybrid_documents": {
        "label": "Search documents by words when meaning is down",
        "summary": "When the embedding model is unavailable, the documents are still searched by their words. "
                   "Each result says it matched by words only.",
        "facts": [{"kind": "free", "text": "No model calls"},
                  {"kind": "needs", "text": "Needs the vector store up"}],
        "description": "A document search embeds the question to match by meaning. When that fails and the store "
                       "holding the documents answers, each passage you may read is ranked by the words it shares "
                       "with the question. Answers and the chat say the match was by words. Off: the search says "
                       "it could not run.",
    },
    "ontology.impacts_only": {
        "label": "Read what bears on what from impacts only",
        "summary": "The impacts a person declared are the one record of what one promise does to another. "
                   "Summaries word them as measured.",
        "facts": [{"kind": "free", "text": "No model calls"},
                  {"kind": "private", "text": "Nothing is deleted"}],
        "description": "An alert summary names each impact that holds, in the words of how it was shown. It also "
                       "says how many are declared and do not hold. An analysis no longer proposes causes of its own, and "
                       "none are kept. The old files stay on disk, unread. Off: the proposed causes are kept and read "
                       "as before.",
    },
    "dashboard.app_versions": {
        "label": "Readers see an App's published version",
        "summary": "A change to a published dashboard is a draft until you publish it. Until then its readers keep "
                   "reading the version you last published.",
        "facts": [{"kind": "free", "text": "No model calls"},
                  {"kind": "private", "text": "Readers never see a draft"}],
        "description": "Publishing makes the dashboard as it stands the App its readers read. Each later change is a "
                       "draft, and the dashboard says which version they read. Unpublishing still reaches nobody at "
                       "once. Off: readers read every change the moment it is kept.",
    },
    "security.principal_scopes": {
        "label": "Limit what each outside program may do",
        "summary": "A principal can be limited to some areas, entities and actions. It never gets more than the "
                   "agent policy allows.",
        "facts": [{"kind": "free", "text": "No model calls"},
                  {"kind": "private", "text": "Refusals say why"}],
        "description": "When minting a principal, a person names the areas it may work in, such as reading "
                       "objects. They may also name the entities and actions it may use. A request outside them is "
                       "refused with why, and its contract lists only what it may use. Off: every principal is "
                       "held to the agent policy alone.",
    },
    "ontology.security_sql": {
        "label": "Apply object security to every answer",
        "summary": "Answers, deep analyses and the SQL editor read only the objects the reader may see. "
                   "A masked property cannot be read there either.",
        "facts": [{"kind": "free", "text": "No model calls"},
                  {"kind": "needs", "text": "Needs object security on"},
                  {"kind": "private", "text": "Readers are told what is hidden"}],
        "description": "The row policies and sensitive properties declared on an entity also apply "
                       "where a question runs its own query. A query that would read a masked property is "
                       "refused, with why. Scheduled checks still count every object. Off: only object "
                       "pages, dashboards and outside programs apply them.",
    },
    "dashboard.composed": {
        "label": "A dashboard in each Data Canvas",
        "summary": "Adds a Dashboards tab to the Data Canvas. Arrange its cards in tabs and sections, "
                   "and show a card only when a condition holds.",
        "facts": [{"kind": "free", "text": "No model calls"}],
        "description": "For example, a card can appear only while a watch is over its limit. Every "
                       "change to the layout is kept, so it can be undone. Off: the Data Canvas is "
                       "unchanged.",
    },
    "briefing.ranges": {
        "label": "Briefings for any date range",
        "summary": "One date-range control replaces the Day, Week, Month and Year switch. "
                   "Headline figures come from approved metrics.",
        "facts": [{"kind": "warehouse", "text": "Queries your warehouse"}],
        "description": "Each figure says whether it is final, still settling, or to date. Each metric's "
                       "date column is set by rule, and a person can correct it in the metric editor. "
                       "Off: the Briefing keeps its switch.",
    },
    "analyst.conclude": {
        "label": "Agent answers end with their own structure",
        "summary": "The agent closes an answer with a headline, the answer and the results it cites. "
                   "The canvas draws each cited result once, with its claim.",
        "facts": [{"kind": "free", "text": "No extra model calls"}],
        "description": "A result the answer does not cite stays behind Sources. A headline over one line, "
                       "or an answer carrying a table, is sent back once to be rewritten. Off: the answer's "
                       "first sentence is its headline and every result is drawn.",
    },
    "briefing.by_period": {
        "label": "Briefings by day, week, month and year",
        "summary": "Adds a Briefing for the last complete day, week, month or year. "
                   "A subscription can send it on that schedule.",
        "facts": [{"kind": "model", "text": "Model writes the narrative"},
                  {"kind": "schedule", "text": "Monthly or yearly sends"}],
        "description": "Each headline metric is compared with the period before. The Briefing also "
                       "lists the alerts and findings from that period. Off: only the standing "
                       "Briefing exists, and a period Briefing is refused with the reason.",
    },
    "ask.converse": {
        "label": "Answer through a conversation with tools",
        "summary": "Quick answers and deep analyses run as an agent that uses tools step by step. "
                   "The same checks run inside every tool.",
        "facts": [{"kind": "model", "text": "Model calls per step"}],
        "description": "In a deep analysis, the model picks the next cut after it reads the last one. "
                       "Off: a fixed script answers, as it did before.",
    },
    "explore.route_wide": {
        "label": "Answer broad questions as a survey",
        "summary": "A broad question, like how sales vary across the business, gets many cuts at once. "
                   "A why question still gets a deep analysis.",
        "facts": [{"kind": "free", "text": "No model call to decide"},
                  {"kind": "route", "text": "Changes routing"}],
        "description": "A fixed rule, not a model, decides which questions are broad. It applies to the "
                       "Agent button and to automatic routing. Off: every such question gets one deep "
                       "analysis.",
    },
    "federation.planner": {
        "label": "Answer questions across two connections",
        "summary": "Answers a question that needs data from two connections. A model plans one "
                   "query for each, and how to join them.",
        "facts": [{"kind": "model", "text": "1 planning call per question"},
                  {"kind": "route", "text": "Can route new questions here"}],
        "description": "Each planned query runs as a check before the results are joined. The plan is "
                       "shown with the answer. When on, some new questions are sent here automatically. "
                       "Off: this planner is not used.",
    },
    "semops.banded_cascade": {
        "label": "Send only unsure rows to the strong model",
        "summary": "When a model judges text rows, a cheap model judges each row first. Only the rows "
                   "it is unsure about go to the strong model.",
        "facts": [{"kind": "model", "text": "Fewer strong-model calls"}],
        "description": "This applies to filters over text columns, like reviews or tickets. A row still "
                       "unsure after the strong model is kept and marked for a person. Off: a sample "
                       "decides, and one disagreement re-runs every row on the strong model.",
    },
    "semops.jev_cheap_tier": {
        "label": "Use Jev as the cheap model",
        "summary": "TypeSafe's hosted Jev service judges text rows first. "
                   "Unsure rows still go to your strong model.",
        "facts": [{"kind": "sends", "text": "Row text leaves this install"},
                  {"kind": "needs", "text": "Needs a TypeSafe key"},
                  {"kind": "private", "text": "Personal data is never sent"}],
        "description": "Needs TYPESAFE_API_KEY and AUGHOR_JEV_MODEL. Every call counts against your "
                       "usage caps and is logged. If Jev "
                       "cannot answer, your own cheap model answers. Off: your own cheap model judges "
                       "every row.",
    },
    "judgment.shadow_treatment": {
        "label": "Record how much work each question needed",
        "summary": "After each question, a model notes the smallest answer that would have "
                   "done, from a lookup to a deep analysis. It changes nothing that runs.",
        "facts": [{"kind": "model", "text": "1 model call per question"}],
        "description": "The record sits beside what actually ran, so the two can be compared later. "
                       "It is for measurement only. Off: nothing is recorded and no call is made.",
    },
    "grounding.full_schema_first": {
        "label": "Show the SQL writer every table",
        "summary": "For a small schema, the SQL writer sees every table, not only the ones picked "
                   "for the question.",
        "facts": [{"kind": "model", "text": "Longer prompts"}],
        "description": "It applies only when the whole schema fits the size limit. In two test runs it "
                       "never wrote a worse query, and twice it answered where the shorter schema "
                       "could not. Off: the SQL writer sees only the tables picked for the question.",
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
    # EMPTY since 2026-08-06 (flag endgame Wave 4) — and staying declared so the
    # disposition ratchet keeps proving nothing re-enters the category. History:
    # "ai_sql" left 2026-08-01: DELETED outright (see the FLAG_ENV tombstone).
    # "obs.prompt_capture" left 2026-08-01: DELETED outright (see the FLAG_ENV
    # tombstone) — "bounded-window use only" is now enforced by the window, not by a note.
    # "search.rrf" left 2026-08-01: DELETED outright (see the FLAG_ENV tombstone) —
    # the flag endgame has no "measured worse, kept anyway" state.
    # "automations.adopt_legacy" left 2026-08-06: turned ON and DELETED, its exit
    # condition met exactly as written — the engine soaked, the L4 receipt held, and
    # the legacy schedulers were deleted with the flag (the win was one loop).
    # "explorer.continuous" left 2026-08-06: turned ON and DELETED — its declared
    # gate (ops.metered_monitors) hardwired ON in Wave 2, and the real spend control
    # is the governed per-connection decision, not a process-wide boolean.
}

#: Group D — adds LLM calls (or changes prompts/routing) for a claimed quality gain;
#: the E4 grid is the exit. Each entry names the question that settles it. Pre-check
#: "does the flag change the prompt?" before buying any grid.
EXPERIMENT: dict = {
    # Arc AP-1, 2026-10-10. It changes where a dashboard is changed, so it is watched before it graduates.
    # Arc AP-2 and AP-3, 2026-10-11. It changes what a dashboard can do — an action a reader runs from it — so it is watched
    # before it graduates.
    "dashboard.wiring": "does a wired dashboard become a place work is done — of the wired dashboards, is an action run from "
                      "one at least weekly? Falsifiers (§3.57): a dashboard drawn before the wiring renders differently "
                      "with it on, or a run reaches the executor without its declared criteria — either stops it",
    "dashboard.app_pieces": "does a dashboard built from sections stay read — of the dashboards split into sections, is each "
                          "read as often as one that is not? Falsifiers (§3.57): a dashboard drawn before sections renders "
                          "differently with it on, or one split into sections is read less often in two weeks",
    "dashboard.shapes": "does a dashboard started from a shape get read again — of the dashboards started from an object, is "
                      "each shape's opened on three or more days in its first two weeks more often than one started "
                      "before shapes? Falsifier (§3.57, AP-5): a shape's dashboards are read no more often than today's",
    "dashboard.queries": "do people show their own queries — of the cards made on dashboards in two weeks, is one in five or "
                       "more a query of their own? Falsifier (§3.57, AP-7): fewer than one in five, and the setup is not "
                       "what they needed",
    "dashboard.variables": "do readers change what a dashboard shows — of the dashboards with a value a reader sets, is one in "
                         "five or more changed by a reader within two weeks? Falsifier (§3.57, AP-8): a variable reaches SQL "
                         "other than as a bound parameter — stop",
    "arrivals.google_comments": "do people bring a file's discussion to the decision — of the decisions argued in a "
                                "Google file over six weeks, is one in five or more read here? Falsifier: a file no "
                                "person named is read, or a comment is booked as an approval — stop",
    # The decision-framework study §3.2, 2026-10-27. It lets mail from outside book an approval, so it is watched.
    "arrivals.email": "do approvals arrive where people give them — of the decisions with a named approver over six "
                      "weeks, is one in five or more approved by email? Falsifier: an approval is booked from a "
                      "sender the provider did not verify, or from someone the decision does not name — stop",
    "record.decision_loop": "do decisions reach a verdict — within six weeks, do five or more decisions on live data reach "
                            "their review with an expectation and a verdict other than cannot tell? Falsifier (PENDING 57, "
                            "study §5): a do-nothing decision is credited its metric's trend — stop",
    # Arc TC, TC-2, 2026-10-26. It adds to what every change records, so it is watched before it graduates.
    "actions.run_attribution": "does every change say what made it — of the edits and audited actions recorded in two "
                               "weeks with it on, does each one made inside a run name that run, and is an object's "
                               "changes opened? Falsifier (§3.59, TC-2): an edit made by an automation shows no run "
                               "— stop",
    # Arc TC, TC-4 (ROADMAP §3.59), 2026-10-26. It changes what an open alert means and lets a recovery end the grace
    # period, so it is watched before it graduates.
    "monitors.recovery": "do alerts close on their own — over two weeks on live monitors, is every alert that came back "
                         "within its limit closed by exactly one recovery, and does the open count fall to the alerts "
                         "still out of limit? Falsifiers (set with the wave; §3.59 named none): a monitor writes two "
                         "recoveries for one alert, or a "
                         "monitor flapping across its line writes more than two alerts a day that its grace period used "
                         "to fold — either stops it",
    # Arc TC, TC-3 (ROADMAP §3.59), 2026-10-26. It keeps more of every save and every run, so it is watched before it
    # graduates.
    "automations.versions": "is a past run replayed or an earlier version read — within four weeks, is one in three or "
                            "more of the automations changed in that time opened at a version or a replay? Falsifier "
                            "(§3.59, TC-3): a replay sends a message, runs an action, calls a model or writes a run — "
                            "stop",
    # Arc TC, TC-5 (ROADMAP §3.59), 2026-10-26. No model call; each changes what an operator reads, so each is watched.
    "hub.failure_rate": "does a failure rate change what is fixed — of the automations shown failing over a week, is one in "
                        "three or more edited, paused or turned off within two weeks? Falsifier (§3.59, TC-5): a node with "
                        "no runs, or one the reader may not see, reads as 0% — stop",
    "obs.log_search": "do people find a failure across runs — of the searches made in two weeks, does one in three or more "
                      "open a run from its results? Falsifier (§3.59, TC-5): a search that says it read further back than "
                      "the oldest line it read — stop",
    "govern.justifications": "are reasons written and read — within four weeks, is the reason readable as a reason in nine "
                             "of ten payload reads, and is the feed exported at least once? Falsifier (§3.59, TC-5): a "
                             "payload read or ledger export with no reason recorded beside it — stop",
    "dashboard.questions": "do people keep a question on a dashboard and read its answers — of the questions kept in two "
                           "weeks, is one in three or more opened after its second answer? Falsifier (PENDING 54): the "
                           "answers go unread while their runs are paid for — stop",
    "dashboard.builder": "is the setup where people change a dashboard — of the dashboards started from an object, is one in "
                       "five or more edited within two weeks of starting? Falsifier (§3.57): fewer than one in five, "
                       "and the setup is not where people look",
    # The dashboard started from an object, 2026-10-10. It is a new way to read objects, so it is watched before it
    # graduates.
    "ontology.object_dashboards": "does a dashboard started from an object get read again — opened on three or more "
                                "days in its first two weeks — more often than one started empty or for a "
                                "process? Falsifier: started dashboards are opened no more than the others, and "
                                "the starter and its three pieces go",
    # ROADMAP §6 item 53 (2026-10-25). It is a new section of the entity's page, so it is watched before it graduates.
    "ontology.entity_usage": "does what-uses-it change what a person does — a dependent opened from the entity's page, "
                             "or a withdrawal or a change of a used entity preceded by a read of the section — in its "
                             "first two weeks? Falsifier: the section is never opened before a change and no dependent "
                             "is reached from it, and the door and the section go",
    # Arc OC-3 (ROADMAP §3.56), 2026-10-09. It changes what the question frame hands an analysis, so it is measured
    # before it graduates.
    "ontology.keyed_metrics": "does reading an approved metric by the entity it measures — over a declared segment, "
                              "through the frame — raise how often a question reaches a declared definition, and how "
                              "often the answer computes the approved one? Falsifier (§3.56): if keying raises neither "
                              "framing reach nor the declared-definition hit rate, OC-3 stops at the minimum and the "
                              "flag goes",
    # Arc BR (ROADMAP §3.48). ON: the Briefing reads any date range — Day, Week, Month and Year
    # become presets of one range control — measures APPROVED metrics compiled from their time
    # fields (set automatically, corrected by a person), says whether each figure is final,
    # provisional or to date, and writes each horizon as its own recipe. OFF → the Briefing,
    # its period versions and their subscriptions are exactly §3.27's.
    "aggregates.share": "does an aggregate that leaves — base rates, normal ranges for share metrics, pack records, "
                        "method backtests, never one install's claim — make a second install's priors better than the "
                        "pack's own? Exit: a receiving install's pack claims held more often, or its first Briefing "
                        "arrived sooner, with the aggregate than without; the user decides what may leave before "
                        "any install sends one (the 2027 study §W, phase 7). Falsifier: no receiver measures a gain "
                        "within two installs → the door is removed and aggregates stay local.",
    "briefing.ranges": "does a dated Briefing carry what the standing one cannot? Falsifier "
                       "(§3.48 BR-4): a person given the Day and the Month Briefing for theLook "
                       "beside the standing one cannot name a move only the dated one carries — "
                       "then the recipes ship without prose, or the flag is deleted",
    # P1 of the canvas-output study, 2026-10-14. No extra model call: the conclusion replaces the prose answer.
    "analyst.conclude": "does an answer that names its own headline and exhibits read better than one cut from "
                        "its prose? Measured on the stored theLook answers: 58% of drawn results carried no words, "
                        "46 of 88 bodies tabulated rows a result below drew again, headlines ran to 32 words at p90. "
                        "Falsifier: on the next twenty Agent answers a cited result is drawn twice, a headline runs "
                        "past 16 words, or the reader faces more words than before — then the first-sentence cut "
                        "stays and the flag is deleted",
    # Arc AO-6 (ROADMAP §3.52), 2026-10-03 — one model call per drafted batch, N per nightly run.
    "agents.testing_centre": "do drafted questions become goldens a person certifies, and does a nightly "
                             "diff catch a regression a person would otherwise have met in a channel? "
                             "Falsifier (§3.52): fewer than a third of drafted questions certified "
                             "after a month of use, or no nightly diff ever named a real regression "
                             "→ the drafter is removed; the nightly run stays only if it caught one",
    # Arc AO-7 (ROADMAP §3.52), 2026-10-03 — no new store; the verdict store is the lesson store.
    "agents.learning_loop": "does a per-agent loop move a held-out golden set's pass rate for that "
                            "agent? Falsifier (§3.52): two weeks of real use with the loop on and no "
                            "movement on any agent's suite → the 'corrected before' block is removed, "
                            "not kept; candidates from use stay only if a person certified one",
    # Arc TC-1 (ROADMAP §3.59), 2026-10-26. It changes what a receipt and a stored turn carry, and adds a refusal to two
    # doors, so it is watched before it graduates. No model calls.
    "agents.revision_on_answers": "can a person tell which configuration of an agent gave an answer — for an agent "
                                  "edited while it was answering, does each receipt and stored turn name the revision "
                                  "it ran under, and is a save sent with a stale revision refused? Falsifier (§3.59): "
                                  "an answer names a revision other than the one it ran under, or a save is taken over "
                                  "a revision newer than the one its caller read — stop",
    # PENDING item 19 (ROADMAP §3.38) — the ML review's point 5, its first level: the warehouse's
    # measured data in the SQL writer's context. The context it adds is measured model-free
    # (evals/linker_recall_eval.py reports the recall it rides on; the block's size is pinned);
    # whether answers improve is a paid A/B.
    "grounding.data_profiles": "do answers get more right when the SQL writer is shown the profiler's "
                               "measured values, ranges and null rates for the linked tables? The "
                               "values a filter must match and the magnitude a sum should land in are "
                               "exactly what five head rows cannot show. Falsifier: if a with/without "
                               "run on the golden and ablation sets shows no gain in execution "
                               "accuracy, the block is deleted with the flag",
    # "briefing.by_period", "answers.recheck", "ontology.explore_on_connect" and
    # "chat.buttons_reach_agent" GRADUATED to FLAG_DEFAULT 2026-09-24 (the user's call,
    # no eval receipt): their falsifiers moved with them onto the FLAG_DEFAULT entries.
    # "semops.banded_cascade" GRADUATED to FLAG_DEFAULT 2026-09-21 (the user's flip): its
    # question was answered by measurement — fewer champion calls AND, after the seam slim,
    # fewer total tokens, at higher accuracy. Receipt on the FLAG_DEFAULT entry.
    # JD-5 (ROADMAP §3.20; docs/JEV_LIVE_RECEIPT_2026-09-21.md). ON puts TypeSafe's Jev
    # behind JD-1's seam as the banded cascade's CHEAP tier — a tenant's row text leaves the
    # box, so every bundle rides govern.outbound (cap + EXTERNAL_CALL event), a PII-bearing
    # bundle is withheld whole, and any bundle Jev cannot answer falls back to the house
    # tier (aughor/judgment/jev.py). Needs TYPESAFE_API_KEY and AUGHOR_JEV_MODEL — no model
    # id ships in the product, the operator names it. Group D on the cheap tier only; the
    # champion and every non-banded path are untouched.
    # CP-1 (ROADMAP §3.22). ON classifies every SETTLED ask through the judgment seam and
    # writes the treatment it WOULD have chosen beside what actually ran, as a
    # `treatment_shadow` session event. It routes NOTHING — CP-3 is the first wave in which
    # a treatment changes what runs, and only after CP-2 has weighed these probabilities on
    # the battery. OFF by default and deliberately so: a classification is a MODEL CALL per
    # settled turn, so this spends on every ask from the moment it is switched on. The
    # corpus cannot be backfilled, which is the argument FOR switching it on early; it is
    # the operator's money, which is why it is not on already.
    "judgment.shadow_treatment": "does a typed judgement pick a different treatment from "
                                 "the one the model's tool choice picked? Measured 2026-09-23: "
                                 "`deep_analysis` was chosen 0 times in 60 tool uses, so the "
                                 "interactive quick/deep split is not being made at all. "
                                 "Falsifier: if the shadow treatment agrees with what ran on "
                                 "essentially every ask, there is no decision here to take — "
                                 "record that in §3.22 and stop the arc's second movement.",
    "semops.jev_cheap_tier": "on the LIVE deployment's filters, does Jev as the cheap tier "
                             "hold the live receipt's numbers (jev-solo +2.6 over sampled, "
                             "parity with the LLM cascade, ~2.6x cheaper) at its measured "
                             "band occupancy (~7%)? Falsifier: accuracy below the sampled "
                             "cascade's, or fallback rate so high the house tier is doing "
                             "the work anyway — then turn it off and say so in §3.20.",
    # "framing.choice_confidence" left this set 2026-10-04: DELETED (see the FLAG_ENV
    # tombstone) — its own exit clause was "delete if the number is flat", and CP-2 measured
    # the flatness on the one corpus that exists.
    # Moved here from the graduation queue by batch B's premise check: queued as
    # "invocation-gated route", but `_federation_eligible` ALSO auto-federates fresh
    # /ask auto-depth turns — an LLM-bearing routing change nothing has measured.
    "federation.planner": "does auto-federating fresh /ask turns improve cross-source "
                          "answers enough to pay its planning call? ⚠️ GRID BLOCKED ON "
                          "CORPUS (premise-checked 2026-08-07): the reference suite "
                          "(9c1e13e458ff) is single-source, so an A/B there measures only "
                          "the selector's overhead + false-positive rate, never the "
                          "cross-source benefit — author a cross-source suite first",
    # "plan.program" left this set 2026-08-01: DELETED outright (see the FLAG_ENV
    # tombstone) — the adopt-or-kill question was settled as KILL, not measured.
    # "ask.converse" left this set 2026-09-16: DEFAULT-ON (SP-14, decision 22(d)). The
    # exit evidence was SP-M's recorded set rather than the 10-turn script this entry
    # originally named: 26/26 staged drafts honest across two recordings (zero check
    # failures), 21/26 real asks behaving correctly on the richer fixture, and the one
    # residual class (step-budget deaths) accepted by the user as a cost knob, not a
    # defect ("Graduate as-is"). The flag STAYS — its off-path is not dead code but the
    # ineligible-turn fallback every converse turn still rides — so this is
    # FLAG_DEFAULT, not deletion.
    # "ask.query_objects" left this set 2026-10-04: DELETED with its tool (see the FLAG_ENV
    # tombstone) — "deleting the flag and the tool is the other exit", and the user took it.
    "explore.route_wide": "do landscape questions answer better through the explore wave? "
                          "⚠️ GRID BLOCKED ON CORPUS (premise-checked 2026-08-07): "
                          "is_wide_question fires on 0/102 of the reference suite "
                          "(9c1e13e458ff) — the deterministic detector, run corpus-wide at "
                          "zero LLM cost, so a grid there measures a no-op on every case "
                          "(the exact L3 mistake Guard 1 exists to refuse). Author a "
                          "landscape-question suite first, then grid the fired subset",
    "grounding.full_schema_first": "when the whole (shard-compressed) schema already fits the "
                          "linker's char budget, does sending it unpruned answer better than "
                          "top-k table/column pruning? WrenAI measured yes below ~30k chars "
                          "(complete join paths beat isolated fragments — 2026-08-14 study). "
                          "GRID 1 (2026-08-15, Superstore accuracy suite 32b30c0880f9 on "
                          "8d36d4c2, 24 reference-SQL cases, temp 0, nemotron:free, runs "
                          "a17652d36f72 off / 6427f47e5cb4 on, 24/24 sensitive): "
                          "off 21/24 → on 23/24, ZERO lost — both gains legible in the traced "
                          "SQL (off hallucinated a table by hand on return-rate; off produced "
                          "no SQL at all on sales-per-year). The one shared miss is a data-vs-"
                          "metadata defect (returns grain note), not the flag. GRID 2 (same day, "
                          "after the grain-claim + comparator fixes lifted the suite to "
                          "ceiling; runs a66e0fcda7fc off / 25db5cbee8fd on): off 24/24 → on "
                          "23/24, the one miss a PROVIDER EMPTY-TURN (744ms, no SQL generated) "
                          "— not a schema effect. Across both replicates the whole schema never "
                          "produced a WORSE query and twice produced a correct one where pruning "
                          "produced none — but this suite can no longer separate the arms. "
                          "Exit: a grid on a suite NOT at ceiling (e.g. LuxExperience 914df862, "
                          "27k chars/14 tables) that repeats a net gain ⇒ graduate; a genuine "
                          "loss (a worse QUERY, not a dead turn) ⇒ delete the bypass",
    # "explorer.synthesis_incremental" left this set 2026-08-01: DELETED outright (see
    # the FLAG_ENV tombstone) — its question was settled by the chat-UI liveliness work.
    # "deep_analysis.evidence_stubs" left this set 2026-08-01: DELETED outright (see
    # the FLAG_ENV tombstone) — it dropped rows, the opposite of the evidence direction.
    # EIGHT left this set 2026-08-06 (flag endgame Wave 5, verdict sheet approved
    # 2026-08-01): hardwired ON and DELETED — where cost is bounded and the behaviour
    # is exactly "more intelligence, well-directed", the answer is yes without a grid:
    #   closed_loop (a user who corrects the system and watches it repeat the mistake
    #     is the worst experience we can ship; prompt-only cost) ·
    #   graph.readback (we finally USE what we know; prompt-only; post-validate with
    #     its already-budgeted grid) ·
    #   deep_analysis.why_where_interaction / why_deepen (the depth a deep run is FOR;
    #     three bounded queries per qualifying run) ·
    #   deep_analysis.causal_drill (serial-path parity twin) ·
    #   explorer.manifest_driven (FEWER model calls, reproducible coverage) ·
    #   kinetic.agent_actions (data-gated; a human accepts every proposal) ·
    #   semops.champion_validate (self-checking is direction; one bounded sample call).
    # The two that remain are the two with an UNMEASURED LLM-bearing routing change;
    # their grids are the exit, nothing else.
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
    # Arc FA, FA-1 (ROADMAP §3.60), queued 2026-10-26. No model call in any of the three.
    "graph.declarations": "receipt: on theLook, a published process and segment are found by the graph search and the "
                          "knowledge door by their own words, read back beside their entity, and a publish rebuilds the "
                          "graph. Falsifier: a declaration only in the draft, or over a withheld table, reaching a "
                          "search stops it",
    "objects.find": "receipt: on theLook, ⌘K finds objects of two entities by name, says how many entities it searched "
                    "and why it skipped the rest, and a row policy narrows what a group member finds. Falsifier: a hit "
                    "the reader's row policy withholds, or a skipped entity not said, stops it",
    "knowledge.hybrid_documents": "receipt: with the embedder stopped and the vector store up, a document search answers "
                                  "by words, every hit marked so, the door, the chat tool and the prompt saying it. "
                                  "Falsifier: a words-only hit read as a match by meaning, or a document outside the "
                                  "caller's scope ranked, stops it",
    # Arc ED, ED-6 (ROADMAP §3.58), queued 2026-10-25. No model call.
    "objects.completeness": "receipt: on theLook, an object query over more rows than the connection returns says "
                            "truncated, a group with a row policy reads withheld, and the contract describes the field. "
                            "Falsifier: an object read cut at the cap that says complete stops it",
    # Arc ED, ED-5 (ROADMAP §3.58), queued 2026-10-24. No model call; it trims one field from an analysis's answer.
    "ontology.impacts_only": "receipt: on theLook, a week's alert summary names the measured impacts in their own words "
                             "and says the ones that do not hold; an analysis keeps no proposed cause. Falsifier: an "
                             "alert summary names a cause the impacts store does not hold stops it",
    # Arc ED, ED-4 (ROADMAP §3.58), queued 2026-10-24. No model call.
    "dashboard.app_versions": "receipt: on the live install, an App published to a group is changed twice; a member of "
                              "the group reads the published version until its owner publishes, then the new one. "
                              "Falsifier: a reader reads a version its owner never published stops it",
    # Arc ED, ED-3 (ROADMAP §3.58), queued 2026-10-24. No model call.
    "quality.expectations": "receipt: on theLook, a scheduled step measures one table's expectations, the verdicts reach "
                            "an answer's caveats and the table-health tool, and one it cannot measure is said, not "
                            "counted. Falsifier: a table read as failing because a query could not run stops it",
    # Arc ED, ED-2 (ROADMAP §3.58), queued 2026-10-24. No model call.
    "mcp.caller_principals": "receipt: on the live install, two outside programs connect over HTTP as two principals with "
                             "different grants; each lists its own tools and every call is audited under its own name. "
                             "Falsifier: two principals with different grants see the same tool list — stop",
    "security.principal_scopes": "receipt: a principal granted reading objects of one entity reads it, is refused another "
                                 "with why, and its contract lists only that entity. Falsifier: a request outside the "
                                 "grant that reaches its handler stops it",
    # Arc ED, ED-1 (ROADMAP §3.58), queued 2026-10-24. No model call.
    "ontology.security_sql": "receipt: on a scratch install over theLook, a group with a row policy gets the same count from "
                             "a quick answer as from the object door, and a question that reads a masked property is "
                             "refused, with why. Falsifier: one count that differs between the two doors stops it. It "
                             "needs ontology.security, so live waits for sign-in as that does",
    # Arc OC-7 (ROADMAP §3.56), queued 2026-10-10. No model call.
    "ontology.security": "receipt: on a scratch install, two people open the same dashboard and see different rows and a "
                         "masked property, each told why, and an agent acting for one reads no more than that person does. "
                         "Falsifier: a policy test that passes with enforcement off is testing nothing — the suite "
                         "turns it off and every policy assertion must fail. Live needs sign-in (the organisation "
                         "install); until then it stays off there",
    # Arc OC-0 (ROADMAP §3.56), queued 2026-10-09. No model call, no warehouse query: it graduates on being READ.
    "ontology.census": "receipt: on the live install, seven daily readings in the journal, each equal to "
                       "GET /ontology/census taken the same hour, and OC-1's receipt quoting its before and "
                       "after from them. Falsifier: no Arc OC wave's receipt reads the journal — then the "
                       "census is a document again, and the flag goes",
    # Arc AO-2b (ROADMAP §3.52), queued 2026-10-03. No model call, no prompt: it graduates on
    # the arc's own measure, which is a clock, not a grid.
    "slack.managed_supervisor": "receipt: on a fresh install with the flag on, the API starts the "
                                "supervisor at boot, a bot card reads *listening since …* within a "
                                "minute, a killed child is back within the backoff, and Create agent → "
                                "a Slack answer takes one person, no terminal, under five minutes "
                                "(§3.52's AO-2 measure) on two machines. Falsifier: not under ten "
                                "minutes on a fresh clone → spawn-and-watch is the wrong shape and "
                                "the in-process Socket Mode spike is reopened.",
    # Arc CT-4 (ROADMAP §3.50), queued 2026-09-28. It adds no model call and changes no prompt,
    # so there is no grid to buy: it graduates on being USED.
    "dashboard.composed": "receipt: on theLook, a person opens a Data Canvas's Dashboards tab and sees "
                        "its cards cut to the range they chose, and a card that appears when its "
                        "watch crosses its limit. Falsifier (§3.50, the third): an approved dashboard "
                        "that nobody reopens within a week was not wanted — then the tab goes, "
                        "and the flag with it",
    # EMPTY again as of 2026-08-28: ask.resume_stream (FL-1b, queued 2026-08-28)
    # graduated on its declared receipt, delivered live the same day: a browser soak
    # (85s deep run, tab killed at ~4s, a reloading client reattached via
    # GET /ask/stream/{session_id} — snapshot then tail — and watched the SAME run
    # complete on screen as one turn; wire proof: two 200s on the resume GET, the
    # strict-mode double reconciled by the stable message id), plus the interrupt
    # receipt (stop cancelled the kernel job — `cancelled: true` on the wire, the
    # run's row terminal rather than orphaned 'running', the next resume GET a 204).
    # Graduated ⇒ the mirror and the endpoint are hardwired at their former guard
    # sites (routers/investigations.py) and the flag, its env var and its off-path
    # are deleted.
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


def env_enabled(name: str) -> bool:
    """What the environment alone says of a flag, with its default — the answer `flag_enabled`
    falls back to when no override is set. For a caller whose override store could not be read
    (Arc TC, TC-5: `govern/justifications.required`), so it degrades exactly as an unset override does."""
    return _env_resolved(_canonical(name))


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
            "summary": meta.get("summary", ""),
            "facts": meta.get("facts", []),
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
