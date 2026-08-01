# Vocabulary Unification — one word, one concept (Wave W)

**Date:** 2026-08-01 · **Status:** PLAN (nothing executed) · **Scope:** full, P0–P4
**Rule:** every concept gets exactly one word, every word names exactly one concept, and the
word is plain language a new reader already knows. Internal codenames, research acronyms and
external product names do not appear in identifiers, UI copy, prompts, or flag metadata.

Built from a four-way code inventory (answer modes · external names · agent taxonomy ·
module codenames) against live code, not the docs — the docs are themselves part of the
drift. Subsumes the still-open NOM-01…NOM-12 items in
`docs/architecture-review-2026-07-03/PART-2-uiux-nomenclature-and-layering.md` §3, and
completes the half-finished REC-U9 `ADA`→`answer` rename.

---

## 1 · The diagnosis, measured

- **One feature, six names.** The deep path is `investigate` (graph mode), `deep` (depth),
  **ADA** (~183 `\bADA\b` + 362 `ada_*` occurrences), "Deep Analysis" (UI/MCP/licence),
  **Analyst** (agent roster), "Agentic" (canvas copy). The quick path is `direct` / `quick` /
  `ask` / "Insight". The word **insight** alone covers ≥7 concepts across ~2,196 occurrences.
- **One screen, three names.** Nav "Agentic Ops", routes `/control-room/*`, panel
  `FleetOverviewPanel`. Packs go by five names (pack / specialist / expertise / expert /
  Domain Expertise Pack); user-created agents by five (user-defined / persona / hired /
  custom / "Gems").
- **External brands are load-bearing.** Palantir's "Object Set" is our public API
  (`ObjectSet`, `GET /ontology/entities/{id}/object_sets`); an LLM prompt opens "You are
  building a Palantir-style semantic ontology" (`agent/prompts_ontology.py:4`); Genie,
  CopilotKit, Databricks and ReFoRCE appear in user-visible flag descriptions
  (`kernel/flags.py`); `web/styles/tokens.css` documents the theme as "Palantir Blueprint
  accent on Databricks Genie neutral-charcoal". The `soma` module ships a persisted
  `soma_probe` execution label and an `AUGHOR_SOMA_CLARIFY` env var.
- **The word ≠ the thing.** `ADA` expands in-code to "Autonomous Intelligence Platform"
  (`agent/investigate.py:2`) — letters that don't match. Four different `verify`s exist
  (`trust/` = SQL validation, `verify/` = human feedback, `agent/verify.py` = claim checking,
  `explorer/verify.py` = a quality gate). `explore.*` and `explorer.*` are different
  subsystems two letters apart.
- **Live defect found by the sweep:** `trust/receipt.py:32` maps artifact kind `"insight"` →
  mode `"explore"`, but nothing writes kind `"insight"` — the explorer writes `"finding"`,
  which is unmapped and has no `MODE_LABEL` entry, so `WhyThisNumber` renders the raw string
  `finding` to the user.

---

## 2 · The canonical glossary

"Kills" may not appear in **new** code, UI copy, prompts, or flag metadata once the ratchet
lands (§6); existing occurrences burn down as files are touched (§7). Frozen persisted
identities are exempt and listed in §5.

### Answering

| Concept | Canonical word | Kills | Notes |
|---|---|---|---|
| The autonomous deep path — **both the mode you pick and the record it produces** | **Deep analysis** (plural "deep analyses") | ADA, "Agentic", "Investigation" *in user-visible text*, `deep` as a standalone product noun | Display layer only; every persisted identifier stays `investigation*` (§5) |
| Fast NL→SQL→answer path | **Quick answer** (label "Quick") | "Insight" as a mode name, "chat", `direct` as a user word | `direct` survives as the internal graph-mode id |
| Wide multi-cut question mode | **Survey** | `explore` *as a question mode*, "landscape", "wide wave" | Frees the explore/explorer stem to mean one subsystem |
| Definitional / KB answer | **Knowledge answer** | `final_text` as a visible word | Add to the frontend mode union — today it is emitted but not typed |
| Schema first-look answer | **Overview** | — | Promote to a real registered mode; today it is an invented value in neither enum |
| Background autonomous learning | **Exploration** (the agent: **Explorer**) | "Scout", "cartography" | Agent name and subsystem name now agree |
| Effort knob (internal) | `depth: quick \| deep` | `AskRequest.deep: bool` → **`escalate`** | Today `deep` is a depth value *and* an unrelated boolean on the same request |
| Any reply to any question | **Answer** | — | |
| The document a deep analysis or survey produces | **Report** | `ada_report`, `ADAReport`, three parallel wire events | One SSE `report` event carrying `mode` |

