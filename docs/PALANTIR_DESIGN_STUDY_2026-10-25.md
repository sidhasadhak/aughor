# Palantir's look, measured — and how far Aughor stands from it (2026-10-25)

The user, 2026-10-25: *"Let's research how we can make Aughor look more like Palantir."* This study measures what
"Palantir" looks like from primary sources, measures what Aughor looks like today on the live instance, puts the two
side by side with one thing changed at a time, and names the calls the user has to make. Nothing is built.

The feature side of Palantir is a different study: `docs/PALANTIR_FOUNDRY_STUDY_2026-07-22.md` (the platform),
`docs/PALANTIR_DOCS_CATALOGUE_2026-10-24.md` (the docs and API inventory), ROADMAP §3.57 (the cockpit as a Workshop)
and §3.58–3.60 (Arcs ED/TC/FA). This one is about the *look*: colour, type, density, chrome, layout and status language.

## 0. The verdict, in six lines

1. "Palantir" is two looks. The **product** (Foundry, Workshop, Ontology Manager, AIP) is built on Blueprint: light by
   default, cool navy-tinted greys, Source Sans at 14px, 30px controls, 4px corners, a 1px divider on everything, one
   blue. The **brand** (palantir.com) is black-and-white, Alliance typeface, 10px uppercase letter-spaced eyebrows and
   photography. The product look is the one worth taking; the brand look is marketing and the face is licensed.
2. Aughor is already Foundry-*shaped* where it counts: the Ontology tab is Ontology Manager's object-type page
   (identity, figures, Overview · Properties · Links · Actions · Sources · History); the cockpit-from-object mockup is a
   Workshop module (filters left, metric cards, object table, detail panel); the rail collapses to Foundry's icon rail;
   the graph draws straight edges as Ontology Manager does.
3. The distance is mostly **surface**, and most of it is already a knob: corners (ours 9–12px, theirs 4px), the tint of
   the greys (neutral charcoal vs cool slate), the accent (jade on the live instance today, blue there), borders (none
   on a dark card here, 1px everywhere there), scale (Radix's own vs Blueprint's 30px), type (Inter vs Source Sans).
4. Four of those six are the Look panel's own knobs (accent · grey · corners · scaling). A fifth is a token the dark
   skin already declares (`--card-edge`). The sixth is a font import. A **"Foundry" preset** is a day's work and moves
   nothing for anyone who does not choose it.
5. The structural things worth taking are Workshop's own published rules (§2.3: at most five primary actions, at most
   ten visible components, 30–40 % whitespace, filters left, the header pinned, one shaded region per page), Ontology
   Manager's **Dependents** and **Usage** sections on an entity, and Foundry's status language (a bordered, tinted tag
   for a state — Resolved, Escalated, Beta).
6. What stays refused: Blueprint itself (2026-10-12, `docs/COMPONENT_LIBRARY_STUDY_2026-10-12.md`), replacing the rail
   with an app portal ([ROADMAP §4.10], the rail stays), the marketing black, and Alliance (a licensed face).

## 1. What was measured, and where

