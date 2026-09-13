# Instrument — the Aughor design system

The design system the web app runs on, adopted 2026-09-13 from the Claude Design project
**"Aughor Design System"** (`Aughor Design System.dc.html`, ten artboards: tokens dark and
light, type, components, the shell dark and light, the four universal states, the trust
system, motion, icons and density). This file is that spec in **this codebase's names**,
plus what adopting it decided. Where it says MUST, a reviewer rejects the diff.

## 0. The thesis

Aughor's product is a claim about a number, and the interface's whole job is to make that
claim checkable at a glance. Everything structural is monochrome on warm paper — the paper
is warm, the ink and the encoding are not. There is **one plane, not a stack of cards**:
hierarchy comes from hairlines and the honest weight of type. **Colour is a data type.**
Density is a feature: a screen carries 3–5× what a consumer app carries and still feels
calm. The answer to a crowded screen is better hierarchy at the same density, never more
whitespace.

## 1. Where it lives

| Layer | File |
|---|---|
| Tokens, both themes (the authority for values) | `aughor-v2/theme/tokens-v2.css` |
| Tailwind + shadcn bridges, pre-theme fallbacks | `styles/tokens.css` |
| Type scale classes | `styles/type.css` |
| Component classes (`.aug-*`), base, motion | `app/globals.css` |
| Primitives | `components/ui/*` (button, badge, input, select, tabs, dialog, toast, table, empty-state, motion …) |
| Chart palette mirror | `components/charts/palette.ts` (+ the committed `aughor/export/chart_ssr.bundle.mjs`) |
| Ant table theme mirror (Ant cannot read a CSS var) | `components/AugTable.tsx` |

`v2`'s `elevation-motion.css` (glass, lift, spring easing) and `components-v2.css` (the
override layer) were folded into `app/globals.css` and deleted: the design forbids glass,
glow and lift, and two component layers for one class is one too many.

## 2. Hard constraints

**Type.** Root 13px. Six steps and no others — `11 · 12 · 13 · 15 · 18 · 22` (`aug-fs-xs … aug-fs-display`);
28px exists in exactly one place, an icon in an empty state (`aug-fs-glyph`, `.aug-empty-glyph`).
11 is the floor. Inter for UI text; **JetBrains Mono for every figure, id, timestamp, metric,
table or column name, and code**, always tabular (`.aug-num`). Line heights 1.45 at 11/18,
1.55 at 12, 1.7 at 13 (1.8 in prose, `.aug-text-prose`), 1.5 at 15, 1.0 at 22.
`lint:tokens` fails an off-scale size and ratchets raw literals down.

**Geometry.** Radii `--r1` 3 · `--r2` 4 · `--r3` 6 (the design's `--r-3/--r-4/--r-6` alias
them). 3 for chips, tags, buttons; 4 for inputs, nav items, small containers; 6 for frames,
panels, overlays — a ceiling, not a default. Fully round (`--r-pill`) only for what IS round:
avatars and status dots. Shell: rail `--sidebar` 248 · topbar `--topbar` 48 · content header
44 · prose measure `--shell-measure` 700.

**Focus.** `2px solid var(--bfocus)` at 2px offset on every interactive element, never a
border colour change alone (`app/globals.css`). A full-bleed row insets it (`outline-offset: -2px`).

**Colour.** Token names are frozen. **No raw hex in a component** — every colour is a
`var(--token)`. Dark is the default and renders before `[data-theme]` is stamped; light is
designed, not inverted.

**Motion.** Tokens only: `--dur-1` 90ms (a state flip) · `--dur-2` 160ms (an entrance) ·
`--dur-3` 260ms (a layout change) · `--ease-out` · `--ease-inout`. The older names
(`--dur-fast/norm/slow/breath`, `--ease-pop/flow/spring`) alias these. Nothing over 260ms, no
spring, no overshoot. Every animation's reduced-motion fallback is its **finished** frame.

## 3. Tokens

41 distinct colour values per theme; an alias is a real `var()`, never a duplicated hex.
Values live in `tokens-v2.css` — read it, not a copy.

- **Surfaces** `--bg-0` canvas · `--bg-1` chrome · `--bg-2` = `--bg-1` (no cards) · `--bg-3`
  inset / input / code well · `--bg-4` pressed · `--bg-hover` = `--bg-3` · `--bg-nav` = `--bg-0` ·
  `--bg-sel` · `--scrim` · `--code-bg`. `--bg-canvas` (the Data Canvas ground) = `--bg-0`.