### Facts and artifacts

| Concept | Canonical word | Kills | Notes |
|---|---|---|---|
| A discovered, evidence-backed fact shown to the user | **Finding** | **insight** (the noun, everywhere), "signal", "pattern", "fact", "domain intelligence" | Already the route noun (`/findings`), the ledger kind, and the object's own text field |
| Quick-answer narrative enrichment | **Narrative** | `_InsightResult`, SSE `insight` / `insight_delta` | |
| Per-sub-question one-liner | **takeaway** | the `insight: str` field | |
| Guard / validator diagnostic | **Issue** (`TrustIssue`, `FanoutIssue`, `KeyIssue`) | guard `*Finding` classes | Also fixes `FanoutFinding` being defined in two modules |
| Human-verified statement | **Claim** | — | `EvidenceClaim` already fits |
| Periodic narrative artifact | **Briefing** | "brief" (as the artifact), "digest", "Intelligence Digest" | `BriefSubscription` → briefing subscription; `Digest` → `BriefingContent`; monitors' digest → `AlertSummary` |
| One execution of anything | **Run** | "session", "episode" (→ **step**) | `job` stays as the internal supervision record; `trace_id` stays (telemetry standard) |
| Saved named filter over an entity's rows | **Segment** | `ObjectSet` / `object_sets` | Business-native word; route becomes `/ontology/entities/{id}/segments` |
| Reusable governed SQL template | **Query template** | `OntologyAction` | It is not an action — this also unclutters the action cluster below |

### Acting

| Concept | Canonical word | Kills | Notes |
|---|---|---|---|
| Governed data write | **Action** | "kinetic", "kinetic action" | The UI already labels the kinetic layer "Actions" |
| Outbound message (webhook / Slack / Jira) | **Notification** | "Action Hub", `ActionTrigger` as a user word | Ends three "Actions" in one nav |
| Approval queue for pending actions | **Approvals** | kinetic "inbox" | Leaves exactly one user-facing **Inbox** (recommendations) |
| Watch-a-metric rule | **Monitor** | — | `playbook/` entries become **Advice rules** or fold into automations (§4.6) |
| Condition→effect engine | **Automation** | — | Already right; finish the absorption it was built for |

### Agents

| Concept | Canonical | Kills |
|---|---|---|
| Built-in agent roster (display names) | **Explorer · Analyst · Responder · Watcher · Briefer · Curator** | "Scout", "Insight" (as an agent), "charter" as a user word |
| Deep-analysis sub-roles | **SQL Engineer · Verifier · Narrator · Orchestrator** | — (register `orchestrator`; today it falls through to an empty echo entry) |
| User-created agent | **Custom agent** | "persona", "hired agent", "user-defined agent", "Gems" |
| Domain bundle | **Pack** | "specialist pack", "expertise pack", "Domain Expertise Pack", "expert", "Specialist Agents" |
| The agents workspace | **Agents** (layers: Overview · Roster · Attention · Activity · Runs) | "Agentic Ops", "Control Room", "Fleet" |
| Human permission ladder | **Viewer · Editor · Owner** | the RBAC display role "Analyst" (value `analyst` frozen) |

**Why the Analyst keeps its name.** The agent that runs deep analyses stays **Analyst** — the
word users already know — and the collision is resolved from the other side: the RBAC human
role renames at the display layer to **Editor**, giving the standard Viewer/Editor/Owner
ladder (`rbac/roles.py` describes exactly that least-privilege ladder today). The stored
grant value stays `"analyst"`.

### Platform internals (module level; §4.7 for staging)

