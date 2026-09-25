# The UI/UX study — every surface, measured, and one layout grammar to hold them

*Measured 2026-09-25 against the web app on `main` at `39e8cfb4` (#548), served from the user's dev server on
port 3000 over the live API. Every surface was driven in the built-in browser at 1440×900 and 1024×768, read as
text and as a DOM probe (font sizes, target sizes, horizontal overflow, header crowding, computed token
contrast in both themes); every surface was also captured headlessly on a fresh browser profile at both widths.
No model call was made, nothing was written to any store, and the browser's theme and viewport were restored.
The review lenses are the house's: `web/aughor-v2/INSTRUMENT.md`, the better-ui family (ui, layout, typography,
accessibility) and emil-design-eng, in better-ui's report format. Findings are grouped by the principle they
violate; severity is `HIGH` (blocks content or an action at a supported width, or a systemic failure), `MEDIUM`
(a visible inconsistency that harms hierarchy, reading order or adaptability) or `LOW` (isolated polish).*

*What this is not: a restyle. Instrument's tokens, type scale, primitives and its "one plane, hairlines,
colour is a data type" thesis stand. Every layout call the user has already made stands too — the verdict-first
Briefing, no numbered gutters, 28px rail rows with a collapsible rail, the press scale on the Primary only. Where
this study disagrees with a standing sentence in Instrument it says so, once, in §4.5.*

---

## 0 · The reading

**The product's visual layer is disciplined; its structural layer is not.** Instrument gave every screen the same
ink, type and primitives, and it shows: nothing here looks cheap. What no screen shares is a *layout*: there is
no page template, so each of the forty-odd surfaces decides for itself where its title, its context, its
switcher, its filters and its primary action go, and the answer is usually "all of them in the 44-pixel header".
At 1440 that reads as crowded; at 1024 it breaks — controls clip off the right edge with no cue, and on Agent Ops
two controls draw over each other. Underneath that, the shell has no notion of *context not yet known*: when the
workspace or the connection has not resolved, screens paint their empty state, or nothing at all, and one of them
tells the reader to "pick one above" beside a picker that is not on the screen. And the number — the thing the
product is a claim about — still reaches the reader unformatted on the surfaces that matter most: the Briefing's
"numbers that moved" tiles and the object page.

Three things therefore, in order: **a context state so nothing paints before it knows what it is showing; one page
grammar with a header that carries a title and a primary action and nothing else; and one formatter and one
name-resolver on every door.** Everything else in this study is either a consequence of those three or polish.

**Overall verdict, in better-ui's terms: `Block`** — nine `HIGH` findings stand (§2.1, §2.3, §2.6), each with its
location. The screens that already show judgement — the Briefing's verdict-first page, the SQL workbench, the
Agent Ops overview's tiles-with-provenance, Integrations' copy, the object page's structure, the Brain map — are
named as such below, because a study that only lists faults teaches the next builder nothing about the bar.

### The ten that matter most

| # | Finding | Severity | Where it shows |
|---|---|---|---|
| 1 | Screens render their **empty state before the workspace and connection have resolved**; Spend and Security & Audit render a **blank pane**; Intelligence and the Brain map say "pick one above" with no picker rendered; the Roster says "no custom agents yet" while two exist | HIGH | cold load of `?tab=intelligence`, `brain`, `spend`, `security`, `agentic-ops&layer=agents` — figs. 2, 6, 7, 8 |
| 2 | The **44px header carries title + context + layer switcher + range + primary**; at 1024 the Intelligence header clips three layers with no overflow cue, and Agent Ops draws its range control under its layer tabs | HIGH | figs. 3, 4; probe: 10 controls in 776px, rightmost at 1201px |
| 3 | The Agent Ops overview's body is **wider than its pane at 1440** (1564px in 1192px) and at 1024 | HIGH | probe on `?tab=agentic-ops` |
| 4 | **Figures reach the reader unformatted**: `180925`, `1820497.55`, `3561748.63`, `7.49e+06` on the Briefing's tiles and findings; `114.98999977111816 USD` on the object page, beside `114.99 EUR` and `114.99 $` for the same value | HIGH | Briefing on theLook; `/objects/order/1` |
| 5 | **Machine identifiers reach the reader as names**: `Agentic · 8233e4fd` on every run card, `__brief_metric_move__` · `card:2878362c` · `cb2_review` · `YouQuery Builder` as agents in the audit, `8233e4fd` in the Memory table, `GET /exploration/{conn}/domains` on the Brain map, `0m · 0r · 0e` on packs | HIGH | Agent runs, Security & Audit, Memory, Brain map, Settings › System |
| 6 | **Three navigation grammars applied inconsistently**: the rail exposes 1 of Intelligence's 9 layers, all 5 of Operations' (and the workspace repeats them), 1 of Evals' 3; Agent Ops has rail → 7 layers → 4 sub-tabs → a range; Settings uses a fourth idiom; names drift (Agent runs / Recents / Agent history) | MEDIUM | every workspace |
| 7 | **11px is the reading size.** On the Briefing 284 of 387 text nodes are 11px; Agent Ops has 11 nodes *under* 11px; 31 and 41 controls per screen are under the 24px target minimum (the segmented item is 23px, links 17px) | MEDIUM | probe, every screen |
| 8 | **The light theme fails its own thesis**: captions at 3.22:1 (AA needs 4.5), the row rule at 1.01:1 — invisible; the dark theme's caption now passes at 4.83:1 after the 09-22 lift | MEDIUM | tokens, both themes |
| 9 | **Loading is said four ways**: skeletons on some screens, "Loading…", "Loading the catalog…", "Loading overview…", "Reading this connection's schemas…" on others; the first-run Home stacks five blocks that each say "nothing yet" | MEDIUM | Data Canvas, Catalog, Agent Ops, Briefing, Home |
| 10 | **The command palette's result rows have no accessible names** (13 unnamed buttons in the tree); the Catalog's 13 favourite toggles are all named "Favorite" | MEDIUM | ⌘K, Catalog |

---

## 1 · Coverage

Forty-three surfaces were reached. "Text" means the surface was read through the accessibility tree and its
visible text; "probe" means the DOM measurement ran; "capture" means a headless screenshot exists in
`docs/assets/ui-study-2026-09-25/` (dark theme; light was measured through computed tokens only).

| Surface | Reached as | Text | Probe 1440 | Probe 1024 | Capture |
|---|---|---|---|---|---|
| Shell: topbar, rail, collapsed rail, ⌘K | live | ✓ | ✓ | ✓ | ✓ (rail in every capture; ⌘K by tree only) |
| Home (first run and returning) | `?tab=home` | ✓ | ✓ | — | ✓ + 1024 |
| Inbox | `?tab=inbox` | ✓ | — | — | ✓ |
| Data Canvas (list) | `?tab=canvases` | ✓ | — | — | ✓ |
| Briefing · Profile · Ontology · Graph · Evidence · Memory · Actions · Org · Brain map (theLook, and Workspace/amazon for the Briefing) | layer tabs | ✓ ×9 | ✓ (Briefing) | ✓ (Briefing) | ✓ ×9 + 1024 |
| Agent runs | `?tab=recents` | ✓ | — | — | ✓ |
| Health | `?tab=health` | ✓ | — | — | ✓ |
| Documents | `?tab=documents` | ✓ | — | — | ✓ |
| Catalog (list; table detail not opened) | `?tab=catalog` | ✓ | ✓ | ✓ | ✓ + 1024 |
| SQL Editor (workbench, catalog rail, tabs) | `?tab=query` | tree | ✓ | ✓ | ✓ + 1024 |
| Semantic Layer (Metrics tab) | `?tab=semantic` | ✓ | ✓ | — | ✓ |
| Agent Ops: Overview · Roster · Attention · Activity (Usage) · Automations · Hub · Departures | layer URLs | ✓ ×7 | ✓ (Overview) | ✓ (Overview) | ✓ ×7 + 1024 |
| Monitors · Notifications · Integrations · Spend · Security & Audit | rail | ✓ ×5 | ✓ (Spend, Security) | ✓ (Spend) | ✓ ×5 + 1024 (Spend) |
| Evals: Suites · Runs · Experiments | layer URLs | ✓ ×3 | — | — | ✓ ×3 |
| Settings: Organization · Access · Appearance · Models · System | tab clicks | ✓ ×5 | ✓ (Organization) | — | ✓ (Organization) |
| Chat (`/chat`) | route | ✓ | — | — | ✓ |
| Object page (`/objects/order/1`, theLook) | route | ✓ | — | — | — |

Not reached: the Catalog's table detail tabs (Overview · Sample · Columns · ERD · Schema Shape · Volumes ·
Permissions · Schema docs), the Add-data panel, a Data Canvas opened, the automation Design canvas, the SQL
workbench's visual mode, the Trace explorer, the Ontology's Human edits / Proposals / Learned skills drawers,
every dialog and toast, hover and focus states, and motion at 10% speed. They are listed under **Not verified**
(§7), not approved.

---

## 2 · Cross-cutting findings, by principle

### 2.1 · Nothing paints before it knows what it is showing — `HIGH`

The repo's own invariant is *withheld is said, never implied: an empty result that means "you may not see this"
teaches the reader the data does not exist.* The shell breaks it at the root. There is no state for "the workspace
and connection are not resolved yet"; every screen has only `loaded` and `empty`, so a cold load — a fresh browser
profile, a deep link, a new machine — paints the empty state first. The pane, warm from earlier sessions, hides
this; the headless captures on a fresh profile show it, and it reproduces at 25 seconds and on a profile that had
already loaded Home (`scratchpad/verify/`).

