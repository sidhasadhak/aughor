# Aughor as the centre piece of an organisation's decision intelligence — the framework, and a run (2026-10-25/26)

The user opened this as a conversation, not a build: *"how making Aughor truly a center piece of an organisation's
decision intelligence"*, then *"Scan the web for more advanced decision intelligence platform[s] and what are they doing
and how"*, then *"an advanced decision flow — forwards & backwards with loops where every decision and their 'why' is
readable if the user wishes to.. let's think big"*, then: *"let's not haste into building something.. rather we should
invest much time into what could be a framework that one can design that will take care of either all of the points or
the most critical of the points.. the target should be to cover all."* And then: *"I want to actually run several
scenarios from arising to learned loops.. and I want you to run it for me."*

This document holds the four things that came out of it: what the field does (§2), the framework (§3), a worked example
on a retailer of a given shape (§4), and the run on the live install with what it found (§5–§6). Nothing in §3 is built
except what §5 says was built to let the run finish. Every number in §1 and §5 was read over HTTP from the live install
or from source on the dates given.

## 0 · The verdict

- **The field has converged on one loop** — sense, recommend, approve with graded autonomy, write back, remember, learn —
  and on *decision memory* as the asset. **None of the vendors scanned shows how an outcome is attributed**: against what
  baseline, with what guard against crediting a decision with the business's own growth. The only vendors that do the
  counterfactual honestly are the experimentation platforms, with program holdouts.
- **Aughor already holds the record the loop needs, nearly field for field** (`record/decisions.py`, the 2027 study §K)
  and the one piece nobody else shows — the comparison-group review with the Record's own calibration as a drift guard
  (PENDING 57, D-3). What it lacked on 2026-10-25 was **use**: 2 decisions ever, 0 missions, 0 recommendation outcomes.
- **The user's calls:** the three readings of "centre piece" are taken as **B + C + A** — the place a decision is
  *proposed* (an agent brings options with predictions, under a mission), the place it is *reviewed and learned from*,
  and the place it is *booked* from wherever people work — with C as the moat and A as its intake; and no building before
  a framework covers the whole problem.
- **The run turned the loop end to end on LuxExperience** and found that the honest review could not run on any metric
  defined today (§6, defect 1), and that one approved metric read the same all-time figure in every period (defect 7).
  Both are fixed on this branch; the other six defects are open and named.

## 1 · The ground, measured 2026-10-25

| On the live install | Count |
|---|---|
| Decisions ever booked (`GET /record/decisions`) | 2 — both approvals of 2026-10-10, no expectation, no outcome |
| Missions | 0 |
| Recommendation outcomes ever | 0 |
| Playbook entries | 886, all `active`, none measured |
| Claims | 577 — 426 findings · 130 predictions · 12 observations · 7 hypotheses · 2 said by a person |
| Corrections | 72 restatements · 42 predictions outside their band · 0 decisions worse than expected |
| Flag `record.decision_loop` | on (env) |

Six doors book a decision: Home's Decide, the approvals inbox, a recommendation, an autonomous action, "Not worth it", and
`POST /record/decisions`. Four places where people decide book nothing: a Slack thread (a ✅ is a verdict on an answer,
TJ-4), a dashboard Question's answer, the Briefing, chat. The Record's tabs are Inquiries · Decisions · Missions · Claims ·
Corrections. The scenario ladder registers identity · declared · history · intervention; the comparison group is the
review's baseline, unregistered on purpose. `autonomy.choose` reads method 4 over past decisions — with 0 outcomes to read.

## 2 · What the field does, and how (scan of 2026-10-25)

Gartner's first Magic Quadrant for Decision Intelligence Platforms (26 January 2026, 17 vendors) names six capabilities:
decision modeling · collaboration · service composition · execution · monitoring · governance. Leaders as self-reported:
FICO, SAS, Aera, IBM, ACTICO, Quantexa; Sapiens a Visionary, Decisions a Challenger, FlexRule a Niche Player.

