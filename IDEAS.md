# Ideas

Ideas to think about. Nothing here is decided yet. [ROADMAP.md](ROADMAP.md) stays the plan of record. When we decide on an idea, it either moves into the roadmap or gets dropped from this file.

## 1. Removing a connection wipes it clean

*Noted 2026-09-12*

When a user removes a connection, the platform should really wipe it clean. Afterwards nothing should be left of that connection, neither its data nor any metadata about it.

- Starting point: removal already goes through `purge_connection_artifacts` in [aughor/db/purge.py:54](aughor/db/purge.py:54), which calls each store's own `purge_connection`.

## 2. A default agent recommends outlier alerts on industry metrics

*Noted 2026-09-12 · **BUILT 2026-09-23 — ROADMAP §3.24**: the Watcher's `alert_proposals` job, model-free, every proposal replayed before it is staged*

When an exploration finishes, whether for a newly created connection or on a daily run, an automation agent should:

1. Map the industry metrics that fit this data, maybe with the playbook's help, maybe without it.
2. Learn how each of those metrics is distributed.
3. Recommend automations that alert the organisation, or specified users, whenever one metric or a set of metrics has an outlier.

The agent could be created by default, alongside the Explorer, the Curator and the other default agents.

Starting points in the code today:

- The default agents are listed in [aughor/kernel/agents.py:67](aughor/kernel/agents.py:67). One of them, the Watcher ("KPI sentinel", [line 98](aughor/kernel/agents.py:98)), already runs threshold and anomaly checks. Its goal is to start a deep analysis when a metric moves, not to alert people.
- The anomaly check is `run_anomaly_monitor` in [aughor/monitors/runner.py:285](aughor/monitors/runner.py:285). It computes a z-score for a metric's daily values over a rolling window.
- An automation can already fire on a monitor through a `metric` condition ([aughor/automations/engine.py:241](aughor/automations/engine.py:241)), and it has a `notify` effect ([aughor/automations/models.py:263](aughor/automations/models.py:263)).
- The playbook code is in [aughor/playbook/](aughor/playbook/).

## 3. Daily, weekly, monthly, yearly and historical briefings

*Noted 2026-09-12* · **BUILT 2026-09-23 — ROADMAP §3.27** (behind the `briefing.by_period` flag, off; no live receipt on a real warehouse yet)

Offer the briefing in several versions: daily, weekly, monthly, yearly and historical. Today there is only the historical briefing, which looks at the whole data set.

The daily, weekly and monthly versions should build a time period into the approach of the briefing itself. The agent that delivers the briefing should know which version it is producing.

Starting points in the code today:

- The Briefer agent is defined in [aughor/kernel/agents.py:112](aughor/kernel/agents.py:112). The briefing text is written by `generate_narrative` in [aughor/knowledge/briefing.py:387](aughor/knowledge/briefing.py:387).
- Brief subscriptions already have a `period`, but it can only be `day` or `week` ([aughor/briefing/models.py:28](aughor/briefing/models.py:28)). The period sets the send time ([aughor/briefing/models.py:13](aughor/briefing/models.py:13)). What the subscription sends is an alert digest built for that period, not the briefing ([aughor/briefing/delivery.py:29](aughor/briefing/delivery.py:29)).
- Exploration already works inside a time window. `_compute_time_window` in [aughor/explorer/agent.py:783](aughor/explorer/agent.py:783) takes up to the last 12 months of real activity, and starts later when the data shows a clear recent break. Before deciding, check whether today's briefing really covers the whole data set or only that window.
- [docs/ADAPTIVE_TEMPORAL_SCOPE.md](docs/ADAPTIVE_TEMPORAL_SCOPE.md) is an earlier design note on choosing the time scope for exploration and briefings. It is marked "Planned", and ROADMAP.md doesn't mention it.

## 4. Learn when each table's numbers stop changing

*Suggested by Claude, 2026-09-13 · **BUILT 2026-09-23 — ROADMAP §3.23**; the first verdict on theLook needs three more days of readings*

Many sources keep rewriting recent days: late rows arrive, backfills land. On theLook, yesterday's order count reads about eight times what the same day settles at a week later. Until the lag was set to 8 days by hand on 2026-09-08, the daily briefing reported that settling as a business spike every morning.

The platform could learn this itself. It already runs the same queries day after day, so it can watch how a past day's number moves as the day ages and find the age at which it stops moving. Briefings, alerts and answers would then speak only about settled days, and label newer ones as still settling.