| Concept | Canonical | Kills |
|---|---|---|
| SQL-ambiguity probe | **ambiguity probe** (`agent/ambiguity_probe.py`) | `soma`, `SomaVerdict`, `AUGHOR_SOMA_CLARIFY` |
| Stalled-run detection | **stall detector** | "wandering" |
| Human ground-truth capture | **feedback** (`aughor/feedback/`) | `aughor/verify/` |
| Control plane (credential / LLM vending) | **control_plane** | `aughor/platform/` (shadows stdlib `platform`) |
| Business/industry inference | **business_profile** | `aughor/profile/` (collides with data profiling) |
| Lifecycle mining | **lifecycle** | `aughor/process/` |
| Demo data | **demo** | `aughor/samples/` (collides with row samples) |
| Unstructured file store | **files** | `aughor/volumes/` |
| Generate→Validate→Execute→Interpret template | **pipeline** | `aughor/capability/` (collides with licence capabilities; also `capability.*` vs `capabilities.*` flags) |
| In-SQL LLM operators | **AI functions** | "semops" as a user word |

---

## 3 · External-name policy

1. **Real integrations keep their names.** DuckDB, MotherDuck, DuckLake, MLflow, Langfuse,
   the AG-UI protocol, Snowflake, BigQuery, the connector roster. A product name naming the
   product it connects to is not jargon.
2. **Licence attribution is untouchable.** `sql/readonly.py`, `sql/tables.py`,
   `tools/postproc.py` are Apache-2.0 adaptations of Superset/pandas code — a legal
   obligation, not branding. **Gap found: `NOTICE` does not list Superset. Add it (P0,
   independent of every rename here.)**
3. **Study docs are historical records.** `docs/*_STUDY_*.md`, teardowns and memory notes
   keep their names. They are the source of the leaks, not the leak.
4. **Everything else goes.** No brand in identifiers, API routes/fields, UI copy, LLM
   prompts, flag names/labels/descriptions, CSS or token comments, or error strings. Where a
   design genuinely derives from a study, cite the doc once — "(see
   `docs/GENIE_DOCS_TEARDOWN_2026-07-26.md`)" — instead of describing the feature *as* the
   brand ("Genie-style", "the Foundry rule", "Palantir-grade").

| Leak | Fix | Phase |
|---|---|---|
| `ENRICH_ONTOLOGY_PROMPT` opens "Palantir-style semantic ontology" (`agent/prompts_ontology.py:4`) | "a semantic ontology for a business data warehouse" | P1 |
| Genie / CopilotKit / Databricks / ReFoRCE across ~15 `FLAG_META` descriptions; "(Wave K3)"-style sprint codes in ~25 labels | Describe behavior; drop wave codes from labels (keep them in code comments) | P1 |
| `web/styles/tokens.css` + `aughor-v2` theme comments ("Blueprint blue", "Genie near-black", "MLflow shell") | Describe the colour and its role, not the brand | P1 |
| chart-lab visible copy: "the Databricks *Color*", "Databricks-style viz editor" | Plain copy | P1 |
| ~50 "Databricks/Genie/Foundry/Palantir-style" docstrings and comments across `aughor/` and `web/` | Behavior + doc citation | P2 (mechanical) |
| `ObjectSet` / `object_sets` public API; "mirrors Palantir's …" docstrings that leak into OpenAPI descriptions in `api.gen.ts` | → **Segment** / `/segments` (dual-route); scrub docstrings; `OntologyAction` → `QueryTemplate` | P3 |
| `soma` module, `SomaVerdict`, `AUGHOR_SOMA_CLARIFY`, persisted `soma_probe` label | → `ambiguity_probe` (env alias kept); new rows labelled `ambiguity_probe`, historical rows untouched | P2–P3 |
| ReFoRCE / BIRD / Spider2 framing in production docstrings | Keep as citations, drop identity framing; evals keep benchmark names | P2 |
| Stale `Hermes` references (`db/connection.py:1112`, `semantic/kb_retriever.py:35`) | Delete | P0 |
| Stale `AUGHOR_OBS_MLFLOW` / `obs.mlflow` in `.env.example` + `docker-compose.yml` (flag deleted 2026-07-31) | Remove | P0 |

Fixture names (**BeautyCommerce**, **missimi**, **swiss_air**) are fictional demo/test data,
not external products — keep them, but stop citing them in production docstrings where a
generic sentence works.

