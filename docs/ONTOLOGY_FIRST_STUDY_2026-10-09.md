# Ontology-first — the implementation roadmap, read against Aughor

**Status: STUDY, 2026-10-09. Nothing built, nothing adopted, nothing written into `ROADMAP.md`.** Written at the
user's ask on 2026-10-09: *"We thoroughly need to study this document and maybe some external sources in order to
truly gauge how we can make our platform an ontology first platform… Study it hard."* The document is
`ontology_first_platform_implementation_roadmap.pdf` — *Implementation Roadmap: designing an ontology-first platform
for building operational applications*, 11 pages, read in full.

**How it was measured.** Code read on `44dee14f` (main) by three read-only passes, one per half of the document and
one over the plan of record. Live figures read over HTTP from the user's install (API pid 84352, served from the
main checkout at `4f97e18f`) — cache-only ontology reads and the Record's list doors, no model call, no warehouse
statement, no sqlite opened on live state. One defect proven by a hermetic run (§6). External sources read the same
day, cited where used (§7); the five vendor claims the conclusions lean on were re-read on the vendors' own pages
(marked ✔). A reference to the plan of record is written *ROADMAP §n*; a bare *§n* is a section of this study.

**The user's reason, in their words** (dictation errors corrected in brackets): *"…each of these become part of the
company processes. And when you say processes there are no[d]es and there are connections or flows between those
no[d]es. Collectively these multiple no[d]es and the flows between them is an ontology. Each no[d]e is an object and
each flow is the nature of the relation, purpose of the relation, and forward and backward and impact on the
no[d]es… the one who owns the [ontology] and leverages it [builds] even more robust organisational intelligence…
eventually we will reach a stage where we will also build apps within the platform and also deploy them on the
platform."*

---

## The answer, on one page

1. **Aughor already has most of what the document calls an ontology.** Object types with stable api names and
   measured keys; links with measured cardinality and business verbs; static, timeseries and detail bindings, across
   connections; expression, computed, frame and rollup properties; segments; processes with promises and rules,
   measured through a compiler; declared actions with typed parameters, criteria, approval, standing grants,
   verification, undo and earned authority; zero-config object pages; a model that drafts and a person who confirms.
   Two things the document has no word for are Aughor's own: **promises measured against the data**, and **a scored
   record of what the organisation believed, decided and got**.

2. **What Aughor does not have is the document's central idea — the ontology as the platform's contract.** Measured:
   - **No version, no release, no history.** A saved declaration overwrites its file, a withdrawal deletes it, and no
     event records either (§6.2) — the one place the repo's *supersede, do not delete* invariant does not hold.
     Nothing checks who depends on a definition before it changes; the delete door the wave text promised would
     refuse "where a consumer depends on the id" does not.
   - **Meaning lives in about nine stores keyed to tables and columns** — the metric registry, profile north stars,
     glossary, vocabulary, trusted queries, column config, monitors, cards, automation triggers. The Cockpit and the
     Briefing import nothing from the ontology. For metrics, the ontology is the *lowest*-precedence source.
   - **The live install barely uses it.** 35 of 35 object types are one table each. One declared action exists. 192
     of 192 claims in the Record are about a whole connection — none about an object, a segment or a type — and none
     cites a definition version, though the field exists.

3. **So "ontology-first" here is a re-centring, not a rebuild.** Five moves, in this order:
   1. give the ontology a **history and a release** that every consumer pins, with an impact check before any
      change — and treat a change of meaning as a **restatement** the Record already knows how to deliver;
   2. **key every meaning-bearing store to ontology ids**, starting with the ones that already half-carry them
      (a claim's `about` and `definition_version`, a metric's grain);
   3. put **ontology-bound pieces where people already work** — an object table, a process board, an action button,
      in the Cockpit — so a declaration pays off the day it is made;
   4. make the user's **process view first-class**: a link's *purpose* (the process it carries) and a flow's
      *impact* (what a change on one node does to another), each with its method on the scenario ladder;
   5. **finish the action engine where apps need it** — versions, an outbox on the job table, transitions, an edit
      layer with history — and only then, if an app needs a unit of work no source holds, object types the platform
      itself owns.

   A generated SDK and a second domain come last, as the document itself orders them.

4. **Three of the document's premises do not transfer, and should not be copied.**
   - *Materialise objects first.* Aughor's law is that rows never move; the object door compiles to the source, and
     its measured cost was accepted (§3). Even Palantir, which added objects over virtual tables in 2025, still
     re-indexes them into its own store (§7.1) — a federated object layer is a real difference, not a gap.
   - *Agents work through the ontology's own query language.* Measured here: a model writing object queries did
     worse than raw SQL (1/14 against 14/14; 3/12 against 12/12); prose about the ontology lifted nothing; resolving
     a question's terms to *declared* definitions before analysis did lift (8 against 3; 9 against 1; 11 against 4
     and 13 against 2 on a second model). Palantir reached the same place from the other side: its agent door now
     gives agents **SQL over the ontology** (§7.1). The ontology is the agent's compiler and checker, not a new
     language for it.
   - *The ontology is the moat.* The 2027 study ranked "the ontology as such" tenth of eleven; the declared, measured,
     relied-on part — terms, promises, owners — third; the record built on it first. **Ontology-first in Aughor means
     declaration-first and contract-first**, which is the 2027 thesis applied, not reversed.

