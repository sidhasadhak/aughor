# The cockpit as a place to build an App — a study of Workshop, measured against the cockpit (2026-10-10)

**Status: ✅ ADOPTED 2026-10-10 as Arc AP** (ROADMAP §3.57, §6 item 51). The user, on the seven screens: *"Picture
perfect. Just make sure that these charts tables graphs or filters are size adjustables in a swift manner.. at the moment
they become either too large or small.. The size needs to be adjusted one grade point at a time.. Let's finalise this
and immediately start with this arc.."* Every call in §6 is taken as recommended. Call 4 is refined by the user into
§4.9.

**The ask.** *"The cockpit is intended to serve as an application as well as a dashboard from where certain actions
can be taken… when cockpits belonging to different objects start looking exactly the same it becomes a terrible
problem. In the current nothing is editable."* The user sent 22 screenshots of Palantir Workshop building a
"Shipment Operations Center", from an empty page to a button whose action takes the shipment chosen in a Gantt
chart, and asked for this to be gone into hard and deep.

**The answer, in one paragraph.** Make the cockpit's Edit mode a builder in the shape Workshop proved. A page holds
sections, and sections hold pieces. Pieces read **named sets of objects**. What a reader **chooses** in one piece
flows into another. A button's parameters come from what the reader chose. Forms and drawers open over the page.
All of this is built on the platform's own laws:

- a piece holds no SQL; the ontology is its definition;
- wiring is by name, never by expression;
- withheld is said;
- a model may arrange a piece and never adds one;
- read first, edit behind *Edit*.

The starter stops drawing one shape for every entity. It reads the ontology and offers the shape that fits: a
queue, an overview, a map, one object's page, or a timeline. It says why, and everything can be changed after.

**The mockup** is `design-mockups/cockpit-builder.html`, seven screens in the approved theme. They are drawn for
1920 × 1080 and fit a laptop (§4.7). Every number on them was read through the live object door on theLook. The
screens:

1. Start from an object
2. Build
3. Sets
4. Wire an action
5. Add a piece
6. Use it
7. Four cockpits

**Sources.** Four research passes over Palantir's public docs read about 220 pages, about 34,000 words of notes. The
notes are kept outside the repo. Each claim below about Workshop names the page it rests on, listed in §8. A claim
the docs do not settle is marked *inferred*. The user's screenshots are primary evidence where they and the docs
differ.

---

## 1 · What was measured first

### 1.1 Today's starter gives every entity the same page, minus pieces

`GET /cockpits/from-object` was asked about each theLook entity on 2026-10-10 (`aughor/cockpit/from_object.py`).

| Entity | Objects | What the starter offers |
|---|---|---|
| Order | 125,080 | 4 filters · 3 figures · a per-day chart · a 6-column table · 2 actions |
| Order line | 181,412 | 2 filters · 2 figures · a per-day chart · a table |
| Customer | 100,000 | 3 filters · 1 figure · a *customers per day* chart · a table |
| Event | 2,427,901 | 4 filters · 1 figure · a per-day chart · a table |
| Inventory item | 489,809 | 3 filters, **"Product Category" and "Product category" both** · 2 figures · a per-day chart · a table |
| Product | 29,120 | 3 filters · 2 figures · a table |
| Distribution centre | 10 | **one figure: "10"** — nothing else, though every centre has coordinates |
| Case | — | **refused** — held by the platform, never compiled into a warehouse query |

**Every entity the starter can read gets the same five-piece layout or a subset of it — the only differences are
subtractions.** The entity that is plainly a map gets a count. The entity that is plainly a queue — cases, with a
status and two actions — gets nothing.

### 1.2 Nothing about a placed piece can be changed

- Once a piece is placed, there is no control for any of these:
  - a figure's aggregate, property, format or label;
  - a chart's time property or window;
  - a filter column's properties;
  - a table's columns, sort or segment.
- The only route is to take the piece off and place it again. That works for the board, table, detail and button
  only; the three object pieces are made only by the starter.
- The other route is a hand-written spec sent by `PUT`.

The one per-element editor in the product is the rows-card "Edit visualization" drawer (`VizEditorPanel`). It edits a
card, not a piece. Source: the inventory, `web/lib/cockpit/edit.ts` and `web/components/cockpit/*`.

### 1.3 The wiring is fixed

- A detail `follows` one table.
- A button takes its object from the detail around it.
- The filter column narrows every piece whose entity name matches, lowercased.
- An action's second object parameter is never filled.
- Every value parameter is a plain text box.

