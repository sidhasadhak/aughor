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
    # "ask.converse" (AUGHOR_ASK_CONVERSE) — SP-14, quick answers and deep analyses as an agent with tools; a
    # binding that cannot call tools still takes the quick body and the phase script — was made unconditional
    # 2026-10-28: part of the platform (ROADMAP §3.65); its off path is deleted. An operator's env var is ignored.
    # "ask.query_objects" (AUGHOR_ASK_QUERY_OBJECTS) was DELETED 2026-10-04 with its tool —
    # kill 8 of the 2027 study (ROADMAP §4.9; §6 item 39(b)). Parked 2026-09-11 on a measured
    # regression (1/14 and 3/12 against raw 14/14 and 12/12) and never reopened; the compiler
    # behind the object pages and `/objects/query` stays. An operator's env var is ignored.
    # AO-2b (2026-10-03): the API spawns, watches and restarts the Slack supervisor.
    "slack.managed_supervisor": "AUGHOR_SLACK_MANAGED_SUPERVISOR",
    # AO-6 (2026-10-03): the agents' testing centre — drafted questions, the nightly run.
    # "agents.testing_centre" (AUGHOR_AGENTS_TESTING_CENTRE) left 2026-10-28 for the organisation setting `scheduled_model_work` (ROADMAP §3.65,
    # `aughor/orgsettings/allows.py`): an admin's choice, read from AUGHOR_AGENTS_TESTING_CENTRE only while the setting is unset.
    # AO-7 (2026-10-03): one closed learning loop per custom agent.
    # "agents.learning_loop" (AUGHOR_AGENTS_LEARNING_LOOP) left 2026-10-28 for the organisation setting `scheduled_model_work` (ROADMAP §3.65,
    # `aughor/orgsettings/allows.py`): an admin's choice, read from AUGHOR_AGENTS_LEARNING_LOOP only while the setting is unset.
    # "agents.revision_on_answers" (AUGHOR_AGENTS_REVISION_ON_ANSWERS) — Arc TC-1, an agent's revision on its
    # answers and `expected_rev` honoured at its doors — was made unconditional 2026-10-28: part of the platform
    # (ROADMAP §3.65); its off path is deleted. An operator's env var is ignored.
    # "explore.route_wide" (AUGHOR_EXPLORE_ROUTE_WIDE) was DELETED 2026-10-28: the automatic route of a broad question
    # to the explore wave, off and never measured (no broad question in the reference suite) — the flags-into-settings
    # decision (ROADMAP §3.65). A survey is read for depth like any question; the wave stays reachable by its declared
    # path. An operator's env var is ignored.
    # "framing.choice_confidence" (AUGHOR_FRAMING_CHOICE_CONFIDENCE) was DELETED 2026-10-04 —
    # kill 6 of the 2027 study (ROADMAP §4.9): its grid was blocked on a corpus that never
    # existed, and CP-2's receipt (a model right 61% of the time at a stated confidence of
    # about 1.0) is the evidence its run would have produced. The second response model went
    # with it (`agent/framing.py`). An operator's env var is ignored.
    # "semops.banded_cascade" (AUGHOR_SEMOPS_BANDED_CASCADE) — JD-3, only the rows the cheap model is unsure of go
    # to the strong one; the sampled cascade it replaced is deleted — was made unconditional 2026-10-28: part of the
    # platform (ROADMAP §3.65); its off path is deleted. An operator's env var is ignored.
    # "semops.jev_cheap_tier" (AUGHOR_SEMOPS_JEV_CHEAP_TIER) left 2026-10-28 for the organisation setting `outside_row_model` (ROADMAP §3.65,
    # `aughor/orgsettings/allows.py`): an admin's choice, read from AUGHOR_SEMOPS_JEV_CHEAP_TIER only while the setting is unset.
    # "judgment.shadow_treatment" (AUGHOR_JUDGMENT_SHADOW_TREATMENT) was DELETED 2026-10-28: the treatment shadow, a
    # model call after every settled turn for a record nobody yet read — stopped with the flags-into-settings decision
    # (ROADMAP §3.65). Its rows stay readable (`treatment.shadow_corpus`). An operator's env var is ignored.
    # "grounding.full_schema_first" (AUGHOR_GROUNDING_FULL_SCHEMA_FIRST) — a schema that fits the linker's budget
    # shown to the SQL writer whole, kept on its measured record — was made unconditional 2026-10-28: part of the
    # platform (ROADMAP §3.65); its off path is deleted. An operator's env var is ignored.
    # "briefing.by_period" (AUGHOR_BRIEFING_BY_PERIOD) — idea 3, the Briefing for a day, week, month or year — was made
    # unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off path is deleted. An operator's env var
    # is ignored.
    # "briefing.ranges" (AUGHOR_BRIEFING_RANGES) — Arc BR, the Briefing for any date range — was made unconditional
    # 2026-10-28: part of the platform (ROADMAP §3.65); its off path is deleted. An operator's env var is ignored.
    # "analyst.conclude" (AUGHOR_ANALYST_CONCLUDE) — P1 of the canvas-output study, the analyst's `conclude` tool:
    # headline, answer and the results it cites — was made unconditional 2026-10-28: part of the platform (ROADMAP
    # §3.65); its off path is deleted. An operator's env var is ignored.
    # "dashboard.composed" (AUGHOR_DASHBOARD_COMPOSED) — Arc CT-4's dashboards — was made unconditional 2026-10-28:
    # part of the platform (ROADMAP §3.65); its off path is deleted. An operator's env var is ignored.
    # "ontology.census" (AUGHOR_ONTOLOGY_CENSUS) — Arc OC-0, the daily ontology census journaled — was made
    # unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off path is deleted. An operator's env var
    # is ignored.
    # "actions.outbox" (AUGHOR_ACTIONS_OUTBOX) — Arc OC-6, a declared action's calls to other systems queued, retried by a
    # worker and never sent twice — was made unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off path
    # is deleted. An operator's env var is ignored.
    # "ontology.builder_doors" (AUGHOR_ONTOLOGY_BUILDER_DOORS) — Arc OC-8, the contract and doors for outside programs —
    # was made unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off path is deleted. An operator's
    # env var is ignored.
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
    # Arc SH (ROADMAP §3.64), 2026-10-27 — Sheets: tables people make, edit, combine and chat with. Its eight waves were
    # made unconditional 2026-10-28 — part of the platform (ROADMAP §3.65); their off paths are deleted. An operator's
    # env var is ignored:
    # "sheets.core" (AUGHOR_SHEETS_CORE) — SH-1, the sheets, their home and the Sheets connection;
    # "sheets.grid" (AUGHOR_SHEETS_GRID) — SH-2, editing a sheet in place;
    # "sheets.chat" (AUGHOR_SHEETS_CHAT) — SH-4, the chat beside a sheet;
    # "sheets.combine" (AUGHOR_SHEETS_COMBINE) — SH-7, links, totals and a newer file;
    # "sheets.views" (AUGHOR_SHEETS_VIEWS) — SH-3, groups with totals, boards, calendars, rules, views kept to oneself;
    # "sheets.everywhere" (AUGHOR_SHEETS_EVERYWHERE) — SH-6, a dashboard made from a sheet;
    # "sheets.sharing" (AUGHOR_SHEETS_SHARING) — SH-8, a sheet shared with chosen people and groups;
    # "sheets.model_columns" (AUGHOR_SHEETS_MODEL_COLUMNS) — SH-5, a column a model writes.
    # Arc ED, ED-5 (ROADMAP §3.58; the user, 2026-10-24: "Impacts are the one store"). ON: what one promise does to
    # another is read from the declared impacts only — the alert summary words them, and the model's proposed causes
    # are neither asked for nor kept. OFF: the causal-graph files are read and written, as before.
    "ontology.impacts_only": "AUGHOR_ONTOLOGY_IMPACTS_ONLY",
    # Arc ED, ED-6 (ROADMAP §3.58). ON: every object door's answer says how complete its read is — complete, truncated
    # at the connection's cap, withheld by a row policy or a masked property, or refused — and how long it took; the
    # contract describes it. OFF: each door answers as before.
    "objects.completeness": "AUGHOR_OBJECTS_COMPLETENESS",
    # "agents.grounding_read" (AUGHOR_AGENTS_GROUNDING_READ) — Arc FA-7, what an agent would read for a question, at
    # its key door and as the MCP tool `ground_agent` — was made unconditional 2026-10-28: part of the platform
    # (ROADMAP §3.65); its off path is deleted. An operator's env var is ignored.
    # "graph.declarations" (AUGHOR_GRAPH_DECLARATIONS) — Arc FA-1, the published declarations as nodes of the
    # connection graph — was made unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off path is
    # deleted. An operator's env var is ignored.
    # "objects.find" (AUGHOR_OBJECTS_FIND) — Arc FA-1, an object found by its name across entities — was made
    # unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off path is deleted. An operator's env var
    # is ignored.
    # Arc FA, FA-1. ON: when the embedder cannot embed a question and the vector store is up, the documents are ranked
    # by their words (BM25) instead, each hit marked matched by words, and every caller says so. OFF: a failed embed
    # makes the document search unavailable, as before.
    "knowledge.hybrid_documents": "AUGHOR_KNOWLEDGE_HYBRID_DOCUMENTS",
    # "canvas.ask_about_chosen" (AUGHOR_CANVAS_ASK_ABOUT_CHOSEN) — Arc FA-2, asking the Data Canvas about what a
    # dashboard's reader chose — was made unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off
    # path is deleted. An operator's env var is ignored.
    # "ontology.set_segments" (AUGHOR_ONTOLOGY_SET_SEGMENTS) — Arc FA-4, a dashboard set kept as a segment and a rule
    # that counts the last days — was made unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off
    # path is deleted. An operator's env var is ignored.
    # "ontology.history" (AUGHOR_ONTOLOGY_HISTORY) — Arc OC-1, every declaration's versions and a withdrawal refused
    # where something depends on it — was made unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off
    # path is deleted. An operator's env var is ignored.
    # "ontology.release" (AUGHOR_ONTOLOGY_RELEASE) — Arc OC-2, a change waiting in a draft until a person publishes
    # it — was made unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off path is deleted. An
    # operator's env var is ignored.
    # "ontology.keyed_metrics" (AUGHOR_ONTOLOGY_KEYED_METRICS) — Arc OC-3, an approved metric keyed to its entity read
    # as its whole statement — was made unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off path is
    # deleted. An operator's env var is ignored.
    # "ontology.dashboard_pieces" (AUGHOR_ONTOLOGY_DASHBOARD_PIECES) — Arc OC-4, dashboard pieces bound to the
    # ontology — was made unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off path is deleted.
    # An operator's env var is ignored.
    # "ontology.object_dashboards" (AUGHOR_ONTOLOGY_OBJECT_DASHBOARDS) — a dashboard started from an object — was
    # made unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off path is deleted. An operator's
    # env var is ignored.
    # "ontology.entity_usage" (AUGHOR_ONTOLOGY_ENTITY_USAGE) — ROADMAP §6 item 53, what an entity is used by, on its
    # own page — was made unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off path is deleted. An
    # operator's env var is ignored.
    # "ontology.put_back" (AUGHOR_ONTOLOGY_PUT_BACK) — Arc FA-3, an earlier version of a declaration put back into the
    # draft — was made unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off path is deleted. An
    # operator's env var is ignored.
    # "ontology.retiring" (AUGHOR_ONTOLOGY_RETIRING) — Arc FA-3, a declaration marked retiring with a successor and a
    # day — was made unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off path is deleted. An
    # operator's env var is ignored.
    # "dashboard.builder" (AUGHOR_DASHBOARD_BUILDER) — Arc AP-1, a dashboard built in place — was made unconditional
    # 2026-10-28: part of the platform (ROADMAP §3.65); its off path is deleted. An operator's env var is ignored.
    # "dashboard.wiring" (AUGHOR_DASHBOARD_WIRING) — Arc AP-2 and AP-3, a dashboard's sets, choices and action
    # buttons — was made unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off path is deleted. An
    # operator's env var is ignored.
    # "dashboard.app_pieces" (AUGHOR_DASHBOARD_APP_PIECES) — Arc AP-4, sections split into sections and the picker's
    # pieces — was made unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off path is deleted. An
    # operator's env var is ignored.
    # "dashboard.shapes" (AUGHOR_DASHBOARD_SHAPES) — Arc AP-5, shapes in the starter — was made unconditional
    # 2026-10-28: part of the platform (ROADMAP §3.65); its off path is deleted. An operator's env var is ignored.
    # "dashboard.queries" (AUGHOR_DASHBOARD_QUERIES) — Arc AP-7, a query of your own on a dashboard — was made
    # unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off path is deleted. An operator's env var
    # is ignored.
    # "dashboard.variables" (AUGHOR_DASHBOARD_VARIABLES) — Arc AP-8, a dashboard's variables — was made
    # unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off path is deleted. An operator's env var
    # is ignored.
    # "dashboard.questions" (AUGHOR_DASHBOARD_QUESTIONS) — PENDING 54, a Question on a dashboard — was made
    # unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off path is deleted. An operator's env var
    # is ignored.
    # "dashboard.breakdowns" (AUGHOR_DASHBOARD_BREAKDOWNS) — a breakdown piece, the Grist study §10 — was made
    # unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off path is deleted. An operator's env var
    # is ignored.
    # "dashboard.marks" (AUGHOR_DASHBOARD_MARKS) — rows marked by a declared rule, the Grist study §10 — was made
    # unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off path is deleted. An operator's env var
    # is ignored.
    # "record.decision_loop" (AUGHOR_RECORD_DECISION_LOOP) — PENDING 57, D-1 to D-3, a decision booked in full where it is
    # made and reviewed on its date against what would have happened anyway — was made unconditional 2026-10-28: part of
    # the platform (ROADMAP §3.65); its off path is deleted. An operator's env var is ignored.
    # The decision-framework study §3.2 (the user's call, 2026-10-27: email reopened for ARRIVALS only). ON: each
    # decision has an address on the install's inbound domain; a mail a provider posts to `POST /doors/email` with the
    # inbound secret becomes an approval (a named approver, verified), a dissent, or evidence. OFF: the door answers 404
    # and a decision shows no address. The platform never sends a mail either way.
    "arrivals.email": "AUGHOR_ARRIVALS_EMAIL",
    # The decision-framework study §3.2 (the user's call, 2026-10-27). ON: a person names one Google file on a decision
    # and its comments are read onto it as later evidence through their own Google grant. OFF: the door answers 404.
    "arrivals.google_comments": "AUGHOR_ARRIVALS_GOOGLE_COMMENTS",
    # "actions.run_attribution" (AUGHOR_ACTIONS_RUN_ATTRIBUTION) — Arc TC-2, every edit and action naming the run it was
    # made through, and an object's changes door — was made unconditional 2026-10-28: part of the platform (ROADMAP
    # §3.65); its off path is deleted. An operator's env var is ignored.
    # "state.backups" (AUGHOR_STATE_BACKUPS) — Arc SV-2, the API's hourly backups of its own state (`db/backups.py`) — was
    # made unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off path is deleted. An operator's env var
    # is ignored.
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
    # "automations.objects_admitted" (AUGHOR_AUTOMATIONS_OBJECTS_ADMITTED) — Arc FA-5, an automation triggered by the
    # objects a rule or segment newly admits — was made unconditional 2026-10-28: part of the platform (ROADMAP §3.65);
    # its off path is deleted. An operator's env var is ignored.
    # "hub.failure_rate" (AUGHOR_HUB_FAILURE_RATE) — Arc TC-5, each automation's and monitor's failure rate on the hub
    # map — was made unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off path is deleted. An
    # operator's env var is ignored.
    # "obs.log_search" (AUGHOR_OBS_LOG_SEARCH) — Arc TC-5, `GET /obs/logs`, the lines of every run over thirty days
    # searched — was made unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off path is deleted. An
    # operator's env var is ignored.
    # Arc TC, TC-5 (§6 item 4, "a reason recorded"). ON: the governance feed takes since, until and an opaque cursor and
    # exports as CSV or JSON lines; reading a run's payload and exporting the ledger need a reason, refused by name without
    # one, and each such read is journaled once as `access.justified`. OFF: the feed reads its newest thousand, and a
    # payload read records who read it but not why.
    # "govern.justifications" (AUGHOR_GOVERN_JUSTIFICATIONS) left 2026-10-28 for the organisation setting `reason_to_read_runs` (ROADMAP §3.65,
    # `aughor/orgsettings/allows.py`): an admin's choice, read from AUGHOR_GOVERN_JUSTIFICATIONS only while the setting is unset.
    # "grounding.data_profiles" (AUGHOR_GROUNDING_DATA_PROFILES) was DELETED 2026-10-28, with the DATA PROFILE block
    # (`tools/catalog_profiles.py`), by its own falsifier: the first clean with/without run — the two before it never
    # built the block, the golden harness's table link having failed silently since 2026-06-30 — read 0.661 → 0.651
    # over 65 questions × 3 runs on claude-haiku-5-5 (paired t −1.01; 11 better, 17 worse), the block in every "on"
    # prompt (`evals/data_profiles_ab_2026-10-28.json`). An operator's env var is ignored.
    # "answers.recheck" (AUGHOR_ANSWERS_RECHECK) — idea 5, the daily re-check of recent answers and the Briefing
    # recall — was made unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off path is deleted. An
    # operator's env var is ignored.
    # Phase 7 of the 2027 study (§Q, §W). ON: the install's aggregate priors — pack records, play base
    # rates, normal ranges for share metrics, method backtests, never a connection id or a claim's text —
    # may LEAVE the install through POST /ledger/v1/aggregates/export. OFF (the default; the user's
    # call): the export door refuses and says so; GET /ledger/v1/aggregates still reads it locally.
    # "aggregates.share" (AUGHOR_AGGREGATES_SHARE) left 2026-10-28 for the organisation setting `share_aggregates` (ROADMAP §3.65,
    # `aughor/orgsettings/allows.py`): an admin's choice, read from AUGHOR_AGGREGATES_SHARE only while the setting is unset.
    # "ontology.explore_on_connect" (AUGHOR_ONTOLOGY_EXPLORE_ON_CONNECT) — business terms proposed for a new
    # connection — was made unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off path is deleted. An
    # operator's env var is ignored.
    # "chat.buttons_reach_agent" (AUGHOR_CHAT_BUTTONS_REACH_AGENT) — PENDING item 15, the Quick and Agent buttons
    # through `/ask` to the conversation agent — was made unconditional 2026-10-28: part of the platform (ROADMAP
    # §3.65); its off path is deleted. An operator's env var is ignored.
    # "ada.adversarial_verify" (AUGHOR_ADA_ADVERSARIAL) was DELETED 2026-07-31 (flag
    # strategy §4G): the always-challenge tier was superseded by the materiality-gated
    # auto tier below, had no constituency, and a deleted flag is the only disposition
    # that actually shrinks the registry. One-off audits can reproduce it by asking the
    # question directly; the refuter itself (run_refutation) is unchanged.
    # "federation.planner" (AUGHOR_FEDERATION_PLANNER) — Rec 2, questions across connections, served through
    # `/query/federated-answer` and `/query/auto-federated-answer` — was made unconditional 2026-10-28: part of the
    # platform (ROADMAP §3.65); its off path is deleted. An operator's env var is ignored.
    # "packs.installed_versions" (AUGHOR_PACKS_INSTALLED_VERSIONS) — Arc FA-6, a pack's installed version and what it
    # offered, and the upgrade doors — was made unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off
    # path is deleted. An operator's env var is ignored.
    # "packs.dashboard_templates" (AUGHOR_PACKS_DASHBOARD_TEMPLATES) — Arc FA-6, a pack's dashboard templates — was
    # made unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off path is deleted. An operator's
    # env var is ignored.
    # "metrics.figure_gates" (AUGHOR_METRICS_FIGURE_GATES) — Arc MC-0, a metric's figures checked at approval — was
    # made unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off path is deleted. An operator's env
    # var is ignored.
    # "metrics.coverage_map" (AUGHOR_METRICS_COVERAGE_MAP) — Arc MC-1/MC-2, the areas of the business and what each
    # measures — was made unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off path is deleted. An
    # operator's env var is ignored.
    # "metrics.coverage_proposals" (AUGHOR_METRICS_COVERAGE_PROPOSALS) — Arc MC-3/MC-4, recipes and the ontology's
    # derivations proposed by code — was made unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off
    # path is deleted. An operator's env var is ignored.
    # "metrics.coverage_writer" (AUGHOR_METRICS_COVERAGE_WRITER) — Arc MC-5, one model call per uncovered area when a
    # connection is profiled — was made unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off path is
    # deleted. An operator's env var is ignored.
    # "metrics.blind_spot_proposals" (AUGHOR_METRICS_BLIND_SPOT_PROPOSALS) — Arc MC-6, a measure the explorer keeps
    # computing proposed in its area — was made unconditional 2026-10-28: part of the platform (ROADMAP §3.65); its off
    # path is deleted. An operator's env var is ignored.
    # "briefing.metric_cap" (AUGHOR_BRIEFING_METRIC_CAP) — Arc MC-6, the Briefing measuring up to 24 metrics (or the
    # workspace's `briefing_metric_cap`) by area — was made unconditional 2026-10-28: part of the platform (ROADMAP
    # §3.65); its off path is deleted. An operator's env var is ignored.
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
    # 2026-10-23 — cockpits were renamed Dashboards (PENDING 54); the nine `cockpit.*` / `ontology.cockpit_*` aliases left
    # 2026-10-28 with their targets, which were made unconditional (ROADMAP §3.65) — an alias only means something while
    # its target lives.
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
    # 2026-10-23 — `AUGHOR_COCKPIT_*` → `AUGHOR_DASHBOARD_*`; the nine left 2026-10-28 with their targets, which were made
    # unconditional (ROADMAP §3.65).
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
    # EMPTY again 2026-10-28: its eleven entries — ask.converse, semops.banded_cascade, the four of 2026-09-24 and
    # Arc OC's five — moved to ALWAYS_ON with the flags-into-settings decision (ROADMAP §3.65,
    # docs/FLAGS_TO_SETTINGS_2026-10-28.md), and from there, area by area, were made unconditional with their off
    # paths deleted (stage 2; tombstones in FLAG_ENV). Their receipts are in git history and on their ROADMAP sections.
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

