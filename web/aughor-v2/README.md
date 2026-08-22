# Aughor Design Language v2 — Handoff Package

A drop-in elevation of the existing Aughor system (primary-blue accent on
near-black charcoal surfaces, DM Sans, token-driven dark/light). Same DNA — deeper
surfaces, real elevation, rounded bars, smooth gated motion, a unified component
and chart treatment across both themes.

This package is **token-first and additive**: the core re-skin is one CSS import
that overrides primitive tokens; every Tailwind/shadcn bridge and existing
`.aug-*` component inherits the new look automatically. Nothing here requires
rewriting component markup.

## What's inside

```
handoff/
├── README.md                      ← you are here
├── INTEGRATION.md                 ← step-by-step for Claude Code + verification + rollback
├── MAPPING.md                     ← token old→new values, chart hex map, rationale
├── theme/
│   ├── tokens-v2.css              ← [CORE] primitive token override (dark+light). Import after styles/tokens.css
│   ├── elevation-motion.css       ← [CORE] new tokens (elevation/glass/easing) + gated animation utilities
│   └── components-v2.css          ← [OPTIONAL] elevates existing .aug-* classes (gradient btn, lifted cards, pill tags…)
└── charts/
    ├── vega-theme-v2.ts           ← themes the EXISTING Vega engine (Chart.tsx/VegaChart) — palette, axes, rounded bars
    └── Charts-v2.tsx              ← portable SVG dashboard charts (Bar/Area/Donut/Pareto/Sparkline/Counter)
```

## Load order (globals.css)

```css
@import "tailwindcss";
@import "tw-animate-css";
@import "../styles/tokens.css";              /* original — keep: all bridges live here */
@import "../aughor-v2/theme/tokens-v2.css";  /* CORE: elevated primitive values        */
@import "../aughor-v2/theme/elevation-motion.css"; /* CORE: shadows, glass, motion       */
@import "../styles/type.css";
@import "../aughor-v2/theme/components-v2.css";    /* OPTIONAL: re-skin .aug-* components */
```

## Three integration tiers (pick how far to go)

1. **Re-skin only (lowest risk).** Import `tokens-v2.css` + `elevation-motion.css`.
   The whole app shifts to v2 colors, depth, and radii with zero markup changes.
2. **+ Component polish.** Add `components-v2.css` for gradient primary buttons,
   card hover-lift, pill tags, input focus rings, glass topbar.
3. **+ Charts.** Apply `vega-theme-v2.ts` to the Vega engine and use `Charts-v2.tsx`
   for dashboard/briefing surfaces (stat sparklines, briefing trend/region/pareto).

Each tier is independent and individually revertible. Start at tier 1, verify,
then proceed. **See INTEGRATION.md before applying.**

## Notable deviations from the original system (deliberate)

> The three bullets that stood here described the first handoff and no longer
> describe the shipped theme — the console re-skin reversed two of them. Current
> state:

- **Radius ceiling restored** to 6px (`--r1/2/3` = 3 / 4 / 6px). The first pass
  raised it to 12px; the re-skin put it back, because the original "max 6px" rule
  was right for a dense tool.
- **One accent, both modes.** `--blue3` is the interaction accent (`#1F6CB0` light,
  `#62AEEF` dark). `--blue-solid` is a darker step used as the primary-button fill
  so it carries white text, which is what `--primary-foreground: #fff` promises.
- **Structure is borders, not shadows.** `--shadow-sm/md/lg/xl` still exist but are
  soft and reserved for real overlays (menus, dialogs, tooltips); `.aug-panel`
  carries none.
- **Inter + JetBrains Mono**, via `next/font` — self-hosted at build time.

`theme/tokens-v2.css` is the authority for values. `MAPPING.md` carries the
rationale, including why the ink tiers are not taken verbatim from the reference
design and why the chart series are untouched.
