# Dashboards — standing questions, and the rename from cockpit (study, 2026-10-23)

PENDING item 54. The user, 2026-10-23:

> *"explore 'Data Canvas as a Cockpit component' feature.. where users can add constant questions as a part of the
> cockpits (lets rename cockpits entirely as Dashboards - externally and internally), which would show analysis as
> part of the dashboard - e.g. Week over week changes in sales.. questions which users like answered not just via
> number or graphs but also summary and why behind it - something that Data Canvas already delivers."*

Measured first, from the source and the live install (three read-only surveys and the theLook instance). The mockup
is `design-mockups/dashboard-questions.html`. Nothing is built.

## 1. What exists

**A Data Canvas answer** is one `investigations` row (data/history.db, `aughor/db/history.py:166-186`), keyed by an
8-hex id, with its canvas, connection and a `report_json` (`aughor/agent/state.py:430-489`): a headline, an
executive summary, labelled `figures`, the why (`phases` — the decomposition and cross-sections — plus
`attribution_waterfall` and `causal_checks`), `gaps` (what it could not see), recommendations, a confidence, the
`spec` it measured (metric, table, date column, window length) and `period_as_measured`. Every finding inside keeps
its SQL, rows and chart. An `envelope` with provenance and receipts rides on top (`answer/envelope.py:94-111`).

- **It costs a full agent run to produce.** One intake call, a tool loop of up to 10 steps (24 on the capable tier),
  two calls per phase tool, one narrator call: about **8–20 model calls**. theLook's daily question took
  **6 min 11 s** this morning (run `1008d310`, 09:00:59–09:07:10 UTC).
- **It cannot be re-run as it stands.** Its SQL is frozen to literal dates spread across several findings; the only
  window it keeps is a label and `spec.window_days`. Asking again means a fresh agent run. The cheap no-model paths
  that exist all start from SQL, not from an answer: the chat re-check (chat rows only, and it skips SQL that reads
  the clock), a card's run cut to a range, `measure_spec`, the Briefing's re-ask.

**A cockpit card** (`aughor/dashboard/models.py:52-70`, table `dashboard_cards`) is SQL: a `kpi`, `chart`, `watch` or
`note`, made from a metric, a trusted query or a finding. On open every card re-runs its SQL (`POST /cards/{id}/run`)
— **no model is ever called to fill a cockpit**, by law (`aughor/routers/cockpit.py:4-7`). No card kind holds a
question, a summary or a why. The card's `refresh.cadence` field is read by nothing.

- The Data Canvas already has **"Pin to dashboard"** (`ChatMessage.tsx:1001-1066`): it pins the turn's SQL and
  headline as a card, scope = the connection. The summary, the why and the answer's id are dropped.

**The nearest thing to a standing question already runs on theLook.** The automation *"The Look - Daily Briefing"*
asks the agent a revenue question every day at 09:00 UTC through an `investigate` step
(`automations/engine.py:1428`). Code writes the period into the question (`automations/temporal.complete_period`,
`scheduled_grounding`): *"Observe 2026-10-15, the most recent complete day given this automation's observation lag
of 8 days … The previous run reported: …"*. It has answered 17 times since 3 October. Its answers are not tied to a
canvas, a cockpit or an inquiry.

**The Inquiry** (`aughor/record/inquiry.py`; GLOSSARY: *"the durable object a deep analysis runs inside"*) already
holds a question, who opened it, its runs with their typed verdicts, what it established and could not settle, a
date it wakes, and `run_cost_estimate` — the median tokens and minutes of this install's own runs, a dollar floor
from priced runs, and the charter's ceiling. Today a waking inquiry only wakes: *"nothing here spends a model"*.

## 2. The design proposed: a Question piece

A dashboard gets one new piece, **Question**. It holds a question and a rhythm; each answer is a Data Canvas answer.

- **It is an Inquiry with a rhythm, not a new store.** The piece holds the inquiry's id. Each answer is a run of that
  inquiry (`attach_run_result`), so the history, the verdicts and the cost estimate are the inquiry's.
- **It is answered on its rhythm, never on open.** Daily, Weekly or Monthly — each the last *complete* period against
  the one before, the period written into the question by code exactly as the automation does today
  (`complete_period` + `scheduled_grounding`, which also hands over the previous answer for consistency). Or *Only
  when I ask*. Opening the dashboard shows the latest kept answer, dated; the cockpit law (no model on open) stands.
- **It shows what the Data Canvas shows**, in this order: the headline · the figures · the summary · *Why* (the
  drivers from the decomposition) · *What it couldn't see* (gaps) · its confidence · *answered Thu 23 Oct for Wed
  15 Oct* · earlier answers · Open in Data Canvas · Ask again now.
