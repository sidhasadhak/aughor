# Vocabulary Unification — one word, one concept (Wave W)

**Date:** 2026-08-01 · **Status:** PLAN (nothing executed)
**Rule:** every concept gets exactly one word, every word names exactly one concept, and the
word is plain language a new reader already knows. Internal codenames, research acronyms and
external product names do not appear in identifiers, UI copy, prompts, or flag metadata.

This plan was built from a four-way code inventory (answer modes · external names · agent
taxonomy · module codenames), not from the docs — the docs themselves are part of the drift.
It subsumes the still-open NOM-01…NOM-12 items from
`docs/architecture-review-2026-07-03/PART-2-uiux-nomenclature-and-layering.md` §3.

---

## 1 · The diagnosis, measured

- **One feature, six names.** The deep answer path is `investigate` (graph mode), `deep`
  (depth), **ADA** (~183 `\bADA\b` + 362 `ada_*` occurrences), "Deep Analysis" (UI/MCP/
  licence), **Analyst** (agent roster), "Agentic" (canvas copy). The quick path is `direct` /
  `quick` / `ask` / "Insight". The word **insight** alone covers ≥7 distinct concepts across
  2,196 occurrences.
- **One screen, three names.** Nav says "Agentic Ops", routes say `/control-room/*`, the
  panel is `FleetOverviewPanel`. Packs go by five names (pack / specialist / expertise /
  expert / Domain Expertise Pack); user-created agents by five (user-defined / persona /
  hired / custom / "Gems").
- **External brands are load-bearing.** Palantir's "Object Set" is our public API
  (`ObjectSet`, `GET /ontology/entities/{id}/object_sets`); an LLM prompt opens "You are
  building a Palantir-style semantic ontology" (`aughor/agent/prompts_ontology.py:4`);
  Genie/CopilotKit/Databricks/ReFoRCE appear in user-visible flag descriptions
  (`kernel/flags.py`); `web/styles/tokens.css` documents the theme as "Palantir Blueprint
  accent on Databricks Genie neutral-charcoal". The `soma` module ships a persisted
  `soma_probe` execution label and `AUGHOR_SOMA_CLARIFY` env var.
- **The word ≠ the thing.** `ADA` expands in-code to "Autonomous Intelligence Platform"
  (`agent/investigate.py:2`) — letters that don't match. `trust/` is SQL validation,
  `verify/` is human feedback, `agent/verify.py` is claim checking, `explorer/verify.py` is
  a quality gate — four `verify`s. `explore.*` flags and `explorer.*` flags are different
  subsystems two letters apart.
- **Live defect found by the sweep:** `trust/receipt.py:32` maps artifact kind `"insight"`
  → mode `"explore"`, but nothing writes kind `"insight"` — the explorer writes `"finding"`,
  which is unmapped, so `WhyThisNumber` renders the raw string `finding` to the user.

---

## 2 · The canonical glossary

The one-word-per-concept table. "Kill" terms may not appear in **new** code, UI copy,
prompts, or flag metadata once the ratchet lands (§6); existing occurrences burn down by
phase (§7). Frozen persisted identities are exempt and listed in §5.

### Answering