#: Part of the platform (the user, 2026-10-28: "not having any feature flags at all.. most of it comes as a
#: default feature like always on and cannot be turned off" — ROADMAP §3.65). On whatever a saved override says,
#: and not offered as a switch: Settings does not list them and the flags door refuses a change. Until its off
#: path is deleted (stage 2, area by area), an operator's env var set to an explicit falsy value still turns one
#: off — the suite runs them that way — and a run-scoped override (tests, eval grids) still wins.
ALWAYS_ON: dict[str, str] = {
    "arrivals.email": "Works once its setup exists (a mail domain and its secret); setting it up is the choice.",
    "arrivals.google_comments": "Works once its setup exists (your Google OAuth client); setting it up is the choice.",
    "knowledge.hybrid_documents": "Works once its setup exists (the vector store running); setting it up is the choice.",
    "slack.managed_supervisor": "Works once its setup exists (Slack configured, and Node.js); setting it up is the choice.",
}

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
    # 2026-10-28: the entries that were on, and the two kept on their record, moved to ALWAYS_ON with the
    # flags-into-settings decision (ROADMAP §3.65); what stays here is still a switch until its own exit.
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
    # "agents.testing_centre" and "agents.learning_loop" left this set 2026-10-28 for the organisation setting
    # `scheduled_model_work` (see their FLAG_ENV tombstones).
    # "grounding.data_profiles" left this set 2026-10-28: DELETED (see the FLAG_ENV tombstone) — its own
    # falsifier, "no gain in execution accuracy ⇒ the block is deleted with the flag", fired on the first run
    # that put the block in the prompt.
    # "briefing.by_period", "answers.recheck", "ontology.explore_on_connect" and
    # "chat.buttons_reach_agent" GRADUATED to FLAG_DEFAULT 2026-09-24 (the user's call,
    # no eval receipt): their falsifiers moved with them onto the FLAG_DEFAULT entries.
    # "semops.banded_cascade" GRADUATED to FLAG_DEFAULT 2026-09-21 (the user's flip): its
    # question was answered by measurement — fewer champion calls AND, after the seam slim,
    # fewer total tokens, at higher accuracy. Receipt on the FLAG_DEFAULT entry.
    # "semops.jev_cheap_tier" left this set 2026-10-28 for the organisation setting `outside_row_model` (see its FLAG_ENV
    # "framing.choice_confidence" left this set 2026-10-04: DELETED (see the FLAG_ENV
    # tombstone) — its own exit clause was "delete if the number is flat", and CP-2 measured
    # the flatness on the one corpus that exists.
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
    # 2026-10-28: the entries that were on, and the two kept on their record, moved to ALWAYS_ON with the
    # flags-into-settings decision (ROADMAP §3.65); what stays here is still a switch until its own exit.
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
    if name in ALWAYS_ON:
        return "always_on"
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
        if FLAG_DEFAULT.get(name, False) or name in ALWAYS_ON:
            return True
        return False
    if FLAG_DEFAULT.get(name, False) or name in ALWAYS_ON:
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
    if name in ALWAYS_ON:       # part of the platform: a saved override is not read (§3.65)
        return _env_resolved(name)
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
    if name in ALWAYS_ON:
        return "on" if _env_resolved(name) else "off"
    ov = _override(name)
    if ov is not None:
        return "on" if ov else "off"
    if _env_present(name):
        return "on" if _env_resolved(name) else "off"
    if FLAG_DEFAULT.get(name, False):
        return "on"
    return "off"