| Platform | What it is | The mechanism it describes |
|---|---|---|
| Aera Decision Cloud | the closest to Moser's loop | a "Decision Data Model" that "captures all the decisions made in your organization, along with their context, actions taken, and outcomes"; agents recommend and "on your approval — executes"; the degree of agency is set **per decision type**, with "escalation thresholds based on confidence scores"; a Control Room monitors "the impact of your decisions" |
| Palantir Foundry / AIP | "every decision can be broken down into data, logic, and actions" | agents "create proposals" an operator decides; **Scenarios** (beta) fork the ontology's edits so several what-ifs stand side by side and the chosen one is merged by an action, 31-day lifespan; "capturing decision outcomes in the Ontology allows users to pair a particular decision with observations of the results" — no method stated |
| Cloverpop | the system of record for decisions | a "Decision Bank" of "what was decided, why, by whom, and outcomes"; a decision logged from Slack with one command; decision velocity and quality charts; outcomes scored by hand |
| IBM · FICO · SAS | decision management grown into the label | policy text turned into decision logic by an assistant; rules + models + generative AI in one governed flow; real-time decisioning; simulation; audit |
| causaLens · Quantexa · o9 | the analytic engines | causal discovery with intervention estimates; entity resolution into a knowledge graph, then scoring; an enterprise knowledge graph with planning scenarios and agents |

Four patterns hold: the decision is a modelled object with a lifecycle; autonomy is graded per decision type and widened as
agents prove accurate; memory of past decisions is read at the next one; scenarios are sandboxes, forked and merged. The
gap they share: none says against what baseline an outcome is judged. Aera "learns", Palantir "pairs", Cloverpop scores,
IBM "monitors". The experimentation vendors (Statsig, Eppo, Optimizely, LaunchDarkly, VWO) hold a control group off every
change and read the program's lift against it — the honest counterfactual, in a different market. Sources at the end.

## 3 · The framework

**In one sentence.** One stored object carries a decision point from the moment it arises to its last consequence;
capture into it is *invited* from wherever people work, never crawled; every edge is a dated fact with a source; and the
"why" at every step is composed by code from those facts, shown only when asked for.

### 3.1 · The thread: one vessel from arising to consequence

The 2027 study's **Inquiry** is the vessel: stored, it outlives its runs, records who or what opened it, what it
established, what it could not settle, the decisions it led to, the lessons at close; its state machine already has
"waiting for a decision". The framework widens it in both directions. The **thread** is a *view* over it — like Belief
and Memory are views in the model — never a new store.

```
ARISING      a signal · a person's sentence from anywhere · a document · a meeting · a prior decision
GATHERING    said claims · evidence by reference · runs · hypotheses · contradictions the data raises
OPTIONS      each option named, each with predictions by a declared method, dissent kept
DECIDED      chosen · by whom · approved by whom, where · the claims relied on AS THEY STOOD
ACTING       proposals → approvals → runs, each run naming its version and its cost        (Arc TC, §3.59)
REVIEWED     on the date, against what would have happened anyway · verdict and why        (D-2, D-3)
LEARNED      lessons · the author's calibration · the base rate for this kind of decision

LOOPS        a relied-on claim restated → the decision reopens, a person answers                   (built)
             an outcome lands → the next decision of this kind reads it as a past case (method 4)  (built, starved)
             a decision supersedes → the old thread is read backwards from the new one
```

**Two kinds of decision.** A *new* decision opens a thread. A *modifying* decision supersedes a prior decision or a
declaration — a process, a promise, a rule — which the ontology already versions as a release. The new thread points at
the old one, so reading backwards from the modification reaches the original reasoning without anyone filing it.

**Decision kinds, declared by the organisation.** A kind — a price change, a supplier switch, a budget move — declares
who must approve, whether an expectation is mandatory, the review cadence, the authority ceiling, and the metrics it
usually moves. Packs ship defaults; people confirm. An agent may then *propose* a decision of a declared kind with options
and predictions from the scenario ladder; a person decides. A model never authors a kind or a decision. This is what makes
reading B possible.

### 3.2 · Capture from anywhere: invited, never crawled

