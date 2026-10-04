# Aughor in 2027 — what the platform should become

*A study, written 2026-10-04 at the user's request. It is not a plan of record: nothing here is in
`ROADMAP.md`, nothing is adopted, and nothing was built. Where it contradicts a standing decision
(§4 of the roadmap, or a rule the user has given) it says so on the line and names what would have
to be true to reopen it.*

***Status: unfinished.** Sections A–T are written. Sections U–Y and the closing attack are outlined at
the end, with the decisions already reached, and are not yet written — the session was paused there at
the user's word.*

*Method. The platform was reconstructed from the code and the ledgers before anything was proposed:
`ROADMAP.md` §0–§1, §4, §7–§8; `PENDING.md` as ticked on 2026-10-04; `IDEAS.md`; `docs/GLOSSARY.md`;
and two read-only sweeps of `aughor/` and `web/` (no database was opened, no model was called, the
running API was not touched). Every count below is quoted from one of those with its date. A count
is a measurement with a timestamp; re-measure before building on one.*

*Words. This study uses the glossary's words. Six words it needs are not in the glossary yet and are
marked **(new word)** where they first appear: claim (widened), inquiry, prediction, decision,
mission, scenario. They are proposals, not renames.*

---

## A · Executive thesis

**What stays scarce.** Start from the last question in the brief, because everything else follows
from it. If analysis becomes nearly free by 2027 — any model, pointed at any warehouse, can write the
SQL, chart it, explain it and investigate it — then none of these is worth owning: answering
questions, finding anomalies, writing narratives, running agents. Six things stay scarce, and none of
them is intelligence:

1. **Warrant.** Not "an answer" but an answer the organisation is entitled to rely on: this
   definition, approved by this person, measured on days that have settled, by this statement, as of
   this date. Cheap intelligence makes plausible claims abundant and warranted ones rarer by
   comparison.
2. **Attention.** A system that can investigate everything can interrupt everyone. The right to
   interrupt a decision-maker is the scarcest resource in the building.
3. **Authority.** Someone has to be answerable for a commitment. A model cannot be. Who may decide,
   who may act, and up to what limit is an organisational fact no vendor can ship.
4. **Agreement.** What "revenue" means here, what the company is trying to do this quarter, which
   trade-off wins. These are settled between people, slowly, and they are different in every company.
5. **Consequence.** What actually happened after a decision. It arrives on the calendar's schedule and
   cannot be bought, inferred or backfilled.
6. **Earned trust.** How often this kind of claim, from this source, has turned out right — which can
   only be counted after 1–5 exist and time has passed.

**What Aughor is today.** A technically deep platform whose real asset is a discipline, not a feature:
no fact without a source, no model-authored fact, every figure with its as-of, a number said only once
its days have settled, a restated number told to whoever was given the old one, a send held when its
definition is not approved, a superseded fact kept with what replaced it. That discipline is the
machinery of *warrant* — the first scarcity — and almost nobody else is building it.

Around that asset sit fifty-two arcs of surface (§3.1–§3.52, 12,919 lines of roadmap): a SQL editor
at parity with a reference console, three canvases, a composed cockpit, a bot factory, a custom-agent
builder, a training-data pipeline, a cheap-model cascade. Most of it is good work. Most of it is also
what every data platform and every model vendor will ship by 2027.

**The brutal part.** The repo's own standing lesson is that features here stall at *tested*, not at
*leveraged*. Applied to the whole product, the measurements say the same thing at full scale:

| Loop | Built | Used (as measured) |
|---|---|---|
| Ask and answer | one door, guards, receipts | 74 ask turns lifetime on 2026-09-23; 111 logged asks on 2026-10-04 |
| Recommendation → outcome | works end to end; review date asked since CB-2 | "nobody has ever recorded an outcome" (`PENDING.md`, loose ends) |
| Governed actions | declare → approve → execute → audit, standing grants, an earned-autonomy ladder | one declared action on the install (roadmap §1, 2026-09-10); none ships in any pack or the demo; the approval gate does nothing unless `AUGHOR_ACTION_APPROVAL` is set |
| Human labels | verdict doors in web, Slack reactions, Departures | 5 labelled decisions of the ~150 a gate needs (Arc JD, A6) |
| Training data | exporters, tiers, gates | SFT 0 of 1,000 · preference pairs 0 of 150 · golden 5 of 150 (Arc TJ) |
| Causal challenge | skeptic step, typed record | 169 of 309 stored deep reports stated a cause; none had a recorded challenge before 2026-10-04 |

Every learning loop is complete and starved. The platform runs for one analyst on one machine, and at
that scale — the roadmap's own value ledger says it (§3.18) — the value of an organisation-wide system
is *unobservable*. No amount of further building changes that. So the first wrong assumption is not
architectural. It is that the next unit of value comes from the next capability.

**The thesis.** By 2027 the organisation's problem is not getting intelligence; it is knowing which of
an unlimited supply of confident claims to rely on, deciding, and finding out whether it was right.
Aughor should stop being the place analysis is *produced* and become the place it is *held to
account*: the organisation's record of what it holds true, what it expected, what it decided, what it
did and what happened — every entry warranted, dated, owned and scored — which people and every
vendor's agents read from and write to.

Three sentences carry the whole design:

- **The atom is the claim, not the answer.** A claim **(new word, widened)** is a dated statement about
  the business that knows its warrant, its owner, its status, how often claims like it have been right,
  and what would overturn it.
- **The molecule is the closed loop.** Claim → decision → action → outcome, with the outcome written
  back onto every claim the decision relied on.
- **Authority is earned by the record.** What an agent may do without asking is decided the way a flag
  graduates in this repo today: on a receipt, never on a demonstration — and it is taken away the same
  way.

---

## B · The category

**What exists today.** Four categories touch this, and each owns one stage of the loop:

| Category | Owns | Stops at |
|---|---|---|
| BI and semantic layers | the definition and the number | the chart; nobody records who relied on it |
| Data platforms with agents (warehouse-native ontology, metric views, an assistant) | the data, increasingly the meaning | their own warehouse; an answer, not a commitment |
| Assistants and agent platforms from model vendors | the reasoning and the tool loop | the conversation; memory is the vendor's, not the company's |
| Systems of action (CRM, ERP, ticketing) with built-in agents | the transaction | their own module; each grades its own agent |

**Why it is insufficient.** None of them holds the *whole* loop, and none of them can, for a structural
reason each: the BI layer has no notion of a decision; the data platform's interest ends at its own
storage boundary, while a decision's evidence and its outcome usually sit in different systems; the
model vendor's record lives inside one vendor's model, which a company will not accept for its own
history; and the system of action is the actor, so it cannot also be the scorer. The roadmap already
states this last rule for models — a model may draft a question, it never grades its own answer into a
pass (§4.8). The same rule holds for vendors.

**What emerges by 2027: accountable intelligence.** A system of record for judgment, in the way a
general ledger is the system of record for money. The comparison is exact rather than decorative, and
the platform's vocabulary already carries it:

| The books | Aughor today |
|---|---|
| No entry without a source document | provenance is required; there is no `llm_inferred` |
| Entries are never erased, only reversed | supersede, do not delete |
| The period is closed before it is reported | settling; *Final · Provisional · To date* |
| A restatement is announced | `answers.recheck`: "we said 1,744; it is now 1,802" |
| Accounts are reconciled | a metric's tie-out; what people say checked against what the data shows (CB-8) |
| Controls sit before money leaves | the departure gate; approvals; the gate map |
| An auditor can re-perform any figure | the signed Trust Receipt at `/receipt/<id>` |

What the books have that Aughor lacks is the other half of double entry: the *expectation* booked
beside the *actual*. A ledger of money records the budget and then the spend. A ledger of judgment
records what was predicted and decided, and then what happened. That half is missing (sections K and L).

**Why Aughor has the right to own it.** Not because of its agents, its ontology or its SQL — because of
its laws. The invariants in `AGENTS.md` (provenance required; withheld is said, never implied; supersede,
do not delete; reversing durable intent clears the durable record first; flags graduate on receipts) are
the operating rules of a ledger, written down and enforced by ratchets, before the category had a name.
A competitor can copy a feature in a quarter. A habit of refusing to show a number before it is measured
is a culture, and it is the part that takes years.

**The defining primitive** is the claim with its warrant. The defining artifact is the ledger those
claims are booked in. The defining number is calibration: of everything this system said with 80%
confidence, was 80% right?

> Salesforce owns the customer record. Snowflake owns the data. Palantir owns operational intelligence.
> **Aughor owns the track record** — what the organisation believed, what it decided, and whether it was right.

**Names considered and refused.** *Decision intelligence* — an existing label that means dashboards with
recommendations. *Agent platform* — the layer most certain to be given away by model vendors. *Enterprise
world model* — describes a component (section F), and promises a completeness nobody can warrant.
*Intelligence operating system* — claims everything, owns nothing.

---

## The reassessment (the brief's part 1)

Classes: **A** strategic moat · **B** necessary infrastructure · **C** useful but commoditising ·
**D** legacy mental model · **E** likely obsolete by 2027 · **F** missing entirely.