class AlwaysOn(ValueError):
    """A change asked of a flag that is part of the platform now (ROADMAP §3.65) — never a switch."""

    def __init__(self, name: str):
        super().__init__(f"{name} is part of the platform now: always on, not a switch.")
        self.name = name


def set_flag(name: str, value: bool) -> None:
    """Set a runtime override (wins over the env var until cleared).

    Writes under the CURRENT name, and drops any row still held under a name this flag
    was renamed from — otherwise the legacy row would outlive the setting that replaced
    it and resurface the moment the new one is cleared.
    """
    name = _canonical(name)
    if name in ALWAYS_ON:
        raise AlwaysOn(name)
    led = Ledger.default()
    led.kv_put(_STORE, name, bool(value))
    for old in _retired_names(name):
        if led.kv_get(_STORE, old, None) is not None:
            led.kv_put(_STORE, old, None)


def clear_flag(name: str) -> None:
    """Drop the override so the env var decides again — under every name it may be
    stored as, or a retired row would silently keep overriding."""
    name = _canonical(name)
    if name in ALWAYS_ON:
        raise AlwaysOn(name)
    led = Ledger.default()
    led.kv_put(_STORE, name, None)
    for old in _retired_names(name):
        led.kv_put(_STORE, old, None)


def list_flags() -> dict:
    """All registered flags with their effective value + source, for the Settings UI."""
    out = {}
    run = _run_overrides.get() or {}
    for name, var in FLAG_ENV.items():
        ov = None if name in ALWAYS_ON else _override(name)   # an always-on flag reads no saved override
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