| Severity | Location | Before | After | Why |
|---|---|---|---|---|
| HIGH | `web/app/page.tsx` (the shell's workspace and connection resolution) → `web/components/IntelligenceWorkspace.tsx` (empty state), `web/components/BrainMapPanel.tsx`, `web/components/OntologyPanel.tsx`, `web/components/AgenticAgentsPanel.tsx`, `web/components/QueryBuilder.tsx`, the Operations workspace behind `web/components/SpendPanel.tsx` and `web/components/SecurityAuditPanel.tsx` | Cold `?tab=intelligence&conn=8233e4fd`: "No connection selected — Briefings are per connection. Pick one above, or add a connection from the Catalog." with **no picker rendered** (fig. 2). Cold Brain map: "The brain map is per connection. Pick one above." — same (fig. 8). Cold Ontology on theLook: "No ontology data available." while the connection has 7 entities and 12 relationships (fig. 14). Cold Roster: "No custom agents yet…" while Anomaly Scout and The Look Analyst exist (fig. 7). Cold SQL editor with `?conn=8233e4fd`: "Select a connection…" and "No schema loaded." — the URL's connection ignored (fig. 15). Cold Spend and Security & Audit: a **blank content pane, no header** (fig. 6), at 10 s and 25 s | One context state — `unknown → resolving → resolved | none` — owned by the shell and read by every workspace. While `unknown`/`resolving`, a workspace renders its **skeleton** (the Briefing already has one); the empty state renders only on `none`; the picker renders in every state; a blank `<main>` is a bug the screenshot gate (§4.9) fails on | Layout · "hint at hidden content"; the repo's own invariant. A first-time reader concludes the product has no data and no agents |
| HIGH | the same empty states' copy | "Pick one above" | Copy never names a control that is not on the screen; when the picker is absent the sentence is the door itself: "Choose a connection →" | Writing · a false instruction is worse than none |
| MEDIUM | `?conn=` handling on cold load | the URL's connection is ignored until the workspace list arrives, then the last-used connection wins | the URL is the authority on load; the stored connection is the fallback | Layout · a deep link that lands somewhere else is not a link |

`Block` until the first two rows land; they are a day's work and unblock every other empty state.

### 2.2 · One navigation grammar — `MEDIUM`

The app has one rail, four kinds of second-level navigation, and no rule for which a screen gets.

| Where | Rail shows | The workspace shows | Third level |
|---|---|---|---|
| Intelligence | 1 item ("Briefing") of 9 layers | a 9-segment switcher (`IntelligenceWorkspace.tsx:62-75`) plus CONNECTION and SCHEMA selects in the same 44px row | Profile has a domain rail; Ontology has Find duplicates · Human edits · Proposals · Learned skills |
| Data | 3 items (Catalog, SQL Editor, Semantic Layer) | Catalog: Suggested · Favorites · Recents + a detail with 8 tabs; Semantic: a SCOPE tree + Metrics · Annotations · Knowledge · Benchmarks · Import | — |
| Agent Ops | 1 item | RANGE (5) + 7 layers (`page.tsx:1334`) in one row | Activity: Usage · Stream · Traces · Phases; Automations: Automations · Runs · Inbox · Propose |
| Operations | **all 5 items** (Monitors, Notifications, Integrations, Spend, Security & Audit) | **the same 5 again** as a segmented row (`OperationsWorkspace.tsx:53-60`) | Security: Security · Activity · Approvals · Query Budget; Notifications: Triggers · Logs |
| Evals | 1 item | Suites · Runs · Experiments (`EvalsWorkspace.tsx:45-47`) | — |
| Settings | 1 item | 5 **underline** tabs (`page.tsx:878-882`) — a fourth idiom | Organization holds an APPEARANCE section while an Appearance tab exists (`page.tsx:871`) |

| Severity | Location | Before | After | Why |
|---|---|---|---|---|
| MEDIUM | `web/app/page.tsx:294-340` (nav), `Workspace.tsx:88` (switcher), the five workspaces | the table above | **One rule:** the rail lists *destinations* and never a layer; a destination with layers shows them in **one** place — a tab row under its header — and never also in the rail. Operations stops being both. Intelligence's nine layers become a tab row (with overflow, §2.3) or, better, split: Briefing · Profile · Evidence · Memory · Org · Brain map stay "Intelligence"; Ontology · Graph · Actions move to a "Model" destination beside Data, because they are authored, not read | Layout · "order by importance", "hint at hidden content"; today eight of the nine Intelligence layers are invisible from the rail while five Operations rows are listed twice |
| MEDIUM | the rail's second group | 18 items + Settings; at 768px tall the last two rows (Security & Audit, Evals) sit **under the pinned footer** (`.aug-nav-foot`, `globals.css:308`) with no scroll cue (fig. 3) | ≤ 12 items: Home · Needs you · Ask · Briefing · Runs · Data (Catalog, SQL, Semantic) · Model (Ontology, Graph, Actions) · Operate (Agents, Automations, Monitors, Departures) · Govern (Spend, Security, Evals) · Settings; the rail body scrolls with a fade over the footer | Layout · "content bleeds, controls float"; a hidden destination is not a destination |
| MEDIUM | naming | rail "Agent runs" · header "Recents" (fig. 9) · palette "Agent history"; rail "Notifications" for outbound *triggers* (`id: "actions"`); "Inbox" = recommendations only, while proposals awaiting approval live in Agent Ops › Attention — two inboxes | **Runs** everywhere; **Triggers** (under Automations); **Needs you** = one queue for proposals, held departures, approvals, broken automations, recommendations — and a topbar tray for it (§4.6) | Glossary · one word, one concept |
| MEDIUM | `?tab=health` | a rail item whose whole content on every connection is "No health metrics configured. Define metrics with targets…" | fold into the Briefing/Profile until a connection has a metric with a target; then it is a section, not a destination | Layout · "order by importance"; a destination that is one sentence teaches the rail is padding |
| LOW | Settings › Appearance | two radio options that duplicate the topbar toggle (`page.tsx:272`) | the toggle in the user menu; the tab goes; the Organization page's APPEARANCE section (chart palette) becomes "Charts" under System | one control per setting |

`Approve` with the work listed — nothing here blocks, and two rows are the user's call (§6).

### 2.3 · A header carries a title and a primary action — `HIGH` at 1024, `MEDIUM` at 1440

Instrument's shell says `header 44 · screen title · context meta · segmented layer switcher · primary action`.
That sentence is the defect: everything is in one row, and rows do not wrap.

Measured with the DOM probe (`.aug-content-header`, `globals.css:375`, height 44, gap 12, padding 0 16):

| Screen | Width | Controls in the header | Rightmost control ends at | Result |
|---|---|---|---|---|
| Intelligence (Briefing) | 1024 | 10 | **1201px** | 3 layers off-screen, header clipped, no cue (fig. 3) |
| Intelligence (Briefing) | 1440 | 10 | fits | 9 segments + 2 selects + title in 1192px; the Workspace connection adds a SCHEMA select |
| Agent Ops (Overview) | 1024 | 13 | 1008 | the RANGE segmented control is **drawn under** the layer tabs — "Ro7ster", "30Attention" (fig. 4) |
| Agent Ops (Overview) | 1440 | 13 | fits | body overflows horizontally: 1564px in a 1192px pane |
| Catalog | 1024 | — | — | the detail's Filter box clips at the right edge; the title appears three times (rail "Catalog", list label "CATALOG", a 22px `<h1>Catalog</h1>` at `CatalogScreen.tsx:1252`) (fig. 5) |
| Agent Ops (Activity) | 1440 | 13 + 4 | fits | three levels of navigation and a range control above the content (fig. 12) |

| Severity | Location | Before | After | Why |
|---|---|---|---|---|
| HIGH | `web/components/IntelligenceWorkspace.tsx` header, `web/components/Workspace.tsx:88` | 9 segments clip at 1024; nothing says more exist | a **tab row** under the header (36px): scrolls horizontally with an edge fade, and a trailing "More ▾" menu lists what is clipped; the active tab is always scrolled into view | Layout · "hint at hidden content"; a control the reader cannot reach is an action blocked at a supported width |
| HIGH | `web/components/AgenticOpsWorkspace.tsx` header | RANGE and the layer switcher share a row and overlap at 1024 | RANGE moves to the **context bar** (§4.3) beside the connection; the layers become the tab row; never two segmented controls in one row | Layout · overlap is content blocked |
| HIGH | Agent Ops overview body (`web/components/FleetOverviewPanel.tsx` + the runs chart) | a table or chart wider than the pane at 1440 and 1024, no horizontal scroll container of its own | every table gets its own horizontal scroll with a sticky first column; charts size to their container | Layout · "plan for growth and clipping" |
| MEDIUM | the six workspace headers (`page.tsx:590, 770, 887, 2117, 2319, 2330, 2342`) | title + selects + switcher + range + primary in 44px | the header carries **title · one status chip · one primary action**; context (connection, schema, range) lives in a 36px context bar; layers in a 36px tab row; filters in a toolbar. Four rows at most, each optional, each with one job (§4.3) | Layout · "group with space, not lines"; the reader parses one decision per row |
| MEDIUM | `CatalogScreen.tsx:1252`, `:1275` | three titles, a clipped filter | one title in the header; the filter in the toolbar; the list pane's label becomes the connection's name | Typography · heading hierarchy |
| LOW | `page.tsx:272` topbar theme toggle as two text buttons "dark · light" | two 23px text buttons in the chrome | one icon toggle in the user menu | Icons · "if an icon and a word say the same thing, the icon goes" applies the other way in chrome: a persistent two-word control for a rare action |

`Block` until the three HIGH rows land.

### 2.4 · Room to read — `MEDIUM`

The user's ask was *nothing compressed, clustered unnecessarily*. Instrument's answer to a crowded screen is
"better hierarchy at the same density, never more whitespace". Both are right about different things: the
hierarchy is missing (§2.3), **and** the reading size is wrong — 11px is Instrument's floor and it has become the
default.

Measured (text nodes by computed size; controls under the 24px target minimum):

| Screen (1440) | 10px | 11px | 12px | 13px | 15px | 22px | Controls < 24px |
|---|---|---|---|---|---|---|---|
| Briefing (theLook) | 0 | **284** | 54 | 38 | 3 | 8 | 31 |
| Agent Ops overview | **11** | 101 | 106 | 3 | 0 | 5 | 41 |
| Catalog | 0 | 55 | 22 | 98 | 0 | 1 | 33 |
| Semantic Layer | 0 | 92 | 28 | 28 | 1 | 0 | 3 |
| SQL Editor | 0 | 10 | 21 | 25 | 0 | 0 | 19 |
| Home | 0 | 46 | 32 | 3 | 1 | 4 | 6 |

The Briefing — a page a person *reads* — is 73% 11px text. Agent Ops carries eleven nodes below the floor the
lint gate is supposed to hold. The segmented item is 23px tall (`.aug-seg-item`, padding `3px 8px` at 11px),
the "View all →" link 17px; Instrument's own button is 26.

| Severity | Location | Location detail | Before | After | Why |
|---|---|---|---|---|---|
| MEDIUM | type roles | every panel decides (4,673 inline `style={{…}}` in 173 files; IDEAS.md 14 counted 4,463 in 219 two weeks ago) | 11px for meta, labels, table cells, captions, tile sub-labels and most prose | **Roles, not sizes:** `display 22` (a Reader's title only) · `h2 15` · `body 13` (anything a person reads as a sentence) · `meta 12` (timestamps, counts, sub-labels) · `label 11 mono` (ids, column names, uppercase section labels). The Briefing's findings, the Evidence claims, the Memory readings, the Departures "why" column are body, not meta | Typography · "size and contrast floors"; the product asks people to read |
| MEDIUM | `.aug-seg-item`, `.aug-tab`, text links | 23px and 17px targets | 26px (the button height) for every segmented item and tab; links inside a 24px line box | Accessibility · 24×24 minimum, 40 on desktop where density permits |
| MEDIUM | the ten screens with an always-open form: Actions › Declare (all fields, kinds, HTTP verbs, headers and body inline), Documents › Set how it is cut, Spend › Declare the cap, Evidence filters, Semantic › Add | the form is the page | a **slide-over** opens the form when the primary is pressed (§4.6); the page shows what exists | Layout · progressive disclosure; a form is a task, not a view |
| LOW | Agent Ops overview | 10px text (11 nodes) | 11px floor enforced by `lint:tokens` on computed output, not only literals | the gate exists and did not catch a class it exists for |
| Decision | density | one density | a **Comfortable / Compact** preference on tokens (`--row-h` 28/24, `--gap-2` 12/8, body 13/12), comfortable by default — the user's call (§6) | Instrument says density is a feature; the user says room is; both can be true per person |

`Approve` with the work listed.

### 2.5 · Colour is a data type — `MEDIUM`

Computed from the live tokens (`getComputedStyle(document.documentElement)`), WCAG contrast against `--bg-0`:

| Token | Dark value | Dark contrast | Light value | Light contrast | Rule |
|---|---|---|---|---|---|
| `--t1` | `#e9ecee` | 14.96 | `#12171a` | 14.79 | AA 4.5 ✓ ✓ |
| `--t2` | `#99a2a8` | 6.84 | `#59636a` | 5.04 | ✓ ✓ |
| `--t3` (captions, meta) | `#7c878d` | **4.83 ✓** (was 4.23 before the 2026-09-22 lift) | `#77828a` | **3.22 ✗** | AA 4.5 |
| `--t4` (never text) | `#545c62` | 2.61 | `#929ba1` | 2.32 | not text — held |
| `--b0` (the row rule) | `#23211f` | 1.11 | `#eee9e0` | **1.01** | a rule must be seen |
| `--b1` (default border) | `#2c2928` | 1.23 | `#e1dacf` | 1.14 | |

| Severity | Location | Before | After | Why |
|---|---|---|---|---|
| MEDIUM | `web/aughor-v2/theme/tokens-v2.css` light block | captions at 3.22:1 on 53 elements of the Home alone; the row rule at 1.01:1 — a light-theme table has no rules | lift light `--t3` to ≥ 4.5 (about `#5e6971`), light `--b0` to ≥ 1.25 and `--b1` to ≥ 1.4 against `--bg-0`, validated by `lint:palette` | Instrument §0: "Light is designed, not inverted"; today it is inverted and paler |
| MEDIUM | `web/app/page.tsx:685-688` (Home stat cards) | four tiles accented blue · violet · green · amber **by position** | no accent, or the accent of the state the figure is in | Instrument §3: "if a hue appears, a reader can name the state it means" |
| MEDIUM | the sparkles icon on Agentic run cards (fig. 9), on the Notifications rail item (`page.tsx:335`, `icon: "spark"`), on Org (`IntelligenceWorkspace.tsx:68`) | violet sparkles = "AI" | the agent's own mark (the roster already gives each agent one); Notifications gets a bell or a webhook glyph | IDEAS.md 14, "the AI costume" |
| LOW | blue on the Catalog's active "Suggested" chip and the "+ New" primary | fine | fine — noted as the correct use | — |

`Approve` with the work listed; the light-theme rows are token edits, one commit.

### 2.6 · Numbers and words reach a reader, not a log — `HIGH`

Arc PX's law is *no machine text reaches an eye*. The sweep held on the surfaces PX touched and did not reach
the ones built since. The number itself — CP-5's formatter — is still per door.

| Severity | Location | Before | After | Why |
|---|---|---|---|---|
| HIGH | Briefing "Numbers that moved" tiles and findings (`web/components/BriefingPanel.tsx`, `extractKeyFigure`, `web/components/brief/keyFigure.ts`) | `180925` · `1820497.55` · `3561748.63` · `13984300.82` · `7.49e+06`; a tile whose text is the model's self-critique ("The query returns 180925 total sold inventory items, but with no category grouping, it does not answer…") shown as a number that moved | **one reader-facing formatter** (CP-5, `lib/format.ts` is the home): thousands separators, the metric's unit, currency from the org setting once per page, precision from the metric, never scientific notation; a tile renders only a figure whose finding **states** a figure, and a finding that is a caveat about itself is not a mover | the product is a claim about a number |
| HIGH | object page (`web/components/objects/ObjectView.tsx`) | `Revenue 114.98999977111816 USD`; then `average_order_value_aov 114.99 EUR` · `Order Line Revenue 114.99 USD` · `revenue 114.99 $` — three currencies for one value on one page | the same formatter; one currency symbol per page, from the org setting; a metric's declared unit wins over a column's guess; when the currency is undeclared the page says so once | one number, one reading |
| HIGH | `web/app/page.tsx:841` (run cards), Memory table's CONNECTION column, Departures' `sb_e2d5c528af66:#aughor_canvas`, Security & Audit's `8233e4fdtheLook` and its AGENT column (`SecurityAuditPanel.tsx:102-126`: `__brief_metric_move__`, `card:2878362c`, `cb2_review`, `Watchermonitor`, `YouQuery Builder`), `BrainMapPanel.tsx:56` (`GET /graph`), Settings › System packs (`0m · 0r · 0e`), Agent Ops "NEEDS YOU" (`monitor:Units Sold anomaly watch+automation:Units Sold anomaly watch: Units Sold: over the last 90…`) | hashes, dunders, route paths and concatenated keys as names | **one name resolver**: a connection id renders as its name, an agent key as its display name, an internal caller as "the Briefing's metric check" or "a dashboard card", a Slack destination as `#channel`; the raw key stays in a hover card and the copy button. A concatenation of two names is two lines. Route paths belong in the door's tooltip, not on the box | PX law; a reader cannot act on `cb2_review` |
| MEDIUM | Evidence (`web/components/EvidencePanel.tsx`) | claims that are intake specifications ("Investigation Specification: ROUTING: this is a temporal-change question…"), sentences cut mid-number ("The 2,744.", "at 16,811 items (3."), `no query recorded`, confidence 0.50 on most rows (a fixed heuristic) | the ledger lists **claims** — a sentence with a figure and a query; specifications and routing notes are trace, not evidence; a truncated sentence is a bug in the extractor, not a row; a heuristic confidence is not drawn as a number | Instrument §8 trust system: a confidence is computed or absent |
| MEDIUM | Graph (`web/components/ConnectionGraphPanel.tsx` warnings), Memory readings, Monitors names, Notifications' "Logs50", Documents' `📄` (`DocumentUploader.tsx:529`) and `ChatPanel.tsx:1088`, the Ontology strip's back-ticked "approve \`aov\`", the Briefing's "across all inventoryitems" | "a rebuild would add 6 metric — the committed graph predates them (the live path writes incrementally, so projection fixes and grown sources only land on a full rebuild)"; a remembered reading that is a reviewer's note ("Totally wrong calls."); a monitor named by a finding's first sentence; a count glued to a label; an emoji where Instrument forbids one | plain sentences ("The graph is behind: 6 metrics were added since it was built. Rebuild"); a reading shows the term and its reading, and the note in the inspector; a monitor is named by its metric and its rule; counts are badges; the glyph is a Tabler icon | Writing · "no machine text"; Instrument §8 "emoji are forbidden" |
| MEDIUM | Briefing (Workspace/amazon) | the FULL SYNTHESIS opens "LuxExperience's marketplace data…" on the *amazon* schema; the theLook synthesis prints `$` while the Profile says the currency is **undeclared** | the synthesis names the connection it was written for; a figure whose currency is undeclared carries no symbol | truth in copy |
| LOW | Semantic › Metrics "UNIT" column | `percent 0-100 (typically 40-75) (measured ≈ 51.86)` in one cell | unit in the cell; the typical band and the measured value in the row's inspector | one fact per cell |

`Block` until the three HIGH rows land; the formatter and the resolver are two functions with many callers, not many fixes.

### 2.7 · One way to wait, one way to be empty — `MEDIUM`

| Severity | Location | Before | After | Why |
|---|---|---|---|---|
| MEDIUM | Data Canvas ("Loading…", fig. 11), Catalog ("Loading the catalog…", fig. 5), Agent Ops overview ("Loading overview…", fig. 4), Briefing ("Reading this connection's schemas…"), against the skeletons the Briefing, Activity and the Catalog list already use | four idioms | one: a skeleton shaped like the content it precedes (`SkeletonRows`, `.aug-skeleton`); a sentence only when the wait has a *reason* a person can act on | Instrument §5: no text-only loading; the same wait should look the same |
| MEDIUM | Home, first run (fig. 1) | a welcome card with three steps, then four "Get started" cards, then four tiles showing `—`, then "No health metrics configured", then "No Agent runs yet" — five blocks saying nothing yet | one hero (ask, or the three steps until a connection exists) and nothing below it until something exists; a tile never shows a dash, it shows its door | Layout · "order by importance"; an empty tile is not information |
| MEDIUM | Health | one sentence | see §2.2 | — |
| LOW | Inbox, Org, Notifications, Roster | empty states with a door and a sentence | keep — these are the model | — |

`Approve` with the work listed.

### 2.8 · The keyboard and the reader — `MEDIUM`

| Severity | Location | Before | After | Why |
|---|---|---|---|---|
| MEDIUM | `web/components/CommandPalette.tsx` result rows (13 buttons with no accessible name in the tree) | a screen reader announces "button" thirteen times | each row's name is its title; results are a `listbox` with `option`s and roving focus | Accessibility · accessible names everywhere |
| MEDIUM | Catalog favourite toggles (13 × "Favorite") | identical names | "Favorite orders" / "Unfavorite orders" | — |
| MEDIUM | 23px segmented items, 17px links | under 24×24 | 26px targets (§2.4) | WCAG 2.5.8 |
| Not verified | focus rings on every stop, Escape on every overlay, focus return, reduced motion, 200% zoom | — | — | needs a keyboard walk in a visible pane |

### 2.9 · What already shows judgement — keep

The Briefing's verdict-first page with "Numbers that moved" and "Ask this briefing"; the Ontology page's
measured-key and bindings structure; the Brain map's boxes-with-doors idea (minus the route text); the Agent
Ops overview's tiles that say "a floor, not a total" and "click a tile to see where its number comes from"; the
Departures ledger's WHY column in plain sentences; the object page's Properties · Links · Findings · Actions ·
Metrics · Notes order; Integrations' copy; the SQL workbench (catalog rail, tabs, run/format/history, "ask about
this SQL — proposals arrive as a diff"); the Documents page's honesty about the embedder; the Attention card that
says "One decision: accepting creates the monitor and saves the chain — all or nothing". These are the bar.

---

## 3 · Surface by surface

Each row: the verdict in better-ui's terms, the finding that decides it, and the figure. Severities refer to §2.

| Surface | Verdict | What decides it | Fig. |
|---|---|---|---|
| **Topbar** | Approve | wordmark · workspace · LIVE strip (renders only once state resolved — on cold loads it is absent) · ⌘K · theme as two text buttons (LOW) · avatar. Missing: the connection context and a "Needs you" tray (§4.6) | 1–13 |
| **Rail** | Approve | 28px rows, groups, collapsible — as decided. 18 items + Settings; last rows under the footer at 768 tall (MEDIUM); one of nine Intelligence layers reachable (MEDIUM) | 3 |
| **⌘K palette** | Block | unnamed result rows (MEDIUM, systemic for keyboard users); the field reads "Search — or ask Spotlight anything…" — good | tree |
| **Home, returning** | Approve | Ask box with Quick/Agent and a placeholder that is three example questions; four "Get started" cards; four tiles; health; recent activity as a table. Tiles with decorative accents (MEDIUM); "View all →" 17px | probe |
| **Home, first run** | Approve | five stacked empties (MEDIUM) | 1 |
| **Inbox** | Approve | "Recommendation Inbox" title repeated in the header and the panel; empty state is a model | capture |
| **Data Canvas** | Approve | "Loading…" text (MEDIUM); a good list page otherwise: search, All/Created by me, grid/list, sort | 11 |
| **Briefing** (theLook) | Block | header crowding (HIGH at 1024); EXPLORER status + Trigger Intel + Refresh + Standing/Day/Week/Month/Year + Schedule + Regenerate + Reload — ten controls above the verdict; unformatted tile figures (HIGH); the self-critique tile; `$` on an undeclared currency | 3 |
| **Briefing** (Workspace/amazon) | Block | "0.119171" as a headline ratio; a tile whose figure is a threshold ("1000" from `rating_count > 1000`); a synthesis about LuxExperience on the amazon schema | text |
| **Profile** | Approve | clear sections; "No table profile yet" while the Ontology reports 124,778 measured rows one tab over (MEDIUM — the two layers disagree about the same connection); governed-metric formulas printed in full in a rail (LOW → inspector) | capture |
| **Ontology** | Approve | dense but structured; the strip's back-ticked copy (MEDIUM); the EXPLORER DRAFT bar carries five actions; Human edits / Proposals / Learned skills are doors in a header — fine | capture |
| **Graph** | Approve | developer-speak warning (MEDIUM); five identical "UNPROBED JOIN … nothing has measured whether the key values actually overlap" cards — group as one row with five joins (LOW) | capture |
| **Evidence** | Block | claims that are specifications and truncated sentences (MEDIUM, but the ledger is unusable as evidence until fixed); the filter chips are lowercase labels "all 80 · unreviewed 80 · validated 0…" — the table is the right shape | capture |
| **Memory** | Approve | good table; raw connection ids (HIGH class); a reviewer note as a reading (MEDIUM); "served 0×" on six of seven | capture |
| **Actions** | Approve | the Awaiting-approval card is the best card in the product; the Declare form is the page (MEDIUM → slide-over) | capture |
| **Org** | Approve | the model empty state | capture |
| **Brain map** | Approve | route paths on boxes (HIGH class, one line each); otherwise the clearest new screen | 8 |
| **Agent runs** | Approve | header says "Recents" (MEDIUM); `Agentic · 8233e4fd` on every card (HIGH class); sparkles in violet; three tiles then a card grid — readable | 9 |
| **Health** | Approve | one sentence (MEDIUM, §2.2) | capture |
| **Documents** | Approve | the wizard leads with chunk parameters greyed out (MEDIUM → disclosure); `📄` (MEDIUM); the embedder notice is honest and good | 10 |
| **Catalog** | Block | Filter clips at 1024, three titles (HIGH/MEDIUM); the draft connection duplicates every LuxExperience table in Suggested; "BigQuery 0 schemas · 0 tables" and "Aughor Ops 0 schemas · 0 tables" listed without a reason (MEDIUM) | 5 |
| **SQL Editor** | Approve | the strongest screen: catalog rail with insert-at-cursor, tabs, Compose/Write toggle, run settings, format, history, shortcuts, ask-for-a-diff; a horizontal overflow of 800px in a 496px pane at 1024 (results table — needs its own scroll) | capture |
| **Semantic Layer** | Approve | SCOPE tree + five tabs + a long explanatory paragraph before the table; UNIT column packs three facts (LOW); the state column ("In use · approved", "Formula rejected", "Needs binding") is good | capture |
| **Agent Ops › Overview** | Block | body wider than the pane (HIGH); RANGE under the tabs at 1024 (HIGH); 10px text (LOW); the NEEDS YOU title is a concatenated key (HIGH class); the tiles and the roster table are good | 4 |
| **Roster** | Approve (warm) / Block (cold) | cold: false empty (HIGH, §2.1); warm: a list + "Select an agent." detail | 7 |
| **Attention** | Approve | the proposal card; "Alert rulesnone yet" glued (LOW); a third navigation level | capture |
| **Activity › Usage** | Approve | three levels + range (MEDIUM); skeletons — the right wait | 12 |
| **Automations** | Approve | rows with Design · Run now · History · Mute · Edit · Delete — six actions per row (LOW → primary + ⋯); `schedule(0 9 * * *) → investigate(What changed in theLook ), slack_post(#aughor_canvas)` as the description (MEDIUM: cron and call syntax to a reader) | capture |
| **Hub** | Approve | "Every automation, one screen" — good; raw connection ids and `● not_fired2026-09-25 00:00` glued (HIGH class, LOW) | capture |
| **Departures** | Approve | the WHY column is the model of plain sentences; `sb_e2d5c528af66:#aughor_canvas` (HIGH class) | capture |
| **Monitors** | Approve | one monitor named by a finding's first sentence (MEDIUM); Total/Active/Unacked tiles | capture |
| **Notifications** | Approve | "Triggers · Logs50" (LOW); the empty state's "when you action a…" (LOW); the destination is misnamed (§2.2) | capture |
| **Integrations** | Approve | the copy is the best in the product; long paragraphs could fold behind "Why an app, not OAuth" (LOW) | capture |
| **Spend** | Block (cold) / Approve (warm) | cold blank pane (HIGH); warm: the "floor, not a total" framing is exemplary; the cap form is inline and unlabelled in the tree (MEDIUM → slide-over); the governance feed is 500 rows of "query safe" (LOW → group identical events) | 6 |
| **Security & Audit** | Block (cold) / Approve (warm) | cold blank pane (HIGH); warm: the raw-id chip in the header, `8233e4fdtheLook`, machine agent names (HIGH class) | capture |
| **Evals** | Approve | suites named by wave with paragraph descriptions (stored data — a curation task, as PX recorded); Runs and Experiments are readable | capture |
| **Settings › Organization** | Approve | one long page: org, playbook, priorities, localisation, appearance, "open on the conversation", owners — six topics; a settings *index* on the left would make it seven pages (MEDIUM) | 13 |
| **Settings › Access** | Approve | roles, groups, members, measured users — dense but honest | text |
| **Settings › Appearance** | Approve | two options (LOW, §2.2) | text |
| **Settings › Models** | Approve | provider, three roles, catalogue, fallback — the copy is careful; the page is a wall | text |
| **Settings › System** | Approve | stats, backend, packs with `0m · 0r · 0e` (HIGH class) | text |
| **Chat** (`/chat`) | Approve | a conversations rail with `✎ 🗑` glyphs (Instrument forbids emoji) and twelve identical "Give me route wise number of flights" rows — group by question; Quick/Agent + agent picker; suggested questions | capture |
| **Object page** | Approve | the structure is right; the raw float and the three currencies (HIGH); the "Workbench" back link says where it goes | text |

---

## 4 · The layout system — one grammar for every screen

The ask was *a proper layout mechanism that is consistent*. This is it: a shell, six page templates built from
one region stack, a spacing and type-role scale, a taxonomy of the things that float or slide, and the rules for
narrow widths — each with the number a builder needs. It keeps Instrument's tokens and primitives and replaces
its one-line shell sentence (§4.5) with a grammar.

### 4.1 · Principles the grammar enforces

1. **Context before content.** Nothing paints its empty state until the shell knows the workspace and the
   connection. The skeleton is the honest first frame.
2. **A row has one job.** Title row, context row, layer row, toolbar row: four rows at most, each optional, never
   two controls of the same kind in one row.
3. **The rail lists destinations; a destination shows its layers once.**
4. **Reading text is 13px.** Eleven is for ids and labels in mono. Density is a preference, not a house rule.
5. **A number is formatted and a name is resolved on every door**, by one function each.
6. **Details open beside, not instead.** A row's detail is an inspector; a task is a slide-over; a fact is a
   popover. The page you were on stays under it.
7. **Nothing clips.** Rows wrap or scroll with a cue; tables scroll inside themselves; a control is always
   reachable at 1024.

### 4.2 · The shell

```
topbar 48   wordmark · workspace ▾ · CONNECTION ▾ [schema ▾] · ⌘K · LIVE strip · Needs-you tray (badge) · user ▾ (theme, sign-out)
rail 248/48 Home · Needs you · Ask · Briefing · Runs · DATA (Catalog · SQL · Semantic) · MODEL (Ontology · Graph · Actions)
            · OPERATE (Agents · Automations · Monitors · Departures) · GOVERN (Spend · Security · Evals) · Settings (pinned)
content     header 44 → context bar 36 → layer tabs 36 → toolbar 36 → body (+ inspector 400–480)
```

- **The connection is global context.** Today three screens carry their own selector (Intelligence, Security &
  Audit, the SQL workbench's combobox) and others inherit silently. The topbar carries it once; a screen that is
  not per-connection (Runs, Spend, Settings) shows it dimmed with "all connections". The URL keeps `?conn=`.
- **Needs you** is one tray and one destination: proposals awaiting approval, held departures, automation
  approvals, broken automations, recommendations — the counts `useNavCounts` already computes, in one place.
- The rail stays as decided: 28px rows, 2px gaps, collapsible to 48, the footer pinned — and the body scrolls
  under a fade so the last rows are never hidden.

### 4.3 · The region stack (every page is built from these, top to bottom)

| Region | Height | Carries | Rule |
|---|---|---|---|
| **Header** | 44 | title (13/600, or 22 on a Reader) · one status chip · **one primary action** (Primary button) · a `⋯` menu for the rest | never a select, never a switcher, never two primaries |
| **Context bar** | 36 | the scope that changes what the body means: schema, RANGE, period, "as of", the explorer status | segmented controls live here; at most two per bar |
| **Layer tabs** | 36 | the destination's layers as `.aug-tabs` (underline) — one idiom for layers everywhere | scrolls horizontally with an edge fade; a trailing **More ▾** lists clipped tabs; the active tab scrolls into view |
| **Toolbar** | 36 | search, filters, view toggle (grid/list), sort, count line ("13 of 80") | filters are chips or a filter popover; never a form |
| **Body** | — | the template's content (§4.4) | max width by template; gutters 24 (16 under 1200) |
| **Inspector** | body height, 400–480 wide | the selected row's detail | docked at ≥1440, an overlay drawer below; `?inspect=` in the URL; Esc closes; resizable; width remembered |
| **Footer** | 28, optional | status line: "measured 12 s ago", pagination | — |

The Intelligence header today = header + context bar + layer tabs collapsed into one row. Agent Ops = header +
context bar (RANGE) + layer tabs + a second tab row. Naming the rows is what stops the collapse.

### 4.4 · Six page templates

| Template | For | Body | Inspector |
|---|---|---|---|
| **Reader** | Briefing, a report, the object page, a document | one column, measure **720px** for prose (Instrument's `--shell-measure`), 880 with exhibits; sections set off by a rule; figures right-aligned mono | a finding's detail, "why this number", the receipt |
| **Ledger** | Runs, Departures, Evidence, Audit, Monitors, Evals runs, Memory, the Hub | a table: sticky 22px header, 28px rows (24 compact), first column sticky, the table scrolls inside itself; row click → inspector | the row |
| **Console** | Agent Ops overview, Spend, Security overview, Brain map, Home | a tile row (4–6 tiles, each with its provenance line), then one chart, then one ledger; tiles open their source in the inspector | the tile's source rows |
| **Workspace** | Ontology canvas, Graph, the automation Design canvas, the SQL workbench | full bleed, its own chrome inside the body; a left rail (catalog, domains) 240–280 collapsible; the inspector is the canvas's own | the selected node |
| **Detail** | Catalog table, an agent, an automation, a metric, a suite | a two-pane: list 280–320 left (searchable), detail right with its own tab row | — (the detail is the page) |
| **Form** | Settings, Models, Access | a left index of sections (200), one section per page, fields in a 2-column grid at ≥1200, labels above, help below, one Save per page | — |

Where today's surfaces land: Home → Console · Inbox/Needs you → Ledger · Data Canvas → Detail · Briefing →
Reader · Profile → Reader with a domain rail · Ontology/Graph → Workspace · Evidence/Memory/Departures/Runs/Hub
→ Ledger · Actions → Ledger (declared) + slide-over (declare) · Org → Ledger · Brain map → Console · Catalog →
Detail · SQL → Workspace · Semantic → Detail · Agent Ops overview → Console · Roster → Detail · Attention → Ledger
· Activity → Console + Ledger · Automations → Ledger (+ Workspace for Design) · Monitors → Ledger · Notifications
→ Ledger · Integrations → Form · Spend → Console · Security → Console + Ledger · Evals → Ledger · Settings → Form
· Chat → its own (a conversation) · Object → Reader.

### 4.5 · Spacing, type roles, density — the numbers

- **Spacing** `4 · 8 · 12 · 16 · 24 · 32 · 48`. Within a group 8; between groups **≥ 16 (2× within)**; between
  sections 24 above a rule and 16 below; label → control 6; page gutter 24 (16 under 1200); card padding 16;
  tile padding 16/20.
- **Type roles** (sizes stay Instrument's six): `display 22` · `h2 15/600` · `body 13/400, lh 1.7` · `meta 12`
  · `label 11 mono uppercase, +0.04em` · figures mono tabular at the size of the text they sit in. A role is a
  class (`aug-role-body`), and `lint:tokens` counts raw `fontSize` literals down from 4,673 inline styles.
- **Density** is two token sets: **Comfortable** (default): row 28, tile 88, gap-2 12, body 13, meta 12.
  **Compact** (opt-in, per person, remembered): row 24, tile 72, gap-2 8, body 12, meta 11. Tables, ledgers and
  the rail read the tokens; prose never compacts below 13.
- **Controls**: buttons 26 (small 22 only inside a 24px table row), segmented items 26, tabs 36 row / 26 target,
  icon buttons 26 square, inputs 28. Nothing interactive under 24×24.
- **Amendment to Instrument** (the one disagreement): §6's shell sentence `header 44 · screen title · context meta
  · segmented layer switcher · primary action` becomes the region stack above; §8's "nav item 22px" is already
  28 by the user's call. "The answer to a crowded screen is better hierarchy at the same density, never more
  whitespace" stays true for a ledger and stops applying to a Reader.

### 4.6 · What floats, slides or pops — the overlay taxonomy (the "extra surfaces")

Instrument allows three floating things (popover, toast, dialog). Two more are needed, and each existing
"details inline" pattern maps onto one of them.

| Surface | Behaviour | Size · motion | Use it for | Not for |
|---|---|---|---|---|
| **Inspector drawer** *(new)* | right-docked panel, **non-modal**, the page stays live and scrollable; selection in the page drives it; `?inspect=<kind>:<id>` in the URL; Esc closes; resizable 400–480; remembers width; at <1440 it overlays with a scrim-less shadow | slide 260ms `--ease-out` from the right; reduced motion: appears | a run, a table, a finding, a claim, a departure, a metric, an agent, a proposal, a monitor, the "why this number" chain, a governed metric's formula | editing (that is a slide-over) |
| **Slide-over** *(new)* | right sheet, **modal**, 520 wide (720 for a wizard), focus trapped, Esc asks if dirty | slide 260ms; reduced motion: fade | every create/edit today drawn inline: Declare an action, New monitor, New trigger, New automation (the form step), Add data, Upload a document (the cut settings and the review), Declare a cap, Seed a trusted query, Create agent | reading |
| **Popover** | anchored, `--bg-3`, `--b2`, radius 4, `--shadow-sm`; origin-aware (`transform-origin` at the trigger) | 160ms | "why this number", guard chips, a receipt, an owner card, an **id hover card** (name, kind, the raw key, copy), a filter builder, the More ▾ menu of a tab row | anything with a form longer than two fields |
| **Dialog** | centred, `--shadow-md` over `--scrim` | 160ms pop 0.98→1 | destructive confirms, "accept all-or-nothing" proposals, sign-in | reading or browsing |
| **Toast** | bottom-right, 3px rule in its hue, stays while an action or error is on it, pauses when the tab is hidden | 160ms | outcomes ("Monitor created — open") | progress |
| **Command palette** | ⌘K, **no entrance animation** (decided), rows are named options | — | search, ask, commands | — |
| **Needs-you tray** *(new)* | a topbar popover listing the five queues with counts and the three oldest items; "Open all →" to the destination | 160ms | proposals, held departures, approvals, broken automations, recommendations | acting — the action happens on the item's page or inspector |
| **Hover card on identifiers** *(new)* | a popover on any resolved name: connection, agent, run, receipt, Slack destination | 160ms after 400ms; instant for subsequent cards | the raw key, kind, links | — |

Rules across all of them: one overlay layer at a time (a popover may sit on a drawer; a dialog closes both);
focus moves in and returns to the trigger; every one closes on Esc; motion tokens only (`--dur-2/3`,
`--ease-out`), reduced motion ends at the finished frame; the drawer and the slide-over are URL-addressable so
a link reproduces the view.

### 4.7 · New and changed surfaces, concretely

1. **Global connection context in the topbar** (retires three per-screen selectors; the SQL workbench keeps its
   combobox as a *tab-level* override because a query is bound to a connection).
2. **Needs you** — the tray and one ledger replacing Inbox + Attention as destinations.
3. **The inspector drawer** on every ledger and console (runs, departures, evidence, memory, hub, catalog list,
   roster, brain-map boxes, spend feed, audit rows).
4. **Slide-overs** for the nine inline forms.
5. **Home**: first run = one hero with the three steps; returning = ask hero · "since you were here" (what
   changed: findings, held sends, proposals — three lines each with a door) · runs in a ledger. No dashed tiles.
6. **Briefing header diet**: title + Regenerate as the primary; the explorer status, period (Standing · Day · Week
   · Month · Year) and Schedule in the context bar; Trigger Intel and Reload in `⋯`.
7. **Intelligence split**: Briefing · Profile · Evidence · Memory · Org · Brain map under Intelligence; Ontology ·
   Graph · Actions under a new **Model** destination — the authored layer beside Data (the user's call, §6).
8. **A settings index**: Settings becomes seven short pages with a left index instead of one scroll.
9. **A grading affordance on every answer surface** — 👍/👎 and "correct" on a Briefing finding, a run card, a
   Slack post's mirror, the object page's findings — the funnel Arc TJ (ROADMAP §3.47, TJ-4) needs; drawn as
   Instrument's trust primitives, not as emoji.
10. **The screenshot gate** (§4.9) — a CI surface, not a user one, and the only thing that keeps the rest true.

### 4.8 · Narrow widths

Breakpoints come from the content, not from devices; three are enough:

| Width | Rail | Inspector | Tab rows | Tables |
|---|---|---|---|---|
| ≥ 1440 | open 248 | docked | fit | fit or scroll inside |
| 1200–1439 | open | overlays | scroll + More | scroll inside |
| 1024–1199 | **auto-collapses to 48** (the user's expanded state is remembered and restored above 1200) | overlays | scroll + More | scroll inside, first column sticky |
| < 1024 | collapsed | full-width sheet | scroll + More | scroll inside |

Never a clipped control, never a horizontal page scroll, never two controls on one pixel. 200% zoom at 1440 is
the 720 case and must hold.

### 4.9 · How it stays true

- **Components, not conventions.** `<Page>` with `<Page.Header>`, `<Page.Context>`, `<Page.Layers>`,
  `<Page.Toolbar>`, `<Page.Body>`, `<Page.Inspector>`; `<Ledger>`, `<Console.Tile>`, `<SlideOver>`, `<Inspector>`,
  `<HoverCard>`. A screen that composes them cannot put a select in the header.
- **Lint.** `lint:layout` fails a `.aug-content-header` with more than one segmented control or any `<select>`;
  `lint:tokens` counts inline `style={{` down from 4,673; the 11px floor is checked on computed output in the
  screenshot run, not only on literals.
- **The screenshot gate.** A Playwright run over every `?tab=`/`layer=` URL and the two routes, at 1440×900 and
  1024×768, dark and light, on the fixture database: it fails on a horizontal overflow, a control whose right
  edge passes the viewport, a `<main>` with no text at 10 s, a text-only "Loading" after 3 s, a computed font
  size under 11, and it stores the images as the review artefact. The headless recipe and the DOM probe in §8
  are the seed; a person still looks at the pictures.
- **The strings dump.** Once a release, every user-visible string in one file, read top to bottom (IDEAS.md 14 §6);
  the vocabulary ratchet gains the slop list (Unlock, Seamless, "great work", exclamation marks, emoji, dunders,
  hex ids, `GET /`).

---

## 5 · What to build, in what order

A recommendation for Arc UI's second movement (ROADMAP §3.16 lists what Instrument's first pass left), not a
roadmap entry — that is the user's to make. Sizes assume one builder; nothing here spends a model call.

| Wave | What | Size | Receipt | Falsifier |
|---|---|---|---|---|
| **UI-1 Context and states** | the context state machine; skeletons on every wait; the picker always rendered; copy that names only what is on screen; no blank `<main>` | 1–2 days | every URL cold-loaded on an empty profile shows a skeleton, then content, never an empty state before context resolves; the six cold captures in §2.1 re-taken and clean | any URL blank or falsely empty at 10 s |
| **UI-2 The page grammar** | `<Page>` regions; the header diet; the context bar; layer tabs with overflow; RANGE out of the title row; tables scroll inside themselves; the six workspaces migrated | 1–2 weeks | 0 clipped controls and 0 horizontal overflows at 1024 across every URL; no header with two segmented controls; the same screen at 1440 and 1024 differs only by wrapping | a screen that needs a select in its header to work |
| **UI-3 Numbers and names** | the formatter on every door (CP-5's seam); the name resolver; the hover card on ids; the slop sweep in §2.6 | 3–4 days | the strings dump carries no hash, dunder, route or e-notation; every figure on the Briefing tiles, the object page and the tiles has separators and a unit; one currency per page | a figure a reader cannot read aloud |
| **UI-4 Inspector and slide-overs** | the drawer on every ledger and console; the nine forms into slide-overs; URL-addressable | 1–2 weeks | a run, a departure, a claim, a table and a proposal open beside their list; a link reproduces the view; Esc and focus return on every one | a detail that still replaces its page |
| **UI-5 Rail, names and Needs you** | the 12-item rail; Runs; Triggers; Needs you tray and ledger; Health folded; Appearance into the user menu | 2–3 days | the rail fits at 768 tall without hiding a row; every layer reachable from its destination in one click | — (decisions in §6) |
| **UI-6 Room to read** | type roles; the density preference; light-theme tokens lifted; 26px targets | 2–3 days | Briefing body text at 13px; no computed size under 11; light `--t3` ≥ 4.5 and `--b0` ≥ 1.25 by `lint:palette`; no control under 24×24 | a reader who prefers compact cannot get it |
| **UI-7 The screenshot gate** | the Playwright run, its assertions, its artefacts in CI on the fixture DB | 2 days | a planted clipped control fails CI; the run's images are attached to the check | the gate passes a screen a person rejects |

Order: UI-1 first (it is the invariant), UI-2 and UI-3 in parallel (grammar and content are separable), UI-4 after
UI-2 (the drawer is a region), UI-5 and UI-6 whenever the decisions are in, UI-7 alongside UI-2 so the grammar
lands with its gate. Total: about five weeks of build; every wave ships behind nothing — layout is not a flag,
it is the product — so each wave's receipt is its own screenshots, both widths, both themes, in the PR.

---

## 6 · Decisions that are the user's

1. **Density default** — Comfortable by default with Compact opt-in (recommended), or Instrument's density with a
   Comfortable opt-in.
2. **The connection as global context** in the topbar (recommended) — it retires three selectors and makes every
   deep link honest; the SQL workbench keeps a per-tab override.
3. **Splitting Intelligence** into Intelligence (read) and Model (authored: Ontology · Graph · Actions) — recommended;
   the alternative is one nine-tab row with overflow.
4. **Health's fate** — fold into Briefing/Profile until a target exists (recommended) or keep the rail item.
5. **Needs you** replacing Inbox and Attention as destinations (recommended) — Inbox's recommendations become one
   of five queues.
6. **The light-theme token lift** — `--t3` to ≥ 4.5 and the rules to ≥ 1.25 (recommended; a token change moves
   every site at once, which is the point).
7. **The screenshot gate in CI** — recommended; it is the only way the grammar survives the next forty screens.
8. **Details beside, not instead** — the inspector drawer as the default for every ledger row (recommended); the
   alternative is today's mix of inline expansion, full-page swaps and modals.

---

## 7 · Not verified

Hover, focus-visible and active states on every control; keyboard walks (Tab order, Escape on overlays, focus
return); motion at 10% speed (the 2026-09-14 review fixed its findings; this study did not re-run it); the
Catalog table detail and its eight tabs; the Add-data panel; an opened Data Canvas; the automation Design canvas
and the Trace explorer; the SQL workbench's visual mode and a result table; the Ontology drawers; dialogs and
toasts; the light theme *rendered* (measured through tokens only — the pane was hidden and could not composite
frames for most of the session, so every screenshot is headless and dark); 200% zoom; RTL. None of these is
approved by omission.

---

## 8 · Method notes and the figures

**The DOM probe** (run in the page at each width): visible interactive elements under 24×24; text nodes by
computed font size; elements whose `scrollWidth` exceeds `clientWidth` under `overflow` auto/scroll/hidden;
`.aug-content-header` control counts and the rightmost control's edge against the viewport; inline-styled
element counts; computed token values and WCAG contrast in both themes.

**Headless capture** (Chrome, fresh profile per shot): `--headless=new --user-data-dir=<fresh> --timeout=10000
--window-size=1440,900 --force-device-scale-factor=2 --screenshot`. `--virtual-time-budget` never settles against
the dev server's live socket and must not be used; a stale `SingletonLock` from an interrupted run blocks the next
one. The blank-pane result was re-taken at `--timeout=25000` and on a profile that had already loaded Home.

**Method files** (`docs/assets/ui-study-2026-09-25/_method/`): `capture.sh` (the headless capture, one screen per
call), `urls-1440.txt` and `urls-1024.txt` (every URL the study captured), `probe.js` (the DOM probe above, ready to
paste or to run through Playwright's `page.evaluate`), and `canvas/` (the five artboards and the index of the
"Aughor Layout Grammar" canvas, as `.dc.html` sources). The screenshot gate of §4.9 starts from these four files.

**Figures** (`docs/assets/ui-study-2026-09-25/`, JPEG at 1280 wide from the 2× originals; every rail tab, every
Intelligence and Agent Ops layer, the Evals layers, `/chat`, and six screens at 1024):

| Fig. | File | What it shows |
|---|---|---|
| 1 | `home.jpg` | first-run Home on an empty profile: five stacked empties, tiles showing `—` |
| 2 | `intelligence.jpg` | cold Intelligence: "No connection selected… Pick one above" with no picker |
| 3 | `intelligence-1024.jpg` | the Briefing header at 1024: layers clipped after Memory; the rail's last rows under the footer |
| 4 | `agentic-ops-1024.jpg` | Agent Ops at 1024: RANGE drawn under the layer tabs; "Loading overview…" |
| 5 | `catalog-1024.jpg` | Catalog at 1024: three titles, the Filter box clipped, "Loading the catalog…" |
| 6 | `spend.jpg` | cold Spend: a blank pane |
| 7 | `ops-agents.jpg` | cold Roster: "No custom agents yet" while two exist |
| 8 | `intel-brain.jpg` | cold Brain map: "Pick one above" |
| 9 | `recents.jpg` | Agent runs: "Recents", `Agentic · 8233e4fd`, violet sparkles |
| 10 | `documents.jpg` | Documents: the wizard leading with greyed chunk parameters; the emoji drop zone |
| 11 | `canvases.jpg` | Data Canvas: "Loading…" |
| 12 | `ops-activity.jpg` | Agent Ops › Activity: rail → layers → sub-tabs → range |
| 13 | `settings.jpg` | Settings › Organization: one long page with an Appearance section beside an Appearance tab |
| 14 | `intel-ontology.jpg` | cold Ontology on theLook: "No ontology data available." — a false empty |
| 15 | `query.jpg` | cold SQL editor with `?conn=` in the URL: "Select a connection…", "No schema loaded."; otherwise the strongest screen |
| — | the rest | `inbox` · `intel-profile` · `intel-graph` · `intel-evidence` · `intel-memory` · `intel-actions` · `intel-org` · `health` · `catalog` · `semantic` · `agentic-ops` · `ops-attention` · `ops-automations` · `ops-hub` · `ops-departures` · `monitors` · `actions` · `integrations` · `security` · `evals` · `evals-runs` · `evals-experiments` · `chat` · `home-1024` · `query-1024` · `spend-1024` |

**Companion artboards.** The layout grammar of §4 is drawn on a Design canvas, "Aughor Layout Grammar"
(https://claude.ai/artifact/7uAuvqMjwVScM9ZdYFPFda — private until shared): the shell with its regions measured, the
Briefing redrawn at 1440 with the inspector open, Home for a returning person, Agent Ops at 1024 with the grammar
holding, and the overlay kit. Each board carries an "annotate" tweak that hides the spec labels.

## 9 · Theme direction — Databricks for dark, Excel for light (proposed 2026-09-25, awaiting the user's opinion)

The ask that followed the study: *"tokens, colours, design layout to be more like Databricks for dark and more like
Excel for light — they are so easy to read and interact with."* Drawn as eleven artboards on the Design canvas **"Aughor
Two Skins"** (https://claude.ai/artifact/XvA4nrhaGxTLjSWLs5VCc3 — private until shared): the two token sets side by
side with their contrast measured, then the Briefing and the Agent Ops overview in each skin, and — added the same day at the user's ask — the agent's
own page that the click on an agent opens — its Overview (boards 6–7), its Runs tab (8–9: a 30-day run chart, Range ·
Status · Trigger · Filter, the ledger with a link per run) and its Setup tab (10–11: the Form template, one field per
field of the agent model, revisions beside it) — drawn from `aughor/custom_agents/models.py`: purpose, instructions,
connection and schema scope, bound documents, packs, tool grants that only ever propose, the golden-suite pass chip,
revisions. In Play the tabs move between the three and the breadcrumb returns to Agents. Sources in
`docs/assets/ui-study-2026-09-25/_method/canvas-skins/`: `gen.py` builds every board from ONE layout and two token
dicts, so the dark and light screens differ by tokens and four skin rules and by nothing else. The calls in §9.4 were
taken the same day and the boards redrawn to them; nothing is yet written into `INSTRUMENT.md` or `tokens-v2.css` —
that lift is wave UI-6 of §5.

### 9.1 · What each reference actually does for the reader

**Databricks (Du Bois).** Cool navy greys, not warm charcoal: 900 `#11171C` for the page, 800 `#1F272D` for every
surface that sits on it, 500 `#92A4B3` for secondary text. Borders you can see (`#3F5162`). One blue for everything
interactive — 400 `#8ACAFF` links, 500 `#4299E0` marks and the active tab, 600 `#2272B4` the one filled button — so
"you can click this" is never in doubt. Tags as bordered pills; tabs as text with a 2 px underline; 13 px base with
40 px table rows.

**Excel.** A white grid on grey chrome (`#F3F3F3`); near-black text; gridlines both ways (`#E1E1E1`) so every value
has a box; figures right-aligned with fixed decimals. Green is the app's own state — the selected cell's thick border,
the active sheet tab, the primary — and blue is only a link. State on a value is a cell fill, not a badge: Good
`#C6EFCE`/`#006100`, Bad `#FFC7CE`/`#9C0006`, Neutral `#FFEB9C`/`#9C5700`. Two regions do most of the "easy to
interact with": the formula bar, which states the selected cell's definition, and the status bar, which says Ready
and the selection's aggregates. Cell text is ~14.7 px.

### 9.2 · Proposed tokens — INSTRUMENT's names, new values

| Token | Dark now | Dark proposed | Light now | Light proposed |
|---|---|---|---|---|
| `--bg-0` page | `#181818` | `#11171C` | `#EDE8DF` | `#FFFFFF` |
| `--bg-1` chrome | `#1C1B1A` | `#1F272D` | `#FDFBF7` | `#F3F3F3` |
| `--bg-2` card | = bg-1 | `#1F272D` — a card is one step lighter than the page | = bg-1 | `#FFFFFF` — a box drawn by its border |
| `--bg-3` input, inset | `#211E1C` | `#11171C` | `#F5F1E9` | `#FFFFFF` |
| `--bg-hover` | = bg-3 | `#26313A` | = bg-3 | `#EBEBEB` |
| `--bg-sel` | `#322921` | `#142E45` | `#E4EFF9` | `#E6F2EB` |
| `--code-bg` | `#141313` | `#0B1116` | `#FAF7F1` | `#FAFAFA` |
| `--b0` row rule, gridline | `#23211F` | `#253039` | `#EEE9E0` (1.01:1 measured) | `#E1E1E1` (1.31:1) |
| `--b1` panel edge | `#2C2928` | `#2F3C47` | `#E1DACF` | `#D4D4D4` |
| `--b2` control border | `#3A3531` | `#3F5162` | `#CFC6B8` | `#C4C4C4` |
| `--b3` strong | `#4D463F` | `#5F7281` | `#B2A897` | `#8A8A8A` |
| `--t1` | `#E9ECEE` | `#E8ECF0` | `#12171A` | `#1F1F1F` |
| `--t2` | `#99A2A8` | `#92A4B3` | `#59636A` | `#424242` |
| `--t3` captions, the floor | `#7C878D` | `#8496A4` (4.96:1 on chrome) | `#77828A` (3.22:1 measured) | `#616161` (5.58:1 on chrome) |
| `--t4` never text | `#545C62` | `#5F7281` | `#929BA1` | `#8A8A8A` |
| blue 1 · 2 · 3 · 4 | `#0E2130 #163C56 #4C9AD6 #7BB8E4` | `#0E2A44 #1F4A75 #4299E0 #8ACAFF` | `#E8F1F8 #C2DAEE #1C6FB5 #17558B` | `#DDEBF7 #9DC3E6 #0F6CBD #0B5394` |
| green | `#0C2A20 #134838 #3EAB82 #6BC9A6` | `#14331F #1F5A33 #3CAA60 #8DDDA8` | `#E5F3ED #BCDFCF #14795A #106044` | `#C6EFCE #8FD3A8 #1E7B45 #006100` |
| amber | `#2A2310 #4C4018 #B88D30 #DCB667` | `#3A2A10 #6B4A1A #DE7921 #F2BE88` | `#FAF0DF #EFD9AE #8F5A08 #834900` | `#FFEB9C #E6C35C #B25E00 #9C5700` |
| red | `#2C1418 #502229 #D45B6A #E68792` | `#3B1A21 #6E2536 #E65B77 #F792A6` | `#FBEAEC #F1C3C9 #B32639 #931F32` | `#FFC7CE #F09AA5 #C50F1F #9C0006` |
| violet | `#1A1832 #2C2852 #8B7DC8 #ADA2DC` | `#2A2140 #4A3B70 #9C7BDD #C0A9EE` | `#EFEBF9 #D2C8ED #5F45A8 #4A3487` | `#EADDF7 #C9A9EA #6B3FA0 #4B2C7F` |
| `--primary` the filled button | `#1F6CB0` | `#2272B4` (5.08:1 under white) | `#1C6FB5` | `#107C41` Excel green (5.27:1) |
| selection edge, active tab | blue3 | `#4299E0` | blue3 | `#107C41` |
| link | blue3 | `#8ACAFF` | blue3 | `#0F6CBD` |

Every text role clears 4.5:1 on the surface it sits on, in both sets; `gen.py` prints the table (the tightest pair is
light amber text on its tint, 4.66:1). Cyan, `--chart-1…7` and `--chart-deemph` are untouched: the chart palette is
validated by `lint:palette` and its CVD order is a guarantee, so it moves only through that gate. Geometry stays
3 · 4 · 6; light uses 3, dark 4.

### 9.3 · What changes in the layout, and what does not

The region stack of §4.3 holds in both skins — topbar 48 · rail 248 · header 44 · context bar or toolbar 36 · layer
tabs 36 · body · inspector 400 on the Briefing. Two regions were proposed from Excel and **refused the same day**;
the boards were redrawn without them:

- ~~The definition bar~~ (a Name box, *fx*, and one line stating what the selected thing is and where it comes from —
  Excel's formula bar for a number). Refused 2026-09-25: the Briefing keeps §4.3's context bar (explorer status ·
  period · schedule) and its inspector; on Agent Ops the click on an agent opens that agent's own page and nothing
  opens inside the overview — no inspector, no selected row, the agent names are links.
- ~~The status bar~~ (Ready · scope · what is withheld · the selection's figure · density). Refused 2026-09-25 for
  both screens; "withheld is said" stays where §2 put it — on the card or the line that carries the figure ("all
  finished runs metered · cost unpriced").

Rows 34 px, controls 28 px (from 26), body 14 px (from 13; §4.5 and UI-6's receipt move with it). Four skin rules,
and only four: gridlines both ways (light) against hairline rows (dark); layer tabs as sheet
tabs (light) against text with a 2 px blue underline (dark); state on a value as Good/Bad/Neutral cell fills (light)
against bordered pills (dark); the selection as a 2 px green outline plus tint (light) against a blue edge plus navy
tint (dark). Kept as decided: the verdict-first Briefing; no numbered gutters — Excel's row numbers are not adopted;
28 px rail rows and the collapsible rail; press scale on the primary only; PX-6; the chart palette.

### 9.4 · Decisions — taken by the user 2026-09-25

1. Body text 13 → 14 px (Databricks 13, Excel ~14.7) — **agreed.**
2. Figures in Inter with tabular numerals; mono only for SQL and ids — **yes.**
3. The light accent: Excel green for selection, active tab and the primary with blue kept for links, or blue for all
   of it as in dark — **keep the different colours**: green is light's own state, blue is dark's; a link is blue in
   both. Green carries two meanings in light (the app's own state and "verified"), which Excel gets away with
   because one is chrome and the other is a cell fill.
4. The definition bar as a standing region — **no; removed.** The click on an agent must open that agent's page;
   nothing appears in the overview.
5. The status bar as a standing region — **no; removed from both screens.**
6. Sentence-case 12 px semibold labels in place of 11 px mono caps — delegated; **sentence case** it is (neither
   reference uses mono labels).
7. Light chrome: Excel grey `#F3F3F3` — **yes.**

### 9.5 · Implemented — the first movement (2026-09-25, on `claude/arc-tj-trajectories`)

The token lift and the reading size are on the live app. `web/aughor-v2/theme/tokens-v2.css` carries both skins
(§9.2's values; dark `--amb3` `#D57420` and light `--chart-7` `#DC1E98` are the two moves `lint:palette` asked for —
the amber for the lightness band, the kind accent for 6 ΔE from the new blue under CVD). `styles/type.css` puts body
at 14 and chrome at 13 (`.aug-fs-chrome`), figures in Inter with tabular numerals (`.aug-num`), and labels at 12 px
semibold sentence case. `app/globals.css` re-dresses the rail (13 px items, sentence-case groups), tabs and
segments (13 px, 28 px targets), tables (32 px rows, a 30 px sentence-case header, figures in Inter), kinds, metas
and eyebrows, and ends with the skin rules — light gridlines both ways, the green tint and green text for light's
active segment and rail item — and the new `.aug-toolbar` row. `Workspace.toolbar` carries the Agent Ops range under
the header instead of beside the layer switcher (§2.3's HIGH). The filled button reads `--primary`, so it is Excel
green in light and Databricks blue in dark. Seven gates, `tsc --noEmit` and the web suite pass.

**The second movement, the same day.** `StatusChip` is a 12 px Inter pill in dark and a borderless cell fill in light
(the `aug-chip` rule); the open `StatTile` wears `--accent` on `--bg-sel`, with Excel's 2 px outline in light. **The
agent's own page is live** (`AgenticAgentsPanel`): the Roster is an index — one row per agent, kind-labelled — and
a row opens the agent as a page: a 44 px header with the breadcrumb back to Agents, the name, its chips (kind · the
golden pass chip · active/paused) and its actions (Chat, Pause), then tabs Overview · Runs · Map · Quality · Setup
(`.aug-tabs`, the accent underline), then the body. Overview keeps the honest run view and gains a 360 px details
rail — connection, schema scope, documents and packs BY NAME (a count until the names load, never an id), what it
may propose (never execute), state, owner, created/updated, the instructions. Runs is a `.aug-dt` ledger of every
run with a Trace door per deep run. Quality is the golden suite (was "Benchmark"), Setup the form (was "Configure",
with guardrails and the configuration history still inside it). Charters wear the same header. Nothing opens
inside the Overview layer; the click on an agent arrives here. Not drawn from the mockup: the held-answers strip,
a Revisions tab (history lives in Setup), a Departures tab.

**The third movement, the same day: the Briefing's figures and the header diet.** The precision policy in
`lib/format.ts` (`normalizeNumberPrecision`) now does three things to a number inside prose it did not compose,
none of which changes a value: it expands scientific notation (`7.49e+06`), collapses float noise as before, and
groups a bare magnitude of five digits or more (`180925` → `180,925`, `1820497.55` → `1,820,497.55`); years, dates and
already-grouped figures are untouched. `extractKeyFigure` runs the policy on the statement before it looks for a
figure, so the Briefing's tiles read `180,925` and `1,820,497.55` where they read the float's own spelling, and the
ledger rows group with them. Four cases in `keyFigure.test.ts` hold it.

The workspace shell (`Workspace.tsx`) now draws §4.3's region stack, one job per row: **header 44** — the
workspace's name and its one action; **context bar 36** — what scopes the view (Intelligence's Connection and
Schema pickers, sentence-case labels), only when there is one; **layer tabs 36** — the perspectives as underlined
tabs (`.aug-layer-tabs`; sheet tabs on chrome in light) in a row that scrolls rather than clips; **toolbar 36** — what
filters the view (the Agent Ops range). Measured at 1024: the Intelligence header holds one title where it held ten
controls with the rightmost at 1201 px; all nine layers fit their row with no overflow; the page has no horizontal
scroll. The Briefing's explorer strip lost its last tracked-caps label and keeps its status on one line.

**The fourth movement, the same day: ids as names, and nothing paints before it knows what it is showing.**
`web/lib/names.ts` is the one name resolver §2.6 asked for — pure, beside `format.ts`: a connection id renders as its
name (a labelled `connection 8233e4fd` until the list answers, never the bare hash), a dunder caller as its roster
name and its job (`__brief_metric_move__` → Briefer · metric move check; `cb2_review` → Curator · measurement;
`card:…` → You · a pinned card; any other dunder as words), a departure's `sb_…:#channel` as `#channel`, and the
needs-you title the API composes (`monitor:X+automation:X: …`) as the names it joins on one line with the sentence
under it. Routed through it: the run cards, the audit's AGENT and CONNECTION cells and its title, the Memory ledger
and the trusted queries' scope, Departures, the Attention rows and the Overview's needs-you cards; the Brain map's
`GET /graph` doors moved to each box's tooltip; the packs line reads `0 metrics · 0 roles · 0 evals`.

§2.1's root cause was two things. `?tab=spend` and `?tab=security` (and the other rail ids that are layers) had no
render branch on a cold load — only `navigate()` knew the aliases — so the pane painted blank with no header;
`resolveDeepLinkTab` now reads the same module-level tables navigate() does, for Operations, Intelligence and Agent
Ops as it already did for Data. And no screen had a state for "still resolving": the shell now carries
`contextReady` (both the connections and the workspaces have answered, either way) and every empty state that
depends on a connection reads it — the Briefing says "Finding your connections…" and its picker is in the context
bar; the Brain map says "Finding your connection…"; the Ontology says it is loading rather than "No ontology data
available."; the Roster says "Loading agents…" until both lists answer. "Pick one above" is gone from the copy.
The seven cold captures re-taken on fresh profiles at 14 s are in `cold-after-2026-09-25/`: Spend and Security
render their workspace, the Briefing and the Ontology show skeletons with the picker present, the Roster lists both
agents, the SQL editor opens on the URL's connection, the Brain map is reading its stores.

Not yet: the density preference; the Evidence ledger's specification rows (§2.6 MEDIUM); the object page's three
currencies for one value (§2.6 HIGH, `ObjectView.tsx`).