---

## 4 · The confusing modes, paths and surfaces

### 4.1 One mode vocabulary, two axes (NOM-01)
Today: `STRUCTURAL_MODES = (direct, investigate, explore, final_text)`, `Depth = quick|deep`,
UI `mode: "auto"|"ask"|"investigate"`, plus `overview` and `dossier` used as queryMode values
that exist in **neither** enum, plus `ChatTurn.mode` and `queryMode` as two parallel fields
with different vocabularies on the same turn. Target:

- `mode ∈ {quick, deep_analysis, survey, knowledge, overview}` — one registry, identical
  backend / wire / frontend union (the frontend today omits `final_text` although it is
  emitted).
- `depth ∈ {quick, deep}` stays the router's internal effort knob; `AskRequest.deep: bool`
  renames to `escalate`.
- `dossier` becomes an internal serving detail of a quick answer ("saved finding"), not a mode.
- One turn-level `mode` field; the parallel vocabulary is deleted.

### 4.2 Deep analysis vs investigation — the display/identifier split
**Display (banned word: "investigation"):** nav "Investigations" → **Deep analyses**; every
UI string, prompt, CLI/MCP/export line and flag label says *deep analysis*. Frontend
identifiers follow the display word (`InvestigationReport.tsx` → `DeepAnalysisReport.tsx`,
`ChatTurn.mode = "deep_analysis"`).
**Identifier (frozen forever):** the `investigations` table, `/investigate` route, the
`investigation` job kind and every ledger key keep their spelling. The glossary records the
mapping once, and `routers/investigations.py` gets a one-line header stating it.
**Exempt from the ratchet:** `web/lib/api.gen.ts` (generated) and the fetch-boundary field
names in `web/lib/api.ts`, which must mirror the backend contract.

### 4.3 `explore` vs `explorer` (two subsystems, one stem)
Background learning keeps **Exploration / Explorer** (`aughor/explorer/`, `/exploration/*`,
`explorer.*` flags, the UI surface, and now the agent display name). The *question mode*
becomes **Survey**: `agent/explore.py` → `agent/survey.py`, mode id `explore` → `survey`
(manifest + alias), flags `explore.*` → `survey.*` via the alias layer, and
`ExplorationReport` (agent state) → `SurveyReport` — ending the situation where
`ExplorationReport` belongs to a different subsystem than `ExplorationStatus`. The MCP tool
`explore`, which starts *background* exploration, then means one thing.

### 4.4 The insight/finding knot (NOM-04/05)
- Explorer's `OntologyInsight` → **`Finding`**; `/exploration/{conn}/insights/{id}/*` →
  `/findings/{id}/*` (dual-route); `insights_found` → `findings_found` (additive first);
  UI "N insights" → "N findings"; `SynthesisSignal` / `SignalCard` → Finding.
- Quick-answer `_InsightResult` and SSE `insight` / `insight_delta` → `Narrative` and
  `narrative` / `narrative_delta` (dual-emit for one release).
- `state.py`'s quick-path `Finding` and deep-path `InvestigationFinding` (incompatible
  shapes, same word) converge on one `Finding` base with a `source` discriminator (NOM-05).
- Guard `*Finding` classes → `*Issue`.
- `GET /exploration/kpi/time-to-first-insight` → `…/time-to-first-finding` (dual-route).
- **Bug fix, P0:** map artifact kind `finding` in `trust/receipt.py` `_MODE` and add the
  matching `MODE_LABEL` entry, so users stop seeing the raw string `finding`.

### 4.5 The brief / briefing / digest knot (NOM-08)
One artifact, one name: **Briefing**. `briefs/` becomes the briefing *subscriptions* module;
`knowledge/digest.py Digest` → `BriefingContent`; `monitors/digest.py` → `AlertSummary`; the
UI unifies (today "Intelligence briefing", "Writing intelligence brief" and "Regenerate
brief" appear within a few lines of one component). Route nouns (`/briefs/subscriptions`,
`POST /exploration/{conn}/briefing`, `GET /monitors/digest`) converge on `briefing` with
dual-routes.

