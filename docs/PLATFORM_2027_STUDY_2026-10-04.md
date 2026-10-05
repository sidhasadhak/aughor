# Aughor in 2027 — what the platform should become

*A study, written 2026-10-04 at the user's request and **adopted the same day** — `ROADMAP.md` §6 item 39,
every call as recommended; §3.53 points here. Its phases 0 to 7 (section W) are the plan for 2027 and
beyond; nothing of them is built. Where it contradicts a standing decision (§4 of the roadmap, or a rule
the user has given) it says so on the line and names what would have to be true to reopen it, and the
roadmap's §4.8 amendment and §4.9 now record what adoption changed.*

***Status: complete.** Sections A–T were written on 2026-10-04 and the session paused at the user's
word; sections U–Z and the closing list were written in the next session the same day, from the outline
and the decisions it recorded, with each new count re-measured against the code first. Adopted 2026-10-04.*

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

*The band diagram above is drawn as a figure, with the flows between bands labelled, in
[`PLATFORM_2027_ARCHITECTURE_2026-10-04.md`](PLATFORM_2027_ARCHITECTURE_2026-10-04.md) — figure 1 the platform
as a place, figure 2 the loop of section I.*

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

## U · Product navigation

**Today, measured in `web/app/page.tsx` and the four workspace components (2026-10-04).** The rail
holds three primary destinations (Home · Inbox · Data Canvas), four under Intelligence (Briefing · Agent
runs · Health · Documents), three under Data (Catalog · SQL Editor · Semantic Layer), seven under
Operations (Agent Ops · Monitors · Notifications · Integrations · Spend · Security & Audit · Evals) and
Settings pinned in the footer with five pages. Under those sit the layers: ten inside Intelligence
(Briefing · Cockpit · Profile · Ontology · Graph · Evidence · Memory · Actions · Org · Brain map), seven
inside Agent Ops (Overview · Roster · Attention · Activity · Automations · Hub · Departures), five inside
Operations, three inside Evals, three inside Data. Eighteen rail items, twenty-eight layers and five
Settings pages: about fifty places a person can land, which is the "thirty-odd tabs" of the kill list
counted properly. The `NavTab` union carries thirty-six ids, seven of them legacy deep links kept so a
saved link still opens. Home is a first-run funnel with an ask box, four stat tiles and a run list.

**What the arrangement says.** Every group is named for a *store* or a *plane* — what Aughor knows,
what it queries, what it runs — and the layers inside are the modules behind them. Evidence, Memory, Org
and Brain map are four screens over the nine stores the Brain map was built to expose. A person who
arrives with a question ("what needs me?", "why did returns move?", "what did we decide in March?") has
to know which store answers it before they can find the screen. That is the legacy mental model of the
reassessment table, and it is the reason the UI/UX study measured the same screens twice carrying the
same controls.

**The rule for a destination.** A destination is a question a person brings, never a store the platform
keeps. Six questions cover what a person comes for; a seventh is a bar, not a place.

| Destination | The question | Absorbs today's places | Template (UI/UX study §4.4) |
|---|---|---|---|
| **Now** | what needs me, this week? | Home · the Inbox · Agent Ops ▸ Attention · the "Needs you" section on the Agent Ops overview · approvals waiting on me · the review questions · the Briefing's lead | Console, then a Ledger |
| **Inquiries** | why is this happening? | Agent runs · deep analyses · Health · chat threads that became questions · missed-move reviews | Ledger → Reader |
| **Decisions** | what are we choosing, and what did we choose? | the Inbox's recommendations · the Approvals lens · scenarios (a scenario lives inside a decision) · the recorded outcomes | Ledger → Reader |
| **Missions** | what are we continuously trying to achieve? | Monitors · promises · cockpits · the Briefing's standing view, each as something a mission watches | Ledger → Reader |
| **Record** | what do we hold true, and what have we learned? | Catalog · Semantic Layer · Ontology · Graph · Profile · Evidence · Memory · Org · Brain map · Documents · object pages · Corrections (new) | Detail, Workspace and Reader |
| **Operations** | what is the system doing, and what may it do? | Agent Ops ▸ Overview · Roster · Activity · Automations · Hub · Departures · Integrations · Notifications · Spend · Security & Audit · Evals · the SQL editor · Settings | Console, Ledger, Form |
| **Ask** | — a bar, present everywhere | the ⌘K palette ("Search, ask, or run a command"), the Home ask box, the chat | its own |

The Briefing is not lost: it is the Reader that Now opens onto and Missions report through, and it
keeps its range control, its recipes and its kept versions (Arc BR). The Data Canvas and the SQL editor
stay as working surfaces inside Record and Operations — the canvas is one view of a set of claims, and
the editor is where a person inspects and corrects a statement (section C, items 2 and 7).

**Six rules the navigation obeys.**

1. **Agents are not a destination.** Nobody comes to see an agent; they come to see work. Operations
   shows runs by duty, failures by type and spend by mission. The Roster survives as a page an agent's
   name opens, as the UI/UX study already decided for the overview (§9.4, item 4).
2. **A store earns a screen only inside Record**, and only as a view of the ledger with its count and
   its doors — the Brain map's rule applied to the whole product.
3. **Nothing is read twice.** A thing has one page, and every other destination links to it: a claim's
   page is in Record, and Now, an inquiry and a decision each cite it there. The UI/UX study's inspector
   drawer is how a citation opens without leaving the page you were on.
4. **A badge counts only what waits on a person.** The amber rule the sidebar already applies
   (`badgeFor`: amber when a human is waited on, neutral when it is only a count) becomes the only rule;
   Now's badge is the week's slots used against its budget.
5. **Every saved link keeps working.** The `NavTab` legacy ids (`intel-hub`, `control-room`,
   `builder`, …) already map onto today's layers; every id here maps the same way, and a bookmark
   from 2026 opens the page that absorbed it, saying so once.
6. **The connection is global context** and the organisation is the scope (UI/UX study §4.2; section
   E, item 2). A screen that is not per-connection says "all connections"; one that is shows which.

**Where this contradicts the UI/UX study (2026-09-25).** That study's §4.2 proposed a rail of five
groups — Data · Model · Operate · Govern, with Home, Needs you, Ask, Briefing and Runs above them — and
its §4.7 item 7 asked for a **Model** destination (Ontology · Graph · Actions) as "the authored layer
beside Data", recorded as the user's call. Those groups are arranged by what the platform *holds*; this
one is arranged by what a person *came to do*, and it folds Model into Record. What that study decided
about the shell survives unchanged: the region stack, the six page templates, the inspector and the
slide-over, the global connection context, the screenshot gate. Its "Needs you" tray survives as Now's
tray. Measured today: "Needs you" exists only as a section head on the Agent Ops overview
(`web/components/FleetOverviewPanel.tsx`), not as a tray or a destination. If the user wants the
authored layer visible on the rail, Record splits into Record and Model and nothing else here changes.

**What a day looks like through the six.** A mission's owner opens Now: three things used their
slots this week, each with the mission it bears on and the one action under it; a review question
from a March decision; one approval. They open the inquiry behind the first, read what is established
and what is open, and open the decision it proposes. An analyst lives in Inquiries and Record: they
correct a statement in the editor, and the correction is a verdict that reaches the ledger. An outside
agent has no navigation at all — it has the MCP server's tools, the ledger API and the receipt link
(section Q); the six destinations are a person's reading of the same ledger it writes to.

The user's standing interface rules apply unchanged: no title bars, every table with Copy and CSV, a
one-row result is a figure, business terms everywhere, nothing that looks machine-made.

---

## V · Reference UX — thirteen screens

Each screen below is given the same seven attributes — primary user · job · hierarchy (what is read
first) · interactions · agent behaviour · human behaviour · what is different from 2026 — and a *today*
line that says what exists on the current build, measured in `web/` on 2026-10-04. Every screen is one
of the UI/UX study's six templates; none needs a seventh. Nothing paints before it knows what it is
showing; a withheld thing says so in its place; a figure is a figure, not a tile with a sparkline.

**1 · Global navigation**

*Today:* the rail and layers measured in section U; the ⌘K palette; the topbar with the workspace
switcher and the live activity strip.

| | |
|---|---|
| Primary user | everyone, including the person who opens one link a month |
| Job | get from a question to the one page that answers it, and back, without learning the stores |
| Hierarchy | the rail's six destinations; Ask in the topbar; the badge on Now; the connection as global context; everything else is inside a page |
| Interactions | ⌘K asks, searches and runs commands; a name anywhere opens its page in the inspector; Esc returns; `?inspect=` and `?tab=` reproduce any view |
| Agent behaviour | none. Agents do not navigate; they write to the ledger and arrive on Now through the departure gate |
| Human behaviour | a reader lands on Now and leaves from it; a builder lives in Record and Operations; nobody configures the rail |
| What is different | six destinations named for questions; agents, stores and planes gone from the rail; one badge rule; every 2026 link still opens |

**2 · Now (Home)**

*Today:* Home is a first-run funnel with an ask box, four stat tiles (tables, entities, findings,
queries), the Health scorecard and a run list. What needs a person is spread over the Inbox
(recommendations), Agent Ops ▸ Attention, a "Needs you" section on the Agent Ops overview, the Approvals
lens of Security & Audit, and the Briefing's lead. Briefing triage already holds items back and records
why (`aughor/knowledge/triage.py`); nothing shows the held list.

| | |
|---|---|
| Primary user | an owner — of a mission, a metric, a decision — who gives the platform a few minutes a day |
| Job | spend this week's attention on the few things that bear on what they own, and know what was kept from them |
| Hierarchy | 1 · the week's slots: *n* of *k* used, each item with the mission it bears on, its one action and its receipt line; 2 · questions addressed to me (a review date reached, an owner question, an approval); 3 · "since you were here": restatements and corrections to things I was told; 4 · the held list — what competed and lost, with why; 5 · the Briefing, one line, opening the Reader |
| Interactions | act on an item where it is (accept, approve, answer, open the inquiry); dismiss with a reason, which is a verdict; "show me what you held"; set my slots; nothing to arrange |
| Agent behaviour | triage (code) ranks by bearing on a mission, size against normal, cost of waiting and novelty against lessons, charges the budget and records every hold; a Deliver agent writes the line, never the ranking; nothing arrives here twice |
| Human behaviour | reads top to bottom and reaches the end; opens two or three things; answers what is addressed to them — each answer is remembered and asked once |
| What is different | it is bounded and it ends; every item names why it won a slot; the held list is a first-class view; a dismissal is data; there is no funnel, no stat tiles and no dashboard — a first run gets one sentence and the three steps |

**3 · The Briefing (the intelligence surface)**

