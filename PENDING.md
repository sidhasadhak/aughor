# Pending — the list we work through

*Cut 2026-09-23 from [ROADMAP.md](ROADMAP.md) (every §3 arc, §5 and §6) and [IDEAS.md](IDEAS.md) 1–14.*

ROADMAP.md stays the plan of record and IDEAS.md the parking lot. This file is neither: it is the
checklist of what those two say is still open, in plain words, one line each, so that finishing an
item is a tick here and not a re-read of 9,000 lines.

**How to keep it honest.** Tick an item (`[x]`) only when it is MERGED, and add the date and PR on the
same line. Never delete a line — a struck item is a record, a missing one is a question. Before starting
an item, re-measure it: this list was taken from prose, and the roadmap's own lesson is that a prose
claim rots silently. If measuring shows an item was already done, tick it and say what showed it.
**⚑** marks an item waiting on a decision, a credential or a paid model run — those are the user's.

---

## The order of work — by impact (agreed 2026-09-23; revised the same day: 10 off, 11–15 added from Arc ON)

Ranked by how many answers or people each one improves, and whether it unblocks others.
Items 11–15 were drawn from the ontology arc at the user's direction ("an important part of the core engine") and are
ranked among its leftovers, each re-measured against the code on 2026-09-23 before it was placed.