Starting points in the code today:

- The lag is a hand-set number today: `observation_lag_days` on an automation's investigate step, default 1 ([aughor/automations/temporal.py:174](aughor/automations/temporal.py:174)).

## 5. Tell people when an answer they were given is no longer true

*Suggested by Claude, 2026-09-13* · **BUILT 2026-09-23 — ROADMAP §3.28** (behind the `answers.recheck` flag, off)

When the data behind a past answer changes enough to change the answer (late rows, a backfill, a corrected metric definition), the platform re-checks it and tells whoever received it: "On Tuesday we told you 1,744. With the rows that arrived since, it is now 1,802." A product recall, for numbers.

Starting points in the code today:

- Answers already come with a signed Trust Receipt that records what was answered and how ([aughor/trust/receipt.py](aughor/trust/receipt.py)).
- The briefing already stamps which version of its inputs it was built on, so it can tell when it has gone stale ([aughor/knowledge/briefing.py:804](aughor/knowledge/briefing.py:804), through `aughor.kernel.rebuild`). The same stamp could sit on a receipt.

## 6. Alerts that prove they work

*Suggested by Claude, 2026-09-13 · **BUILT 2026-09-23 — ROADMAP §3.26**: `POST /monitors/{id}/backtest`, `POST /monitors/{id}/drill`, `GET /monitors/{id}/proof`; the runner, the backtest and the Watcher share one rule*

Two halves:

- **Backtest before switching an alert on.** Replay it over the last year and show how often it would have fired, and on which days ("41 times, 30 of them Mondays"). Tune it before it interrupts anyone.
- **Fire drills after.** An alert that never fires looks exactly like a broken one. Now and then, feed each alert a made-up outlier (without touching the warehouse) and check the whole path still works, through to the Slack message. Show "last proven working" on each alert.

Silent non-firing has already happened here: an instruction added to scheduled briefings on 2026-09-05 never ran once until it was found on 2026-09-08, and its test passed the whole time.

Starting points in the code today:

- Automation runs already record whether each tick fired ([aughor/automations/models.py:546](aughor/automations/models.py:546)), and monitors keep their last alert ([aughor/monitors/runner.py:63](aughor/monitors/runner.py:63)).
- A proposed automation already gets a one-off dry run ([aughor/automations/propose.py:290](aughor/automations/propose.py:290)). A backtest would run the same check at past dates.
- The anomaly check works on daily values over a rolling window ([aughor/monitors/runner.py:285](aughor/monitors/runner.py:285)).

## 7. Fact-check a document against the data

*Suggested by Claude, 2026-09-13 · **BUILT 2026-09-23 — ROADMAP §3.25**: `POST /factcheck`, `POST /factcheck/upload`, `@aughor check:`; every claim checked through the platform's own answer path*

Paste a board memo or an email, or upload a PDF deck. The platform finds every number in it and checks each against the warehouse: it matches, it doesn't (and why: refunds excluded, a different date range), or it can't be checked. The platform stops being only something that writes reports and becomes something that checks everyone's.

Starting points in the code today:

- The platform already checks the numbers in its own reports against the query results ([aughor/agent/verify.py](aughor/agent/verify.py)). This points the same check at documents people wrote.
- Charts inside PDFs are already read back as tables ([aughor/knowledge/charts.py](aughor/knowledge/charts.py)).

## 8. Retrospectives on what the platform missed

*Suggested by Claude, 2026-09-13*

When someone finds a big move by asking about it, and neither exploration nor any alert flagged it, the platform runs a short blameless review of itself. Was there no alert on that metric? Was the exploration window too short? Did briefing triage hold it back? It then proposes the fix, such as a new alert or a wider window.

Starting points in the code today:

- Briefing triage already holds signals back and records why ([aughor/knowledge/triage.py](aughor/knowledge/triage.py), described at [aughor/knowledge/briefing.py:399](aughor/knowledge/briefing.py:399)).
- The platform can already draft automations for review ([aughor/automations/propose.py](aughor/automations/propose.py)).
- Exploration's time window is chosen in [aughor/explorer/agent.py:783](aughor/explorer/agent.py:783).

## 9. An attention budget for each person

*Suggested by Claude, 2026-09-13*

Each person gets a fixed number of interruptions a week, across alerts, briefings and inbox items. Everything competes for those slots on expected value. Things a person never opens lose their place, and the platform shows what it held back and why. This matters more once idea 2 starts proposing alerts on its own.