| Source | What it gave | Kind |
|---|---|---|
| `@blueprintjs/colors@5` `lib/esm/colors.js` (unpkg) | every Blueprint hex | primary, exact |
| `palantir/blueprint` `packages/core/src/common/_variables.scss` and `_color-aliases.scss` (develop) | grid, type, control heights, radius, shadows, dividers, the semantic aliases | primary, exact |
| `packages/core/src/components/html-table/_html-table.scss` | row heights, striping, hover | primary, exact |
| palantir.com/docs → Workshop → *Application design best practices* | Palantir's own numbers for a screen | primary |
| palantir.com/docs → *Orientation and navigation*, Ontology Manager *Overview*, Object Views *Overview*, Workshop *Overview* | the chrome and the screens, 9 screenshots read | primary |
| palantir.com and palantir.com/docs, computed styles read in the browser pane | the brand's type and colours | measured |
| localhost:3000 (the user's :3000, main `0a5fff50`) on theLook, computed styles and attributes read | Aughor today | measured |
| The same page with one attribute changed at a time, screenshot each time | the side-by-sides (§5) | measured |

Two Workshop pages the design page links to ("Component-specific best practices", "Module settings") answered 404 on
2026-10-25; their guidance is not in this study. Foundry's own CSS was not read: it sits behind a login, and the user
asked for the public site only (2026-10-24).

## 2. Palantir in numbers

### 2.1 Blueprint v5 — the tokens the product is drawn with

**Greys** (cool: every step carries a little blue — DARK_GRAY1 `#1C2127` is hue 213°, not neutral):

| Role | Dark skin | Light skin |
|---|---|---|
| Page (`$pt-app-background-color`) | DARK_GRAY1 `#1C2127` | LIGHT_GRAY5 `#F6F7F9` |
| Secondary surface | BLACK `#111418` / DARK_GRAY1 | WHITE |
| Elevated (card, popover) | DARK_GRAY2 `#252A31` / DARK_GRAY3 `#2F343C` | LIGHT_GRAY4 `#EDEFF2` |
| Text | LIGHT_GRAY5 `#F6F7F9` | DARK_GRAY1 `#1C2127` |
| Muted text, icons | GRAY4 `#ABB3BF` | GRAY1 `#5F6B7C` |
| Divider | `rgba(255,255,255,.2)` (muted `.1`) | `rgba(17,20,24,.15)` (muted `.1`) |
| Link | BLUE5 `#8ABBFF` | BLUE2 `#215DB0` |
| Code background | `rgba(17,20,24,.3)` | `rgba(255,255,255,.7)` |

**Intent** — exactly four, and every control, tag, callout and icon speaks them:
primary BLUE3 `#2D72D2` · success GREEN3 `#238551` · warning ORANGE3 `#C87619` · danger RED3 `#CD4246`. Each hue has
five steps (1 darkest … 5 lightest); the dark skin's input focus uses step 4 (`#4C90F0`, `#32A467`, `#EC9A3C`,
`#E76A6E`). Eleven more hues exist (vermilion, rose, violet, indigo, cerulean, turquoise, forest, lime, gold, sepia)
for data, never for state.

**Type and grid:** 14px base (`$pt-font-size`), 12px small, 16px large; line height **1.28581** (18px at 14 — tight);
the family is the system stack in Blueprint, and **Source Sans Pro in Foundry** (the Workshop design page names it as
"the default Foundry font"). Grid 10px, spacing unit 4px.

**Sizes:** control and input **30px** (small 24, smaller 20, large 40); navbar **50px**; icons 16px and 20px; table rows
**40px** (`$pt-spacing × 10`) and **30px** compact; headers 600 weight; striping `rgba(gray, .15)`, hover `.3`.

**Corners and edges:** radius **4px** (`$pt-border-radius`). An edge is a 1px inset shadow (`0 0 0 1px rgba(black,.15)`,
dark `rgba(white,.2)`) on *every* elevation — a Blueprint card is always boxed. Elevation adds a drop shadow in four
steps; the dark skin adds a half-pixel inner highlight. Transitions 100ms.

### 2.2 Foundry's chrome

- A **collapsible left sidebar** (`⌘O`), dark on every skin (the screenshots show `#1C2127`-class navy with white
  icons), in five groups: Home · Search (`⌘J`) · Notifications · What's New / Recent · Files · Applications / promoted
  applications / favourite files / AIP Assist (`⌘⇧U`) · Support · Account. Collapsed it is an **icon rail** about 44px
  wide; expanded it carries labels. There is no top bar of the platform's own; each application draws its own header.
- **Content is light by default.** A Workshop module can be switched to dark per module (a setting, "non-critical").
  Two community threads ask for a platform-wide dark mode, which says the platform has none.
- **Home** is a tile page: a banner, then "Applications for Data Ops / Analytics / Operations", each app a bordered
  white tile with an icon, a name and a one-line purpose. The **Applications portal** is a dialog: a category list on
  the left (All apps 75 · Platform 40 · Promoted 35), a search, tiles on the right, "Promote app" at the bottom.

### 2.3 Workshop's own rules for a screen (palantir.com/docs, *Application design best practices*)