First build order: 2 → 3 → 6 and 1 → 10 — all merged in #545 except 10, which the user took off.
Build order now: 7, 8 and 9 (the user's focus); on the ontology, 11 → 12 (terms get proposed, then get recognised),
with 14 first for any receipt that must reproduce on a fresh clone; 13 sits beside 9 — both are screens over stores
nobody can see today.

1. [x] **The structured answer** (CP-4, §3.22) — every answer, whether in chat, Slack, a PDF or a scheduled post, comes from one structured result and each destination takes only what it needs; it also stops the model narrating "guard receipts" to readers (`aughor/agent/converse_tools.py:611`) and makes every new destination cheap. *Built 2026-09-23 on `claude/pending-top-nine`, live receipt on theLook turn `47a130145460`; merged 2026-09-23 · #545.*
2. [x] **Learn when numbers settle** (idea 4) — watch how a recent day's numbers keep changing as it ages, and speak only about days that have stopped moving; today theLook's lag is an 8-day number set by hand, and items 3 and 8 depend on this. *Built 2026-09-23 (ROADMAP §3.23) on `claude/pending-top-nine`; first reading taken on theLook, first verdict possible 2026-09-26; merged 2026-09-23 · #545.*
3. [x] **A built-in outlier-alert agent** (idea 2) — after each exploration, pick the industry metrics that fit, learn what is normal for each, and propose alerts; the anomaly check and the notify effect already exist. Needs item 2 first or it alerts on data that is still settling. *Built 2026-09-23 (ROADMAP §3.24) on `claude/pending-top-nine` as the Watcher's job; merged 2026-09-23 · #545.*
4. [ ] **Let a judgment pick quick or deep** (CP-3, §3.22) — in chat, deep analysis was chosen 0 times in 60 tool uses and a deep run costs ~4× a normal one, so routing fixes quality one way and cost the other; behind a flag, only after CP-2's week of shadow data says the labels can be trusted. *Blocked until ~2026-09-30: the shadow went live 2026-09-23 and CP-2's thresholds are fitted to that corpus, never chosen — skipped on 2026-09-23, to be taken once the week is in.*
5. [x] **Fact-check a document** (idea 7) — paste a memo or upload a deck and every number in it is checked against the warehouse; the report-number check, chart reading from PDFs and CB-8's said-versus-measured check are most of the machinery. *Built 2026-09-23 (ROADMAP §3.25) on `claude/pending-top-nine`: two API doors + the Slack `check:` verb, live receipt on theLook (2 measured, 2 contradicted); merged 2026-09-23 · #545. Still no web door.*
6. [x] **Alerts that prove they work** (idea 6) — replay an alert over the past year before switching it on, and later feed it a fake outlier to prove the whole path still works, with "last proven working" on each; a broken alert once went unnoticed here for three days while its test passed. *Built 2026-09-23 (ROADMAP §3.26) on `claude/pending-top-nine`: backtest, drill and proof doors, one shared rule; merged 2026-09-23 · #545. Still no web buttons.*
7. [ ] **Briefings by period** (idea 3) — daily, weekly, monthly and yearly briefings, each written for its window; today there is only the whole-history one, and the day/week subscriptions send an alert digest, not a briefing. *Built 2026-09-23 (ROADMAP §3.27) on `claude/determined-bohr-qh3b1p` behind the `briefing.by_period` flag (off): each headline metric measured for the window by its own trend query cut to it, the period's alerts and recorded findings, a narrator told its version, a scheduled send re-measured line by line; receipt over HTTP on a DuckDB shop (the week's GMV equal to hand SQL), not yet on a real warehouse; unmerged.*
8. [ ] **Tell people when an answer goes stale** (idea 5) — re-check past answers and tell the person when late data changes one ("we said 1,744; it is now 1,802"); CB-1 already keeps what each fact replaced, and item 2 tells a real change from late arrivals. *Built 2026-09-23 (ROADMAP §3.28) on `claude/determined-bohr-qh3b1p` behind the `answers.recheck` flag (off): each chat answer's own query re-run daily and compared on its own labels at the 5% noise band, late rows told from a restatement by the learned lag, recorded on the answer, told in its Slack thread through the departure gate or shown under the web answer; receipt over HTTP on a DuckDB shop, not yet on a real warehouse or Slack; unmerged.*
9. [ ] **The company-brain map** (Arc CB, §3.21) — one screen where every store behind the "brain" is a box with a live count; eight built features with no screen are the built-and-never-used failure this project keeps repeating, and it is the demo the user asked for.
10. ~~[ ] ⚑ **Email in and out** (HB-5, §3.18) — the one major destination that does not exist at all; waits on the user's Google OAuth client, and is cheapest right after item 1.~~ *Taken off this list 2026-09-23, the user's call; still open under the hub arc below.*
11. [ ] ⚑ **Every new connection gets its business terms proposed** (Arc ON, §3.15) — the ontology lifts answers only where a question's business terms (processes, rules, promises) are declared: on the 2026-09-15 re-runs LuxExperience went from 5 of 16 right to 16 of 16 and Olist from 7 of 15 to 14 of 15, and plain SQL's misses were silent, not refused. A fresh connection has none, because the explorer that proposes them (`aughor/ontology/explorer.py`) runs only from the map's button; adding a connection runs the data explorer and the table-level build, not this. Wiring it is hours; the ⚑ is its quality gate — its one live check on LuxExperience fused two groups that should stay apart, it may run by default only with none, and re-checking is a paid model run.
12. [ ] **Recognise a business term however it is worded** (Arc ON) — the frame matches only declared words and synonyms a person typed (`aughor/agent/framing.py:80`); reworded questions scored 0 of 3, and a question that matches nothing loses the frame silently with no counter, so how often it happens is unknown. First count the misses (free, no decision), then grow the 3-item paraphrase set, then offer near-matches to the chooser that already picks among candidates — that last step reverses a rule ROADMAP §3.15 calls "by design", so it is the user's call. Worth little until item 11 gives connections terms to match.
13. [ ] **Object pages show what is known about each object** (Arc ON) — the findings panel is empty on every object page of every connection: it lists only findings whose SQL filters that exact object's key (`aughor/semantic/object_context.py:107`), exploration findings are aggregates by region, tier or status, and it reads only the home connection. LuxExperience's metrics panel is empty too: the shipped revenue and AOV are scoped to the samples and name a column LuxExperience lacks. Showing findings about the object's type or segment is the medium part; the rest is small. *Built 2026-09-23 (ROADMAP §3.29) on `claude/determined-bohr-qh3b1p`: the findings panel now lists, after the exact ones, findings about the object's segment and its type, each marked; on the samples customer C00042 the panel went from 0 to 3; the LuxExperience metrics half is still open; unmerged.*
14. [ ] **Declared terms survive a fresh clone** (Arc ON) — the Olist, LuxExperience and cross-connection declarations behind item 11's numbers live only on the builder's machine, keyed by machine-local connection ids; their shipped home, `data/shipped/ontology_overrides/`, does not exist yet, and `AGENTS.md` still says `data/ontology_overrides/` is tracked while `tests/unit/test_seed_overlay_frozen.py` fails if anything new is tracked there. Needs stable connection ids first; until then no fresh checkout can re-prove item 11 or 12.
15. [ ] ⚑ **The chat's main buttons reach the agent that holds the ontology's tools** (Arc ON) — Quick posts to `/chat` and the default Agent button to `/investigate`; only Edit, starters, clarify answers and re-runs reach the conversation agent, the one with the object tools. Both buttons still read the ontology through the shared answer core, so what they lose is the tools, and the gain is unmeasured. The switch is small; the ⚑ is cost — a conversation turn runs ~20k tokens — and it belongs in the same decision as item 4.