### 4.6 Surfaces and navigation
- **Agents workspace:** nav "Agentic Ops" → **Agents**; layers **Overview · Roster ·
  Attention · Activity · Runs** ("Fleet" retired from the UI). Backend `/control-room/*`
  stays until the P4 router rename; command-palette labels align with sidebar labels (four
  disagree today).
- **Nav id ≠ label:** align `recents`→"Deep analyses", `intelligence`→"Briefing",
  `canvases`→"Data Canvas"; delete the five legacy dead ids (`intel-hub`, `intel`,
  `org-intel`, `ontology`, `control-room`) behind a deep-link redirect map.
- **Three "Actions":** the Intelligence layer "Actions" (governed writes) keeps the word;
  Operations "Action Hub" → **Notifications**; the approvals surface is **Approvals**. One
  **Inbox** remains (recommendations).
- **Three "Overviews":** the answer mode keeps **Overview**; the catalog per-table tab
  becomes "Summary"; Home is just Home.
- **Glossary gets a home** — today it is reachable only as a word in a blurb; give it a tab
  under Semantic Layer. **"Hub"** (NOM-12) → **Profile**.

### 4.7 The when-X-do-Y family (NOM-07)
Five packages implement condition→effect (`monitors/`, `briefs/`, `automations/`,
`playbook/`, `actions/`). The plan of record is already written in `automations/__init__.py`
("one engine replacing three") — **finish that absorption** behind `automations.adopt_legacy`
rather than renaming five peers. Vocabulary meanwhile: Monitor · Briefing subscription ·
Automation · Advice rule (playbook entries) · Notification. `starters.py` stops calling its
templates "research playbooks" (they are **starters**); `PackPlaybook` → `PackRecipe`.

### 4.8 Module renames (pure code moves, last)
`platform/`→`control_plane/` · `user_agents/`→`custom_agents/` · `verify/`→`feedback/` ·
`capability/`→`pipeline/` · `samples/`→`demo/` · `profile/`→`business_profile/` ·
`process/`→`lifecycle/` · `volumes/`→`files/` · `actions/`→`notifications/` **then**
`kinetic/`→`actions/` (strictly that order) · `briefs/`→`briefing/`. Optional and lowest
value: `kernel/`→`runtime/`, `semops/`→`ai_functions/`, `obs/`→`observability/`. One package
per PR, with import shims for one release.

---

## 5 · Frozen identities (never renamed; mapped at the display boundary)

Each gets a one-line comment naming its display word.

- Ledger `natural_key` prefixes `ada:` and `insight:`; artifact kinds `ada_report`,
  `finding` (the `ada:` freeze is already documented at `routers/investigations.py:4331`).
- The `investigations` table, `/investigate` route, `investigation` job kind (§4.2).
- Licence capability **value** `"analysis.deep"` (the enum member `DEEP_ANALYSIS` may be
  renamed in code; the string may not).
- Job kinds, charter ids (`scout`, `analyst`, `insight`, …), specialist ids in
  `agent.handoff` payloads, the `agent_governance` KV store name and keys, session-log
  `agent_id`, checkpoint key `agent_id`.
- RBAC role value `"analyst"` (display: Editor).
- DB columns (`investigations.origin_insight_id`, `user_agents.*`), the Qdrant payload key
  `insight_id`, dashboard card `source="insight"` (write `finding`, read both).
- The pack on-disk format (`pack.yaml`, `expertise.md`, manifest keys) — a published format.
- Historical `soma_probe` task-history rows.

---

## 6 · Enforcement — the vocabulary ratchet

New `tests/unit/test_vocabulary_ratchet.py`, following the repo's proven baseline-zero
pattern:

- A `BANNED` table of term → scope globs → baseline count, captured at P0. Terms: `\bADA\b`,
  `ada_`, `insight`, `investigation`/`investigate` (web/ + user-visible strings only),
  `palantir`, `genie`, `foundry`, `blueprint` (styles), `databricks` (outside connectors and
  attribution headers), `soma`, `persona`, `hired`, `specialist`, `digest`, `agentic ops`,
  `control room`, `fleet`, and `kinetic` once §4.8 lands.