| Rule | Number |
|---|---|
| Primary actions in top-level navigation | **at most 5** |
| Visible components in one view (buttons, panels, widgets) | **at most 10** |
| Whitespace | **30–40 %** of the screen |
| Reading pattern | F-shaped: scan across the top, then down the left |
| Layouts | grid (left→right), column (navigation at the top of each panel), **row + column: filters anchored left, content flows right, Metric Cards for the key figures** |
| Headers | one page header (largest text) · section headers (second largest) · a one-line description under a section only when needed |
| Padding | **Compact** in most cases; a reliable custom is 80 % with **16px** spacing |
| Grouping | containers between groups, dividers within a group, padding between groups |
| Elevation | a drop shadow on the one section that matters; inner shadow for the lesser; **shaded padding once per page** |
| Backgrounds | lighter = important content; darker = filters and collapsible panels |
| Scrolling | no horizontal scroll (fit columns); navigation and tabs in the pinned primary header; touch targets **≥ 30px** |
| Overlays | temporary and secondary tasks only; never for analysis that needs two layers at once |
| Type | Source Sans Pro default; system fonts allowed; custom faces only if installed on the viewer's machine |
| Validation | squint at it; follow the real workflow; show an element only where someone acts on it |

### 2.4 The screens, read

- **Sample Claims Dashboard** (Workshop): icon rail · a white module header with the app's icon and name · a *Group*
  column of four metric cards (Claims 329/11/52/23 as four small figures with labels, a muted "Group ID" line) · an
  object table (checkbox · title in blue · a bordered status tag · date · owner · comment), ~30px rows, 1px rules ·
  a detail panel on the right: title, *Details* with label/value pairs, *Comments* with "+ Add", and two full-width
  action buttons (Escalate, Resolve in green) pinned at the panel's foot.
- **Flight Alert Inbox** (Workshop): *Filters* column left — Open 230 / Escalated 1 / Resolved 69 as a choose-one,
  then Urgency and Alert type as checkbox · label · count · **blue bar**, a date histogram, "Add filter" · a table with
  intent tags (Low green · Medium orange · High red, bordered) · an *Object View* panel with De-escalate / Escalate
  Alert at its top right, tabs Overview · Properties · Alert Details, a *Properties* label/value list, a *Links* list of
  linked objects in blue.
- **Row + column template**: a header strip (app icon · title · tabs · a search on the right) · a filters column with
  Current/Past segmented, checkbox lists with counts and bars · four metric cards in one row ("123 · label") · one
  bordered table. White cards with a 1px edge and a faint shadow on `#F6F7F9`.
- **Ontology Manager, object type overview**: ① identity (name, type, actions ▾, "Open in" ▾; a two-column
  label/value grid: plural, description, aliases, point of contact, contributors, datasource; right column: status,
  visibility, index status, edits, RID) · ② Properties (icon · name · tag; "Edit") · ③ Action types · ④ **Link types
  as a graph** — nodes are pill boxes, edges straight · ⑤ **Dependents** (Workshop 6, Function 1, Graph template 1,
  Quiver dashboard 1, Automation 1 … each listed) · ⑥ Data (datasource rows with "synced · 7 weeks ago") · ⑦ **Usage**
  (a bar chart by month). Every section a white card with a 1px edge on a light page.
- **Object View** (standard): a top strip (object name, Full / Panel, "Switch to configured view"), an image or
  prominent property, then figures, *Properties*, *Linked objects*. The **panel** form factor is the same page cut to
  the properties that matter — the shape of our object drawer.

### 2.5 The brand (palantir.com)

Body `#1E2124` on white, or white on black video; **Alliance No.1** for text, **Alliance No.2** for display; the
eyebrow is **10px, uppercase, letter-spacing 0.5px, `#B9B9B9`**; buttons `#1E1F2B`; nav links 34px light. The docs site
uses the same family at 18px/25px. Alliance is a Degarism retail face, not free; nothing of Foundry's product is set in
it.

## 3. Aughor in numbers (measured live, 2026-10-25, the user's :3000 on theLook)