There is no chart-click-to-filter, no choice that flows from one piece to another, no bulk run, and no drawer.

### 1.4 The door is closed by law, not by accident

`web/lib/cockpit/rules.ts` refuses the rendering library's own state and event machinery. Each refusal says why:

- `on`: *"A cockpit defines no action of its own"*.
- `watch`: *"A cockpit runs nothing without a click"*.
- `repeat`.
- Any `$` expression in a prop: *"In a cockpit a prop is written, never computed"*.

The catalog declares `actions: {}`. These laws were right for a board a model arranges. An App needs one narrow,
typed door through them (§4.1b).

### 1.5 What already exists to build on

- **The object door already compiles sets.**
  - `ObjectQuery` / `ObjectListing` (`aughor/semantic/object_query.py`) take an entity, plus a segment: verified,
    derived from a promise or rule, or overdue.
  - Conditions use 13 operators, with paths across up to 3 links, and `exists` over to-many links.
  - Several measures per query; `by` over to-one paths; a time grain from hour to year; refusals with what is
    available.
  - OC-7 row policies and masks apply to every read.

  Workshop's *object set definition* (a starting set, filters on a property, a variable or a link, and a hop to
  linked objects) maps onto it almost one to one.
- **The action plane is richer than the cockpit uses.** `KineticAction` has:
  - typed parameters (value or object);
  - submission criteria with messages;
  - risk and approval;
  - the outbox, verification and undo;
  - `creates` for platform-owned entities.

  `ActionDesigner` already declares actions in seven steps with a live dry run, and offers "Where it appears".
- **Builder patterns in the product.** `EntityTypeMap` is three panes (a rail, a canvas, a panel). `QueryWorkbench` is
  three resizable panes. `VizEditorPanel` is a model-driven inspector.
- **Versions** keep `changes` (keys added, removed and changed). There is publishing to groups and roles, and a
  release pin with a "since" list.

### 1.6 Five defects found while reading (none fixed here)

1. **Arrange shows pieces as blank lines.** It names elements by `props.card`, which pieces lack.
2. **Moving a section to a new tab breaks an object cockpit.** "Move to tab → A new tab" copies the root's filter
   column into the tab, and the rules then refuse the spec. This is this branch's build.
3. **A reader of a shared App can rewrite the publisher's card.** The rows-card editor writes through
   `PUT /cards/{id}`, which checks only that the card exists. Confirmed in source; it is spawned as its own task.
4. **The cards' Why and Evidence doors never appear.** The Cockpit tab mounts the cockpit without them.
5. **The pin strip prints element keys** for the three object pieces.

---

## 2 · What Workshop is — the parts that matter here

### 2.1 The model

- **A module** is one header, any number of **pages**, any number of **overlays**, and **one shared pool of
  variables**.
- **A page** is a tree of **sections**. A section holds widgets, or is given a layout:
  - columns or rows;
  - tabs;
  - flow;
  - toolbar;
  - loop, which repeats an embedded module per object.

  Sections have headers, can collapse, and can be hidden by a true/false variable.
- **An overlay** is a drawer or a modal. Events open and close it, and a variable can hold its state both ways.
  (`concepts-layouts`)

### 2.2 Widgets

- **Configuration** sits on three tabs: *Widget setup* (inputs, outputs, options), *Metadata* (name, raw JSON) and
  *Display* (sizing, mounting).
- **The catalogue** has about 78 widgets in these groups: core display, visualization, filtering, event-trigger, AIP,
  embedding, scheduling and mobile.
- **The ones that carry an operational app**: Filter List, Object Table, Button Group, Object View or Property List,
  Metric Card, Chart XY, Map, and Gantt or Timeline. The getting-started tutorial builds its inbox from exactly
  Filter List → Object Table → Object View, plus one button. (`concepts-widgets`, `getting-started`)

### 2.3 Variables are the wiring

- There are 12 types: object set, object set filter, string, numeric, boolean, date, timestamp, array, struct,
  geopoint, geoshape and time series set.
- There are 7 ways to define one, including an object set definition, an object property, an aggregation and a
  transformation.
- Variables compute lazily, only for what is visible.
- Widgets never talk to each other. A widget's **output** — *Active object*, *Selected objects*, *Filter output* —
  is a variable another definition reads.