Just outside the list: the next industry package (insurance has public data to test on; payments does not) · numbers that link back to their source (idea 11) · the anti-AI-look UI work (idea 14, partly under way) · the fine-tuned text-to-SQL model (MI-4, needs far more training data than exists).

---

## Everything pending, by arc

### Central answer path — Arc CP (§3.22)
- [ ] CP-1 shadow classification — built and live; every answered question gets a logged label (lookup · one query · several · investigation) that changes nothing yet, one model call per answer; needs about a week of rows before CP-2 can read them.
- [ ] CP-2 calibration — built; measures how far the labels can be trusted, and can only run once the week of shadow data exists.
- [ ] CP-3 route on the label — see top item 4.
- [x] CP-4 the structured answer — see top item 1; merged 2026-09-23 · #545.
- [ ] CP-5 one exhibit formatter — one shared table builder and one chart-image renderer for every destination; today there are three table builders and two renderers.

### Company brain — Arc CB (§3.21; all eight waves built)
- [ ] The map — see top item 9; it is also the only place fact dates and history would show.
- [ ] The "how much of the business we can see" share reads "unknown" for both BigQuery connections, because the profiler has nothing cached for them.
- [ ] A second Slack reply on the same object overwrites the first reply's check — claims are counted per object, not per reply.
- [ ] Screenshot of the owners panel still owed.

### Typed judgments — Arc JD (§3.20)
- [ ] ⚑ JD-1's agreement receipt and JD-4's corpus receipt — both are paid model runs not yet approved.
- [ ] The outside cheap judge (Jev) is on in the live app; nobody has checked whether it behaves live the way it did in testing (band occupancy ~7%, fallback rate).
- [ ] JD-6, a small local scorer — on hold behind JD-4's measurement.
- [ ] A2, sending close calls to a person — blocked because nothing yet produces a real confidence number (`converse.tool` never does).
- [ ] A3, the metric-definition report screen — built, never tried in the live app.
- [ ] A5 — users' questions are stored word for word in the decision log with no expiry, only a row cap.
- [ ] A6, auto-tuning metric definitions — held until ~150 human-labelled decisions exist; there are 5.

### The hub — Arc HB (§3.18)
- [ ] Group permissions are recorded but not enforced — waits on real sign-in.
- [ ] The full live run of the promise-breach chain: Slack alert → Jira ticket → ticket closed → Briefing shows before and after.
- [ ] Accepting a Slack send from the inbox does not file a thread the way automatic sends do.
- [ ] The links and probation queues have no screen — API data only.
- [ ] "That's wrong" said in a Slack thread does not come back as a correction.
- [ ] A deep report does not record whether its cause-and-effect claims survived their own checks.
- [ ] The ranker needs more note kinds, and should ask once when two equally trusted sources disagree.
- [ ] ⚑ Email in and out (HB-5) — the one major destination that does not exist at all; waits on the user's Google OAuth client, and is cheapest now that the structured answer (top item 1) has merged. Was top item 10 until the user took it off the list on 2026-09-23.
- [ ] Jira and Confluence through Atlassian's MCP server — built, never tried against a real Atlassian server.
- [ ] Slack thread replies without an @mention are not picked up (needs `message.channels` + a reinstall).

### Industry packages — Arc IP (§3.17)
- [ ] ⚑ Banking is built but inactive (draft) until a person reviews and activates it in the UI; activation must also stop "Retail Banking" matching the retail package.
- [ ] Payments & fintech next, then insurance, plus a risk-and-fraud function — payments has no public per-company data to test on and insurance does, which may flip the order.
- [ ] Loan-level lending metrics are not covered: delinquency buckets, roll rates, vintages, approval rates.
- [ ] ⚑ The paid with-and-without-package test on airline (gate 5), which the arc's proof depends on — waits on the user's go.
- [ ] More airline metrics — load factor needs a data download the user approves; others need revenue sources or checked ranges.
- [ ] The SQL auto-fixer ignores the packages' data-quality checks, and one wrong metric-name match still stands.
- [ ] Old data-quality queries still name sample tables; drafting a new package is still manual.
- [ ] The install's industry question is untested in a real Windows console; the profile prompt does not name the chosen industries.
- [ ] Promoting a package strips the comments from its `pack.yaml`.