- **Its cost is said before it is kept and beside every answer**: a run is about 6 minutes and 8–20 model calls; a
  daily question is about 30 runs a month, a weekly one about 4. The figure comes from `run_cost_estimate`, never a
  guess; an unpriced model is said as unpriced.
- **Two doors.** From a Data Canvas answer: *Keep on a dashboard* (choose the dashboard and the rhythm) — the
  existing "Pin to dashboard" keeps pinning SQL; this one keeps the question. Inside a dashboard: *+ Question*.
- **The laws it keeps.** A person adds the piece; a model never does. The answer is the agent's, shown with its
  receipts as the Data Canvas shows it — never as a measured card figure. A run that ends without an answer says its
  verdict (`no_data`, `out_of_budget` …) in the piece; the previous answer stays, marked as the previous one.
- **Not proposed now.** A cheap re-answer (re-running a stored decomposition's SQL for the new period with no model)
  — possible later from `spec` + `scoped_statement`, but every answer's why would then be last period's prose over
  this period's numbers. Not until it can be done honestly.

## 3. The rename, measured

"cockpit" appears **6,268 times in 284 files**: web 3,814 (2,286 outside tests), aughor 1,028, tests 680, docs 327,
ROADMAP 206, PENDING 174. Reader copy is about 564 lines; 21 API routes (`/cockpits…`); 9 flags; 144 web
identifiers; 54 files under `web/components/cockpit/`, 33 under `web/lib/cockpit/`, 22 under `aughor/cockpit/`.

Three things the rename has to get past:

1. **"Dashboard" is already taken internally.** `aughor/dashboard/` is the CARD store (`dashboard_cards`,
   `AUGHOR_DASHBOARD_DB`, the `/cards` routes, `DashboardCard` in `web/lib/api.ts`), and the ontology uses
   `source_kind: "dashboard"` for an outside BI asset. Moving `aughor/cockpit` onto `aughor/dashboard` collides.
2. **The glossary forbids the word today.** `docs/GLOSSARY.md:90` — Cockpit, *Don't use: "dashboard, board (in
   anything a reader sees)"*; `:141` App likewise. The rename reverses that entry; the glossary is the authority and
   changes first.
3. **Stored names.** Persisted, and read back by name: the Ledger artifact kind `cockpit` and natural keys
   `cockpit:person:{conn}:{owner}:{id}` (+ the legacy `cockpit:{canvas}`); the spec root `"cockpit"` / element
   `Cockpit`; proposal kinds `cockpit_draft` / `cockpit_publish` and their inbox rows; audit and approval action
   names `cockpit.draft` / `cockpit.publish`; the `cockpit-images` file volume; the user pref section id `cockpit`;
   browser keys `aughor:cockpit:*`; deep links `?tab=cockpit` / `?layer=cockpit`; metering sites `cockpit.draft` /
   `cockpit.edit`; flag override rows.

**The plan proposed — staged, each stage green on its own:**

- **R1 · What people see.** GLOSSARY first (Dashboard becomes the reader word; *cockpit* moves to the retired column),
  then every label, empty state, tooltip, toast, Settings flag label, chat redirect and model prompt. Deep links
  accept `?layer=dashboards` and keep reading the old ones. *Pin to dashboard* and *Pinned to the dashboard* already
  say it; they stay.
- **R2 · Free the name.** The card store moves to `aughor/cards/` (it is the card store); its table, env var and
  routes stay as they are — frozen names.
- **R3 · The code.** `aughor/cockpit/` → `aughor/dashboards/`, the router, `web/components|lib/cockpit/` →
  `dashboards/`, identifiers, `data-testid`s, tests, the validator bundle and its CI drift check, the SQL-door and
  icon registries. Routes become `/dashboards…` with `/cockpits…` kept answering. The nine flags move through
  `RENAMED` / `RETIRED_ENV` (`aughor/kernel/flags.py:256-313`), so every operator `.env`, override row and the
  restart script keep working.
- **R4 · Lock it.** "cockpit" joins the vocabulary ratchet as a retired term, its baseline the frozen stored names
  above (exempt with a reason each).
- **Stored names stay frozen and are read both ways** — as the Phase 8 rename did (persisted keys kept). Audit and
  approval history is never rewritten.

**Order:** the rename first, then the Question piece — built after, it is born with the new names instead of being
renamed with everything else.

## 4. Decisions for the user

1. How far the rename goes now — all four stages (recommended), or what people see first and the code later.
2. Stored names — kept frozen and read both ways (recommended), or migrated (the Ledger, inbox rows and browser keys;
   audit history cannot be).
3. The Question piece's rhythms and default — Daily / Weekly / Monthly / Only when I ask, defaulting to Weekly
   (recommended), each answer a full agent run with its cost said.
4. The mockup — approved as drawn, or what to change.
