# Bringing Palantir Foundry's features into Aughor (2026-10-24)

**The question.** Which of Foundry's features should Aughor take, in what shape, and in what order — so that
Aughor gains what Foundry does well without breaking the laws in [`AGENTS.md`](../AGENTS.md).

**Sources.**
- [The catalogue study of the same day](PALANTIR_DOCS_CATALOGUE_2026-10-24.md) and its
  [329-operation API table](PALANTIR_FOUNDRY_API_CATALOGUE_2026-10-24.csv): what Palantir publishes, and what
  [the July study](PALANTIR_FOUNDRY_STUDY_2026-07-22.md) never read.
- 246 public docs pages from the 24 unread sections that touch Aughor most, read in four clusters: agents and
  outside access · the ontology · operations · apps and the developer platform.
- The Aughor tree at `f7af0167`, read file by file and read-only. Four parallel readers wrote the cluster findings.
  Every claim a top recommendation rests on was re-checked by hand; §9 lists what was and was not.

**The short answer.** Aughor has already taken most of Foundry's shape — declared actions, the edit layer,
releases, object pages, Apps, row policies, a contract for outside programs, one automation engine. What Foundry
still has that Aughor lacks is mostly not a new product. It is three properties of the products Aughor already
built: **a rule holds at every door, every change says what made it, and what Aughor knows can be found and handed
on.** The work below is ordered that way.

---

## 1. Where Aughor stands

### 1.1 The July roadmap, three months on

