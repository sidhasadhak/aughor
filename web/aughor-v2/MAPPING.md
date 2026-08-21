# MAPPING — old → new token values & rationale

All variable **names** are unchanged from `styles/tokens.css`; only **values** move.
`tokens-v2.css` re-declares these in `:root` (dark) and `[data-theme="light"]`.

> **This file records the ORIGINAL v2 handoff and is kept for its rationale, not as
> a current reference.** The values below stopped matching the shipped theme before
> the console re-skin (this file lists `--bg-0: #0A0D13`; the file shipped
> `#10161D`). **`theme/tokens-v2.css` is the only authority for current values** —
> read it, not this table. See "Console re-skin" at the foot of this file for what
> the latest pass changed and why.

## Backgrounds (dark)

| Token | Original | v2 | Why |
|---|---|---|---|
| `--bg-0` | `#0D1117` | `#0A0D13` | deeper canvas floor |
| `--bg-1` | `#111418` | `#0E121A` | rails/topbar |
| `--bg-2` | `#161A20` | `#141925` | base card |
| `--bg-3` | `#1C2128` | `#1A2030` | raised/hover |
| `--bg-4` | `#222A33` | `#232C3E` | control/active — wider step for clearer lift |
| `--bg-sel` | `rgba(12,140,233,.12)` | `rgba(59,130,246,.14)` | matches brighter accent |

## Borders (dark)

| Token | Original | v2 |
|---|---|---|
| `--b0` | `#161A20` | `#11151D` |
| `--b1` | `#1E2329` | `#1B2130` |
| `--b2` | `#252B33` | `#252E40` |
| `--b3` | `#2E3540` | `#334056` |
| `--bfocus` | `#0C8CE9` | `#3B82F6` |

Text (`--t1..4`) is essentially unchanged — only `--t1` nudged `#E2E4E9` → `#EAEDF3`
for the deeper canvas. Hierarchy + legibility floor preserved.

## Accent & intent (dark)

The canonical accent is **`--blue3`** (read by `--primary`/`--accent`/`--ring`/`--sidebar-*`).

| Ramp | Original `3` (base) | v2 `3` | Notes |
|---|---|---|---|
| blue | `#0C8CE9` | `#3B82F6` | brighter primary blue; full ramp re-tuned |
| grn | `#18985A` | `#1FA968` | |
| amb | `#BD8800` | `#D9A013` | |
| red | `#C42A2A` | `#E0444E` | |
| vio | `#6040B8` | `#7C5CE0` | |
| cyn | `#1690BE` | `#1AA0C4` | |

Light mode keeps the neutral-gray scheme: accent `#1F77B4`, categorical chart
palette. Full ramps in `tokens-v2.css`.

## Radius

| Token | Original | v2 | Scope |
|---|---|---|---|
| `--r1` | `2px` | `4px` | chips/badges |
| `--r2` | `4px` | `6px` | buttons/inputs |
| `--r3` | `6px` | `10px` | **panels/cards/modals** — the visible "modern" shift |

> Revert: comment out the three `--r*` lines in `tokens-v2.css` to restore the 6px ceiling.

## Elevation

| Token | Original | v2 |
|---|---|---|
| `--shadow-sm` | `0 1px 4px rgba(0,0,0,.35)` | `0 1px 2px rgba(0,0,0,.4), 0 1px 1px rgba(0,0,0,.3)` |
| `--shadow-md` | `0 4px 16px rgba(0,0,0,.45)` | `0 4px 16px rgba(0,0,0,.45), 0 1px 2px rgba(0,0,0,.4)` |
| `--shadow-lg` | *(new)* | `0 8px 28px rgba(0,0,0,.5), 0 2px 8px rgba(0,0,0,.4)` |
| `--shadow-xl` | *(new)* | `0 20px 60px rgba(0,0,0,.6), 0 6px 18px rgba(0,0,0,.45)` |

`--shadow-lg/xl` and `--shadow-acc`, `--glass-bg`, `--ease-spring`, and the
`--acc-dim/soft/glow` tints are **new**, defined in `elevation-motion.css`.

## Layout

| Token | Original | v2 |
|---|---|---|
| `--sidebar` | `224px` | `232px` |
| `--topbar` | `48px` | `56px` |

## Charts — token palette

`--chart-1..6`, `--chart-threshold-*`, `--chart-axis/grid/tick` keep their names.
v2 makes axis/grid **alpha-based** (`rgba(255,255,255,.10)` / `.05` dark;
`rgba(20,40,80,.12)` / `.06` light) so they read correctly on any surface.

