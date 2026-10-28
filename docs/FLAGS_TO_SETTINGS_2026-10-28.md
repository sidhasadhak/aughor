# Flags into settings — 2026-10-28

**The ask** (the user, 2026-10-28): *"let's consider not having any feature flags at all.. instead of having 30-40
feature flags, we will make sure that most of it comes as a default feature like always on and cannot be turned off..
and some of them can be turned on off based on the requirements of the organisation and not the user mostly... this is
one of the critical things that we need to do.."*

**The answer in one line:** of the install's 81 flags, 57 are already on and nobody turns them off — they become plain
platform behaviour; 10 more join them once each passes a check on live data. Four turn on by themselves when their
setup exists. Four real choices remain, and they belong to an organisation's admin as settings, not to an operator as
flags. Five experiments are decided once — kept or deleted — and never offered as a switch. New work stops shipping
behind flags: it merges on, or stays on its branch.

---

## 1. Measured (live install, `d6a8032e`, read over HTTP)

- **81 registered flags; 63 on.** Where each value comes from: 44 a runtime override (someone pressed a toggle), 13 an
  environment variable (the twelve-setting restart recipe exists only to set them), 24 the default.
- **Their declared dispositions** (the 2026-07-31 strategy's ratchet): 38 *graduation queue*, 32 *experiment*, 11
  *default on*. Of the 38 waiting to graduate, most are on live already — a flag that is on and waiting is a switch
  nobody will press and a receipt nobody scheduled.
- **120 places in the code read a flag**, plus a "byte-identical when off" test per flag.
- **This happened once before.** The 2026-07-31 strategy (`docs/FLAG_STRATEGY_2026-07-31.md`) found 91 flags, sorted
  them by kind and cut the visible surface to about 22 decisions, with a ratchet so every flag declares its exit. The
  ratchet held the *exit*; nothing held the *count*. Since August every arc shipped behind its own flags — 81 again.
- **The cause is a rule, not neglect.** `AGENTS.md`: *"Flags are off by default and byte-identical when off… A flag
  graduates on a receipted GraduationDecision."* Every piece of work therefore arrives as a flag, and leaves only when
  someone takes a receipt for it alone. The work is proven live (every arc this month was) — the flag simply stays.

## 2. What a switch is for

A switch earns its place only when two organisations would rightly choose differently. Measured against the 81, that
happens for three reasons and no others:

1. **Data leaves the install** — to another install, or to an outside model provider.
2. **Model work nobody asked for** — calls Aughor makes on its own schedule, not because a person pressed something.
   (Work a person asks for, with its cost said first, is not a switch: asking is the consent.)
3. **A governance posture** — a rule about people, such as needing a reason to read a run's details.

Everything else is either the product, or a piece of the product that waits for its own setup.

## 3. The proposal

| Becomes | Flags | How |
|---|---|---|
| **Always on** | 57 | The flag and its off branch are deleted; the code path stays. All 57 are on live today. |
| **Always on, after its check** | 10 | Each is off today. It is turned on with a check on live theLook (the receipt it already names), then deleted the same way. One that fails its check is fixed or deleted — never left as a switch. |
| **On when set up** | 4 | No switch: inbound email works once its domain and secret are set; Google comments once the OAuth client is; the Slack bot once Slack is configured; word search over documents once the vector store is up. Missing setup is *said* where the feature would appear. |
| **Organisation setting** | 5 → 4 settings | Admin-only, in the organisation settings that already exist (`aughor/orgsettings`, the same place as currency and the model policy), each with its default stated. |
| **Decided once** | 5 | Experiments that change prompts or routing. Each is kept (always on) or deleted, on a measurement or on your word — never a switch. |

**The four organisation settings** (Settings ▸ Organization ▸ *What Aughor may do*):

| Setting | Default | From |
|---|---|---|
| Share summary statistics with other installs | Off | `aggregates.share` |
| Send row text to an outside, cheaper model for row-by-row work | Off (on here today) | `semops.jev_cheap_tier` |
| Ask for a reason before anyone reads a run's details | Off | `govern.justifications` |
| Let Aughor run model work on its own schedule (nightly agent tests, re-tests after reviews) — within the Spend budget | Off | `agents.testing_centre`, `agents.learning_loop` |

**The five decided once:** `grounding.full_schema_first` has its own record in its favour (two test runs, never
worse, twice answered where the shorter schema could not) — keep it. `judgment.shadow_treatment` makes one extra model
call on every question to record how much work it needed, for PENDING item 4 — stop it, and measure once when item 4
is taken up. `grounding.data_profiles`, `explore.route_wide` and `federation.planner` are off and unmeasured — delete
the switches; their ideas stay in PENDING items 19 and 31.

## 4. The rule for new work (replaces the flag invariant)

- **A feature merges on.** There is no feature flag. Work that is not ready stays on its branch until it is.
- **The receipt moves before the merge.** "Green tests are not proof" stands: a piece is shown working on live data (a
  scratch API, or the live install) before its PR, as every arc this month already was.
- **An organisation setting is added only for the three reasons in §2**, with its default, admin-only, and a test for
  both values. A ratchet holds the count: a new setting must name its reason.
- **Withheld is still said.** A feature waiting on its setup says what is missing where it would appear.

## 5. What changes for this install

- The twelve-setting restart becomes one setting (model prices).
- Settings ▸ System ▸ *Feature flags* goes; Settings ▸ Organization gains *What Aughor may do* (four rows).
- About 120 flag reads and the off-path tests go; the disposition ratchet is replaced by the settings ratchet; the
  persisted override rows are cleared by a migration that records what each said (supersede, do not delete).
- `AGENTS.md`'s flag invariant and `docs/GLOSSARY.md`'s *flag* entry are rewritten to §4.

## 6. Risks, and what answers them

- **An always-on path cannot be switched off when it misbehaves.** The answer is a revert, as for any code. The 57 have
  run on live for days to weeks; the 10 off ones get their check first.
- **Object security (`ontology.security`, `ontology.security_sql`) changes answers for everyone once on.** It enforces
  only rules an organisation declares, and says what it withholds; its check is a reader with a declared policy on
  theLook seeing less, and being told so.
- **A deleted experiment may have been right.** Its idea stays in the record (PENDING keeps the line); only the switch
  goes.

## 7. Execution (one branch, a commit per area)

1. The rule (`AGENTS.md`, glossary), the settings section and its ratchet; the four organisation settings.
2. The 57, area by area — dashboards, sheets, ontology, metrics and the Briefing, agents and actions, the rest — each
   commit deleting the flag, its off branch and its off-path tests, the full suite once at the end.
3. The 10, each checked live and then deleted.
4. The 4 self-configuring, each saying what is missing.
5. The 5 experiments, as decided.
6. Live: the restart without its eleven flag settings; the override rows cleared and recorded.

## 8. The calls (yours)

1. **The rule for new work:** no flags at all — unfinished work stays on its branch *(recommended)*; or a short-lived
   build flag allowed, deleted within two weeks or CI fails.
2. **The four organisation settings** as listed in §3 *(recommended)* — or fewer, or others.
3. **The 10 that are off today:** check each on live and turn it on *(recommended)*; or delete the ones not worth
   checking now.
4. **The 5 experiments:** decide now without spending — keep `grounding.full_schema_first`, stop
   `judgment.shadow_treatment`, delete the other three *(recommended)*; or measure them (model calls).

---

## Appendix — every flag, in plain English

### Always on — 57, all on live today

The switch goes and the feature stays. Each one is on now, and none sends data out or spends on its own schedule.

**Dashboards**

- `dashboard.composed` — The Dashboards tab itself: cards arranged in tabs and sections, a card shown only while a condition holds. *Why always on:* It is the base every other dashboard piece sits on, and it does nothing until someone builds a dashboard.
- `dashboard.app_pieces` — Sections split into columns, rows or tabs; an empty section offers a piece. *Why always on:* It is how every dashboard is laid out today; switching it off would break the dashboards already made with it.
- `dashboard.builder` — Edit a dashboard in place, every change kept as a version you can go back to. *Why always on:* It is the way dashboards are edited, and it only ever changes your own.
- `dashboard.shapes` — Starting from an object offers the shapes its data fits — a queue, a map, a timeline — with why. *Why always on:* It is only an offer when starting; you still choose.
- `dashboard.queries` — A card holding your own SQL, drawn as a table, figure or chart. *Why always on:* Nothing happens until someone writes a query, and it runs read-only and time-limited.
- `dashboard.variables` — A value on a dashboard can come from the reader, a set's count or the chosen object. *Why always on:* Nothing happens until an author adds one; a reader's value stays in their browser.
- `dashboard.wiring` — Choosing a row in one piece narrows the others; buttons run declared actions on chosen rows. *Why always on:* Every action keeps its own checks and approvals, and nothing runs without a click.
- `dashboard.breakdowns` — Groups objects by a property, with Other and No value rows, and says whether the groups add up. *Why always on:* Checked today on theLook; it appears only when someone adds one.
- `dashboard.marks` — Marks the rows a declared segment covers, with a legend that counts them. *Why always on:* Checked today on theLook; it marks only by what the ontology declares.
- `dashboard.questions` — A question on a dashboard the agent answers on a rhythm, weekly by default. *Why always on:* It spends model calls, but only for a question a person put there, on the rhythm they chose; opening the dashboard never asks.
- `ontology.dashboard_pieces` — The ontology's pieces: process board, objects table, object detail, action button. *Why always on:* Dashboards built from the ontology are made of them; an action that needs approval is proposed, never run.
- `ontology.object_dashboards` — Start a dashboard from an object: its filters, figures, a daily chart and its objects. *Why always on:* It is an offer; a filter is each reader's own and never changes the dashboard.
- `packs.dashboard_templates` — A pack bound to a connection offers dashboard templates you can keep. *Why always on:* Nothing is kept until you keep it.

**Spreadsheets**

- `sheets.core` — Spreadsheets: tables made from a file, a query's rows or nothing, readable by every chat and dashboard. *Why always on:* The base of Sheets, live with four Olist sheets.
- `sheets.grid` — Edit cells, rows and columns, with undo; each change keeps who and when. *Why always on:* A sheet you cannot edit is not a spreadsheet, and nothing is ever deleted.
- `sheets.views` — Grouped grids with totals, boards, calendars and row rules; a view can be yours alone. *Why always on:* It only changes how rows are shown.
- `sheets.combine` — Link sheets by a key, total another sheet's rows, add a newer file — every miss counted first. *Why always on:* Each change is previewed and can be undone.
- `sheets.everywhere` — Make a dashboard from a sheet; its cards follow every edit. *Why always on:* An offer from the sheet, nothing more.
- `sheets.chat` — Ask a sheet questions beside it, or have it propose a change for you to apply. *Why always on:* Model calls happen only when a person asks, and nothing changes until they apply it.
- `sheets.model_columns` — A column a model fills for the rows you pick, at most 200 a fill, calls and cost said first. *Why always on:* It spends only when a person presses Fill after seeing the cost; the organisation's limit on spend is its Spend budget.
- `sheets.sharing` — Share a sheet with chosen people or groups, as readers or editors. *Why always on:* The sheet's maker decides; without it every sheet is everyone's.

**The ontology**

- `ontology.history` — Keeps every version of each entity, link, process, rule and action, and blocks a removal something depends on. *Why always on:* Off loses history and allows a removal that breaks things — against the rule that nothing is deleted, only superseded.
- `ontology.release` — Changes wait in a draft until someone publishes them; each is rated, and a breaking one is refused. *Why always on:* It is the safety net for every reader; off applies a change the moment it is saved.
- `ontology.put_back` — Put an earlier version back into the draft. *Why always on:* An undo for the ontology, still published like any change.
- `ontology.retiring` — Mark an element as retiring on a date, with what replaces it. *Why always on:* It applies only when someone marks one.
- `ontology.census` — Counts once a day what each ontology declares and what depends on it. *Why always on:* Free — no model calls, no warehouse queries.
- `ontology.entity_usage` — An entity's page lists what uses it, and counts its queries by month from the platform's own log. *Why always on:* Free and read-only.
- `ontology.builder_doors` — Outside programs can read your objects and their types, and propose an action for a person to approve. *Why always on:* Nothing runs from outside, and a program needs its own key.
- `ontology.set_segments` — Keep a dashboard's set as a segment of the ontology, in the draft. *Why always on:* Only when someone keeps one, and it is published like any change.
- `ontology.keyed_metrics` — An approved metric linked to its entity is used for any segment of it. *Why always on:* Figures stay true to the approved definition; on live already.
- `ontology.explore_on_connect` — When a connection is added, Aughor proposes its entities, links, processes and rules for a person to confirm. *Why always on:* One model call per new connection, skipped if already explored — part of what connecting means.
- `graph.declarations` — Search finds what the ontology publishes: segments, processes, rules, actions, links. *Why always on:* Free, and it withholds what you may not see.
- `objects.find` — The command bar finds an object by its name. *Why always on:* Row policies apply; it reads only what you may see.

**Metrics and the Briefing**

- `metrics.figure_gates` — Before approval, six months of a metric's figures are checked; a flat or out-of-range one is refused. *Why always on:* It stops a wrong metric reaching the Briefing — the 10-26 'never happens again'.
- `metrics.coverage_map` — The Metrics tab shows each area of the business and which have metrics. *Why always on:* Free; it reads approved figures at most hourly.
- `metrics.coverage_proposals` — Proposes metrics for areas with none, from the pack and the ontology, each checked first. *Why always on:* Proposals only; nothing is approved without a person.
- `metrics.blind_spot_proposals` — Proposes a metric for a measure the explorer keeps computing without one. *Why always on:* Proposals only.
- `metrics.coverage_writer` — When a dataset is profiled, one model call per business area drafts metrics from the knowledge base. *Why always on:* It runs once per profiling — 11 calls on LuxExperience — says how many on the Metrics tab, and only proposes.
- `briefing.by_period` — Briefings for the last complete day, week, month or year, and subscriptions on that schedule. *Why always on:* It is the Briefing as you use it; it sends only to subscribers.
- `briefing.ranges` — One date-range control for the Briefing, its figures from approved metrics. *Why always on:* How the Briefing reads today.
- `briefing.metric_cap` — The Briefing measures up to 24 metrics, or a workspace's own number, by area. *Why always on:* How LuxExperience's Briefing reads today; the number is already a workspace setting.

**Answers, agents and decisions**

- `ask.converse` — Answers run as an agent using tools step by step, with the same checks inside each tool. *Why always on:* It is how chat answers today; off falls back to an older fixed script.
- `chat.buttons_reach_agent` — Chat's Quick and Agent buttons go to that same agent. *Why always on:* The same path as above.
- `analyst.conclude` — An answer ends with a headline, the answer and the results it cites. *Why always on:* No extra model calls; it is the answer shape you see today.
- `answers.recheck` — Re-runs the last 14 days' answers daily and tells the asker when a number moved 5% or more, with why. *Why always on:* Honesty about changed numbers; warehouse queries only, and its Slack replies pass the same send checks.
- `agents.grounding_read` — A program holding an agent's key can see what the agent would be given for a question. *Why always on:* Read-only, cut to what the caller may see, and recorded.
- `agents.revision_on_answers` — A custom agent's answer names the revision of its setup that gave it. *Why always on:* Free, and it stops a save made against an out-of-date agent.
- `record.decision_loop` — A decision keeps its evidence and expectation and is reviewed on its date against what would have happened anyway. *Why always on:* No model calls; live since 10-24.
- `semops.banded_cascade` — When a model judges text rows, a cheap model goes first and only the unsure rows go to the strong one. *Why always on:* It spends less than switching it off would.

**Operations and the platform**

- `actions.outbox` — An action's calls to other systems are queued, retried safely and never sent twice. *Why always on:* Off sends once with no retry — less safe.
- `actions.run_attribution` — Every edit and action records the run that made it, and its cost. *Why always on:* Free, and it is the audit trail.
- `automations.objects_admitted` — An automation can start when objects enter a rule or segment. *Why always on:* It is offered; the automation's owner chooses it.
- `hub.failure_rate` — The hub map shows each automation's failure rate over the week. *Why always on:* Free; it says 'no runs', never 0%.
- `obs.log_search` — Search the log lines of every run over 30 days. *Why always on:* Free; who may use it is a permission, not a switch.
- `canvas.ask_about_chosen` — Ask the Data Canvas about the objects you ticked on a dashboard. *Why always on:* No extra calls, and your row policy holds.
- `packs.installed_versions` — Binding a pack records its version; a newer one shows what changed. *Why always on:* Free, and it never re-offers what you declined.
- `state.backups` — Hourly checked copies of Aughor's own state, thinned over eight weeks. *Why always on:* The safety net for everything else; it says so when the disk is too full.

### Always on, after its check — 10, off today

Each is turned on only after the check named here passes on live theLook.

- `dashboard.app_versions` — A shared dashboard's readers keep reading its last published version while its maker drafts changes. *Today:* readers see each change the moment it is kept. *Why on:* readers should not see half-made changes. *Its check:* publish, change it twice, and a reader still sees the published one until it is published again.
- `automations.versions` — Each save of an automation or monitor keeps the one before; each run names its version and can be replayed without sending anything. *Today:* a save replaces the old definition for good. *Why on:* nothing should be destroyed by a save. *Its check:* save one twice, read both versions, replay a past run and see nothing sent.
- `monitors.recovery` — An alert closes itself when its metric comes back within its limit; the recovery is shown, never sent. *Today:* an alert stays open until someone acknowledges it. *Why on:* an alert that has recovered still reads as open (worth your word: some teams prefer to acknowledge by hand). *Its check:* a monitor on theLook that fires, recovers, and closes with the value that came back.
- `objects.completeness` — Every object read says whether it was complete, cut short, narrowed for you, or refused. *Today:* a read cut at a limit can look complete. *Why on:* withheld is said, never implied — today it can be implied. *Its check:* a read past the row limit on theLook says there are more.
- `ontology.impacts_only` — Only the impacts a person declared count as what affects what; an analysis stops proposing causes of its own. *Today:* causes a model proposed are kept and read as if declared. *Why on:* no model authors a fact. *Its check:* an alert summary names only declared impacts, and how many do not hold.
- `ontology.security` — Each reader sees only the objects their groups may see; sensitive properties are masked, with the reason. *Today:* everyone sees everything, even where a policy is declared. *Why on:* a declared policy that is not enforced is a broken promise; with none declared nothing changes. *Its check:* a reader with a declared policy on theLook sees less, and is told so.
- `ontology.security_sql` — The same policies and masks hold in answers, deep analyses and the SQL editor. *Today:* only object pages, dashboards and outside programs apply them. *Why on:* otherwise a question can read what the object page withholds. *Its check:* the same reader's question on theLook is refused the masked property, with why.
- `mcp.caller_principals` — An outside program connects to the MCP server as itself, with its own key, and sees only its tools. *Today:* every program shares the server's one token. *Why on:* each program should answer for its own calls. *Its check:* a program connects with its own key, and one already connected keeps working.
- `security.principal_scopes` — A program's key can be limited to some areas, entities and actions. *Today:* only the agent policy limits a program. *Why on:* it applies only when someone sets limits. *Its check:* a limited key is refused outside its areas, with why.
- `quality.expectations` — An automation checks what a table must meet — never empty, no repeated key, recent enough — and records it as the table's health. *Today:* health reads 'not checked'. *Why on:* it measures only what someone declares, read-only. *Its check:* one expectation on a theLook table, met and then not.

### On when set up — 4

No switch: each works once its setup exists, and says what is missing where it would appear.

- `arrivals.email` — Each decision gets an email address; mail to it is kept as evidence, an approval or a dissent. *Needs:* a mail domain and its secret. *Why no switch:* setting it up is the choice.
- `arrivals.google_comments` — Comments on a named Google file are read onto a decision. *Needs:* your Google OAuth client. *Why no switch:* setting it up is the choice.
- `slack.managed_supervisor` — Aughor starts the Slack bot itself and restarts it if it stops. *Needs:* Slack configured, and Node.js. *Why no switch:* setting it up is the choice.
- `knowledge.hybrid_documents` — When the embedding model is down, document search matches words instead, and says so. *Needs:* the vector store running. *Why no switch:* setting it up is the choice.

### Organisation settings — 4, from 5 flags

Admin-only, in Settings ▸ Organization ▸ *What Aughor may do*.

- **Share summary statistics with other installs** (`aggregates.share`) — Exports how often packs' claims held here, never names, ids or values. *Default:* Off. *Why a setting:* data leaves your install — the organisation's call.
- **Send row text to an outside, cheaper model** (`semops.jev_cheap_tier`) — TypeSafe's hosted Jev judges text rows before your own strong model. *Default:* Off (on here today). *Why a setting:* row text leaves your install to another company — the organisation's call.
- **Ask for a reason before anyone reads a run's details** (`govern.justifications`) — Reading a run's full payload or exporting the ledger asks why, and records it. *Default:* Off. *Why a setting:* a governance posture: a regulated organisation wants it, a small team does not.
- **Let Aughor run model work on its own schedule** (`agents.testing_centre`, `agents.learning_loop`) — Nightly runs of each custom agent's checked test questions, and re-tests after reviews. *Default:* Off. *Why a setting:* model calls every night that nobody pressed — the organisation decides whether to spend on that, within its Spend budget.

### Decided once — 5

Each changes prompts or routing. None stays a switch.

- `grounding.full_schema_first` — For a small schema, the SQL writer sees every table, not only the ones picked for the question. *Today:* off. *Recommended:* Keep — always on — its own record: in two test runs it never wrote a worse query, and twice it answered where the shorter schema could not.
- `grounding.data_profiles` — Adds a short data profile — row counts, ranges, common values — to the SQL writer's prompt. *Today:* off. *Recommended:* Delete the switch — nothing measured; it is PENDING 19's idea, better built and measured there than left as a switch.
- `explore.route_wide` — A broad question gets a survey of many cuts instead of one deep analysis. *Today:* off. *Recommended:* Delete — unmeasured, and it changes how questions are routed.
- `federation.planner` — Answers a question needing two connections: a model plans each query and the join. *Today:* off. *Recommended:* Delete — unmeasured, and it would route some questions on its own; the idea stays in PENDING 31.
- `judgment.shadow_treatment` — After every question, a model notes the smallest answer that would have done. *Today:* on. *Recommended:* Stop it — one extra model call on every question, for a record nobody reads yet; it can run as a one-off measurement when PENDING 4 is taken up.