5. **Two calls are the user's before anything is built** (§10): whether apps may keep **state of their own** inside
   the platform (an edit layer first; platform-owned object types only if needed — this narrows the 2027 study's
   "not a system of action" for the platform's own objects, and moves no customer row); and **what an app is** — a
   published cockpit over ontology-bound pieces and declared actions, inside the existing rail. A custom-code path
   with a public SDK reopens the 2027 study's "the app is the pack" and "no public SDK", and is recommended later,
   not now.

6. **Found on the way** (§6): the action plane drops every declared action's verification, undo and reversibility on
   read-back — proven by a hermetic run — so no side-effect action can graduate or be undone, and the web form cannot
   declare one at all. Six more defects by reading, one line each.

---

## 1 · What the document says

A faithful digest; the PDF is the authority.

- **Objective.** Represent an organisation's operational reality as a *governed* ontology, and build applications,
  workflows and agents on it. "The ontology, its data integration layer, and its execution infrastructure come
  first"; the application builder "should not be the first major investment."
- **Layers.** Apps (generated, custom, dashboards, workspaces) → the ontology and its operational API (objects,
  properties, links, queries, actions, functions, events) → data infrastructure and execution infrastructure
  (transactions, jobs, integrations, events) → cross-cutting identity, authorization, audit, versioning,
  observability. The ontology, it says, is not a diagram of the data but *"the contract between underlying systems
  and the applications"* that run on them.
- **Five primitives.** Object types; links (direction, cardinality, semantics, integrity); properties (types,
  nullability, units, constraints, source mappings, freshness, computed expressions); actions (typed inputs,
  preconditions, authorization, execution behaviour, outcomes); functions and derived values.
- **Separate** definitions (versioned metadata, never frontend code) · instances (stable identity across renames and
  source changes) · source mappings (several sources, precedence, joins, lineage, freshness, invalid values; identity
  resolution explicit — "similar names do not prove records refer to the same entity") · operational changes ·
  execution rules.
- **Engine before builder.** Metadata service · object data service · relationship and query engine · action and
  execution engine · security and audit. Start on PostgreSQL; add a graph engine only on measured need.
- **Authoring is the product.** An Ontology Studio (model graph, object editor, source-mapping editor, relationship
  editor, action designer, preview and validation on real objects, version and release management); top-down and
  bottom-up; "do not automatically equate a database table with an object type"; a seven-step guided workflow; AI
  proposals reviewable, "not silent production schema modifications."
- **An ontology compiler.** Parse and validate → dependency graph → execution plan (storage and index config,
  mapping config, API and SDK metadata, app metadata, validation and test cases) → publish an immutable version.
  It ranks the compiler above any diagramming tool because it makes modelling *"repeatable and testable"*.
- **Materialised versus federated** — use both, start materialised. A typed object query contract; bounded
  traversal.
- **Actions are first-class.** A contract (identity and version, parameters, target, preconditions, authorization,
  effects, execution policy, audit); local changes separated from external effects through a transactional outbox,
  at-least-once delivery and idempotent consumers; explicit state transitions enforced by the backend — "hiding a
  button is not a security boundary."
- **Authorization in the runtime** — identity, object, property, action, context, purpose; deny by default; agents
  with explicit identities and scoped permissions; "natural-language instructions must never bypass action
  authorization."
- **Versioning.** Draft → Validated → Published → Deployment; a compatibility table; the compiler names affected
  apps, functions and actions before publication.
- **Apps on the ontology.** A metadata-driven UI runtime (object table, detail view, relationship explorer and
  timeline, map, action form, metrics and task lists) from a declarative, versionable spec validated against the
  ontology and the viewer's permissions; a visual designer; a custom-code path through a generated TypeScript SDK.
- **Phases.** 0 domain design (weeks 0–4) · 1 ontology core (months 1–3) · 2 Studio (3–5) · 3 operational execution
  (4–7) · 4 app runtime and builder (6–9) · 5 expansion and a second domain (9–12+).
- **AI accelerates creation, never runtime correctness.** Hardest problems: identity resolution, synchronisation and
  provenance, schema evolution, consistent security, operational correctness, query performance.
- **Success metrics** — time to create a type, time to map a source, mappings validated automatically, time to build
  an app from existing types, apps reusing types and actions, query latency, action success and reconciliation
  backlog, breaking changes caught before publication, authorization coverage.
- **Not in the first version** — a universal graph database, a distributed workflow engine, hundreds of connectors,
  a general agent platform, arbitrary generated application code, enterprise simulation, multi-region, a low-code
  editor for everything.
- **The principle.** Not a feature inside the platform but *"the platform's central contract"*: integration
  populates it, the query engine exposes it, the action engine changes state through it, security governs it, the
  builder turns it into interfaces, the SDK exposes it, AI helps create and operate it.

The document is explicitly "inspired by publicly described ontology-first platform concepts" — Palantir's — and says
its APIs are illustrative.

---

## 2 · The user's framing, made precise

The user describes a business as **processes**, each made of **nodes** and **flows**, where a flow carries four
things. Mapped onto what exists:

| The user's word | What it means | In Aughor today | Gap |
|---|---|---|---|
| **Node** | a thing the business runs on | an object of an object type (`OntologyEntity`, `aughor/ontology/models.py:327`) — federated, read live | types are tables by construction (§5) |
| **Nature of the flow** | what kind of relation it is | a link: from, to, cardinality declared *and measured*, a business verb (`OntologyRelationship`, `models.py:484`) | 15 of 37 live links carry a verb |
| **Forward and backward** | the relation read both ways | `api_name` and `reverse_api_name`; a declared link has a reverse name | none |
| **Purpose of the flow** | why the relation exists — which process it carries | implicit: a process stage reaches its timestamp through a link path (`shipment.ship_date`) | not recorded on the link |
| **Impact on the nodes** | what a change on one node does to another | not declared anywhere. The frame proposes candidate drivers by *link hops* (ON-10), which is structure, not impact | absent |
| **Process** | the nodes and flows in order, with what is promised | a declared process: ordered stages anchored to timestamps or states, promises with measured breach rates, rules (ON-9) | single-entity anchored; no declared transitions |

Two consequences shape everything after this section.

- **The process is where flows get their purpose.** A link that a stage reaches through *carries* that process; that
  can be read from declarations that already exist, with nothing new to author (§8.4).
- **Impact is the one genuinely new primitive** the user is asking for, and it is also the one the field lacks:
  Palantir's links are navigational and its process mining documents no promise (§7.1); Aughor's promises already
  measure breaches. An impact is a declared expectation between two nodes — *a late dispatch on an order line raises that
  order's chance of a late delivery* — measured like a promise, and carried with its **method** on the 2027 study's
  scenario ladder (declared → history → intervention). Without a method it is an assumption, and the departure gate
  already holds causal wording that has no licence.

**"Organisational intelligence" is two layers, not one.** The business layer — what exists and how it flows — and
the record layer — what the organisation believed about it, decided, did, and got (claims, decisions, actions,
outcomes, missions, scenarios; the 2027 study §G: *"Objects and Events are what every Claim is about"*). The document
describes only the first. The second is where the 2027 study put the moat. An ontology-first Aughor is the first layer
made into a contract so that the second can attach to it — which, on the live install, it does not yet (§5).

---

## 3 · Premise checks — what transfers and what does not

| The document's premise | Aughor's law or measurement | Verdict |
|---|---|---|
| **Start with materialised objects** (the document's §6.1) | "No object store, no sync" — reopened only on a measured latency a cache cannot cover (ROADMAP §3.15 laws; ROADMAP §6 item 14). Rows never move (2027 §F). Measured: object pages read live; a cross-source answer took 1.4–5.2 s against 43–66 ms as one statement, and the posture held | **Does not transfer.** Keep source-backed objects federated. Store only what the platform owns. Show freshness as the source's own (§8.2) |
| **The action engine changes operational state**, local transaction plus outbox (the document's §7) | 2027 §M: "The platform does not become a system of action. An action is a reference…". ROADMAP §4.7: nothing is written to a customer's warehouse. The only local state an action changes is the edits overlay, and an edit may only *add* a property the source lacks | **Transfers for the platform's own state only.** Apps need state of their own — decision (b) |
| **Agents operate through the ontology** (Palantir's posture when the July study was written: no raw SQL) | Prose ontology in prompts: no lift (R4 regressed, 58% with five silent-wrong against raw 92%; ON-0 13/14 = 13/14; ON-0a 13/14 against 14/14). Model-written object queries: 1/14 and 3/12 against raw 14/14 and 12/12; re-measured 7/15 and 10/16 against framed 14/15 and 16/16. Framing to declared definitions: 8 against 3, 9 against 1; on a second model 11 against 4, 13 against 2 | **Transfers as framing, compiling and checking — not as a language.** Palantir's own agent door now hands agents SQL over the ontology (§7.1) |
| **AI proposals are reviewable, not silent** (the document's §5.3 and §12) | The explorer's proposals are measured and then *served at once* as `origin: model`, "proposed"; explore-on-connect is on by default (turned on 2026-09-24 over its unmet quality gate — precision 0.67, recall 0.89) | **Transfers through a release**: proposals live in the draft; the published release holds what a person confirmed — decision (f) |
| **The ontology is the differentiator** | 2027 moat ranking: "the ontology as such" 10th of 11; "declared organisational context" 3rd; the decision-and-outcome history 1st | **Transfers as declaration-first.** The ontology matters as the place declarations live and the record attaches |
| **The builder comes last** (the document's §0 and §11) | ROADMAP §7: "Features stall at TESTED, not at LEVERAGED." Live: one declared action; 35 of 35 types are tables | **Partly.** No builder early — but the first ontology-bound *consumer* must arrive early, or declarations stay unmade |
| **Not a general agent platform** (the document's §15) | Aughor is agent-native; the roster is frozen (ROADMAP §4.9 #3) | No conflict |
| **Apps: a metadata runtime plus custom code on a generated SDK** (the document's §10) | 2027 §Q: "The platform's equivalent of an app is the pack… UI: cards only… No arbitrary interface code"; the same study's line 186: "no public SDK"; Arc CT refused "any action a spec defines" | **The visual path transfers** — actions by reference to declared ones is the existing law ("an action names an EXISTING governed door"). **The custom-code path reopens §Q** — decision (d) |

---

## 4 · The crosswalk — measured

State as of `44dee14f`. BUILT means a door, a store and a consumer exist; PARTIAL names what is missing.

### 4.1 The ontology core

| The document | State | Evidence | Note |
|---|---|---|---|
| Object types: identity, stable api name, key | BUILT | `models.py:327-464`; key measured (`theLook Order: 124,987 distinct over 124,987`) | built types are tables by construction (`builder.py:852-918`) |
| Validation rules, constraints, enums, required, value types | ABSENT | — | nullability is a measured null rate; `unit` is free text |
| Links: direction, cardinality, semantics | BUILT | `models.py:484-557`; cardinality measured at build | 36 of 37 live links measured, all agreeing with what was declared |
| Link integrity, link properties, N:N through a junction | ABSENT · ABSENT · REFUSED | — | the compiler traverses only measured, non-N:N links |
| Properties: computed, expression, timeseries, frame, rollup | BUILT | `models.py:25-68,202-264`; `ontology/expressions.py`; ON-1b, ON-5 | model scores on objects were never built (`PENDING.md:78`) |
| Per-property source of truth, freshness, behaviour when unavailable | ABSENT | `bindings.py:99-104` first binding wins; a source that cannot be read is refused | `settling/` learns a lag per table; no ontology code reads it |
| Interfaces (polymorphism) | PARTIAL | `models.py:466`; detected from column-name patterns (`builder.py:707`) | served, never queried |
| Functions with declared dependencies | PARTIAL | `object_query.py:778-800` parses dependencies at compile | no code functions; registered methods run outside (`record/methods.py`) |
| Metadata separated from instances | BUILT | instances are never stored; edits in their own store (`actions/overlay.py:32-35`) | |
| Mappings separated from definitions | PARTIAL | `backing` and `bindings` live inside the type's declaration (`overrides.py:163-171`) | measured verdicts are written back into the same files (`store.py:204-273`) |
| Identity across renames | PARTIAL | `api_name` never overwritten; built ids come from table names | a renamed table strands its overrides ("entity not in graph", `overrides.py:770`) |
| Instance identity resolution | ABSENT | ON-8 meets keys by exact canonical string (`ontology/sources.py`) | dedup is *type*-level only (`dedup.py`) |
| Ontology metadata service | BUILT, unversioned | 79 routes in `routers/ontology.py`; 8 in `routers/objects.py`; 12 in `routers/kinetic.py` | nothing hardcoded in the web |
| Typed object query contract | BUILT for aggregates | `POST /objects/query` (`object_query.py:93-141`): 13 filter operators, ≤3 hops, limit ≤10,000 | **no listing**: at least one measure is required and there is no offset; the web never calls it |
| Bounded traversal | BUILT | measured links only, ≤3 hops, fan-out refused by construction | no precomputed results; no caching on object paths |
| Model graph, object editor, mapping editor, relationship editor | BUILT | `web/components/ontology/EntityTypeMap.tsx`, `EntityTypePanel.tsx` (1,893 lines) | semiadditive declarations are API-only |
| Preview and validation on real objects | PARTIAL | every declaration measured at its door; object pages | no whole-draft preview |
| Version and release management | ABSENT | — | §6.2 |
| The compiler (parse → dependency graph → plan → immutable version) | ABSENT as a whole | per-declaration `*_problem` validators; per-query `_Compiler` (`object_query.py:618`); `validator.py`; a CI test that every shipped declaration compiles (ROADMAP §3.45) | nothing derives API, SDK, app metadata or tests |
| Dependency and impact analysis | ABSENT for the ontology | `govern/lineage.dependents_of` walks tables → findings, metrics, briefs | withdrawing a declared type runs no consumer check (`routers/ontology.py:1761-1788`) |
| AI proposes, a person confirms | BUILT · served before confirmation | explorer (`ontology/explorer.py`); confirm, withdraw, restore doors | the organisation's ontology is people-only, ratcheted (ROADMAP §6 item 20) |
| Materialised and federated | federated only, by law | `object_instances.py:4-6` | |

### 4.2 Actions, security, apps, doors

| The document | State | Evidence | Note |
|---|---|---|---|
| Action identity | BUILT | `models.py:986-988`; stored as `{conn}/{schema}/action/{id}.yaml` | |
| Action **version** | ABSENT | no field; accepting a proposal loads the *current* definition (`inbox.py:756`) | |
| Typed parameters, object targets | BUILT | `ActionParameter` (`models.py:777-799`); objects resolved live (`executor.py:231-252`) | one instance per parameter; no set or bulk target |
| Preconditions with authored messages | BUILT | restricted AST, fail-closed (`executor.py:94-155`) | cannot read overlay values (D5) |
| Effects | BUILT | overlay edits; `notify`, `webhook`, `http`, `trigger_investigation` (`models.py:870`) | never the source, by law |
| Verification, undo, reversibility, earned authority L0–L5 | BUILT in code · **lost in storage** | `authority.py:62-116,326-554` | D1, D4 |
| Execution policy (transaction, retries, timeout, idempotency) | PARTIAL | inline in the request, one attempt (webhook 10 s, http 20 s); staging idempotent on `(org, run_id, call_id)` | |
| Transactional outbox, worker, reconciliation | ABSENT | four separate SQLite commits (`inbox.py`, `overlay.py`, `grants.py`, `kernel/ledger.py`); `uncertain` is terminal | the job queue is in-process only (`kernel/queue.py:38-66`); Arc SR's jobs table is not on main |
| Optimistic concurrency on objects | ABSENT | overlay is last-writer-wins by authority rank (`overlay.py:150-171`) | cockpit drafts carry `base_version` |
| Declared state transitions on object types | ABSENT | lifecycle is mined (`aughor/lifecycle/mapper.py`), processes measured | enforced state machines exist only on platform artifacts (metric governance, proposals, jobs) |
| Audit | BUILT | `govern.audit` on every verdict; an Action ledger artifact per execution | no `object.changed` or `action.executed` event kind (`kernel/events.py`) |
| Identity: user, group, agent, service | BUILT · off by default | `security/authz.py:38-52`; `service_principals.py` | enforcement is a no-op unless `AUGHOR_REQUIRE_IDENTITY=1` and the tier has `RBAC_SSO` (`rbac/deps.py:93,100`) |
| Securables include ontology things | PARTIAL | catalog, schema, table, artifact, metric, promise, process, rule, domain, automation, agent, canvas (`metastore/models.py:143-172`) | no object type, property, link, action, instance or cockpit |
| Object (row) access · property access | ABSENT · ABSENT | `ROW_POLICIES = {}` (`rbac/row_policy.py:24`); clearances gate table-grade securables only (`govern/tags.py:190-193`) | |
| Agent scoping | BUILT | MCP and service-principal gate read · run · act; default `run`, so an outside agent cannot accept or execute (`rbac/agent_gate.py:105-141`) | natural language never bypasses criteria |
| Object detail view | BUILT, zero-config | `web/components/objects/ObjectView.tsx`; `GET /objects/{type}/{pk}` | actions *offered*, run elsewhere |
| Object table and filter builder · relationship explorer · map | ABSENT · PARTIAL · PARTIAL | type map and paths (`objects.py:298-380`); choropleth and point charts | |
| Declarative, versioned, validated app spec | PARTIAL — the cockpit | json-render catalog of five components, `actions: {}` (`web/lib/cockpit/catalog.ts:73`); validated in Node and on the server; versioned as ledger artifacts | cards bind to SQL, a metric, a trusted query or a finding — **nothing binds to an object type, a list of objects, a link or an action** |
| Publish to others | off main | publish to a group or role exists on the unmerged `claude/cockpit-canvas` branch (served live) | a cockpit is "theirs alone" on main (`docs/GLOSSARY.md:84`) |
| Generated typed SDK | ABSENT | `openapi-typescript` types only; `web/lib/api.ts` is 10,660 hand-written lines; object routes return untyped dicts | 2027 study: "no public SDK" |
| Versioned API | PARTIAL | only `/ledger/v1` | about 800 route decorators in 74 routers |
| MCP | BUILT, reads | 22 static tools; `describe_entity`, `search_graph` | no object query, no action tool |
| Events | PARTIAL | ~60 kinds, ratcheted; seven automation triggers, all but the inbound webhook *polled* on a 60-second heartbeat | `promise_breached` and `finding_created` are triggers |
| Packs as products | PARTIAL | ontology claims, metrics, function layer, templates; `kit.py:3-4` "the platform's equivalent of an app is the pack" | never ship declared actions or cockpits; no upgrade, migration or dependency resolution |

### 4.3 Where Aughor is ahead of the document

The document is a good outline of Palantir's shape. It has no answer to six things Aughor already does, and an
ontology-first Aughor keeps all six:

- **Every declaration is measured against the data**, not only validated as a schema — a key is a key because
  124,987 rows have 124,987 distinct values, a link's cardinality is counted, a promise has a breach rate.
- **Promises.** Lux's refund promise (10 days) is broken on 23.3% of returns; the measurement also flags 4,199
  refunds dated *before* the return was received — counted as kept "although impossible". Palantir's process product
  documents no promise at all (§7.1).
- **Framing** — the only measured accuracy gain in the repo, and deterministic.
- **Guarantees by construction** — fan-out refused, to-many pre-aggregated, semiadditive rules — plus the guard
  battery on everything else.
- **Actions that prove themselves** — a verification read after dispatch, an undo with a window, authority earned on
  receipts and withdrawn on a miss.
- **The record** — claims with warrants and two clocks, decisions with booked expectations, outcomes scored by code.

---

## 5 · The live install — the data, not the source

Read 2026-10-09 over HTTP from the user's install; cache-only.

| Connection · schema | Object types | of which a table each | with a detail binding | Links | with a verb | Processes | Promises | Rules | Declared actions |
|---|---|---|---|---|---|---|---|---|---|
| theLook `8233e4fd` · thelook | 7 | 7 | 2 | 12 | 8 | 1 | 0 | 1 | 0 |
| LuxExperience `914df862` | 14 | 14 | 2 | 18 | 7 | 2 | 2 | 7 | 1 |
| Olist `baef6c3e` · ecommerce | 9 | 9 | 0 | 6 | 0 | 1 | 2 | 2 | 0 |
| Superstore `8d36d4c2` | 3 | 3 | 0 | 1 | 0 | 0 | 0 | 0 | 0 |
| Workspace · uber_ncr | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| spotify `7611b995` | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **Total** | **35** | **35** | 4 | **37** | **15** | **4** | **4** | **10** | **1** |

- **Measured, and mostly verified.** Backing verified on 25 of 35 types; display property on 20; 36 of 37 links
  counted; 7 of 7 bindings, 50 of 50 segments, 11 of 14 computed properties verified; 304 of 329 properties
  described. The machinery works.
- **Declared, barely.** No type that is not a table exists anywhere live. The organisation's ontology holds two
  domains — four types, two links — and its one cross-source link joins LuxExperience to its own explorer copy. The
  one declared action (`flag_order_for_review`, Lux) is exactly the document's contract — typed object parameter,
  a criterion with its message, an edit kept beside the data — with no side effect.
- **Consumed, barely.** One automation in six reads the ontology (*Dispatch promise watch*, a `promise_breached`
  condition). The Record holds 192 claims: about a connection 192, about an object · segment · type 0; citing a
  metric 149; citing a segment 0; citing a definition version 0. No decision and no mission is booked.

The plane is complete and the install does not lean on it — the repo's own recurring failure (ROADMAP §7: *"A
complete and inert plane is the recurring failure"*). The study's program is ordered by that finding: every wave below must give a
person a reason to declare something on the day it lands.

---

## 6 · Defects found while studying

Not fixed — the ask was a study. One entry each; D1 is proven, the rest are by reading at `44dee14f`.

### 6.1 The action plane

*Update, later on 2026-10-09: D1–D3 are fixed in `742114d7` on this branch (local, not pushed) — the overlay keeps
the three fields, the web form declares them, and a call with no answer is a recorded dispatch error. D4–D7 stand.*

- **D1 (proven).** `_EDITABLE["action"]` (`aughor/ontology/overrides.py:198-203`) lacks `reversibility`,
  `verification`, `undo` and `parallel_safe`, so `_apply_action` drops them on every read. Hermetic run: a declaration
  with a verification read, an undo and `compensable` read back as `None`, `None` and `''`, and
  `authority.declaration_problem` then refuses the read-back action. Every stored side-effect action reads as L1,
  can never graduate, and its undo is refused. `tests/unit/test_kinetic_k5.py:37-42` asserts only `fields.kind`.
- **D2.** The declare form (`web/components/DeclaredActionsPanel.tsx:128-158`) never sends those three fields, so a
  side-effect action declared from the web is refused with a 422 (`routers/ontology.py:2852-2855`).
- **D3.** Transport errors and `OutboundBlocked` in `_dispatch_webhook` / `_dispatch_http` are not caught
  (`actions/executor.py:277-285,381-387,697`): a 500, no `dispatch_error` audit, the inbox row left `accepted` — which
  a resumed automation reads as `executed` (`automations/engine.py:2782`).
- **D4.** The authority level and its ceilings are never consulted at execution — only when widening and in autonomy
  (`authority.py:545-546`; `autonomy.py:60-61`).
- **D5.** Criteria resolve objects without the overlay (`semantic/object_instances.py:477-501`), so an action cannot
  be gated on state another action set.
- **D6.** `authority.graduated`, `authority.demoted` and `pack.demoted` are listed as subscribable
  (`kernel/events.py:91-92`) and never pushed.
- **D7.** `/approvals/allow`, `/kinetic-actions` and `/authority` mutations fall to the `resource.write` floor: once
  RBAC is enforced, any Editor can allowlist a high-risk action for a connection (`routers/approvals.py:23-28`).

### 6.2 The ontology's own record

- **No history.** `_write` replaces a declaration's file and `_unlink` deletes it (`overrides.py:332-374`); no event
  kind records a declaration changing (`kernel/events.py` has `ontology.measure`, `.explore`, `.build` only). History
  exists only if an install commits its tree to git. `AGENTS.md` says ontology overrides are "superseded with history
  intact"; they are not.
- **No consumer check on withdrawal.** `DELETE /ontology/entities/{id}` removes a declared type without asking who
  depends on it (`routers/ontology.py:1761-1788`); the wave that built it said the door would refuse "where a consumer
  depends on the id" (ROADMAP §3.15, ON-7).
- **Metrics and the object door are drifting apart.** Every metric written since 2026-09-26 is a whole statement;
  the object compiler re-anchors only flat expressions and refuses a statement (`semantic/object_query.py:449-468`, by
  reading).

### 6.3 Seen in live data, not investigated

- theLook's `Order.days_to_delivery` is unverified — "empty on every one of the 1,000 rows checked" — though 43,680 of
  124,987 orders reached *delivered*.
- A finding's text, *"The Men's department generates a higher total profit…"*, drops the scope its warrant's SQL
  applies (`WHERE p.category = 'Accessories'`).

---

## 7 · What the field does

Three research passes, 2026-10-09. Each claim below carries its source in Appendix B; **[D]** documented by the
vendor or standards body, **[R]** reported by third parties, **[I]** inference. The claims marked ✔ were re-read on
the vendor's own page for this study. The July study (`docs/PALANTIR_FOUNDRY_STUDY_2026-07-22.md`) is not repeated.

### 7.1 Palantir, mid-2025 to October 2026

- ✔ **Agents got SQL back — over the ontology.** Ontology MCP (GA 2026-06-25) gives an outside agent *"a SQL tool"*
  over every object type in the application, **each action type as its own tool**, and query functions as tools [D].
  AIP Analyst (GA 2026-03-31) carries Ontology SQL and dataset SQL tools [D]. The July study recorded "no raw SQL
  tool" as Palantir's posture; Palantir's own documentation now says otherwise. The convergence with Aughor's
  measurement is the most useful single fact in this study: models write SQL well, so give them SQL over *declared*
  meaning, and actions as typed tools.
- ✔ **A breaking change cannot be saved without a migration.** Changing a property's type, a primary key or a source,
  or removing a property that carries user edits — *"Ontology Manager will block the user from saving changes until
  they define a migration"*: drop the edits, move them, cast them, or revert; at most 500 at once; never on a primary
  key [D].
- **Every change is a proposal.** Global Branching went GA on 2026-05-18 across pipelines, the ontology, Workshop and
  AIP Logic; AI FDE (GA 2026-03-12) and Pilot (beta 2026-03-05: a prompt becomes object, link and action types, a
  React app and seed data) both route what they draft through branch proposals a person merges [D].
- **Ontology as code, with lock files.** SuperRepo (beta 2026-08-04) compiles TypeScript ontology definitions into
  installable products; the open-source OSDK *maker* writes a schema lock file, checks compatibility at build time,
  and stages a published interface's change with a grace window that ends in *finalize* or *delete* [D].
- **Still a copy.** Objects over virtual or Iceberg tables (2025-09) are re-indexed into Palantir's own object store;
  no object type is read live from the source at query time [D, I]. A federated object layer is not something
  Palantir has and Aughor lacks — it is the reverse.
- ✔ **Machinery models a process as the states of one object type** — one state property, *"Actions are the cause of
  state transitions"*, a Log object type, nested process containers — and overlays mined transitions on declared ones
  (found only in data; declared but never observed) [D]. **Its documentation shows no promise or SLA construct**
  [D, I].
- **Security moved onto the ontology.** Object and property security policies (row, column, cell) went GA 2026-04-23,
  independent of the source's permissions; policy testing GA 2026-06-30; a token is the intersection of the person,
  the app's restrictions and the requested scope; the docs warn against `NOT` conditions because a scoped token may
  lack the attribute they test [D]. A hidden value shows as `null` — which Aughor's *withheld is said* rule refuses.
- **Actions in two lanes.** At most one writeback webhook runs *before* the edits and its failure blocks them; side-
  effect webhooks run *after*, best-effort, and their failures are not shown to the person [D]. Applying an action
  returns an operation id — a 200 is not "applied". An action log object is written per successful submission and
  linked to every edited object; the object timeline (2026-08-11) attributes each change to an agent or a person [D].
- **What critics say.** "It's just ER modelling" with a services model that locks in [R]; no RDF/OWL export [R]; the
  NHS Federated Data Platform — £330m over seven years — projects £777m of benefit against £1.042bn of lifetime cost,
  with a break clause in 2027 [R]. The research found no head-to-head accuracy numbers from Palantir for
  ontology-grounded agents [I].

### 7.2 The landscape — four poles, and where Aughor stands

| Pole | Who | What it models | What it lacks |
|---|---|---|---|
| **Metrics** | Snowflake semantic views, Databricks metric views, dbt MetricFlow (Apache-2.0 since 2025-10-14), Cube, AtScale, Looker | datasets, keys, fields, metrics, relationships, synonyms | processes, actions, promises |
| **Objects and actions** | Palantir; Microsoft Fabric IQ with operations agents; C3 AI; Anduril Lattice | types, links, actions (Palantir), tasks per asset (Lattice) | Fabric's ontology runs nothing (below) |
| **Processes** | Celonis (object-centric, OCEL 2.0), Palantir Machinery, SAP's process knowledge | events, objects, qualified relations, conformance | Celonis extracts the data; Machinery has no promise |
| **Inferred context** | Databricks Genie Ontology ("OntoRank"), Snowflake Horizon Context and Cortex Sense, newly funded startups | context mined from usage, dashboards, SQL | what governs the inferred part — "the whole game", in one practitioner's words [R] |

Five signals from the poles, each one checked against Aughor:

- ✔ **Execution is leaving the ontology.** In Microsoft's new Fabric IQ experience (page dated 2026-09-15) a business
  rule is a natural-language definition, and the *"Ontology doesn't run the rule against data or execute actions"*;
  the Activator integration is gone; acting moved to operations agents, which approve each action and run it under a delegated,
  recorded agent identity [D]. Aughor's rules and promises are *measured*, not prose — stronger than Fabric's — and the
  lesson is where they run: compiled, receipted statements, never the definition store.
- ✔ **Metrics now have a standard; ontologies do not.** Apache Ossie (ex-OSI; incubating since July 2026; draft
  0.2.0.dev0) defines datasets, fields, metrics, relationships, dialects, AI context and extensions — and nothing for
  actions, processes, rules, state machines, identity or authorization [D]. Ossie *import* would let Aughor start from
  the semantic models customers already trust (Fabric already builds ontologies from Power BI models [R]); an *export*
  is ROADMAP §4.6's question, refused.
- **Each big platform binds its ontology to its own storage.** Fabric's static bindings must sit in OneLake; a semantic
  view is a Snowflake object; Genie Ontology lives in Unity Catalog; SAP bought Dremio to reach data outside SAP [D].
  The neutral tools that federate across warehouses — Timbr's SQL ontology, Stardog's virtual graphs — carry no
  processes, no actions and no agents [D, R]. **A neutral, federated, process-aware ontology with actions and a
  record is unoccupied ground** [I].
- **Agents see meaning, never raw tables.** Salesforce: "expose Data Graphs and DMOs to the AI layer, never raw DLOs";
  Snowflake grants SELECT on the semantic view, not the tables [D]. Gartner (2026-05-11) says organisations that put
  semantics first can raise agent accuracy by up to 80% by 2027, and expects 60% of agentic-analytics projects that
  rely on MCP alone to fail by 2028 [D, R].
- **Authoring proposes before it applies.** Fabric's ontology agent plans, then acts; Snowflake's Autopilot "generates
  proposals. It does not generate truth" [R]; Palantir's AI FDE drafts on a branch [D]. Aughor's explorer measures
  before it writes — and then serves before a person confirms (§3).

### 7.3 The building blocks — and the evidence

**The evidence on ontology-grounded agents supports all three of Aughor's findings** [R; vendor numbers flagged]:

| Finding here | What the field measured |
|---|---|
| Prose about the ontology lifts nothing | An auto-inferred semantic layer *hurt* on a clean schema (0.75 → 0.50); strong models find the relevant schema unaided; irrelevant context degrades reasoning. The counter-examples (a 4 KB hand-written definitions document: +17–23 points; BIRD's "evidence": 34.9% → 54.9%) carry *definitions and disambiguation* a model cannot infer, not restated structure |
| A model writing an ontology query language does worse than SQL | No winning system has the model *author* a query language. The model *selects* declared, typed slots — metric, dimension, filter ids — and a deterministic compiler writes the SQL: dbt 2026 98.2% / 100% against text-to-SQL 90.0% / 84.1% (vendor); an IR of declared semantic-model ids plus a compiler 94% on Spider 2.0-Snow (preprint). Out of scope, the semantic layer answered 0% against SQL's 70% — the fallback stays |
| Resolving terms to declared definitions lifts | Ontology-based query checks with repair: 72% plus 8% "unknown"; binding intent to governed definitions and validating the SQL for join, grain and filter; a preprint ablation finds the *semantic content* drives the gain and that contract rules were used 98% of the time when retrieved against 4% when placed in the prompt |

One more reading of that table matters for design: a semantic layer's failures are **loud** (it refuses a question it
cannot compile), text-to-SQL's are **silent** (a wrong number). Aughor's guard battery and *withheld is said* are the
same choice.

The rest, by problem, with the choice each points to:

| Problem | State of the art | Fit for Aughor |
|---|---|---|
| A definition language and compiler | LinkML (30+ generators), SHACL (closed-world validation; 1.2 still a W3C draft), OWL (open-world — a missing value is not an error), Fabric's TMDL with a `lineageTag` that keeps an element's identity across renames | **Keep YAML + Pydantic as the only source** (the `interchange.py` lesson: a second representation drifts); add a stable id per element; validate closed-world; *emit* artifacts |
| Schema evolution | Confluent's modes (BACKWARD by default, transitive variants); Buf's strictness tiers; oasdiff's ERR · WARN · INFO; GraphQL Inspector's breaking · dangerous · safe, with breaking changes checked against 30 days of real usage; dbt contracts, versions and exposures | A rule catalogue for ontology changes, usage-aware, plus Aughor's own class — **meaning-changing** (§8.5) |
| Processes | OCEL 2.0: objects, events, *qualified* event-to-object and object-to-object relations, attribute values over time. Forcing one case notion inflates, collapses or loses events (convergence, divergence, deficiency). Performance per step: synchronisation, pooling, lagging, flow time. Declared lifecycles: statecharts (SCXML, XState, python-statemachine) | Compile object-centric events at read time from timestamp and status columns; pick each promise's lead object from measured cardinality and refuse convergence the way fan-out is refused today; declared transitions as statecharts; PM4Py is AGPL — never embedded |
| Flows with impact | Metric trees separate *component* edges (an exact formula) from *influence* edges (correlated, not causal); DoWhy's graphical causal models attribute a change along a *declared* graph | An impact carries its mechanism — formula · influence · validated — and is promoted only with recorded evidence (§8.4) |
| Identity across sources | Splink 5 (MIT; DuckDB and Postgres; 2026-09-28): deterministic rules, then probabilistic, with a review band; survivorship per attribute; chained merges are the classic failure | Exact keys now; a match is a supersedable decision record when a cross-source need is measured — the 2027 study's "a person confirms; a rejected pair is remembered" |
| Authorization | Cedar (default deny, forbid beats permit, the determining policies returned as the explanation, policy-set analysis in CI; in-process Python bindings); OpenFGA and SpiceDB (relationship-based, a service); MCP's 2025-11 and 2026-07 authorization (OAuth 2.1, protected-resource metadata, resource indicators, no token pass-through); Entra Agent ID GA; RFC 8693 `act` for delegation | The 2027 study's call stands — the platform's own small policy engine until policies outgrow it; Cedar is this study's candidate successor, its schema generated from the release; an agent's access is its grant ∩ its person's |
| Durable actions | Transactional outbox; idempotency keys in atomic phases; optimistic locking; `SKIP LOCKED` queue tables; DBOS, Procrastinate, pgmq as Postgres-native options; Temporal, Restate, Inngest, Hatchet as services | Arc SR decided the queue is a table in the store — so the outbox is rows in it, worked with `SKIP LOCKED` and a lease; a separate engine is refused |
| Declarative UI | json-render (the Cockpit already uses it), Google's A2UI (flat specs, catalog negotiation, `checks`), MCP Apps (final 2026-01-26; HTML in a sandboxed frame), forms from JSON Schema (RJSF, JSON Forms), generated clients (openapi-typescript, Hey API, Orval, Kubb; Palantir's OSDK 2: thin types plus a generic client) | Keep json-render; add ontology-bound pieces to the catalog; action forms from each action's generated JSON Schema; MCP Apps outbound only — opaque HTML cannot be validated |
| Graphs without a graph database | SQL/PGQ committed to PostgreSQL 19 and **reverted** on 2026-09-07; BigQuery Graph GA 2026-09-01 (DDL in the warehouse); BigQuery caps recursion at 500 iterations; DuckPGQ | Bounded traversal stays compiled joins and recursive CTEs with a depth bound and a cycle guard; nothing created in a customer's warehouse; a graph engine only for Aughor's own edges (the context graph, lineage) |

---

## 8 · What ontology-first means for Aughor

### 8.1 The shape

```
 SURFACES      object pages · the Cockpit, with ontology-bound pieces · the Briefing · chat · Slack · MCP · later, an SDK
               ── every surface reads a PUBLISHED RELEASE, never the working draft ──────────────────────────────────
 THE CONTRACT  one release per scope (connection · schema, or organisation · domain), immutable once published:
               types · properties · links and their purpose · processes · promises · rules · impacts · actions · segments
               each element: a stable id · a version · its warrant (who declared it, what measured it, as of when)
               · who depends on it
 ENGINES       the compiler (release → statements, frames, JSON Schemas, TypeScript types, MCP tool specs, monitors)
               the object door (federated reads, edits merged) · framing · the action engine (criteria, authority,
               an outbox, verification, undo) · measurement on the settle clock
 OWNED STATE   the ledger (the Record, releases, executions, events) · the edit layer · platform-owned objects (b)
 DATA          sources, queried in place — rows never move, nothing is written back
 ACROSS        identity · groups · grants whose securables include ontology ids · the gate map · audit
```

This is the document's layer diagram with Aughor's laws applied: the contract in the middle, everything above it
reading a release, everything below it never copied. Apart from decision (b), it adds nothing the 2027 architecture
refused — the INTELLIGENCE
band there already holds "types, links, processes, promises, rules · definitions · the object door (a compiler)". What
is new is that the band becomes **versioned, published and depended on**.

### 8.2 Three kinds of object

| Backing | What | Read | Changed by | State today |
|---|---|---|---|---|
| **Source-backed** | an order, a customer, a shipment — the business's own things | live, compiled to the source; freshness is the source's own, shown per type from the settle clock | nothing in the source; the edit layer adds properties beside it | built |
| **Record-backed** | a claim, a decision, an action, an outcome, a mission, an inquiry | the ledger | their own doors, supersede only | built; **not yet attached** to source-backed objects on the live install (0 of 192) |
| **Platform-owned** | a case, a review, an assignment — an app's unit of work that no source holds | the platform's store | declared actions only, each change kept | absent — decision (b) |

The edit layer is the bridge and the first step. Today it is an overlay in which an edit may only *add* a property, a
withdrawal hard-deletes the row, criteria cannot see it (D5), and nothing checks a concurrent change. With history,
transitions, a concurrency check and visibility to criteria, it holds most of what a first app needs — an assignee, a
status, a reviewed flag — on the object the app is about. Platform-owned types wait for an app whose unit of work is
not one source row.

### 8.3 The agent and the ontology — the measured posture

1. **Resolve first.** Framing stays the front door: a question's terms resolved, by code, to declared definitions
   before anything is written — the one accuracy gain the repo has measured, now corroborated outside.
2. **Compile from declarations.** A declared metric, segment, promise or rule is compiled, never re-derived by the
   model. The model may *choose* among declared ids; it does not compose an object query (that tool stays deleted).
3. **Check against the contract.** Fan-out and grain from measured cardinality, a promise's lead object, lifecycle,
   row policy — the guard battery reads the release.
4. **SQL stays the language.** *Ontology SQL* — each type, link and segment of a release compiled into a named
   relation a person or the agent can `SELECT` from, expanded to the source at run time — is where Palantir,
   Snowflake's semantic views and Timbr all landed. Here it is a **hypothesis to measure** on the ON-10 sets (raw ·
   framed · framed plus ontology SQL) before the agent gets it; `ACTION:` template tokens are a precedent for
   expansion inside SQL (`aughor/ontology/actions.py`).
5. **Actions as typed tools.** One proposal tool per declared action, propose-only by default — the shape of
   Palantir's agent door, under Aughor's authority ladder.

### 8.4 Processes and flows — the user's framing as design

- **A flow has two backings.** A *link* between two types (an order line belongs to an order) and a *transition*
  between two states of one type (an order goes from placed to shipped, caused by an action or observed in the data).
  Palantir models the first in its ontology and the second in Machinery; Aughor has the first and half of the second
  (stages are measured, transitions are not declared).
- **Purpose is derived, not authored.** A link a stage reaches through *carries* that process; a link with a promise
  on it carries that promise. Both can be read from today's declarations and shown on the link and the map.
- **Impact is declared with its mechanism.** *formula* — exact (an order's revenue is the sum of its lines) · *influence*
  — measured as an association with its *n*, its lag and its window (orders whose lines missed dispatch miss delivery
  at rate *x* against *y*) · *validated* — an intervention or a decision's outcome showed it. Measured through the
  compiler exactly as a promise is; promoted only on recorded evidence; worded by mechanism at the departure gate, which
  already holds causal language that has no licence. Consumers on day one: the frame ranks candidate drivers by impact
  before hops; the Briefing explains a moved promise by what is upstream of it; the scenario ladder propagates along
  formula edges first.
- **Events are object-centric, compiled at read time.** One event touches several objects, each with a role (a
  dispatch touches the order, the line, the product and the centre). Each promise names its lead object, chosen from
  measured cardinality, and a breach rate that would double-count or collapse is refused — the process twin of the
  fan-out refusal.
- **Transitions are declared, then measured.** A statechart per lifecycle: on source-backed types, conformance is
  *measured* — transitions seen only in data, declared ones never observed (Machinery's overlay); on edit-layer and
  platform-owned state, the action engine *enforces* them.
- **Timestamps are checked before they are believed.** Promises already flag impossible orders (4,199 Lux refunds dated
  before receipt); theLook's item timestamps precede creation in 58% of multi-item rows. A monotonicity check becomes
  part of measuring every stage.

### 8.5 The release, concretely

- **A stable id per element**, separate from its name, so a rename is matched rather than read as delete-plus-add.
- **History before releases.** Every save and withdrawal kept with its prior body. The repo already has a versioning
  substrate — `aughor/kernel/lifecycle.py`: save ≠ publish, versions, diff, revert, serving saved queries, canvases,
  cards and evals — and the ontology is not on it. *One store per concept* says put declarations there, with the YAML
  tree as export and import, not build a release store beside it.
- **A release** is an immutable set of element versions for a scope, with the measured verdicts as of that moment and
  a hash: draft → validated (compiles, measures, no ERR) → published. Rollback publishes an earlier set.
- **A compatibility catalogue**, usage-aware: adding is safe; renaming with the same id is safe; removing what something
  uses, narrowing a type, changing a key, a binding's source or a link from to-one to to-many is an ERR; tightening an
  action's criteria is a WARN. A key change or a type change on a property with edits needs an edit migration — drop,
  move or cast, as Palantir requires.
- **Aughor's own class: meaning-changing.** Moving a promise from two days to three, changing a rule's values, a
  segment's filter or a metric's statement changes what every claim computed under it *means*. Publishing one marks
  those claims as computed under the old version and sends them down the Record's existing restatement path — *"a
  restated number told to whoever was given the old one"* (ROADMAP §0). No platform in §7 versions *meaning* against a record
  of what was told to whom; this is where the contract and the moat meet.
- **Dependents** as edges (consumer, element id, how it is used, last used): metrics through their grain and tables,
  cards, trusted queries through their SQL's lineage, automations through processes, promises and tables, segments,
  processes through their link paths, actions through types, parameters and edits, claims through `about`, metric and
  `definition_version`, glossary and vocabulary entries. Much of this keys to tables today; bindings translate tables
  into types, so the index is useful before any store is re-keyed.
- **Consumers pin.** A claim's `definition_version` names the release; a cockpit, an automation and an action
  declaration name the release they were checked against; the agent and the Briefing read the published release.

### 8.6 Security on the contract

When identity is on — the 2027 study's phase-0 exit, not yet observable: securables add object type, property, link,
action and cockpit; a property carries a sensitivity tag; a row policy per type compiles to SQL (`rbac/row_policy.py`
exists, empty); the resolver is enforced at the object door, the action engine and the app runtime; a withheld row or
property says so; an agent's access is its grant intersected with its person's, and both decisions are audited;
`/access/explain` answers why. No `NOT` conditions — the Palantir lesson.

### 8.7 Apps

An app, in Aughor's terms, is **a published cockpit whose pieces bind to a release**:

- **New pieces:** an object table (a type or segment, columns, sort, paging), an object detail (today's object page,
  embedded), a process board (stages, breach rates, the open-and-overdue list), a link explorer, and an action button
  that names a *declared* action by id — Arc CT refused an action a spec *defines*; naming an existing governed door is
  the law the chat already follows.
- **Checked three ways before it renders:** every id resolves in the pinned release; the viewer's grants allow each
  binding; the compatibility check passes for the release it is published against.
- **Shared, not copied:** published to a group (built on the unmerged `claude/cockpit-canvas` branch the live install
  serves), inside the Cockpit tab — the rail stays.
- **No code inside the platform.** A custom-code path — generated TypeScript types and a thin client for the object
  door and actions, used by an application that lives *outside* — comes later and is decision (d). MCP Apps (Arc CT's
  unscheduled CT-6) is the outbound door for showing an Aughor view inside someone else's host.

---

## 9 · The program — Arc OC, the ontology as the contract (proposed)

**Not adopted; not in `ROADMAP.md`.** The label is a proposal. Every wave ships behind a flag that is off by default
and byte-identical when off, carries a live receipt — on theLook, the go-to connection (ROADMAP §6 item 18(c)),
unless the wave names another — and a falsifier written before the build, and must give a person a reason to declare
something on the day it lands: §5's finding is the ordering principle.

| Wave | What | Receipt | Falsifier |
|---|---|---|---|
| **OC-0 · Preconditions** | Fix D1–D3 (the action plane holds and reports its own declarations). Write the ontology's nouns into `docs/GLOSSARY.md` — object type (user-facing) and `entity` (internal), link, property, binding, part, process, stage, promise, rule, impact, release, edit layer. Turn §5's census into a recurring measurement: the baseline every later wave moves | a side-effect action declared from the web reads back with its verification and undo, runs, verifies, and is undone | — |
| **OC-1 · History and stable ids** | Declarations on the existing versioning substrate, every save and withdrawal kept; a stable id per element; a first dependents index from what already names ontology things; withdrawal refused where something depends — the ON-7 promise | a theLook promise declared, changed twice and withdrawn, all three versions read back; withdrawing a type an automation uses is refused with the automation named | if "what did *late* mean on 1 October" cannot be answered, it is not history |
| **OC-2 · The release** | Draft → validated → published per scope; diff and dependents on screen; the compatibility catalogue with meaning-changing as its own class; claims pin `definition_version` and take `about` from the frame; the agent and the Briefing read the published release; explorer proposals wait in the draft — decision (f) | the dispatch promise moved from 2 to 3 days in a draft: the diff names the claims, the automation and the cards it touches; after publishing, the claims computed under 2 days say so | replay the tracked declarations' git history: every past change that broke a consumer must class as ERR or WARN — one miss and the catalogue is wrong |
| **OC-3 · One contract** | Metrics carry the type and grain property they measure, and the object compiler accepts a statement metric; `entity_appears` and `source_change` accept a type; glossary and vocabulary entries carry the property they name; cards may bind to a segment or a type | the share of meaning-bearing records keyed to release ids, per store, against OC-0's baseline | if keying raises neither framing reach nor the declared-definition hit rate on the ON-10 sets, stop at the minimum |
| **OC-4 · The first ontology-bound surface** | A listing door for objects (type or segment, columns, sort, offset, total); the object table, process board, action button and object detail pieces; the screen shown before the build | a *late dispatch* cockpit on theLook: process board → open-and-overdue orders → an order → *flag for review* → the edit visible in the table and on the page | if the census does not move in the weeks after, the surface was not the bottleneck — stop and re-survey |
| **OC-5 · Processes and flows** | Link purpose derived from processes; impact declarations with their mechanism, measured; object-centric events with a lead object per promise; declared transitions with measured conformance; monotonicity on every stage | late dispatch → late delivery measured as an influence with *n* and lag — on Olist, whose two deadlines are real (ROADMAP §3.15, ON-9: 9.35% and 8.11% broken), and on theLook once its fulfilment process carries a promise — and a framed deep analysis of "what is causing delivery delays" starting from it | on the ON-10 sets, framed plus impact against framed: no gain, and impacts stay reading aids |
| **OC-6 · Actions for apps** | Action versions pinned on proposals and executions; the outbox as rows on Arc SR's job table, a `SKIP LOCKED` worker with a lease, retries by cause, an `unknown` delivery reconciled by running the action's own verification read before any retry, dead letters on screen; two lanes; the edit layer — history, transitions, a concurrency check, visible to criteria; D4–D7 closed; platform-owned types only on decision (b) and a named app | the cockpit's *notify carrier* through the outbox; a forced timeout reconciled by the verification read; the review flag's history read back | a delivery whose outcome nobody can state is the failure this wave exists to remove — count them |
| **OC-7 · Security on the contract** | Ontology securables, property sensitivity, row policy per type, enforcement at the three doors, withheld said, agent ∩ person — needs the organisation install | two people open the same cockpit and see different rows and a masked property, each told why | a policy test that passes with enforcement off is testing nothing — mutate it |
| **OC-8 · Doors for builders** | From a release: JSON Schemas for action forms, TypeScript types and a thin client (decision (d)), one MCP proposal tool per declared action; versioned `/ontology/v1` and `/objects/v1`; ontology SQL only if OC-5's measurement earns it; Ossie import as a bootstrap | a script outside the platform lists late orders and proposes the action through the generated client | — |
| **OC-9 · The second domain** | Lux's return-to-refund process (refunds within 10 days, broken on 23.3%) rebuilt in the same shape | the cockpit, the impacts and the actions, with no change to core code | the document's own: any domain-specific conditional added to the runtime means the core is not generic |

**Order.** OC-0 → OC-1 → OC-2 → OC-3 alongside OC-4 → OC-5 → OC-6 → OC-7 → OC-8 → OC-9. OC-7 moves earlier the day the
organisation install arrives. OC-0 is small and is mostly a defect fix; it is worth doing whatever is decided about
the rest.

**The document's success metrics, read for Aughor** — today's values are the baseline:

| Metric | Aughor's reading | Today |
|---|---|---|
| Time to create an object type | declared types, and hours from a connection to its first | 0 declared types live |
| Time to map a source | onboarding hours (`docs/GLOSSARY.md`) | "not yet" — no decision booked |
| Mappings validated automatically | the verified share per kind | backing 25/35 · links 36/37 · bindings 7/7 · segments 50/50 · computed 11/14 |
| Apps reusing types and actions | cockpit pieces bound to release ids | 0 |
| Query latency and error rate | object-door spans, p50 and p95 | not read here |
| Action success and reconciliation backlog | executions verified · `unknown` deliveries | 1 declared action |
| Breaking changes caught before publication | ERRs refused | no mechanism |
| Authorization coverage | securables enforced | enforcement off |
| *Aughor's own:* the record attached to the contract | claims about an object, segment or type · claims pinning a definition version | 0 of 192 · 0 of 192 |
| *Aughor's own:* framing reach | questions resolved to a declared definition | 15 of 18 Olist questions (ON-10) |

**What not to build** — the document's §15 and the plan of record, merged:

- an object store, a sync of customer rows, or edits written back to a source (Arc ON's laws; ROADMAP §4.7);
- a graph database, or a property graph created in a customer's warehouse;
- a workflow engine or a separate durable-execution service (ROADMAP §4.2, §4.3; Arc SR: the queue is a table);
- an export of the ontology to Fabric IQ, RDF, OWL, Turtle or OCEL (ROADMAP §4.6) — imports only;
- code that runs inside the platform's process, or an action a spec defines (the 2027 study §Q; Arc CT);
- a visual agent builder (ROADMAP §4.1, §4.8) or a new rail destination (ROADMAP §4.10);
- a model writing the organisation's ontology (ROADMAP §6 item 20), or more ontology prose in a prompt (ROADMAP §6
  item 15);
- a visual app designer before an app built from the catalogue has users;
- probabilistic identity resolution before a cross-source need is measured.

---

## 10 · What this study asks of the user

Each with a recommendation. None blocks OC-0.

- **(a) The arc.** Adopt Arc OC — the ontology as the contract — into ROADMAP §3, OC-0 to OC-2 first. *Recommended:
  yes.*
- **(b) State of their own for apps.** The edit layer first: history, transitions, a concurrency check, visible to
  criteria. Platform-owned object types only when a named app's unit of work has no home in a source. This narrows the
  2027 study's "not a system of action" to the platform's own objects and moves no customer row. It also touches
  `PENDING.md` item 31's open question — an edit that *corrects* a source value — which wants a declared strategy
  (the edit wins, or the newer of edit and source wins, as Palantir offers). *Recommended: the edit layer yes; owned
  types and corrections each on their own receipt.*
- **(c) What an app is.** A published cockpit over ontology-bound pieces and declared actions, shared with a group,
  inside the Cockpit tab — and its word: keep *Cockpit*, or add *App* to the glossary. The screen is shown before
  anything is built on it. *Recommended: keep "Cockpit".*
- **(d) A custom-code path and a public SDK.** This reopens the 2027 study's "the platform's equivalent of an app is
  the pack" and "no public SDK". *Recommended: generated JSON Schemas, types and MCP proposal tools in OC-8; a client
  for outside applications only when a customer asks for one; nothing hosted that runs code.*
- **(e) The agent.** Framing first stays; ontology SQL is measured before the agent gets it; the object-query tool stays
  deleted. *Recommended: yes.*
- **(f) Proposals before confirmation.** The explorer's measured proposals wait in the draft and the published release
  holds what a person confirmed — instead of today's measured-then-served. Explore-on-connect keeps running.
  *Recommended: yes.*
- **(g) Identity across sources.** Exact keys now; supersedable match records — rules first, then a probabilistic
  matcher — when a cross-source question needs them. *Recommended: as the 2027 study's table already says.*
- **(h) Vocabulary.** *Object type* in everything a person reads; `entity` stays the internal spelling, as
  `investigation` did for *deep analysis*. *Recommended: yes.*
- **(i) Hosts.** theLook first, Lux returns second. *Recommended: yes.*
- **(j) Ossie.** Import as a bootstrap from the semantic models customers already keep; export stays refused under
  ROADMAP §4.6. *Recommended: import only, in OC-8.*

---

## Appendix A · The document, section by section

| § | The document | Aughor |
|---|---|---|
| 1 | The mental model; the ontology as the contract | the INTELLIGENCE band of the 2027 architecture — not yet a contract (§4, §5) |
| 2 | Five primitives | object types, links and actions built; properties and functions partial (§4.1) |
| 3 | Separate definitions, instances, mappings | instances federated and separate; mappings inside definitions; no versions (§4.1, §6.2) |
| 4 | Engine modules and stack | all five modules exist in some form; SQLite for one person, Postgres for an organisation (the 2027 study; Arc SR, not on main) |
| 5 | Authoring as the product; the compiler | a real studio without releases; per-declaration validation, no whole compile (§4.1) |
| 6 | Materialised or federated; query contract; bounded traversal | federated by law; aggregates, no listing; traversal bounded (§3, §4.1) |
| 7 | Actions; outbox; state transitions | a strong contract; no outbox, no version, no transitions; D1–D7 (§4.2, §6) |
| 8 | Authorization in the runtime | designed in Arc HB; enforcement off; no ontology securables (§4.2) |
| 9 | Versioning and controlled publication | absent for the ontology (§6.2, OC-1, OC-2) |
| 10 | The app platform | the Cockpit, without ontology-bound pieces (§4.2, §8.7) |
| 11 | Phases 0–5 | mostly past phase 2 on the noun side; OC maps phases 2–5 onto what is missing |
| 12 | AI accelerates creation | built, with people-only authorship across connections (§4.1) |
| 13 | The hardest problems | identity (OC later), provenance (strong), schema evolution (OC-1, OC-2), security (OC-7), correctness (OC-6), performance (no caching on object paths) |
| 14 | Success metrics | §9's table |
| 15 | What not to build | §9's list |
| 16 | The initial product | built except release management and ontology-bound apps |

## Appendix B · Sources

Read 2026-10-09. ✔ re-read on the source's own page for this study.

**Palantir** — ✔ Ontology MCP architecture: palantir.com/docs/foundry/ontology-mcp/sample-architecture · ✔ schema
migrations: palantir.com/docs/foundry/object-edits/schema-migrations · ✔ Machinery: palantir.com/docs/foundry/machinery/core-concepts
· AIP Analyst: palantir.com/docs/foundry/aip-analyst/capabilities · announcements, 2025-06 to 2026-10:
palantir.com/docs/foundry/announcements/YYYY-MM · Global Branching: palantir.com/docs/foundry/global-branching/core-concepts
· SuperRepo: palantir.com/docs/foundry/superrepo/faq · OSDK maker: github.com/palantir/osdk-ts (packages/maker) ·
edits and source conflicts: palantir.com/docs/foundry/object-edits/how-edits-applied · multi-datasource objects:
palantir.com/docs/foundry/object-permissioning/multi-datasource-objects · object and property policies:
palantir.com/docs/foundry/object-permissioning/object-and-property-policies · webhooks:
palantir.com/docs/foundry/action-types/webhooks · action log: palantir.com/docs/foundry/action-types/action-log ·
interfaces: palantir.com/docs/foundry/interfaces/interface-overview · critiques: vonng.com/en/db/ontology-bullshit
(2026-02-21); theregister.com, NHS Federated Data Platform (2026-05-07); infoworld.com/article/4209881 (2026-08-17).

**Landscape** — ✔ Fabric IQ business rules: learn.microsoft.com/en-us/fabric/iq/ontology/how-to-use-rules (2026-09-15)
· Fabric IQ ontology overview, binding, graph, ontology agent, definition format: learn.microsoft.com/en-us/fabric/iq/ontology/*
and learn.microsoft.com/en-us/rest/api/fabric/articles/item-management/definitions/ontology-definition · operations
agents: learn.microsoft.com/en-us/fabric/real-time-intelligence/operations-agent · ✔ Apache Ossie core spec:
github.com/apache/ossie/blob/main/core-spec/spec.md · Snowflake semantic views: docs.snowflake.com/en/user-guide/views-semantic/overview
· Databricks business semantics and Genie Ontology: docs.databricks.com/aws/en/business-semantics,
docs.databricks.com/aws/en/genie/genie-ontology · dbt MetricFlow: getdbt.com/blog/open-source-metricflow-governed-metrics
· Salesforce semantic layer: salesforce.com/blog/semantic-layer-ai-agents-data-360 · SAP and Dremio:
dremio.com/newsroom (2026-05) · Celonis Process Intelligence Graph: celonis.com/blog · OCEL 2.0: arxiv.org/abs/2403.01975
· single-case problems: arxiv.org/pdf/2311.08795 · OPerA: arxiv.org/abs/2204.10662 · Timbr: docs.timbr.ai ·
Gartner (2026-05-11): gartner.com/en/newsroom/press-releases/2026-05-11-gartner-says-lack-of-semantics-causes-inaccurate-artificial-intelligence-agents-and-wasted-spending
· Sequeda on Data + AI Summit 2026: juansequeda.substack.com.

**Building blocks and evidence** — LinkML generators: linkml.io/linkml/generators · Confluent schema evolution:
docs.confluent.io/platform/current/schema-registry/fundamentals/schema-evolution.html · Buf: buf.build/docs/breaking/rules
· oasdiff: github.com/oasdiff/oasdiff · GraphQL Inspector: the-guild.dev/graphql/inspector/docs/essentials/diff · dbt
contracts, versions, exposures: docs.getdbt.com · Splink: moj-analytical-services.github.io/splink · Cedar:
docs.cedarpolicy.com; arxiv.org/abs/2403.04651; cedarpy: github.com/k9securityio/cedar-py · MCP authorization:
modelcontextprotocol.io/specification/2025-11-25/basic/authorization and the 2026-07-28 changelog · RFC 8693 ·
transactional outbox: microservices.io/patterns/data/transactional-outbox.html · idempotency keys:
brandur.org/idempotency-keys · DBOS: github.com/dbos-inc/dbos-transact-py · A2UI:
developers.googleblog.com/introducing-a2ui-an-open-project-for-agent-driven-interfaces · MCP Apps (SEP-1865):
modelcontextprotocol.io/seps/1865-mcp-apps-interactive-user-interfaces-for-mcp · metric trees: mixpanel.com/blog/metric-tree
· DoWhy GCM: jmlr.org/papers/v25/22-1258.html · SQL/PGQ revert: commandprompt.com/blog/two-features-just-left-postgresql-19
· evidence: arxiv.org/abs/2311.07509 (data.world, 2023), arxiv.org/abs/2405.11706, docs.getdbt.com/blog/semantic-layer-vs-text-to-sql-2026
(vendor), snowflake.com/en/blog/engineering/cortex-analyst-text-to-sql-accuracy-bi (vendor), arxiv.org/abs/2604.25149,
arxiv.org/abs/2606.31041, arxiv.org/abs/2609.22259, arxiv.org/abs/2608.26157, arxiv.org/abs/2608.16663 (2026 preprints,
unreviewed), arxiv.org/abs/2305.03111 (BIRD), arxiv.org/abs/2408.07702, arxiv.org/abs/2302.00093.