Starting points in the code today:

- Monitors already have an anti-flap debounce so they don't re-alert people ([aughor/automations/engine.py:246](aughor/automations/engine.py:246)).
- Briefing triage already ranks findings by business impact ([aughor/knowledge/briefing.py:405](aughor/knowledge/briefing.py:405)).

## 10. The data shopping list

*Suggested by Claude, 2026-09-13*

For the questions a business in this industry usually asks, show which the connected data can answer, which it can't, and exactly what would unlock each one ("to compute customer acquisition cost, connect marketing spend by channel"). The platform shows its gaps and tells the organisation what to connect next.

Starting points in the code today:

- Playbook entries already name the metric they depend on (`trigger_metric`, [aughor/playbook/models.py:10](aughor/playbook/models.py:10)).
- Idea 2's mapping of industry metrics would produce the list of questions.

## 11. Receipts that travel with the number

*Suggested by Claude, 2026-09-13*

Every chart or number that leaves the platform, in a PDF or a slide, carries a short link to its Trust Receipt. Anyone who meets that number in a deck months later can open the link and see the query, how old the data was, and whether it is still true (idea 5).

Starting points in the code today:

- A receipt page already exists at `GET /receipt/{receipt_id}` ([aughor/routers/receipt.py:37](aughor/routers/receipt.py:37)), and receipts are signed ([aughor/trust/receipt.py:9](aughor/trust/receipt.py:9)).
- The PDF and slide exports ([aughor/export/pdf.py](aughor/export/pdf.py), [aughor/export/slides.py](aughor/export/slides.py)) don't link back to receipts today.

## 12. Guess before you look

*Suggested by Claude, 2026-09-13*

Before revealing a key number, say in the weekly briefing, invite people to guess it. Over time the platform learns where the organisation's picture of itself is most wrong. That's where an insight is worth the most, so exploration and briefings lean there. It's opt-in, and it's the oddest idea here.

Starting points in the code today:

- People can already accept, correct or reject a finding ([aughor/routers/verify.py:33](aughor/routers/verify.py:33)). Guesses would be a second record of what people believed, kept beside those verdicts.

## 13. Judge a recommendation against what would have happened anyway

*Suggested by Claude, 2026-09-13*

Comparing a metric before and after a recommendation credits the recommendation with seasonality and trend. Compare the after-value with what the metric's own history predicted for that period instead: did it land outside its expected range?

Starting points in the code today:

- Recommendation outcomes already have fields for the metric before and after ([aughor/playbook/outcomes.py:27](aughor/playbook/outcomes.py:27)).
- Idea 2's per-metric distributions would supply the expected range.

## 14. A UI that doesn't look like AI slop

*Thought through by Claude, 2026-09-13*

**What slop is.** AI-made UI looks like slop because every choice falls to the average: the average accent (purple), the average layout (cards), the average copy (filler), and equal weight for everything because nothing was chosen as primary. Taste is mostly decisions and subtraction. So the fix is to make the decisions explicit, and make them hard to skip.

**Already done.** The 2026-09-09 audit (Arc PX, ROADMAP.md §3.14) found the slop was mostly words and navigation: machine text on screen, screens that said false things, and the best features given the least design. All seven waves shipped, and its rules stand: no machine text on screen, an empty screen offers the action that fills it, the differentiator gets the design budget. It judged the visual layer fine, and colour really is: every Tailwind colour family is mapped onto the theme in `web/styles/tokens.css`.

**What it didn't reach, measured 2026-09-13:**

- **Faint text everywhere.** On the dark ground `--t3` has 4.23:1 contrast and `--t4` 2.76:1 (4.05 and 2.46 on light), against WCAG's 4.5:1 for normal text. Components reference them 774 and 515 times. Faint grey on near-black is one of the most recognisable looks of a generated dashboard. Raising the two tokens changes every one of those at once; that decision was left open on 2026-08-22.
- **The AI costume.** The sparkles icon marks Notifications ([web/app/page.tsx:342](web/app/page.tsx:342)), the Recommendation Inbox ([web/app/page.tsx:2295](web/app/page.tsx:2295)) and agent runs, drawn in violet beside blue chat ([web/app/page.tsx:784](web/app/page.tsx:784)). Violet is the most-used colour after the greys (209 class uses). It's the generic "this is AI" signal, not a chosen one.
- **Each component decides its own look.** 219 components hold 4,463 inline `style={{…}}` objects. The tokens are shared, but spacing, emphasis and layout get decided again in every file. The seven lint gates check that values come from the scale; nothing checks that similar screens are built the same way.
- **Sprawl.** One 2,465-line `web/app/page.tsx` switches between 35 tabs. That's a lot of destinations for a person to hold in their head.