*Today, the strongest screen on the build:* one Briefing for any range (Day · Week · Month · Year ·
to date · custom), a recipe per horizon (Measured · What moved · Why · Alerts · Revisions · Actions ·
Data health), every figure Final · Provisional · To date, each version kept as of the day it was built
and a revision named in the next Day Briefing, the Cockpit tab beside it, every send through the
departure gate (Arc BR, Arc CT). Its ranking is the size of a move and a model-inferred north star;
no item carries an action; it is delivered to a channel, not signed.

| | |
|---|---|
| Primary user | a leader reading on the horizon's cadence; a Slack channel that gets the Day |
| Job | know what moved in the range, why, what is being done, and what the platform could not say |
| Hierarchy | 1 · the mission line: each active mission's objective against baseline for the range; 2 · what moved, ranked by bearing on a mission then by size against normal, each item in the seven lines of section O, with its one action and its receipt; 3 · revisions since the last Briefing of this range; 4 · open inquiries that wait on settling days, each with the date it will speak; 5 · data health and coverage: what share of the business this range could see |
| Interactions | the range control (as today); open any item's inquiry or claim in the inspector; take the action under an item through the gate; mark a line wrong, which is a verdict; compare with the same range a year ago at the same age |
| Agent behaviour | the Deliver duty writes the prose from fields; the Inquire duty's open items are listed, never summarised past their state; a model never ranks and never writes a number |
| Human behaviour | reads the mission line first and usually stops at item 2; acts on one item a week; the verdicts feed the ledger |
| What is different | ranked by missions people wrote; every item is a claim with a counted confidence and an action; signed and dated as a delivery, so a Briefing met in a slide a year later opens to the version that was sent; it says what it could not see |

**4 · Inquiry**

*Today:* a deep analysis is a run that produces a report (`investigations`, `report_json`); the Agent
runs screen lists runs as cards with a headline; chat threads are conversations; hypotheses and their
verdicts are saved (`hypotheses_json`) and nothing reads them back; the skeptic step records
`causal_checks` since 2026-10-04; a run ends when its report is written.