- A Filter List gets its own base set, so a choice never shrinks its own options. The table's set applies the filter
  "using a variable".

The user's screenshots show the result. The variables panel lists *All Shipments*, *Filtered Shipments* and
*Shipments Filter*, each with what uses it, and the button's parameter picker offers *Object table 1 Active object*
and *Selected Shipment, output from Gantt chart 1*. (`concepts-variables`, `widgets-filter-list`)

### 2.4 Events

- **19 verbs**: open and close an overlay; switch page or tab; expand or collapse a section; set, reset or recompute a
  variable; refresh data; open other applications; and a few more.
- **What triggers them**: a button click, a table's active-object change, a chart or pivot selection, an action's
  start or success, an overlay closing, a tab click, a drop.
- **They run in order and do not wait** for what they change to finish recomputing. The docs call this out, and a
  builder that copies the model should fix it rather than copy it. (`concepts-events`)

### 2.5 Actions — where the page becomes an application

**An action type is declared on the ontology:**

- Rules: create, modify or delete objects, or links, or one function rule.
- Parameters, with constraints, defaults and conditional overrides.
- A form with sections.
- Submission criteria, each with its failure message.
- A test run that applies nothing.
- An action log, and undo from the success toast only.
- A writeback webhook *before* the edits and side effects *after* them.

**On a page, a Button Group's *On click → Action*:**

- binds each parameter's default to a variable — typically the table's *Active object*;
- shows each parameter as *Visible*, *Hidden* or *Disabled*;
- can run events on submission start and on success.

The user's last two screenshots show this exact loop. *Parameter defaults → [Gena] Shipment → Local default value →
Select a variable* lists every set and choice on the page that holds a shipment. They also show *Hide form and apply
immediately if valid*, *Button state if invalid: Disabled | Hidden* and *Output object set*. The docs list those on
other widgets; the screenshots are newer.

Two documented limits: **no trigger on failure**, and **a success event cannot run a second action**.
(`actions-use`, `action-types/overview`, `widgets-button-group`, `widgets-inline-action-form`)

### 2.6 What makes building feel safe

- **Save is not publish.** There is a dev link for the last save and a live link for the last publish.
- **A changelog per version**: added, changed, removed, moved, made unused — with JSON diffs and one-click revert.
- **Branches and proposals**, resolved widget by widget.
- **A *Check access* panel** that names exactly which entity, action or function a person lacks.
- **A profiler** that shows each variable's compute time.
- **Live values in the editor**: "Current value: 83 [Gena] Shipments", visible in the user's screenshots, while
  building.

That last one is the quiet reason it feels confident: the builder always shows what each choice holds right now.
(`publishing-and-versioning`, `changelog-panel`, `permissions`)

### 2.7 Why their apps look different

**The data's main axis picks the main widget:**

- place → a map;
- time and a resource → a Gantt;
- a status → a queue;
- links → a graph;
- measures → metric cards.

**The task picks the page shape:**

- triage → three panes: filters, list, detail with the decision in its header;
- monitoring → a strip of figures over a map;
- planning → a full-width timeline.

**Palantir's own starter makes the person pick.** Workshop's home page offers *inbox*, *map* or *metrics*, then asks
for an object type and one property such as the geohash. It never infers the pattern from the data. Inferring it
from the ontology is where Aughor can do better. (`example-applications`; the template images, read in the docs on
2026-10-10)

**Their design rules are numbers** (`application-design-best-practices`):

- at most 10 components in a view;
- at most 5 primary actions;
- filters anchored on the left;
- 30–40% whitespace;
- one elevated main area;
- no horizontal scroll;
- touch targets of at least 30 px;
- a squint test.

These agree with `CLARITY.md` almost line for line.

**A recurring shape across 68 published solution descriptions:** three Apps on one data model — a *control tower* for
the lead, an *inbox* for the operator, and an *outcomes tracker* for the manager. This is a count of words, not of
screens. (`build.palantir.com` catalogue)

### 2.8 Seen, not adopted

- **Pilot** (beta) generates ontology, React code and seed data from a prompt, and hosts the app. Not adopted: §6
  item 50(d) settled *nothing hosted runs code*, and a cockpit stays a declarative spec that the platform checks.
- **The dual-axis chart** in their own operating-picture example. Not adopted: the dataviz law here is one axis,
  never two.
- **Loop layouts, Scenarios, Commands and App Pairing, custom widgets, AIP widgets, mobile.** Later or never. None is
  needed for the loop the user showed.