**How to make sure:**

1. **Write the decisions where the builder reads them.** Much of this UI is written by AI agents, and an agent's defaults are the slop. `web/AGENTS.md` is loaded by every Claude session working in `web/` (through `web/CLAUDE.md`), so the house style belongs there: the voice, the density, what each colour means, the one primary action on each kind of screen, and a banned list. Name references rather than adjectives: the SQL editor already follows DataGrip, chat should feel like a frontier-LLM chat, and the audit named Agent Ops, the SQL workbench and the Integrations copy as screens that already show judgement.
2. **Keep the libraries, change the decisions.** The answer is not a hand-built custom look (the 2026-08-26 call was to lean on library defaults). The decisions live in tokens, layout and words.
3. **Make the gates catch slop, not just off-scale values.** The vocabulary ratchet already scans `web/` for retired terms ([tests/unit/test_vocabulary_ratchet.py:31](tests/unit/test_vocabulary_ratchet.py:31)); add slop copy to it (Unlock, Seamless, "Great work", exclamation marks, emoji). Add one-way ratchets, like the raw-button one, for faint tokens used as text colour, the sparkles icon, inline style objects and the tab count.
4. **Look at every UI change the way a person does, with ugly real data.** Screenshots in both themes, on the messiest real connection: long names, nulls, zero rows, huge numbers. Demo data hides slop; "1 entities", a raw `0.315801` and a "2014" tile were all found on real data.
5. **Use a critic that isn't the builder.** Before a UI change merges, a separate review pass gets only the screenshots and the house-style rules, and is asked to find slop, not to approve.
6. **Read all the words at once.** Most slop is copy. Once a release, dump every user-visible string into one file and read it top to bottom. Repetition, filler and machine text stand out together in a way they never do one screen at a time.
7. **Set the bar with a human designer once.** The gates can hold a standard but can't invent one. An afternoon with an experienced product designer on the five most-used screens, turned into the house-style rules and the banned list, gives the gates something worth holding.

## Codos idea set

Every idea tagged *Codos idea set* under its title belongs to this set. **Planned 2026-09-22 as Arc CB — ROADMAP §3.21, eight waves in the user's order; the four shaping answers are §6 item 30.** The ideas came from reading [codos.ai](https://www.codos.ai/) on 2026-09-22, mainly its [company brain page](https://www.codos.ai/company-brain) and its [benchmark post](https://www.codos.ai/blog/aethos-enterpriserag-benchmark). Codos deploys an on-premise "company brain": a graph of people, projects, commitments and decisions. It is built by extracting small dated claims from what employees write and say (Slack, email, meeting notes, documents), and agents read it over MCP. Aughor's context graph is similar machinery pointed at what the warehouse measures. Its node types are table, metric, glossary term, domain, finding and brief ([aughor/ontology/context_graph.py:35](aughor/ontology/context_graph.py:35)), and it allows no model-inferred source at all ([line 40](aughor/ontology/context_graph.py:40)), where theirs is built from model extraction.

Two things were judged not worth copying. Crawling Slack history and email bodies goes against the hub's first law, that the hub owns meaning and not data ([ROADMAP.md:6344](ROADMAP.md:6344)). And their retrieval benchmark is not a race worth entering: in their own numbers the graph adds about 4.5 points over a strong model doing plain file search.

## 15. Show how much of the business the platform can see

*Codos idea set · suggested by Claude, 2026-09-22*

Codos puts one number in front of the executive: the share of the company's working context that AI can see. Their reasoning is that an agent with partial context is confidently wrong, people stop trusting it after the third mistake, and so a gap costs far more than its size. Their screen also names the single gap holding up the most work ("three pilots are stalled on the same gap, fix it once").

Aughor computes pieces of this number and shows none of them. It would say what share of the connected tables are mapped to business objects, and which one missing definition is holding the most back. We have lived the second half. On 2026-09-18, on theLook, one missing approved `revenue` definition held the Slack send, floored confidence to LOW and put a warning on top of every revenue answer. Approving it cleared all three, and nothing on screen had said that this one definition was the most valuable thing to fix.