- **Lines** `--b0` the row rule, the workhorse · `--b1` default border · `--b2` input border,
  strong divider · `--b3` hover border · `--bfocus` = `--blue3`.
- **Text** `--t1` primary · `--t2` secondary · `--t3` captions and meta · `--t4` **never text** —
  ticks, rules, gutter numerals.
- **Intent** `--blueN --grnN --vioN --ambN --redN --cynN`: 1 tint · 2 border · 3 the colour ·
  4 text · 5 aliases 4. Cyan has no tint or border of its own (`--cyn1` = `--bg-3`, `--cyn2` = `--b2`).
- **Solid** `--blue-solid`, `--blue-solid-hover` (white label, AA), `--vio-solid` = `--vio3`.
- **Charts** `--chart-1..6` = blue3 · grn3 · vio3 · amb3 · cyn3 · red3, in that order (the order
  is the colour-blindness guarantee — do not reorder); `--chart-7` the kind accent;
  `--chart-deemph`; `--chart-axis/grid/tick` = `--b2/--b0/--t4`; thresholds warn = amb3,
  crit = red3, target = deemph.
- **Elevation** `--shadow-sm` (popover, tooltip, menu), `--shadow-md` (dialog, toast).
  `--shadow-lg` = sm and `--shadow-xl` = md for older call sites.

### Colour semantics — one vocabulary for state and series

| token | means | series |
|---|---|---|
| `--blue3` | interactive · links, selection, receipts | 1 |
| `--grn3` | guard passed · healthy · live | 2 |
| `--vio3` | deep analysis · agent reasoning | 3 |
| `--amb3` | waiting on a human · unresolved guard | 4 |
| `--cyn3` | no state meaning | 5 |
| `--red3` | adverse figure · failed run · refusal | 6 |

If a hue appears, a reader can name the state it means. No brand colour on chrome, no accent
for emphasis.

## 4. What adoption decided (2026-09-13)

1. **The hues were held to `lint:palette`, not the gate to the hues.** Four of the design's
   values failed a hard check: dark `--grn3` and `--cyn3` sat just above the lightness band
   and `--amb3` well above it, dark `--cyn3` and light `--cyn3` sat under the chroma floor,
   and dark `--grn3` sat at normal-vision ΔE 15.0 from `--blue3`. Each moved the minimum the
   validator needed — dark grn3 `#3FAE86→#3EAB82` (ΔE 0.9), amb3 `#C79A3A→#B88D30` (ΔE 4.3),
   cyn3 `#3FA8B4→#32A6B2` (ΔE 1.1); light cyn3 `#0D7A88→#00819C` (ΔE 3.3). Every other value
   is the design's hex.
2. **`--chart-7` stays a separately validated kind accent**, not `--vio3`: the automation canvas
   shows all seven step kinds at once. Dark keeps `#9B2378`; light moved to `#B73BCD` because the
   old `#871E5F` sat within normal-vision ΔE 11.9 of the new six.
3. **`--t4` carries no text.** The design's `--t3`/`--t4` are dimmer than the ramp they replaced
   (dark t4 ≈ 2.8:1), so every text colour that was `--t4` moved to `--t3`; `--t4` stays for
   ticks and rules (including `--chart-tick`, as the design aliases it).
4. **Sign-diverging chart colour** reads `--grn3` for positive and `--red3` for negative:
   `--chart-threshold-target` means a plan-target line now, so it no longer doubles as "good".

## 5. Components (class → primitive)

- **Buttons** — height 26 (small 22), radius 3, label 12/600; a press steps the background,
  the label never moves; loading = rest state + ◐ at .8 opacity. `.aug-btn`
  (`-primary` `-ghost` `-minimal` `-sm`). `<Button>` variants: `default` Primary · `secondary`
  Secondary · `outline` and `minimal` Ghost (bordered) · `link` Minimal ("show source") ·
  `ghost` the quiet toolbar/menu-row idiom (not on the sheet) · `destructive`. Sizes: default,
  `sm`, `lg` 26; `xs` 22; icon sizes square at 26/22.
- **Fields** — `.aug-input` `.aug-select` `.aug-textarea`, `<Input> <Textarea> <SelectTrigger>`:
  height 28, radius 4, `--bg-3`, `--b2` → `--b3` on hover, error `--red2` border with `--red4`
  text (`.aug-field-error`), placeholder `--t3` and never italic; a figure is mono (`.aug-input-figure`).