| Component | What it is today | Class | Why |
|---|---|---|---|
| **The laws** | provenance required; no model-authored fact; withheld is said; supersede, do not delete; graduation on receipts — enforced by ratchets | **A** | the machinery of warrant; a habit, which is slower to copy than a feature |
| **Time honesty** | settling learned per table; as-of on every figure; Final · Provisional · To date; daily re-check of answers | **A** | nobody else closes the period before speaking |
| **The departure gate and the Trust Receipt** | laws checked on every send, each recorded; a signed receipt page | **A** | the control point every outside agent will need to pass |
| **Declared business terms** (processes, promises, rules) **and framing** | declared by people, compiled by the object door | **A** | the one measured accuracy gain in the repo: 5 of 16 → 16 of 16 and 7 of 15 → 14 of 15 (2026-09-15) |
| **Checking what is said** | fact-check a document; said against measured (CB-8) | **A** | the first features where the platform checks rather than produces |
| **Alerts with a record** | backtest, fire drill, "last proven working", review of a missed move | **A** | an alert that proves itself is rare; one that explains its misses is rarer |
| **Human verdicts and the ambiguity ledger** | accept · correct · reject with corrected SQL, read back into planning; a choice asked once and remembered | **A** | ground truth, and the only memory that records being wrong |
| **Kernel** | one transactional ledger (`system.db`): versioned artifacts, lineage, events, supervised jobs | **B** → the home of A | necessary today; strategic once claims live in it |
| **Data model** | 44 database stores, about 20 JSON stores, an embedded vector store | **D** | "one store per concept" is the repo's own rule and its most-broken one — see *five claim shapes* under E |
| **Ontology** (types, links, bindings, the object door) | measured, compiled, cross-connection by key | **B** | necessary — and what every warehouse vendor will ship. As a description injected into a prompt it was measured twice and lifted nothing; a model filling object queries regressed (1 of 14, 3 of 12) |
| **Semantic layer** (metric statements, grain, versions, approval) | built | **C** | definitions are becoming a warehouse feature and an open interchange format. Approval and grain are the part to keep |
| **Context graph** | six node kinds, a projection with a cap of 100 findings | **C** | a view over the ledger, not a store to grow |
| **Evidence ledger** (`evidence_claims`) | confidence hardcoded; "freshness" is the run's finish time; outcome fields have no writer | **D** | the right idea frozen in its first shape |
| **Few-shot SQL memory** | remembered statements, evicted on a reject | **C** | compensates for a weakness the next model has less of |
| **Agent architecture** | six built-in agents, sub-roles, custom agents, a roster | **D** | a staff of named personas is the 2025 picture of "agentic" |
| **Agent runtime** | graph loops, a tool loop, seven model backends | **B**, with **E** as an investment | model vendors ship this; keep it working, stop improving it |
| **SQL-writing scaffolding** | repair loops, dialect fixes, a banded cascade, a cheap outside judge | **E** | it depreciates with every model release. Guards on *claims* are A; guards on *syntax* are E |
| **Actions** | declared action, executor, approvals, standing grants, earned ladder | **B**, inert | the right shape, never leveraged |
| **Automations** | engine with seven triggers and thirteen effects; a canvas | **B** (engine) · **C** (canvas) | the engine is how a mission acts; drawing it by hand is not the future |
| **Governance** | gate map; agent policy read · run · act; tags and clearances; caps; groups recorded, not enforced; row policies an empty dict in source | **B**, with A at the gates | |
| **Evaluation** | golden suites by result set; guards on all traffic; graduation receipts; run labels | **A** as method · **F** as calibration | it grades SQL well and grades judgment not at all |
| **Training pipeline** (exporters, tiers, the gym, a student model) | 0 of 1,000 · 0 of 150 · 5 of 150 | **E** | a fine-tune on a starved corpus, chasing a frontier that moves faster than the corpus grows |
| **Navigation** | 17 destinations, 10 Intelligence layers, 7 Agent Ops layers; Home is a first-run funnel | **D** | arranged by the store behind each screen, not by what a person came to do |
| **SQL editor** | parity with a reference console | **C** | fewer people write SQL each year. Its lasting job is to inspect and correct a statement |
| **Data Canvas · Cockpit** | built; the composed cockpit's flag is off | **C** | a board is one view of a set of claims |
| **API** | 66 routers, about 695 routes; a typed client used only by the web app; no public SDK | **B** · **F** | |
| **MCP, both ways** | 18 tools plus live ones, policy-trimmed; consuming behind five gates, read-only first | **B**, in a strategic position | the door outside agents arrive through |
| **Integrations** | 18 connector kinds; Slack, Teams, webhook, Jira | **B** · **C** | |
| **Observability** | OTLP, traces, cost with unpriced calls said | **B** | |
| **Deployment** | a local install; one writer per `data/`; a scheduler in the process | **D** | right for one analyst; the reason every loop is starved |
| **Tenancy** | one `default` organisation; identity off unless switched on | **B**, deliberately parked | section F |
| **Extensibility** | 17 packs, skill import, custom agents; no pack upload, no plugin loading, registries filled by one hard-coded call | **F** | |
| **Missing** | prediction · the organisation's decision · a delivered outcome question · mission · inquiry · scenario · calibration as the product's number · an attention budget · coverage shown · matching one real-world thing across sources · **an organisation using it** | **F** | |

**The assumptions that will be wrong in 2027.**

1. **"The moat is the ontology-to-agent loop"** (roadmap §0). The same paragraph observes a much larger
   company assembling the same stack. A moat cannot be something a competitor ships to its whole base
   while you watch, and the repo's own ablations say the description does not lift answers — the
   *declarations people make* do. The moat is the warrant and the record. The ontology is the map they
   are drawn on.
2. **"The unit of value is an answer."** An answer nobody relied on is worth nothing, and nothing records
   reliance.
3. **"Accuracy scaffolding is the product."** Half of it compensates for a model's weakness and half
   establishes warrant. Only the second half appreciates.
4. **"Agents are a staff the customer manages."** Agents will be abundant, interchangeable and mostly
   someone else's. The product is what they answer to.
5. **"An agent proposes; a person acts" — as an absolute.** As a starting point it is right. As a
   permanent law it caps the product at advice. Authority should be earned and revocable (section M).
6. **"A forecast never departs"** (`govern/departure.py`). Right while there is no forecaster and no
   score. The 2027 rule is narrower: an *unscored* forecast never departs.
7. **"The connection is the scope."** The organisation is. Arc ON's second movement began this.
8. **"People come to the platform."** The hub amendment already says otherwise; the navigation has not
   caught up.
9. **"One analyst on one machine is a deployment."** It is a workbench. Every loop this study relies on
   needs several people who own different things.
10. **"More capability is more value."** Fifty-two arcs, 111 asks.

---

## C · What to kill

"Kill" means stop investing and stop presenting it as the product. Working code stays until it costs
something to keep.

| # | Kill | Because | What survives |
|---|---|---|---|
| 1 | **The fine-tuning destination** — Arc MI's gates, the gym (TJ-5), serving a student (TJ-6) | the corpus is starved and the frontier moves faster than it fills | the graded ledger and the trajectory record, as *evaluation* data |
| 2 | **The SQL editor's parity race** — freeze at SE-8 | commoditising; the reference it chases is a competitor's free feature | the editor as the place a person inspects and corrects a statement, in the same provenance system |
| 3 | **The roster as a product idea** — six named agents, a custom-agent builder that keeps growing, Agent Ops as fleet management | section H; §4.1 already says an agent is one record | duties; one Operations view of *work*. From Arc AO (adopted 2026-10-03), "one truth per number" and "one closed loop" are moat-side and stay; "the agent estate as a product" is the part this contradicts |
| 4 | **Quick or deep as something a person picks** | the measurement that started Arc CP: deep was chosen 0 times in 60 | one ask; the treatment is the platform's problem |
| 5 | **The cheap-model line** — the banded cascade and the outside judge as things to extend | inference prices fall faster than this engineering pays back | what is there, left alone |
| 6 | **New model-compensating scaffolding** | assumption 3 | re-measure each repair loop against a current model; delete the ones that no longer fire |
| 7 | **Canvases as surfaces to improve** — the automation canvas, the Data Canvas | the standalone canvas is the most disposable layer of the stack (the roadmap's own finding, §4.2) | the engine; the canvas as a read-only picture of what a mission does |
| 8 | **The parked object-query tool** | measured worse twice (`PENDING.md` 30) | the compiler behind object pages |
| 9 | **The Evidence panel as it is** | hardcoded confidence is a number shown before it is measured | the claim ledger (E-1) |
| 10 | **Thirty-odd tabs** | section U | six destinations |
| 11 | **"Three planes" as the thesis** | it describes infrastructure, not what is owned | the planes, as architecture (F) |
| 12 | **N bots from a factory** | every tool will sit in chat | one door per channel, held to the departure gate |

---

## D · What to preserve

1. **Every invariant in `AGENTS.md`.** Not as engineering hygiene — as the product.
2. **No model-authored fact, and no model as grader.** By 2027 this will be the unfashionable position
   and the correct one.
3. **Settling, as-of, and the re-check.** The closed period is what makes a number bookable.
4. **The departure gate**, including its hold on a causal sentence with no verdict behind it.
5. **The Trust Receipt**, signed, reachable by a link that travels with the number.
6. **People-only authorship of what spans the organisation** — the organisation's ontology, and now
   missions and policies.
7. **The propose-and-confirm pattern** — explore-on-connect, the Watcher's alert proposals, the
   resolve-once queue. It is how the platform avoids being a configuration project.
8. **Declared terms compiled by code**, not interpreted by a model.
9. **The method** — pre-registered falsifiers, receipts before graduation, ratchets that fall and never
   rise, "prove it live". Section M applies it to the customer's business instead of to the codebase.
10. **Queries run where the data lives.** What leaves is measured information, never the rows.
11. **The refusals in §4** — a foreign flow engine, a write side on the warehouse, raw-SQL tools for
    outside agents, a model judge. Each one keeps a single governed path.

---

## E · What to rebuild

1. **One claim ledger.** There are five claim shapes today, mutually unaware: the Explorer's finding
   (stored twice — in exploration state and as a ledger artifact); the deep analysis's finding (a typed
   dict inside the `report_json` blob); `EvidenceClaim` in its own database; a pack's `CoreClaim` inside
   the ontology graph; and the hub's `ClaimCheck` on a staged note. Verdicts sit in a sixth place. This
   is the pattern `AGENTS.md` names — five eval surfaces, thirteen spellings of "out of date", five
   audit sinks. Rebuild as one artifact kind in the kernel ledger, with the hub's envelope and two
   clocks; the other five become writers into it or are retired.
2. **The scope.** The organisation first, the connection second. The object door's cross-connection path
   is the start; glossary, metrics, findings and the Briefing still read one connection.
3. **The deep analysis becomes a run inside an inquiry.** Hypotheses move from a JSON column nothing
   reads to claims in the ledger.
4. **Recommendation and outcome become decision and outcome.** From a flat JSON file and a question
   nobody is sent, to section K — with the review question delivered to the resolved owner through the
   departure gate.
5. **Confidence, from stated to counted.** Section O.
6. **The Briefing's ranking.** From the size of a move and a model-inferred north star, to bearing on a
   mission a person wrote and the cost of waiting — under an attention budget (`IDEAS.md` 9).