---

## 3 · The gap, side by side

| Workshop | The cockpit today | Proposed |
|---|---|---|
| Module → pages → sections → widgets | Cockpit → tabs → sections → cards and pieces | Keep; tabs are the pages |
| Section layouts: columns · rows · tabs · flow · toolbar | Sections in a grid, sized by spans; tabs at the top | Add rows, columns and tabs *inside* a section; sizes stay spans, never pixels |
| ~78 widgets | 14 components, 7 of them ontology pieces | ~20 pieces in 5 groups (§4.4); 7 new |
| Widget setup per widget | **None** for pieces | A Setup and a Look tab for every piece |
| Variables: named, typed, "used by" | None | **Sets**, **choices** and **values**, each saying what reads it |
| Filter output → "using a variable" | Narrows by entity name | A filter column **narrows named sets** |
| Active object · Selected objects | One table → one detail | **Chosen** and **ticked**, from any table, list, map or timeline |
| Events (19 verbs) | Refused (`on`) | A closed set: *choose · show a set · open a drawer · read again* |
| Overlays | None | A **drawer** and a **form**; nothing else floats |
| Button Group → action, defaults bound to variables | One button in a detail; first object filled | **Action buttons**: every parameter takes a source (§4.5) |
| Inline Action · inline edits | — | Later: inline edit through a declared action |
| Save ≠ publish · changelog · revert | Every keep is a version; publish to groups; History | Add a changelog in words from `changes`; keep the rest |
| Check access | Withheld said per piece | **Preview as a group** — the App under that group's row policies |
| Templates: inbox · map · metrics, picked by a person | One shape for all | **Shapes inferred from the ontology**, offered with why |
| Profiler | — | Each set says its read time in the Data tab |

---

## 4 · The design

### 4.1 The laws it is built on

- **a. The ontology is the definition.** A piece names a set. A set names an entity, segment, conditions and links.
  No cockpit holds SQL. This is unchanged from OC-4.
- **b. Wiring by name, never by expression.**
  - This generalises the `follows` the detail already uses.
  - Props stay literal.
  - The catalog gains typed reference props: `set`, `chooses`, `ticks`, `narrows`, `shows`, `from`. Each is a
    string checked against the spec's declared `sets`, `values` and choices, the way `follows` is checked against
    the elements.
  - The library's `on`, `watch` and `$` expressions stay refused.
  - *"A cockpit defines no action of its own"* stays true: a button names a declared action, and the declaration
    owns its risk, criteria and approval. The cockpit cannot loosen them.
- **c. Withheld is said.**
  - A set is compiled for each reader under their row policies.
  - The builder offers as conditions, splits and filters only the properties the author may read.
  - A masked property is refused there, as the door already refuses it.
  - *Preview as* shows the App as a group sees it.
- **d. A model may arrange, never add — and never wire.** A set or a parameter source is part of a piece's
  definition. The "In words" door keeps its current powers.
- **e. Read first, edit behind *Edit*.** The builder *is* the cockpit's Edit mode. A reader sees one bar (the frame
  rework already offered) and the App.
- **f. The reader's own choices stay theirs.** Filter ticks, the chosen row, ticks and the shown set are held in the
  browser per cockpit, as the user decided on 10-10. What the **author** sets — a set's conditions — is the kept
  cockpit.

### 4.2 The words (a glossary proposal — the user's call)

| Use this | For | Don't use |
|---|---|---|
| **Set (on a cockpit)** | A named group of objects that pieces read. It is an entity or one of its segments, narrowed by the author's conditions, by a filter column or by a link from a chosen object, and it may start from another set. It says what reads it. A set kept for everyone is a *segment* | variable, object set, query |
| **Chosen · ticked** | The object a reader clicked in a piece, and the objects they ticked — each named, each read by other pieces | active object, selection, selected objects |
| **Value** | A number, a date or a word the author sets once and sets read, such as *Window: 14 days* | parameter (that is an action's), variable |
| **Drawer · form** | What opens over the page: a drawer beside it, a form in front of it | overlay, modal, popup |
| **Shape** | What a cockpit is for — a queue, an overview, a map, one object's page, a timeline — and so how it is laid out | template (that is a pack's, §glossary), layout |

*Piece* stays the word for what a person places. *Widget*, *module* and *application* stay out of anything a reader
sees: the glossary already rules them out.

### 4.3 The spec, vocabulary v5 (a sketch)