## Charts — hardcoded hexes to replace (in `components/Chart.tsx`)

These are inline in the Vega spec builders today; swap for `vegaV2Marks.*`:

| Usage | Hardcoded | Replace with |
|---|---|---|
| bar fill | `#818cf8` | `vegaV2Marks.bar` (`--chart-1`) |
| line/area | `#10b981` | `vegaV2Marks.line` (`--chart-2`) |
| pareto cumulative line | `#f59e0b` | `vegaV2Marks.paretoLine` (`--chart-3`) |
| 80% / reference rule | `#71717a` | `vegaV2Marks.reference` (`--chart-tick`) |
| treemap/heatmap stroke, PNG bg | `#131c27` / `#0e1520` | `vegaV2Marks.pngBg` (`--bg-2`) |
| bar shape | *(square top)* | add `cornerRadiusEnd: 3` |

Also feed `vegaV2Range()` to categorical color scales (replaces the inline
`AUG_PALETTE` range in `lib/palette.ts`), and spread `vegaV2Config()` into the
spec's `config`.

## color-mix → static fallbacks (only if targeting old browsers)

| Expression | Static (dark accent #3B82F6) |
|---|---|
| `--acc-dim` = `color-mix(… 16%)` | `rgba(59,130,246,.16)` |
| `--acc-soft` = `color-mix(… 26%)` | `rgba(59,130,246,.26)` |
| `--acc-glow` = `color-mix(… 42%)` | `rgba(59,130,246,.42)` |


---

## Console re-skin

A pass over `tokens-v2.css` to adopt a console visual language: cool near-neutral
surfaces, one blue that means "interactive", flat hairline structure, tight shape.
Values are in the file; this records the decisions a reader would otherwise have to
reverse-engineer.

| Area | Change | Why |
|---|---|---|
| Surfaces | Cool near-neutrals, canvas below surfaces | Panels read as planes without a shadow doing the work |
| Shape | `--r1/2/3` → 3 / 4 / 6px | Restores the original "max 6px" ceiling the earlier pass raised to 12px. Density is a feature in a tool kept open all day |
| Elevation | `.aug-panel` shadow removed; `--shadow-*` softened | `.aug-panel` already carries `1px solid var(--b1)`, so the shadow restated the same edge — and stacked across nested panels it is what made surfaces read as boxes |
| Tags | `.aug-tag` pill → `--r1` | Rectangular badges. `--r-pill` stays for what is genuinely round: avatars, status dots |
| Fonts | DM Sans → Inter, IBM Plex Mono → JetBrains Mono | Both via `next/font` (self-hosted at build; no runtime CDN request). `--font-ui`/`--font-mono` absorb the swap everywhere else |
| Primary hover | Hardcoded `#2A82CC` → `var(--blue-solid-hover)` | **Bug fix.** The literal was a dark-mode value, so light mode hovered *lighter* instead of darker |

### The ink tiers are NOT taken verbatim

The reference design has three text tiers and reserves its faintest
(`--text-placeholder`) for placeholder text. This system has four and uses `--t3`
and `--t4` for real content — timestamps, row meta, labels. Adopting the
placeholder grey as `--t3` measured **2.31:1** on the canvas and would have
re-opened the defect `styles/tokens.css` already records:

> *"the old --t3 (~3:1) and --t4 (~1.9 — below perceivable) made row numbers,
> timestamps and labels 'almost invisible' (user report)."*

So `--t1`/`--t2` are the reference values exactly, and `--t3`/`--t4` are stepped
down from `--t2` in the same hue until every tier clears 3:1 on every surface.
Measured, worst surface in each mode:

| | t1 | t2 | t3 | t4 |
|---|---|---|---|---|
| light | 16.04 | 4.43 | 3.73 | 3.13 |
| dark | 13.47 | 6.40 | 3.85 | 3.18 |

Both tiers land **above** what shipped before this pass (light t3 2.89, t4 1.94).

### The chart series are untouched, deliberately

`--chart-1..6` were chosen by the `lint:palette` validator, not by eye — stepped
into a lightness band and ordered by exhaustive search for CVD separation. They
already sit in this accent's hue family, so retinting them would spend real CVD
headroom for no visible gain. What moved is the chrome (`--chart-axis/grid/tick`),
which follows the new borders and text. `--chart-tick` is `--t2`, not `--t3`:
axis labels are text and must read as text.