The hardest part of the user's problem is the first: a topic arises from Slack, a comment on a presentation or a sheet,
an email, a meeting; details and approvals arrive the same ways. The field's answer is to crawl, which this platform
refuses by law (the hub's first law; §K rule 3) and which buries a thread in noise. The framework's answer is **invited
capture**, in three tiers: a person attaches a thing; an owner connects one channel or one document to the thread and the
platform reads only that; crawling stays refused.

| Where it happens | How it enters the thread | State (2026-10-26) |
|---|---|---|
| inside the platform — a Home finding, a Briefing figure, a Question's answer, a chat answer, an alert | a Decide button on the figure opens or joins a thread; the figure's claim is the first evidence | Home built (D-1); the other four small |
| Slack — a topic arises, details are argued, approvals are given | a verb on the bot (as `check:` and `note:` already are) opens a thread from a message; a reaction attaches one; a **decision card** departs to the approvers and their ✅ books the approval as theirs, told apart from an answer's ✅; the thread's permalink is evidence | the bot, the departure gate and the ✅ verdict exist; the verb, the attach and the card are new |
| Google Sheets · Slides · Docs — comments on a sheet or a deck | the owner connects one file; its comments are read as said claims with author and time, the cell or slide as the locator | blocked on the Google OAuth client (VA-10) |
| email — approvals and details | an inbound address per thread; a forwarded mail is evidence, a reply from a named approver books the approval | blocked by Arc HB's "no email in either direction"; needs an inbound-only reopening — **the user's call** |
| meetings — where most decisions are taken | a person declares the decision in one sentence; the notes or transcript are uploaded as a document and the model *proposes* the decision candidates it finds, each confirmed or refused by a person | the said-claim door and document upload exist; candidate extraction is new, proposing only |
| presentations, PDFs, memos | uploaded as documents; the numbers in them checked against the warehouse | built (`/factcheck`; one quick model call per number) |

**The evidence envelope.** A claim's warrant is a run, a document, an attestation or another claim. The framework adds
two kinds — a *conversation* and a *meeting* — each a reference plus a hash plus an excerpt only when its author shared it.
The platform keeps meaning and pointers, never copies of people's conversations. Everything said arrives at tier `said`,
below measured, approved and declared on the authority ladder that exists. When what people said contradicts what the
data shows, the owner is asked once (CB-8, the departure gate's owner question).

**The model's one job here** is to propose: a decision candidate in a transcript, the figure a comment refers to, the
thread two messages belong to. A person confirms; only the confirmation is a fact.

**With contract terms landing in the warehouse by ELT** (the user, of the example in §4), constraints move from declared
to measured: an agreement bound like any table, its clauses properties — options checked against terms by code, a renewed
agreement restating the clause claim and reopening every decision that stood on it, a mission carrying a contractual
constraint its report checks, co-op money read as a measured input. The daily load means the two clocks matter: a
decision relies on the term as recorded on its date; the review reads what the warehouse held then.

### 3.3 · Implications, learning, and the readable why

**Forwards.** Actions run under the decision and name their version and cost (TC-2, TC-3). The expectation on each
option is scored on settled days against a comparison group or the metric's own calibrated history (D-2, D-3, live). The
outcome writes back to four places the model names: the relied-on claims' reference class, the playbook entry, the
author's track record, the action kind's grant. Consequences are then queries: the decisions that later relied on this
outcome, the mission report it moved, the Corrections view's row "a decision that went worse than expected".

**Learning for the next wave**, all by code: calibration by owner group; base rates by decision kind, so the next proposal
of that kind says "three past cases, effect −2 to −9%"; lessons at close; revisiting, which is the reopen loop.

**The why, in three layers**, composed from fields and never from a model's narrative: one line, the verdict; one
sentence, the why — fields that exist on outcomes, review dates, reopenings and amendments, and would be added to the
choice itself; the receipt — the numbers, the versions, the statements. The reader opens each layer by choice (CLARITY's
fold).

### 3.4 · The laws it keeps

Provenance on everything (no fact without a source, no model-authored fact) · two clocks · the authority ladder · invited
capture, never a crawl · a model proposes, a person decides · every departure through the gate · withheld is said · a
tombstone before a deletion · the organisation's ontology and its missions written by people only · no new store (the
Record holds decisions; the thread is a view).

### 3.5 · Coverage, against the user's points

| The user's point | Mechanism | State |
|---|---|---|
| a topic arises from any source | invited capture into a thread | inside the platform mostly built; Slack half; Google and email blocked |
| details from inside and outside the platform | the evidence envelope by reference, two new kinds | run · document · attestation built |
| discussion across channels | said claims and conversation evidence on one thread | said claims built from Home and Slack |
| decisions in meetings, approvals in Slack or email | one declared sentence; decision cards through the gate; the inbound address | gate and ✅ built; cards and email new |
| implications, positive or negative | outcomes against an honest baseline; write-backs; corrections | live (§5) |
| learning for the next wave | calibration by owner, base rates by kind, lessons, reopening | reopening built and proven (§5); the rest has three cases to wait for |
| every why readable if wished | three layers from fields | fields exist in part |

### 3.6 · The calls

Decided by the user: **B + C + A**; the framework before any build; Slack is the first door; contract data is in the
warehouse (so constraints are measured), left out of the first run. Open: an inbound-only email door (reverses Arc HB);
the Google OAuth client; the person-facing word for the vessel (inquiry · thread · case — a glossary decision); which real
decisions to rebuild by hand as the coverage test.

## 4 · A retailer of a given shape — an example, not a target

The user named a Berlin online beauty retailer as the example (*"we are not building our platform for this
organisation"*): 500+ people, many brands, 50,000+ products, 20+ countries from one warehouse; Databricks and Tableau; SAP,
Emarsys, a warehouse system, Google Workspace, Personio, Business Central, a contract platform whose data lands in the
warehouse daily; Slack. At that shape almost nobody decides about a product: people decide **policies** — a discount depth,
a safety-stock rule, a shipping threshold, a brand's terms — that then apply to thousands of rows. The decisions worth a
thread are policy decisions, their actions are rule changes in the operational systems, and their implications land across
countries and brands, which is what makes them measurable: twenty countries and many brands give every decision a natural
comparison group.

| Rhythm | Decisions | Where the record lives today |
|---|---|---|
| daily | price matches, stock allocation, campaign sends, replenishment | as rows in systems, not as decisions |
| weekly | promotion depth per country and brand, the CRM calendar, carrier mix, inbound priorities | a deck, a Slack thread, memory |
| monthly | margin against plan, spend moves, brand reviews on co-op and minimums | minutes in Docs, mail with the brand, the contract platform |
| quarterly, yearly | country launches, brand onboarding and exits, peak staffing, return and shipping policy | a board deck and a sheet |

| Their system | What the framework reads from it |
|---|---|
| Databricks | the warehouse: products, brands, orders, shipments, countries, suppliers, margin, **contract terms** — one connection, the ontology bound to it |
| Tableau | nothing directly; a figure is not a claim until measured through the platform's door |
| SAP · Business Central · Emarsys · the warehouse system | actuals, orders, prices, events, process stages, promises — read through the lakehouse; actions proposed by the platform, made by a person or under a grant |
| Personio | principals and groups — today an owner is free text |
| Google Workspace · Slack | the doors of §3.2 |

Three threads were walked in the talk (promotion depth for one brand in France; a supplier's lead time caught before the
stockout; moving a country's free-shipping threshold, superseding a two-year-old decision and reopening when the carrier
rate was restated) and are the shape the run in §5 took on LuxExperience.

## 5 · The run — six decisions from arising to learned, on the live install

**Method.** Six Flaconi-shaped decisions on the LuxExperience connection (Postgres `dcc63d83`; orders 2020-07-01 to today;
five platforms, 35 countries, 70 brands in three tiers, campaigns, prices, inventory, shipments, returns), each entering by
a different door, each declared through the live decision door with options, a persona who decided and who approved, one
dissent, the claims relied on, and an expectation with a segment. Every decision was **dated in the past** so the hourly
review fell due at once — the two clocks keep that honest (decided then, recorded today). Every stand-in for a door that
does not exist was recorded as a stand-in in the decision's note. Every write is marked `SCENARIO RUN 2026-10-25`.

**Pre-steps.** A second Slack bot, **Lux Analyst**, bound to the KPI Analyst agent on Lux (the only bot answered from
theLook); a GMV metric proposed by the platform and approved by the user (nothing on Lux added up, so the comparison group
had no metric to run on); a mission *Grow repeat purchase in North America* (active, with a gross-margin floor); two said
claims standing in for the Slack attach door and the inbound email door.

| # | Kind | Door | Decision (backdated) | Expectation |
|---|---|---|---|---|
| 1 | strategy | a sentence from "the leadership meeting", under the mission | expand clienteling to top customers in Canada and the US, 1 Jul 2026 | repeat purchase rate · Canada · up |
| 2 | marketing | Home finding → Decide (the server cited the finding's claim itself) | move a third of YOOX paid search to email and affiliate, 1 Aug 2026 | GMV · YOOX · hold within 3% |
| 3 | campaign | the user's Slack message to Lux Analyst (trace `49249607`: the grounding guard refused the narrative and showed the rows — 132 of 923 Mytheresa orders, 117k of 804k EUR from paid social in 90 days; attribution channel ≠ campaign channel on some orders) | pause paid social on Mytheresa for September, 1 Sep 2026 | GMV · Mytheresa · hold within 3% |
| 4 | trading | an Analyst inquiry (`fb1b7a55`: ultra margin 46.02→44.90%, concentrated on Mytheresa's July step; THE OUTNET had no ultra sales after April, so the decision moved to Mytheresa; the cause unexplained) | cap markdown depth for the ultra tier on Mytheresa, 1 Jul 2026 | gross margin · Mytheresa · up |
| 5 | finance | a returns memo, its numbers measured by SQL (the fact-check door spends a model call per number and was not authorised) | a 9.90 EUR return fee under 250 EUR to Canada and the US, 1 Aug 2026 | item return rate · Canada · down to 0.30–0.34 |
| 6 | supply | a forwarded email, as a said claim | raise safety stock for the ultra tier in Bologna, 1 Mar 2025 (snapshots end 2025-06-30) | weeks of cover · Bologna · up |

**Pass one (13:00 UTC, 2026-10-25).** The hourly sweep reviewed all five due decisions. Every one: *cannot tell — "a
whole query cannot be cut by a segment — its segments are its own"*. Defect 1 (§6). Meanwhile the **reopen loop was
proven unprompted**: marking the email-ROAS finding wrong (the Slack turn's rows had shown the attribution channel and the
campaign channel disagree) restated it, found the marketing decision that relied on it, reopened it, and the owner's
answer was kept with both versions — four versions of one decision, nothing deleted. The mission's report composed
(defect 2). Calibration by author gained rows in the user's name.

**The fix** (commit `212fa3d1`, branch `claude/decision-review-segment-cut`): `metric_time.measure_sql` / `run_measure`
take the named `part` beside `by`; a statement's grain table is filtered to `by = part` and to the rest of its group, the
statement's own arithmetic runs over each, two rows per window come back — the part and `_rest` — which is what
`scenario.comparison` sums. Tests: a CTE'd statement cut to one status and the rest adds up to the whole; the
decision-loop twin of the expression review reads the same +20% through a statement; mutant killed. Full unit suite
14,894 passed. Deployed: the live checkout detached at the commit, the API restarted with its twelve flags.

**Pass two (19:46 UTC, 2026-10-26, the first tick after the restart; the six re-declared).**

| # | What the review found | Verdict |
|---|---|---|
| 2 | **comparison ran**: YOOX GMV 89,252 against 90,830 predicted from the other four shops at YOOX's prior share 0.1742; inside the band | cannot tell — held |
| 3 | **comparison ran**: Mytheresa GMV 300,299 against 272,458; +27,841, **above** the band 3,081..52,600 — Mytheresa did better than the other shops with paid social off | cannot tell, because "hold" names no wanted direction (defect 5) |
| 1 | repeat purchase 0.153 against 0.151 from its own history; inside the noise | cannot tell |
| 5 | return rate 0.364 against 0.345 from history; the expected 0.30–0.34 missed above — the fee did not lower returns | cannot tell |
| 6 | no inventory rows in the 30 days after the decision | cannot tell — no rows (defect 6) |
| 4 | gross margin read **40.732 in every window**, an impossibility | "worse", unfounded — corrected by a person's outcome naming the cause (defect 7) |

"Cannot tell" is the right answer for most: one month on one slice is noisy and the review says so instead of inventing a
verdict. Method 4 on the September pause answered honestly too: *"only 1 past decision of this kind has a measured
outcome; 3 are the least an effect is read from."* The Record's Decisions view, under the Lux workspace, shows twelve
scenario decisions: the six first attempts with their failed reviews and the six re-declared ones, every version kept.

## 6 · Defects the run found

| # | Defect | Weight | State |
|---|---|---|---|
| 1 | a whole-SELECT metric could not be cut by a segment, and the metrics door accepts nothing else — so D-3's comparison review never ran on a metric defined today (it had passed on theLook only on grandfathered expression metrics) | the honest review was switched off | **fixed**, `212fa3d1` |
| 7 | a statement whose date table sits on the optional side of an outer join is not bounded by the window: Lux's gross margin (`order_items LEFT JOIN orders`, dated on orders) read the all-time 40.73% in every period — 703 of 273,917 items matched the filter, the rest stayed in the sum. Affects every period reading, the Briefing included, not only reviews | serious, pre-existing | **fixed** on this branch: `scoped_statement` refuses the grain table on the optional side of a LEFT, RIGHT or FULL join, by name |
| 2 | the mission report cannot read `repeat_purchase_rate`: "the date column orders.order_date is not on customers" — the period compiler reads the subquery's alias | medium | **fixed**, `216196c6`: a governed metric is measured by the period compiler |
| 3 | the Corrections view counts a *scored* expectation claim as a "restatement" (85 after the run) | copy / meaning | **fixed**, `216196c6`: only a changed statement is a restatement |
| 4 | the Record panel kept showing theLook's decisions after a workspace switch until a reload | UI | **fixed**, `216196c6`: the Record remounts on a workspace switch |
| 5 | a "hold" expectation that moves outside its band reads as *cannot tell*, since hold names no wanted direction — scenario 3 moved clearly above and the platform shrugged | verdict logic | **fixed**, `216196c6`: a fifth verdict, *missed* |
| 6 | a month-end snapshot table never falls inside a 30-day review window ending on the 30th | window vs grain | **fixed**, `216196c6`: whole periods of the reported grain, and the review waits for one to end |
| 8 | the expectation band is judged against the *prior window* ("before"), the verdict against the *baseline* — a "hold within 3% of the other shops" expectation is read against the wrong thing | semantics | **fixed**, `216196c6`: the band reads the verdict's baseline |

Three more, outside the review: an Analyst run's findings are not booked as claims (the inquiry held the run, `claims:
[]`), so a decision cannot cite what the inquiry found; a plain query's figure cannot be cited as a claim either (the
"Decide on a figure" door should book the figure as a reading); and the card "With an expectation · each can be scored"
overstated while every outcome said cannot tell. **All three fixed** (§9): the Analyst writes its deep report's receipt
and every receipt lands its claims on the run's inquiry (none of the 23 live inquiries with runs held one); a Briefing
figure is measured and booked as a reading when a decision is taken on it; the card says how many reviews reached a
verdict.

## 7 · What not to do

No new decision store · no crawl of mail, Drive or Slack · no model authoring a decision, a kind or a mission · no causal
claim on a company-wide total without a holdout or a comparison group · no money value without a confirmed currency · the
learning-from-runs study (PENDING 56) stays parked · no renaming for an analogy.

## 8 · Next, in order — the state on 2026-10-27 (what was built is in §9)

1. ✅ The open defects above, cheapest first: 5 and 8 together (the hold expectation and the band's reference), 3 (copy), 6
   (a window that ends on the grain's own boundary), 2 (the period compiler on a subquery), 4 (the UI refetch).
2. ✅ Arc TC (§3.59) as the plumbing under every reading — TC-1 to TC-5 built, each behind its own flag, off.
3. ✅ The intake doors, cheapest first: the Decide button on a Question's answer and on the Briefing; the Slack verb and
   decision card (a reaction attaching a message waits: a reply in the thread is already a said claim). **Waiting on the
   user:** the inbound email address (reverses §3.18) and Google comments (the OAuth client).
4. ✅ Decision kinds as declarations, then the platform's proposal of a declared kind under a mission (reading B) —
   composed by code from the kind, the mission and the Record; the agent's own proposal (a model writing options) is not
   built, and the law that a model proposes only is kept by the proposal having no model in it at all.
5. The falsifier stands: five decisions with a verdict other than cannot tell by 2026-12-05 (PENDING 57, §5.2), or the
   doors were the bottleneck, not the scoring.

Beyond §8, from §3, also built: the decision's reading from where it arose to what was learned (§3.1, §3.3), the
modifying decision, the evidence envelope's conversation and meeting kinds, and the meeting door (§3.2).

## 9 · Built, 2026-10-26/27 — the study continued, fully

The user, on 2026-10-26: *"Lets continue as per the decision framework study fully, back to back.. ask questions right
now if you have any.. else, go for everything without stopping."* Nothing below needed an answer first; the calls that
are the user's are listed at the end. Branch `claude/decision-review-segment-cut`.

| What | Where | The law it keeps |
|---|---|---|
| The six open defects and the three gaps (§6) | `216196c6` | a verdict says what was measured; a hold names no wanted side, so a move outside it is *missed*, never better or worse |
| A decision on a dashboard Question's answer cites what its run booked; on a Briefing figure, the figure is measured for the edition's days and booked as a *reading* with its own receipt | `fbbdb495` | the server cites, never the page; what could not be cited is said |
| `@bot decide: … — approvers @a @b` books a decision from a Slack thread citing the thread's answer; the card's ✅ is the named approver's approval, its ❌ a dissent | `fbbdb495` | a ✅ on an answer stays a verdict (TJ-4); someone not named cannot approve |
| Decision kinds, declared by people; a decision of a kind keeps its rules; method 4 reads past decisions of the same kind; under a mission the platform proposes a decision of each kind that moves the objective | `9f4da21b` | a model never authors a kind; the proposal is composed by code, booked by nobody until a person chooses |
| The decision read from where it arose to what was learned, forwards and backwards, its why in three layers; a modifying decision names the one it revises | `493ec8bd` | a view over the Record, never a new store; a stage with nothing in it says so |
| The evidence envelope's *conversation* and *meeting* kinds; the meeting door — the model proposes the decisions it finds in pasted notes, a person confirms or refuses each | `afcabccc` | invited, never crawled; a reference and a hash, the words only when shared; a candidate is never a fact |
| Arc TC-1…TC-5 — an answer names its agent's revision; an edit names its run; automations and monitors keep versions and replay as a dry run; alerts close; operations read across runs | merged from five branches | each behind its own flag, off, byte-identical off |

### 9.1 · Proven live on LuxExperience (2026-10-27, the API at `80472992`, every write marked "SCENARIO RUN 2026-10-26 (continued)")

| Defect or door | What the live install said |
|---|---|
| 5 · a hold that moved | Mytheresa, paid social paused for September, "hold within 3% of the other shops": **missed** — GMV +27,841 (+10.2%) against its comparison group, above the ±3% its hold allowed, "neither better nor worse" |
| 8 · the band's reference | YOOX, "hold within 3%": the band read against the comparison baseline; inside a noise of −21,090 to +17,930, wider than ±3%, so whether it held **cannot be told** — no longer a band read against August |
| 6 · month-end snapshots | Bologna's weeks of cover, decided 1 March 2025: thirty days (1–30 March) held none of its rows, so the review read **the month** (1–31 March) and found the snapshot; it still cannot tell, because only 2 earlier months hold readings |
| 2 · the mission report | *Grow repeat purchase in North America* measured: 0.1552 over 25 September–24 October against its history 0.1318–0.1894 — unmoved. The day before it said "the date column orders.order_date is not on customers" |
| 3 · Corrections | 5 restatements, down from 85 — scored predictions are no longer numbers that changed |
| 4 · the workspace switch | the Record's Decisions moved from Luxeperience's 17 to TheLook's 2 at the switch, no reload |
| a Briefing figure | a decision on the week of 12–18 October cites a **reading**: "GMV (EUR) read 158,815", measured, Final, warranted by its own receipt |
| a kind and its proposal | "a clienteling programme" (moves repeat purchase, must say what it expects) declared; under the mission it is proposed with: acting — "only 0 past decisions of this kind have a measured outcome"; not acting — "its own history predicts 0.1318 to 0.1894; the interval held 2 of 4 times". The first read quoted the mission's last *booked* report, written before the fix, and said the old error — fixed the same hour (`80472992`): a proposal measures the objective now |
| the reading forwards and backwards | the YOOX marketing decision reads from the Home finding it was taken on, through the two claims it stood on, the dissent and approvers, its first review's old failure, to the reopening loop settled with the owner's answer |

Not proven live: the Slack `decide:` verb and its card (they wait for a person's message in Slack — the bots run the new
code under a new supervisor), the meeting door (one model call), the Analyst's receipt landing its claims on its inquiry
(an Analyst run), and the TC flags (off; each is the user's switch).

**Not built, and why.** The inbound email door and Google comments wait on the user's calls. A Slack reaction that
attaches a message waits: a reply in a thread the platform filed is already a said claim, and the decision card carries
the thread as its evidence. The agent's own proposal — a model writing options — is not built: the proposal under a
mission is composed by code, which keeps "a model proposes only" by having no model in it. The meeting door was not run
live: it spends one model call, and none was authorised.

**Carried out the same day:** the renames; the trace's sub-pages admin-only; four TC flags on live (their first
receipts: the hub map measured 10 automations and monitors over 7 days and said *no runs* of 2; the log search read
12,902 runs and 28,372 lines back to 26 September; an object's changes read 4 edits and an action, each "which run made
it was not recorded" — all made before the flag); the email door built and on, refusing every mail until the install
sets its inbound domain and secret; Google comments on a named file built and on, refusing until the Drive-comments
card is connected (`docs/GOOGLE_OAUTH_CLIENT_SETUP.md`).

**Google comments proven live, 2026-10-27.** After the user's client was saved (the store had held a placeholder — now
refused by shape), the consent screen opened to their account, a withheld permission was named, and the Drive API was
enabled in their project, the user's own sheet was read onto the Mytheresa decision: 2 comments, each a said claim in its
author's name pointing at its cell ("132 of 923", "300,299 EUR"), later evidence on the decision's new version, read in
its inquiry under what it stood on — and the decision still cites nothing it did not cite when it was decided.

**The user's calls, answered 2026-10-27** (ROADMAP §6 item 54(f)): local branch; *the inquiry* as people's word; *missed*
stays; TC-2's read is an object's *changes*; four TC flags on; email inbound only; the Google client, guided; the trace's
sub-pages admin-only; the coverage test skipped. **As first listed:** The inbound email door (it reverses §3.18); the Google OAuth client; the person-facing
word for the vessel (the decision's reading avoids the noun); which real decisions to rebuild by hand; whether *missed* is
the word for a hold that moved; *timeline* now names both a dashboard piece (AP-4) and TC-2's object read; and each TC
flag's switch.

## Sources

Gartner's 2026 Magic Quadrant as reported by SAS, FICO, Aera, Sapiens, Decisions and FlexRule; Gartner's Critical
Capabilities abstract (27 Jan 2026); aeratechnology.com/platform and /what-is-agentic-decision-intelligence/;
palantir.com/docs/foundry/platform-overview/ and /ontology/overview-ontology-scenario/; cloverpop.com/decision-platform;
ibm.com/products/decision-intelligence; causalens.com; quantexa.com/platform; o9solutions.com; statsig.com/glossary/hold-out;
geteppo.com/blog/now-live-holdouts; support.optimizely.com (global holdouts); R. Moser, *Why Palantir Is Really a Decision
Company* (2026-04-28, as shared); `docs/DECISION_LOOP_STUDY_2026-10-24.md`; `docs/PLATFORM_2027_STUDY_2026-10-04.md` §G, §I,
§J, §K, §N, §P; the live install over HTTP on 2026-10-25 and 2026-10-26.