Idea 10, the data shopping list, is the other half: this idea says how much is covered, idea 10 says what to connect to cover more.

Starting points in the code today:

- `Coverage` in [aughor/ontology/declarations.py:60](aughor/ontology/declarations.py:60) already computes the share of tables mapped, takes declared exclusions out of the denominator, and bands the result green, orange or red ([line 77](aughor/ontology/declarations.py:77)). Only its unit test imports it.
- The graph's review queue already lists its own weak points (unprobed joins, isolated tables, contested findings), each with a question and a one-click check ([aughor/ontology/graph_questions.py:78](aughor/ontology/graph_questions.py:78)).
- The warrant audit already reports the share of joins that were measured and not just matched by name ([aughor/ontology/graph_warrant.py:219](aughor/ontology/graph_warrant.py:219)).
- The departure gate holds a send when no approved metric defines the number ([aughor/govern/departure.py:546](aughor/govern/departure.py:546)). Counting holds per missing definition gives the "fix this one and N unblock" line.

## 16. Put a date on every fact, and keep what it replaced

*Codos idea set · suggested by Claude, 2026-09-22*

Codos dates every claim and keeps each record's history. An old plan imported today keeps its original date and does not displace a newer decision. They also separate two events that look alike: "the date was wrong" corrects a claim, "the launch moved" records a real change.

In Aughor's context graph a fact has a source and no date, and a node holds only its current state. History is whatever git kept. When a finding replaces an older one, the older one's id is kept and its text is dropped. The hub's provenance envelope, built for a different arc, already has the fields this needs. So the platform has two provenance carriers, and only one of them knows when.

Idea 5 needs this too. To tell someone an answer is no longer true, the platform has to hold what the answer used to be.

Starting points in the code today:

- The graph's `Provenance` carries `source`, `measured` and `note`, and nothing else ([aughor/ontology/context_graph.py:57](aughor/ontology/context_graph.py:57)).
- The hub's `Provenance` carries `observed_at`, `valid_until` and `author` ([aughor/hub/provenance.py:67](aughor/hub/provenance.py:67)).
- Saving the graph bumps a version number and overwrites the file ([aughor/ontology/context_graph_store.py:72](aughor/ontology/context_graph_store.py:72)).
- A superseded finding leaves only its id behind ([aughor/ontology/finding_consolidation.py:239](aughor/ontology/finding_consolidation.py:239)).

## 17. Check what people say against what the data shows

*Codos idea set · suggested by Claude, 2026-09-22*

The strongest example on Codos's site was done by hand. In one client build they put each owner's reported status next to what the records showed, found that some targets and actuals were in different units, and turned each gap into a question the owner could answer.

Aughor can do that by machine, because it can run the check against the warehouse. The claims people make (an OKR sheet, a board memo, a reply in a filed Slack thread) come in at the "said" tier. Each one that states a number is checked against the data. Agreement raises it to "measured". Disagreement becomes a question to its owner. "Can't be checked" stays visible as unknown. This would be Aughor's version of a company brain: not everything people said, only what they said that the data can confirm or contradict.

Idea 7 (fact-check a document) is the one-off version. This is the standing one. It depends on idea 18, because the question needs somewhere to go.

Starting points in the code today:

- The hub's authority ladder already has the tiers, from `measured` down to `said` and `inferred` ([aughor/hub/provenance.py:34](aughor/hub/provenance.py:34)).
- A reply in a filed Slack thread already arrives as a staged note ([aughor/routers/arrivals.py:38](aughor/routers/arrivals.py:38)) and becomes a context piece ([aughor/hub/adapters.py:17](aughor/hub/adapters.py:17)).
- No prompt sees those pieces, because the injection list is empty until a kind earns its place ([aughor/hub/injection.py:22](aughor/hub/injection.py:22)). A "said" note that has been checked against the data is a candidate for the first kind let through.
- The prose mapper already extracts only what a text explicitly states ([aughor/intake/prose.py:35](aughor/intake/prose.py:35)).
- The platform already checks the numbers in its own reports against query results ([aughor/agent/verify.py:154](aughor/agent/verify.py:154)).
- Asking the owner already exists for one case. When readings of a metric disagree at departure, the owner is asked ([aughor/govern/departure.py:768](aughor/govern/departure.py:768)), and the answer is remembered so it is asked once ([line 408](aughor/govern/departure.py:408)).

## 18. Owners the platform can reach

*Codos idea set · suggested by Claude, 2026-09-22*