```jsonc
{
  "root": "cockpit",
  "values": { "window": { "kind": "days", "value": 14, "label": "Window" } },
  "sets": {
    "placed":  { "entity": "Order", "where": [{ "path": "created_at", "op": "in_last", "value_from": "window" }] },
    "waiting": { "from": "placed", "segment": "overdue_dispatch" },
    "shipped": { "from": "placed", "where": [{ "path": "shipped_at", "op": "not_null" }] },
    "late":    { "from": "shipped", "segment": "late_dispatch" },
    "lines":   { "entity": "OrderItem", "linked_to": { "choice": "chosen-order", "link": "order_item_to_order" } }
  },
  "elements": {
    "filters":  { "type": "ObjectFilters", "props": { "narrows": ["waiting", "late", "shipped"], "properties": [/* … */] } },
    "fig-wait": { "type": "ObjectFigure",  "props": { "set": "waiting", "agg": "count", "of": "placed", "shows": "shown" } },
    "chart":    { "type": "ObjectChart",   "props": { "set": "waiting", "across": { "path": "created_at", "grain": "day" },
                                                      "measure": { "agg": "count" }, "split": { "path": "placed_by.country", "top": 3 } } },
    "table":    { "type": "ObjectTable",   "props": { "set_from": "shown", "default_set": "waiting", "chooses": "chosen-order",
                                                      "ticks": "ticked-orders", "sort": "created_at" } },
    "detail":   { "type": "ObjectDetail",  "props": { "follows": "chosen-order" } },
    "its-lines":{ "type": "LinkedObjects", "props": { "set": "lines", "columns": ["of_product.name", "sale_price", "of_product.ships_from.name"] } },
    "buttons":  { "type": "ActionButtons", "props": { "buttons": [
      { "action": "open_case", "params": { "order": { "from": "chosen-order" }, "assignee": { "ask": true } },
        "ask": "form", "blocked": "disable", "after": [{ "read": "waiting" }, { "open": "case-opened" }] },
      { "action": "flag_for_review", "params": { "order": { "from": "chosen-order" }, "reason": { "ask": true } } } ] } }
  }
}
```

**The rules that come with it**, in `rules.ts` and on the server:

- Every reference resolves.
- Kinds match. An *order* parameter takes a chosen order, a ticked order (once per object) or an order set (asks
  first); never a customer.
- Sets form no cycle, and a filter's counts never narrow by its own ticks — as today.
- Every set compiles through the object door when kept. `pieces.py` already probes each piece this way.
- A v4 spec upgrades with **no change to what a reader sees**. Each `entity` piece reads an implicit set *All <entity>*,
  narrowed by the root filter column, and a test holds the two byte-identical.

**One addition the door needs:** a relative condition (`in_last` N days), resolved at read time.

### 4.4 The builder

Screens 2–5 of the mockup.

**Three panes inside the Cockpit tab; the rail stays.**

- **Left — Layout · Data · Actions.**
  - *Layout* is the tree: page → sections → pieces, with drawers below. Drag to move, double-click to rename.
  - *Data* lists the sets, the choices and the values. Each shows what it holds now and what reads it, such as
    *Waiting · 1,375 · read by 4*.
  - *Actions* lists the actions declared on what the cockpit reads, where each is placed, and *Declare an action*,
    which opens the existing `ActionDesigner`.
- **Middle — the cockpit as its reader sees it**, live.
  - The selected piece is outlined. Above it, a toolbar: move, add above or below, split, duplicate, take off.
  - Selecting a set dashes every piece that reads it.
- **Right — Setup and Look** for the selection.
  - Every field shows the value it reads now, the way Workshop's "Current value" does.
  - The chart's Setup has these fields:
    - *Reads*;
    - *Draw as* (bars, line, area);
    - *Across* (a date property by hour to year, or a category);
    - *Measure* (count, or the sum, average, minimum or maximum of a property, with *+ Add a measure*);
    - *Split by* (top N, the rest folded into Other);
    - *Split shown* (stacked, side by side, share);
    - *Behind it* (another set as the grey line);
    - *A click on a bar* (does nothing, narrows the set, or chooses).

  Every option is one the object door already compiles. The panel reuses `VizEditorPanel`'s model-driven sections.

**The bar.** It shows: *Editing · saved 21:42 · version 7* · undo · redo · *11 pieces read cleanly · 1 to fix* ·
*Preview as Everyone ▾* · History · Publish as an App · Done.

