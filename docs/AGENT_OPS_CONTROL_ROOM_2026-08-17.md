# Agent Ops — from a status page to a control room (2026-08-17)

**What this is:** the design for transforming the sidebar's **Agent Ops** surface (nav id
`agentic-ops`, formerly labelled "Agents") and its five layers — Overview · Agents ·
Attention · Activity · Run graphs — into something a person can read in one glance and act
from in one click. Modelled on the *grammar* of OpenRouter's Activity tab (user directive
2026-08-14: "similar way of representing our Agent Activities", explicitly not a copy), checked
against thirteen current agent/workflow observability products, and grounded in what this
repo's stores can actually serve today. Companion mockup: `AGENT_OPS_CONTROL_ROOM_mockup.html`
(published as an artifact the same day).

**Rename done:** sidebar item, command palette entry and workspace aria-label now read
**Agent Ops** (`web/app/page.tsx:498`, `components/CommandPalette.tsx:201`,
`components/AgenticOpsWorkspace.tsx:95`). Route ids and deep-links are unchanged.

---

## 0 · The thesis — a control room answers three questions in order, and every number is a door

**What's wrong? → What's running? → What did it cost?** In that order, above the fold, from
stores that exist — and every figure on the page opens the filtered list it was computed from.
Today the surface answers the third question first, the first not at all, and no number opens
anything.

Three facts, all measured on 2026-08-17 (read-only, `data/system.db`), decide the design:

1. **The loudest thing on the page is not an agent.** The "Unassigned kinds" row is the
   automation engine's tick — one job per minute, 0.02 s each, `total_tokens: 0` — folded into
   a charter row because no charter claims the `automation` job kind
   (`aughor/routers/control_room.py:189-198`). It is **1,291 of the 1,316 jobs in the last 24 h
   (98%)**. Runs/min reads **1.10 with it and 0.10 without it**; the pulse sparkline and the
   fleet table's largest row are its heartbeat. Real agent work in the same 24 h: profile 19,
   investigation 3, exploration 3.
2. **Per-agent activity cannot be drawn today.** `session_events.agent_id` is populated on
   **0 of 7,365 rows** (it was 10 of 5,683 on 08-14). Not a bug: `agent_id` means "which
   *custom agent* asked", is set only when a custom agent is activated on `/ask`, and charter
   (platform) work runs with it NULL by construction (`obs/session_log.py:237` →
   `telemetry.trace_identity:291`). So the "Top Agents" panel — the centrepiece of the
   OpenRouter grammar — has no data behind it, and every custom-agent row reads "0 model
   calls". Per-*model* activity is rich (3,393 `llm_call`s over ~12 models).