| July wave | What it proposed | Today |
| --- | --- | --- |
| K · declared actions | actions with submission criteria, an edit layer, agents writing through the same gate | Merged [#201](https://github.com/sidhasadhak/aughor/pull/201). Declared actions, Approvals, the edit layer with history (OC-6) |
| E · sessions and evals | a session schema, suites, evaluators, experiments | Merged by 2026-07-26 (`PLATFORM_PROGRAM_2026-07-26.md` §0). `/evals` suites, experiments, graduation receipts |
| A · automations | one condition → effect engine | Merged by 2026-07-26. Monitors and brief subscriptions run in it; the legacy schedulers are deleted (`kernel/flags.py:252-257`) |
| V · artifact lifecycle | save ≠ publish, versions, freeze | Merged #219. Cards and canvases use it (`cards/store.py:178`, `canvas/store.py:172`); **dashboards do not** (§3, item 4) |
| G · governance | tags, clearances, categorised audit, usage | Partly: table tags and clearances trim retrieval (`govern/tags.py`, `govern/retrieval_trim.py`). No audit export, no justifications (§4.3) |
| S · surface | object pages, next-action verbs, typed module interfaces | Partly: zero-config object pages (ROADMAP §3.29, §3.44). Module interfaces still unbuilt (§4.4) |

### 1.2 Foundry ideas Aughor already has, under its own names

| Foundry | Aughor (glossary word) | Where, and its state |
| --- | --- | --- |
| Action types with submission criteria | **Declared action**, **Approvals** | `aughor/actions/`, `/kinetic-actions/*` — on |
| Edits kept beside the source | **Edit layer** | `actions/overlay.py` — on, with history |
| Ontology proposals and branches | **Draft** and **Release** | `ontology/release.py`, `ontology.release` default on; changes classed ERR · MEANING · WARN · SAFE |
| Object views | **Object page** | `web/components/objects/ObjectView.tsx` — on, no flag |
| Workshop apps, variables, action buttons | **Dashboard**, **App**, **Set**, **Variable**, **Action buttons** | Arc AP; the builder flags are off (`dashboard.*`) |
| OSDK | **Contract of a release** and the builder doors | `GET /ontology/v1/contract`, `/ontology/v1/types.d.ts`; `ontology.builder_doors` graduated on |
| Object and property security policies | **Row policy**, **Sensitive property** | `ontology/security.py`; `ontology.security` off |
| Object Monitors → Automate | **Monitor** inside the one **Automation** engine | on |
| Workflow Builder's live preview | **Dry run** | `POST /automations/{id}/dry-run` — on |
| Ontology MCP | Aughor's MCP server: 23 governed tools, plus `ask_<agent>` and `propose_<action>` | `aughor/mcp/` — on |
| Foundry Rules | **Rule**, read as a segment | `ontology/models.py` `BusinessRule` — on |
| Vertex cause and effect, scenarios | **Impact**, **Scenario** | `ontology/impacts.py`, `record/scenario.py` |
| AIP Evals | Evals | `/evals/*` — on |

Where Aughor is already ahead, it stays ahead: a model proposal no person confirmed is refused at release
(`release.py:235-238`); the agent proposes and a person accepts, where Foundry's agents execute; monitors have
backtests, proofs and a review of what was missed, which Foundry's do not.

---

## 2. Fix first — defects found while comparing

These are not Palantir features. They are places where Aughor's own rule does not hold today, found because a
Foundry feature pointed at them.

| | Defect | Evidence | New? |
| --- | --- | --- | --- |
| D1 | **The ontology's row policies never reach SQL.** OC-7 applies at the object doors only (`semantic/object_query.py:693`). Quick answers and deep analyses go through `rbac/row_policy.py`, a second store that ships empty (`ROW_POLICIES = {}`, line 24) and never reads the ontology's. Inert today because `ontology.security` is off; a hole the day it graduates. | re-checked | new |
| D2 | **Edit history ignores who is reading.** `GET /actions/edits/history` scopes by organisation only (`routers/actions.py:74-81`) — no row policy, no sensitive property. | re-checked | new |
| D3 | **Table health can only say "not checked".** The quality plane has readers (`mcp/knowledge_tools.py:213`, `knowledge/briefing_content.py:173`) and no producer: nothing outside `aughor/quality/` writes a result. | re-checked | new |
| D4 | **Document search turns a failure into "no match".** `knowledge/indexer.py:457` returns `[]` on any exception — withheld is said, never implied. | re-checked | new |
| D5 | **Monitors: the eight open defects of ROADMAP §3.26**, still open in code. `grace_period_hours` is never saved (`monitors/store.py:164-165` writes only `reanchor_window`; every monitor runs on the 4-hour default, `models.py:40`); the anomaly runner z-scores a category breakdown as days. | re-checked | recorded, open |
| D6 | **Cause and effect in two stores.** `ontology/impacts.py` and `data/causal_graph.json` (`lifecycle/causal.py`, read by `monitors/alert_summary.py:147`). | re-checked | new |
| D7 | Stale words: `mcp/policy.py` says "eighteen static tools" over a table of 23; `routers/builder_v1.py:7` says "(off)" of a graduated flag. | re-checked | new |

D1 and D2 belong in the first arc because they decide whether the security Aughor already built means anything.

---

## 3. The recommendations, ranked

Ranked by value to Aughor × fit with its laws × size. Every new behaviour is behind a flag that is off by
default; the names are proposals. Sizes: S ≈ a day or two, M ≈ a week, L ≈ more.

| # | Build | Why it matters | Size | Proposed flag | Depends on |
| ---: | --- | --- | --- | --- | --- |
| 1 | **One row policy at every door.** Apply the release's row policies and sensitive properties at the SQL gate; filter edit history by reader; retire `ROW_POLICIES` once a receipt matches the object doors' counts | A policy that holds at one door is not a policy. Fixes D1 and D2 | M | `ontology.security_sql` | `ontology.security`; sign-in for a live receipt |
| 2 | **Every outside caller is someone.** MCP over HTTP accepts a service principal or a user bearer, and every call runs as that caller; a principal carries entity and action allowlists and area scopes (`objects:read`, `actions:propose`, `analysis:run` …), and the contract it reads is generated from the same grant | Two MCP clients look identical to the agent policy and the audit today (`mcp/client.py:93-95`, one shared `AUGHOR_MCP_TOKEN`) | M + M | `mcp.caller_principals`, `security.principal_scopes` | `security/service_principals.py` (exists) |
| 3 | **Every change says what made it.** Stamp the agent's `config_rev` on every answer and receipt; stamp the run and trace id on edit history and on the action audit; give automations and monitors versions and stamp each run with the version it ran under | Provenance is Aughor's first law; today an answer cannot say which revision of the agent gave it, and an edit cannot say which automation run made it | S + S–M + M | `agents.revision_on_answers`, `actions.run_attribution`, `automations.versions` | `kernel/lifecycle.py`, `custom_agents/revisions.py` (precedents) |
| 4 | **An App publishes one version.** Readers see the published version; later keeps are drafts until published | Today an edit carries its audience to the next version (`dashboards/versions.py:366`, "an edit does not unpublish"), so readers see every keep at once. Foundry separates deployed from latest | S–M | `dashboard.app_versions` | the existing lifecycle — **a decision for you, §8** |
| 5 | **Alerts that close, and rules that act on each object.** A breach records *recovered* when it comes back within its limit; a new condition fires for each object a rule or segment newly admits | Today an alert never closes, and a rule defines a population but cannot act as an object enters it | S + M | `monitors.recovery`, `automations.objects_admitted` | D5 first |
| 6 | **The ontology can be searched.** Declarations become nodes in the existing graph search; ⌘K finds an object by name across entities and says how many it searched; document search gets a lexical fallback and says when it failed | Nothing searches the declarations by meaning, and an object cannot be found without knowing its entity | S + S + S–M | `graph.declarations`, `objects.find`, `knowledge.hybrid_documents` | — |
| 7 | **A choice can leave its piece.** Typed references to objects and sets (`<type>:<key>` — the form the builder doors already use) dragged or sent "Open in" to the Data Canvas ("ask about these"), a choose-one piece or an object page, compiled through the object door under the reader's row policy | Today a selection cannot leave the piece it was made in | M | `canvas.ask_about_chosen` | release pinning (OC-2) |
| 8 | **Removing something from the ontology is safe.** Put back an earlier version into the draft; a *retiring* status with a successor and a date; reads per entity over 30 days | Aughor's change control is stronger than Foundry's, but it lacks the three things that make a removal safe | S + M + S–M | `ontology.put_back`, `ontology.retiring`, `ontology.usage` | `ontology/history.py` |
| 9 | **A set becomes a named segment.** "Keep as a segment" declares a dashboard set through the draft; the builder shows each set as its chain with a count at each step | Sets live only inside one dashboard, and no one can see where objects dropped out | M + S | `ontology.set_segments` | `dashboard.variables` |
| 10 | **Operations you can see.** Failure rate over a window on the hub map; log search across runs; the audit feed with a time window, a cursor and export; a required reason on payload reads | The pieces exist per run; nothing reads across runs, and the audit feed stops at 1,000 rows with no window (`routers/governance.py`) | S + S + S–M | `hub.failure_rate`, `obs.log_search`, `govern.justifications` | — |
| 11 | **Packs as products.** Record the installed pack version and the inputs a person declined; "upgrade to vN" shows the input diff; a pack may carry a dashboard template a person keeps | The version stored with a binding is whatever the caller sends (`routers/packs.py:296-297`), and there is no upgrade path | M + M | `packs.installed_versions`, `packs.dashboard_templates` | — |
| 12 | **Any SDK can call an agent.** A chat-compatible endpoint where the model is an Aughor agent and the receipt rides in metadata; a grounding read that returns what an agent would read without calling the model | Programs built with any agent SDK reach Aughor only through MCP today; `/ask/context` exists but no door reaches it | M + S | `doors.chat_completions`, `agents.grounding_read` | item 2 |

**Next after these:** an App takes values from its address or an embedding host (the July study's module
interfaces, M–L, mockup first); MCP tool search and `platform_help` on MCP (S); a neighbourhood view on the object
page (M); interfaces declared by a person (M); reading objects under a past release (M); proposed agent revisions
— try variants against certified goldens and stage the best in Approvals, the Evolve pattern (M, after goldens
exist and your call); an organisation's own help shelf (S); exporting a dashboard's Questions as one dated document
(S); offering the piece picker when the In-words door must refuse (S).

### 3.1 Three arcs

**Adopted 2026-10-24** as Arc ED, Arc TC and Arc FA — ROADMAP §3.58–§3.60 and §6 item 52, which are now the plan
of record; `PENDING.md` item 58 tracks them. The roadmap's waves add two things this study listed under §5 and D6:
ED-5 folds the second cause-and-effect store into impacts, and ED-6 gives every object read its completeness.

1. **Trust holds at every door** — D1–D7, items 1, 2 and 4. Mostly small; it makes the security, the outside
   access and the sharing Aughor already built mean what they say.
2. **Every change traceable** — items 3, 5 and 10. One theme: a reader can go from any edit, alert or answer to
   the run, the version and the cost behind it.
3. **The ontology people can find and act on** — items 6, 7, 8, 9, 11 and 12. The feature work.

---

## 4. Area by area

Each line: what Foundry does · what Aughor has · what to do. Foundry pages are under
`https://www.palantir.com/docs/foundry/`.

### 4.1 Agents and outside access

- **Ontology MCP** (`ontology-mcp/overview/`): one app becomes an MCP server; every action type is a tool; access is
  the app's OAuth client acting as a user or a service user. · Aughor's server already serves agents and actions as
  live tools with an agent policy, but every HTTP client is one principal. · **Item 2.**
- **Palantir MCP** (`palantir-mcp/overview/`, `tool-search/`): 70+ builder tools; tool search on by default, ranked
  locally with no model call; no destructive tools. · Aughor's write posture already matches (proposals only); its
  tool list grows with every agent. · Tool search and `platform_help` on MCP, after counting the live list.
- **Pro-code agents** (`agents/overview/`): agents written with the Claude, OpenAI or Google SDKs, published as
  functions. · Refused here (ROADMAP §4.4, a TypeScript agent runtime); doors already reach Aughor's agents. · An
  outside agent gets its own service principal and a config on the agent's Doors tab (rides item 2).
- **AIP Chatbot Studio API** (CSV): sessions pin an agent version; a `ragContext` call returns what was retrieved
  without the model; traces return tool-call groups. · Streaming and blocking continue already match. · **Items 3
  and 12.**
- **AIP Evolve** (`aip-evolve/overview/`): a fleet tries changes against a goal and limits, then proposes. ·
  Experiments over model × flags exist (`evals/experiments.py`); nothing searches agent variants. · Later, after
  certified goldens exist.
- **Boardroom, Threads, Assist, Document Intelligence**: low value or already covered (delegation, chat sessions,
  `platform_help`, the fail-closed converter). Two small items: an organisation help shelf; a dashboard's Questions
  exported as one document.

### 4.2 The ontology

- **Ontology Manager** (`ontology-manager/save-changes/`, `view-usage/`, `cleanup/`): restore a type to an earlier
  version; usage per type over 30 days; a cleanup queue with deprecation dates. · Draft → release with classed
  changes and restated claims is stronger; put back, retire and usage are absent. · **Item 8.**
- **Object permissioning** (`object-permissioning/object-security-policies/`): object and property policies give
  cell-level control; a reader who fails a property policy sees null. · OC-7 has the same shape and states what it
  masks, but holds at one door only. · **Item 1.**
- **Semantic search** (`ontology/overview-semantic-search/`): vector properties and nearest-k object sets; skip search
  when everything fits. · One vector seam, hybrid vector + BM25 for the knowledge base; RRF was measured worse and
  deleted. · **Item 6.** Do not embed customer object text — that is a second copy of the rows.
- **Object Explorer** (`object-explorer/getting-started/`): search objects across types, charts as filters, compare
  two sets, run an action on up to 1,000 selected. · Object pages, set algebra at the door; no cross-entity search.
  · **Item 6** (find), a compare piece (S).
- **Insight** (`insight/core-concepts/`): a path of cards with an object count at each, published as an object set. ·
  Sets read other sets, but their steps are hidden. · **Item 9.**
- **Vertex** (`vertex/explore-object-relationships/`): a graph grown by "search around", scenarios against a
  baseline. · Impacts, scenarios and a dry run exist; no picture of one object's neighbourhood. · Neighbourhood view
  later; fold `causal_graph.json` into impacts (D6).
- **The Ontologies API** (CSV): object sets as handles, interfaces, value types, edits history with paging,
  `branch` / `scenarioRid` / `transactionId` on reads and actions, aggregates that declare their accuracy. · Sets are
  structures inside a query (keep it so); interfaces are detected, not declared; edits history is fixed at 200 rows;
  reads are stamped with their release but cannot be read under a past one. · §5.

### 4.3 Operations

- **Object Monitors, retired into Automate** (`object-monitors/overview/`): Foundry consolidated its watchers into one
  automation product. · Aughor did the same and goes further (backtest, drill, proof, the review of what was missed,
  the Watcher's proposals). · **Item 5** (recovery), D5.
- **Foundry Rules** (`foundry-rules/object-model/`): rules as objects with logic in a fixed grammar; edits as
  proposals the rule's owner approves. · Rules are declarations, preview equals execution; release is published by
  anyone with `ONTOLOGY_EDIT`. · **Item 5** (objects admitted).
- **Workflow Builder** (`workflow-builder/core-concepts/`): live previews on real objects; "send to preview" replays a
  past run; version history. · Same grammar and a dry run; runs keep no trigger payload and automations no versions.
  · **Item 3**, then "replay a run as a dry run" (S).
- **Autopilot** (`autopilot/object-timeline/`): an object timeline crediting each edit to a person, an agent or an
  automation, with its cost. · The edit layer records the actor, not the run. · **Item 3.**
- **Workflow Lineage and observability** (`workflow-lineage/getting-started/`, `aip-observability/log-search/`):
  failure rate per node with "no runs" and "no permission" kept apart; log search across executions. · Three lineage
  walkers already exist — do not add a fourth; traces filter by status, user and cost but logs are per trace. ·
  **Item 10.**
- **Data Health, Orchestration, Checkpoints, Audit APIs** (CSV): checks with a free-text intent and latest reports;
  versioned schedules whose runs name their version; justification records; audit log files by date. · **Items 3, 10**
  and D3.

### 4.4 Apps and the developer platform

- **Pilot** (`pilot/overview/`): prompt → generated entities, React code and seed data. · Refused here for good reason
  (ROADMAP §6 item 50(d), "nothing hosted runs code"); Aughor's In-words door is the safe half. · Copy only "pause and
  ask": offer the piece picker when the door must refuse.
- **Custom widgets** (`custom-widgets/core-concepts/`): typed parameters and events in a sandboxed iframe. · No code
  extension point, by decision. · Take the reverse direction: an App as a widget others embed, with typed values from
  the address or host (next after item 12).
- **Cross-application interactivity** (`cross-app-interactivity/drag-and-drop-overview/`): typed drag payloads for
  objects and sets; app pairing; commands. · One object address; an untyped navigation intent. · **Item 7.** Not
  commands fired on a value change — a dashboard runs nothing without a click.
- **OSDK React applications** (`ontology-sdk-react-applications/osdk-react/`): an SDK generated for the resources an
  app was granted. · The contract exists; every program is handed the whole published scope. · **Item 2**, and
  release-published and proposal-decided events through the departure gate (S).
- **Third Party Applications, Marketplace, scopes** (CSV): deployed ≠ latest; versioned installs with inputs; 52
  OAuth scopes. · **Items 4, 11, 2.**

---

## 5. API design choices to adopt

Measured in the Foundry API table; each one fits a law Aughor already holds.

- **Say how complete a read is.** Foundry aggregates take `accuracy` and answer `ACCURATE` or `APPROXIMATE` with
  `excludedItems`. Aughor's object doors carry a truncation boolean. Add one typed `completeness` field to every
  object door and to the contract — complete · truncated · withheld by policy · refused over a cap — and its time
  taken. S. (Withheld is said, never implied.)
- **Stamp the version on everything that has one.** Foundry pins agent versions on sessions, function versions on
  calls, schedule versions on runs. Aughor stamps releases on reads; extend it to agents, automations and Apps (items
  3, 4).
- **Read under a past release.** Foundry reads and acts at a `transactionId`. Aughor marks a claim as computed under
  an older release; a `release=` parameter would let it recompute. M.
- **Scope programs by area.** 52 scopes against Aughor's 10 person permissions and one level per program; area scopes
  intersected with the agent policy and the acting person, never widening (item 2). Skip per-operation scopes.
- **Page with a cursor.** 52 Foundry operations page with `pageToken`. Aughor's edit history is fixed at 200 rows and
  the audit feed at 1,000; give both a cursor.
- **One reference form.** Foundry names every resource by a typed id. Aughor should not migrate every store; it should
  use the `<type>:<key>` form the builder doors already use at every new seam — drag payloads, events out, App values.
- **Retrieval you can inspect.** Foundry's `ragContext` returns what an agent would read without the model; Aughor's
  `GET /ask/context` does the same for the ask path and should be reachable for an agent (item 12).

---

## 6. One concept, two stores

AGENTS.md: "Before adding a store, search for the four that already do most of what you want." This comparison found
three places where Aughor already holds one concept twice, and one where it must not add a third:

- **Who may see a row:** `ontology/security.py` (OC-7) and `rbac/row_policy.py` → item 1 makes the release's policy
  the one authority.
- **Cause and effect:** `ontology/impacts.py` and `data/causal_graph.json` → fold the confirmed edges into impacts as
  `validated`, then retire the file (D6).
- **Reasons people give:** payload reads, exports and prompt windows each keep their own → one catalogued event kind
  under `data_access` (item 10).
- **Lineage:** `govern/lineage.py`, `ontology/dependents.py` and `automations/graph.py` already walk it → read failure
  rates onto the existing hub map; do not write a fourth walker.

---

## 7. What not to copy

- **A raw query tool for agents**, and actions that execute without a person — Aughor's agent proposes.
- **Hosted code of any kind**: widget bundles, generated apps, agent runtimes, OSDK hosting (ROADMAP §4.4, §6 item 50(d)).
- **Generated entities and seed data** — rows with no source break the provenance law.
- **A model's verdict presented as a fact**: vision-graded extraction, a model explaining a trace. Aughor's trace
  summary is composed by code.
- **Embedding customer object text**, HyDE, and RRF (measured worse here).
- **Commands fired when a value changes**, and chains that continue past a failure.
- **Agent teams as a product** (ROADMAP §4.9), forced monitor expiry, per-user ontology working states, static key
  lists, an SQL sandbox whose output leaves the ontology, a graph database, and classification machinery.

---

## 8. Decisions for you

1. **Should an App's readers see a published version rather than every keep?** Today an edit carries its audience
   forward, deliberately. *Recommended:* yes, one published version per App, the next keep a draft until published.
2. **Which arc first?** *Adopted in the order proposed (§6 item 52).* *Recommended:* "trust holds at every door". Its defects are latent — they cost nothing today
   and become real the day `ontology.security` graduates or a second MCP client connects.
3. **Programs calling agents through a chat-compatible endpoint (item 12):** wanted now, or when a customer asks
   (the same rule ROADMAP applies to a client library)?
4. **Proposed agent revisions:** start once agents have certified goldens, or not at all?
5. **Adopt into the roadmap:** *Done 2026-10-24 — §3.58–§3.60, §6 item 52, PENDING item 58.* record the three arcs in ROADMAP §3 and the defects D1–D7 in PENDING.md?

---

## 9. What was checked, and what wasn't

**Re-checked by hand in the tree at `f7af0167`:** OC-7 at the object door and the separate empty `ROW_POLICIES`
(D1); the edit-history route's scoping (D2); quality results read but never written outside the package (D3); the
`[]` on exception (D4); `grace_period_hours` absent from the store and its 4-hour default, and ROADMAP §3.26's open
list (D5); the 23-entry MCP tool table (D7); one MCP principal from env (`mcp/client.py:93-95`); a declared action's
single description; `config_rev` read only by the agents router; `read_shared` reading the latest version and edits
carrying `published_to`; the pack binding's caller-supplied version; the audit feed's 1,000 cap; the second cause-and-effect store (D6); the legacy schedulers' deletion
(`kernel/flags.py:252-257`); cards and canvases on the lifecycle; the release refusing an unconfirmed model proposal;
ROADMAP §4.4, §4.9 and §6 item 50(d).

**From the cluster readers, not re-checked:** the three lineage walkers; the absence of object
search across entities; interfaces being detected rather than declared; the edit-history page size; automations'
run payloads.

**Not known:** live flag values (no HTTP call was made); how much of quick answers about entities pass through the
object door versus raw SQL, which sets how much item 1 changes in practice; whether a signed-in session works inside
a third-party frame; Foundry behaviour marked "where enabled" or beta in its docs. The Automate pages that replace
Object Monitors were not in the page set.