| Concept | Canonical word | Kills | Notes |
|---|---|---|---|
| Fast NL→SQL→answer path | **Quick answer** (label "Quick") | "Insight" (mode name), `direct` as a user word, "chat" | `direct` may stay as the internal graph-mode id |
| Autonomous deep path | **Investigation** / verb **Investigate** | ADA, "Deep Analysis", "Agentic", "deep" as a product name | Already the DB table, router, UI list, job kind |
| Wide multi-cut question mode | **Survey** | `explore` (the *question mode* only), "landscape", "wide wave" | Frees "explore" to mean one thing |
| Definitional/KB answer | **Knowledge answer** | `final_text` as a visible word | Add to the frontend mode union (today it's emitted but not typed) |
| Schema first-look answer | **Overview** | — | Register it as a real mode; today `overview` is an invented depth/mode value in neither enum |
| Background autonomous learning | **Exploration** (agent: **Explorer**) | "Scout" (display), "cartography" | The surface is already "Exploration" everywhere |
| Effort knob | `depth: quick \| deep` (internal) | `AskRequest.deep: bool` → rename **`escalate`** | Today `deep` is both a depth value and an unrelated boolean on the same request |
| Any reply to a question | **Answer** | — | |
| The investigation/exploration document | **Report** | `ada_report`, `ADAReport`, triple wire events | One SSE `report` event carrying `mode` |

### Facts and artifacts

| Concept | Canonical word | Kills | Notes |
|---|---|---|---|
| A discovered, evidence-backed fact shown to the user | **Finding** | **insight** (the noun, everywhere), "signal", "pattern", "fact", "domain intelligence" | Already the route noun (`/findings`), the ledger kind, and the object's own text field |
| Quick-answer narrative enrichment | **Narrative** | `_InsightResult`, SSE `insight`/`insight_delta` | |
| Per-sub-question one-liner | **takeaway** | `insight: str` field | |
| Guard/validator diagnostic | **Issue** (`TrustIssue`, `FanoutIssue`, `KeyIssue`) | guard `*Finding` classes | Also fixes the duplicate `FanoutFinding` class defined in two modules |
| Human-verified statement | **Claim** | — | `EvidenceClaim` already fits |
| Periodic narrative artifact | **Briefing** | "brief" (as the artifact), "digest", "Intelligence Digest" | `BriefSubscription` → **briefing subscription**; the workspace `Digest` → `BriefingContent`; monitors' digest → `AlertSummary` |
| One execution of anything | **Run** | "session", "episode" (→ **step**) | `job` stays as the internal supervision record; `trace_id` stays (telemetry standard) |
| Reusable governed SQL template | **Query template** | `OntologyAction` | It is not an action; also unclutters the action cluster below |

### Acting

| Concept | Canonical word | Kills | Notes |
|---|---|---|---|
| Governed data write | **Action** | "kinetic", "kinetic action" | The UI already labels the kinetic layer "Actions" |
| Outbound message (webhook/Slack/Jira) | **Notification** | "Action Hub", `ActionTrigger` as a user word | Ends the three-"Actions"-in-one-nav problem |
| Approval queue for pending actions | **Approvals** | "inbox" (kinetic) | Leaves exactly one user-facing **Inbox** (recommendations) |
| Watch-a-metric rule | **Monitor** | — | `playbook/` entries become **Advice rules** or fold into automations (see §4.6) |
| Condition→effect engine | **Automation** | — | Already correct; finish the absorption it was built for |

### Agents

| Concept | Canonical word | Kills | Notes |
|---|---|---|---|
| Built-in platform agents (the roster) | **Agent**, displays: **Explorer · Investigator · Responder · Watcher · Briefer · Curator** | "charter" as a user word; displays "Scout", "Analyst", "Insight" | Ids `scout/analyst/insight/...` are persisted governance keys — display-only rename |
| Investigation sub-roles | **SQL Engineer · Verifier · Narrator · Orchestrator** | — | Register `orchestrator` in `SPECIALISTS` (today it falls through to an empty echo entry) |
| User-created agent | **Custom agent** | "persona", "hired agent", "user-defined agent", "Gems" | Route is already `/agents/custom`; UI "Hire" → **Create** / "Create from pack" |
| Domain bundle | **Pack** | "specialist pack", "expertise pack", "Domain Expertise Pack", "expert", "Specialist Agents" | Folder, route and flag already say `pack` |
| The agents workspace | **Agents** | "Agentic Ops", "Control Room", "Fleet" (as the workspace name) | Layers become Overview · Roster · Attention · Activity · Runs; "Fleet" survives only if we keep it as the Overview layer's nickname — recommend not |

### Platform internals (module-level; §4.7 for staging)

| Concept | Canonical | Kills |
|---|---|---|
| SQL-ambiguity probe | **ambiguity probe** (`agent/ambiguity_probe.py`) | `soma`, `SomaVerdict`, `AUGHOR_SOMA_CLARIFY` |
| Stalled-run detection | **stall detector** | "wandering" |
| Human ground-truth capture | **feedback** (`aughor/feedback/`) | `aughor/verify/` |
| Control plane (credential/LLM vending) | **control_plane** | `aughor/platform/` (shadows stdlib `platform`) |
| Business/industry inference | **business_profile** | `aughor/profile/` (collides with data profiling) |
| Lifecycle mining | **lifecycle** | `aughor/process/` |
| Demo data | **demo** | `aughor/samples/` (collides with row samples) |
| Unstructured file store | **files** | `aughor/volumes/` |
| Generate→Validate→Execute→Interpret template | **pipeline** | `aughor/capability/` (collides with licence capabilities; also `capability.*` vs `capabilities.*` flags) |
| In-SQL LLM operators | **AI functions** | "semops" as a user word (package rename optional) |
| Saved filtered entity view | **Segment** (`/ontology/entities/{id}/segments`) | `ObjectSet` / `object_sets` (Palantir's term in our public API) |

---

## 3 · External-name policy

1. **Real integrations keep their names.** DuckDB, MotherDuck, DuckLake, MLflow, Langfuse,
   AG-UI protocol, Snowflake, BigQuery, the connector roster — a product name naming the
   product it connects to is not jargon.
2. **License attribution is untouchable.** `sql/readonly.py`, `sql/tables.py`,
   `tools/postproc.py` are Apache-2.0 adaptations of Superset/pandas code — those header
   comments are a legal obligation, not branding. **Gap found: `NOTICE` does not list
   Superset — add it (P1, independent of any rename).**
3. **Study docs are historical records** — `docs/*_STUDY_*.md`, teardown docs, memory notes
   keep their names. They are the *source* of the leaks, not the leak.
4. **Everything else goes.** No brand in: identifiers, API routes/fields, UI copy, LLM
   prompts, flag names/labels/descriptions, CSS/token comments, error strings. Where a
   design genuinely derives from a study, cite the doc file or arXiv id once —
   "(see docs/GENIE_DOCS_TEARDOWN_2026-07-26.md)" — instead of describing the feature *as*
   the brand ("Genie-style", "Foundry rule", "Palantir-grade").

Specific fixes (from the sweep; full file:line lists live in the inventory, §8):

| Leak | Fix | Phase |
|---|---|---|
| `ENRICH_ONTOLOGY_PROMPT` opens "Palantir-style semantic ontology" (`agent/prompts_ontology.py:4`) | "a semantic ontology for a business data warehouse" | P1 |
| Genie/CopilotKit/Databricks/ReFoRCE in ~15 `FLAG_META` descriptions + "(Wave K3)"-style sprint codes in ~25 labels | Rewrite descriptions to describe behavior; drop wave codes from labels (keep in code comments) | P1 |
| `web/styles/tokens.css` + `aughor-v2` theme comments ("Blueprint blue", "Genie near-black", "MLflow shell") | Describe the color/behavior, not the brand | P1 |
| chart-lab visible copy: "the Databricks *Color*", "Databricks-style viz editor" | Plain copy | P1 |
| ~50 "Databricks/Genie/Foundry/Palantir-style" docstrings & comments across `aughor/` + `web/` | Behavior + doc citation | P2 (mechanical sweep) |
| `ObjectSet` / `object_sets` public API; `OntologyInterface`/`OntologyAction` docstrings "mirrors Palantir's …" (the phrase leaks into OpenAPI descriptions in `api.gen.ts`) | `Segment` / `/segments` (dual-route), scrub docstrings; `OntologyAction` → `QueryTemplate` | P3 |
| `soma` module, `SomaVerdict`, `AUGHOR_SOMA_CLARIFY`, persisted `soma_probe` exec label | `ambiguity_probe` module/class/env (env alias kept); new executions labeled `ambiguity_probe`, old rows stay | P2–P3 |
| ReFoRCE/BIRD/Spider2 rationale in production docstrings | Keep as *citations* (arXiv/benchmark name), drop identity framing; evals keep benchmark names | P2 |
| Stale `Hermes` references (`db/connection.py:1112`, `semantic/kb_retriever.py:35`) | Delete | P1 |
| Stale `AUGHOR_OBS_MLFLOW`/`obs.mlflow` in `.env.example` + `docker-compose.yml` (flag deleted 2026-07-31) | Remove | P1 |

Fixture names (**BeautyCommerce**, **missimi**, **swiss_air**) are fictional demo/test data,
not external products — keep, but stop citing them in production docstrings when a generic
sentence works.

---

## 4 · The confusing modes, paths and surfaces — and the fixes

### 4.1 One mode vocabulary, two axes (NOM-01)
Today: `STRUCTURAL_MODES = (direct, investigate, explore, final_text)`, `Depth = quick|deep`,
UI `mode: "auto"|"ask"|"investigate"`, plus `overview` and `dossier` as queryMode values that
exist in **neither** enum, plus `ChatTurn.mode` and `queryMode` as two parallel fields with
different vocabularies. Target:

- `mode ∈ {quick, investigate, survey, knowledge, overview}` — one registry, backend =
  wire = frontend union (frontend today omits `final_text` even though it's emitted).
- `depth ∈ {quick, deep}` stays the router's internal effort knob; `AskRequest.deep: bool`
  (escalate-past-dossier) renames to `escalate`.
- `dossier` becomes an internal serving detail of quick answers ("saved finding"), not a mode.
- One turn-level `mode` field; delete the parallel vocabulary.

### 4.2 `explore` vs `explorer` (two subsystems, one stem)
Background learning keeps **Exploration/Explorer** (`aughor/explorer/`, `/exploration/*`,
`explorer.*` flags, the UI). The *question mode* becomes **Survey**: `agent/explore.py` →
`agent/survey.py`, mode id `explore` → `survey` (manifest + alias), flags `explore.*` →
`survey.*` (alias layer, §6), `ExplorationReport` (agent state) → `SurveyReport` — ending the
situation where `ExplorationReport` belongs to the *other* subsystem than
`ExplorationStatus`. MCP tool `explore` (which starts *background* exploration) is then
unambiguous.

### 4.3 The insight/finding knot (NOM-04/05)
- Explorer's `OntologyInsight` → **`Finding`**; `/exploration/{conn}/insights/{id}/*` routes
  → `/findings/{id}/*` (dual-route); counters `insights_found` → `findings_found` (additive
  field first); UI "N insights" → "N findings"; `SynthesisSignal`/`SignalCard` → Finding.
- Quick-answer `_InsightResult` + SSE `insight`/`insight_delta` → `Narrative` + `narrative`/
  `narrative_delta` (dual-emit one release).
- `state.py` quick-path `Finding` vs deep-path `InvestigationFinding` (incompatible shapes,
  same word): converge on one `Finding` base with a `source` discriminator, per NOM-05.
- Guard `*Finding` classes → `*Issue`.
- **Bug fix (immediate):** map artifact kind `finding` in `trust/receipt.py` `_MODE` and add
  a `MODE_LABEL` entry so users stop seeing the raw string `finding`.
- `KPI /exploration/kpi/time-to-first-insight` → `…/time-to-first-finding` (dual-route).

### 4.4 The brief/briefing/digest knot (NOM-08)
One artifact, one name: **Briefing**. `briefs/` becomes the briefing *subscriptions* module;
`knowledge/digest.py Digest` → `BriefingContent`; `monitors/digest.py` → `AlertSummary`;
UI strings unify ("Intelligence briefing" / "Writing intelligence brief" / "Regenerate
brief" — currently three variants lines apart in one component). Route nouns
(`/briefs/subscriptions`, `POST /exploration/{conn}/briefing`, `GET /monitors/digest`)
converge on `briefing` with dual-routes.

### 4.5 Surfaces and navigation
- **Agents workspace:** nav "Agentic Ops" → **Agents**; layers → Overview · Roster ·
  Attention · Activity · Runs. Backend `/control-room/*` routes stay as legacy contract;
  router file rename to `routers/agents_ops.py` happens in the code-move phase. Command
  palette labels align with sidebar labels (today four disagree).
- **Nav id ≠ label mismatches:** `recents`→"Investigations", `intelligence`→"Briefing",
  `canvases`→"Data Canvas" — align ids with labels; delete the five legacy dead ids
  (`intel-hub`, `intel`, `org-intel`, `ontology`, `control-room`) after a deep-link redirect
  map.
- **Three "Actions":** Intelligence layer "Actions" (governed writes) keeps the word; the
  Operations "Action Hub" (webhooks) → **Notifications**; approvals surface named
  **Approvals**. One **Inbox** remains (recommendations).
- **Three "Overviews":** the answer mode keeps **Overview**; the catalog per-table tab →
  "Summary"; Home is just Home.
- **Glossary and Overview get a home:** the business glossary is currently reachable only
  via a blurb word; give it a tab under Semantic Layer.
- **"Hub"** (`IntelligenceWorkspace` layer, NOM-12) → name by content: "Profile"
  (domain knowledge & data profile).

### 4.6 The when-X-do-Y family (NOM-07)
Five packages implement condition→effect (`monitors/`, `briefs/`, `automations/`,
`playbook/`, `actions/`). The plan of record is already written in
`automations/__init__.py` ("one engine replacing three") — **finish the absorption** behind
`automations.adopt_legacy` rather than renaming all five. Vocabulary now: Monitor,
Briefing subscription, Automation, Advice rule (playbook entries), Notification. `starters.py`
stops calling its templates "research playbooks" (they are **starters**); `PackPlaybook` →
`PackRecipe`.

### 4.7 Module renames (pure code moves, last)
`platform/`→`control_plane/` (stdlib shadow) · `user_agents/`→`custom_agents/` (HTTP header
collision) · `verify/`→`feedback/` · `capability/`→`pipeline/` · `samples/`→`demo/` ·
`profile/`→`business_profile/` · `process/`→`lifecycle/` · `volumes/`→`files/` ·
`actions/`→`notifications/` then `kinetic/`→`actions/` (strictly that order) ·
`briefs/`→`briefing/` · optional, lowest value: `kernel/`→`runtime/`, `semops/`→`ai_functions/`,
`obs/`→`observability/`. One package per PR; import-shim modules for one release
(`aughor/kinetic/__init__.py` re-exporting with a deprecation note) so external scripts
don't break.

---

## 5 · Frozen persisted identities (never rename; map at the boundary)

Renaming these orphans history. Each gets a one-line comment naming its display word:

- Ledger `natural_key` prefixes `ada:`, `insight:`; artifact kinds `ada_report`, `finding`
  (the `ada:` freeze is already documented at `routers/investigations.py:4331`).
- Licence capability **value** `"analysis.deep"` (the enum *member* `DEEP_ANALYSIS` →
  `INVESTIGATION` is a safe code-side rename).
- Job kinds (`exploration`, `investigation`, `monitor`, `brief`, `profile`), charter ids
  (`scout`, `analyst`, `insight`, …), specialist ids in `agent.handoff` journal payloads,
  the `agent_governance` KV store name/keys, session-log `agent_id`, checkpoint key
  `agent_id`.
- DB columns (`investigations.origin_insight_id`, `user_agents.*`), Qdrant payload key
  `insight_id`, dashboard card `source="insight"` (accept `finding` as new writes, read both).
- Pack on-disk format (`pack.yaml`, `expertise.md`, manifest keys) — a published format.
- Historical `soma_probe` task-history rows.

---

## 6 · Enforcement — the vocabulary ratchet

The repo's proven pattern (baseline-zero ratchets, CI-checked). New
`tests/unit/test_vocabulary_ratchet.py`:

- A `BANNED` table: term → scope globs → baseline count (captured at P0). Terms: `\bADA\b`,
  `ada_`, `deep_analysis` / `Deep Analysis`, `insight` (scoped to live code, case-insensitive),
  `palantir`, `genie`, `foundry`, `blueprint` (styles only), `databricks` (outside
  connectors + attribution headers), `soma`, `kinetic` (once §4.7 lands), `persona`,
  `hired`, `specialist`, `digest`, `agentic ops`, `control room`.
- Rule: **a baseline never rises**; each PR that touches a file may only lower it. Exempt
  globs: `docs/`, `evals/` benchmark names, attribution headers, `data/`, frozen identities
  (matched by exact string).
- A small **flag-alias layer** in `kernel/flags.py`: `RENAMED: dict[old, new]` consulted by
  env resolution, runtime-override reads, and the flags API (old key reported with a
  `renamed_to` field); the existing registry ratchet asserts no old key ever re-registers.
  This is a prerequisite for `ada.*`→`investigate.*`, `explore.*`→`survey.*`,
  `capability.*`→`pipeline.*`, and prefixing the four orphans (`ai_sql`, `closed_loop`,
  `snapshot_receipts`, `specialist_packs`).
- `docs/GLOSSARY.md` — the canonical table from §2, linked from `AGENTS.md` so every future
  session inherits the vocabulary.

---

## 7 · Execution phases

Each phase is independently shippable and observable; flags stay byte-identical-off; the
frontend runs all five gates; `cd web && npm run gen:api` after any route change.

**P0 — Glossary + ratchet (1 PR).** `docs/GLOSSARY.md`, the ratchet test with captured
baselines, the flag-alias layer (no renames yet), the `NOTICE` Superset addition, and the
two immediate bug fixes (receipt `finding` mapping; stale `obs.mlflow` env/compose lines).

**P1 — Words users and models see (1–2 PRs, display-only).** UI labels ("Agentic Ops"→
Agents, "Deep Analysis"→Investigate, "Insight"→Quick, "Expertise packs"→Packs, "Personas"→
Custom agents, "Hire"→Create, Action Hub→Notifications, digest/brief→Briefing), charter
display names (Investigator/Responder/Explorer), flag labels+descriptions scrub (brands,
wave codes), the ontology prompt, tokens.css comments, chart-lab copy, CLI/MCP/export
prose, command-palette alignment, Hermes deletions. Zero contract changes. Verify live:
screenshot the renamed surfaces; snapshot a flag-metadata diff to prove only prose changed.

**P2 — Internal identifiers (2–3 PRs).** Kill `ADA` in `web/` (NOM-03: types, stream
actions, `ADAReport` alias); `soma`→`ambiguity_probe`, `wandering`→`stall`; guard
`*Finding`→`*Issue`; register `orchestrator`; `OntologyInsight`→`Finding` (class only,
serialization keys unchanged); comment/docstring brand sweep; graph node display mapping so
Run-graphs shows phase names, not `ada_*` ids.

**P3 — Wire and config contracts, with aliases (3–4 PRs).** SSE unification
(`report` + mode; `narrative` dual-emit; retire `ada_report`/`answer_report` events after
one release), `/findings` + `/segments` + `/briefing` dual-routes, `branch:"ada"`→
`"investigation"` (additive), `AskRequest.deep`→`escalate` (accept both), mode id
`explore`→`survey` (manifest + declarative-modes alias), flag family renames through the
alias layer, `AUGHOR_ADA_*`/`AUGHOR_SOMA_*` env aliases, MCP `deep_analysis`→`investigate`
(alias one release), `Capability.DEEP_ANALYSIS`→`INVESTIGATION` (value frozen). Regenerate
`api.gen.ts` per PR.

**P4 — Package moves (1 PR each, mechanical).** §4.7 order matters only for
`actions`→`notifications` before `kinetic`→`actions`. Import shims for one release.

**Deliberately out of scope:** NOM-06 (`SemanticContract` unification) and NOM-11
(`ExecutionScope`) — real architecture, not vocabulary; NOM-07's `Safeguard` base — the
automations absorption supersedes it; any rename of frozen identities (§5).

---

## 8 · Source inventories

The four raw inventories (file:line evidence for every claim above) are in this branch's
session record; the load-bearing anchors are cited inline. Prior art: NOM-01…NOM-12
(2026-07-03 review §3), `docs/UNIFIED_ANSWER_PATH.md`, `automations/__init__.py`'s
absorption charter, and the REC-U9 half-finished `ADA`→`answer` rename this plan completes.