- **A baseline never rises.** A PR touching a file may only lower it. Exempt globs: `docs/`,
  `evals/` benchmark names, attribution headers, `data/`, `web/lib/api.gen.ts`, and the
  frozen strings in §5 (matched exactly).
- **Insight burns down incrementally** — no big-bang sweep PR. The baseline captured at P0
  ratchets down as files are touched by normal work, which avoids review-bombing and merge
  conflicts against in-flight waves.
- **A flag-alias layer in `kernel/flags.py`.** *Premise checked:* the registry's `MIGRATION`
  group is a **disposition category, not a rename facility**, and there is no alias mechanism
  today — so `RENAMED: dict[old, new]` must be built first, consulted by env resolution,
  runtime-override reads and the flags API (old key reported with `renamed_to`), with the
  existing registry ratchet asserting no old key re-registers. Prerequisite for `ada.*` →
  `deep_analysis.*`, `explore.*` → `survey.*`, `capability.*` → `pipeline.*`, and prefixing
  the four unprefixed orphans (`ai_sql`, `closed_loop`, `snapshot_receipts`,
  `specialist_packs`).
- **`docs/GLOSSARY.md`** — the §2 table, linked from `AGENTS.md` so every future session
  inherits the vocabulary instead of re-deriving it.

---

## 7 · Execution phases

Each phase ships independently; flags stay byte-identical when off; the frontend runs all
five gates; `cd web && npm run gen:api` after any route change.

**P0 — Glossary, ratchet, and the bugs the sweep found (1 PR).** `docs/GLOSSARY.md`; the
ratchet with captured baselines; the flag-alias layer (no renames yet); the `NOTICE`
Superset attribution; the `trust/receipt.py` `finding` mapping fix; deletion of the stale
`obs.mlflow` env/compose lines and the dead `Hermes` references.

**P1 — Words users and models see (1–2 PRs, display-only).** UI labels (Agentic Ops→Agents,
Investigations→Deep analyses, Insight→Quick, Expertise packs→Packs, Personas→Custom agents,
Hire→Create, Action Hub→Notifications, brief/digest→Briefing, Fleet→Overview, Hub→Profile),
charter display names (Explorer/Analyst/Responder/…), the RBAC ladder (Viewer/Editor/Owner),
the flag label + description scrub (brands and wave codes), the ontology prompt, tokens.css
comments, chart-lab copy, CLI/MCP/export prose, command-palette alignment. Zero contract
changes. **Verify live:** screenshot the renamed surfaces and diff flag metadata to prove
only prose moved.

**P2 — Internal identifiers (2–3 PRs).** Kill `ADA` in `web/` (NOM-03: types, stream
actions, the `ADAReport` alias); `soma`→`ambiguity_probe`; `wandering`→`stall`; guard
`*Finding`→`*Issue`; register `orchestrator`; `OntologyInsight`→`Finding` (class only,
serialization unchanged); the comment/docstring brand sweep; a graph-node display mapping so
Run graphs shows phase names instead of `ada_*` ids.

**P3 — Wire and config contracts, with aliases (3–4 PRs).** SSE unification (`report` +
`mode`; `narrative` dual-emit; retire `ada_report`/`answer_report` after one release);
`/findings`, `/segments` and `/briefing` dual-routes; `branch:"ada"`→`"deep_analysis"`
(additive); `AskRequest.deep`→`escalate` (accept both); mode id `explore`→`survey`; flag
family renames through the alias layer; `AUGHOR_ADA_*` / `AUGHOR_SOMA_*` env aliases; MCP
`deep_analysis` stays (already correct) while `investigate`-flavoured tool prose is aligned.

> `Capability.DEEP_ANALYSIS` needs no rename after all — choosing "deep analysis" as the
> canonical word made the existing enum member already correct. Its value `"analysis.deep"`
> stays frozen regardless.

**P4 — Package moves (1 PR each, mechanical).** §4.8, with `actions`→`notifications` strictly
before `kinetic`→`actions`. Import shims for one release.

**Deliberately out of scope:** NOM-06 (`SemanticContract`) and NOM-11 (`ExecutionScope`) —
real architecture, not vocabulary; NOM-07's `Safeguard` base — superseded by the automations
absorption; any rename of a §5 frozen identity.