Codos resolves "Nora" in a transcript to a person, or leaves the match open until there is more evidence. In Aughor an owner is free text on a metric, a process and a business rule, and a glossary term has no owner at all. Routing understands `group:finance` and `user:a@b`, and leaves "Ana (logistics)" as the display text it always was, so a question for Ana has nowhere to go.

Ideas 17, 20 and 22 all end in "ask the owner", so they depend on this. The existing rule stays: never link a person by matching a display name. Someone links "Ana (logistics)" to a user once. Until then the platform shows the owner as unresolved, and says so where it would have asked.

Starting points in the code today:

- Free-text owners: [aughor/semantic/metrics.py:76](aughor/semantic/metrics.py:76), and `Process` and `BusinessRule` in [aughor/ontology/models.py:680](aughor/ontology/models.py:680) and [line 700](aughor/ontology/models.py:700). The glossary has no owner field.
- `owner_principal` decides whether an owner string can be routed ([aughor/rbac/routing.py:53](aughor/rbac/routing.py:53)).
- The identity resolver never creates a link on its own ([aughor/identity/resolver.py:15](aughor/identity/resolver.py:15)).

## 19. Remember a rejected duplicate

*Codos idea set · suggested by Claude, 2026-09-22*

When a Codos operator splits two people who were merged by mistake, the system keeps the reason and uses it in later matching. Aughor suggests near-duplicate business objects (Customer and Client) from embedding similarity, recomputed on every read. Nothing records a "no, these are different", so a pair someone already rejected comes back every time.

The ontology already does this right in two other places, so this is a pattern to repeat, not a new design.

Starting points in the code today:

- The suggestions are computed on each call to `GET /ontology/duplicate-entities` ([aughor/routers/ontology.py:941](aughor/routers/ontology.py:941)) by [aughor/ontology/dedup.py](aughor/ontology/dedup.py), which has no store of decisions.
- A dismissed ontology recommendation is never brought back ([aughor/ontology/recommendations.py:267](aughor/ontology/recommendations.py:267)).
- The explorer remembers a proposal a person withdrew and does not make it again ([aughor/ontology/explorer.py:516](aughor/ontology/explorer.py:516)).

## 20. One action beside each Briefing item

*Codos idea set · suggested by Claude, 2026-09-22*

Codos's executive screen is a short feed. Each item is a finding in two sentences with one action under it ("Pause the other 3 pilots"). Aughor's Briefing ranks findings by business impact and stops there. Nothing in the Briefing code offers an action. Recommendations with an Execute button live in the Recommendation Inbox, one card per investigation, a screen away from where the finding is read.

Put the single best action under each Briefing item, sent through the same gated path the inbox uses. We have already recorded that features here stall at tested and never get used. This puts the action where the reader already is.

Starting points in the code today:

- The Briefing narrative and its ranking by business impact: [aughor/knowledge/briefing.py:387](aughor/knowledge/briefing.py:387) and [line 405](aughor/knowledge/briefing.py:405).
- Executing a recommendation through a Slack, webhook or Jira trigger, behind the departure gate: [aughor/routers/actions.py:168](aughor/routers/actions.py:168).
- The inbox itself: [web/components/RecommendationInbox.tsx](web/components/RecommendationInbox.tsx).
- Past success already re-ranks which recommendation comes first ([aughor/playbook/retriever.py:45](aughor/playbook/retriever.py:45)), which is how "the single best action" would be chosen.

## 21. What the company is trying to do this quarter

*Codos idea set · suggested by Claude, 2026-09-22*

Codos keeps a third store beside stable facts and the operational record: working memory, holding synthesis and priorities. Aughor stores nothing about what the organisation is working on now. The nearest thing is the north-star metrics a model infers for each connection. So the Briefing ranks a finding by how big the move is and whether it touches a north-star metric, never by whether it bears on a goal leadership has set.

A short list of priorities, written by people, each naming a metric and a target. Triage ranks findings against it, and the Briefing can say "this bears on the goal to cut returns". People write it and the platform never does, in keeping with the rule that people edit the organisation's ontology.

Starting points in the code today:

- North-star metrics are inferred per connection ([aughor/business_profile/models.py:55](aughor/business_profile/models.py:55)).
- Organisation settings are already written by people and already win over inference ([aughor/orgsettings/models.py:20](aughor/orgsettings/models.py:20)). That makes them the natural home.
- The impact score is where a declared priority would count ([aughor/knowledge/triage.py:402](aughor/knowledge/triage.py:402)).
- The hub's scope ladder already has an `organisation` level ([aughor/hub/provenance.py:45](aughor/hub/provenance.py:45)).