### Install — Arc IN (§3.19)
- [ ] ⚑ `aughor migrate-state`, which moves the data out of the code folder, has never run for real — it needs the API stopped.
- [ ] `context_graph/` and `ontology_column_config/` are both tracked in git and rewritten by the app, so `aughor update` will eventually refuse on them (the same split `metrics.json` got).
- [ ] Moving `ontology_overrides/` into the data folder needs a safe top-up for installs that already migrated.

### Ontology — Arc ON (§3.15; finished, these are its leftovers)
*Every line below was re-measured against the code on 2026-09-23; the five with the most reach became top items 11–15.*
- [ ] ~~Computed fields cannot be summed or averaged in object queries,~~ and answers built by the compiler carry no badge. *Measured: formula fields carry the `measure` role and a test averages one (`tests/unit/test_object_bindings.py:661`), so the first half is stale; the badge half stands — the web lists the `compiled` event as one it never shows.*
- [ ] Formula fields cannot use columns from a type's extra linked tables. *Measured true; almost no one reaches it, since no tracked declaration has a formula field; about a day.*
- [ ] LuxExperience object pages show empty metrics and findings panels — see top item 13. *Measured: the findings half is empty on every connection, not only LuxExperience.*
- [ ] Model scores on objects (churn risk per customer) were never built — only the timeseries half of ON-5 was. *Measured true; no scoring code exists anywhere; a SQL-only stand-in such as days since the last order is possible now.*
- [ ] ~~The explorer does not run automatically when a connection is added.~~ The business-term explorer does not run when a connection is added — see top item 11. *Measured: the data explorer and the table-level ontology build do run on connection add.*
- [ ] Across connections: a hop into a second connection inside a sub-query is refused, and object pages show only the home connection's findings (the second half folds into top item 13). *Found by reading, not run: a formula field on a type in another connection is read as a real column (`aughor/semantic/object_query.py:695`), and the object page runs a cross-connection query's SQL directly though the compiler marks that SQL "not run" (`aughor/semantic/object_context.py:98`).*
- [ ] A question worded differently from the declared names is not recognised until a person adds a synonym — see top item 12.
- [ ] The Olist, LuxExperience and cross-connection declarations exist only as untracked local override files — see top item 14. *Measured: in a fresh clone they do not exist at all, and they cannot simply be committed, being keyed by machine-local connection ids.*
- [ ] Actions can flag a record but can never correct a source value. *Measured: refused on purpose by the read-only law (ROADMAP §6 item 14), and even a stored correction only attaches a note, never swaps the value.*
- [ ] The chat's Quick button skips the agent ~~— a filed defect~~ — see top item 15. *Measured: nothing was ever filed, and the default Agent button skips the conversation agent too.*
- [ ] ⚑ ~~The chat's object-query tool stays parked (§6 item 15) until there is a test set where plain SQL fails.~~ Decide the parked object-query tool. *Measured: that set exists and was run on 2026-09-15, and the tool lost to the frame that already ships — LuxExperience 10 of 16 against 16 of 16, Olist 7 of 15 against 14 of 15. Delete the flag and the tool, or pay for a re-run on a stronger model.*

### Design system — Arc UI (§3.16)
- [ ] ~30 components with hard-coded colours, ~46 bare "Loading…" lines and ~50 bare error lines to replace with proper states, plus the needs-human badge.
- [ ] The Human/Agent/Substrate switcher — held until there is a concrete use for it.

