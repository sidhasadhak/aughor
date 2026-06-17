# INTEGRATION — for Claude Code

Apply in tiers, verifying after each. Everything is additive and revertible.

---

## Prerequisites

- The repo already imports `styles/tokens.css` and `app/globals.css`.
- Copy this `handoff/` folder into the web app as `web/aughor-v2/` (or any path;
  adjust the import paths below to match).

---

## Tier 1 — Re-skin (tokens) · LOW RISK

1. Copy `theme/tokens-v2.css` and `theme/elevation-motion.css` into `web/aughor-v2/theme/`.
2. In `app/globals.css`, add the two imports **after** `../styles/tokens.css`:

   ```css
   @import "../styles/tokens.css";
   @import "../aughor-v2/theme/tokens-v2.css";
   @import "../aughor-v2/theme/elevation-motion.css";
   ```

3. **Why this works:** `tokens-v2.css` re-declares only primitive tokens
   (`--bg-*`, `--b*`, `--t*`, intent ramps, `--blue3` accent, `--r*`, `--shadow-*`,
   `--chart-*`). The Tailwind bridge (`--primary`, `--accent`, `--ring`, …) and the
   accent-palette bridge (`--color-blue-500`, …) in the original `tokens.css`
   reference these via `var()`, so they cascade with no further edits.

   ✅ Verify: app renders in dark + light (toggle `data-theme` on `<html>`).
   Surfaces are deeper, cards lift off the page, accent is brighter blue, panels
   are softer-cornered. No layout shifts. No console errors.

   ⏪ Rollback: remove the two import lines.

---

## Tier 2 — Component polish (.aug-*) · LOW RISK

1. Copy `theme/components-v2.css`; import it **last** in `globals.css` (after
   `type.css`).
2. For cards that should lift on hover, add `aug-panel-interactive` next to
   `aug-panel` on clickable cards only (non-clickable cards keep static elevation).

   ✅ Verify: primary buttons are gradient + glow; tags are pills; inputs show a
   focus ring; topbar reads as glass; nav active-rail glows.

   ⏪ Rollback: remove the import. Delete individual rules to revert single elements.

---

## Tier 3a — Vega charts (existing engine)

The analytical charts in `components/Chart.tsx` (via `VegaChart`) keep using Vega —
just theme them.

1. Copy `charts/vega-theme-v2.ts` to `web/aughor-v2/charts/`.
2. In `Chart.tsx`, where the final spec is assembled, merge the config and range:

   ```ts
   import { vegaV2Config, vegaV2Range, vegaV2Marks } from "@/aughor-v2/charts/vega-theme-v2";

   const themed = { ...spec, config: { ...vegaV2Config(), ...(spec.config ?? {}) } };
   // categorical scales: range: { scheme: ... } → range: vegaV2Range()
   ```

3. Replace hardcoded mark hexes (see `MAPPING.md › Charts`):
   - bars `#818cf8` → `vegaV2Marks.bar`
   - lines `#10b981` → `vegaV2Marks.line`
   - pareto line `#f59e0b` → `vegaV2Marks.paretoLine`
   - reference rules `#71717a` → `vegaV2Marks.reference`
   - PNG export bg `#131c27` → `vegaV2Marks.pngBg`
   - add `cornerRadiusEnd: 3` to bar marks (or rely on the `bar` config block).

4. **Theme reactivity:** `vegaV2Config()` reads CSS vars at call time. Ensure the
   chart re-renders when `data-theme` flips — pass the current theme as a `key` or
   effect dependency to the chart wrapper so the spec is rebuilt.

   ✅ Verify: bars rounded + on-palette, axes/grid use `--chart-*` tokens, charts
   restyle on theme toggle. PNG export background matches the card.

---

## Tier 3b — Dashboard charts (new, presentational)

For Briefing / Health / stat tiles, use `charts/Charts-v2.tsx` (dependency-free
SVG). These are NOT for query results — keep Vega for those.

```tsx
import { AreaChart, DonutChart, BarChart, ParetoChart, Sparkline, Counter }
  from "@/aughor-v2/charts/Charts-v2";

<AreaChart data={[{ label: "Jan", v: 4.2e6 }, …]} accent="var(--chart-1)" valuePrefix="$" />
<Counter value={3.98} prefix="$" suffix="M" decimals={2} />
```

Requires Tier 1 imports (tokens + elevation-motion) for colors and the
`.av2-gv-*` keyframes.

---

## Motion gate (required for any animation)

Entrance/grow animations are gated behind `html.av2-animate`, added via
`requestAnimationFrame` so frozen-timeline contexts (SSR snapshot, print,
reduced-motion, headless capture) render the **finished** state instead of
`opacity:0`. Add once, near the root client component:

```ts
useEffect(() => {
  const id = requestAnimationFrame(() =>
    requestAnimationFrame(() => document.documentElement.classList.add("av2-animate"))
  );
  return () => cancelAnimationFrame(id);
}, []);
```

Then opt elements in with `av2-rise` / `av2-fade` / `av2-pop`, or stagger a group
with `data-av2-stagger` on the parent and `style={{ "--i": index }}` on children.
Charts already carry `av2-gv-bar` / `av2-gv-draw` and animate when the class is on.
Skip the class (or honor `prefers-reduced-motion`) to ship a fully static UI.

---

## Verification checklist (run after each tier)

- [ ] `next build` / typecheck passes (Charts-v2.tsx is typed; vega-theme-v2.ts is typed).
- [ ] Dark + light both render; toggle `data-theme="light"` on `<html>`.
- [ ] No contrast regressions on `--t3`/`--t4` text, table headers, row meta.
- [ ] Focus rings visible on inputs/buttons (keyboard tab-through).
- [ ] Charts re-theme on mode switch; bars rounded; palette = `--chart-*`.
- [ ] With JS disabled / reduced-motion: content is fully visible (no blank cards).
- [ ] Existing `.aug-*` screens unchanged structurally — only restyled.

---

## Risks & notes

- **Radius change is global** (`--r3` 6→10px). If product guidelines mandate the
  6px ceiling, comment out the three `--r*` lines in `tokens-v2.css`.
- **`color-mix()`** is used for accent tints (elevation-motion.css, components-v2.css).
  Supported in all current evergreen browsers; if you must support older targets,
  replace with static rgba equivalents from `MAPPING.md`.
- **`backdrop-filter`** (glass topbar) has a `-webkit-` fallback included; it
  degrades to a solid surface where unsupported.
- Do not edit the original `tokens.css` — keep it as the source of bridges; the
  override layer is intentionally separate so the whole package reverts cleanly.