## 22. Decide when to ask whether a recommendation worked, at the moment it is accepted

*Codos idea set · suggested by Claude, 2026-09-22*

An open question of ours: when is a person asked whether a recommendation worked? Codos's practice suggests an answer. They agree the baseline with finance before building anything, name an owner, and review every week. The outcome question is scheduled before the work starts.

For Aughor: when someone marks a recommendation accepted, record the metric, its value now, and a review date. On that date the platform measures again and asks the person who accepted it. Today the outcome record has fields for the metric before and after, but they arrive only with the request that logs the outcome. Nothing schedules a second measurement and nothing prompts anyone, which may be why the loop runs and nobody has used it.

Idea 13 then says how to judge the second measurement.

Starting points in the code today:

- The outcome record, with `metric_before` and `metric_after` ([aughor/playbook/outcomes.py:20](aughor/playbook/outcomes.py:20)), written by `log_outcome` ([line 56](aughor/playbook/outcomes.py:56)) from a single caller ([aughor/routers/investigations.py:6205](aughor/routers/investigations.py:6205)).
- No review date exists anywhere in [aughor/playbook/](aughor/playbook/).
- Verified and rejected outcomes already update each playbook entry's success rate ([aughor/playbook/outcomes.py:108](aughor/playbook/outcomes.py:108)), so an outcome that gets asked for does get used.

## 23. One central path for every ask, and the destination decides only the delivery

*Noted 2026-09-23 · STUDIED and drafted into the roadmap the same day as **Arc CP**, §3.22, **ADOPTED** — §6 item 31, all four clauses YES — the measurements there supersede any estimate here*

Query processing, formatting and the safeguards should happen once, centrally, whatever the ask is and wherever the answer is going — a quick question, a deep investigation, a Slack thread, an email, a scheduled automation. Where the answer is going then decides its length, breadth and format, and nothing else.

The pattern this repo already believes in for charts. `POST /charts/svg` exists so that "a chart posted into Slack is the chart the platform itself would have drawn", running the same resolver as the browser and the PDF. The idea is that principle applied to the whole answer rather than to one exhibit.

The cost of not having it, all found in one session on 2026-09-23:

- **The same operation, implemented twice.** Rasterizing an SVG lives in [aughor/export/echarts.py](aughor/export/echarts.py) for Python callers and again in [bots/slack/src/chart.ts](bots/slack/src/chart.ts) for the bot. Both had the same defect — a transparent background that made dark ink vanish on a dark Slack theme — and the fix had to be made twice, the second time only because a screenshot showed it still live.
- **A decision that drifted to the edge.** The browser resolved a chart's type before choosing an engine; the headless path resolved it one layer later. The result was that a category plus an additive measure at 7–24 rows drew nothing at all on every headless surface.
- **Three ways to put text in Slack**, each with its own truncation: [aughor/slackbots/post.py:43](aughor/slackbots/post.py:43), [aughor/notifications/executor.py:167](aughor/notifications/executor.py:167), and the `slack.chat.postMessage` chain operation at [aughor/integrations/operations.py:213](aughor/integrations/operations.py:213).
- **Two implementations of "attach the exhibits"**: [bots/slack/src/bot.ts:158](bots/slack/src/bot.ts:158) for the interactive path and `_attach_chart` in [aughor/automations/engine.py](aughor/automations/engine.py) for the scheduled one.

The sharper half of the idea: **the core has to emit structure, not prose.** A real Slack answer measured on 2026-09-23 carried a markdown table, then the transport attached the same five rows again as the exhibit grid — neither knew the other had it. The same answer narrated "No guard receipts fired on this query", because the tool description at [aughor/agent/converse_tools.py:611](aughor/agent/converse_tools.py:611) asks the model to report guard receipts to the reader, which is the opposite of the decision that took receipts off Slack messages. Both are the same fault: prose has no fields, so a destination cannot select from it, and shortening it needs a second model call — which spends back the efficiency the centralising was for.

If the core emitted a typed envelope instead — headline, grid, caveats, provenance, follow-ups — Slack takes the headline, the grid and the top caveats; email takes all of it; a PDF adds the exhibits. Selection is free. The `/ask` stream's frames (`chart_type`, `chart_config`, the grid frames) are already a partial envelope that the Slack bot consumes; the gap is that the prose is not in it.