**The picker** groups pieces by what they are for:

| Group | Pieces |
|---|---|
| Show objects | objects table · **object list** · object detail · **linked objects** · **map** · **timeline** |
| Measure | figure · chart · process board · card · finding |
| Filter | filter column · **search** · **choose one** · period |
| Act | action buttons |
| Words & media | note · image |

Bold is new — seven pieces.

### 4.5 Actions on the page

Screens 4 and 6. **Each parameter takes one source:**

| Source | Runs |
|---|---|
| The **chosen** object | once |
| The **ticked** objects | once per object, each through the executor, at most 50 |
| A **set** | asks first, says the count |
| **Asked in the form** | the reader picks it |
| **A fixed value** | the same one every time |

- **Only sources that hold the parameter's entity are offered.** The user's screenshot shows the same rule.
- **Value parameters get typed inputs** from the declaration: a number, a date, or a list of values read from the
  data. The ActionDesigner's typed questions already describe them.

**For each button the author picks:**

- *Ask first*: show the form, or run when complete.
- *When it cannot run*: disabled with the reason, or hidden.
- *After it runs*: read named sets again, open a drawer, choose the object it made.

**The declaration still owns** who may press it, its criteria, its risk and its approval. A high-risk action on 20
ticked orders is 20 proposals in the Actions inbox, never one silent batch.

**Workshop's two limits are fixed, not copied.** A failed run says why on the button's row. *After it runs* waits for
the reads it names before it opens a drawer.

### 4.6 Shapes: the starter reads the ontology

Screens 1 and 7.

| Shape | The ontology says it fits when | theLook |
|---|---|---|
| **Queue** | a status or a process with a promise (an overdue segment) **and** actions on the entity | Order — 1,375 placed in the last 14 days are past the 2-day dispatch promise; 2 actions · Case — held by the platform, 2 actions |
| **Map** | coordinates, on the entity or one link away | Distribution centre — 10 places; Customer |
| **One object** | many links into it and a name to choose by | Customer — orders, lines, events |
| **Overview** | a date, measures and categories of modest size, and no actions | Order line (revenue), Product, Event |
| **Timeline** | two moments on each object | Inventory item — in stock → sold |
| **Process** | a declared process (exists today: *For a process*) | Order fulfilment |

**How the starter offers shapes:**

- It offers one to three shapes, the one that fits first, with one sentence of why.
- The author picks; every piece can be changed after.
- **Queue**, the first shape built: three figures that switch the list, a filter column, a chart of what waits, the
  list oldest first, and the chosen object with its lines and its actions.
- **Later**: the "three Apps on one data model" seen in §2.7 — a lead's overview, an operator's queue, and a manager's
  outcomes read from the Record's decisions — offered together for one process.

**What the receipt showed:** theLook's 24,872 overdue orders reach back to 2019, because the data keeps orders
"Processing" for years. An unwindowed queue would open on 2019. That is why a set takes the author's conditions, and
why the starter asks *which orders wait*.

### 4.7 Room to build: the screen it is drawn for

The user, on Workshop's editor: *"consider the resolution at which they operate… that makes their entire UI look
enormous and gives them enough space to accommodate all the components."*

**Measured on the user's screenshots (frames ~2000 × 1120):**

| Part of the editor | Width |
|---|---|
| Global icon rail | ~52 px |
| Editor tab column | ~52 px |
| Left panel | ~220 px |
| Canvas, showing the page at 100% | **~1,290 px** |
| Right panel | ~365 px |
| One header | ~64 px tall |

Their room comes from four things: a wide screen, rails of icons only while building, narrow panels, and one header.
It does not come from smaller type, which sits at about 12–13 px, as ours does.

**The builder is drawn for 1920 × 1080 and fits itself below it** (screen 2 at both sizes):

| | 1920 × 1080 | 1512 × 900 (a 14-inch laptop) |
|---|---|---|
| Rail | 48 px — its own collapsed state | 48 px |
| Layout · canvas · setup | 232 · **1,336** · 304 | 232 · 928 · 304 |
| The cockpit on the canvas | **100%** | fits at **81%**, and says so; 99% with the layout panel folded |

The rail folds using the state it already has (`data-nav="collapsed"`, `--sidebar-collapsed: 48px`). Edit mode sets it
for its own duration and **does not write the person's stored preference**, so *Done* gives the rail back as it was.
The header's theme toggle once wrote a person's stored theme; this must not repeat that.

