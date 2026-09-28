# A cockpit you ask for — json-render, and where it fits (study, 2026-09-28)

> **Why now.** The user, with `vercel-labs/json-render` on screen: *"Where can use this? Be a little open to ideas
> here.. and some wild but relevant use cases.."* After a first mock: *"it needs to be full extension version with
> (sections, tabs, conditional tiles)"*; then *"But will this use Vega that we have in place already ?"* and *"Lets
> study and add it to the roadmap."* This document is the measurement, then the proposal. The code was measured on
> `main` at `1913fd8d`; the library was measured from its npm registry entries and its own documentation on
> 2026-09-28. **The library was read, not run** — nothing was installed. §7 lists what that leaves unknown, and
> CT-1 is the wave that runs it.

## 1 · What the library is

json-render turns a JSON description of a screen into real interface, using only components from a catalog the
host defines. The model (or plain code) writes the JSON; the host owns every component and every action.

| what | measured | where from |
|---|---|---|
| version | `0.21.0`; every package pins the same core version exactly | npm registry |
| age | first published 2026-01-14, last published 2026-09-18; pre-1.0, a Vercel Labs project | npm registry |
| licence | Apache-2.0 | npm registry |
| React | `@json-render/react` needs `react ^19.2.3`; the web runs 19.2.4 | npm registry, `web/package.json` |
| Zod | core needs `zod ^4`; the web lockfile already holds 4.4.3, as a peer of the `ai` packages, not as a direct dependency | npm registry, `web/package-lock.json` |
| size | core 1.22 MB and react 0.57 MB **unpacked** — not the weight a page pays | npm registry |
| chart engine | none; it arranges components the host registers | documentation |

**The spec** is a flat map, not a tree of nested objects: a `root` id, an `elements` map, and an optional `state`
object. Each element carries `type`, `props`, `children` (ids), and optionally `slots` and `visible`.

**Expressions inside props:** `$state` reads a path, `$bindState` reads and writes one, `$cond`/`$then`/`$else`
picks a value, `$template` interpolates, `$computed` calls a function the host registered, and `repeat` with
`$item`/`$index` walks a list.