| | |
|---|---|
| Primary user | the owner the inquiry is about; the analyst who opened or was handed it; the next agent that works it |
| Job | know what is established, what is open and what would settle it — without reading a transcript |
| Hierarchy | 1 · the question, in declared business terms, with who or what opened it and its state (open · waiting for … · closed as …); 2 · what is established: claims with tier, status, counted confidence and receipt; 3 · hypotheses: each with its state (open · supported · refuted · abandoned) and the evidence that decided it, refuted ones kept; 4 · what is open and what data or date would settle each; 5 · the decision it proposes or fed; 6 · runs and cost so far, folded; 7 · lessons, written at close |
| Interactions | add a hypothesis (a person's, named); mark a claim wrong with the corrected statement; hand it to an owner; set or clear the next check; close with a reason; open any run's trace in the inspector |
| Agent behaviour | Inquire proposes hypotheses and runs the cheapest test first; Challenge attacks the survivor from a second binding; Observe adds readings; the inquiry wakes on a restated claim or a settle date without being asked; it refuses to re-test a refuted hypothesis and says so; every run books a typed verdict, never an empty result |
| Human behaviour | reads items 1–4 in a minute; adds the hypothesis only a person would know; answers the one question addressed to them; rarely opens a run |
| What is different | a record that outlives its runs; the refuted list is memory, read by the next inquiry on the same object; "what would settle it" is a field, not a sentence in prose; cost is on the page; three duties disagreeing is one contested claim, not three agents talking |

**5 · Decision**

*Today:* the Inbox holds recommendations with accept · reject and an Execute through the gated path;
approvals sit in a resolve-once queue with proposer and reasoning; on acceptance a baseline is measured
and a review set thirty days out (`aughor/playbook/outcomes.py`, a flat JSON file); the review question
is shown in the Inbox and logged, never sent; a proper decision record exists only for the machine's
own choices (`aughor/learning/decisions.py`); five decisions have a human label.

| | |
|---|---|
| Primary user | the person answerable for the choice; their approvers; later, the auditor and the new director who asks why |
| Job | choose between options with their expectations on the table, book the expectation, and come back on the review date to learn what happened |
| Hierarchy | 1 · the question and who is answerable; 2 · the options side by side — each with its predictions (interval, method and the method's licence), cost, reversibility and who would act; 3 · what the decision relies on: the claims as recorded at this moment, each with its counted confidence; 4 · dissent, kept; 5 · the chosen option, the booked expectation in one line and the review date; 6 · after the date: the outcome against expectation *and* against baseline, with the verdict |
| Interactions | choose; edit the expectation line before booking; add an option; record dissent; set the review date (proposed from the metric's settling lag); "we decided this elsewhere" in one sentence; reopen when a relied-on claim is restated |
| Agent behaviour | Inquire prepares the options and their evidence; Forecast fills each option's prediction with its method; after the date, code measures the outcome on settled days against baseline and writes back to every relied-on claim's class, the playbook entry and the author's record; no agent chooses |
| Human behaviour | reads the options row, chooses, accepts or edits the proposed expectation, leaves — twenty seconds; on the review date reads one line |
| What is different | the decision is the organisation's, not the machine's; recorded as a by-product of accepting, approving or replying; the expectation is booked at the moment of deciding; dissent is kept; "what did we believe when we chose this?" is a filter on the page |

**6 · Scenario**

*Today:* nothing. There is no forecaster, and the departure gate's law 5 says a forecast never departs
(`aughor/govern/departure.py`). Metric statements and formulas give method 1 its arithmetic; declared
processes and promises with measured stage durations give method 5 its structure; the causal edges that
would feed method 4 exist (`aughor/lifecycle/causal.py`) and have never been fed, because no
recommendation has been marked verified.

| | |
|---|---|
| Primary user | the decision's owner; the analyst who states an assumption |
| Job | see what each option is expected to do, in parts, each part with the method that produced it and how far that method can be trusted here |
| Hierarchy | inside a decision, under an option: 1 · the assumptions — variable · value · source (declared by a named person · measured · estimated) · author; 2 · each prediction split by method: the identity part exact, the historical part with its interval and backtest error, the intervention part with its count of past cases, the declared part with its author's name; 3 · the limits, in words: outside the observed range · no past change of this kind · assumes X holds; 4 · what the prediction will be scored against, and when |
| Interactions | change an assumption (it becomes a declared claim with your name); add a past case the ledger missed; compare two options' predictions; nothing to run — it recomputes |
| Agent behaviour | Forecast fills methods 1, 3 and 5 from their inputs and method 4 from the decision ledger's own outcomes; it refuses method 6 above the stated stake unless backtested on this install; it never supplies an elasticity or a rate a person did not declare and the data did not measure |
| Human behaviour | reads the parts, supplies the one assumption only they hold, puts their name on it |
| What is different | a scenario has no page of its own — it lives inside a decision, a mission or an inquiry; every part carries a method and a licence; every prediction made under it, including the untaken option's where a baseline allows, is scored when its days settle |

**7 · Mission**

*Today:* nothing. The nearest things are the north-star metrics a model infers per connection
(`aughor/business_profile/`), organisation settings written by people, monitors, declared promises and
a person's cockpits — each a thing a mission would watch, none a mission.

| | |
|---|---|
| Primary user | the mission's owner, a named person; the leadership that reads its report |
| Job | state what to achieve and what not to damage, give it a budget and an authority ceiling, and read every month whether it moved against baseline and what that cost |
| Hierarchy | 1 · the objective against baseline, with its interval — before anything else; 2 · the constraints and whether each held; 3 · what it watched: monitors, promises and claims, each with its state; 4 · what it opened: inquiries by state; 5 · what it decided and what became of each decision; 6 · what it cost: interruptions used of its budget, spend, actions by authority level; 7 · lessons and changed priors |
| Interactions | write or edit the mission (objective, constraints, scope, budget, ceiling, review cadence); pause or retire it; open anything it lists; read a past report as of its date |
| Agent behaviour | none writes a mission; the loop reads it — triage ranks signals by bearing on it, inquiries open under it, decisions carry its ceiling, Operate acts inside its grants, and the report is composed from fields by Deliver. A mission with no owner does not run |
| Human behaviour | writes it once in five lines; reads the report monthly; is charged for every interruption it causes them |
| What is different | the first object in the product that says *why*; judged by the objective against baseline and never by activity — "nine findings, one decision, no measurable effect yet" is a valid report; the authority ceiling is where section M's ladder is bounded |
**8 · Agent supervision (Operations)**

*Today:* Agent Ops has seven layers — Overview (what is wrong · running · cost), Roster (an agent's own
page: Overview · Runs · Map · Quality · Setup), Attention, Activity (the live tail, traces, deep-run
phases), Automations, Hub and Departures; Arc AO added the testing centre and one closed learning loop
per agent. Cost is counted and said when unpriced. The unit everywhere is the agent as a persona.

| | |
|---|---|
| Primary user | whoever runs the install; an owner checking why an answer was late or wrong |
| Job | see the work — what ran, what failed and how, what it cost and what it produced — and change what an agent may do |
| Hierarchy | 1 · the week by duty: runs · warranted claims · typed failures · cost per warranted claim, one row per duty (Observe · Inquire · Challenge · Forecast · Steward · Operate · Deliver); 2 · failures by type (no data · no definition · withheld · out of budget · tool failed · contradicted), each opening its runs; 3 · departures: sent · held · asked, with the law that held each; 4 · principals: every agent and service principal with its track record by claim kind, its grants and its budget; 5 · the live tail and traces, folded |
| Interactions | open a run's trace; rehearse a principal against a golden suite; pause a principal; change a scope or a stance; widen or withdraw a grant (which is section M's table, screen 11); nothing to arrange on a canvas |
| Agent behaviour | every run books a typed verdict; a principal on probation reaches only its declarer; a demotion lands here as a ledger entry with its cause; the platform's own agents and an outside vendor's appear in the same rows |
| Human behaviour | looks when something is wrong or expensive; reads the failure column, not the transcript; grants and withdraws |
| What is different | the row is a duty, not a persona; the score is a count of what became of entries, not a model's opinion; an outside agent is supervised in the same table as a built-in one; "cost per warranted claim" replaces tokens per run |

**9 · Organisational memory (Record)**

*Today:* spread over Intelligence ▸ Evidence, Memory ("what the closed loop has learned"), Org, Brain
map (nine stores with live counts, and the facts that changed with what they replaced — CB-1), Profile,
Ontology and Graph; Data ▸ Catalog and Semantic Layer; Documents; the object pages. Two provenance
carriers; one clock. Restatements are kept; refuted hypotheses are saved and unread; missed moves are
reviewed since 2026-10-04; nothing records a prediction that missed or a decision that went badly.

| | |
|---|---|
| Primary user | the analyst and the steward; the new director; the auditor; every agent, which reads it before it writes |
| Job | find what the organisation holds true about a thing, as of any date, with its warrant — and see what it has been wrong about |
| Hierarchy | 1 · the "as of" control: today, or any past date — the whole screen re-reads as recorded then; 2 · by object, type, metric or term: the current claims with tier, status, counted confidence and owner, and what each superseded; 3 · the definitions with their versions and approvals; 4 · the map: types, links, processes, promises and rules, each measured; 5 · **Corrections**, a first-class view: restatements · refuted hypotheses · missed moves · predictions outside their interval · decisions worse than expected, each with what was believed and what replaced it; 6 · coverage: what share of the business is mapped, and the one missing definition holding back the most sends |
| Interactions | search; set the date; open a claim's page (screen 10); declare, confirm or withdraw a term; mark a claim wrong; follow a link across connections; ask "who else was told this?" |
| Agent behaviour | Steward proposes definitions, duplicates and coverage gaps, and nothing it proposes is shown as held until a person confirms it; every agent's entries carry its author; no agent edits the organisation's map |
| Human behaviour | the steward confirms a proposal a day; the analyst looks a metric's definition up; the director asks one question a quarter and gets an answer with names and dates |
| What is different | one ledger behind every view, two clocks on every entry, so "as of" is a filter; Corrections is a destination's first page, not history; the Brain map's nine boxes become one box with views; a term, a claim and a decision are three kinds of one thing |

**10 · Evidence — the receipt page**

*Today:* `/receipt/<id>` is a page of its own (idea 11, 2026-10-04): the statement, the tables and
columns read (DE-4's lineage), the engine and the as-of, the doors the statement passed (GM-3), the
guards that fired and the guards that could not run (GM-4), the model binding on the receipt (TJ-1),
signed. Every figure in an exported PDF or deck links to it. It does not say how often claims of its
kind have been right, who else was told, whether it has changed since, or offer to re-perform.

| | |
|---|---|
| Primary user | anyone who met a number and wants to know whether to rely on it — a person in a meeting, a regulator, another vendor's agent |
| Job | answer "why did the system tell me this?" in one page, the same page for a person and an agent |
| Hierarchy | the seven lines of section O, in order, each from a field: what we know · what we think (with the counted confidence of its class and *n*) · what we do not know · why we think it (the warrant chain: statement → tables and columns → engine → as-of → definition version → doors and guards → model binding → author) · what disagrees · what would change our mind, and when it next runs · what it costs to wait. Then: who else was told, and whether it has changed since (the re-check's record) |
| Interactions | **Re-perform** — run the statement now and show both figures with the difference explained (late rows · a restatement · a definition change); open the inquiry it came from; copy the line that travels; open any table or column in Record; nothing else |
| Agent behaviour | none on the page. An outside agent reads the same fields over MCP and receives "Provisional" and "withheld" in words |
| Human behaviour | reads line one, maybe line four; presses Re-perform once and believes the page thereafter |
| What is different | confidence is a hit rate with its *n*, or absent; the re-check that already runs daily is offered as a button; "who else was told" closes the loop idea 5 opened; the page is the agent contract's read side made visible |

**11 · Action centre**

*Today:* Intelligence ▸ Actions lists declared actions and overlay edits; the Approvals lens of Security
& Audit holds the resolve-once queue; standing grants exist (`aughor/actions/grants.py`) and an earned
ladder exists (`aughor/memory/trust.py`) and neither has a screen nor has met the other; one action is
declared on the install; the approval gate is off unless `AUGHOR_ACTION_APPROVAL` is set.

| | |
|---|---|
| Primary user | the person who sets ceilings and signs grants; the owner of a target system; the auditor |
| Job | see every kind of action, what level it may run at, on what record, and take authority away in one gesture |
| Hierarchy | 1 · **the authority table**: one row per action kind × scope — its level L0–L5, the ceiling a person set, what the record has earned, the receipt that granted the current level, its last verification and whether it passed, its undo window; 2 · executions waiting on approval, each with its preview, its expected outcome and its verification statement; 3 · recent executions with their verification reading and outcome state; 4 · demotions, each with the miss that caused it |
| Interactions | approve or refuse with a reason; set a ceiling; sign or withdraw a standing grant (bound to a target, a scope, limits and an expiry); run the undo inside its window; open the declaration; run a drill |
| Agent behaviour | Operate previews, executes inside its grant, runs the verification statement and books the reading; a failed verification or an unexplained miss demotes the action kind automatically and the demotion is an entry here; an irreversible action never appears above L3 |
| Human behaviour | approves at L3 a few times a week; signs a grant when the receipt is on the table; reads the demotions column |
| What is different | authority is a table, not a setting; every level cites the receipt that gave it; the approval gate is on by default; standing grants and the earned ladder are one mechanism; undo is a column |

**12 · Admin**

*Today:* Settings has five pages — Organization (with the owners link and, since DE-2c, the agent
policy in one sentence), Access (roles), Appearance, Models, System; Security & Audit has three lenses
(security · activity · approvals); the gate map is a census file (`docs/SQL_DOORS.json`, 191 door
calls) held by a ratchet test, and Spotlight can name the doors an answer passed; groups are recorded
and not enforced; row policies are an empty dict in source; identity is off unless
`AUGHOR_REQUIRE_IDENTITY=1` is set at start.

| | |
|---|---|
| Primary user | the install's administrator; the security reviewer |
| Job | see every door in and out and what guards it, read every policy as a sentence, and change who may see or do what by group |
| Hierarchy | 1 · the gate map as a picture: every input and output door, the laws on it, the last time each fired, and the two `none` sites (3 → 2 on 2026-10-04) with their reasons; 2 · policies as sentences, each with its owner and version, and what it has held or withheld this month; 3 · groups — persona and function — with their grants by tag and clearance, and who is in them; 4 · identity, model bindings and keys; 5 · the audit export door and where it points |
| Interactions | write a policy from structural clauses (a form that reads back as a sentence); add a person to a group; set a clearance; turn identity on (a restart, by design); export the audit trail; nothing freeform |
| Agent behaviour | none. Governance is deterministic and a model never decides who receives what (roadmap §8). The agent policy — read · run · act — is one of the sentences |
| Human behaviour | sets groups once; reads the "what it held" counts monthly; gives the auditor the export |
| What is different | the gate map is a screen, not a JSON file; a policy is a sentence a person can read back, never an expression string; groups are enforced; row policies are data; defaults come from groups and nothing is configurable that can be measured |

**13 · Developer**

*Today:* an MCP server with 18 tools plus live ones, policy-trimmed; `aughor packs list · check ·
measure · promote · demote`; the Integrations layer; 66 routers and about 695 routes behind a typed
client only the web app uses; a key-minting route under RBAC since Arc AO; no pack upload, no plugin
loading, no authoring guide, no published contract.

| | |
|---|---|
| Primary user | a pack author; an integrator declaring an action; a vendor connecting its agent; the customer's own engineers |
| Job | extend the platform without opening a second write path — and see how what they built is measured |
| Hierarchy | 1 · packs: installed and available, each with its measured record (how often its claims held on the installs that bound it) and its tier; 2 · doors: the ledger API, the MCP server's tools as the policy shows them, the event catalogue, with examples; 3 · principals and keys: service principals, their policy, their track record; 4 · the kits: validate a pack, bind it against a sample warehouse, run the compile test, declare an action with its verification and undo, register a method with its backtest; 5 · the agent contract as a document: the seven duties, the typed verdicts, what an entry must carry |
| Interactions | upload a pack; run its checks; mint a key for a principal under a policy; declare an action; register a method; read the contract; nothing that runs inside the process |
| Agent behaviour | an outside agent is a principal here: it reads by clearance, books by duty with a warrant, acts by grant, and is scored like any other |
| Human behaviour | an author reads the record of their pack and fixes the claim that keeps failing; an integrator declares and tests; a vendor reads the contract once |
| What is different | the app is a pack of declarations, measured and demotable by the same receipt that promoted it; the contract is published; the quality bar is the product's own record, not a listing's stars |

**The boundary (the brief's part 15).** One question draws the line — *who is answerable?* — and
everything answerable stays with a named person. The table is the whole rule; the screens above apply it.

| Only people | Only agents and code | Either, under the rule |
|---|---|---|
| goals and trade-offs (a mission, its constraints and its budget) | watching — every settle tick, every monitor, every re-check | a hypothesis: an agent proposes, a person may add one, both are named |
| what a word means (a definition's approval, the organisation's map) | inquiry — hypotheses, tests, challenge, cheapest first | an option on a decision: agents prepare, a person may add, the person chooses |
| a novel decision, and the expectation booked with it | synthesis — the seven lines written from fields | an assumption: declared by a person, or measured, never estimated by a model |
| confirming what a steward proposes | evidence — running the statement, the receipt, the lineage | execution: an agent inside its grant and its verification; a person at L3; never an agent on an irreversible action |
| dissent | scenarios' arithmetic, history and simulation parts | an answer to an owner question: a person answers; code remembers it and asks once |
| granting and withdrawing authority | scoring — at settle, by code, never by a model | delivery: an agent writes the line; the departure gate — code — decides whether it leaves |
| what a mission may spend and interrupt | ranking and gating — triage, the attention budget, the laws | — |

What the boundary refuses, by name: a model that grades an answer into a pass (§4.8), a model that
decides who receives what (§8), a model that writes a fact (no `llm_inferred`), an agent that chooses a
goal, and a person asked to do by hand what a settled reading can decide.

---

## W · Roadmap — phases 0 to 7

**Four ordering rules.**

- **Record first what cannot be backfilled** — the rule Arc CB was reordered by. Decisions and
  expectations are booked as plain ledger entries in phase 1, before they have a screen, because
  every month without them is a month of calibration that can never be recovered.
- **Phase 0's exit is an organisation's install** — several people who own different things — and the
  kill list of section C executed. Without it no later exit criterion can be observed: the value ledger
  in roadmap §3.18 already says an organisation-wide system's value is unobservable at one analyst.
- **Phase 4 is gated on phase 3.** Authority cannot be earned until outcomes are being recorded; §4.8's
  refusal stands until then (section M).
- **Every exit is a receipt taken live**, on the organisation's install, never a green suite — the
  repo's own graduation rule.

**The shape of the dependency.** Phases 1–2 are engineering; phases 3–5 wait on the calendar. A
decision's review date is weeks out, a prediction is scored when its range is Final, a mission is judged
over a quarter. So the critical path is not how fast the ledger is built but how early the first
expectation is booked — which is why phase 1 books decisions before it draws them, and why the closing
attack's answer to an internal team is *start the clock first*.

```
 0 remove ─▶ 1 ledger ─▶ 2 inquiry ─▶ 3 decision & scenario ─▶ 4 action ─▶ 5 missions & memory
                 │                          │                                   │
                 └──────── 6 verticals ◀────┘          (method 4 needs 3's outcomes; a mission needs 4's ceiling)
                                │
                                └──▶ 7 platform & ecosystem   (the contract needs 1; aggregate priors need 6)
```

**Each phase: what it builds, where, what a person sees, what it needs, what could go wrong, how it is
measured, and what lets it close.** The metrics name the baseline measured in this study where one
exists, so the phase's movement can be read against it.

**Phase 0 · Remove the wrong assumptions**

| | |
|---|---|
| Capabilities | the freeze of section C written into `ROADMAP.md` as a decided list, each kill with what survives; roadmap §0 restated — the moat is the warrant and the record, the ontology is the map; the approval gate on by default (`AUGHOR_ACTION_APPROVAL`, read straight from the environment in `aughor/govern/actions.py`, becomes a kill switch, and the old name is kept as an alias rather than stranded — the rule `AGENTS.md` sets for renames); roadmap §1's stale lines corrected (five triggers → seven, twelve effects → thirteen, "neither is a trigger" → both are); the baseline numbers of section A re-measured and dated |
| Architecture | nothing new. Identity on (`AUGHOR_REQUIRE_IDENTITY=1`), the kernel ledger on Postgres (it already runs there — `aughor/kernel/ledger.py` keeps portable SQL for it), one scheduler leader, API workers stateless; a snapshot of `data/` before and `git ls-files data/` after, as `AGENTS.md` requires |
| Product | an install where five or more named people own different metrics, processes and promises, with owners linked to principals (CB-3's panel); Slack live; the Day Briefing delivered seven mornings (BR-5's owed receipt) |
| Dependencies | the user's decision on the install — this is the call section F named; a Postgres; the IdP receipt still open since VA-10 |
| Risks | the install is treated as a login wall around a demo (Arc MT's refusal was right about that and stays); the freeze is read as deletion — it is not, working code stays; the kill list is argued item by item instead of adopted or refused as a list |
| Metrics | owners resolved (today: the owners panel exists; the count on the install is not published) · people who asked a question this month (today: one) · asks a month (111 logged on 2026-10-04, lifetime) · declared actions (1) · the freeze written (no) |
| Exit | one organisation, at least five owners, identity on, the freeze in the roadmap — and the first number that left the platform and was acted on by someone who is not the analyst, with its receipt. That last receipt is the flywheel's first turn (section S) and nothing later can be observed without it |
| Status | *2026-10-05: the code half is built (ROADMAP §3.53 lists it and the receipt). The install half waits on an identity provider and on people — the user chose their own machine, no provider yet, one owner for now — so the organisation-scale exit is not observable and the roadmap says so.* |

**Phase 1 · The intelligence kernel**

| | |
|---|---|
| Capabilities | **one claim ledger** in the kernel: the hub's envelope with two clocks, the kinds of section G; the five claim shapes of section E become writers into it (the Explorer's finding, the deep analysis's finding, `EvidenceClaim`, a pack's `CoreClaim`, the hub's `ClaimCheck`) or are retired; verdicts move in beside them; **organisation scope** on glossary, metrics, findings and the Briefing (the object door already reads across connections); **counted confidence** for two classes — observations re-checked (hit rate of answers that held on re-check) and findings challenged (share that survived) — shown with *n* or not shown; the Evidence panel's hardcoded 0.8 and 0.5 removed; **decisions and expectations booked** as ledger entries from the three doors that already exist (accepting a recommendation, approving an action, a Slack reply), with a review date proposed from the settling lag |
| Architecture | the ledger as the only state that matters; the context graph rebuilt as a projection; `recorded_at` on every entry; a dependency index (claim → claims and cards that read it) so a restatement marks dependents dirty — the artifact cascade's fresh · dirty · stale extended to beliefs; the second provenance carrier retired (`IDEAS.md` 16) |
| Product | the receipt page gains line two's counted confidence and "who else was told"; Record's first view: claims by object with as-of; a decision is visible as a row, not yet a page; the Briefing's items are claims |
| Dependencies | phase 0's install; the daily re-check proven on a real warehouse and in a Slack thread (owed since 2026-09-24) |
| Risks | a sixth claim store instead of one (the rule has been broken three times; the ratchet is a count of stores that may fall and never rise); confidence shown before *n* is meaningful (say *n*; below a threshold say "too few to count"); the migration drops a superseded finding's text (supersede with history intact, tested on the live ledger) |
| Metrics | claim shapes (5 → 1) · share of figures leaving the platform that are ledger entries (0 → 100%) · decisions booked a week (0 today) · share of booked decisions with an expectation line · answers re-checked and the restatement rate · reference classes with *n* ≥ 30 |
| Exit | every figure that departs is a ledger entry with a receipt; one restatement delivered to the thread it was first said in, on the organisation's warehouse; the first ten decisions booked with expectations; the Evidence panel shows no number that was not counted |
| Status | *2026-10-05: the code half is built, in five slices on `claude/platform-2027-study` (ROADMAP §3.53 lists each and its receipt): the one claim ledger as kernel artifacts with the three laws at the door and belief as a view; the first three writers (every receipted answer, the deep analysis's findings, the re-check's restatement) and `EvidenceClaim`'s 0.8 / 0.5 gone; decisions booked as a by-product of the three doors with the expectation line and the review date from the settling lag, and the Record's own doors; confidence counted for two classes and shown with n or not at all; the receipt's line two. Of the exit, two parts are code and are met in the test receipts — the Evidence panel shows no uncounted number, and every receipted answer that concluded something is a ledger entry; two parts need the install — a restatement delivered on the organisation's warehouse, and ten decisions booked by people — and are not observable yet. All five writers are in (the pack's with phase 6; the Explorer's finding and the hub's `ClaimCheck` with the arc's close-out, 2026-10-05, ROADMAP §3.53: a finding is a measured claim warranted by the explorer's own artifact, left alone when a run reads it back unchanged and withdrawn when the re-validation or a person drops it; a reply in a filed thread is a said claim per reply, never per object, with the check's verdict as its state). Organisation scope landed with the close-out (C2, 2026-10-05): a metric scoped `org:<id>` and the glossary's `organisations` section sit between a connection's own words and the install's, read by every connection of the organisation and by no other; the unscoped reads a person makes show one organisation its own when identity is on; a Briefing's history is read by its organisation and `GET /briefing/organisation` folds every visible connection's latest kept Briefing. The graph became a projection of the ledger with the close-out (C3, 2026-10-05): its finding nodes are the Record's measured findings and observations, each naming the claim it reads with the claim's tier as its warrant; the explorer store and the answer receipts fill in only what predates the Record; the file is generated state rebuilt on demand by every reader that answers a question, and `data/context_graph/` is no longer tracked. Nothing of phase 1's code half is still open; its two exit parts wait on the install.* |

**Phase 2 · Agentic inquiry**

| | |
|---|---|
| Capabilities | **the durable inquiry**: a deep analysis becomes a run inside it; state (open · waiting · closed), next check, what would settle each open item; hypotheses as claims with their state, **refuted ones read back** before the next inquiry on the same object generates its own; **challenge by a second binding** where the install has two, recorded on the `causal_checks` record; **new signals**: a declared process's early stages and the settling lag itself; **triage under an attention budget** (`IDEAS.md` 9): slots a week per person, every hold recorded and listed; the platform opens inquiries from signals, not only from asks; typed failure verdicts on every run |
| Architecture | the settle tick as the loop's heartbeat (it already runs); the inquiry as a kernel artifact with its runs as children; triage as code with four named terms (bearing on a mission — empty until phase 5 — size against normal, cost of waiting, novelty against lessons); agents called by the loop under a budget, cheapest test first, stop when no open hypothesis could change the decision |
| Product | Now, bounded: slots, the held list, "since you were here"; the Inquiry page (screen 4); Health folded into Inquiries; quick-or-deep removed as a choice (kill 4) |
| Dependencies | phase 1's ledger; two model bindings on the install for challenge (one is enough to start, said on the record) |
| Risks | the loop becomes a finding factory — the budget and "a mission with no owner does not run" are the guards; the refuted list is saved and still not read (the measurement is the count of hypotheses *not* re-tested); triage's four terms are weighted by hand — publish the weights and the held list, and let misses (idea 8's review) move them |
| Metrics | share of inquiries opened by the platform rather than a person (0 today — every run starts at an ask) · hypotheses refused as already refuted · stated causes that survived a challenge (169 of 309 deep reports stated a cause on 2026-10-04; 0 challenged before that day) · slots used of slots offered, and the held count · alerts acted on against alerts sent · typed-failure share (no empty results) |
| Exit | a measured share of inquiries the platform opened; one hypothesis refused because it was refuted before, on a real object; the held list shown to a real person; the Now page read to its end by its owners in a measured week |
| Status | *2026-10-05: the code half is built, in three slices on `claude/platform-2027-study` (ROADMAP §3.53): the inquiry as a kernel artifact that outlives its runs, with hypotheses as claims and refuted ones read back and refused; every run booking a typed verdict; the skeptic challenging from a second binding where the install has two; a fired alert opening an inquiry; the attention budget charged at the departure gate with the held list and the four terms published. Of the exit, the refusal and the held list are met in the test receipts and wait on a real object and a real person; the share of inquiries the platform opened is measurable from the record (`opened_by`) and is 0 until alerts fire on the install; the Now page is phase 2's product work still open, as is the removal of quick-or-deep as a choice (kill 4, held by CP-2's falsifier). Triage's mission term landed with phase 5; the settling lag and a process's early stages as signals, and a run proposed with its cost, with the close-out (C4, 2026-10-05, ROADMAP §3.53): the day's settling reading that moves the lag, a stage that slowed or a promise breaking more against the measurement it overwrites, each opens an inquiry that spends no run — and every inquiry a signal opened, or that woke, proposes its run with the median tokens, minutes and dollar floor of the install's own metered runs, the charter's ceiling, and what the run could change.* |

**Phase 3 · Decision and simulation**

| | |
|---|---|
| Capabilities | **the decision record as a by-product** (section K's three rules), with options, relied-on claims as recorded, dissent and the expectation line; **the review question delivered** to the resolved owner through the departure gate, where today it is logged; **outcome against baseline** — the metric's own history, not "before" (`IDEAS.md` 13 and 22) — and against expectation; **scenario methods 1–3** behind the method interface: identity from statements and formulas, declared assumptions as named claims, history from a bought forecaster with its backtest error on this metric; **predictions scored** when their range is Final, interval coverage by method, metric and author; the departure gate's law 5 narrowed from "a forecast never departs" to "an *unscored* forecast never departs" |
| Architecture | Decision, Scenario and Outcome as ledger kinds (section G); the scorer is code on the settle tick; the forecaster is a library behind an interface that must declare its backtest; write-back from an outcome to every relied-on claim's class, the playbook entry and the author's record |
| Product | the Decision page (screen 5) with the Scenario inside it (screen 6); the Inbox retired into Decisions; the review question arrives in the thread or on Now; the Briefing's items carry the predictions that bear on them |
| Dependencies | phase 1's booked decisions (the first review dates fall in this phase); an owner resolved for every decision; a forecaster chosen and backtested per metric |
| Risks | the ledger stays empty because capture costs a form — the three rules of section K are the design, and the metric is the share of decisions captured without a form; a good decision with a bad outcome punished — both verdicts kept, always; a model asked for the volume response — refused by construction (`llm_inferred` does not exist) |
| Metrics | decisions booked a month · share captured as a by-product · share with an expectation line · review questions delivered and answered (0 and 0 today) · outcomes reconciled · interval coverage at the stated level, by method · signed error by owner group |
| Exit | a first set of decisions reconciled on their review dates against baseline; interval coverage published for method 3 on at least one metric; the first forecast that departed, scored |
| Status | *2026-10-05: the code half is built, in three slices on `claude/platform-2027-study` (ROADMAP §3.53): the review measures the metric's own history (method 3) beside the "before", books the Outcome with both verdicts by code, scores the prediction and delivers the question through the departure gate to the owner's channel — a person with no channel bound is said, not silent; the ladder's first three methods behind one interface, each saying what it must, predictions scored on the settle tick when their range is Final, coverage counted by method, metric and author; law 5 narrowed so a forecast citing a scored prediction departs. Of the exit, every part needs the install: decisions reconciled on real review dates, coverage published for method 3 on a real metric, a forecast that departed and was scored. Still open in phase 3: the Decision page (screen 5) and the Scenario inside it; the Inbox retired into Decisions; the Briefing's items carrying their predictions; a bought forecaster behind the history method (today the method is the platform's own mean-and-band, with its backtest said).* |

**Phase 4 · Action**

| | |
|---|---|
| Capabilities | **verification and undo on every declaration** — an action with no verification statement cannot be declared; **the earned ladder joined to standing grants**: keyed by action kind and scope, fed by verified executions and outcomes inside expectation, widening and withdrawing grants (`aughor/memory/trust.py` and `aughor/actions/grants.py`, which have never met); **automatic demotion** on a failed verification or an unexplained miss, as a ledger entry; the L0–L5 table of section M; L4 and L5 reopen §4.8 — only here, only on the condition that phase 3's outcomes exist, and §4.7 stays closed |
| Architecture | Action as a ledger kind with its grant cited; the outbound gateway and the single MCP call door stay the one write path; the verification read runs through the ordinary query door; the undo is a declared compensating action with a window |
| Product | the Action centre (screen 11) with the authority table; the approval queue absorbed into it; the Operate duty appears in Operations' duty rows |
| Dependencies | phase 3's recorded outcomes; the approval gate on by default from phase 0; the user's decision to reopen §4.8 on that condition |
| Risks | a grant drifts wider than its receipt — a grant is bound to a target, a scope, limits and an expiry, and widening is itself a receipted graduation; demotion that nobody notices — it is a Now item for the owner and a row on the mission report; an action declared without an undo because "it is harmless" — refused at declaration |
| Metrics | declared actions (1 today) · share with verification and undo · executions by level · verification pass rate · undo rate · demotions · approval work per week (should fall as L4 grows) |
| Exit | one action kind graduated L3 → L4 on a receipt, on the organisation's install; one demoted in a drill with the misses cited on the entry; no irreversible action above L3, checked by a ratchet |
| Status | *2026-10-05: the code half is built, in three slices on `claude/platform-2027-study` (ROADMAP §3.53): every declared side-effect action carries its reversibility, a verification statement and an undo or is declared irreversible by name, refused at the declare door otherwise; the executor runs the verification read after dispatch and books every execution as an Action entry citing what it ran under; the ladder is computed per action and scope from that record, L4 granted only on a graduation receipt whose condition is phase 3's exit by construction (an outcome inside expectation on a decision that ran the action), L5 unreachable until missions exist; a failed verification demotes automatically and withdraws the standing grants; a policy grant is minted only at L4, bound and capped, citing its receipt; `/authority` serves the table. Of the exit, the ratchet is met (an irreversible action never graduates, held by code and test); the graduation on the organisation's install and the demotion in a drill wait on the install and on phase 3's first reconciled outcomes. Still open in phase 4: the Action centre (screen 11) and the approval queue folded into it; the Operate duty in Operations' duty rows. The undo is fired as an executable compensating action and the integration and MCP write paths book their writes as Action entries since the close-out (C5, 2026-10-05, ROADMAP §3.53): `POST /authority/{action}/executions/{entry}/undo` runs the declared undo through the same governed pipeline inside its window, its entry naming the one it compensates, the original restated as undone, a failed undo demoting the action; every gateway write is on the record with its status, saying it declares no verification read and no undo (`GET /authority/writes`).* |

**Phase 5 · Missions and memory**

| | |
|---|---|
| Capabilities | **the mission** (section J) as a ledger kind written by people, with its budget and authority ceiling; triage's first term ("bears on a mission") gets its input; **the mission report** on its cadence, the objective against baseline first; **Corrections** as a first-class view with its four records; **scenario method 4** fed from the install's own reviewed decisions, so the confirmed-cause graph (`aughor/lifecycle/causal.py`) grows for the first time; procedures carry a success rate learned from outcomes, not from use |
| Architecture | Mission as a ledger kind; the budget charged by triage and the gateway; the report composed from fields; method 4 reads Outcome entries and nothing else |
| Product | the Mission page (screen 7); Missions as a destination, absorbing monitors, promises and cockpits as what a mission watches; Record's Corrections view (screen 9); the Briefing's mission line |
| Dependencies | phase 3's outcomes (for method 4 and the report), phase 4's ceiling (for a mission's authority), phase 2's triage (for bearing) |
| Risks | missions written by a model "to help" — refused, the same rule as the organisation's ontology; a mission that produces activity and no movement reads as success — the report leads with the objective against baseline by construction; forty missions — the budget is per owner and interruptions are charged, so a mission with no slots left is silent |
| Metrics | active missions with owners · interruptions charged against budgets · mission reports delivered · objective movement against baseline with its interval · Corrections entries by kind · method-4 estimates with a count of past cases |
| Exit | one mission run for a full quarter and reported against baseline, with its cost — whether or not it moved the objective |
| Status | *2026-10-05: the code half is built, in two slices on `claude/platform-2027-study` (ROADMAP §3.53): the mission as a kernel artifact written by people and refused from a model, with its objective, constraints, scope, owner, budget, authority ceiling, watches and cadence — a mission without an owner does not run; triage's first term read from the missions people wrote, the mission written on every departure's row and charged against its own interruptions a week on top of the addressee's slots, a spent mission held and named; the ladder capped at the ceiling an active mission set; the report composed from fields by code — the objective against the metric's own history first, then constraints, watches, what it opened, what it decided, what it cost and the lessons — booked, advanced and delivered to the owner through the gate on the heartbeat; Corrections as one view over five ledger records with what was believed and what replaced it, a missed move booked by the review that found it; scenario method 4 from Outcome entries and nothing else; the confirmed-cause graph grown from the review's measured verdict; a play's success rate learned from outcomes with its count. Of the exit, every part needs the install and a quarter: a mission run for a full quarter and reported against baseline, with its cost. The close-out (C6) added the two code items that were still open: spend attributed to a mission from the receipts of the runs its inquiries spent, with its unit, what was unpriced and the budget it is read against (said as not counted when nothing prices it); and L5 — granted only on an L5 receipt a person books on a long L4 record (20 verified executions) inside a mission whose ceiling sets the action at L5, lost on a demotion — with the agent that chooses among the declared actions toward a mission by their measured effect on its objective (method 4), the parameters the owner wrote, one action per review period, booked as a Decision with its expectation and run through the governed pipeline; held at the approval gate until a standing grant covers the parameters, said. Still open in phase 5: the Mission page (screen 7) and Missions as a destination absorbing monitors, promises and cockpits; the Corrections view on screen; the Briefing's mission line.* |

**Phase 6 · Vertical intelligence**

| | |
|---|---|
| Capabilities | **packs as claims with priors** — types, links, processes and promises as claims measured on connect (ON-0a's direction), monitors with prior normal ranges, playbook entries with base rates, scenario and mission templates, golden questions; **two verticals deep** from section P — commerce (two packs and three datasets exist) and one of B2B SaaS or banking (a drafted package exists); **onboarding hours as a release gate**: connect → first warranted claim someone relied on; the data shopping list (`IDEAS.md` 10) and coverage (`IDEAS.md` 15) as the day-one screen |
| Architecture | the pack loader measures and compiles; nothing in a pack is code; the kernel's industry-noun ratchet (section P) starts at its measured baseline; the method interface accepts a pack's scenario templates |
| Product | a new connection speaks the industry's words within a day: terms proposed for confirmation, alerts with backtests, the shopping list, the first Briefing |
| Dependencies | phases 1–5 for the objects a pack declares templates over; a second customer organisation in each vertical to take the hours measurement on |
| Risks | the vertical becomes a code path (the ratchet: a pack cannot add a store, a screen type or a code path); a pack's priors shipped before they were measured anywhere (a prior carries the installs it was measured on, or says none); a confirm-not-configure flow that still needs a consultant — the hours measurement is the gate |
| Metrics | hours from connect to the first relied-on claim · share of a pack's claims that held on connect · definitions confirmed against proposed · industry nouns in the kernel (baseline, falling) |
| Exit | on a new customer in each of the two verticals: connect to first relied-on claim in under a day, with the receipt |
| Status | *2026-10-05: the code half is built, in two slices on `claude/platform-2027-study` (ROADMAP §3.53): a pack's map measured against a connection is booked into the Record as the pack's hypotheses — open while the data cannot speak, supported or refuted once it has, restated on every build — by the pack writer, the fourth of §E's five shapes; packs ship watches with prior normal ranges, plays with base rates, scenario and mission templates, and the static gate refuses a prior that states a number without saying where it was measured or that it was not; commerce (core-ecommerce, fashion-ecommerce) and banking carry priors and templates with their provenance (two public datasets' promise readings; the FDIC's dataset the package was measured on; approval rate said as unmeasured); onboarding hours — connect to the first claim a decision relied on — measured against a 24-hour gate and "not yet" before any decision; the data shopping list and coverage as one day-one door; the kernel's industry-noun ratchet at its measured baseline, and the kernel's doors answering with no pack installed. Of the exit, both parts need a new customer in each vertical: the hours measured on their install, with the receipt. The close-out (C7) added the two connect-day items: a bound pack's terms — a metric's title and aliases, an object's name and aliases on the table the map matched it to — written into the connection's vocabulary at a `pack` source below a person's word and this install's mined evidence, widening what a question can match at once and reaching no prompt until a person confirms one, a decline a tombstone the next bind cannot resurrect; and a measured prior's band staged as one monitor proposal per bounded side, in the inbox's own shape, with the prior's provenance and a backtest of that band on this connection ("would have fired 3 times in the last 365 days", or why it could not be replayed), armed only by a person's accept — an unmeasured prior and a metric the connection has not registered stage nothing and say why. Still open in phase 6: B2B SaaS as a second deep vertical (banking was chosen, its package drafted); the industry nouns still in the kernel's docstrings, which the ratchet now counts down.* |

**Phase 7 · Platform and ecosystem**

| | |
|---|---|
| Capabilities | **the ledger API** published: post a claim with its warrant, read as recorded on a date, subscribe to restatements; **the agent contract** published (the seven duties, the typed verdicts, what an entry must carry); **the pack kit and upload**; **the method interface** for forecasters, estimators and simulators with their backtests; **the event catalogue** out; **aggregate priors** across installs — base rates and normal ranges as aggregates only, never a customer's claims |
| Architecture | the MCP server and the ledger API as the two doors; service principals under policy; nothing runs inside the process; an exported ledger so adopting is not a trap |
| Product | the Developer screen (screen 13); packs listed with their measured record and demoted by the same receipt that promoted them |
| Dependencies | phase 1's ledger for the API; phase 6's two verticals for priors worth aggregating; the user's call on what aggregates may leave an install |
| Risks | a third party's write path around the warrant — refused at the door, the only door; a pack listing that rewards stars instead of record — the listing *is* the record; the contract published before the platform's own agents obey it — they are held to it first |
| Metrics | outside principals posting claims · claims posted with a warrant (100% by construction) · third-party packs with a measured record · methods registered with backtests · installs contributing aggregates |
| Exit | an outside vendor's agent posting warranted claims under a service principal and being scored beside the built-in ones; a third-party pack listed with a measured record |
| Status | *2026-10-05: the code half is built, in one slice on `claude/platform-2027-study` (ROADMAP §3.53): the ledger API under `/ledger/v1` — post a claim with its warrant (the three laws at the door, refused with why; the author is the principal, never a field), read claims as recorded on a date, read what was restated since a cursor with what each replaced, subscribe to the Record's events as webhooks, export the ledger as lines so adopting is not a trap; service principals minted by a person and held to the organisation's agent policy, resolved from two headers, revocable, their record read beside the built-in agents'; the agent contract rendered from the code that enforces it (`docs/AGENT_CONTRACT.md`, held equal by a test) and the four MCP tools that carry it; the event catalogue as a measured ratchet (every kind the source journals is catalogued with its payload) and events out through the one departure gate — a delivery is judged like every other exit, with the attention budget exempt by the gate's own written policy because a machine asked; the pack kit (`GET /packs/kit`, `POST /packs/check`, `POST /packs/upload`) writing a passing pack as a draft with its provenance, refusing code, and the listing that IS the record — a pack demoted by the same measured claims that promoted it; the method interface for forecasters, estimators and simulators registered with a declared backtest and run only as foreign MCP tools through the one door, projecting in the ladder's shape; aggregate priors (pack records, base rates, normal ranges for share metrics, method backtests, never a connection id or a claim's text, enforced) behind `aggregates.share`, off by default — the user's call — with the export door refusing and saying so. Of the exit, both parts need the install: an outside vendor's agent on a real service principal, scored beside the built-in ones; a third party's pack uploaded and measured on a connection. Still open in phase 7: the Developer screen (screen 13 — the doors exist, no screen reads them, and the web client is not regenerated for the new routes); OAuth for MCP servers that need their own sign-in; a second install to receive an aggregate; the exit itself.* |

**What is deliberately in no phase.** Fine-tuning (kill 1); the SQL editor past SE-8 (kill 2); new
model-compensating scaffolding (kill 6); the canvases as surfaces to improve (kill 7); a hosted
multi-tenant plane (Arc MT stays dropped); email as a door (the user's); a model judge (§4.8); a write
side on the warehouse (§4.7). Each has a revisit trigger on its line in the roadmap or in this study,
and none is a gap in the plan.

---

## X · North Star

**Three candidates were weighed.**

| Candidate | What it counts | Why it is not enough alone |
|---|---|---|
| **Reliance** | the share of what leaves the platform that someone acted on | it is the flywheel's first arrow and the right phase-0 exit, but it cannot see whether the reliance was deserved: a wrong number acted on counts the same as a right one |
| **Calibration error** | of everything said at a stated confidence, how far the hit rate fell from it | it is the product's defining number (section B), but as a target it is gamed by saying less, or saying only the safe things; a perfectly calibrated system that nobody decides on has done nothing |
| **Closed loops** | decisions that carried a booked expectation and were reconciled with a measured outcome | a count alone can be inflated with trivial decisions |

**The choice: closed loops per quarter, guarded by calibration error.** A count that must stay
calibrated cannot be inflated: a trivial decision adds a prediction that has to land inside its
interval at the stated rate like every other, and a flood of safe ones shows as over-confidence or
under-confidence by class. Each number stops the other's failure mode.

**The definition, so it can be a query and not an impression.** A loop is closed when all five hold:

1. a **Decision** entry exists with a named, resolved owner;
2. it carries at least one **prediction** booked at or before `decided_at` — a target, an interval at a
   stated coverage, a method and a `settles_on`;
3. an **Outcome** entry was written on or after the review date, measured on **settled days only**;
4. the outcome records both verdicts — against expectation and against baseline, where baseline is the
   metric's own history (`IDEAS.md` 13) — or says *cannot tell* and why;
5. the write-back ran: the relied-on claims' reference classes, the playbook entry and the author's
   record were updated.

A decision with no expectation is booked and counted separately (it is still worth having — it is
reliance recorded) but it is not a closed loop. A loop closed by a model's judgment of the outcome
does not exist: the scorer is code on settled readings (§4.8).

**The guard, as a number.** Calibration error is the mean absolute gap, by month and by reference
class, between stated coverage and observed coverage over the predictions that settled that month —
and the same for stated confidence on claims, once confidence is counted (phase 1). It is published on
the Briefing's data-health line and on the Developer screen for every pack and principal. The North
Star is reported as a pair, never as one figure: *loops closed this quarter · calibration error this
quarter*, with *n*.

**Today's value: zero, measured.** "Nobody has ever recorded an outcome" (`PENDING.md`, loose ends,
2026-10-04). No decision has an expectation because nothing can book one. The number can only be
observed on an organisation's install (phase 0), and its first non-zero reading falls in phase 3, when
the first review dates arrive. That is the honest state, and it is the whole argument of section A in
one digit.

**The leading indicators, by phase** — what moves before the North Star can:

| Phase | Leading indicator | Reads from |
|---|---|---|
| 0 | numbers that left and were acted on by someone who is not the analyst | the departures ledger joined to the first reliance records |
| 1 | decisions booked a week; the share with an expectation line | the Decision entries |
| 2 | inquiries opened by the platform; the held list's length against slots | Inquiry entries; triage's holds |
| 3 | review questions answered; predictions settled; coverage by method | Outcome entries; the scorer |
| 4 | executions verified; the first L4 grant | Action entries; the authority table |
| 5 | missions reporting against baseline | Mission reports |
| 6–7 | hours to first relied-on claim; outside principals posting warranted claims | onboarding receipts; the ledger API's audit |

**What it is not.** Not asks, not findings, not agents, not tokens, not seats, not packs installed.
Each of those can rise while the organisation learns nothing about itself. A quarter with eleven
closed loops at 4% calibration error and nine hundred asks is a good quarter; a quarter with nine
thousand asks and no closed loop is the quarter the platform has had so far.

---

## Y · The 2027 customer story

**The organisation.** A commerce company of the kind the repo already has data for — a few hundred
people, one warehouse, a commerce platform, an ERP, two carriers, an ad platform, a Slack. It bound the
commerce pack in a day in early 2027. Eight people own things in it: gross margin, returns, the
delivery promise, three category P&Ls, pricing, the definition of revenue. Two of its other vendors'
agents read and write the ledger over MCP under service principals. Nobody there writes SQL for a
living, and two people still do when they want to.

**What the operations director said, in the quarterly review.** (A role, not a person; the sentences
are the ones the mechanisms in sections G–O make possible, and each is cross-referenced so none is a
promise this study has not accounted for.)

> "Three things changed this year, and none of them is that the AI got smarter.
>
> The first is that we stopped arguing about numbers. Every figure anyone brings to this room has a
> receipt, and the receipt says whether the days have settled, which definition it used, and how often
> figures of that kind have held up — so when two numbers disagree we open the receipts instead of the
> people [sections O, D]. The platform told us in June that a number we had used in April had been
> restated, in the thread where we were given it, before anyone was embarrassed by it [magic moment 1].
>
> The second is that we decide on the record. When we chose the free-shipping threshold in March, the
> options were on one page with what each was expected to do and where that expectation came from —
> arithmetic for one part, our own past price changes for the other — and we booked 'conversion +2 to +4
> by November'. In November the platform came back on its own and told us: +0.6, against a baseline of
> −0.3, so the decision worked, less than we thought [sections K, L; moments 17–19]. The quarterly
> record now tells us that pricing's forecasts run high and supply's lead times run short — not as an
> opinion, as a count [moment 20]. We have never had a document like that about ourselves.
>
> The third is that the system does things, and I am not afraid of it. Promotion pauses run under a
> standing grant because sixty of them were approved by a person first, every one verified, every
> outcome inside expectation; when two reorder changes missed, that action kind dropped back to needing
> approval by itself, with the two misses cited, and nobody had to notice [section M; moments 22–23].
> I get three interruptions a week and I can see the forty-one it kept from me and why [moment 13].
>
> What I would say to another director is: it is not an analytics tool. It is where we keep what we
> believed, what we decided and whether we were right — and it is the only thing in the building that
> remembers all three."

**"If it disappeared tomorrow, what is lost?"** The test of a system of record is what cannot be
reproduced by buying something else. Nothing on the left column below is lost; everything on the right
is.

| Not lost — any model re-derives it in an afternoon | Lost — it was time-locked, and the calendar does not run backwards |
|---|---|
| the SQL for any question | **what was believed on each date** — the ledger as recorded, the second clock |
| the charts, the narratives, the reports | **which decisions stood on which claims**, and which were reopened when a claim was restated |
| the anomaly list | **the outcomes** — what actually happened after each decision, measured against baseline on settled days |
| the ontology as a description of the tables | **how often each source, method, author, pack and agent has been right** — the counted confidence that turned claims into things people relied on |
| the agents, the prompts, the model bindings | **the authority the organisation's agents had earned**, kind by kind, with the receipts that granted it and the misses that withdrew it |
| the dashboards | **the agreements** — what revenue means here, what the missions are, who owns what — written by the company's own people |
| the alerts | **what the organisation was wrong about** — the restatements, the refuted causes, the missed moves, the predictions outside their interval |

The right column is also the answer to what a competitor arriving in 2027 with a better model cannot
offer on the day it arrives, which is section S in a sentence. And it is why the ledger must be
exportable (the closing attack, the internal team): a record a customer cannot take with them is a
trap, and a trap is not a system of record.

---

## Z · The closing attack

Five attackers, each given its strongest case rather than a straw one, and for each: the attack, why it
is strong, what it cannot do by its own nature, what survives it, and what it forced this study to
change. The redesigns are not new sections; each names where in F–Y it was already folded in.

**1 · The best AI-native startup.** *The attack:* faster and lighter — connect a warehouse, ask, get
investigated answers in an hour, nothing to declare, no ontology, no approvals, a product that feels
like a frontier model because it is one. *Why it is strong:* it is what Aughor was on 2026-08-26 (chat
first, Agent the default), and it wins every demo. Most of what section A's table calls "built and
starved" is exactly the surface it would ship. *What it cannot do:* it has no reason to refuse to show a
number before the days have settled, no reason to hold a send, and no record — speed is its whole
product, and warrant is slow by nature. In month six its customer has a thousand confident answers and
no way to know which were right. *What survives:* day-one value with nothing declared — the Watcher's
proposed alerts, explore-on-connect, the shopping list, the Briefing on a fresh connection (phase 6's
hours gate is the measure, and it is a release gate, not a hope); six destinations instead of fifty; and
the open door — let its agent cite this ledger over MCP, because a startup whose answers carry Aughor's
receipts has become a client, not a competitor. *What it forced:* confirm, do not configure (section P);
Ask as a bar everywhere (U); the agent contract as the way in (Q).

**2 · The best data platform.** *The attack:* the warehouse vendor ships metric definitions, an
ontology, a semantic layer and an assistant, bundled at no extra price, inside the place the data
already lives, with every vendor's BI tool reading them. Roadmap §0 saw this coming and called the
ontology-to-agent loop the moat anyway. *Why it is strong:* it owns the data and increasingly the
meaning, its distribution is total, and its definitions will become the open interchange format. *What
it cannot do:* its interest ends at its storage boundary, and a decision's evidence and its outcome
usually sit in different systems — the warehouse, the commerce platform, a Slack thread, a carrier's
feed. It has no notion of a decision, no second clock, and it is a party to the number it would be
scoring. *What survives:* import its definitions (section F's buy table: own approval and grain, not
the statement); own what spans sources — the organisation's ontology keyed across connections (ON-8),
promises that cross systems; and own what is not data at all — decisions, expectations, outcomes,
authority, the record of being wrong. *What it forced:* the semantic layer downgraded to class C and its
definitions treated as imports (reassessment table; F); the ontology moved from moat to map (assumption
1); the scope moved from the connection to the organisation (E, item 2).

**3 · The best enterprise software company.** *The attack:* the system of action — CRM, ERP, commerce,
ticketing — ships agents inside the transaction. It owns the action, the workflow, the approval chain
and the user's screen; its agent pauses the promotion because the promotion lives in it. *Why it is
strong:* it needs no integration, its actions are native and reversible by its own machinery, and it
already has the customer's authority model. *What it cannot do:* it is the actor, so it cannot be the
scorer — the roadmap's own rule for models (§4.8) holds for vendors; each one grades its own agent, in
its own module, by its own definition of success, and nobody holds the whole loop across the five
systems a decision touches. *What survives:* stay thin on action — a reference, never a second write
path (M); be the independent record across every system of action, which is what section F's "the
scorer is code and is never the actor" buys the customer; let their agents take the Operate duty under a
service principal and be scored beside everyone else's. *What it forced:* actions as references with a
verification statement and an undo (G, M); the authority table that cites receipts rather than roles
(screen 11); the refusal to become a system of action, written as a law rather than a preference.

**4 · The best model vendor.** *The attack:* it owns the intelligence, the default surface — the chat
every employee already has open — and "memory": it remembers what the company told it, across every
conversation, and improves with every model release. Its agents will take every duty in section H
better than Aughor's built-ins. *Why it is strong:* everything in the reassessment table marked E
depreciates toward it, and class D's agent architecture is a 2025 picture of what it ships for free.
*What it cannot do:* its memory lives inside one vendor's model, which a company will not accept as the
record of its own history; it cannot be model-neutral about its own outputs; it grades its own answers
by construction; and the company's authority, agreements and outcomes are not things it can know
without being told — by a system of record. *What survives:* a model-neutral ledger in the customer's
custody with bring-your-own backend (F); scoring by code on settled readings, never by a judge (O,
§4.8); agents defined by duty so any vendor's can take one and nothing is remembered that nobody can
inspect (H); and the position of being the server its agents call rather than the surface that competes
with its chat (Q). *What it forced:* the agent runtime delegated and the roster killed (C, item 3); the
model id kept out of source and off the moat list (S, rank 11); memory redefined as the ledger read
through time (N); the receipt page made the same page for a person and an agent (screen 10).

**5 · An internal team with unlimited engineers.** *The attack:* "we can build agents on our own data";
they know the business, they own the warehouse, they have the model vendor's kit and a year. *Why it is
strong:* they are right about the agents — section H says the platform does not need its own agents to
be the best ones, and theirs can be. *What it cannot do:* it cannot have priors learned across other
installs (S, rank 5 — the one thing an internal build can never have); it will rebuild the laws the hard
way, one incident at a time (the departure gate exists because of 2026-09-16's "NOT reliable" brief);
and — the decisive part — it starts its record on the day it ships, which is a year from now, while the
calendar is already running. *What survives:* priors across customers as aggregates; the method as the
product — settling, the envelope, the scorer, the ladder, the receipt — which is a year of lessons
nobody wants to re-learn; and a ledger the customer can export, so adopting is not a trap and the
internal team can build on it instead of against it. *What it forced:* an exportable ledger as a
requirement rather than a courtesy (F, Y); the agent contract so their agents are first-class (Q);
"start the clock first" as phase 1's ordering rule — book decisions and expectations before they have a
screen, because the record is the only asset whose value is a function of its start date (W).

**What the five together force.** Thin agents and thin actions; definitions imported rather than owned;
the scorer never the actor; a model-neutral ledger in the customer's custody that it can export;
day-one value with nothing declared; one door that any vendor's agent can come through and be scored.
Each of those is already in sections F, H, M, Q and W. Not one of the five attackers can be the neutral
party, and that — not a feature — is the position.

**The final question, answered.** The brief's last question was what stays scarce when intelligence is
nearly free. Section A gave six answers; here is what each becomes in the product, so the whole study
can be checked against them.

| Scarce in 2027 | What it becomes here | Where |
|---|---|---|
| **Warrant** | the ledger and the receipt — no entry without a source, every figure with its as-of and status, the seven lines | G, O, screen 10 |
| **Attention** | the budget — slots a week, charged to missions, every hold recorded and shown | I, J, screen 2 |
| **Authority** | the earned ladder — granted on a receipt, withdrawn on a miss, bounded by a ceiling a person set | M, screen 11 |
| **Agreement** | terms, definitions and missions written by people only, compiled by code | D (6, 8), J, P |
| **Consequence** | outcomes — measured on the review date, on settled days, against baseline, written back | K, phase 3 |
| **Earned trust** | calibration — confidence as a counted frequency with its *n*, published by month as the product's own number | O, X |

Six scarcities, six mechanisms, one ledger. If analysis becomes free, this is what is left to own.

---

## The pending ledger against this roadmap

*`PENDING.md` re-read in full on 2026-10-04, as ticked on #565. Every line still open — `[ ]` or `[~]` —
is placed against this study. The rule applied is the user's: an item that goes against the study is
discarded. A discard is a struck line in `PENDING.md` with its reason, never a deleted one (the file's own
rule) — done 2026-10-04 on adoption: the twenty are struck in `PENDING.md` with these reasons, and every kept
and reshaped line carries its phase at its end, as *2027 study: phase N* (76 lines). Six verdicts: **discard**
(what it contradicts), **reshape** (what it becomes), **keep** (which phase), **receipt owed** (unchanged —
the repo's rule, not the study's), **the user's** (⚑, unchanged) and **parked** (unchanged).*

The file holds 126 open lines (113 `[ ]`, 13 `[~]`). They are placed as items, not lines: the top list's
thirteen open items are the same items as their arc lines, two lines are split where their halves go
different ways, and a few receipts owed sit inside ticked lines — 117 placements.

| Verdict | Placements |
|---|---|
| Discard | 20 |
| Reshape | 12 |
| Keep, in a phase | 55 |
| Receipt owed, hygiene, parked or the user's — unchanged | 30 |

**Discarded.** Each contradicts a line of section C, a class in the reassessment table, or a refusal.

| Pending line | Where | Contradicts |
|---|---|---|
| TJ-5 the gym, as written — K rollouts to SFT, preference and repair pairs | top item 36 | kill 1: the fine-tuning destination. Its first half is reshaped below |
| TJ-6 serving a student | top item 37 | kill 1 |
| MI-4 the first fine-tuned text-to-SQL model | Arc MI | kill 1; class E |
| MI-5 / MI-6 a model shipped with the app, adapter releases, RL training | Arc MI | kill 1; roadmap §8 (no model weights in the repo) |
| JD-1's agreement receipt and JD-4's corpus receipt — paid runs to extend the outside judge | Arc JD | kill 5: the cheap-model line, "what is there, left alone" |
| JD-6 a small local scorer | Arc JD | kill 5; kill 1 |
| A6 auto-tuning metric definitions — the auto-apply half | Arc JD | section D item 6 and H: a definition is declared by a person; a model may only propose. The propose half is reshaped below |
| Payments & fintech next, then insurance, a risk-and-fraud function | Arc IP | section P chose five verticals; neither is among them. Revisit after phase 6 |
| The paid with-and-without-package test on airline (gate 5) | Arc IP | airline is not one of the five; the gate itself is reshaped below |
| More airline metrics | Arc IP | same |
| The Human / Agent / Substrate switcher | Arc UI | kill 11: the three planes are architecture, not a control a person uses |
| The weekly count of new agents and automations in Agent Ops | Arc SP | kill 3: the roster as a product idea; Operations shows work by duty, not a headcount |
| Documents placed on the canvas (the second half of its line) | Arc DX | kill 7: canvases as surfaces to improve |
| Pinning from a canvas's chat keeps the card for the connection, not the canvas | Arc CT | kill 7; the cockpit left the canvas with CT-10 |
| The palette's Runs side rail — rewrite its spec or drop it | Arc DS | kill 7: drop it |
| Ports and wires coloured by data type | Arc DS | kill 7 |
| Greyed-out palette items with a link to enable them | Arc DS | kill 7 |
| The Langflow steps we lack: file read/write, a calculator, the date, a raw LLM step | Arc DS | kill 7, and H's rule for the last: anything that must give the same answer twice is code |
| The drag fix and drop-a-wire gesture's hands-on test | Arc DS | kill 7 |
| A web-search vendor for a step | Arc DS | not in the study anywhere; a tool choice with no mechanism behind it |

**Reshaped.** The item survives as something the study names.

| Pending line | Becomes | Phase |
|---|---|---|
| TJ-5's first half — problems with known answers from the declared ontology's compiler, scored by execution match | the generator for golden suites and the canary (section O), not a training corpus | 1 |
| Scores on objects — churn risk per customer (top item 29) | a Claim of kind prediction under the Forecast duty, carrying method 6's licence: refused above a stated stake unless backtested on this install. The SQL-only stand-in is a formula today | 3 |
| BR-8 the daily ledger — every approved metric's parts per day, so "what we knew on a date" is a query (top item 45) | the settle clock's readings booked as observation claims with two clocks; it is the data half of section G's ledger | 1 |
| A2 — send close calls to a person, blocked on a real confidence number | a question to the resolved owner, asked once through the gate, as the departure gate already does for a disagreement; the number it waits on is counted confidence | 2 |
| A6's propose half | the Steward duty proposes a definition; a person confirms | 2 |
| The with-and-without-package gate | a pack's measured record on connect: how often its claims held on the installs that bound it (section Q) | 6 |
| A second Slack reply on the same object overwrites the first reply's check | one claim per said statement in the one ledger (section E, item 1) | 1 |
| The ranker's note kinds, and asking once when two equally trusted sources disagree | section N's conflict rule: tier, then scope, then recency by kind; two at one tier are contested and the owner is asked once | 1 |
| A limit set by a cockpit proposal schedules no monitor | a card's limit is a watch a mission holds; the mission's page offers the monitor | 5 |
| `context_graph/` tracked in git and rewritten by the app | the graph becomes a projection of the ledger, rebuilt on demand (section F); nothing of it is tracked | 1 |
| The "pause for a human" step, off by default so it never fires | on by default, with the approval gate (section E, item 7) | 0 |
| Idea 12, guess before you look | a person's guess is a Claim of kind prediction with their name on it, scored like any other; optional | 3 |

**Kept, and placed.** The phase each belongs to; the ones marked ⚑ keep their mark.

| Phase | Pending lines |
|---|---|
| **0 · Remove the wrong assumptions** | delete the parked object-query tool (top item 30, ⚑); the chooser-confidence switch — run it once, keep or delete (Arc MI); the prompt blocks §6 item 15(d) said to cut back (Arc ON, ⚑ a paid ablation); `aughor migrate-state` run for real (Arc IN, ⚑); `ontology_overrides/` into the data folder (Arc IN); group permissions enforced (Arc HB — identity on); cross-user questions (Arc SP — identity on); Slack approvals tied to the approver (Arc SP — identity on); the proposal approver recorded by screen name (Arc CT — identity on); an automation using another user's account, logged not blocked (VA — identity on); SSO against a real identity provider and the Google account's connect-use-revoke (VA, ⚑); theLook's Day subscription and `briefing.ranges` on — the seven mornings (Arc BR, ⚑); the promise-breach chain run live end to end (Arc HB) — this is the flywheel's first turn; cap hits, guardrail events and budget overruns on the governance feed (Arc MI, ⚑) — one audit sink; the stale roadmap lines (the file's last section) |
| **1 · The intelligence kernel** | TJ-2's open bullets — exporters reading the one record, the guard table's second meaning, the explorer's step log; TJ-3's step credit and NULL confidence, and ⚑ the audit sitting of 50–100 bronze rows; BR-2's live receipt on theLook (⚑); BR-7's cell, metric and covered days on a finding, and the live exploration run (⚑); the cross-connection hop and object pages that read one connection (Arc ON); links to query-backed types (Arc ON — the other half of that line is built, below); A3 the metric-definition report screen, tried live; A5 questions kept word for word with no expiry — section N's retention rule; accepting a Slack send from the inbox files a thread like an automatic send (Arc HB) — "who else was told" needs every send recorded; the Jev judge checked live (Arc JD) — the canary's job; the data-profiles block's clean rerun (top item 19) and table popularity measured once (Arc SP) — facts for the model, not prose; the consistency and federation screens' flags (Arc PX) |
| **2 · Agentic inquiry** | CP-3 route on the label (top item 4) — held by its own falsifier until the corpus is repaired; a screen over the misses door (top item 28); a question worded differently, recognised by a synonym a person adds (Arc ON); the links and probation queues given a screen (Arc HB) — Operations; a person accepting, live, a suggestion the platform raised on its own, and the red-team drives (Arc SP) — the phase's exit metric; approval cards with a real cost per run (Arc SP); answer buttons on a deep-link registry (Arc SP) — section U's rule 5; idea 9, the attention budget; idea 14, the UI that does not look generated — section U's rules; the active tab marked by weight alone (Arc CT) — superseded by the navigation rework; the needs-human badge (Arc UI) — Now's badge |
| **3 · Decision and simulation** | the outcome loop nobody has ever answered (loose ends) — the review question delivered; idea 13, judge a recommendation against its trend |
| **4 · Action** | one Composio or Arcade tool run end to end through a custom MCP server (VA, ⚑) — an action as a reference to an integration call |
| **5 · Missions and memory** | the metric step's breakdown and an entity step (Arc DS) — the engine is how a mission acts |
| **6 · Vertical intelligence** | banking activated by a person (Arc IP, ⚑); loan-level lending metrics (Arc IP); what a clone still lacks — the two datasets (⚑) and the cross-connection declarations (top item 26); idea 10, the data shopping list; the install's industry question and the profile prompt (Arc IP); the coverage share reading "unknown" on BigQuery (Arc CB) — re-measure first, top item 19 found theLook's cache populated |
| **7 · Platform and ecosystem** | drafting a new package by hand, and old data-quality queries naming sample tables (Arc IP) — the pack kit; promoting a package strips `pack.yaml`'s comments (Arc IP); bundles of steps inside packs (Arc DS, ⚑) — mission and automation templates are declarations; MCP servers that need their own OAuth (VA); the guide searching packs and skills (Arc SP); CT-6 a cockpit out by other doors, on its trigger |

**Unchanged.** Receipts owed on the user's machine: Arc DE's MySQL, Postgres and Trino sections; Arc AO's
Install-button path over HTTPS, Rehearse on a real workspace, the nightly run and the every-fifth-verdict
trigger; TJ-4 live, once the app has `reactions:read` (⚑); Jira and Confluence through Atlassian's server;
revise-in-place and the three drafts proven live; promoting a chain's SQL shown live; the MCP tool step
seen in a browser; the owners panel's screenshot. Hygiene: the three meanings of "door" and the
`FleetOverviewPanel` rename (Arc AO — the rename lands with section U); the census's docstrings (Arc TJ);
the cockpit ask's 67,000 tokens of tool roster (Arc CT); a card that cannot say it is withheld (Arc CT);
the fixer ignoring a package's data-quality checks and one wrong metric-name match (Arc IP); hard-coded
colours and bare error lines (Arc UI); the eval suites renamed by purpose and the spend-cap refusal's link
(Arc PX); re-indexing that does not re-read originals, a chart inside a PDF read as an image, and short
Confluence pages lost (Arc DX); images and files from MCP tools dropped (VA); the two fixture automations
and the never-vacuumed database; the three local branches. The user's, unchanged: email in and out (HB-5)
— in no phase, as section W says; the `[export]` extra. Parked, unchanged: DE-7 the JDBC bridge; private
Google Sheets and Drive (Arc KI); an outside credential vault (VA); the deliberate refusals of the ontology
arc (top item 31) — each stays refused with its reason, and the study agrees with every one.

**Lines found stale while placing them.** Arc ON's "nothing can declare a measure that must not be summed
across periods" — the compiler holds `take: last` and refuses a sum across moments since top item 27
(`aughor/semantic/object_query.py`); only the links-to-query-backed-types half is open. Arc CB's "the
coverage share reads unknown for both BigQuery connections because the profiler has nothing cached" —
top item 19 measured theLook's cache populated on 2026-10-04 (7 tables, 75 columns); the second
connection is unmeasured. Arc AO's hygiene line already strikes two of its own four clauses.

**What the placement says about the ledger.** Of 117 placements, twenty go against the study, and all
twenty sit in three places: the fine-tuning destination, the automation canvas, and verticals the
study did not choose. Nothing in the kernel's own leftovers — the ontology, the hub, the Briefing, the
gate map — is discarded; most of it is phase 0 or phase 1 work the study depends on. The ledger and the
study disagree about where value grows, not about what is broken.

---

## What this study asks of the user

**All eight decided as recommended on 2026-10-04** — `ROADMAP.md` §6 item 39. In the roadmap's own manner
(§6, "the user's, not the builder's"), these were the calls the study needed, each with the recommendation
it was written under; they stay as the record of what was decided.

1. **The organisation's install** (section F; phase 0's exit) — identity on, Postgres, five or more
   owners. Everything measurable in this study depends on it. *Recommended: yes, as the condition of
   the rest; Arc MT stays dropped — this is not a hosted plane.*
2. **The freeze list** (section C) — adopt or refuse as a list, with each kill's "what survives" line.
   *Recommended: adopt as written.*
3. **Reopen §4.8's "an agent proposes; a person acts"** for L4 and L5 only, and only once outcomes are
   being recorded and scored (section M; phase 4's gate). §4.7 is not reopened. *Recommended: yes, on
   that condition, which is not yet met.*
4. **The navigation** (section U) — six destinations; and whether the authored layer gets its own
   Model destination as the UI/UX study proposed, or folds into Record. *Recommended: fold.*
5. **The North Star** (section X) — closed loops per quarter, guarded by calibration error.
   *Recommended: yes; today's reading is zero and should be published as such.*
6. **Six new words** for `docs/GLOSSARY.md` — claim (widened), inquiry, prediction, decision, mission,
   scenario — each proposed where it first appears. *Recommended: add them in the PR that first uses
   each, as the glossary requires; `investigation` stays frozen.*
7. **The departure gate's law 5** — "a forecast never departs" narrowed to "an unscored forecast never
   departs", in phase 3 and not before. *Recommended: yes, then.*
8. **The pending ledger** — strike the twenty discarded lines in `PENDING.md` with their reasons, and
   carry the phase of every kept line onto it, as the section above places them. *Recommended: yes, in
   the same commit that adopts this study; a struck line is a record, so nothing is lost.*

**Measured while writing this study, and not yet in the roadmap.** Automations have seven triggers and
thirteen effects, and a broken promise and a new finding are both triggers (roadmap §1 says five, twelve
and neither). The rail holds eighteen items, twenty-eight layers and five Settings pages (section U).
"Needs you" exists as a section head on the Agent Ops overview and nowhere else. The kernel ledger
already runs on Postgres. Identity is a start-time environment switch, not a flag. The approval gate is
off by default. The receipt page shows the guards that fired and the columns read, and offers no
re-perform. Each is a count with a date; re-measure before building on it.