- **Selection** — `.aug-tabs`/`.aug-tab` (2px `--blue3` underline, 600 when active) and
  `.aug-segmented`/`.aug-seg-item` (`--bg-4` selected, `--b2` dividers). `<Tabs>` `line` and
  `default`. Never both in one header. Every workspace layer switcher is segmented.
- **Badge** — `.aug-badge-{blue,green,amber,red,violet,cyan,neutral}` (`.aug-tag-*` alias):
  11px mono, `2px 7px`, radius 3, tint 1 · border 2 · text 4.
- **Callout** — `.aug-callout-{blue,green,amber,red,violet}` + `.aug-callout-kind`: radius 4,
  tint 1, border 2, a 3px left rule in hue 3. Never an icon in a circle.
- **Status dot** — `.aug-dot-{live,idle,waiting,failed,analysing}`, 7px; live and analysing pulse.
- **Progress** — `.aug-progress`, `<Progress>`: a 3px rule, never a ring; print the figure beside it.
- **Table** — `.aug-dt`, `<Table>`: sticky 22px header on `--bg-1`, `--b2` underline, 11px mono
  uppercase labels in `--t3`; 24px rows ruled `--b0`; hover `--bg-hover`, selected `--bg-sel`;
  numeric cells `.num` — right-aligned, mono, tabular.
- **Overlay** — the only three things that float: `.aug-popover`/`.aug-tooltip` (`--bg-3`,
  `--b2`, radius 4, `--shadow-sm`), `.aug-toast` (`--bg-1`, 3px left rule in its hue, radius 6,
  `--shadow-md`), `.aug-dialog` (`--bg-1`, `--b2`, radius 6, `--shadow-md`, over `--scrim`).
  A shadow on a panel, a table or a metric tile is a review reject.
- **Empty** — `<EmptyState>` / `.aug-empty`: left-aligned, the 28px glyph in `--b3`, a 13/600
  title, 12px body, then the one action that resolves it. Never a shrug.
- **Pending and loading** — `<Pending>` (◐) and `<SkeletonRows>` / `.aug-skeleton`.
  **No spinners anywhere in the product.**
- **Trust system** — `.aug-guard`, `.aug-receipt-*`, `.aug-confidence`, `.aug-cite`, `.aug-why` →
  `components/ui/trust.tsx` (`GuardChip`, `ReceiptChain`, `Confidence` + `confidenceTier`, `Cite`,
  `WhyFigure`, `WhyCard`).
- **Error, partial, refusal** — `.aug-error`, `.aug-partial` (+ `.aug-hatch`), `.aug-refusal` →
  `components/ui/states.tsx` (`ErrorState`, `PartialState`, `Refusal`).

## 6. The shell

```
topbar 48   wordmark · workspace switcher · ⌘K command · user menu
rail 248    Home · Inbox · Data Canvas / INTELLIGENCE / DATA / OPERATIONS, then Settings pinned
header 44   screen title · context meta · segmented layer switcher · primary action
```

Nav item 22px, 12px label, 14px icon. **Active**: `--bg-sel`, weight 500, a 2px `--blue3` bar
at the rail edge — one in the whole rail. **Hover**: `--bg-hover` and nothing else. The rail
keeps **Spend** under Operations: the design was synced before Spend shipped.

## 7. Motion

| name | class | duration · easing | reduced motion |
|---|---|---|---|
| streaming-caret | `.aug-caret` | 1s `steps(1)` | solid, static |
| step-in | `.aug-anim-up` `.aug-step-in` `.aug-stream-in` | `--dur-2` · `--ease-out`, opacity + 4px up | final position |
| check-pop | `.aug-check-pop` | `--dur-1`, 1.04 that settles | colour only |
| pulse | `.aug-pulse-dot` `.aug-dot-live` | 1.05s `--ease-inout` | lit colour, static |
| shimmer | `.aug-skeleton` | 1.1s linear, 360px sweep | flat `--bg-4` |
| disclosure | `.aug-disclose` | `--dur-3` · `--ease-out` | instant |
| modal-pop | `.aug-anim-pop`, `<DialogContent>` | `--dur-2`, 0.98 → 1 | final state |
| press | element `:active` | `--dur-1`, background only | background only |

## 8. Icons and density

One stroke set — Tabler, through `components/ui/icon.tsx` only (`lint:icons`) — at 14px,
`currentColor`, no fills. Icons are navigational, never decorative: if an icon and a word say
the same thing, the icon goes. Status is a 7px dot, not an icon. Emoji are forbidden. Spacing
`4 · 6 · 8 · 10 · 12 · 16 · 20 · 24`. Dense row 24px (the default), header 22, comfortable 34
only where a row carries two lines, nav item 22, attention row 28, activity-tail line 17.

