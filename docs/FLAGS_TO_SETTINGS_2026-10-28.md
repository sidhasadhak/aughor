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

**The five decided once:** `explore.route_wide`, `federation.planner`, `grounding.data_profiles`,
`grounding.full_schema_first` (all off — each claims better answers for more prompt or a different route) and
`judgment.shadow_treatment` (on — it makes one extra model call per question to record how much work each question
needed, for PENDING item 4). Measuring the four off ones costs model calls; deciding them without measuring means
deleting them.

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
4. **The 5 experiments:** decide now without spending — keep `judgment.shadow_treatment` until PENDING item 4 is
   settled, delete the four off ones *(recommended)*; or measure them (model calls).

---

## Appendix — every flag

| Flag | Live now | Becomes | What it does |
|---|---|---|---|
| `actions.outbox` | on | Always on | Send action calls through an outbox |
| `actions.run_attribution` | on | Always on | Which run made each change |
| `agents.grounding_read` | on | Always on | Let programs read what an agent would read |
| `agents.revision_on_answers` | on | Always on | Name the agent's revision on its answers |
| `analyst.conclude` | on | Always on | Agent answers end with their own structure |
| `answers.recheck` | on | Always on | Tell people when their answer changes |
| `ask.converse` | on | Always on | Answer through a conversation with tools |
| `automations.objects_admitted` | on | Always on | Act on each object a rule admits |
| `briefing.by_period` | on | Always on | Briefings by day, week, month and year |
| `briefing.metric_cap` | on | Always on | Measure up to 24 Briefing metrics, by area |
| `briefing.ranges` | on | Always on | Briefings for any date range |
| `canvas.ask_about_chosen` | on | Always on | Ask about the objects you chose |
| `chat.buttons_reach_agent` | on | Always on | Send chat buttons to the conversation agent |
| `dashboard.app_pieces` | on | Always on | Split dashboards into sections and add more pieces |
| `dashboard.breakdowns` | on | Always on | Breakdowns on dashboards |
| `dashboard.builder` | on | Always on | Build dashboards in place |
| `dashboard.composed` | on | Always on | A dashboard in each Data Canvas |
| `dashboard.marks` | on | Always on | Rows marked by a rule on dashboards |
| `dashboard.queries` | on | Always on | Your own query on a dashboard |
| `dashboard.questions` | on | Always on | Questions on a dashboard |
| `dashboard.shapes` | on | Always on | Start a dashboard from a shape |
| `dashboard.variables` | on | Always on | Variables on a dashboard |
| `dashboard.wiring` | on | Always on | Wire a dashboard's pieces and actions |
| `graph.declarations` | on | Always on | Search what the ontology declares |
| `hub.failure_rate` | on | Always on | Failure rate on the hub map |
| `metrics.blind_spot_proposals` | on | Always on | Propose the measures the explorer keeps computing |
| `metrics.coverage_map` | on | Always on | Show which areas of the business have metrics |
| `metrics.coverage_proposals` | on | Always on | Propose metrics for areas that have none |
| `metrics.coverage_writer` | on | Always on | Write metrics from the knowledge base on profiling |
| `metrics.figure_gates` | on | Always on | Check a metric's figures before it is approved |
| `objects.find` | on | Always on | Find an object by its name |
| `obs.log_search` | on | Always on | Search logs across runs |
| `ontology.builder_doors` | on | Always on | Let outside programs read the ontology |
| `ontology.census` | on | Always on | Count the ontology once a day |
| `ontology.dashboard_pieces` | on | Always on | Build dashboards from the ontology |
| `ontology.entity_usage` | on | Always on | What uses an entity |
| `ontology.explore_on_connect` | on | Always on | Propose business terms for a new connection |
| `ontology.history` | on | Always on | Keep ontology history |
| `ontology.keyed_metrics` | on | Always on | Compute approved metrics for any segment |
| `ontology.object_dashboards` | on | Always on | Start a dashboard from an object |
| `ontology.put_back` | on | Always on | Put an earlier ontology version back |
| `ontology.release` | on | Always on | Publish ontology changes as releases |
| `ontology.retiring` | on | Always on | Mark an ontology element as retiring |
| `ontology.set_segments` | on | Always on | Keep a dashboard set as a segment |
| `packs.dashboard_templates` | on | Always on | Start a dashboard from a pack's template |
| `packs.installed_versions` | on | Always on | Record each pack's installed version |
| `record.decision_loop` | on | Always on | Decisions reviewed honestly |
| `semops.banded_cascade` | on | Always on | Send only unsure rows to the strong model |
| `sheets.chat` | on | Always on | Ask about a sheet, and have changes proposed |
| `sheets.combine` | on | Always on | Combine sheets |
| `sheets.core` | on | Always on | Spreadsheets: tables you make and keep |
| `sheets.everywhere` | on | Always on | Dashboards made from sheets |
| `sheets.grid` | on | Always on | Edit sheets in place |
| `sheets.model_columns` | on | Always on | Columns a model writes, row by row |
| `sheets.sharing` | on | Always on | Share sheets with chosen people |
| `sheets.views` | on | Always on | Boards, calendars and rules on sheets |
| `state.backups` | on | Always on | Back up Aughor's own state every hour |
| `automations.versions` | off | Always on, after its check | Versions and replays for automations |
| `dashboard.app_versions` | off | Always on, after its check | Readers see an App's published version |
| `mcp.caller_principals` | off | Always on, after its check | Outside programs connect as themselves |
| `monitors.recovery` | off | Always on, after its check | Alerts that close when a metric recovers |
| `objects.completeness` | off | Always on, after its check | Every object read says how complete it is |
| `ontology.impacts_only` | off | Always on, after its check | Read what bears on what from impacts only |
| `ontology.security` | off | Always on, after its check | Limit who sees which objects and properties |
| `ontology.security_sql` | off | Always on, after its check | Apply object security to every answer |
| `quality.expectations` | off | Always on, after its check | Measure what tables must meet |
| `security.principal_scopes` | off | Always on, after its check | Limit what each outside program may do |
| `arrivals.email` | on | On when set up | Decisions by email, inbound only |
| `arrivals.google_comments` | on | On when set up | Comments on a Google file, read onto a decision |
| `knowledge.hybrid_documents` | on | On when set up | Search documents by words when meaning is down |
| `slack.managed_supervisor` | on | On when set up | Start the Slack bot automatically |
| `agents.learning_loop` | off | Organisation setting | Let custom agents learn from reviews |
| `agents.testing_centre` | off | Organisation setting | Test custom agents every night |
| `aggregates.share` | off | Organisation setting | Share summary statistics with other installs |
| `govern.justifications` | off | Organisation setting | A reason to read a run's payload |
| `semops.jev_cheap_tier` | on | Organisation setting | Use Jev as the cheap model |
| `explore.route_wide` | off | Decide once: keep or delete | Answer broad questions as a survey |
| `federation.planner` | off | Decide once: keep or delete | Answer questions across two connections |
| `grounding.data_profiles` | off | Decide once: keep or delete | Show the SQL writer what the data holds |
| `grounding.full_schema_first` | off | Decide once: keep or delete | Show the SQL writer every table |
| `judgment.shadow_treatment` | on | Decide once: keep or delete | Record how much work each question needed |