7. **Authority.** Standing grants joined to the earned ladder; the approval gate on by default.
8. **Navigation.** Section U.
9. **Packs.** From prose expertise to claims with priors — the direction ON-0a already took ("the map
   as claims, evaluated by tier").
10. **The install.** From one writer on one machine to something an organisation of ten can run. Not
    shared multi-tenancy (section F).

---

## F · The 2027 platform architecture

```
 EXPERIENCE    Now · Inquiries · Decisions · Missions · Record · Operations
               chat channels · the MCP server (outside agents) · receipts by link
 ────────────────────────────────────────────────────────────────────────────────────────────────
 GOVERNANCE    the gate map · policy · groups and clearances · the departure gate
               · the attention budget · audit                        ← every arrow below passes here
 ────────────────────────────────────────────────────────────────────────────────────────────────
 AGENT         seven duties · the job kernel (heartbeats, retries, resume) · model routing by role
               · budgets                                             [the runtime itself: delegated]
 ACTION        declared actions · the outbound gateway · authority · verification · undo
 EVALUATION    scoring at settle · calibration · golden suites · the canary
               · graduation and demotion receipts
 ────────────────────────────────────────────────────────────────────────────────────────────────
 INTELLIGENCE  types, links, processes, promises, rules · definitions · the object door (a compiler)
               · the inquiry engine · the scenario ladder · triage
 MEMORY        THE LEDGER — claims · evidence · decisions · actions · outcomes · missions · policies
               append-only, two clocks.   Indexes: lessons · procedures · preferences · embeddings
 ────────────────────────────────────────────────────────────────────────────────────────────────
 DATA          sources — warehouses, files, business systems, documents — queried in place
               · the settle clock · profiles · mirrors
```

| Concern | Choice | Why |
|---|---|---|
| **Ledger storage** | relational and append-only, in the kernel ledger; SQLite for one person, Postgres for an organisation | the kernel already versions artifacts and keeps lineage; a second ledger would be the ninth store |
| **Graph** | a projection of the ledger, rebuilt on demand; no graph database | the graph is a way of reading claims, not a place they live |
| **Temporal state** | two clocks on every entry; "as recorded on" is a filter | no separate temporal database |
| **Events** | the kernel's append-only journal and the settle tick as the heartbeat | no message broker until one install needs more than one worker |
| **Semantic retrieval** | the embedded vector store, as an index over the ledger and never a source of truth | an unreachable index must degrade to "said so", not to silence |
| **Structured query** | pushed down to the source through the dialect seam | rows do not move |
| **Model routing** | by role, configured per organisation, bring-your-own key; no model id in source | already the rule |
| **Agent runtime** | delegated; today's loops stay as glue | not strategic |
| **Policy engine** | the platform's own, small, structural clauses | adopt an open-source engine only if policies outgrow it |
| **Workflow** | the automations engine on the job kernel | built; a foreign engine is refused (§4.2) |
| **Action gateway** | the outbound seam and the single MCP call door with its five gates | one write path |

**Centralised and decentralised.**

| One per organisation | Many, and replaceable |
|---|---|
| the ledger | compute — it runs in the sources |
| policy and the gate map | agents — any runtime, any vendor, held to the duty contract |
| identity, groups and grants | models — any backend |
| scoring and calibration | actions — they happen in the systems of action |
| the attention budget | packs — declarative, distributed, versioned |

The rule: centralise what must be *consistent* (what is true, what is allowed, what happened, who was
interrupted). Decentralise what must be *abundant*.

**Do not overbuild (the brief's part 27).**

| Component | Buy · open source · delegate · own | Strategic? |
|---|---|---|
| Agent runtime, tool loop | delegate to model vendors' kits | no |
| Connectors to business systems | buy or reach through MCP (§3.4 already decided this) | no |
| Forecasting | open-source libraries or a time-series model | no — the *score* is |
| Causal estimation | open source | no — the *licence* is |
| Process simulation | open source, driven by declared processes | no |
| Matching one thing across sources | open source for candidates; a person confirms; a rejected pair is remembered | partly |
| Vector store | open source, as now | no |
| Policy engine | own while small | the policies are, the engine is not |
| Metric definitions | import from where they already live; own approval and grain | approval is |
| The ledger, the envelope, settling, the departure gate, scoring, authority, the decision record, the scenario ladder, pack priors | **own** | **yes — this is the whole product** |

**Enterprise scale without enterprise weight (the brief's part 19).** One decision carries most of it:
**the install is the tenant.** The customer runs the data plane; one organisation per install; nothing
shared.

| Requirement | How |
|---|---|
| Multi-tenancy · residency · sovereignty · private and hybrid | by deployment: the install runs where the customer says; no shared plane to partition |
| Customer-owned models · model isolation | bring-your-own backend and key, already per organisation |
| Access control | persona groups and function groups with grants by tag (Arc HB's design), enforced once identity is on; row policies as data, not a dict in source |
| Audit · deterministic trails | the append-only ledger and signed receipts; an export door for the customer's own log system (the capability exists and gates nothing today) |
| Availability · recovery | Postgres, stateless API workers, one scheduler leader. **The ledger is the only state that matters** — the graph, the embeddings, the profiles and the mirrors can all be rebuilt from it and the sources |
| Simplicity | defaults come from groups; one gate map; nothing is configurable that can be measured instead |

Arc MT stays dropped: this is not a login wall around a hosted demo. But the honest reading of the table
in section A is that an *organisation's* install — identity on, Postgres, more than one person — is the
dependency of everything in this study, and that is the user's call to make.

**Every architectural decision, and what the customer gets from it.**

| Decision | Product consequence | Customer value |
|---|---|---|
| One ledger, two clocks | "what did we believe when we decided?" is answerable | decisions judged fairly; audits answered in minutes |
| Confidence counted, never stated | every claim shows how often its kind has been right | people learn what to rely on |
| The scorer is code and is never the actor | the platform can grade any vendor's agent, including its own | one independent record across every tool |
| Agents defined by duty, memory in the ledger | a model or vendor can be swapped with nothing lost | no lock-in to a model; the record outlives every model |
| Actions are references with a verification statement | every change is checked and can be undone inside its window | automation people will actually switch on |
| Authority earned on receipts, withdrawn on a miss | autonomy grows exactly where it has worked | less approval work without a leap of faith |
| The install is the tenant | data never leaves; the security review is short | adoption in regulated organisations |
| Packs are claims measured on connect | day one speaks the industry's words without a configuration project | value in days |
---

## G · The core object model

**The atomic unit.** BI's atom is the metric: a definition that returns a number. The 2027 atom is the
**claim**: a number or a statement that knows its warrant, its date, its owner, how often claims like it
have been right, and what would overturn it. The molecule is the closed loop — claim → decision → action
→ outcome — and it is the molecule, not the atom, that compounds.

**Seventeen nouns in the brief; eleven things stored.** Each stored thing must earn its place by being
written by one door and read by at least one consumer (the repo's rule: shipped means consumed). The
other six are kinds, fields or views, and making them stores would repeat the "nine stores behind the
brain" problem the Brain map was built to expose.

| The brief's noun | Here it is | Why |
|---|---|---|
| Entity | **Object** — stored (today's ontology object) | already built; nothing new |
| Event | **Event** — a typed reference, resolved in the source | the hub owns meaning, never the rows |
| Observation · Hypothesis · Prediction | **kinds of Claim** | one envelope, one ledger, one scorer |
| Claim · Evidence | stored | the atom and its warrant |
| Belief | **a view**: the unsuperseded claims as recorded by a date | a second store of "what we believe" would drift from the first |
| Investigation | **Inquiry** *(new word)* — stored | `investigation` is frozen as the name of one deep-analysis run |
| Mission · Decision · Action · Outcome · Policy | stored | each is written once and read by the loop |
| Agent | **Principal** of kind agent | people and agents hold grants the same way |
| Scenario | stored, small: assumptions plus the predictions made under them | so a prediction can be scored against what was assumed |
| Memory | **a view**: the ledger read through time, plus three indexes | section N |

**One envelope.** Everything that asserts carries the same envelope. It already exists in the hub
(`aughor/hub/provenance.py`: the authority ladder, the scope ladder, `observed_at`, `valid_until`,
`author`); the context graph's own `Provenance` is the thinner second carrier that `IDEAS.md` 16 named.
The proposal is to finish that merge, not to design a third.

**Two clocks.** Every entry carries `as_of` (the data's date) and `recorded_at` (when the platform
booked it). With both, "what did we believe on 3 March?" is a query, and a decision can be judged by
what was known when it was taken rather than by what is known now.

```
Object                     what exists — today's ontology object; nothing new to store
  type            → ObjectType (declared or measured; api name stable)
  key             the source key, resolved through the object door, never copied
  bindings[]      connection · table · column, each measured
  links[]         → Object, with measured cardinality
  owner           → Principal, resolved — or said to be unresolved

Event                      what happened — a reference, not a copy
  object          → Object
  kind            a declared process stage (placed, shipped…) | a platform event (decided, acted, restated)
  at              source time
  source          statement + connection, run where the data lives | a ledger entry

Claim                      the atom
  kind            observation | finding | reading | definition | hypothesis | prediction | said | cause
  about           object → segment → type → connection → domain → organisation
  statement       typed where it can be: metric · object set · range · value · unit. Prose is a label, not the claim
  tier            measured > approved > declared > reviewed > said > inferred
  status          Final | Provisional | To date
  as_of · recorded_at · valid_from · valid_until
  warrant[]       → Evidence
  confidence      {reference class, hit rate, n} — a counted frequency, or empty. Never a model's own estimate
  falsifier       the check that would overturn it, and when it next runs
  owner · author  → Principal (person | agent | system)
  supersedes      → Claim, kept with its text
  relied_on_by[]  → Decision

Evidence
  kind            run (statement, result hash, row count, connection, engine, as-of)
                  | document (page, cell) | attestation (a person's verdict) | claim (by id)
  receipt         → Trust Receipt, signed
  reproducible    yes | no, and why not
  supports | contradicts → Claim

  -- three kinds of Claim, spelled out --
  hypothesis      + inquiry · state: open | supported | refuted | abandoned · the evidence that refuted it.
                  A refuted hypothesis stays in the ledger: it is memory.
  prediction      + target (metric, scope, range) · interval (low, mid, high at a stated coverage)
                  · method (section L) · assuming[] · settles_on · score, filled when its range is Final
  observation     one measured reading at tier `measured`. The lowest rung and the highest volume.
                  A finding is an observation that survived triage and carries a comparison.

Inquiry
  question        one sentence, framed in declared business terms where they exist
  opened_by       person | monitor | broken promise | restated claim | mission | review of a missed move
  hypotheses[]    → Claim(hypothesis)
  runs[]          → Run — the work, with its cost
  claims[]        what it has established
  open[]          what it could not settle, and what data would settle it
  decisions[]     → Decision
  state           open | waiting (for days to settle, an owner, a decision) | closed (answered, overtaken, abandoned)
  next_check      when it wakes without being asked
  lessons[]       written at close: what was believed at the start and turned out wrong

Mission
  objective       metric · direction · target · by when
  constraints[]   metrics or promises that must not be damaged, each with its limit
  scope           domain · segment · connections
  owner           → Principal, a person. A mission without an owner does not run
  budget          interruptions a week · spend a month · authority ceiling per action kind
  watches[]       monitors, promises and claims it follows
  review          cadence, and the report: objective against baseline, what the work contributed, what it cost
  state           proposed | active | paused | met | retired

Decision
  question        what is being decided
  owner           → Principal, answerable        approvers[]
  options[]       each: description · predictions[] · cost · reversibility · who would act
  chosen          → option          dissent[]   who disagreed and why, kept
  relied_on[]     → Claim, as recorded at that moment
  objective       → Mission | metric
  decided_at · review_on           the review date is set at the moment of deciding
  actions[] → Action               outcome → Outcome
  reopened_by     a relied-on claim restated or refuted

Action
  kind            → declared action: typed parameters, risk tier,
                  reversibility: undoable until… | compensable | irreversible
  target          → Object | segment, and in which system
  under           → Decision | the standing grant it ran under
  actor           → Principal        authority  L0–L5 at the time, and the receipt that gave it
  expected        → Claim(prediction)
  preview · result
  verification    the statement that checks the change took effect, and its reading
  undo            the compensating action and its window

Outcome
  of              → Decision | Action | Claim(prediction)
  measured_on     the review date, on settled days only
  actual · baseline   baseline = what the metric's own history predicted without the change
  effect          actual − baseline, with an interval and its method
  verdict         as expected | better | worse | cannot tell, and why
  writes_back     each relied-on claim's reference class · the playbook entry
                  · the author's track record · the action kind's grant

Principal
  kind            person | agent | group | service
  agent fields    duty (section H) · model binding (configured, never hardcoded) · tools · scope
  grants[]        (action kind × scope) → authority level, each citing its graduation receipt
  track_record    by claim kind and action kind: n, hit rate, calibration, cost per warranted claim
  budget          spend · rate · interruptions it may cause

Policy
  applies_to      a door on the gate map | an action kind | a tier | a tag | a group
  rule            structural clauses, never an expression string
  effect          allow | hold | withhold | require approval | cap
  says            the sentence shown when it fires. A block always says so
  owner · version · supersedes

Scenario
  for             → Decision | Mission | Inquiry
  assumptions[]   variable · value · source (declared by a person | measured | estimated)
  predictions[]   → Claim(prediction, assuming these)
  limits[]        in words: outside the observed range · no past change of this kind · assumes X holds
```

**How they connect.**

```
 Mission ──opens──▶ Inquiry ──holds──▶ Claim(hypothesis) ──tested by──▶ Run ──produces──▶ Evidence
    │                  │                                                                    │
    │                  └────────establishes────▶ Claim ◀───────────warrants──────────────────┘
    │                                             │  ▲
    │                                relied on by │  │ writes back (calibration)
    ▼                                             ▼  │
 Decision ◀──each option carries── Claim(prediction), made under a Scenario
    │                                                ▲
    └──authorises──▶ Action ──verified by──▶ Claim(observation)
                       │                             │ scored when its range is Final
                       └──reviewed on the date──▶ Outcome
```

Policy constrains every arrow. A Principal is the owner, author or actor of every node. Objects and
Events are what every Claim is about.

---

## H · Agent architecture

**The rule that decides whether an agent exists.** A model is used only where judgment under ambiguity
is needed. Anything that must give the same answer twice is code. That removes four of the brief's
eleven agent types before the taxonomy starts:

- *Governance agents* and *auditor agents* — policy, ranking and gating are deterministic. The roadmap
  already refuses "a model that decides who receives what, or which context outranks which" (§8).
- *Evaluator agents* — the scorer is ground truth: execution, settled readings, a person's verdict. A
  model may sort what a person should look at first; it never issues a pass (§4.8).
- *Domain agents* — a domain is a pack (data and declarations), not a different agent.
- *Decision agents* — a decision belongs to a person or to a standing grant a person gave. Agents
  prepare it.

**What remains: seven duties.** An agent is defined by the kind of entry it is licensed to book in the
ledger, not by a persona. Six of today's built-in agents already map; two duties are empty.

| Duty | Books | Today | Why it must exist |
|---|---|---|---|
| **Observe** | observations, proposed monitors | Explorer, Watcher | somebody has to look where nobody asked |
| **Inquire** | hypotheses, findings | Analyst (SQL Engineer, Narrator, Orchestrator inside it) | explanation is a search over causes |
| **Challenge** | contradicting evidence, refutations | Verifier; the skeptic step and its `causal_checks` record | a claim rises a tier only after an attempt to break it — by a different binding from the one that made it, where the install has two |
| **Forecast** | predictions, scenarios | *none* | a system that never commits to an expectation can never be scored |
| **Steward** | proposed definitions, duplicates, coverage gaps | Curator, the business explorer | the model of the business goes stale; people confirm what a steward proposes |
| **Operate** | previews, executions, verifications | *none* (the propose-only tool is the seed) | closes the loop |
| **Deliver** | departures: answers, Briefings, questions to owners | Responder, Briefer | attention is spent at this door and nowhere else |

A custom agent stays what §4.1 says it is: one record, a scope and a stance — now over one or more
duties. An **outside agent** (any vendor's) takes the same duties through the MCP server, under a
service principal, held to the same contract. That is the point of defining agents by duty: the
platform does not need its own agents to be the best ones.

| Concern | Design | Product consequence |
|---|---|---|
| **Lifecycle** | declared → rehearsed on goldens → on probation (its output reaches only its declarer) → graduated per duty and scope on a receipt → demoted on a miss → retired, record kept | a new agent cannot embarrass anyone in its first week |
| **Memory** | none of its own beyond the run. What is worth keeping is booked to the ledger, where it is dated, governed and visible | changing a model or a vendor loses nothing; nothing is remembered that nobody can inspect |
| **Identity** | a service principal; every entry carries its author | "which agent told us this, and how often is it right?" has an answer |
| **Permissions** | reads by clearance, books by duty, acts by grant; tools are doors on the gate map | one place to see everything an agent can reach |
| **Delegation** | a typed sub-question, never a paragraph (the judgment seam's rule). The delegate's authority is the intersection of both principals' grants | delegation can never raise authority |
| **Communication** | agents do not message each other. They read and write the inquiry. Disagreement is two claims on one hypothesis, shown as contested | no transcript of bots talking; a person reads one page |
| **Evaluation** | by what became of its entries: observations restated, findings that survived challenge and a person's verdict, predictions inside their interval, actions verified and inside expectation, deliveries opened and not marked wrong — and cost per warranted claim | an agent's score is a count, not an opinion |
| **Failure** | a typed verdict — no data · no definition · withheld · out of budget · tool failed · contradicted — never an empty result. A failed run books nothing and says why; partial work stays on the inquiry | a failure and a true negative never look alike |
| **Cost** | budgets on the mission and the principal. A run is proposed with what it costs and what its result could change; the cheapest test goes first; work stops when no open hypothesis could change the decision | spend follows the value of the information, not the size of the question |
| **Escalation** | to the resolved owner of the object, metric or mission — by rule, once, the answer remembered | questions land with someone who can answer them |
| **Autonomy** | section M | — |

---

## I · The intelligence loop

Today the loop starts when a person asks. In 2027 it starts when something changes, and it is driven by
the ledger, not by conversations. Agents are called by the loop; the model of the business is not a
by-product of their chats.

```
settle tick — code, cheap, on the clock that already runs
  ├─ re-measure claims whose days have settled or whose re-check is due       → restatements
  ├─ score predictions whose range is now Final                               → calibration
  ├─ measure outcomes whose review date has come                              → write-backs
  ├─ evaluate monitors, promises and cockpit limits                           → signals
  └─ mark what depends on anything that changed as dirty: claims, decisions, cards, Briefings
triage — code
  ├─ rank by: bears on a mission · size against its own normal range · cost of waiting · new against lessons
  └─ charge the attention budget; hold the rest and keep the list of what was held
inquire — agents, only where triage says the spend is worth it
  ├─ open or wake an inquiry · hypotheses · cheapest test first · challenge the survivor
  └─ book claims; say what could not be settled and what would settle it
deliver — the departure gate
  └─ to the owner, where they already are, once, with the receipt
```

The world model is therefore a **dependency graph of claims with invalidation** — closer to a build
system than to a chat history. The platform already speaks this language for artifacts (fresh · dirty ·
stale, and the lineage-aware cascade); the proposal extends it from artifacts to beliefs.

**What the loop looks for, and by what mechanism.** Each line names something that exists or the piece
that is missing.

| Looks for | Mechanism | State |
|---|---|---|
| Anomalies | each metric's own learned normal range | built (the Watcher) |
| Weak signals before a KPI moves | the early stages of a declared process (dispatch lag before late delivery); a distribution shifting before its mean; the settling lag itself changing | a broken promise and a new finding are both automation triggers in code (`automations/models.py`; the roadmap §1 line saying neither is one is stale). A process's early stages and the settling lag are not signals yet |
| Causal candidates | candidate breakdowns, then the skeptic step | built 2026-09-22 and 2026-10-04 |
| Against history | the metric's own baseline | built in parts |
| Against plan | predictions and mission targets | **missing** — nothing books an expectation |
| Regime change | change points on settled series; a declared cardinality or grain that stops holding | drift checks were scoped (Wave O6); not a signal today |
| Hidden relationships | only along measured links, across connections through the organisation's ontology — every screen counts its tests | the links are built; the screen is not, deliberately: a correlation hunt without a count of tests is a false-discovery machine |
| Contradictions | what people say against what the data shows; two readings of one metric; two contested claims | built (CB-8, the departure gate's owner question) |
| Opportunities | segments beating their baseline; playbook entries with a good record that were never tried here | **missing** — triage ranks bad news |
| Unresolved questions | inquiries that are waiting, each with what would settle it | **missing** — a deep analysis ends when its report is written |

**The inquiry is the durable object.** A deep analysis today is a run: it produces a report and ends. An
inquiry outlives its runs. It waits for days to settle, wakes when a claim it relied on is restated,
remembers which hypotheses were refuted so the next run does not test them again, and closes with what
was believed at the start and turned out wrong. Its page is a record, not a transcript (section V).

---

## J · Mission architecture

A **mission** *(new word; `IDEAS.md` 21's "priorities, written by people, each naming a metric and a
target" is its first slice)* is a standing objective a person gives the platform:

```
"Protect gross margin."                 objective    gross margin ≥ 41%, rolling 4 weeks
"…without damaging service levels."     constraint   delivery promise kept ≥ 92%
                                        scope        EU, apparel
                                        owner        a named person
                                        budget       3 interruptions a week · a monthly spend cap
                                                     · authority ceiling: L3 for price changes, L4 for promo pauses
                                        review       monthly, against baseline
```

```
MISSION → watches (monitors, promises, claims) → signals → triage against the objective
        → inquiries → hypotheses → claims → a decision put to the owner, each option with its prediction
        → actions under the mission's authority ceiling → outcomes on the review date
        → the mission report: objective against baseline · what the work contributed · what it cost
        → lessons, and changed priors for the next cycle
```

**How a mission differs from a workflow (an automation).**

| | Automation | Mission |
|---|---|---|
| Says | what to do, step by step | what to achieve, and what not to damage |
| Starts | on its trigger | never stops; it is a standing interest |
| Steps | fixed, drawn | none fixed; inquiries open as signals bear on the objective |
| Ends | when the steps ran | when a person retires it |
| Judged by | did it run | did the objective move against its baseline, and at what cost |
| Authority | each step's grant | a ceiling the owner sets, inside which authority is earned |
| Fails by | erroring | being wrong — which it reports |

An automation is how a mission *acts* (the engine, its seven triggers and thirteen effects stay). A
mission is why. People write missions; a model never does — the same rule the organisation's ontology follows.

**What a mission must not become:** a to-do list for agents to look busy. Two guards. A mission is
charged for every interruption it causes, out of its owner's attention budget. And its report leads with
the objective against baseline, so a mission that produced forty findings and moved nothing reads as
exactly that.

---

## K · Decision architecture

**The decision ledger is the missing half of the books.** The pieces around it exist. A recommendation
sits in the Inbox; an approval sits in a resolve-once queue with its reasoning and proposer; on
acceptance a baseline is measured, a review is set thirty days out and an hourly job re-measures it
(`aughor/playbook/outcomes.py`, a flat JSON file). The platform even keeps a proper decision record —
context, the options, the one chosen, the outcome — but only for the *machine's* own choices
(`aughor/learning/decisions.py`). What it does not hold is the organisation's decision: what was being
chosen between, what was expected, who dissented, which beliefs it stood on. And the review question it
does generate is shown in the Inbox and written to a log; it is never sent to anyone.

**Capture has to cost nearly nothing, or the ledger stays empty** — the outcome loop already proved that
by running end to end with no outcome ever recorded. Three rules:

1. **A decision is recorded as a by-product, never as a form.** Accepting a recommendation, approving an
   action, or replying "we are going with B" in a thread the platform has answered *is* the record. The
   platform fills the rest: the claims on the page at that moment become `relied_on`; the options it had
   prepared become `options`; the review date is proposed from the metric's settling lag.
2. **The expectation is booked at the moment of deciding.** One line: "expected: conversion +2% to +4% by
   14 November." Without it there is nothing to score. With it, `IDEAS.md` 13 and 22 are both answered:
   the review date exists, and the outcome is judged against what the metric's own history predicted, not
   against "before".
3. **Decisions taken elsewhere are declared in one sentence.** The platform does not crawl mail or chat to
   find them — the hub's first law stands. A person says "we decided X"; the platform attaches the claims
   and asks for the expectation.

**What the ledger makes answerable** — each is a query, not a model's impression:

| Question | Read from |
|---|---|
| How does this organisation actually decide? | time from signal to decision · options considered per decision · share with a booked expectation · share reviewed |
| Which decisions keep producing poor outcomes? | outcomes by decision kind, owner group and playbook entry |
| Which assumptions are consistently wrong? | predictions outside their interval, grouped by method, metric and author |
| Which teams overestimate or underestimate? | the signed error of predictions by owner group |
| Which decision should be revisited? | decisions whose relied-on claims were restated or refuted since |
| What did we believe when we chose this? | the ledger as recorded on that date |

The last two are what the second clock buys. They are also the two a competitor cannot produce on the day
it arrives, however good its model is.

---

## L · Simulation architecture

**One ladder of methods, each with a licence.** The departure gate already holds a causal sentence that
has no verdict behind it. A scenario answer is treated the same way: it carries the method that produced
it, and it takes the *weakest* method on its path as its tier.

| # | Method | Answers | Comes from | Must say |
|---|---|---|---|---|
| 1 | **Identity** — deterministic | the arithmetic inside a definition: price × units, the margin tree | metric statements and formulas already declared | what is held fixed |
| 2 | **Declared assumption** — human-specified | "if demand stays elevated for 30 days", "if supplier X fails" | a person's assumption, booked as a `declared` claim with their name | whose assumption it is |
| 3 | **History** — statistical | what the metric's own past predicts for a period | settled series; a bought forecasting library or time-series model | its interval, and its backtest error on this metric |
| 4 | **Intervention** — causal | the effect of a change of this kind | **the decision ledger's own outcomes**; holdouts; natural experiments | how many past cases, or that there are none |
| 5 | **Simulation** | a flow through a declared process: queue, capacity, lead time, stock | the ontology's processes and promises, with measured stage durations | which stages are measured and which assumed |
| 6 | **Learned** | structure nobody declared | fitted models | refused above a stated stake unless backtested on this install |

**Worked example — "what happens if price rises 7%?"** Method 1 gives the mechanical part exactly:
revenue at constant units. The volume response is method 4 if the ledger holds past price changes in this
category ("3 past changes; effect on units −2% to −9%"), and otherwise method 2 — a person states an
elasticity and their name goes on it. The answer shows the two parts separately, each with its method.
What the platform never does is let a model supply the elasticity: that is the `llm_inferred` provenance
the repo deliberately does not have.

**What is owned and what is bought.** The forecaster, the causal estimator and the simulator are bought
or open source (section F). What is owned is the ladder, the licence, the backtest and the score — the
part that says how far to trust the answer. And method 4 is fed by section K: every reviewed decision is
one more past case. That is the link that makes the two systems one. Its seed is already in the code: a
proposed cause becomes a confirmed causal edge only when a recommendation is marked verified
(`aughor/lifecycle/causal.py`), and the deep analysis reads those edges. No recommendation has ever been
marked, so the graph has had nothing to grow from.

**A scenario with no decision attached is a toy.** Scenarios live inside a decision, a mission or an
inquiry (section G), and every prediction made under one is scored when its days settle — including the
ones for the option that was not chosen, where a baseline allows it.

---

## M · Action architecture

**The substrate stays thin.** The platform does not become a system of action. An action is a
*reference* to something that already exists — an integration call or an allowlisted MCP tool — wrapped
in a declaration. That is the roadmap's own structural law (§4.2: "their node is code; ours is a
reference"), and it is what keeps one governed write path.

Every declared action carries: typed parameters · risk tier · reversibility class · a preview · a
**verification statement** (the read that proves the change took effect) · an undo and its window · an
expected outcome · a review date. An action with no verification statement cannot be declared.

**Graduated autonomy.**

| Level | Means | Granted when |
|---|---|---|
| L0 observe | no action | the default for anything undeclared |
| L1 recommend | the agent proposes | the action is declared |
| L2 prepare | preview and parameters ready for one tap | a dry run and a verification statement exist |
| L3 execute with approval | a person approves each | the owner is resolved; the action is undoable or compensable |
| L4 execute within policy | a standing grant: bound to a target and a scope, with limits on count and value, and an expiry | a graduation receipt: *n* approved executions, every verification passed, outcomes inside expectation |
| L5 autonomous | the agent chooses *among* declared actions toward a mission, inside its budget | a long L4 record; reviewed on the mission's cadence |

```
authority(action kind, scope) = the lower of
      the ceiling a person set                      — policy
      what the record has earned                    — reversibility × blast radius × value at risk
                                                      × verified executions × outcomes inside expectation
```

Three rules hold at every level. Authority is granted on a receipt, the way a flag graduates
(`GraduationDecision`), never on a demonstration. It is **taken away automatically** on a failed
verification or an unexplained miss, and the demotion is itself a ledger entry. And an irreversible
action never passes L3.

**What already exists.** More than the levels suggest. A standing grant is built
(`aughor/actions/grants.py`): a person pre-authorises one action for one exact target value, the grant
bypasses approval and never the action's criteria, and every use cites it. An earned ladder is built too
(`aughor/memory/trust.py`): a connection climbs L0–L3 on its count of clean, grounded runs — and its
only consumer today is whether a learned skill is drafted. The two have never met. The proposal is to
join them: key the ladder by action kind and scope instead of by connection, feed it verified executions
and outcomes instead of clean runs, and let it widen or withdraw standing grants. One default has to
change first: the approval gate is off unless an environment variable is set, so on a fresh install a
high-risk action is not held at all.

**Where this contradicts a standing decision.** §4.8 refuses executing grants for agents: "an agent
proposes; a person acts." This study asks to reopen that — and only that — on one condition, which is
not yet met: outcomes are being recorded and scored. Today none has ever been recorded, so there is no
record for authority to be earned on, and the refusal is correct as it stands. §4.7 is not reopened: the
platform writes nothing to a customer's warehouse at any level.

---

## N · Organisational memory

Memory is not a store. It is the ledger read through time, plus three indexes over it.

| Kind | Holds | Today | Rule |
|---|---|---|---|
| **Episodic** | runs, traces, trajectories | built (the session log, Arc TJ) | payloads kept for a short capture window; the step record kept long |
| **Semantic** | claims, objects, definitions | built in several stores — the Brain map counts nine | one envelope, two clocks |
| **Procedural** | playbook entries, starters, query templates, remembered SQL | built; a rejected query is evicted | every procedure carries a success rate learned from outcomes, not from use |
| **Decision** | decisions, options, expectations, outcomes | **missing** | section K |
| **Organisational** | declared terms, missions, owners, policies, preferences | declared terms, owners and policies built; missions and preferences missing | written by people only |

**The system must remember what it was wrong about.** Four records, each a first-class view under
*Corrections* rather than something buried in history:

1. **Restatements** — a number it gave that later changed (built: `answers.recheck`).
2. **Refuted hypotheses** — what it thought the cause was and tested false. Kept on the inquiry and read
   before the next inquiry on the same object generates hypotheses. Today each hypothesis's verdict is
   saved (`investigations.hypotheses_json`) and nothing ever reads it back; the report's "what is not the
   cause" is filled from data gaps, not from what was refuted.
3. **Missed moves** — something a person found by asking that nothing had flagged (built 2026-10-04).
4. **Predictions outside their interval, and decisions that went worse than expected** — missing.

| Concern | Design |
|---|---|
| **Provenance** | the envelope; no entry without a source; no model-authored fact |
| **Versioning** | a claim records the version of the definition it was measured under; changing a definition marks its dependents dirty |
| **Conflict** | code decides, never a model: authority tier, then scope (narrower wins), then recency *by kind*. Two claims at the same tier are shown as contested and the owner is asked once; the answer is remembered |
| **Retention** | the record is kept; payloads expire |
| **Forgetting** | supersession and loss of *reach*, not deletion. An observation's reach into a prompt decays; an approved definition's does not. Real deletion happens in two cases only — a person reverses durable intent (the tombstone first), or the law requires erasure — and each leaves a tombstone |

---

## O · Trust and provenance; evaluation

**The chain.** Every consequential output can be walked back through:

```
CLAIM → reasoning artifact (the inquiry, its hypotheses, the record of what challenged them)
      → EVIDENCE → SOURCE (statement, connection, engine, as-of)
      → TRANSFORMATION (definition version, formula, binding)
      → MODEL (the binding and version, on the receipt) → AGENT (the principal)
      → ACTION → OUTCOME
```

| Lineage | Carried by | State |
|---|---|---|
| Data | the statement, its tables, the engine and the as-of on the receipt | built |
| Semantic | the definition version and the declared terms a question was framed with | built; shown with the answer |
| Agent | the author on every entry; the trace | built for runs; not on every claim |
| Decision | `relied_on` | **missing** |
| Action | the audit trail; the grant cited on every auto-allowed run | built |
| Model | the model id on the receipt | fixed 2026-09-26 (TJ-1) |
| Freshness | Final · Provisional · To date; fresh · dirty · stale | built |
| Reproducibility | re-perform the statement and compare: "re-performed today 1,802; booked 1,744 on 12 September; the difference is late rows" | built as the re-check; not offered as a button on a receipt |

**"Why did the system tell me this?"** is one page, the same for a person and for an outside agent: the
claim; what warrants it; what it relied on; how often claims of its class have been right; what would
overturn it; who else was told; and whether it has changed since.

**The seven lines.** Every consequential conclusion is written in the same order, each line from a field,
none from a model's phrasing of its own confidence:

| Line | Field |
|---|---|
| What we know | claims at tier `measured` or `approved`, status Final |
| What we think | claims below that, each with its counted confidence |
| What we do not know | *Unmeasured*; coverage gaps; open questions on the inquiry |
| Why we think it | the warrant chain |
| What disagrees | contradicting evidence; contested claims; what people said that the data did not confirm |
| What would change our mind | the falsifier, and when it next runs |
| What it costs to wait | exposure a day × the days until the next settled reading, where both are measured |

**Confidence is a counted frequency or it is not shown.** The one calibration the platform has taken on a
model's stated confidence found it right 61% of the time at a stated confidence of about 1.0 (CP-2,
2026-10-04). A model's own estimate of its certainty is not a number to print. Today an answer's
HIGH · MEDIUM · LOW is the model's, capped by one skeptic call, and the evidence ledger writes 0.8 for a
significant result and 0.5 otherwise (`aughor/evidence/linker.py`). Neither has been compared with what
happened. Confidence on a claim should be the hit rate of its reference class — this kind of claim, this
method, this source — with its *n*; where *n* is small it says so.

### Evaluation — how the platform knows it is intelligent, and when it is getting worse

| Level | Measures | Ground truth | State |
|---|---|---|---|
| **Claim** | factual and analytical accuracy | golden suites compared by result set; the guard battery at 100% of traffic; restatement rate | built |
| **Cause** | causal reasoning | share of stated causes that survived a recorded challenge; later, method-4 estimates against held-out outcomes | record built 2026-10-04; no rate published |
| **Prediction** | forecast accuracy, calibration | interval coverage and signed error at settle, by method, metric and author | missing |
| **Decision** | decision quality | outcome against expectation *and* against baseline — a good decision can have a bad outcome, so both are kept | missing |
| **Action** | correctness | verification pass rate; undo rate | missing |
| **Agent** | usefulness, efficiency | what became of its entries (section H); cost per warranted claim | cost built; the rest missing |
| **Attention** | false positives and negatives | alerts acted on against alerts sent; missed moves; what was held and later mattered | backtest, drill and missed-move review built; no rate published |
| **Mission** | business outcome | objective against baseline, with the interval | missing |

Three things make it continuous. A **canary**: a small golden suite run against the live model binding on
the existing clock, so a silent provider swap shows as a drop — the cheap cover the roadmap noted when it
dropped online evals, and never queued. **Calibration by month**, published as the product's own number.
And **automatic demotion** (section M), which is evaluation with a consequence.

One refusal stands and should stay: no model grades live traffic into a score (dropped 2026-09-06, with
its revisit triggers). Ground truth beats a judge, and by 2027 the platform will have more ground truth,
not less.

---

## P · Vertical and horizontal strategy

**The kernel — what works identically in every industry.** The ledger and its envelope · the settle
clock · the object door · the definition store (statement, grain, version, approval) · the inquiry
engine · decision and outcome records · the scenario ladder (the method interface, not the models) · the
action gateway and authority · policy, the gate map and the departure gate · the attention budget ·
scoring and calibration · principals and grants · the pack loader.

**What never enters the kernel.**

- An industry noun — order, patient, loan, shipment.
- A metric's definition, a threshold, or what counts as normal.
- A model id (already a rule), a vendor's API shape, a dialect quirk (those live at the dialect seam).
- Prose expertise the kernel would have to interpret.
- A forecasting, causal or simulation model — they come through the method interface.
- A screen that exists for one industry.
- Rows.

The test is one the repo knows how to write: the kernel passes its suite with no pack installed, and a
ratchet counts industry nouns in its source — a baseline that may fall and never rise.

**What belongs at each layer.**

| Layer | Holds | Written by |
|---|---|---|
| **Core platform** | the kernel | the vendor |
| **Domain pack** | object types, links, processes and promises *as claims to be measured against the customer's data*; metric statements with grain; starters; monitors with prior normal ranges; playbook entries with base rates; scenario templates; action declarations; golden questions; mission templates | the vendor and third parties — declarations only, never code |
| **Organisational context** | the bindings from a pack's types to the customer's tables; approved definitions; owners; groups; missions; policies; preferences | the customer's people, only |
| **Custom agents** | a scope and a stance over the seven duties | the customer; no new primitive |
| **Custom ontologies** | declarations through the same doors as a pack's | the customer's people |
| **Custom actions** | a reference to an integration call or an allowlisted MCP tool, with parameters, a verification statement and an undo | the customer or a third party; the code lives outside the platform |

**How one platform avoids the four failures.**

| Failure | Guard |
|---|---|
| A generic abstraction nobody loves | the kernel is never shown bare; with a pack bound, every screen speaks the industry's words on day one |
| Disconnected vertical apps | a pack is data over one kernel. It cannot add a store, a screen type or a code path — ratcheted |
| An enormous configuration project | *confirm, do not configure.* A pack's claims are measured against the data on connect; what fits is proposed, what does not becomes the shopping list (`IDEAS.md` 10). People confirm |
| A consulting-heavy implementation | onboarding has one measured number — hours from connect to the first warranted claim someone relied on — and it is a release gate |

### Five verticals

Chosen for the shortest path to a reference customer: two the repo already has data and packs for, one
with a drafted package, two where the declared-process machinery is the natural fit. Healthcare, energy
and government are deliberately not in the first five — in each, custody and compliance cost arrives
before any value does.

**1 · Commerce (retail and e-commerce)** — core 80% · vertical 20%

| | |
|---|---|
| Objects | Customer · Order · Order line · Product · SKU · Channel · Supplier · Promotion · Shipment · Return |
| Events | placed · paid · shipped · delivered · returned · price changed · promotion started · stock-out |
| Metrics | GMV · net revenue · AOV · conversion · return rate · sell-through · gross margin · stock cover · on-time delivery |
| Stances | pricing and promotion · inventory · fulfilment |
| Missions | protect gross margin · cut returns without hurting conversion · keep stock cover inside a band |
| Decisions | a price change · a promotion go or no-go · reorder · delist · a carrier switch |
| Actions | pause a promotion · change a price in the commerce system · draft a purchase order · open a carrier ticket |
| Scenarios | price (identity + past changes) · promotion cannibalisation · stock cover under a demand assumption |
| Sources | the warehouse · the commerce platform · ERP and warehouse systems · ad platforms · carrier feeds |
| On screen | the margin tree on Now; SKU and Supplier pages; promises kept and broken by stage |
| Already here | two packs; theLook, Olist and LuxExperience; the order-to-delivery promise measured at 9.35% and 8.11% |

**2 · B2B SaaS** — core 80% · vertical 20%

| | |
|---|---|
| Objects | Account · Contact · Opportunity · Subscription · Invoice · Plan · Seat · Ticket |
| Events | lead created · stage changed · won · lost · activated · expanded · downgraded · churned · renewed |
| Metrics | ARR · net and gross retention · pipeline coverage · win rate · sales cycle · activation · payback · runway |
| Stances | pipeline · retention · capacity |
| Missions | hold net retention above a floor · find churn risk early · improve forecast accuracy |
| Decisions | pricing and packaging · hiring pace · a discount · a renewal approach for one account |
| Actions | create a customer-success task · mark an account at risk · open a ticket |
| Scenarios | hire 20% faster → ramp → capacity → bookings · the loss of a named customer · a conversion assumption on the pipeline |
| Sources | the CRM and billing connectors that already exist · product events · support |
| On screen | the quarter's forecast calls, each scored when the quarter closes — here the prediction ledger *is* the product |

**3 · Banking and lending** — core 70% · vertical 30%

| | |
|---|---|
| Objects | Customer · Account · Loan · Application · Collateral · Product · Counterparty |
| Events | applied · approved · disbursed · payment due, made, missed · rolled to a bucket · restructured · charged off |
| Metrics | net interest margin · cost of risk · delinquency buckets · roll rates · vintages · approval rate · liquidity coverage |
| Stances | credit risk · liquidity · collections |
| Missions | hold cost of risk under a limit without cutting approvals below a floor |
| Decisions | a policy cut-off · pricing · a limit change · a collections strategy |
| Actions | L1–L3 only: draft a policy memo · queue accounts for review. Most are irreversible and regulated |
| Scenarios | vintage curves under a policy change · stress under declared assumptions · liquidity run-off (identity) |
| Sources | core banking · origination · collections · treasury |
| On screen | every figure with the version of its regulatory definition; the decision ledger as model-risk evidence |
| Already here | a drafted package awaiting a person's activation; loan-level metrics still uncovered |

This is the vertical where the ledger is bought for its own sake: a regulator asks what was believed
when a decision was taken, and the second clock answers.

**4 · Logistics and fulfilment** — core 75% · vertical 25%

| | |
|---|---|
| Objects | Shipment · Stop · Route · Vehicle · Warehouse · Carrier · Lane · Customer |
| Events | booked · picked · departed · arrived · delivered · exception · claim |
| Metrics | on-time in full · dwell · cost per drop · fill rate · lane margin · claims rate |
| Stances | network · carrier performance · capacity |
| Missions | hold on-time above a floor at a cost per drop under a ceiling |
| Decisions | carrier allocation · lane pricing · adding capacity · cut-off times |
| Actions | reassign a carrier on a lane · open a claim · tell customers about a delay |
| Scenarios | lead time under a capacity change — a flow through measured stages, the natural home of method 5 |
| Sources | transport and warehouse systems · telematics · carrier portals |
| On screen | the promise board: where in the process promises break |

**5 · Manufacturing** — core 70% · vertical 30%

| | |
|---|---|
| Objects | Plant · Line · Machine · Work order · Batch · Part · Supplier · Defect · Maintenance order |
| Events | started · stopped · changeover · completed · inspected · failed · maintained |
| Metrics | equipment effectiveness · yield · scrap · cycle time · time between failures · schedule adherence · cost per unit |
| Stances | quality · maintenance · supply |
| Missions | raise throughput without raising scrap |
| Decisions | when to maintain · a supplier switch · a schedule change · a quality hold |
| Actions | raise a maintenance order · put a batch on hold · request a supplier's corrective action |
| Scenarios | throughput under a downtime assumption · a supplier failing, against stock on hand |
| Sources | execution, planning and quality systems · the historian — sensor rows stay where they are; only readings are booked |
| On screen | line pages; schedule adherence as the promise |

Across the five, what differs is nouns, definitions, priors and a handful of scenario templates. Inquiry,
decision, scenario, mission, authority and the receipt are identical — which is the 70–80%.

---

## Q · The developer ecosystem

**The platform's equivalent of an app is the pack.** Not code that runs inside the platform — a bundle
of declarations the platform measures, compiles and scores. That is the same structural choice §4.2 made
against a foreign flow engine, and it is what lets a third party extend the platform without opening a
second write path.

A 2027 pack holds: types, links, processes, promises and rules (as claims) · metric statements · starters
· monitors with priors · playbook entries with base rates · scenario templates · action declarations ·
mission templates · golden questions with reference SQL · its own measured record (how often its claims
held on the installs that bound it).

| Interface | For | State today |
|---|---|---|
| **Ledger API** — post a claim with its warrant; read claims as recorded on a date; subscribe to restatements | outside agents, other tools | the pieces exist behind 66 routers; no published contract |
| **MCP server** | any vendor's agent, under a service principal and the agent policy | built: 18 tools plus live ones; no raw-SQL tool, by design |
| **Events out** | a restated claim, a broken promise, a decision due, an outcome scored — as webhooks | automations can do this; there is no stable event catalogue |
| **Pack kit** — validate, bind against a sample warehouse, run the compile test, measure, publish | pack authors | `aughor packs list · check · measure · promote · demote` exist; packs cannot be uploaded and there is no authoring guide |
| **Action kit** — declare parameters, risk, verification and undo over an integration call or an MCP tool | integrators | declared actions exist; adding an integration operation means editing source |
| **Evaluation kit** — golden questions, falsifiers, a backtest for a scenario method | pack and method authors | suites exist; not packaged |
| **Method interface** — register a forecaster, estimator or simulator with its backtest | model builders | missing |
| **Agent contract** — the seven duties, the typed failure verdicts, what an entry must carry | agent builders | missing as a document; implicit in the code |
| **UI** | *cards only*: a card's spec in the cockpit's existing format. No arbitrary interface code | built for cockpits |

What third parties can build: packs, connectors (as MCP servers), actions, agents (outside, through the
contract), scenario methods, mission templates. What they cannot: anything that writes to the ledger
without a warrant, anything that runs inside the platform's process, anything that grades itself.

The ecosystem's quality bar is the product's own: a pack is listed with its measured record, and a pack
whose claims keep failing on real installs is demoted by the same receipt that promoted it.

---

## R · The business model

**What not to price.**

- **Seats.** Agents become the main readers, and the product's job is to need *less* of each person's
  time. Seats would price the wrong thing in both directions.
- **Decisions recorded or loops closed.** That taxes the behaviour the whole product depends on.
- **Tokens, at a markup.** Inference is a commodity the customer can bring. The platform already says
  what a call cost and says so when it cannot price one.

**The recommendation — three parts.**

1. **A platform fee by scope under record.** Priced on the number of governed domains (commerce,
   finance, supply) an organisation keeps in the ledger, each with unlimited people and unlimited
   agents reading and writing. Every additional reader makes the record more embedded, so readers are
   free.
2. **Work at cost.** Model and compute spend is metered, shown, and passed through — the customer's own
   key at no markup, or bundled at a published margin. Budgets belong to missions and principals, so a
   customer sees what each objective cost.
3. **Missions, by authority.** An active mission is priced by the highest level it is allowed to act at:
   watching and recommending is cheap; executing within policy costs more, because that is where work is
   actually taken off people.

**Outcome-linked pricing — offered, never required.** For a mission whose objective the ledger itself
measures against a baseline, a share of the measured effect is possible, because for once both sides can
audit the number: the method, its interval and its receipt are on the page. It should stay optional —
attribution is honest only where the scenario ladder says it is.

**Packs.** A subscription, with a revenue share to third-party authors. A subscription rather than a
purchase because a pack's value is its priors, and those update.

**How the three free tiers of today map.** The licence tiers exist (free, pro, enterprise; the default
is enterprise and several capabilities gate nothing). The single-analyst install stays free: it is the
workbench that produces packs and proof. The organisation's install is what is sold.

---

## S · Moats and the flywheel

**Ranked by defensibility.**

| # | Layer | Why it holds — or does not |
|---|---|---|
| 1 | **The decision-and-outcome history** | time-locked and specific to one organisation. A competitor arriving in 2027 with a better model starts at zero and cannot buy two years of calendar |
| 2 | **Calibration** — the counted record of how often each kind of claim, method, agent and pack was right | it is what turns a claim into something relied on, and it only accumulates on top of 1 |
| 3 | **Declared organisational context** — terms, promises, missions, owners, policies | written by the customer's people; leaving means re-agreeing all of it |
| 4 | **The receipt as the standard** — once "nothing leaves without a receipt" is how a company works, every other tool's output is measured against it | workflow embedding of the strongest kind: it is a control, not a habit |
| 5 | **Pack priors across customers** — base rates and normal ranges learned on many installs, shared only as aggregates | a network effect, and the one thing an internal build can never have |
| 6 | **Independence** — the scorer is not the actor | structural: the vendors best placed to copy the product are the ones who cannot be the neutral party |
| 7 | **Vertical expertise in packs** | medium — the declarations can be read and copied; the priors cannot |
| 8 | **Ecosystem** | potentially high, late |
| 9 | **Action infrastructure** | low — connectors are a commodity |
| 10 | **The ontology as such** | low by 2027 — every data platform will have one |
| 11 | **Agents, prompts, SQL scaffolding** | none |

**The flywheel.** It does not start at "more data". Data is the one input every competitor has.

```
   a number someone relies on, with its receipt          ← it starts here
→  the reliance is recorded (a decision, with what was expected)
→  the outcome is measured on the review date, against baseline
→  it is written back: the claim's class, the method, the playbook entry, the author
→  confidence becomes a counted frequency
→  people — and other vendors' agents — rely on more of it, for larger things
→  authority is earned for more kinds of action
→  more decisions pass through, with more at stake
→  more outcomes
```

Its first turn is small and specific: **one warranted number that leaves the platform and is acted on by
someone who is not the analyst.** Everything upstream of that already exists. What has never happened is
the second arrow.

What stops a competitor copying it: the loop is cheap to describe and slow to run. Its inputs are a
customer's decisions and the months it takes for their outcomes to settle; neither can be generated.

---

## T · Magic moments

Each of these uses a mechanism named above. The ones marked *(today)* work on the current build.

**The number tells the truth about itself**

1. *(today)* "We said 1,744 on the 12th. It is 1,802 now — late orders, not an error." Sent to the
   person who was given the old number, in the thread they were given it in.
2. *(today)* A figure met in a slide three months later carries a link: the statement that produced it,
   how old the data was, and whether it still holds.
3. *(today)* "Yesterday is still provisional — a tenth of its orders have not arrived. Tuesday will be
   final on Friday." No dashboard says this.
4. The lag itself moves: "orders used to settle in 8 days; for three weeks they have taken 13." A change
   in how the data arrives, flagged before any metric moves.

**The platform checks, it does not just produce**

5. *(today)* The night before a board meeting, the memo is checked: 14 numbers confirmed, 2 contradicted,
   3 it cannot check — each with its query.
6. A belief is challenged. The objectives sheet says returns are a sizing problem; three of four tests
   say otherwise. The question goes to the person who owns returns, once.
7. Another vendor's agent asks, over MCP, for an account's revenue and receives the number, its receipt
   and "Provisional" — and is told in words that an unapproved definition was withheld.
8. "Which of our numbers can we not stand behind?" — one screen: what share of the business the platform
   can see, and the one missing definition holding back fourteen sends.

**It finds what nobody asked for**

9. Dispatch lag in one region drifts for six days. Late delivery — the KPI — has not moved yet. The
   promise on the earlier stage breaks first, and the owner hears then.
10. Refund tickets on one connection and late dispatch on another turn out to be the same orders from
    one supplier — found along a link a person declared across the two.
11. *(today)* A drop was found by someone asking. The platform reviews itself: no alert existed; here is
    one, replayed over last year — it would have fired three times, twice rightly.
12. *(today)* "Last proven working: two days ago", on every alert.
13. "This week 41 things were held back from you. These three used your slots; here is why each won."

**It reasons about what has not happened**

14. A price change is opened for decision and the scenario is already on the page, in two parts: the
    arithmetic, exact; the volume response, "from three past changes in this category: −2% to −9%".
15. "Settling whether this is seasonal would change the choice. Waiting a week costs about this much.
    The test is one query." Then it runs the query.
16. A supplier-failure assumption is run against stock on hand and open promises: which customers are
    told first, and by when.

**It remembers what was decided — and whether it was right**

17. "The free-shipping decision in March stood on a claim that was restated last week. It is open for
    review." Nobody asked.
18. A new director asks why pending orders are excluded from revenue. The record answers: who decided,
    when, on what evidence, and what it replaced.
19. "In March we recommended this and expected +2% to +4%. Settled result against baseline: −0.3%. That
    playbook entry's record has fallen, and similar recommendations now say so."
20. The quarterly record: "pricing's demand forecasts have run 12% high for four quarters; supply's
    lead-time estimates run short." A counted fact about how the organisation thinks.
21. "What did we believe about churn on the day we chose the annual plan?" — answered as of that date,
    not as of today.

**It acts, and answers for it**

22. A promotion is paused under a standing grant; the verification read confirms it; a review is booked
    for fourteen days out; the pause can be undone for 72 hours.
23. After two misses, "reorder-point changes" drops from *execute within policy* to *approval required*.
    Automatically, with the two misses cited.
24. A mission's monthly report leads with the objective against baseline — and says "nine findings, one
    decision, no measurable effect yet" when that is the truth.
25. Three duties on one page: the inquirer's leading cause, the challenger's segment where it fails, the
    forecaster's interval — shown as one contested claim, not as three agents talking.

**It arrives ready**

26. A new connection, within a day: the business terms proposed for confirmation, alerts proposed with
    their backtests, and the list of usual questions this data cannot answer and what would unlock each.

---

## Not yet written — outline for the next session

*The session was paused here at the user's word. Sections A–T above are written. What follows is the
outline of the rest, with the decisions already reached, so the next session finishes it rather than
re-derives it. The brief's parts still owed: 15, 16, 28, 30, 31, 32 and the final challenge.*

### U · Product navigation

Today (measured in `web/app/page.tsx`): three primary destinations (Home · Inbox · Data Canvas), four
under Intelligence, three under Data, seven under Operations, and Settings — plus ten layers inside
Intelligence and seven inside Agent Ops. Home is a first-run funnel.

Proposed — six destinations, and Ask as a bar present everywhere (the ⌘K palette already is), not a place:

| New | Asks | Absorbs |
|---|---|---|
| **Now** | what needs me? | Home · the Briefing · Attention · the review questions · approvals waiting on me |
| **Inquiries** | why is this happening? | Agent runs · deep analyses · chat threads that became questions |
| **Decisions** | what are we choosing, and what did we choose? | the Inbox · approvals · scenarios (a scenario lives inside a decision) |
| **Missions** | what are we continuously trying to achieve? | monitors · promises · cockpits, as what a mission watches |
| **Record** | what do we hold true, and what have we learned? | Catalog · Semantic Layer · Ontology · Graph · Evidence · Memory · Brain map · Documents · object pages · Corrections |
| **Operations** | what is the system doing, and what may it do? | Agent Ops · Automations · Integrations · Notifications · Spend · Security & Audit · Evals · the SQL editor · Settings |

The user's standing interface rules apply unchanged (no title bars, every table with Copy and CSV, a
one-row result is a figure, business terms, nothing that looks machine-made).

### V · Reference UX — thirteen screens

Each still needs its seven attributes (primary user · job · hierarchy · interactions · agent behaviour ·
human behaviour · what is different). The one-line intent of each:

1. **Global navigation** — the six above.
2. **Home = Now** — bounded: a fixed number of slots a week; it ends; it shows what it held back.
3. **Intelligence surface = the Briefing** — a dated, signed reading of a range; kept as a delivery.
4. **Inquiry** — a record, not a transcript: question · hypotheses with their state · what is established · what is open and what would settle it · cost so far.
5. **Decision** — options side by side, each with its prediction and method; what it relies on; dissent; the review date.
6. **Scenario** — inside a decision: assumptions with their authors; each prediction split by method.
7. **Mission** — objective against baseline first; then what it watched, opened, decided, cost.
8. **Agent supervision** — work, not personas: runs by duty, typed failures, cost per warranted claim.
9. **Organisational memory** — the Record as of a date; Corrections as a first-class view.
10. **Evidence** — the receipt page: the seven lines of section O.
11. **Action centre** — the authority table: each action kind, its level, the receipt that gave it, its last verification.
12. **Admin** — the gate map, policies as sentences, groups.
13. **Developer** — packs with their measured record; doors; keys.

**The boundary (the brief's part 15).** People: goals, trade-offs, values, a novel decision, confirming
what a steward proposes. Agents: watching, inquiry, synthesis, evidence, scenarios, execution inside a
grant. The line is drawn by one question — *who is answerable?* — and everything answerable stays with a
named person.

### W · Roadmap — phases 0 to 7

Four ordering rules decided:

- **Record first what cannot be backfilled** (the rule Arc CB was reordered by). Decisions and
  expectations are booked as plain ledger entries in phase 1, before they have a screen.
- **Phase 0's exit is an organisation's install** — several people who own different things — and the
  kill list of section C executed. Without it no later exit criterion can be observed.
- **Phase 4 is gated on phase 3**: authority cannot be earned until outcomes are being recorded.
- **Every exit is a receipt taken live**, not a green suite.

| Phase | Core of it | Exit |
|---|---|---|
| **0 · Remove wrong assumptions** | freeze list C; restate roadmap §0; approval gate on by default; an organisation's install; take the baseline numbers | one organisation with at least five owners; the freeze written into the roadmap |
| **1 · Intelligence kernel** | one claim ledger, the envelope, two clocks; organisation scope; resolved owners; counted confidence for two claim classes; decisions and expectations booked | every figure that leaves is a ledger entry; the re-check proven on a real warehouse and in Slack (still owed today) |
| **2 · Agentic inquiry** | the durable inquiry; hypotheses as claims, refuted ones read back; challenge by a second binding; process stages and the settling lag as signals; the attention budget | a measured share of inquiries opened by the platform; a refuted hypothesis reused; the held-back list shown |
| **3 · Decision and simulation** | the decision record as a by-product; the review question delivered; outcome against baseline; scenario methods 1–3; predictions scored | a first set of decisions reconciled; interval coverage published |
| **4 · Action** | verification and undo on every declaration; the earned ladder joined to standing grants; automatic demotion | one action kind graduated on a receipt; one demoted in a drill |
| **5 · Missions and memory** | the mission; its report; Corrections; scenario method 4 from the install's own outcomes | one mission run for a full quarter, reported against baseline |
| **6 · Vertical intelligence** | packs as claims with priors; two verticals deep; onboarding hours as a release gate | connect to first relied-on claim in under a day, on a new customer, in each |
| **7 · Platform and ecosystem** | the ledger API and the agent contract published; pack kit and upload; the method interface; aggregate priors | an outside agent posting warranted claims; a third-party pack with a measured record |

Still to write per phase: capabilities, architecture, product, dependencies, risks, metrics.

### X · North Star

Candidates: (1) **closed loops per quarter** — decisions that carried a booked expectation and were
reconciled with a measured outcome; (2) **reliance** — the share of what leaves the platform that
someone acted on; (3) **calibration error**. Choice: **closed loops**, with calibration error as its
guard — a count alone can be inflated with trivial decisions; a count that must stay calibrated cannot.

### Y · The 2027 customer story

To write: an executive's statement, and the answer to "if it disappeared tomorrow, what is lost?" The
answer already reached: not the answers — any model re-derives those — but the record: what was believed
when, which decisions stood on what, how often each source was right, and the authority the
organisation's agents had earned.

### The closing attack

Five attackers, and what each forces:

| Attacker | Its attack | What survives it |
|---|---|---|
| The best AI-native startup | faster, lighter, no declarations needed | value on day one with nothing declared; six destinations; let its agent cite this ledger |
| The best data platform | definitions, an ontology and an assistant bundled at no extra price | import its definitions; own what spans sources and what is not data at all — decisions and outcomes |
| The best enterprise software company | it owns the action and the workflow | stay thin on action; be the independent scorer — the actor cannot be the scorer |
| The best model vendor | it owns the intelligence, the default surface and "memory" | a model-neutral ledger in the customer's custody; scoring by code; be the server its agents call |
| An internal team with unlimited engineers | it can build agents on its own data | priors learned across customers; the method as product; a ledger the customer can export, so adopting is not a trap; start the clock first |

The redesign these force is already folded into sections F, H, M and Q: thin agents and thin actions;
definitions imported rather than owned; the scorer never the actor; an exportable ledger; day-one value
without declarations.

**The final question** is answered in section A. The mapping to write out: warrant → the ledger and the
receipt · attention → the budget · authority → the earned ladder · agreement → terms and missions
written by people · consequence → outcomes · earned trust → calibration.