### Spotlight, the ⌘K operator — Arc SP (§3.11)
- [ ] The guide cannot search the text of packs and skills.
- [ ] Tools exposed over MCP do not describe their arguments properly, and clients must reconnect to see new ones.
- [ ] A person has never accepted, live, a suggestion the platform raised on its own; recurring live attack (red-team) drives are owed too.
- [ ] Cross-user questions ("who changed this?") are unbuilt until sign-in is on.
- [ ] Approval cards cannot show a real cost per run.
- [ ] Revise-in-place and the edit, monitor and brief drafts have not been proven live.
- [ ] Finishing a draft in the editor drops its timezone and its run-as agent.
- [ ] Slack approvals are not tied to the approver's identity, and there has been no proof run from a fresh clone.
- [ ] The weekly count of new agents and automations is not shown in Agent Ops.
- [ ] Answer buttons that open a screen or run a saved query wait on a deep-link registry.
- [ ] Table-popularity data is collected, but the switch that would use it is off.

### Machine intelligence — Arc MI (§3.9)
- [ ] ⚑ Should cap hits, guardrail events, metric enforcement and budget overruns show in the governance feed? Today they do not.
- [ ] The chooser-confidence switch has never run — it needs a question set with two competing measures, then it is kept or deleted.
- [ ] MI-4, the first fine-tuned text-to-SQL model — waits on 1,000 training pairs, 150 preference pairs, 150 gold examples and 30 days of guard data.
- [ ] MI-5/MI-6 — a model shipped with the app, adapter releases and RL training all wait behind MI-4.

### Documents — Arc DX (§3.13)
- [ ] Re-indexing does not re-read the original files, and documents cannot be placed on the canvas.
- [ ] Understanding what a chart inside a PDF shows needs reading the page as an image.
- [ ] Short Confluence and Notion pages silently disappear during indexing.

### Product polish — Arc PX (§3.14)
- [ ] Rename the eval suites by purpose; a lint check for machine-looking titles is unbuilt.
- [ ] A spend-cap refusal in chat should link to where the cap is raised.
- [ ] The consistency and federation screens wait on their feature flags.

### Knowledge intake — Arc KI (§3.10)
- [ ] Importing from private Google Sheets and Drive — parked until a deployment asks.

### Automations canvas — Arc DS (§3.7, §3.8)
- [ ] ⚑ The palette's Runs side rail was claimed as shipped and never existed — rewrite its spec or drop it.
- [ ] Ports and wires are not coloured by data type.
- [ ] Greyed-out palette items explain how to enable them but give no link.
- [ ] The "pause for a human" step works but is off by default, so it never fires on a normal install.
- [ ] Connectors, platform tools and our own MCP tools are listed in the palette but cannot be placed on the canvas.
- [ ] The metric step returns one number rather than a breakdown, and entities have no step.
- [ ] ⚑ Shipping bundles of steps inside packs is unbuilt, and no web-search vendor has been chosen.
- [ ] An automation newly exposed as an MCP tool only appears after the client reconnects.
- [ ] Promoting a chain's private SQL and reusing it in another chain has never been shown live.
- [ ] ⚑ Langflow steps we lack: file read/write, a calculator, the current date, a raw LLM step — a posture call, and the roadmap leans against the last one.
- [ ] The drag fix and the drop-a-wire gesture still need one hands-on test by a person and a React Profiler trace — no tool here can drive a drag.

### MCP, credentials and sign-in — VA-9d, VA-10, VA-11 (§3.1, §3.4, §3.5)
- [ ] ⚑ One Composio or Arcade tool run end to end through a custom MCP server with a real API key — the user's to run.
- [ ] MCP servers that need their own OAuth sign-in cannot be connected.
- [ ] Images and files returned by MCP tools are dropped.
- [ ] ⚑ Single sign-on against a real identity provider, and the live connect-use-revoke of a Google account — both wait on a Google OAuth client only the user can create.
- [ ] An automation can use another user's connected account — logged, not blocked, until sign-in is on.
- [ ] Plugging in an outside credential vault — deliberately later.

### Loose ends (§5 ledger)
- [ ] The playbook's outcome loop works end to end and nobody has ever recorded an outcome — CB-2 now asks at the review date; watch whether anyone answers.
- [ ] Two disabled DS-6/DS-7 fixture automations remain by choice; `automations.db` has never been VACUUMed (12.1 MB).
- [ ] Installing the `[export]` extra would restore chart pictures in PPTX decks — the user's environment.
- [ ] `secretvault.decrypt_secret` returns the ciphertext instead of failing when given a wrong key — noted during the #535 review, not in the roadmap, unverified.

---

## Ideas not yet taken up (IDEAS.md 1–14)

