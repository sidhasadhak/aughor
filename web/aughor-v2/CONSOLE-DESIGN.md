# Aughor — Operations Console Design System

A portable spec for adopting the "analyst's operations console" direction in the
real app. Lineage: **Palantir** (object model, graph, provenance) · **Bloomberg**
(monospace authority, telemetry strip) · **Honeycomb** (surface the one signal) ·
**Linear** (restraint, command-first) · **HUD instruments** (reticle, mono labels).

The system is delivered as three additive files in `aughor-v2/theme/` plus this
doc. It rides on the existing token architecture — nothing is rewritten.

---

## How it imports (the whole wiring)

The app is already token-driven: `styles/tokens.css` defines primitives and a
Tailwind/shadcn bridge, `aughor-v2/theme/tokens-v2.css` overrides primitives, and
`.aug-*` component classes read those tokens via `var()`. The accent is read
everywhere through `--blue3`. So a re-skin is a token file, not a refactor.

Add these lines to `app/globals.css`, in this order, after the existing imports:

```css
@import "../aughor-v2/theme/tokens-console.css";      /* palette + radii re-skin */
@import "../aughor-v2/theme/console-components.css";  /* signature primitives    */
```

That is the entire integration for Phase 1–2. To revert, delete the two lines.

---

## What the re-skin does (Phase 1 — instant, ~60%)

`tokens-console.css` re-points primitives only. The load-bearing move: the accent
ramp `--blue*` is re-pointed to **amber**, so every bridge that reads it
(`--primary`, `--accent`, `--ring`, sidebar selection, all `.aug-*` accent uses,
and Tailwind `*-blue-*` utilities) becomes amber at once. Surfaces drop to
low-chroma graphite; `--red*` stays critical; `--cyn*` becomes the sparse
scan/link colour; radii tighten to instrument values (2 / 4 / 7px).

Result without touching a single component: graphite surfaces, amber accent,
tighter geometry, flatter elevation. A `[data-theme="light"]` "broadsheet" variant
is included for the bright register.

---

## What needs components (Phase 2 — the signatures)

Some pieces are structural, not colour. `console-components.css` adds them as
`.aug-*` classes so they slot into the existing vocabulary:

- `.aug-lbl` (+ `-sig` / `-crit` / `-scan`) — mono micro-labels; the console voice.
- `.aug-statusbar` / `.aug-st` — the telemetry strip under the topbar.
- `.aug-reticle` (+ child `.aug-reticle-x`) — HUD corner ticks for one signature panel.
- `.aug-conf` — segmented confidence meter.
- `.aug-receipt` / `.aug-rc` — provenance chips that justify a claim.
- `.aug-kv` — object-inspector key/value row.
- `.aug-tl` / `.aug-ts` — the reasoning timeline.

Drop these into the matching components (see adoption map). They reuse the
existing `@keyframes aug-blink` from `globals.css`.

---

## Type system

One grotesque + one mono — you already ship the mono (`--font-code`, IBM Plex Mono).

- **UI / body:** the platform sans (`--font-ui`). Keeping DM Sans is fine; Inter is
  the reference grotesque if you want the exact sample feel. Swapping requires a
  `next/font` wire-up in `app/layout.tsx` — optional, not required for the re-skin.
- **Data, labels, telemetry, coordinates, code:** `--font-code`, always with
  `font-variant-numeric: tabular-nums`. Mono carries figures and micro-labels.
- Scale: display 21–26 / heading 17–19 / body 13 / micro-label 9.5–10 (mono, tracked).

---

## Colour discipline (the rule that keeps it from "slop")

1. **Amber = signal** — active state, the primary finding, attention, key data.
2. **Red = critical only** — the one anomaly/loss on a screen. If everything is
   red, nothing is.
3. **Cyan = scan/link** — sources, "view SQL", drill-ins. Used sparingly.
4. **Everything else is graphite + ink.** Deltas, on-target metrics, structure —
   neutral. No green/blue/purple decoration. Status is a 7px mark + a word.

Provenance and confidence are first-class: any surfaced number can show source,
freshness, and a confidence meter. This is what distinguishes an *intelligence*
platform from a BI dashboard.

---

## Per-screen adoption map (Phase 3 — layout, high-value first)

Re-skin lands everywhere for free; these screens earn bespoke layout work, in order:

1. **Investigation** (`ChatPanel`, `ThinkingTrace`, `EvidencePanel`, `TrustReceipt`)
   → three columns: reasoning (`.aug-tl`) · finding + chart · evidence/provenance
   (`.aug-conf`, `.aug-receipt`, `.aug-kv`). The core flow; do this first.
2. **Intelligence Map** (`IntelligenceWorkspace`, `OntologyCanvas`) → object list by
   novelty · schematic graph on a coordinate grid · object inspector (`.aug-kv`).
   The signature screen.
3. **Topbar shell** (`app/page.tsx`) → add `.aug-statusbar` telemetry strip; make the
   command bar central with `/command` affordance.
4. **Briefing** → headline-signal-at-full-width composition.
5. **Health** → on-target recedes to grey, off-target is the only amber/red, sorted up.
6. Catalog / Fleet / Security → already table-forward; they inherit the re-skin well.

The standalone prototypes (`design-mockups/aughor-console-direction.html`, and the
full Swiss build) are the visual reference for these layouts.

---

## Rollout, verification, accessibility

- **Ship behind the import line** (or a class on `<html>`) so you can A/B the skin.
- **Verify:** run `next dev`, sweep every screen in dark + light, watch for any place
  that hard-codes a hex instead of a token (those won't re-skin — fix to use tokens).
- **Contrast (a11y):** amber `#EAB23E` on graphite passes for large text / UI, but
  **do not** use amber for small body text on dark — keep body on `--t1/--t2`. On the
  light broadsheet, amber is darkened (`#B5781A`) to hold contrast. Keep the focus
  ring (`--bfocus`) visible; it's amber now.
- **Motion:** the existing `prefers-reduced-motion` block in `globals.css` already
  neutralises `aug-blink` etc. — the live markers degrade to static.
- **Charts:** `Chart.tsx` / ECharts read `--chart-*`; those are re-pointed, so charts
  recolour automatically.

---

## Files

| File | Role |
|------|------|
| `aughor-v2/theme/tokens-console.css` | Palette + radii re-skin (Phase 1) |
| `aughor-v2/theme/console-components.css` | Signature `.aug-*` primitives (Phase 2) |
| `aughor-v2/CONSOLE-DESIGN.md` | This spec |
| `design-mockups/aughor-console-direction.html` | Visual reference (Investigation + Map) |
