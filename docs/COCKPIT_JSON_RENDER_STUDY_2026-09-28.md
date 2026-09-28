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