3. **The page fails its own readability bar.** Labels sit at `--t3` (**4.23:1** on `--bg-0`,
   below AA's 4.5) and captions at `--t4` (**2.76:1**, below AA-large); the violet used for
   agent ids as text is 2.63:1. Nothing is wrong with the tokens — the ramps' `4/5` steps and
   `--t1/--t2` clear AA easily — the panels simply reach for the faint ones for content.

Two smaller facts that shape the plan: there are **no charts on this surface** (one 40-line
SVG `Sparkline`, a CSS-width waterfall, pill strips) while ECharts and a theme-aware builder
library (`components/charts/echarts/`, exhibited in `/chart-lab`) sit installed and unused;
and there is **no shared time axis anywhere in the stack** — every fold is row-windowed
(`scan=5000`), and the Overview already shows two time bases in one table (a client-side
1-minute × 1 h pulse beside server-side 1-hour × 24 h sparks).

`web/components/ActivityUsagePanel.tsx` — untracked, imported by nothing, its wiring lost in
the N8-3 reset — is a sketch of the Activity/Usage panel this plan calls for. Its
`/obs/model-usage` and `/obs/prompt-weight` halves work; its `roles`/`window`/`fallback` half
expects a Migration 10 that does not exist. Fold it in; do not rebuild it.

---

## 1 · What "Unassigned kinds" is (question 2, answered)

A synthetic fleet row. `charter_for_kind()` returns the `_UNKNOWN` charter (`id="worker"`) for
any job kind no charter claims, and the fleet endpoint emits **one** row for all of them so
their runs and spend cannot vanish (`control_room.py:189-198`). Its role string lists the kinds:
today `automation` (the every-minute engine tick), potentially `eval_experiment` and any new
kind. It is a *runner*, not an agent, and it should never again share a table — let alone a
runs/min figure — with agents. **Design consequence:** a separate **Background runners** lane
(Automations · Evals), excluded from the agent totals by default, with a visible toggle to
include them.

Also worth knowing from the roster (`aughor/kernel/agents.py:67-129`): **Responder** (`insight`)
owns zero job kinds, so its row is 0/0/0 forever until quick answers are metered as jobs — the
table should say so rather than show three zeros.

---

## 2 · The grammar we are adopting (from the reference and the field)

From OpenRouter (copy the grammar, not the pixels): one big number per tile with a sparkline
and an explicit "— No prior data" state; **one shared time axis** so spikes line up by eye;
stacked bars where colour is the join key to a ranked list; ranked lists with `Explore ›`;
dark, low-chrome, the data is the only bright thing.

From the field (research 2026-08-17; URLs in the research note): the four that change this
surface most —

- **Attention first, throughput last** (Airflow home, Headlamp's warnings-first tail, the
  agent "mission control" playbook): approvals and stalls at the top, KPI tiles second.
- **Every bin is a query** (LangSmith, Braintrust): click a bar → the list filtered to that
  time-bin *and* that series. Anthropic's console: click a bar → finer granularity.
- **One global range + filter bar that reshapes every panel and lives in the URL** (Braintrust,
  Grafana drilldown, Vercel's team→project scope with identical layout).
- **Drawer, not modal, for row detail; arrow keys move the selection** — the table stays as
  context. Temporal's run timeline (event groups → one bar, retry badges) for "one run
  reconstructed"; Airflow's grid of state cells for "the last N runs of every agent".

Anti-patterns we will not import: self-reported status as truth; machine chatter as the
primary feed; stacked series for comparing magnitudes (stack only when the total is the
point); colour as the *only* join key; silently divergent per-widget time ranges; a single
"No data" for empty / null / error.

---

## 3 · Information architecture — five layers, kept, each with one job

Keep the five ids (deep-links, keep-alive and cross-layer focus already work —
`AgenticOpsWorkspace.tsx:71-88`); change what each *is* — and take the layer **labels** from
`docs/GLOSSARY.md`, which already prescribes *Overview · Roster · Attention · Activity ·
Runs*. With the workspace now called **Agent Ops**, the inner layer stops being "Agents"
(a workspace called Agent Ops with a tab called Agents was the collision) and "Run graphs"
becomes "Runs". *Vocabulary:* the glossary retires "persona" for **custom agent**, and
"Control Room" / "Fleet" as *names* — this document uses "control room" only as a
description of what the Overview should feel like, never as a label.

| layer | today | becomes | one job |
|---|---|---|---|
| Overview | KPI strip + one table + jobs list | **the control room** | what's wrong · what's running · what it cost — one screen |
| Agents → **Roster** | roster + config forms | **agent pages** | one agent, fully: health, runs timeline, model mix, budget, config |
| Attention | 4 counts + card list | **the inbox** | act on what needs a human; every card has an age and one action |
| Activity | raw event tail + traces | **Usage · Stream · Traces** | spend and volume by model/role/call-site; then the tail; then one run |
| Run graphs → **Runs** | wall of "did not fire" ticks | **runs, collapsed by default** | one row per automation with its ticks folded; deep-run phases as today |

A shared **time range** (1 h · 24 h · 7 d · 30 d · custom, brushable) lives in
`Workspace.headerControls` (`Workspace.tsx:26,72`, the slot built for it) and is written to
the URL. It governs every panel on every layer. A **density** toggle (Calm / NOC) already
exists and stays.

### 3.1 · Overview — the control room, top to bottom

1. **Status rail** — one pill per agent (charters, then custom agents): name, state dot
   (running / idle / paused / failing), live count. Click → scroll-and-highlight its row.
   The rail *is* the answer to "what's running".
2. **Needs you** — the Attention inbox's top three, inline: source chip, title, a live
   waiting timer, the one action (Accept / Reject / Open & resume). "N more →" opens the layer.
   Empty state stays honest ("Nothing needs a human · all three sources empty").
3. **KPI row** — `StatTile` (`components/brief/StatTile.tsx`, the canonical spec, unused
   here today), five tiles over the shared window: **Runs** (agents only; "+1,291 background"
   as the caption) · **Failures** (with orphaned restarts split out, as now) · **p50 / p95
   duration** (p50 is computed and never rendered — `control_room.py:130`) · **Tokens** (with
   the metered/unmetered coverage the endpoint already returns) · **Cost** (see §4.4; ships
   with its `unpriced` caveat or not at all). Each tile: value → delta vs the prior window →
   sparkline → coverage caption. Click → a right-hand **drawer**: definition, denominator,
   coverage, and "Open the list →" (jobs filtered to exactly this number).
4. **Activity chart** — stacked bars over the shared axis, one series per agent, colours from
   `--chart-1..6`; legend chips toggle series and are the join key to the table swatches;
   hover = per-series values; **drag = brush**, which sets the range and re-filters the table.
   Background runners are a hatched grey series, off by default (toggle in the chart header).
5. **Fleet table** — two lanes. *Agents*: charters and custom agents in the **same columns**
   (today custom-agent rows are half dashes because their store has no runs — §4.1 fixes the
   store, not the table): swatch · name + role · status chip · 24 h sparkline (threshold-coloured) ·
   runs · failures (+orphaned) · tokens (+unmetered) · p95 · last run · `Explore ›`. Row click
   → expand inline: last-20-runs state cells (Airflow grid), model mix bar, budget bar, "Open
   agent →". *Background runners*: Automations (ticks folded: "1,291 ticks · 0 fired · next
   due 00:00"), Evals — muted, one row each, never summed into the agents' totals.
6. **Jobs** — as today, but filtered by the shared range and any active brush.

Rules of the page: values `--t1`, labels `--t2`, captions `--t3` at ≥ 12 px only, `--t4`
never for text; semantic colour is `grn4 / amb4 / red4` (the text-grade steps — `red3` and
`vio3` do not clear AA), and it means state, never decoration; the accent `--blue3` means
*interactive or selected*, nothing else.

### 3.2 · Roster — one agent, fully

Roster rail as today (`AgenticAgentsPanel.tsx:88-116`), detail becomes a page: header (name,
role, lane, status, budget bar), the same five KPI tiles scoped to this agent, a **runs
timeline** (one bar per run coloured by state, retry badge, click → trace), a **model mix**
bar, then Governance and Configure as they are. Charter and custom agent get the **same layout**;
what differs is the source line under the tiles ("from job metering" / "from the session
log") — the honest `spend_source` split the endpoint already carries.

### 3.3 · Attention — the inbox

Cards grouped by source with the age visible as a live timer, oldest first (already sorted
server-side by `waiting_ms`); the action inline; keyboard: arrows move, Enter acts. Add the
two leading indicators the research names and the stores can serve: **oldest waiting job**
and **attempts on the worst job** (`jobs.attempt`).

### 3.4 · Activity — Usage · Stream · Traces

- **Usage** is the OpenRouter page: tiles Requests · Tokens · Cost · Fallback rate · Calls
  without usage (coverage as a first-class number); **Usage by model** stacked over the shared
  axis; **Top models** and **Top call-sites** ranked lists with `Explore ›` → the Stream
  filtered to that model/caller. This is where `ActivityUsagePanel.tsx` lands, its broken half
  repaired by §4.1.
- **Stream** keeps the SSE tail (`ActivityStreamPanel.tsx`) but **groups by trace** — one row
  per trace, expand to events — with the kind histogram chips it already builds from data,
  plus model / caller / agent filters, warnings-first as a preset, and a pause.
- **Traces** is `TraceExplorerPanel` with a Temporal-style timeline (event groups → bars,
  retry badges) instead of a single proportional strip.

### 3.5 · Runs

Automation ticks fold into one row per automation, expandable; fired runs get the full row
with conditions → effects verbatim as now. Deep-run phase view unchanged.

---

## 4 · The data plane — what must exist before the page can be honest

Every wave in this repo's history that built a surface before its store existed shipped a
panel that rendered empty (Top Agents would, today). So the backend wave is **first**.

### 4.1 · Attribution — Migration 10 (`aughor/kernel/ledger.py`, currently stops at 8)

Add to `session_events`: `job_id`, `charter_id` (from a job contextvar set in
`kernel/jobs.py` at run start and read in `trace_identity()` beside `agent_id`), and lift
`role` and `fallback` out of `payload` into columns (the untracked
`tests/unit/test_session_event_attribution.py` already specifies these two). Add an index on
`at`. This is what joins **charter identity to model spend** — impossible today because
charter work never sets `agent_id` and `jobs` has no model dimension.

### 4.2 · Time — one axis for everything

`from` / `to` / `bucket=hour|day` on `/control-room/fleet`, `/obs/model-usage`,
`/obs/prompt-weight`, `/activity`; one new `/obs/timeseries?group=charter|model|kind|role`
returning `[{bucket_start, series…}]`. Retire the client-side minute pulse in favour of the
same buckets.

### 4.3 · Drill — every number is a door

`/activity` gains `model`, `provider`, `caller`, `charter`, `job_id` filters (`model` and
`provider` are already indexed columns). `/jobs` already filters by state and kind. **Ratchet
from day one:** a test that, for every tile the fleet endpoint returns, the filtered list it
links to has the same count — the CR4 shape (`needs-human.count == Σ sources`).

### 4.4 · Cost — from the provider's own price list, never hardcoded

`PRICES` has one row (`openrouter`, `:free`, $0). The model picker already fetches
OpenRouter's `/models`, which carries per-token pricing; cache it into `PRICES` at config time
(the *no hardcoded model ids* directive extends naturally to *no hardcoded prices*). Anything
unpriced keeps counting into `unpriced_calls` and the tile says "of which N unpriced". RBAC:
`/control-room/*` is at the open floor and `/usage` is `admin.manage_billing` — a decision is
needed (§7) before dollars appear on Overview.

### 4.5 · Background runners

Give the automation engine's tick its own job kind or a `charter_id="automations"` so it
stops folding into "Unassigned kinds"; the fleet endpoint returns it in a `runners` list, not
in `rows`. Same for `eval_experiment`.

---

## 5 · Waves

| wave | scope | ~effort | proof |
|---|---|---|---|
| **W0 data plane** | §4.1–4.5 | 2 d | `agent_id`/`charter_id` populated on ≥ 95% of new `llm_call`s; `/obs/timeseries` serves charter × hour; count-parity ratchet green |
| **W1 Overview** | §3.1: shared range in `headerControls`, status rail, needs-you strip, `StatTile` row with drawer, ECharts stacked activity with legend + brush, two-lane table with row expand, jobs by range | 2½ d | at 1280 × 720 the fold answers all three questions; runs/min shows agents only; zero dead numbers |
| **W2 Activity** | §3.4: Usage (fold `ActivityUsagePanel`), Stream grouped by trace with model/caller filters, Traces timeline | 2 d | Top models / call-sites drill to the filtered stream; fallback rate renders from a column |
| **W3 Roster · Attention · Runs** | §3.2, 3.3, 3.5 | 2 d | custom-agent and charter pages render the same layout; ticks folded |
| **W4 readability sweep** | tokens: `t1/t2/t3≥12px`, semantic `*4` steps, `Sparkline` hexes → tokens (it hardcodes `#818cf8/#34d399/#f87171` and does not flip in light mode), className-driven type so `lint:tokens` actually sees this surface; light theme pass | 1 d | every text token on the surface ≥ 4.5:1 in both themes; a surface-scoped lint rule pins it |

Total ≈ 9½ days. W0 first; W1 and W2 can overlap once §4.2 lands.

---

## 6 · What "better" means — three numbers, one qualitative

- **Dead numbers → 0.** Every figure on Overview opens a list whose count equals it (the
  ratchet). Baseline: 0 of ~40 figures are clickable.
- **Contrast.** Share of text nodes on the surface at ≥ 4.5:1 → 100% (baseline: labels 4.23,
  captions 2.76).
- **Signal share.** Runs/min and the pulse count agents only; the automation tick is visible
  as one folded row. Baseline: 98% of the "activity" is the tick.
- **The glance test.** A reader names, without clicking, what needs them, which agent is
  failing, and roughly what today cost — at 1280 × 720, without scrolling.

---

## 7 · Decisions — LOCKED 2026-08-17 (user chose the recommendation on all four)

1. **The automation tick lives in a muted *Background runners* lane on Overview** — spend
   nobody can see is the reason the row exists; it is never summed into the agents' totals.
2. **Dollars appear on Overview**, from provider-fed prices at the open RBAC floor, always with
   the unpriced share stated. `/usage` keeps its billing RBAC for the full ledger.
3. **Attention is both an inline strip on Overview and its own layer.**
4. **The five layers stay**, under one shared range; entity tabs are not pursued.

Sequencing stands: W0 first.