Ideas 15–22 became Arc CB and 23–24 became Arc CP. Git history to 2026-09-23 shows no work on 1–14.

- [ ] 1 · **Deleting a connection leaves nothing behind** — no data and no metadata about it in any store.
- [x] 2 · **A built-in outlier-alert agent** — top item 3; merged 2026-09-23 · #545.
- [ ] 3 · **Briefings by period** — top item 7; built 2026-09-23 (ROADMAP §3.27), unmerged.
- [x] 4 · **Learn when numbers settle** — top item 2; merged 2026-09-23 · #545.
- [ ] 5 · **Tell people when an answer goes stale** — top item 8; built 2026-09-23 (ROADMAP §3.28), unmerged.
- [x] 6 · **Alerts that prove they work** — top item 6; merged 2026-09-23 · #545.
- [x] 7 · **Fact-check a document** — top item 5; merged 2026-09-23 · #545.
- [ ] 8 · **Reviews of what was missed** — when someone finds a big move nothing flagged, the platform works out why (no alert? window too short? triage held it?) and proposes the fix.
- [ ] 9 · **An attention budget per person** — a weekly cap on interruptions, with alerts, briefings and inbox items competing for the slots on expected value.
- [ ] 10 · **A data shopping list** — show which usual industry questions the connected data cannot answer, and what to connect to answer them.
- [ ] 11 · **Numbers that link back to their source** — every figure in a PDF or slide carries a short link to the page showing how it was produced.
- [ ] 12 · **Guess before you look** — people guess a key number before it is revealed, so the platform learns where the organisation's picture of itself is most wrong.
- [ ] 13 · **Judge a recommendation against its trend** — compare the result with what the metric's own history predicted, not just before versus after; CB-2 now records the numbers this needs.
- [ ] 14 · **A UI that does not look AI-generated** — raise the faint text tokens, drop the sparkles and violet "AI" styling, stop one-off inline styles, cut the 35 tabs, and write house-style rules plus checks that catch it; the dark-theme contrast lift is the first slice and is on an unmerged branch (below).

---

## Unmerged branches (2026-09-23)

- [ ] `claude/dark-theme-lift` — the dark-theme contrast lift the user approved live, PLUS the law-8 amendment (no receipts on Slack messages), the quoted-rows guard fix (a product name "6B" read as billions) and the killed-run drain fix; not pushed; identical uncommitted copies sit in the main checkout.
- [ ] `claude/delivery-log-truth` — a disabled trigger now logs `skipped` instead of `failed`; not pushed.
- [x] `claude/remove-vercel-config` — `vercel.json`, `.vercel/` and the Vercel-only entrypoint removed; its commit rode into `claude/pending-top-nine` and merged 2026-09-23 · #545 (`vercel.json` and `api/index.py` are gone on main). The local branch is redundant.
- [ ] `claude/retire-vercel-platform-tick` — merged as #543; the local branch is redundant and can be deleted. *Measured 2026-09-23: the branch is also still on origin, and its tree matches the #543 squash exactly, so nothing is lost by deleting it; `git push origin --delete` from a cloud session is refused (403, the push credential is scoped to one branch) — delete it from a local checkout or the GitHub branches page.*

---

## Roadmap lines that read as pending but are not (to correct in ROADMAP.md)

- [ ] §3.9 MI-2a "the 336 failed deliveries are a live defect" — they were 332 skipped sends from disabled automations and 4 test sends; the logging fix is on `claude/delivery-log-truth`.
- [ ] §5 "remaining code: the langfuse.trace.input gate" — already built at `aughor/telemetry.py:812`.
- [ ] §3.15 ON-2 "theLook's `revenue`, marked verified, is `SUM(num_of_item)`" — the approved definition is `SUM(sale_price)` v1.
- [ ] §5 ledger "Slack reinstall with `files:write`" — the permission was granted at install; nothing to reinstall.
- [ ] §3.15's inline "open" questions on the Fabric export and the LuxExperience generator — both decided 2026-09-21 (§6 items 16 and 18c).
- [ ] §5 "a package's questions are not covered" — #539 merged them.
- [ ] §3.22 does not mark CP-1 and CP-2 as built (#542).
- [ ] §3.5's "VA-10 is therefore not one band" and §5's "cross-user Know waits on VA-10" — sign-in shipped 2026-09-06; only the live IdP receipt is open.