- **Type:** Inter 14px / 21px (line height 1.5 — Blueprint is 1.29); figures tabular Inter; JetBrains Mono for ids.
- **Skin:** dark, neutral charcoal (page `gray-1`, display-p3 .067 ≈ `#111`, card `gray-2` ≈ `#191919`), no border on a
  dark card (`--card-edge: transparent` by design, CLARITY §3), 1px row rules at `gray-5`.
- **The live look is the user's own:** `data-accent-color=jade · data-gray-color=sand · data-radius=large ·
  data-scaling=100%` — not the 2026-10-06 default (indigo · gray · large · 100 %). The green active row in every
  screenshot is jade. The look is per person (`aughor/db/user_prefs.py`), so this is a fact, not a defect.
- **Corners:** large = Radix factor 1.5 → `--radius-2` 6px, `--radius-3` 9px, `--radius-4` 12px (cards). Blueprint: 4.
- **Rail:** 248px with labels in four groups; collapses to an icon rail (`data-nav=collapsed`,
  `--sidebar-collapsed`). Buttons measured 25px (size 1). Rows: Radix's own (36px by the 10-06 decision).
- **Chrome:** a 36px top strip (wordmark · connection · LIVE sparkline · ⌘K · dark/light · avatar); each workspace a
  tab strip (Briefing · Dashboards · Profile · Ontology · Graph · Evidence · Memory · Actions · Org · Brain map), no
  page titles ([no-page-title-bars]).
- **Status language:** chips without borders (`6 to approve` amber fill, `✓ key`, `● 1 proposed` violet), figures as
  label / value / one muted line; filter rows value · count · 6px bar (cockpit-from-object).

## 4. The gap, dimension by dimension

| Dimension | Palantir (product) | Aughor today | Distance | How it closes |
|---|---|---|---|---|
| Skin by default | light; dark per module | dark; light available | far | a *choice*, not a gap — see call 4 |
| Grey | cool navy (`#1C2127`, hue 213°) | neutral charcoal | near | Look panel: grey **slate** |
| Accent | one blue `#2D72D2` | jade today; indigo default | near | Look panel: accent **blue** |
| Corners | 4px | 9–12px | near | Look panel: corners **small** (4.5/6px) or **none** |
| Edges | 1px on every card, both skins | none on a dark card | near | `--card-edge: var(--gray-6)` under the preset |
| Density | 14px/1.29; 30px controls; 30–40px rows | 14px/1.5; 25px buttons; 36px rows | middle | scaling **95 %** gets most of it; row height is Radix's, revisit after a week |
| Type | Source Sans (Foundry), system (Blueprint) | Inter | middle | Source Sans 3 (OFL) self-hosted via next/font, chosen like a knob |
| Rail | dark icon rail, five groups | labelled rail, collapses to icons | near | nothing; dark rail on light content is a new skin (call 4) |
| Home | app tiles by purpose | the desk (one thing to know · needs you · questions) | far, on purpose | keep ours; Palantir's home is navigation, ours is the morning |
| Object page | identity · properties · links graph · dependents · data · usage | identity · figures · Overview · Properties · Links · Actions · Sources · History | near | add **Dependents** and **Usage** (needs usage attribution) |
| Module layout | filters left · metric cards · table · detail panel | the same (cockpit-from-object, AP-1…8) | none | — |
| Status tags | bordered, tinted, four intents | filled chips, five meanings (CLARITY §4) | near | a bordered variant where a *state* stands (Resolved · Escalated · Beta) |
| Rules for a screen | ≤5 actions · ≤10 components · 30–40 % air · header pinned | CLARITY §1–3 (the four-part test, figures → needs you → picture → list) | agree | write Workshop's numbers into CLARITY §3 |
| Icons | Blueprint icons 16/20 | Tabler 16 | none visible | — |
| Graph edges | straight, pill nodes | straight (decided 10-10) | none | — |
| Brand | Alliance, black, 10px eyebrows | Inter, charcoal, 11px eyebrows | n/a | not the product; leave |

## 5. The side-by-sides (`design-mockups/palantir-inspired/aughor-foundry-knobs-2026-10-25.png`)