**`visible`** is one condition, a list (all must hold), or `{"$or": [...]}`. A condition is a `$state` path with at
most one of `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, and `"not": true` to invert it.

**Actions** are declared in the catalog and handled by functions the host registers; a spec can name a declared
action and nothing else. `setState` is built in. **`watch`** fires an action when a state path changes — with no
click at all.

**Validation:** `validateSpec` checks structure (dangling children, malformed conditions, repeat scopes) and
`autoFixSpec` repairs what it can. **Edits** to an existing spec arrive as RFC 6902 patches, one per line.
**The prompt** is generated from the catalog (`catalog.prompt()`), so the model is told exactly the components
that exist.

**State from outside:** the host hands the renderer its own store (`StateProvider` with `store`), so the facts a
condition reads can be the platform's and not the spec's.

**Render targets beyond React** that matter here: `@json-render/react-pdf`, `@json-render/react-email`,
`@json-render/image` (its peer is `@resvg/resvg-js`, which `bots/slack/` already carries) and
`@json-render/mcp`. There is no PPTX target.

**Not taken:** `@json-render/shadcn`. Its 36 components are built on Radix; the web is built on Base UI.

## 2 · What is already here

| # | what | where | what it means for this |
|---|---|---|---|
| 1 | The cockpit exists. It is the Briefing's standing layer, "Your cockpit" | `web/components/BriefingPanel.tsx` → `brief/PinnedCards.tsx` | not a new concept; a new home and a new shape |
| 2 | A card is drawn by `PinnedCardBody` → `ResultChartCard` → `Chart` → `resolveVegaSpec` → `VegaChart` | `web/components/brief/PinnedCardBody.tsx`, `web/components/Chart.tsx` | **charts stay on Vega**; no other chart library is imported anywhere in the web source |
| 3 | Four card kinds: note, kpi, chart, watch. A card holds its guarded SQL, its refresh history, its thresholds and its provenance | `aughor/dashboard/models.py` | the card is already the unit that measures |
| 4 | One cockpit per connection per person, with no name: the arrangement is keyed on connection and user | `aughor/dashboard/store.py` (`get_layout`, `set_layout`) | a "returns cockpit" and a "revenue cockpit" cannot sit side by side today |
| 5 | The server stores and lists cards by canvas; no screen asks. All five call sites in the web pass `scope: "connection"` | `aughor/dashboard/store.py` (`list_cards`); `PinnedCards.tsx`, `NewCardComposer.tsx`, `BriefingPanel.tsx`, `QueryBuilder.tsx` | the canvas cockpit is half-built and unused |
| 6 | The Data Canvas has three tabs — Chat, History, Artifacts — no cards and no range control | `web/components/CanvasWorkspace.tsx` (`WsTab`) | the fourth tab is the gap |
| 7 | A card already runs cut to a range and says what it covers | `POST /cards/{id}/run` (BR-9), `aughor/routers/dashboard.py` | the range is host state that exists |
| 8 | A watch card graduates to a Monitor | `POST /cards/{id}/graduate` | a watch's status is host state that exists |
| 9 | A closed answer vocabulary the model composes from: six part kinds, version 1. Used in 3 of 42 turns where it was offered | `aughor/agent/present_tool.py`, §3.11 AV-M | the precedent, and a warning: a vocabulary can be offered and not chosen |
| 10 | A closed chart vocabulary: the model names a job or a shape, code builds the chart. Headless rendering uses the same resolver; maps are refused headless | `aughor/agent/chart_vocab.py`, `web/scripts/chart-ssr-entry.ts` | chart kinds are not re-declared in a second place |
| 11 | A versioned artifact store: a write supersedes the version before it and never deletes; it takes a `canvas_id` | `aughor/kernel/ledger.py` (`artifact_write`, `artifact_latest`, `artifact_versions`); used by `aughor/briefing/versions.py` | the spec needs no new store |
| 12 | Adding a proposal kind touches four code sites and a comment in the inbox, one staging site, one list, the approval card's chip and branch, and the typed client | `aughor/actions/inbox.py`, `aughor/agent/spotlight_act.py`, `aughor/agent/authoring_measure.py`, `web/components/ProposalCard.tsx`, `web/lib/api.ts` | the cost of "approve a cockpit" is known |
| 13 | Approved metrics per connection, with status draft, proposed, approved or deprecated | `aughor/semantic/metrics.py` (`list_metrics`) | "is this metric approved" is one call |
| 14 | The numerals law: a number in prose must match a measured value or the send is held | `aughor/govern/departure.py`, `aughor/explorer/grounding.py` | the same law applies to text a model writes into a spec |
| 15 | Python already runs a Node bundle built from the web's own code | `aughor/export/echarts.py` (`AUGHOR_NODE_BIN`) | the renderer's own validator can run on the server the same way |
| 16 | No email door. Delivery goes by webhook, Slack or Jira | `aughor/notifications/models.py` | email would be a new door, with the departure gate in front of it |
| 17 | "Cockpit" and "card" are in the interface and the code and have no entry in the glossary | `docs/GLOSSARY.md` | the arc enters them before it names anything new |

## 3 · What earlier decisions allow and refuse

- **§3.11 (2026-09-15) refused** "an open UI language rendered from model output" and adopted a closed,
  versioned vocabulary in which "an action names an EXISTING governed door and nothing else". A json-render
  catalog is closed in the same way. Three of the library's features cross that line unless they are switched
  off: `watch`, any action a spec could define for itself, and a literal figure typed into a prop.
- **The 2026-06-30 experiment** measured about 14 seconds for layout written by a model
  (`docs/COPILOTKIT_AGUI_ADOPTION_PLAN_2026-07-13.md`). A cockpit is therefore written once, approved, and
  re-rendered at no model cost. It never sits on the path of a live answer.
- **One store per concept.** The spec arranges; the card store measures; the chart vocabulary stays where it is.
- **Provenance is required.** No figure may be written by a model, so no figure may appear in a spec.
- **Withheld is said, never implied.** A card hidden by its own condition and a card the reader may not see are
  two different things and must look different.
- **Supersede, do not delete.** Every approved change to a cockpit is a new version.
- **Flags are off by default and byte-identical when off.**

## 4 · The design

**4.1 · The spec arranges, the card store measures.** The catalog holds five components: `Cockpit`, `Tabs`,
`Tab`, `Section` and `Card`. A `Card` element carries the id of a card in the card store and nothing about
what that card measures. Its SQL, its thresholds, its history and its provenance stay where they are, and it is
drawn by `PinnedCardBody` unchanged.

```json
{
  "root": "cockpit",
  "state": { "tab": "overview" },
  "elements": {
    "cockpit":      { "type": "Cockpit", "props": { "title": "Returns" }, "children": ["tabs"] },
    "tabs":         { "type": "Tabs", "props": { "value": { "$bindState": "/tab" } },
                      "children": ["tab-overview", "tab-watches"] },
    "tab-overview": { "type": "Tab", "props": { "name": "overview", "label": "Overview" },
                      "children": ["sec-headline"] },
    "sec-headline": { "type": "Section", "props": { "title": "Headline", "columns": 4 },
                      "children": ["alert-rate", "card-rate", "card-net", "note-moving"] },
    "alert-rate":   { "type": "Card", "props": { "card": "c_7f3a", "tone": "bad" },
                      "visible": { "$state": "/cards/c_7f3a/status", "eq": "over" } },
    "card-rate":    { "type": "Card", "props": { "card": "c_7f3a" } },
    "card-net":     { "type": "Card", "props": { "card": "c_91b2" } },
    "note-moving":  { "type": "Card", "props": { "card": "c_2d40" },
                      "visible": { "$state": "/range/status", "neq": "final" } }
  }
}
```

**4.2 · Conditions read what the host supplies, and nothing else.** The host publishes a small state tree:
`/range` (its key and whether it is final, provisional or to date), `/cards/<id>/status` (within, over,
unmeasured or withheld) and `/tab`. A `$state` path outside that tree is refused when the spec is validated.
The tree carries statuses, not figures; figures appear only inside cards.

**4.3 · Hidden is counted, withheld is said.** Each section states how many of its cards are waiting on a
condition. A card the reader may not see, or one with no approved metric behind it, stays on screen and says
so.

**4.4 · Validated by the renderer's own validator, then by the platform's rules.** Structure is checked by the
library's `validateSpec` and the catalog, run on the server from a Node bundle built from the web's own
catalog — the same arrangement the chart renderer uses, so the validator cannot drift from what renders. The
platform then checks what only it knows: every `card` id exists in this canvas; every `$state` path is in the
published tree; there is no `watch`, no `on`, and no `$computed` name the host did not register; and every
piece of text a model wrote passes the numerals law. A spec that fails is refused whole, with sentences.

**4.5 · Kept as versions.** The spec is a Ledger artifact of kind `cockpit`, one natural key per canvas.
Cards made for a canvas cockpit are stored at canvas scope. The connection-level cockpit in the Briefing
keeps its arrangement table untouched.

**4.6 · The ask is a proposal.** In a Data Canvas chat, "build me a returns cockpit" stages one proposal: the
cards to create — each naming an approved metric, a trusted query or a finding — and the spec that arranges
them. Approval saves all of it or none of it. A later "move the watches to their own tab" arrives as patches
against the current spec, is approved the same way, and becomes version 2. The model does not write SQL here.

**4.7 · Charts.** A chart card is drawn by the existing Vega path. Should a cockpit ever leave by PDF, email
or image, its charts come from the existing headless renderer as SVG.

## 5 · Where it lives

In the Data Canvas, as a fourth tab beside Chat, History and Artifacts.

- The ask and the result sit together: the chat is where it is asked, the proposal appears there, and the
  approved cockpit lands one tab over.
- A canvas already has a name and a set of tables, so it names the cockpit and limits what the model may choose.
- The server already stores cards by canvas.
- The Briefing is what the platform found for a period; a cockpit is what a person asked to keep watching. The
  Briefing's own code draws that line ("the cockpit is the surface the user curates, not a dump of the brief").

The Briefing keeps its cockpit as it is. Showing a chosen canvas cockpit inside a Briefing is possible later
and is not part of this arc.

## 6 · The other ideas, and what became of each

| idea | status | why |
|---|---|---|
| A cockpit you ask for | **the arc** | the one place the library does what the code cannot: a layout written by someone who is not a developer |
| One Briefing, every door (email, PDF, image card) | named in CT-6, on its trigger | for one fixed layout a plain template is simpler; it pays once one spec feeds several doors |
| Answers inside other AI clients (`@json-render/mcp`) | named in CT-6 | automations already deploy as MCP tools and return text |
| Clarify as a small form | not scheduled | needs the library's event binding, which this study could not read |
| One form renderer for the four field-list forms | not scheduled | they work; the gain is tidiness |
| Industry packages ship views as data | not scheduled | follows once a spec is a kept artifact |
| What-if panels | not scheduled | a scenario is not a measurement; it needs its own label and its own rule |
| Approved layouts as training pairs for Arc TJ | not scheduled | follows once approvals exist to count |
| A video Briefing | not pursued | Remotion carries its own company licence |
| Graduating a layout to code (`@json-render/codegen`) | not pursued | nothing has been used enough to graduate |
| Replacing the chat's answer parts renderer | **not pursued** | 3 of 42 turns used the vocabulary; the renderer is not what is missing |
| Replacing the on-screen Briefing | **not pursued** | 3,330 lines of hand-tuned layout that work |

## 7 · What this study did not measure

1. The library was not installed or run. Its behaviour under React 19.2.4 and Next 16 is read from its peer
   ranges, not seen.
2. The weight it adds to the canvas route.
3. Whether `validateSpec` and the catalog run cleanly from a Node bundle called by Python.
4. Whether `PinnedCardBody` can be registered as a component unchanged.
5. The syntax that binds a click to an action (`on`) and its `confirm` option. Two documentation pages
   described the React side only. The design in §4 uses no action of its own, so nothing depends on it yet.
6. How large the generated prompt is in tokens, and how often a small model's first proposal passes
   validation. The second is the arc's falsifier and costs model calls, which are the user's to spend.
7. Whether the library can export a JSON Schema. None is documented. §4.4 does not need one.

Two mocks were drawn in the conversation, not in the repository. They used the word "tile" and component names
(`KpiTile`, `ChartTile`, `WatchTile`, `NoteTile`) invented for the drawing. The code's word is "card", and the
design above has one `Card` component.

## 8 · The proposal

`ROADMAP.md` §3.50, Arc CT, with its decisions at §6 item 36. **Adopted by the user on 2026-09-28**, as drafted;
the install for CT-1 and the model calls of CT-5's receipt still wait on their word.

| wave | what | waits on |
|---|---|---|
| CT-0 | this survey | done |
| CT-1 | the premise, run: install pinned, render one hand-written spec that hosts two existing cards, state the weight, run the validator from Python | the user's yes to the dependency |
| CT-2 | the catalog and the validator, in one home, with the refusals of §4.4 | CT-1 |
| CT-3 | the spec kept as versions; cards at canvas scope | CT-2 |
| CT-4 | the Cockpit tab, behind a flag, with the range control and the counted conditions | CT-3 |
| CT-5 | ask for it: one proposal, approved all or nothing; edits as patches | CT-4, and the user's yes to the receipt's model calls |
| CT-6 | out by other doors | its trigger: a person asks for a cockpit outside the app |

## 9 · CT-1's receipt — the premise, run (2026-09-28)

The library was installed and run the same day, at the user's *"Yes, install it and start CT-1 and CT-2"*.
**Falsifier (1) did not fire:** the card component is registered unchanged, and the rules run from Python.

| asked of CT-1 | measured |
|---|---|
| install, pinned | `@json-render/core` and `@json-render/react` at exactly `0.21.0`. The lockfile gained those two entries and nothing else. Neither package runs a script on install. `zod` is now declared (`^4.4.3`), at the version the lockfile already held |
| one hand-written spec, drawn | `web/lib/cockpit/premise.fixture.json`: two tabs, two sections, two cards from the card store, one card and one section shown by a condition. Drawn in a browser from this branch's own dev server, with a chart card added: the chart drew its six bars through Vega, and the console showed no error |
| the card component, unchanged | yes. `PinnedCardBody` was not edited. The only change near it is that `PinnedCardsGrid` now exports the card height it already used |
| the states that matter | seen in the browser, not only in tests: a card appears when the host says its watch is over; a withheld card stays in its place and says so; the open tab survives a change of host state; a section waiting on its condition is counted; a refused spec draws nothing and gives its reasons |
| the rules, from Python | yes. `aughor/cockpit/validate.bundle.mjs` is 377,712 bytes, builds to the same bytes twice, and answers in about 60 ms |
| the weight | 88.6 KB gzipped (403 KB minified) for the library, the rules and Zod, with React left out. **24.5 KB gzipped** (76 KB minified) with Zod left out too. Zod is most of it, and the `ai` package the chat already loads imports Zod — so a page of this app may already carry it. The figure on the canvas route itself is CT-4's to measure, once something mounts the cockpit |
| the prompt | `catalog.prompt()` is 15,783 characters for five components. Most of it describes what this arc refuses. CT-5 needs a prompt of its own |

### What running it corrected

1. **The library's validator does not check props.** `catalog.validate` checks a component's name and an
   element's shape. A tone outside the list, a number where a card id belongs and a prop nobody declared
   all passed. The closed catalog is closed by `rules.ts`, which holds every prop to the catalog's own
   schema, strictly.
2. **`watch` and `on` are dropped by the library's parse, not refused.** A spec carrying them validated.
   The rules refuse them by name, with the reason.
3. **A condition on a path nobody publishes is simply false.** The card would be hidden and nothing would
   say why. The rules refuse any path the host does not publish.
4. **§7 item 7 was wrong.** The library does export a JSON Schema (`catalog.jsonSchema()`); its
   documentation does not mention it. The design still does not need it.
5. **`defineRegistry` hides the element from a component**, so a section could not count its own waiting
   cards. The registry is written by hand, and the compiler refuses a missing or an extra component name.
6. **The design system's tabs drew horizontal tabs as a row.** `components/ui/tabs.tsx` styled an
   attribute nothing sets. No screen had used that primitive, so nobody had seen it. jsdom could not see
   it either; the browser did. Fixed at the cause.
7. **One of this wave's own tests passed for the wrong reason.** It handed the renderer a new spec object
   on every render, so the state was rebuilt from scratch and the test stayed green with the host's state
   never reaching an open cockpit. A deliberate break showed it. The test now holds one object, and the
   component is keyed on what a spec says rather than on which object says it.

### Still open after CT-1 and CT-2

- The drift gate is written into CI and has not run there; nothing is pushed.
- `check_spec_for_canvas` was tested against a stand-in for the card store, not a live one.
- The server needs Node wherever a spec is to be accepted, as PDF export already does. Without it the
  verdict is "not checked" and nothing is accepted.
- The active tab is marked by weight alone: the tabs primitive's underline and colour do not draw. It is
  CT-4's to settle when the tab is mounted.

## 10 · CT-4's receipt — the tab, live (2026-09-28)

Run on this branch's own servers (web on 3117, API on 8117) with every store in a scratch
directory, the platform's clocks off and no model key in the environment. The warehouse is
the product's own demo, provisioned through `POST /connections/demo`: three months of revenue
and payment data, September to November 2025.

| step | what happened |
|---|---|
| a canvas, through `POST /canvases` | "Payments", on the demo warehouse |
| six cards, through `POST /cards/pin-query` | each kept at canvas scope, each run through the guard battery before it was kept |
| a limit on one card | payment failure rate, over 1.7 |
| `POST /canvases/{id}/cockpit/start` | version 1: sections by kind, written by code |
| `PUT /canvases/{id}/cockpit` | version 2: three tabs, and an alert card shown while the failure rate is over its limit |
| the tab, read as written | revenue 8.42M, 800 paying customers, failure rate 1.59. The alert card waits, and the section says one card is waiting |
| the tab, read for November 2025 | revenue 2.78M, failure rate 1.84. The alert card appears. Every card says "for 2025-11-01 to 2025-11-29" |
| the second tab | two bar charts, drawn by Vega, cut to the same range |
| the history, "Go back to this" twice | versions 3 and 4, each naming the version it restored |

### What the live run found that the tests had not

1. **A card read for a range showed its all-time figure under the range's label.** Revenue read
   8.42M "for November"; November held 2.78M. The run carried the range's figure in `rows`, as
   text, and `refresh` — the card's standing value — beside it, and the card drew `refresh`.
   This is older than the cockpit (BR-9) and reached the Briefing's cockpit as well. A run now
   says its own `value`, and the card draws that when it was read for a range.
2. **Every ranged card read as unmeasured.** The status check read the figure out of `rows` and
   asked for a number; the server sends text. Twenty tests passed on it, each of them handing
   it a number.
3. **The library draws nothing in place of a component that throws.** A card that failed to draw
   vanished, with a line in the console. A boundary inside the library's now says, in the
   card's own place, that it could not be drawn.
4. **The active tab's underline and colour never drew.** The app resets raw buttons with a rule
   outside any layer, and an unlayered rule beats a utility whatever its specificity.

### What a test that failed one run in six found

The numerals law was held against every title, whoever wrote it. The test's canvas names
were random, and one in seventeen was all digits: the canvas's name became the cockpit's
title, and the title "stated a figure". A canvas called "Store 4521" could not have started
a cockpit. The law is for text a model wrote. Whose words a version's titles are is now kept
with the version, and going back to a version holds it to the rule it was first held to.

### Open after CT-4

- Nothing says a card is `withheld`. The platform has no rule for which cards a reader may not
  see: whoever may open a canvas may see its cards.
- A card can be made on the tab itself. Pinning a finding or a query from the canvas's chat
  still keeps the card for the connection.
- The range control needs `briefing.ranges`. With it off the tab reads every card as written.
- The weight the tab adds to the canvas page was not measured; §9's figure for the library stands.

## 11 · CT-5's receipt — asking for it, run without a model (2026-09-28)

The user's word was *"Start CT-5"*. It was read as the word to build the wave, not as the
word to spend: §6 item 36(f), the model calls of the receipt, is still open. So this receipt
is of everything **but** the model. What a model would write was written by hand and handed
to the tool, against the real stores, the real rules and the real warehouse guard.

### What the survey measured, before anything was built

| asked | measured |
|---|---|
| can the library apply an edit? | it has `applySpecPatch`, and it is lenient by design. A `replace` of a path that is not there **creates** it; a `remove` of nothing and an operation it has never heard of pass in silence; the whole-document path writes a key named `""`. It is built for a spec arriving in pieces. An approved edit must do what it said, so edits are applied by a strict applier of this repo's, in the same bundle as the rules |
| is any chat tool offered only in a canvas? | no. The canvas's id reached the tools only to be written on receipts. `draft_cockpit` is the first |
| what makes a card from a metric, or from a trusted query? | nothing did. A finding had a door (`POST /cards/pin-insight`), a query written by hand had one (`pin-query`), and both ran the guard from inside the router. The guard and the card a finding becomes moved to `aughor/dashboard/doors.py`; both doors and the proposal call them |
| who approved? | the accept route takes the approver's name from the request, and the web sends the name of the screen. Where someone is signed in, a cockpit's version is kept in their name |
| does a chat show a proposal again when it is reopened? | no, for any kind of proposal: the card is drawn from a live frame. It stays in Agent Ops → Attention |

### The tool

One tool, `draft_cockpit`, in three shapes of call. It is offered only when the flag is on,
the turn is in a Data Canvas, and the turn has a channel to draw a card on. Its description
is 918 characters and is sent on every such turn; what a writer needs to know is 7,201
characters and is sent only when `options` is asked for.

| call | what it does | what it costs |
|---|---|---|
| `options` | the approved metrics, trusted queries and findings a card may be made from, limited to the canvas's tables; the cards the canvas holds; the cockpit as it stands; the grammar | no query, no model call, nothing written |
| `new` | stages one proposal: the cards to create and the whole spec | one guarded query per new card |
| `edit` | stages one proposal: the cards to create and RFC 6902 operations against the cockpit as it stands | the same |

The grammar is 3,723 characters, against the 15,783 the library writes for the same five
components. It is written from the constants the rules read, names nothing the arc refuses,
and its example is checked by the rules in a test.

### The run

On this branch's own servers, against the demo warehouse, with no model key in the environment.

| step | what happened |
|---|---|
| two metrics and a trusted query, through `POST /metrics`, `/metrics/{name}/transition` and `/learning/trusted` | proposed, then approved. The first try at one metric was refused by the route itself: a metric's SQL is a whole SELECT. A third metric was left a draft on purpose |
| `options` | two approved metrics, one trusted query, six cards, the cockpit at version 4. The draft metric was not offered |
| an edit with five faults of five kinds | refused once, naming all five: a draft metric; a card carrying a query of its own; a tone outside the list; a condition reading a figure; a title stating a figure |
| an edit whose operation does not apply | refused: "Operation 1 of 1 is refused: … is not in the spec. Nothing was changed." |
| the edit, repaired | staged as one proposal. Three new cards, each with the query read from its record, each run once. The cockpit was still version 4 and the canvas still held six cards |
| the approval card, in Agent Ops → Attention | the arrangement in words, each condition as a sentence, each new card with the record and version it is made from, and no query |
| Accept, in the browser | version 5, kept in the approver's name, with three new cards. Each card records where it came from |
| the tab "Asked for" | the failure rate reads 1.59 against a limit of 1.5, so its section is shown. The chart is drawn by Vega |
| a second edit, drafted twice | the second draft superseded the first. Its card marks the two sections it changes and the two lines it adds, and names the card it takes off and where it was |
| Accept | version 6 |

### What the live run found that the tests had not

1. **A card with a limit said it was alerting.** "Alerting when above threshold", with the
   title "This card is now a scheduled monitor". That was true while graduating a card was
   the only way to give it a limit. A proposal gives a card a limit and schedules nothing.
   The card now says its limit, says no alert is set, and keeps the door to one.
2. **An edit's card said "1 removed" and not what.** The outline is of the cockpit as it will
   be, so what is taken off was nowhere on it. It is now named, with where it was.
3. **An edit's card showed the whole cockpit with nothing marked.** Each line an edit adds or
   changes is now marked, and a line it leaves alone says nothing.
4. **The inbox row read the canvas's id.** It reads the canvas's name.
5. **Stopping the server is not the server being gone.** The first draft ran a second after
   the scratch API was stopped and was warned that the old process still held the stores.
   The later runs waited for the process, not the port.

### What the deliberate breaks found

Sixty-six guards were broken on purpose. All were caught in the end; six were not at first.

1. A trusted query that belongs to another connection had no test.
2. **"Every fault in one round" was half true.** What only the platform knows — a card the
   canvas does not hold, a figure in a title — was asked only of a spec the rules had
   accepted. A spec with a refused field and a card it does not hold was told of the field
   alone, which is the case CT-3 had named. The rules now hand back what they read from a
   refused spec, from the elements whose props were sound, and the platform says its part of
   that in the same refusal.
3. One guard was backed by a second further down, so breaking it changed nothing a test
   could see. Its test now counts that no card was ever made.
4. Two breaks failed tests by exception: a refused draft was read for a field it did not
   have. A test that breaks is not a test that noticed. Drafts are now asserted to be staged,
   with their reasons as the message.
5. One guard was half redundant. It is now one check.

### Not done

- **No model has drafted a cockpit.** Falsifier (2) — fewer than half of first proposals pass
  validation over ten asks on theLook — is unmeasured. So is whether a model asks for
  `options` before it drafts, and how many rounds a repair takes. It was attempted; see §12.
- The reasoning a model gives is held to the numerals law, as titles are. A card's title
  taken from a finding is the finding's own sentence and may state a figure, as it does when
  a finding is pinned from the Briefing.
- A limit set by a proposal schedules no monitor.
- An edit takes a card off the cockpit and never out of the canvas.

## 12 · The receipt by a model — ten asks on theLook (2026-09-28)

The user's word was *"Run the ten asks on theLook"*. **Falsifier (2) fired: 4 of 10 first
drafts passed validation, fewer than half.** Every ask ended with a staged proposal.

### How it was run

Ten asks, sent one at a time to the install's own `/ask` as the canvas's chat sends them:
depth "auto", a fresh session each, the canvas "E-Commerce Operations Overview" on theLook.
Each turn's frames were read as they arrived, and its steps were read back from the
install's own record of the run. Nothing was approved: that is a person's act.

The first ask was sent alone, and was not answered by the tool at all. The install's model,
`typesafe/jev-router` for every role, is recorded by the install as unable to call tools, so
the conversation with tools serves no turn there and `draft_cockpit` is offered to nobody.
"Build me a returns cockpit" was answered as a query of return rate by category. The user
chose `deepseek/deepseek-v4.1-flash` for the run; the coder role was switched to it, and
switched back afterwards. The ten asks below are on that model.

### What each ask did

| # | the ask | first draft | drafts to stage | what the first draft was refused for |
|---|---|---|---|---|
| 1 | Build me a returns cockpit. | staged | 1 | |
| 2 | Make a dashboard for this canvas: revenue, units sold and average order value on top, returns below. | staged | 1 | |
| 3 | I want a cockpit with two tabs, Sales and Returns. Show an alert when the return rate goes above 12%. | refused | 2 | the reasoning stated a figure, 12% |
| 4 | Create a cockpit for the operations team with shipping lead time, sell-through and repeat purchases. | staged | 1 | |
| 5 | Set up a board with gross margin and net merchandise revenue, and show the conversion rate only when the range is final. | staged | 1 | |
| 6 | Give me a cockpit of the key metrics for this canvas. | refused | 2 | placed cards by names the draft had not declared |
| 7 | Build a cockpit from the most interesting findings of this canvas. | refused | 2 | made 19 cards; a draft makes at most 12 |
| 8 | Cockpit with revenue, units and AOV. One section, nothing else. | refused | 2 | placed two cards by names the draft had not declared |
| 9 | I need a returns watch: the item return rate with a limit at 10 percent, and a section that only appears when it is over. | refused | 2 | the reasoning stated a figure, 10%; and a condition was an empty list |
| 10 | Make me an executive cockpit with tabs for Sales, Margin, Customers and Operations. | refused | 3 | made 17 cards; then placed a card by a name it had not declared |

Asks 6 and 8 were first answered by the door itself with a question — "which metric, and
over what time period?" — and were sent again past it, as a person would.

### What held

- **The writer asked first.** `options` was the first call in 10 of 10.
- **Every ask was staged**, in 1.7 drafts on average and never more than three. A refusal
  was repaired in the next draft in six cases of seven.
- **The closed vocabulary closed.** No draft was refused for a component, a prop, a field or
  an expression outside the catalog. No draft carried SQL, `watch`, `on` or `repeat`.
- **A refusal named more than one fault at once** when there was more than one (ask 9).

### What failed, and why the falsifier's reading is "the prompt"

| kind of fault | first drafts | what the writer had been told |
|---|---|---|
| more new cards than a draft may make | 2 | nothing. The cap of 12 is in the code and in no text the writer reads |
| the reasoning repeated the limit the person asked for | 2 | that a figure belongs to a card. A limit the draft itself sets is a setting, not a measurement, and the rule does not tell them apart |
| a card placed by a name the draft did not declare | 2, and one second draft | one sentence in `options`. The refusal then calls it "a card this canvas does not hold" and does not say that the repair is to list it in `cards` |
| a condition that was an empty list | 1 | that a list of conditions means all of them |

Three of the four are things the writer was not told, or was told in words that did not
land. None is a fault of the catalog.

### What it cost

54 model calls for the ten turns: 670,139 tokens in and 39,542 out, about 67,000 in per ask.
A turn took 18 to 90 seconds. Most of what goes in is the roster of some forty tools, sent
on every call of the turn; the answer to `options` is about 12,700 characters of it.

### What the run found beside the falsifier

1. **Where the model cannot call tools, a cockpit cannot be asked for, and nothing says so.**
   The ask is answered as a question about data. The Cockpit tab's empty state invites it
   all the same.
2. **The door pauses a request for a cockpit to ask for a metric and a time period.** Its
   clarify gate is deterministic and reads the request as an under-specified question.
3. **The API froze twice, for 3m45s and for 8 minutes.** After every settled ask the door
   calls the judgment treatment shadow, which is a model call, in the `finally` of
   `stream_with_session_log` — on the event loop. On DeepSeek the reply stalled, and while
   it did the API served nothing and six automations failed every tick. It is older than
   this arc. The last four asks were sent with the shadow switched off, at the user's word,
   and it was switched back. It was fixed the same day: the shadow now runs on a thread of
   its own, and the stream ends without waiting for it.
4. **A refused draft's reasons had been recorded nowhere.** They went to the model and were
   gone. They are now in the step's own `error`, which is how the table above could be
   written.

### Not measured

- Nothing was approved, so the cockpit a model drafted was never drawn.
- All ten asks were for a new cockpit. An edit drafted by a model is unmeasured.
- One model. Whether another passes more first drafts is not known.

## 13 · The three repairs, and the ten asks again (2026-09-28)

The user's word was *"fix the three faults and run the asks again"*.

### What was repaired

| the fault | what the writer is told now |
|---|---|
| more new cards than a draft may make | the cap, in three places: the answer to `options` (`limits.new_cards`), what that answer says of drafting, and the tool's own schema |
| the reasoning repeated the limit the person asked for | the reasoning may name a limit the draft sets, as 12 or as 12%. Any other figure is refused as before, and with no limit set the same figure is a figure |
| a card placed by a name the draft did not declare | that the draft creates none of that name; the exact entry to add to `cards` when the name is an approved metric, a trusted query or a finding; and what the draft does create. Told once for a card that is both placed and read |

What `options` says of drafting now shows one card created, placed and read by the same
name. A spec a person hands in is refused in the plain words it was: the repair is a draft's.

The fourth fault, a condition that was an empty list, was the model's own slip and the rules
already say it plainly. One sentence was added to what `options` says: leave `visible` out
of an element that is always shown.

### The same ten asks

| | first run | second run |
|---|---|---|
| first drafts that passed | 4 of 10 | **10 of 10** |
| asks that ended staged | 10 of 10 | 10 of 10 |
| drafts to stage, on average | 1.7 | 1.0 |
| asked for `options` first | 10 of 10 | 10 of 10 |
| model calls | 54 | 42 |
| tokens in, out | 670,139 and 39,542 | 556,793 and 22,367 |
| the API froze | twice | never |

The first run's calls include the judgment shadow's, one to an ask, on its first six asks;
the second run was made with the shadow off throughout. So the two counts of calls are not
like for like.

Three things the second run showed that the first could not:

- The two drafts that had made 19 and 17 cards made 12.
- Asks 3 and 9 named their limit in percent. Both metrics are declared as a ratio from 0 to
  1, and the drafts set the limits as 0.12 and 0.10. The unit came from `options`.
- The two records of each draft — the frame that a proposal was staged, and the step's own
  `error` — were held against each other for all ten and agreed.

### What this does not show

**These are the ten asks the repairs were written for.** The first run is the measurement
of the prompt as it was. The second shows that the repairs repair what they were aimed at.
Ten asks nobody has seen — other wording, other subjects, an edit among them — are the fair
test, and they have not been run.

Also as before: one model and one canvas; the door paused asks 6 and 8 to ask for a metric
and a period; nothing was approved, so no cockpit a model drafted has been drawn.

## 14 · Ten asks nobody had seen (2026-09-28)

The user chose to run them, through the question tool. Same canvas (`d617964b`), same model
(`deepseek/deepseek-v4.1-flash`), shadow off for the run. The asks were written before the run
and not changed after it (`ct5c_asks.py` in the session's scratchpad). Five ask for a new
cockpit. Five edit the one that stood: the user had approved "Executive Cockpit" (12 cards,
four tabs) at 15:14.

| # | the ask, in short | first draft | by hand |
|---|---|---|---|
| 1 | a morning board: are orders shipping and arriving | staged (as an edit) | a Shipping tab; a second lead-time card beside the first |
| 2 | move return rate onto Sales, after revenue | staged | exactly |
| 3 | lay out a customer view | none | read as a question; the answer was withheld, its figures not in its rows |
| 4 | take the margin chart off | staged | exactly |
| 5 | a category dashboard | refused, then staged | totals, not categories; limits nobody asked for; replaces the cockpit |
| 6 | rename Operations to Fulfilment, lead time last | staged | exactly |
| 7 | a finance view, warn under 45 | staged | a Finance tab, limit at or below 45; a second Revenue card |
| 8 | merge Customers and Operations into Health | staged | exactly |
| 9 | a marketing cockpit on traffic sources | staged | two findings of the canvas and its conversion card; replaces the cockpit |
| 10 | repeat purchase only once the range is final | staged | exactly |

**Falsifier (2) holds: 8 of 9 first drafts passed.** `options` came first in all nine. The one
refusal named `pinned__2`, which `list_findings` had listed: that tool lists the connection's
findings, and a cockpit takes only the canvas's. 62 model calls, 847,529 tokens in and 48,094
out, 689 seconds. Three turns ran to the step ceiling, each after running queries before it
drafted.

**The user approved asks 7 and 10 during the run** (versions 2 and 3). The Finance tab
draws "Limit: at or below 45 · no alert is set". In the view as written, with no range
chosen, the Customers tab says "1 card waits on a condition".

### What passing validation did not catch

- **The numerals law read "11-12%" as "12%".** Ask 5's reasoning said every category "sits near
  11-12%". The 12 matched the draft's limit and the 11 was not read as a figure.
- **A limit nobody named.** Ask 5 set 12% on two return cards; the person named none. The
  second run's repair lets the reasoning name a limit the draft sets. It was written for a
  limit the person asked for, and it licenses one the model chose from a measurement.
- **A card for a metric already shown.** Ask 1 placed a new lead-time card beside the canvas's
  own; ask 7 made a second Revenue card rather than place the first.
- **A new cockpit replaces the standing one whole.** Asks 5 and 9 would take off 9 and 12
  cards. The approval card lists them; the chat did not say it.
- **An ask a cockpit cannot answer.** "Which categories sell best" cannot be a card of a total,
  and the draft did not say so. The turn's last words were a list of bare numbers.

### Not measured

One model, one canvas. Each edit was drafted against the version standing when it was asked,
not a fixed one: asks 8 to 10 were made against version 2.