## 9. What exists, and what does not yet

**Pass 1 (2026-09-13)** — tokens, type, motion, the primitives and the shell chrome.

**Pass 2 (2026-09-13)** — the rest of the design system, adopted into the shared surfaces:
- **Trust system** (`components/ui/trust.tsx`): guard chips on the chat's guard receipts, on Why
  this number's guard rows and glance, on the Security audit verdicts and on the Briefing
  explorer's refused status; `Confidence` on the evidence claim, the evidence panel and the
  report's hypotheses and findings, with one threshold set everywhere; the grounded-number receipt
  popover drawn as the why-this-number popover.
- **States** (`components/ui/states.tsx`): `ErrorState` for the chat turn error, the render
  boundary, the chart error, and the tinted red boxes in Add connection, Agents, Integrations,
  Create agent, the audit feed, document upload, the SQL runner and the Briefing synthesis. No
  `animate-pulse` is left: skeletons are `.aug-skeleton`, live dots `.aug-pulse-dot`, the run
  caret `.aug-caret`.
- **Shell**: the topbar LIVE activity strip (`components/shell/ActivityStrip.tsx` — the Agent Ops
  runs chart in miniature, in-flight agent jobs, "exploring"), the dark/light toggle in the topbar,
  and the rail's badge counts (`components/shell/useNavCounts.ts` — unacknowledged alerts on
  Monitors and the Operations header, running agent runs on Agent runs).

**Pass 3 (2026-09-13) — the Briefing** (`Aughor Intelligence.dc.html`, artboards 01 and 10), with
artefact manners: a 44px gutter numbering the sections (01, §1…), a 700px measure, superscripts
(`CiteRef`) into a 300px apparatus rail, and a signature. The shell's header carries the brief's
written-at stamp, Regenerate and Investigate, under a title that stays "Intelligence" (`Workspace`
`title`). §1 is the north-star metrics as a table (`components/brief/MovedNumbers.tsx`): now and
prior are the series' last two buckets — never the whole-history value query beside them, which
stays on the row as "overall" — and the receipt is a column (`ReceiptRef`). What the data cannot
carry is not drawn:
- no briefing number, no "unprompted", no Export — nothing numbers, attributes or exports a brief;
- no verdict tone, no confidence and no "earned" bar — none is computed for a brief;
- no contribution column — nothing computes a metric's contribution to the verdict;
- no Figure 1 — no chart is tied to the prose;
- the signature's guard chips are the trust gate's plausibility reading of the cited findings, and
  `held_back` stays off the page (it read as an error log — BriefingPanel says why);
- a brief is one POST, not a stream: the screen says "opening" or "being written" over skeletons,
  with no caret and no placeholder prose.

**Not yet:**
- The Human / Agent / Substrate switcher — left out by the user until there is a concrete use.
- An Agent Ops needs-human badge: `GET /control-room/needs-human` runs the expiry and parked-run
  sweeps on every call, so the shell must not poll it; it needs a side-effect-free count first.
- A coverage figure in the strip: no endpoint serves the explorer's frontier.
- `PartialState` has no call sites yet — the "floor, not a total" captions (Spend, the Agent Ops
  tiles, usage, traces) still print as captions.
- About 46 text-only "Loading…" placeholders, about 50 bare red error lines (no one-line inline
  error primitive yet), and about 30 components with raw hexes (canvases, Semantic Layer badges,
  Monitors toggles).
- The Agent Ops runs chart hatches RUNNER runs, which clashes with the hatch's one meaning
  (unknown, not zero) — left for a decision.
- The other Intelligence screens (`Aughor Intelligence.dc.html` 02–09): Profile, Ontology, Graph,
  Evidence, Memory, Actions, Org, and Ontology on a warehouse that has just connected.

## 10. Self-check before a screen ships

1. Every font size is 11/12/13/15/18/22. 2. Every colour is a `var(--token)`. 3. Every figure
is mono, tabular, right-aligned in tables. 4. Every figure reaches its receipt. 5. Every hue on
screen can be named as a state. 6. Every interactive element has the 2px ring. 7. Every radius
is 3, 4 or 6 — or round on something round. 8. Empty, loading, error and partial all exist.
9. Every animation's reduced-motion frame is its finished frame. 10. Nothing floats that is not
a popover, a toast or a dialog. 11. Light was designed, and dark still renders first.