The cockpit strip folds into the name picker while editing, so the canvas starts as high as Workshop's. The reader's
view keeps the rail as the person left it. At 1920 its sections can use the fourth column the grid already allows.

### 4.8 What reading costs

- A set is one compiled read per reader per change, shared by every piece that reads it.
- Only visible pieces read.
- The Data tab says each set's read time.
- The 15 reads behind the mockup took 0.8–7.1 s each, through the live door.

---

### 4.9 Sizes, one grade at a time (the user's refinement of call 4)

Today a piece takes one of six sizes: 1 to 3 columns of a section that draws at most 4, by 1 or 2 rows. A step is
therefore a quarter or a third of the width, or a doubling of the height. The user: *"they become either too large or
small."*

**The grid.**

- A section that has been resized has **twelve columns** and **rows of 40 px**.
- A piece takes a width of 1 to 12 columns and a height in rows.
- The spec says grid units, never pixels.

**One grade at a time.** Every way of resizing moves one column or one row:

| Way | How |
|---|---|
| Drag | The right edge (width), the bottom edge (height) or the corner (both). It snaps grade by grade, says the size as it moves ("8 × 6"), and lands on release |
| Buttons | − and + for width and for height in the toolbar of the selected piece |
| Keys | Alt+← → for width, Alt+↑ ↓ for height |

**A minimum and a maximum per kind**, so that nothing becomes too small to read or too large for its content:

| Kind | Smallest | Largest |
|---|---|---|
| Figure | 2 × 2 | 6 × 4 |
| Chart, process board | 3 × 4 | 12 × 14 |
| Objects table | 4 × 4 | 12 × 20 |
| Object detail, note, image | 2 × 3 | 12 × 16 |

**Each piece fills its box:**

- a chart draws at the box's height;
- a table shows as many rows as the height holds — one grade, one more row;
- a figure keeps its value centred.

**Saving.** A burst of steps is kept as one version, about a second after the last.

**Old cockpits.** A v4 section keeps its six-name sizes and draws exactly as it did, until a person resizes something
in it. Then the section is converted to the grid, each piece keeping the room it had, rounded to the nearest grade.

## 5 · Arc AP — the cockpit as an App builder (proposed phases)

Each phase:

- sits behind its own flag, off by default and byte-identical when off;
- carries a receipt on theLook, shown on the user's own UI;
- has a falsifier.