Two boundaries worth keeping:

- **Decisions central, encodings local.** Which chart a grid wants is a decision and belongs in the core. PNG width, raster background, Slack's 40 KB cap, "attach as CSV past N rows" are encodings and belong at the edge. The treemap defect above was a decision that had drifted into an encoding's place.
- **A central safeguard still needs to know who is accountable at each exit.** The engine gates every unattended send at the departure gate, and the inbox's accepted send is deliberately ungated because a person read the text and pressed send. That exception is right, so "one code path" is not quite the rule — "one gate, told who is answering for this exit" is.

## 24. Collapse quick and deep, and let a typed judgement pick the treatment

*Noted 2026-09-23 · STUDIED and drafted into the roadmap the same day as **Arc CP**, §3.22, **ADOPTED** — §6 item 31, all four clauses YES. The study REFRAMED this idea: `deep_analysis` is chosen 0 times in 60 tool uses, so on the interactive path the quick/deep choice is not being made badly — it is not being made at all*

Today the split between a quick answer and a deep investigation is a tool the model picks: `deep_analysis` at [aughor/agent/converse_tools.py:353](aughor/agent/converse_tools.py:353), declared at [line 640](aughor/agent/converse_tools.py:640), against the ordinary answering path, with [aughor/runners/investigation.py:234](aughor/runners/investigation.py:234) behind it. Collapse the two and let a judgement bundle decide the treatment from the question itself, on criteria we name and can measure.

The precedent is Adaptive-RAG (NAACL 2024), which routes a question to no-retrieval, single-step or multi-step by predicted complexity and reaches 1.03 average steps where a fixed multi-step pipeline pays for every one.

The primitives are already typed in [aughor/judgment/seam.py](aughor/judgment/seam.py) — `Noul`, `Choice` and `Score` over 2–10 ordered levels, after TypeSafe's Jev. The hosted binding accepts **noul bundles only** ([aughor/judgment/jev.py:118](aughor/judgment/jev.py:118)), because the banded cascade never asked for anything else, so Choice and Score are a binding to fill in rather than a design to invent. Jev evaluates a mixed bundle in parallel and its latency scales with tokens rather than question count, so a ten-question bundle costs about what one does — ask speculatively.

A first set of levers:

- **Choice** — treatment: `lookup · single_query · multi_query · investigation`; intent: `describe · compare · diagnose · forecast · act`, where `diagnose` is what earns depth and `act` belongs to the approval gate.
- **Score** — specificity 0–3 (does the ask name metric, grain, window and filter?); steps implied 0–4, which is the budget; stakes 0–3, from a private thread up to a scheduled post, which sets both verbosity and how strict the gate should be.
- **Noul** — is the ask causal? does it name a governed metric with an approved definition? is it answerable from the last result without new SQL? is it a follow-up composing on prior state?

**Classify only what is uncertain.** Where the answer is going, who asked and which connection is in play are known facts; looking them up costs nothing and inferring them adds a way to be wrong. This is also the clean join with idea 23: the judgement infers the question's properties, the destination's policy is looked up, and the envelope combines the two.

**The blocker is calibration, and it is the whole idea's load-bearing part.** The seam says it plainly: *"The probability is STATED, not measured."* No provider here exposes logprobs, so every probability is a number the model was asked to write into a schema — "not calibration, but the input calibration is measured ON". [evals/judgment_battery_eval.py](evals/judgment_battery_eval.py) is the instrument that would say whether those numbers mean anything, and it has never been run with real model calls. The routing literature is consistent that thresholds set by intuition are miscalibrated, that fixing calibration is where the savings actually come from, and that an escalation rate of only 1–3% can erase a cascade's savings entirely. Routing live answers on uncalibrated self-reported confidence would be building the decision on the one number nobody has checked.

So the first step is **shadow mode**: extend the binding to Choice and Score, classify every incoming ask, and log the treatment it would have chosen beside what actually ran. No routing and no risk to an answer, and it produces the calibration corpus the battery needs as a by-product of ordinary use. Only once that says the numbers mean something does anything route on them, behind a flag, the way `semops.jev_cheap_tier` already is at [aughor/kernel/flags.py:92](aughor/kernel/flags.py:92).

A useful built-in check comes free: a flat distribution over `treatment` means the categories overlap. The taxonomy is wrong, not the question.