Six captures of the live Ontology tab (Customer Order on theLook), one thing changed each step, by setting the Theme's
attributes on `<html>` in the browser pane and reloading at the end (nothing was stored; the user's look is intact).

| # | Changed | What it did |
|---|---|---|
| 1 | — | the user's own look: jade · sand · large · 100 % |
| 2 | corners → small | chips and the figure cards square off; at 800px it is the quietest step |
| 3 | + grey → slate, accent → blue | **the largest single step toward Foundry** — the selected row, the bars and the tab underline read as Blueprint blue on a cool grey at once |
| 4 | + scaling 95 %, card edges on | one more row fits (Order Line appears under PARTS); the figure cards and the Needs-you box gain a visible edge |
| 5 | + Source Sans 3 | more words per line at the same size: the entity description no longer truncates ("Contains 125,303 orders." is read), the tab strip fits "Brain map" without scrolling |
| 6 | + light skin | closest to a Workshop module as published; the rail stays light, which Foundry's is not |

Recipe to repeat (debug only, in the browser pane's JS):
`document.documentElement.setAttribute('data-gray-color','slate')` · `data-accent-color=blue` · `data-radius=small` ·
`data-scaling=95%`; a `<style>` with `:root{--card-edge:var(--gray-6)}`; a Google Fonts link for *Source Sans 3* and
`:root{--font-inter:"Source Sans 3"}`; the light skin by swapping the `dark` class and `data-theme`.

## 6. What to take, and what not — against the standing decisions

**Take**
- A **Foundry look preset**: blue · slate · small · 95 % · edges on · Source Sans 3 — one button in the Look panel, each
  knob still its own afterwards. Per person; the default stays what was decided on 2026-10-06 until the user says
  otherwise after using it.
- Workshop's **numbers into CLARITY §3** — they agree with the four-part test and make it countable: at most five
  primary actions in a screen's top row, at most ten visible components, the header and tabs pinned, filters left, one
  shaded region per page.
- Ontology Manager's **Dependents** (every dashboard, monitor, question and automation that uses an entity) and
  **Usage** (reads by month) as two sections of the entity's Overview — the July study's gap 9 ("usage attribution
  lives on the definition page"), which also answers "can I remove this?" honestly.
- A **bordered state tag** (Blueprint's minimal tag) wherever a row has a state: Resolved · Escalated · Beta · Draft;
  CLARITY's five colour meanings unchanged.
- The **panel object view** idea is already ours (the object drawer); keep the full view and the panel view the same
  page cut down, as Foundry does.

**Leave**
- Blueprint (refused 2026-10-12: four maintainers, React 19 loop bug, a second reset beside Radix).
- An app-tile Home and an Applications portal: the rail stays ([rail-stays-new-pages-go-inside]); the desk is ours.
- A platform-wide switch of the default skin to light, or of the greys to slate: both were decided on real
  side-by-sides (10-05 charcoal, 10-06 indigo/gray); a preset leaves them as decided.
- Alliance and the marketing black: a licensed face and a look for a website, not an instrument.
- Blueprint's 1.29 line height on prose: it is right for a 30px row and wrong for a Briefing paragraph; take it only
  where Source Sans is chosen and only on controls and rows.

## 7. Proposed steps (Arc PL — the Foundry look), each a half-day to a day, flags where a default moves

- **PL-1 · the preset.** `LookPanel.tsx` gets a *Presets* row (Aughor · Foundry); choosing one writes the four knobs
  through the existing `chooseLook`. No backend change: the values are already in `ALLOWED_KEYS`. Test: the preset's
  four values equal the four knobs after a click; nothing else in the store moves.
- **PL-2 · edges.** A fifth knob `edges: off | on` (default off), carried like the other four (`lib/lookValues.ts`,
  `themeBoot.ts`, `user_prefs.ALLOWED_KEYS`, `test_user_prefs_look.py`); on → `--card-edge: var(--gray-6)` in dark too.
  The Foundry preset turns it on.
- **PL-3 · type.** A sixth knob `type: inter | source-sans`; Source Sans 3 self-hosted by next/font (OFL); the body
  family follows the knob; figures stay tabular. The Foundry preset chooses it. Check the chart SSR bundle gate is not
  touched (`components/charts/*` unchanged).
- **PL-4 · state tags.** `ui/badge.tsx` gains `variant="outline"` (Radix Badge has it); the places where a row carries a
  state use it. Vocabulary ratchet: no new words.
- **PL-5 · CLARITY §3 numbers.** The Workshop table of §2.3 above, as a "Count it" block, with a test only where a
  count can be held (the flag cards already have one).
- **PL-6 · Dependents + Usage on an entity.** Needs the use count per entity (dashboards, monitors, questions,
  automations already name their entities; reads by month come from the request log). Behind a flag
  (`ontology.entity_usage`), byte-identical off.
- **PL-7 · the Foundry chrome** (dark icon rail on light content): **one screenshot first**, built by hand on the
  live page, shown, and only then a skin — a navigation-adjacent change under the 10-05 rule.

Order: PL-1 → PL-2 → PL-3 (one PR, the preset usable) · PL-4 + PL-5 (one PR) · PL-6 · PL-7 at the user's word.

## 8. The user's calls

**Taken 2026-10-25** (the user: *"Product look, preset with all six, build the chrome screenshot"*): calls 1, 2 and
3 as recommended, call 4 yes; calls 5 and 6 stand as recommended (scaling only; Dependents and Usage after). Built
the same day — PL-1 to PL-3 as one change: the preset is named **Workbench** in the panel, because the vocabulary
ratchet retires a product's name in code and copy and "Slate" is already the grey's own name.

1. **Which Palantir?** The product look (Foundry/Workshop) or the brand (palantir.com)? — *Recommended: the product.*
2. **Preset or default?** A Foundry preset in the Look panel, per person, or move the platform's default? —
   *Recommended: the preset first; a default moves only after a week of real use, on a side-by-side as before.*
3. **What the preset holds:** blue · slate · small · 95 % · edges · Source Sans 3 — all six, or the four existing knobs
   only? — *Recommended: all six; PL-2 and PL-3 are small and each stays a knob of its own.*
4. **Foundry's chrome** (dark rail, light content) — build the screenshot? — *Recommended: yes, one screenshot, no code
   until it is seen.*
5. **Density beyond scaling** (Blueprint's 30px rows) — leave to Radix's own, or add a compact row size? —
   *Recommended: scaling only now; revisit with the preset in use.*
6. **PL-6 Dependents + Usage** — after the preset, or now? — *Recommended: after; it is the only step that needs new
   data.*

## 9. Sources

- Blueprint colours: https://unpkg.com/@blueprintjs/colors@5/lib/esm/colors.js
- Blueprint variables and aliases: https://github.com/palantir/blueprint/tree/develop/packages/core/src/common
  (`_variables.scss`, `_color-aliases.scss`), tables in `packages/core/src/components/html-table/_html-table.scss`
- Workshop, Application design best practices: https://www.palantir.com/docs/foundry/workshop/application-design-best-practices/
- Foundry, Orientation and navigation: https://palantir.com/docs/foundry/getting-started/orientation-and-nav/
- Ontology Manager overview: https://www.palantir.com/docs/foundry/ontology-manager/overview/
- Object Views overview: https://www.palantir.com/docs/foundry/object-views/overview/
- Workshop overview: https://www.palantir.com/docs/foundry/workshop/overview/
- Carbon workspaces (home pages, menu bar): https://www.palantir.com/docs/foundry/carbon/workspaces-overview/
- Dark mode is per module: https://palantir.com/docs/foundry/learning-application-appdev-05/28 ·
  https://community.palantir.com/t/dark-mode-across-the-whole-platform/5421
- The screenshots read are the docs' own images under `https://www.palantir.com/docs/resources/foundry/…`
  (`workshop/sample-claims-dashboard.png`, `workshop/object-apps-workshop-module.png`,
  `workshop/example-dashboard-combo-rows.png`, `getting-started/homepage.png`, `getting-started/apps-portal.png`,
  `getting-started/nav-sidebar.png`, `ontology-manager/oma-user-interface-overview-annotated.png`,
  `object-views/standard-full-and-panel-object-view.png`). They are Palantir's and are not copied into this repo.
