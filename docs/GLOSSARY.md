# Glossary — the platform's vocabulary

**One word per concept. One concept per word.** If you need a word that is not here, add it
here in the same PR that introduces it.

This is the authority for names in code, UI copy, LLM prompts, flag labels and docs. The
plan that produced it — with the file:line evidence and the phased burn-down — is
`VOCABULARY_UNIFICATION_2026-08-01.md` (absorbed into `ROADMAP.md`; recoverable from git history). The
"don't use" column is enforced by `tests/unit/test_vocabulary_ratchet.py`: a baseline may
fall, never rise.

---

## Answering

| Use this | For | Don't use |
|---|---|---|
| **Deep analysis** | The autonomous multi-phase path — *both* the mode you pick and the record it produces (plural: deep analyses) | ADA, Agentic, "investigation" *in anything a user reads* |
| **Quick answer** | The fast NL→SQL→answer path | "Insight" as a mode, chat, `direct` as a user word |
| **Shape** | The kind of question, read from its words before any body runs — **describe** · **check** · **diagnose** · **survey** (`aughor/agent/question_shape.py`); the same four words at every door, in the model classifier, on the route receipt, in the report and the trace | "mode" or "intent" for the kind; `direct` / `investigate` / `explore` as the kind of a question (those are bodies) |
| **Survey** | A wide question answered by many cuts at once | "landscape", "wide wave"; `explore` in anything a user reads |
| **Knowledge answer** | A definitional answer from the knowledge base | `final_text` |
| **Overview** | The first-look tour of a newly connected schema | — (Home is Home; the catalog's per-table tab is "Summary") |
| **Exploration** | Background autonomous learning about the data | cartography |
| **Answer** | Any reply to any question | — |
| **Report** | The document a deep analysis or survey produces | `ada_report`, `ADAReport` |

**Deep analysis vs `investigation`.** "Deep analysis" is the only spelling users, prompts,
CLI output and flag labels may use. `investigation` survives as the **internal** spelling —
the `investigations` table, the `/investigate` route, the `investigation` job kind and the
ledger keys — because renaming a persisted identity orphans history. Backend identifiers
keep it; frontend identifiers and every user-visible string do not.

## Facts and artifacts

| Use this | For | Don't use |
|---|---|---|
| **Finding** | A discovered, evidence-backed fact shown to the user | **insight**, signal, pattern, fact, domain intelligence |
| **Narrative** | The prose enrichment attached to a quick answer | insight (the `_InsightResult` sense) |
| **takeaway** | The one-line summary of a single sub-question | insight (the per-subquestion sense) |
| **Issue** | A diagnostic raised by a guard or validator | guard classes named `*Finding` |
| **Statement** | A metric's SQL: a whole `SELECT` (CTEs allowed) that returns one row with the metric's value — every metric written since 2026-09-26 | "expression" or "formula" for a metric's SQL in anything a user reads |
| **Grain** | The date a metric's row counts on, written `schema.table.column` — the table because a statement is cut to a range by filtering that table | "time column" in anything a user reads |
| **Claim** | The atom of the Record (the 2027 study §G, phase 1 — `aughor/record/claims.py`): a dated statement about the business that carries its warrant, its owner, its tier on the authority ladder, its status (Final · Provisional · To date), both clocks (`as_of`, the data's date; `recorded_at`, the booking's) and, once counted, how often its class has been right. Kinds: observation · finding · reading · definition · hypothesis · prediction · said · cause. A statement a person verified — the word's earlier, narrower sense — is a claim at tier `approved` or with an attestation warrant | assertion; "fact" for the stored thing; a model's own confidence as a number |
| **Prediction** | A claim of kind prediction: a metric, a direction, an interval at a stated coverage, the method that produced it and the date it settles on; scored by code when its range is Final, never by a judge | forecast (as a stored thing — the gate's law 5 keeps the word for what never departs unscored), estimate |
| **Decision** | The organisation's choice, booked as a by-product of accepting a recommendation, approving an action or declaring it in a sentence (`aughor/record/decisions.py`): the question, the options, the one chosen, the claims relied on as recorded at that moment, dissent, and the expectation booked with it; the review date set at the moment of deciding | recommendation outcome (that is the older playbook record it supersedes), choice log |
| **Decision candidate** | A decision the model proposed from a meeting's notes a person brought (`aughor/record/meetings.py`): what was being decided, what was chosen, the options, who said so and the line it was read from — a proposal, never a fact, until a person confirms it (then it is that person's decision, dated the meeting's day, the meeting its evidence) or refuses it (kept, with why). A *conversation* or *meeting* warrant is where something was said: a reference, a hash of the words read, and the words only when their author shared them | extracted decision, AI decision, suggestion |
| **Decision kind** | A kind of decision the organisation declares — a price change, a budget move — saying who must approve one, whether it must say what it expects, when it is reviewed, the authority ceiling for what it runs, and the metrics it usually moves (`aughor/record/kinds.py`). Declared by people only, superseded never deleted. A decision of a declared kind keeps its kind's rules at the door, and past decisions of the same kind are the next one's base rate (method 4); under a mission the platform proposes a decision of each kind that moves its objective, composed by code | decision type, category, template |
| **Outcome** | What became of a decision, measured on its review date on settled days: the actual against the expectation AND against the metric's own baseline, with a verdict (as expected · better · worse · missed · cannot tell — *missed* is a hold that moved outside its band beyond the baseline's noise: it named no wanted side, so it is neither better nor worse) and what was written back. A relative band is read against the same baseline as the verdict | result, impact |
| **Inquiry** | The durable object a deep analysis runs inside (the 2027 study §G and §I, phase 2 — `aughor/record/inquiry.py`): the question, who opened it (a person · a monitor · a restated claim · a review), its runs with their verdicts, its hypotheses as claims with their state (open · supported · refuted · abandoned), what it established, what stays open and what would settle it, its state (open · waiting · closed) and the date it wakes without being asked. A refuted hypothesis on it is memory, read before the next run on the connection proposes its own | investigation (the frozen name of one run), case, thread, ticket |
| **Run verdict** | How a run ended, typed and booked for every run: answered · contradicted · no data · no definition · withheld · out of budget · tool failed — never an empty result, so a failure and a true negative never read alike | error, "no results", status alone |
| **Scenario** | A projection FOR a decision, an inquiry or a mission (the 2027 study §L, phase 3 — `aughor/record/scenario.py`): its assumptions, each with its source and whose it is; the predictions made under it, each carrying its **method** on the ladder (identity · declared · history, then intervention · simulation · learned) and taking the weakest method on its path as its tier; its limits in words. A scenario with no decision attached is a toy | simulation (as the stored thing), forecast (for the stored thing), what-if |
| **Method** | How a projection was produced, named from the scenario ladder, and what it must say: identity says what it held fixed; declared says whose assumption it is; history says its interval and its backtest error on this metric. A prediction's method is what calibration is counted by | model (for the method), algorithm |
| **Authority level** | What a declared action may do on a scope, L0–L5 (the 2027 study §M, phase 4 — `aughor/actions/authority.py`): observe · recommend · prepare · execute with approval · execute within policy · autonomous. Computed from the record of verified executions and outcomes, never from a setting; the lower of the ceiling a person set and what the record earned; an irreversible action never passes L3 | autonomy level (the older per-connection ladder in `memory/trust.py`, which it supersedes for actions), trust level, permission |
| **Graduation receipt** | The ledger entry that grants L4 to one action on one scope, naming the record it was earned on: the approved executions whose verification passed, no failed verification, and an outcome inside expectation on a decision that ran the action. Authority is granted on a receipt the way a flag graduates, never on a demonstration; a demotion is the same kind of entry in the other direction, booked automatically on a failed verification | promotion, upgrade, "trusted" |
| **L5 receipt** | The ledger entry that grants L5 — autonomous within a mission — to one action on one scope (the 2027 study §M; the close-out's C6, `aughor/actions/authority.grant_l5`). A person books it, and only on a record that earns it: L4 held, twenty verified executions, no failed verification, a reversible action with its undo declared, and an active mission on the scope whose ceiling sets the action at L5. The agent that then chooses among the L5 actions toward the mission (`aughor/actions/autonomy.py`) picks by method 4's measured effect on the objective, with the parameters the mission's owner wrote, one action per review period, through the same approval gate as any execution; a demotion takes the level | full autonomy, auto-pilot, "trusted agent" |
| **Verification statement** | The read a declared action names that proves its change took effect, run through the ordinary query door after dispatch and recorded on the action's ledger entry as passed · failed · unavailable. A side-effect action with none cannot be declared; one with no undo is declared irreversible by name | check, post-condition, assertion |
| **Mission** | A standing objective a person gives the platform (the 2027 study §J, phase 5 — `aughor/record/mission.py`): what to achieve (a metric, a direction, a target, by when) and what not to damage (constraints with limits), its scope, its owner — a person; a mission without an owner does not run — its budget (interruptions a week, spend a month, an authority ceiling per action kind), what it watches and its review cadence. People write missions; a model never does. Judged by whether the objective moved against its own baseline and at what cost, never by activity | goal, OKR, priority (the `IDEAS.md` 21 word it grew from), workflow (that is an automation — how a mission acts) |
| **Mission report** | What a mission is judged by, composed from fields by code on its cadence: the objective against the baseline the metric's own history predicts FIRST, then whether each constraint held, what it watched, what it opened, what it decided and what became of each, what it cost (interruptions used of its budget, actions by level, demotions, spend — said as not counted when nothing prices it) and the lessons. "Nine findings, one decision, no measurable effect yet" is a valid report | summary, status update, dashboard |
| **Bearing** | Triage's first term: how far a departure is about an active mission — 1 on its objective's metric, 0.7 a constraint's, 0.5 something it watches, 0 when no active, owned mission bears on it. Read from the missions people wrote, written on the departure's row, and the charge against the mission's own interruptions a week | relevance, priority score |
| **Correction** | A record of something the platform was wrong about, read under one heading (the 2027 study §N, phase 5 — `aughor/record/corrections.py`, `GET /record/corrections`): a restatement, a refuted hypothesis, a missed move, a prediction outside its interval, a decision worse than expected — each with what was believed and what replaced it | error log, history, audit trail (for this view) |
| **Missed move** | A move a person found by asking that nothing had flagged — the review of a miss (`monitors/missed.py`, idea 8) books it as a Correction when, and only when, the day was a move by the series' own spread and no watch that could have fired did | false negative, gap |
| **Prior** | A number a pack ships before this install measured it — a watch's normal range, a play's base rate (phase 6 — `aughor/packs/priors.py`). A prior carries the installs or public datasets it was measured on, or says none (`unmeasured: true`), and the static gate refuses one that does neither; an unmeasured prior is shown as such, never as a range. An install's own measurement replaces it as soon as one exists | default, benchmark (that is a sane range with a published source), threshold |
| **Template** | A declaration a pack ships for a person to write something from — a mission template (an objective, constraints, a cadence) or a scenario template (a method on the ladder, its formula and the inputs a decision varies). A template never becomes a mission or a prediction on its own | preset, blueprint, recipe (that is a metric's) |
| **Shopping list** | What the connected data cannot answer for the industry's usual questions, and what would unlock each line (`IDEAS.md` 10, phase 6 — `aughor/packs/onboarding.py`, `GET /onboarding`): a pack's expected object no table matched, a pack metric whose role the binding leaves unresolved, a mission template whose metric nothing measures — each with the plays, questions, links and processes that wait on it. *Confirm, do not configure* | gap analysis, requirements, backlog |
| **Proposed term** | A pack's word for a thing, written into a connection's vocabulary the day the pack is bound (the 2027 study §P, phase 6; the close-out's C7 — `aughor/packs/connect.py`, `ontology/vocabulary.py` source `pack`): a metric's title and aliases on the metric, an object's name and aliases on the table the map matched it to. Below a person's word and this install's own mined evidence, above a model's guess; it widens what a question can match at once and reaches no prompt until a person confirms it, which makes it theirs in place. A decline is a tombstone the next bind cannot resurrect. The same word for an alert from a prior's band: a monitor proposal with its backtest on this connection, armed only by a person's accept | suggested synonym, auto-synonym, default alert, "pre-configured" |
| **Onboarding hours** | Onboarding's one measured number and a release gate: hours from a connection's first ontology build to the first claim a decision on it relied on, under a day to pass. "Not yet" — never a number guessed from activity — before any decision relied on anything | time to value, activation |
| **Service principal** | An outside agent's identity on this install (phase 7 — `aughor/security/service_principals.py`): minted by a person, presented as `X-Aughor-Service` and `X-Aughor-Service-Key`, named `service:<name>`, held to the organisation's agent policy, revocable, scored by what became of the entries it booked. Never a person, never the platform's own agent | API key, bot user, machine account |
| **Grant** (of a service principal) | What narrows the agent policy for one service principal (Arc ED, ED-2 — `aughor/rbac/principal_grant.py`): the *areas* it may work in, the entities it may read, the declared actions it may propose and the connections it may name, set by a person when minting it. It only ever narrows the policy; a list left empty does not narrow there. Held behind `security.principal_scopes`; its contract is cut to it | scope (a connection's or a schema's), permission, role |
| **Area** (of a grant) | One kind of work a grant may name, written `<what>:<verb>`: catalog:read · objects:read · actions:propose · analysis:run · automations:run · ledger:read · ledger:write. Each API route belongs to one; a route in none is closed to a principal whose grant names areas | scope, permission |
| **Agent contract** | What any agent — the platform's own first, an outside vendor's through the doors — is held to: the seven duties and what each books, the typed verdicts, what an entry must carry, the laws at the door (`aughor/kernel/contract.py`, rendered to `docs/AGENT_CONTRACT.md` and held equal by a test) | agent spec, persona (retired), system prompt (that is one duty's instructions, not the contract) |
| **Ledger API** | The Record's own door for outside tools, `/ledger/v1`: post a claim with its warrant, read claims as recorded on a date, read restatements since a cursor, subscribe to events out, export the ledger as lines. One of the two doors; the MCP server is the other | REST API (as a name for this), write API, webhook API |
| **Event catalogue** | Every kind the kernel journal is written with, each with what its payload carries and its category on the governance feed (`aughor/kernel/events.py`, `GET /ledger/v1/events/catalogue`), held to the source by a ratchet: a new kind is a decision written down, never a string that appeared | event schema, topic list |
| **Events out** | A subscription's delivery of the Record's events — a restatement, a refutation, an outcome, a scored prediction, a mission report, an authority change, a pack demotion — as a webhook, through the departure gate like every other exit (`aughor/record/subscriptions.py`); a held delivery is said with why | push notifications, event stream, webhook feed |
| **Registered method** | A forecaster, estimator or simulator registered with its declared backtest and run only as a foreign MCP tool through the one door (`aughor/record/methods.py`); on the ladder beside the four built methods, never inside the process | plugin model, custom forecaster, integration |
| **Pack kit** | The door a pack author uses instead of writing into an install's tree: the guide read from the models, a check that runs the static gate without writing, an upload that writes a passing pack as a draft with its provenance (`aughor/packs/kit.py`; `GET /packs/kit`, `POST /packs/check`, `POST /packs/upload`). Declarations only — never code | SDK, marketplace, app store |
| **Sign-in (to an MCP server)** | A person's OAuth authorization of this deployment to call a foreign MCP server that authenticates by OAuth (the 2027 study §Q; the close-out's C9 — `aughor/mcpservers/oauth.py`): begun from the server's row, finished when the browser returns to the callback, its token set stored encrypted on the row and never returned — a read says only that someone signed in and when. A machine identity is the other mode (client credentials) and needs no person. A server nobody signed in to refuses with the door's name; it never guesses or hangs | OAuth connect, "authorize", token (as the stored thing) |
| **Unread source** | A source a pack cites but nobody read where the pack was drafted — reached through an index or a summary, a paywall or a blocked network (`PackSource.unread`; the 2027 study's close-out, C8). What the pack says of it is a report of a report: its `notes` say how it was reached, it carries no figures (a quote nobody read cannot be verbatim — the static gate refuses one), and a pack citing one cannot be promoted to active until a person has read the document, carried its figures in the words they were published in and dropped the flag. The B2B SaaS draft cites six | secondary source, "per reports", citation needed |
| **Measured record (of a pack)** | How often a pack's claims held across the installs that measured them, by state, with the installs' count and the pack's status journal (`aughor/packs/record.py`, `GET /packs/{id}/record`); the listing IS this record, and a pack is demoted by it — ten measured, half refuted — or by a person with a reason | rating, stars, reviews |
| **Organisation scope** | The layer between a connection's own words and the install's: a metric scoped `org:<id>`, the glossary's `organisations` section, a Briefing read by its organisation (the 2027 study §E item 2 — the organisation first, the connection second; `aughor/semantic/metrics.org_scope`, `aughor/semantic/glossary.ORGANISATIONS_KEY`, `GET /briefing/organisation`). Every connection of the organisation reads it; no other organisation does | tenant (the install's word for isolation), workspace (a person's selection of connections), global (the install's layer) |
| **Aggregate** | What an install may share across installs when a person turns `aggregates.share` on: pack records, base rates with n, normal ranges (the band for a share metric, only the relative width for any other unit), method backtests — never a connection id, a claim's text, an object's key, a name or an absolute level (`aughor/packs/aggregates.py`). Off by default; nothing leaves and the door says so | telemetry, benchmark data, usage analytics |
| **Briefing** | The periodic narrative artifact, and its subscription | brief (as the artifact), digest, Intelligence Digest |
| **What we know** | The Briefing's standing view: everything the platform has learned, not tied to dates (Arc BR, ROADMAP §3.48) | Standing, "history" (both survive as internal names only) |
| **Range** | The days a Briefing covers: a preset — Day, Week, Month, Year, Month to date, Year to date — or a custom first and last day | window (in anything a reader sees) |
| **Current · Last (period)** | The Dashboard's periods: the day, week, month or year under way, and the one before it — each read only over days whose data has arrived (`briefing/ranges.py` `EDGE_PRESETS`) | latest (it meant the newest *settled* period; the Briefing's presets keep that meaning) |
| **Data through** | The newest complete day every measured table has rows for, read from the warehouse when a current or last period is resolved; a day still loading is left out, and the range says so (`ranges.data_edge`) | as of (the day a range is read), freshness |
| **Statement line** | Where a metric sits on its industry's income statement — gross sales, discounts and returns, net sales, cost of goods sold, gross profit, … profit — then the figures that drive it; an industry declares its `statement` in `industry.json`, naming a line in its own words where it has them (`briefing/reading_order.py`) | category, group |
| **Note (on a dashboard)** | A person's own words on their dashboard — a Markdown subset, up to 2,000 characters — typed by them, stamped by the server with who kept it and when, measured by nothing and cited by nothing; a model may move, resize or take one off, never write one (`web/lib/cockpit/catalog.ts`, `cockpit/versions.stamp_notes`) | text card, comment, annotation |
| **Image (on a dashboard)** | A file a person uploaded into the connection's dashboard volume and placed by its object id, with a caption; shows who uploaded it and when, no period and no comparison; one the reader may not see stands as its caption and says why (`cockpit/images.py`) | picture, attachment, static card |
| **Question (on a dashboard)** | A question a person keeps on a dashboard, answered by the agent the Data Canvas uses — on a rhythm (daily, weekly by default, monthly) or only when asked — each answer a full run for the last complete period against the one before, kept and shown as the Data Canvas shows one: figures, summary, why, what it could not see. Opening the dashboard never asks. Its rhythm is an automation; its answers are filed under its own session, `question:<id>` (`aughor/dashboards/questions.py`, PENDING 54) | saved question, standing query, alert (a monitor watches a condition; a question is answered) |
| **Size (of an element)** | How much of a section's grid a card, note, image or piece takes: on a section's twelve columns and its rows of 40 px, a width of 1 to 12 columns by a height of rows, each moved one grade at a time (Arc AP; the user, 2026-10-10: *"adjusted one grade point at a time"*), within a minimum and maximum its kind sets. The six names — small, wide, tall, large, full, hero — are the spans a v4 dashboard says, drawn as they were. Never pixels (`catalog.ts` `SIZES`, `GRID`) | span, layout, dimensions |
| **Briefing switches** | Which of the Briefing's sections a person shows, in what order, and which dashboard of theirs rides with it — six sections, plus the verdict's two parts (its measured figures, what the findings found) that hide on their own and move with it; a per-person preference (`briefing_sections`); the content of a section is the platform's, and a send carries the platform's Briefing, not the switches | layout, customised briefing |
| **Published (dashboard)** | A dashboard a person made readable to the members of a group they belong to, or the holders of a role, under their name; a version, as unpublishing is; a reader sees it under "Shared with you", read-only, for a period of their own, and may start a dashboard of their own from it (`cockpit/sharing.py`). A published dashboard is an **App** (§6 item 50(c)) — what a reader sees has said *App* since OC-4 (2026-10-09): *Publish as an App*, *Apps shared with you* | shared, exported, broadcast |
| **Final · Provisional · To date** | A figure's status: its days (and, for a cohort, its outcome) have settled; have not yet; the range is still under way | preliminary, estimate, partial |
| **Dashboard** | A standing set of cards a person keeps watching for one area — returns, pricing. It is theirs alone, and they keep as many as they like, in the Dashboards tab beside the Briefing; each is composed from a spec — tabs, sections and cards shown by a condition (Arc CT, ROADMAP §3.50). Until CT-7 the Briefing held one unnamed dashboard per connection, and a Data Canvas could hold one. Named *cockpit* until 2026-10-23 (the user: *"lets rename cockpits entirely as Dashboards - externally and internally"*); the names already stored keep `cockpit` (see *Names that are frozen*) | cockpit, board (in anything a reader sees) |
| **Card** | One measured thing on a dashboard — a figure, a chart, a watch or a note — kept in the card store with its SQL, its limits and its history. A dashboard's spec holds a card's id and nothing about what it measures | tile, widget |
| **Process board · objects table · object detail · action button** | The four pieces of a dashboard bound to the ontology (Arc OC-4, ROADMAP §3.56), each naming what it reads by id: a declared process (its stages, each promise and its open-and-overdue objects); an entity or a segment of it, a page of objects at a time; the object chosen in the table a detail follows; a declared action, run on that object or proposed for approval. A person places them by hand ("From the ontology"); a model may arrange one and never adds one. Unlike a card, a piece holds no SQL — the ontology is its definition | widget, panel, tile |
| **Section** | A titled group of cards and pieces inside a dashboard — or, laid out in columns, rows or tabs, a group of sections of its own, which may go untitled (Arc AP-4). One may hold nothing yet while it is built; a reader is drawn nothing there | group, block (in anything a reader sees) |
| **Set (on a dashboard)** *(Arc AP)* | A named group of objects that pieces read. It is an entity or one of its segments, narrowed by the author's conditions — each comparing a property with a value typed or with one of the dashboard's values (Arc AP-8) — by a filter column, or by a link from a chosen object, and it may start from another set. It may then get its objects' *linked objects* — the customers of the waiting orders — and be *combined* with another set of the same objects: either, both, or but not (Arc AP-8b). It says what reads it. A set kept for everyone is a *segment*. A set is one kind of *variable* | object set, query; traverse, union, intersect, subtract (in anything a reader sees) |
| **Chosen · ticked** *(Arc AP)* | The object a reader clicked in a piece, and the objects they ticked. Each is named and read by other pieces; the reader's own, never kept in the dashboard | active object, selection, selected objects |
| **Value (on a dashboard)** *(Arc AP)* | A number of days, a number, words or a day that sets and queries read — *Window: 14 days*. It *comes from* its author, set once; the reader, on the page, from the choices offered or as they type — kept in their own browser, never in the dashboard; how many objects a set holds; or a property of the object a reader chose (Arc AP-8). A value is one kind of *variable* | parameter (that is an action's; in SQL a value is bound as one underneath) |
| **Variable** *(Arc AP-8)* | What a dashboard's pieces and queries read that is not fixed in them, listed together in the builder's Variables pane: its values, its sets, and what its pieces output (a row chosen, rows ticked, a figure clicked) — each saying where it comes from, what it holds now and what reads it. A query of your own reads a value as `{{name}}`, bound by the engine and never pasted into the statement. A value is days, a number, words, a day, *yes or no* or a *list*; it comes from you, the reader, a set's count or *sum*, the chosen object, or the first value of a *query* of your own (AP-8c) | input, control, dynamic filter |
| **Action buttons** *(Arc AP)* | A piece of up to six buttons, each running a declared action with every parameter taken from one source: the chosen object, the ticked ones (one run each, at most 50), a set's objects (asked first), the form, or a fixed value. Every run goes through the action's own door, so its criteria, risk and approval hold on each. Unlike the action button in an object detail, which runs on the object the detail shows | button group, action bar |
| **Drawer · form** *(Arc AP)* | What opens over a dashboard: a drawer beside the page — the pieces it holds, opened when a reader chooses the object it opens on and closed by letting go of it — and a form in front of it, asking an action's values before it runs | overlay, modal, popup, sheet |
| **Object list · map · timeline · choose one · search** *(Arc AP-4)* | The pieces the builder's picker adds, each reading an entity or a set as a table does: a queue of objects as cards (each called by a property — or its key, "Order 63981" — a number beside it, a mark under it); each object placed by its latitude and longitude; each a bar from one moment to the next, one still open drawn to today; one object found by the words typed, for the pieces that follow it; and words that narrow every piece over an entity, for that reader only | widget, card list, geo chart, gantt, dropdown, search bar |
| **Shape (of a dashboard)** *(Arc AP)* | What a dashboard is for — a queue, an overview, a map, one object's page, a timeline — read from the ontology and offered with why | template (that is a pack's), layout |
| **Your own query** *(Arc AP-7)* | A card that reads a person's own SQL — one table, several or another schema — shown as a table, a figure or a chart as they set it up: what runs along the bottom and in what buckets, what is summed, what splits it, stacked, side by side or as shares. It reads the tables straight, so it says so | custom SQL widget, SQL tile, native query (in anything a reader sees) |
| **Preview as · checks** *(Arc AP-6)* | Two ways a builder reads a dashboard before others do: *preview as* a group — read as the builder and a member of that group would, so only ever less, with what a row policy or a mask holds back said — and the *checks*: how many of its elements read cleanly, how many are still reading, and the ones to fix, each with why | impersonate, view as, log in as (a preview never reads as the group alone); lint, validation (that is the keep door's) |
| **Within · Over · Unmeasured · Withheld** | A card's status as the host says it to a dashboard: inside its limit; past it; not measured, or with no limit to be past; not for this reader to see. A withheld card stays in its place and says so | breached, alerting; "hidden" for withheld (a card hidden by its condition is *waiting*) |
| **Run** | One execution of anything | session, episode (a step *inside* a run is a **step**) |
| **Trace** | The telemetry kept ABOUT one run — the `session_events` it wrote, reconstructed | run (a trace is the record, not the execution) |
| **Trajectory** | One run's trace with its steps' tool, arguments and results, its answer, and the reward attached to it — the one record the exporters read (Arc TJ, ROADMAP §3.47). A trace without a reward is not a trajectory | episode; rollout (a rollout is the act of producing one or more trajectories for one problem, not the record) |
| **Layer** | What a dataset — a schema or a table — is for: Business, Integration, Raw, Reference, Uploads or System. Proposed from its signs with the evidence, set by a person; it decides what the Explorer does with the dataset on its own initiative (`aughor/ontology/dataset_layers.py`; the exploration principles §5) | role (a metric binding's and a person's access), tier, zone, "medallion" |
| **Maturity** | Three readings of a dataset — Structure, Questions, Time — each a share or "does not apply" with the reason, drawn as three vertical bars and a number (`aughor/explorer/maturity.py`) | coverage (the ontology's mapped share of tables), freshness |
| **Off (for analysis)** | A schema or table a person turned off: never explored, never queried by Investigation or Quick analysis; the SQL editor still reads it. Stored as an exclusion with its reason (`ontology/visibility.py`) | hidden, disabled, deleted |
| **Segment** | A saved, named filter over an entity's rows | ObjectSet |
| **Query template** | A reusable governed SQL template | OntologyAction |

## The ontology

The nouns of the business model the platform runs on (Arc OC, ROADMAP §3.56). *Entity* is the word a person
reads and the word the code uses (§6 item 50(h)); an **object** is one of its members. A row marked *(OC-n)* names
a thing that wave builds — the word is fixed before the thing exists, so it arrives with one name.

| Use this | For | Don't use |
|---|---|---|
| **Entity** | A kind of business thing — Order, Customer, Shipment — with its key, the rows that are its objects (its backing: a table or a keyed SELECT), its properties, its lifecycle and its segments (`OntologyEntity`). The builder proposes one per table; a person declares, merges, absorbs and names them | object type (in anything a reader sees), class, model, table (a table is an entity's backing, not the entity) |
| **Object** | One member of an entity — order 8821 — read live from its source by its key, never copied; its page says what is known about it, its segment and its entity | instance, record (that is the Record, the ledger), row (in anything a reader sees, where the object is meant) |
| **Property** | A named value of an entity's objects: a source column, an expression, a computed property, one a binding supplies or one the edit layer sets | attribute, field (in anything a reader sees) |
| **Link** | A named relation between two entities, its cardinality measured on the data and its name read both ways (`api_name`, `reverse_api_name`; the model is `OntologyRelationship`) | edge, join (that is the SQL that reads it); relationship in new copy |
| **Binding** | A further source an entity's properties are read from, joined on its key — *static* (one row per object), *timeseries* (many over a clock) or *detail* (many with no clock, read only through its rollups). The first binding is the entity's backing (`Binding`) | mapping, source mapping, enrichment |
| **Part** | An entity marked as part of another — an order's lines — listed under its parent and still an entity with its own objects, links and pages; the mark holds only while the parent binds the part's table (`OntologyEntity.absorbed_into`, `ontology/parts.py`) | child, sub-entity, nested type |
| **Process** | The stages one entity's objects pass through, each anchored to a moment or a state and measured on the data, with an owner (`Process`). A process may say how an object **leaves** it — a property holding one of some values (an order cancelled, `ProcessExit`): one that left is no longer open, and never overdue | workflow (that is an automation), pipeline, funnel |
| **Stage** | One step of a process, anchored to a date or timestamp property or to lifecycle states; a stage anchored to a state is counted, never timed, and carries no promise (`ProcessStage`) | step (a step is inside a run or an automation), phase, status |
| **Promise** | What the business promises about reaching a stage — within N days or hours of the previous one, or by a per-object deadline — measured as kept, broken, open and open-and-overdue; from it the object door derives a `late_<name>` segment, a lag property and a breach-rate metric, and — for a dashboard — an `overdue_<name>` segment of the objects still open and already past it (`Promise`) | SLA, target (that is a metric's), KPI |
| **Expectation** | One statement a table's data must meet — a column never empty, a key never repeated, a value in a list or a range, the newest row recent enough, the row count or the set of values not drifting (Arc ED, ED-3 — `aughor/quality/expectations.py`; the code's `quality.rules.Rule`). Measured read-only by an automation step, it records how many rows break it, never which, in the one quality store; one that could not be measured is said, never counted as failing. The table's *health* is its expectations' latest verdicts. The decision 2026-10-24, the user's: *Expectation* | rule (that is a business rule), check (claim verification, and a question's shape), test, assertion |
| **Rule** | A named, owned definition the business holds and its data does not — a value set ("DACH is DE, AT and CH") or a condition — measured for the objects it admits, read as a segment of its entity (`BusinessRule`) | policy (that is security's), business logic, filter (that is a segment's SQL) |
| **Impact** *(OC-5)* | A declared effect of one promise on another — late dispatch on late delivery (`Impact`, `ontology/impacts.py`) — with its mechanism — *formula* (exact), *influence* (measured: an association with its *n*, lag and window) or *validated* (an intervention or a decision's outcome showed it); worded by its mechanism at the departure gate | driver, cause (unless validated), correlation |
| **Declaration** | A person's — or a pack's — statement of an ontology element: an entity, a link's name, a binding, a process, a promise, a rule, a segment, an action. Stored in the overrides tree with who made it; from OC-1 every save and withdrawal is a version with a stable id | override (the store's internal name, `data/ontology_overrides/`), config, setting |
| **Draft (of a release)** | The ontology's changes waiting to be published (Arc OC-2, `data/ontology_overrides_draft`): what the Ontology screens show, laid over the published declarations, until a person publishes or discards them; each change classed ERR · MEANING · WARN · SAFE. The explorer's proposals wait here. Not the explorer's *draft record* (ON-7b), which is its memory of what it proposed and what a person withdrew | staging, pending changes, sandbox |
| **Release** | A numbered, recorded set of declaration versions for one scope, with a hash (`<connection>/<schema>@<n>`, `ontology/release.py`): what every consumer reads, and what a claim names in `definition_version`. A person publishes the draft as the next release, refused while a change would break something; a release that changes a meaning restates the claims computed under the one before. Release 1 is what was in force when releases were turned on | version (that is one element's), snapshot, deployment |
| **Edit layer** | The values people set on objects through declared actions, kept beside the source and merged at read; the source row is never touched (`aughor/actions/overlay.py`). From OC-6 it keeps history and transitions and is visible to criteria | write-back, overlay (the internal name), correction (a correction of a source value is refused — PENDING item 31) |
| **Platform-owned entity** *(OC-6)* | An entity whose objects the platform itself keeps — a case, a review, an assignment: an App's unit of work no source holds — changed only through declared actions, each change kept (§6 item 50(b)). No customer row moves | internal table, app data, system of record |
| **Row policy** *(OC-7)* | A group and the conditions on an entity's own properties that its members' objects meet (`RowPolicy`, `ontology/security.py`, flag `ontology.security`). Once an entity declares one, a reader sees only the objects a policy of one of their groups admits; a reader in none sees none and is told which groups would | row-level security, RLS (in anything a reader sees), filter (that is a query's) |
| **Sensitive property** *(OC-7)* | A property only the groups it names may read (`Sensitivity`); for everyone else its value is *masked* — empty, never guessed — and a query that would filter, group or measure by it is refused. When an agent acts for a person, the rows are those both may see and a property is masked if either may not | PII flag, redacted, hidden (a masked value is said, never silently dropped) |
| **Contract (of a release)** *(OC-8)* | A release served to outside programs as JSON Schemas of each entity's objects and each declared action's parameters, and the same as TypeScript declarations (`ontology/builder_doors.py`, `/ontology/v1`, flag `ontology.builder_doors`). A program reads it, lists objects and *proposes* an action; a person approves every proposal | SDK, client, API spec |
| **App** | A published dashboard — versioned, pinned to an ontology release from OC-2, shared with a group or role — read inside the Dashboards tab (§6 item 50(c)); the dashboard is where it is made. The copy moved from *published dashboard* to *App* with OC-4 (2026-10-09), its wording shown first and approved; an App holding pieces says the release it was pinned to and what changed since | application (in anything a reader sees), cockpit, workspace (a person's selection of connections), module |

## Acting

| Use this | For | Don't use |
|---|---|---|
| **Action** | A governed write to the data | kinetic |
| **Notification** | An outbound message (webhook, Slack, Jira) | Action Hub |
| **Approvals** | The queue of actions awaiting a human | the kinetic "inbox" (one **Inbox** exists: recommendations) |
| **Outbox** *(OC-6)* | A declared action's calls to other systems, kept as rows and delivered by a worker under a lease; retried by why a call failed, and one that got no answer is checked by the action's own verification before it is ever sent again (`actions/outbox.py`, flag `actions.outbox`). A call no retry will deliver waits for a person — *Retry* or *Dismiss* | queue, job, dead-letter queue (in anything a reader sees: it *waits for a person*) |
| **Monitor** | A watch-a-metric rule | — |
| **Recovered (alert)** *(Arc TC, TC-4)* | The alert a monitor writes on its first check back within its limit after a warning or critical from a rule with a limit (threshold, anomaly, drift, freshness): it names the alert it closes, when that fired and the value that came back, and closes every alert of that monitor since the last recovery. It is recorded and listed, never sent as an alert, and the next alert after it opens a new one. A check that files nothing says *within its limit* or *suppressed by its grace period*, never "no alert" for both (`aughor/monitors/recovery.py`, flag `monitors.recovery`) | resolved, cleared, OK; "in limit" (a card's status is *Within*) |
| **Automation** | The condition→effect engine | — |
| **Only if** | A guard on ONE step: it runs only when the guard holds against what earlier steps published. `when` is the wire's field name | "When" (the automation's trigger already owns that word on the canvas), filter, condition (that is the trigger's) |
| **For each** | A fan-out on ONE step: it runs once per item of a list, and each iteration reads its item as `item.<field>` (a scalar as `item.value`). `for_each` is the wire's field name, and the surface word too — there is no collision to translate away | loop, iterate, batch (a batch is one send of many things; this is many sends) |
| **Otherwise** | The route on ONE step: it runs exactly when the named step's Only if was evaluated and did NOT hold — an undecided guard takes neither arm. `else_of` is the wire's field name | else/branch/if-else (programming words for a drawn surface), fallback (that is the every-step-failed escape hatch), condition |
| **From any** | The join: a binding that reads the first of several references that resolved (`{"$from_any": [...]}`), which is how one step runs after either arm of a route. Every alternative is validated, awaited and drawn | merge (git's word), first-of, coalesce (SQL's) |
| **In parallel** | An automation's step scheduling: steps run as their arrows allow — each waits for the steps it reads and nothing else. "In order" is the default and the pre-DS-7 sequential walk. `scheduling` is the wire's field name | concurrent/async/frontier (implementation words for a drawn surface), fan-out (that is For each — many sends of ONE step) |
| **Advice rule** | A "if metric X then recommend Y" entry | playbook (the `playbook/` sense) |
| **Starter** | A named question template that seeds a run | research playbook |

## Agents

| Use this | For | Don't use |
|---|---|---|
| **Explorer · Analyst · Responder · Watcher · Briefer · Curator** | The six built-in agents | Scout, "Insight" as an agent, charter (as a user word) |
| **SQL Engineer · Verifier · Narrator · Orchestrator** | The sub-roles inside a deep analysis | — |
| **Custom agent** | An agent a user created | persona, hired agent, user-defined agent, Gem |
| **Pack** | A domain bundle (entities, metrics, questions, evals) | specialist pack, expertise pack, Domain Expertise Pack, expert |
| **Agent Ops** | The workspace (layers: Overview · Roster · Attention · Automations · Hub · Departures · By duty · Action centre · Developer — Activity folded into Overview 2026-10-13, Runs into Activity before that) — renamed from "Agents" 2026-08-17 so the workspace and its Roster layer stop sharing a name | Agents (as the workspace name), Agentic Ops, Control Room, Fleet |
| **Map** | An agent's Roster tab: what it is scoped to, the doors it can be reached through, and the chains it operates — read-only, every node a field that already exists | Canvas (that is Data Canvas), Design (that is the automation editor's mode, and this edits nothing), Graph (that is the knowledge graph) |
| **Viewer · Editor · Owner** | The human permission ladder | "Analyst" as a *human* role — it names the agent |

The agent that runs deep analyses stays **Analyst**; the human RBAC role renamed to
**Editor** so the word means one thing. The stored grant value is still `"analyst"`.

## The explorer's passes

An exploration run is one of three **jobs**, and every surface — the log, the job title, the Catalog's
maturity bars, the API — says the job and the pass by name, never a number. "Phase 8", "domain_intel_only",
"manifest-driven" and "baseline cells" reached the log and the user on 2026-10-22 (PENDING item 53); the map
from the old numbers lives at the top of `aughor/explorer/agent.py`.

| Use this | For | Don't use |
|---|---|---|
| **structure** (the job) | Learning the structure with no model call: the five passes below | foundation, "phases 3-7" |
| **null meaning** · **join verification** · **lifecycle mapping** · **distribution profiling** · **cross-table patterns** | The five structure passes (`_pass_null_meaning` … `_pass_patterns`; journaled as `null_meaning`, `join_verification`, `lifecycle_mapping`, `distribution`, `cross_table`) | Phase 3 … Phase 7 |
| **questions** (the job) | What the explorer asks each dataset once a person has set its layer: the **pinned key questions**, the industry manifest's **baseline questions**, then the **curiosity loop** (`_pass_pinned_questions`, `_pass_questions`) | Phase 8, domain intel(ligence), manifest-driven, baseline cells |
| **synthesis** | Pairs of findings composed into one neither holds (`_pass_synthesis`) | Phase 9 |
| **full** (the job) | structure, then questions, then synthesis | — |

The persisted phase key `domain_intel` — the explorer's state and journal, `ExplorationPhase.DOMAIN_INTEL`, the
`domain_intel_only` keyword, the `/trigger-intel` route — keeps its spelling: renaming a persisted identity
orphans history, exactly as `investigation` does above. Its reader label is "asking its questions".

A deep analysis step is shown by its **name** (`phase_name`), never its id: `adhoc_3` is the conversation
agent's third query, and the thinking row says what that query was.

## Platform internals

These are the package names on disk. Every rename below has landed; the old names do not
exist any more, so there is nothing to fall back to.

| Package | Holds | Renamed from |
|---|---|---|
| `aughor/actions/` | Governed writes to the data | `kinetic/` |
| `aughor/notifications/` | Outbound webhook / Slack / Jira delivery | `actions/` |
| `aughor/control_plane/` | Credential and inference vending | `platform/` (also shadowed stdlib `platform`) |
| `aughor/custom_agents/` | User-created agents | `user_agents/` (reads as the HTTP header) |
| `aughor/feedback/` | Human accept / correct / reject capture | `verify/` (one of four `verify`s) |
| `aughor/business_profile/` | Inferred industry and business model | `profile/` (collided with data profiling) |
| `aughor/lifecycle/` | Lifecycle / state-machine mining | `process/` |
| `aughor/pipeline/` | The generate→validate→execute→interpret template | `capability/` (collided with licence capabilities) |
| `aughor/demo/` | The bundled sample workspace | `samples/` (collided with row samples) |
| `aughor/files/` | Unstructured file store | `volumes/` |
| `aughor/briefing/` | Briefing subscriptions and delivery | `briefs/` |

Other internals: an **ambiguity probe** (`agent/ambiguity_probe.py`, was `soma`) generates
candidate readings and asks only when they diverge. Say **validate** for SQL checking
(`trust/`), **feedback** for human verdicts, **check** for claim verification — `verify`
named all three plus a quality gate.

**No import shims were left behind.** The plan originally called for them, but a shim would
keep the retired word alive in the tree — and the ratchet would rightly count it. Every
reference in the repo moved atomically instead. An out-of-repo script importing
`aughor.platform` will need updating; the table above is the map.

`verify` currently names four unrelated things (SQL validation in `trust/`, human feedback
in `verify/`, claim checking in `agent/verify.py`, a quality gate in `explorer/verify.py`).
Only the first keeps the word in prose: say **validate** for SQL, **feedback** for humans,
**check** for claims.

---

## The look (Settings ▸ Appearance)

| Use this | For | Don't use |
|---|---|---|
| **Skin** | Dark or light — `<html data-theme>`, the toggle in the top strip | "theme" in anything a user reads (the Theme is Radix's root) |
| **Look** | The six knobs one person keeps: accent, grey, corners, scaling, edges, typeface (`web/lib/lookValues.ts`, `aughor/db/user_prefs.py`) | "theme", "style", "density" (retired 2026-10-06; scaling is the one knob for size) |
| **Preset** | All six knobs at once, named for what it does: **Aughor** (the default) · **Workbench** (blue · slate · small corners · 95% · boxed cards · Source Sans) | a product's name for a look (the ratchet retires those) |
| **Edges** | Whether a card in the dark skin is boxed by a hairline (`--card-edge`); the light skin always is | "borders" as a knob |
| **Typeface** | The face the interface is set in: Inter or Source Sans; figures stay tabular, ids and code mono | "font" as the knob's name |

## External names

**Keep** the name of anything we actually integrate with — DuckDB, MotherDuck, MLflow,
Langfuse, Snowflake, BigQuery, the AG-UI protocol, every connector. Naming the product you
connect to is not jargon.

**Keep** attribution headers. `aughor/sql/readonly.py` and `aughor/sql/tables.py` are
Apache-2.0 adaptations of Superset code and say so; `NOTICE` records them. That is a licence
obligation.

**Don't** name our own features after products that inspired them. No "Genie-style",
"Foundry rule", "Palantir-grade", "Databricks-style" in identifiers, UI copy, prompts, flag
metadata, or CSS comments. Where a design genuinely came from a study, cite the document
once — `(see docs/GENIE_DOCS_TEARDOWN_2026-07-26.md)` — instead of describing the feature as
the brand.

**Study documents keep their names.** `docs/*_STUDY_*.md` are historical records.

**Fixture names** (BeautyCommerce, missimi, swiss_air) are fictional demo data — fine to
keep, but don't reach for them in a production docstring when a generic sentence works.

---

## Names that are frozen

These are persisted identities. They are never renamed; they are mapped to a display word at
the boundary. If you are tempted to rename one, you are about to orphan history.

- Ledger `natural_key` prefixes `ada:` and `insight:`; artifact kinds `ada_report`, `finding`
- The `investigations` table, the `/investigate` route, the `investigation` job kind
- **The four `STRUCTURAL_MODES`** — `direct`, `investigate`, `explore`, `final_text`.
  `query_mode` is a field on the checkpointed graph state and the checkpointer writes to
  `data/checkpoints.db`, so these values sit on disk in every paused run. Display words map
  at the boundary: Quick answer · Deep analysis · **Survey** · Knowledge answer. They are
  BODIES, derived from the question's **shape** and the depth (`question_shape.body_for`) —
  never asked of a model and never the word for a question's kind.
  `aughor/agent/explore.py` keeps its name deliberately — renaming it to `survey.py` while
  the mode id stays `explore` would trade one mismatch for another
- The licence capability **value** `"analysis.deep"`
- Job kinds; agent ids (`scout`, `analyst`, `insight`, …); sub-role ids in `agent.handoff`
  payloads; the `agent_governance` store name and keys; session-log and checkpoint `agent_id`
- The RBAC role value `"analyst"`
- DB columns (`investigations.origin_insight_id`, `user_agents.*`), the Qdrant payload key
  `insight_id`, dashboard card `source="insight"`
- The pack on-disk format (`pack.yaml`, `expertise.md`, manifest keys)
- What a dashboard stored while it was called a *cockpit* (renamed 2026-10-23; read both ways, never rewritten): the
  Ledger artifact kind `cockpit` and its natural keys `cockpit:person:{connection}:{owner}:{id}` (and the older
  `cockpit:{canvas id}`); a spec's root `"cockpit"` and its element type `Cockpit`; the proposal kinds `cockpit_draft` /
  `cockpit_publish`, their `cockpit:{title}` action ids and the `cockpit` proposer; the audit and approval names
  `cockpit.draft` / `cockpit.publish`; the `cockpit-images` file volume; the Briefing-switches section id `cockpit`;
  the browser keys `aughor:cockpit:*`; the metering sites `cockpit.draft` / `cockpit.edit`; and the old links
  `?tab=cockpit` / `?layer=cockpit`, which still open; and the data's field names those stored rows carry, which the API mirrors — `cockpit`,
  `cockpit_id`, `cockpits` (a proposal's params, a Ledger payload, a response). The nine flags were renamed through
  `RENAMED` / `RETIRED_ENV` (`cockpit.*` → `dashboard.*`, `AUGHOR_COCKPIT_*` → `AUGHOR_DASHBOARD_*`), and `/cockpits…`
  is served as `/dashboards…`. The vocabulary ratchet holds the word at its count
- The card store's table `dashboard_cards`, its file `data/dashboard_cards.db` and its `AUGHOR_DASHBOARD_DB` override —
  the store itself moved to `aughor/cards/` (2026-10-23) so that *dashboard* names dashboards; a stored card is a
  `StoredCard` in code

**Flag names are renameable, but only through the alias layer** — `RENAMED` and
`RETIRED_ENV` in `aughor/kernel/flags.py`. Editing a `FLAG_ENV` key on its own strands the
operator's env var, their persisted override row, and any script that passes the old name.