| # | Builds | Receipt on theLook | Falsifier |
|---|---|---|---|
| **AP-1** | **Sizes one grade at a time** (§4.9), **Edit mode** (the three panes, the tree, the toolbar) and **Setup for every existing piece**: table columns, sort and segment; figure aggregate, property and format; chart measure, grain and split; filter column properties; detail; buttons. Also the reading-mode one bar (the frame rework already offered) | Change the Order cockpit's chart to split by status and its table's columns, with no spec written by hand | Of cockpits started from an object, under 1 in 5 edited within 2 weeks → the Setup is not where people look |
| **AP-2** | **Sets, choices and values** (spec v5): named sets built on each other, chosen and ticked, a filter column narrowing named sets, a figure showing a set, linked objects through the chosen object; the Data tab with live counts; the v4 upgrade with no visible change | The dispatch desk of the mockup built by hand, numbers equal to the door's | A v4 cockpit renders differently after the upgrade → stop |
| **AP-3** | **Actions on the page**: parameter sources, typed inputs, form or run, disabled with the reason, ticked runs (at most 50), after-run reads and a drawer | Open a case on one order from the desk — a write on the live platform, run only with the user's OK at the time | A run that reached the executor without its criteria → stop |
| **AP-4** | **New pieces and overlays**: object list, linked objects, map, timeline, search, choose one; drawer and form; rows, columns and tabs inside a section. Counts for platform-owned entities (a case queue's figures) | Distribution centres as a map; a case queue | — |
| **AP-5** | **Shapes in the starter**: signals → shapes, offered with why | The 7 theLook entities get ≥ 4 different shapes; none gets a lone figure | A started cockpit read on ≥ 3 days in 2 weeks no more often than today's (the existing `ontology.object_cockpits` falsifier, read per shape) |
| **AP-6** | **Building safely**: preview as a group, a changelog in words per version, the checks chip, read times per set; saved views per reader later | Preview the desk as a group with a row policy; see the rows it withholds said | — |

**The order recommended:**

1. AP-1 first. It is the smallest change, no wiring changes, and the user sees "nothing is editable" answered on their
   own cockpit.
2. AP-2 and AP-3 together, as the loop the user showed.
3. Then AP-5, so that cockpits stop looking alike.
4. AP-4 and AP-6 follow.

The five defects in §1.6 ride AP-1 where they touch it (1, 2 and 5). Defect 3 is its own task. Defect 4 is one line
in the Cockpit tab.

---

## 6 · The user's calls

| # | Question | Recommended |
|---|---|---|
| 1 | Adopt the direction — Edit mode becomes the builder, and the starter infers the shape — as **Arc AP** in `ROADMAP.md` | Yes |
| 2 | Wiring **by name**: typed reference props, checked like `follows`. The alternative is opening the library's own `$` expressions and `on` | By name — keeps *a prop is written, never computed* |
| 3 | The words of §4.2: **set · chosen · ticked · value · drawer · form · shape** | These |
| 4 | Sizes stay **spans, never pixels**. Workshop allows absolute widths; this adds rows, columns and tabs inside a section | Keep spans — **refined by the user: one grade at a time (§4.9)** |
| 5 | **Ticked runs** — one press runs a declared action on each ticked object, each through the executor, high risk as one proposal each | Yes, at most 50 |
| 6 | **Order** of the first build | AP-1 now (with the frame rework); then AP-2 + AP-3 as one |
| 7 | **The branch.** This branch holds 7 unpushed commits the user is verifying. AP-1 would build on it after that check, as one branch | After the user's check |
| 8 | **The room to build** (§4.7). Drawn for 1920 × 1080. Edit mode folds the rail to icons (its own state, never written to the person's preference) and the strip into the name. The canvas shows the cockpit at 100%, or fits it and says the zoom | Yes |

---

## 7 · Not adopted, and why

| Item | Why not |
|---|---|
| Generated React apps, hosted (Pilot) | §6 item 50(d): nothing hosted runs code |
| Expressions in props, `on`, `watch` | The rules' own reasons stand; §4.1b gives the wiring without them |
| Two y-axes | The dataviz law |
| Absolute pixel widths | The glossary's *Size*; the approved theme's grid |
| A model wiring sets or parameters | A model may arrange and never adds, §glossary *Process board · …* |
| Loop layouts, scenarios, custom widgets, AIP widgets, mobile | Not needed for the loop; each needs its own case |

## 8 · Sources

**Palantir docs**, read 2026-10-10, under `https://www.palantir.com/docs/foundry/`:

- **Workshop concepts**: `workshop/overview`, `workshop/getting-started`, `workshop/concepts-layouts`,
  `workshop/concepts-widgets`, `workshop/concepts-variables`, `workshop/concepts-events`.
- **Workshop actions and widgets**: `workshop/actions-use`, `workshop/widgets-button-group`,
  `workshop/widgets-inline-action-form`, `workshop/widgets-filter-list`, `workshop/widgets-object-table`,
  `workshop/widgets-metric-card`.
- **Workshop features**: `workshop/variable-backed-layouts`, `workshop/module-interface`, `workshop/state-saving`,
  `workshop/routing`, `workshop/loop-layouts`, `workshop/auto-refresh`, `workshop/kiosk-mode`.
- **Workshop design**: `workshop/example-applications`, `workshop/application-design-best-practices`,
  `workshop/application-design-components`, `workshop/application-design-faqs`.
- **Action types**: `action-types/overview`, `action-types/permissions`, `action-types/test-run`.
- **Object edits**: `object-edits/how-edits-applied`, `object-edits/user-edit-history`.
- **Other**: `object-views/overview`, `automate/effect-actions`, `pilot/overview`, `use-case-patterns`.

**Other sources:**

- the Build with AIP catalogue (`build.palantir.com`);
- the user's 22 screenshots, 2026-10-10;
- in this repo: `web/lib/cockpit/{catalog,rules,start,objectView}.ts`, `web/components/cockpit/*`,
  `aughor/cockpit/{from_object,pieces,versions}.py`, `aughor/semantic/object_query.py`,
  `aughor/ontology/models.py` (`KineticAction`), `aughor/actions/executor.py`,
  `web/components/ontology/ActionDesigner.tsx`.

**Every theLook number** here and on the mockup was read on 2026-10-10 through `POST /objects/query` and
`/objects/list` on the live API. The answers are kept beside the mockup's generator.
