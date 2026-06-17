# MAPPING — old → new token values & rationale

All variable **names** are unchanged from `styles/tokens.css`; only **values** move.
`tokens-v2.css` re-declares these in `:root` (dark) and `[data-theme="light"]`.

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
| blue | `#0C8CE9` | `#3B82F6` | brighter Blueprint blue; full ramp re-tuned |
| grn | `#18985A` | `#1FA968` | |
| amb | `#BD8800` | `#D9A013` | |
| red | `#C42A2A` | `#E0444E` | |
| vio | `#6040B8` | `#7C5CE0` | |
| cyn | `#1690BE` | `#1AA0C4` | |

Light mode keeps the Tableau-neutral scheme: accent `#1F77B4`, Tableau-10 chart
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
