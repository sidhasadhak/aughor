# Implementation Brief — Operations Console Design

> **For an AI coding agent (Claude Code).** This is a self-contained task spec to
> roll the "analyst's operations console" design across the Aughor web app. The
> design system, tokens, and a reference implementation already exist in the repo
> (listed below). Your job is to apply the system to the remaining screens.
> Work in small, verifiable commits. Do not break behaviour — this is a re-skin +
> component-primitive adoption, not a logic change.

---

## 0. Orientation — what already exists

Read these first; they are the source of truth.

| File | What it is |
|------|-----------|
| `web/aughor-v2/CONSOLE-DESIGN.md` | The design system spec (philosophy, colour rules, type, components) |
| `web/aughor-v2/theme/tokens-console.css` | Token re-skin: graphite surfaces + amber accent. **Already imported.** |
| `web/aughor-v2/theme/console-components.css` | The `.aug-*` console primitives. **Already imported.** |
| `web/app/globals.css` | Imports the two files above (lines after `type.css`). |
| `design-mockups/aughor-console-direction.html` | **Visual ground truth.** Open in a browser. Investigation + Intelligence Map, fully built. Match this. |
| `design-mockups/aughor-swiss-prototype.html` | Full 17-screen layout reference (earlier monochrome pass; use for composition ideas). |

Reference implementation already done (study these as the pattern to copy):
`components/ThinkingTrace.tsx`, `components/EvidencePanel.tsx`,
`components/TrustReceipt.tsx`, `components/ChatPanel.tsx`.

---

## 1. The non-negotiable rules

The whole point of this design is **restraint**. Breaking these makes it "AI slop."

1. **One accent.** The accent token is `--blue3` (now amber `#EAB23E`). Use it for
   active state, the primary signal/finding, key data, focus. Nothing else competes.
2. **Red = critical only** (`--red3`). The single anomaly/loss on a screen. If
   everything is red, nothing is.
3. **Cyan = scan/link only** (`--cyn3`). Sources, "view SQL", drill-ins. Sparse.
4. **Everything else is graphite + ink.** On-target metrics, deltas, structure,
   generic "done" states → neutral (`--t1`–`--t4`, `--b0`–`--b3`, `--bg-0`–`--bg-4`).
   No green/violet/blue decoration. Status = a small mark + a word.
5. **Mono carries data & labels.** Use `var(--font-code)` + `tabular-nums` for all
   figures, and the `.aug-lbl` class for section / micro labels (mono, uppercase, tracked).
6. **Use tokens, never hex.** Any `#rrggbb` literal in a component will NOT re-skin.
   Replace with the nearest token (see colour map below).
7. **Hairlines over shadows.** Lean on `1px solid var(--b1)` borders; keep radii tight
   (`--r1` 2px, `--r2` 4px, `--r3` 7px).

### Colour token map (use these, not raw hex)
- Surfaces: `--bg-0` (canvas) → `--bg-4` (raised). Hairlines `--b0`–`--b3`. Focus `--bfocus`.
- Ink: `--t1` (primary) `--t2` (secondary) `--t3` (tertiary) `--t4` (faint).
- Accent (amber): `--blue3` base, `--blue4` bright, `--blue1`/`--blue2` tints. (Tailwind
  `*-blue-*` and `*-amber-*` utilities both resolve to amber via the bridge.)
- Critical: `--red3`/`--red4`. Scan/link: `--cyn3`/`--cyn4`. Positive (rare): `--grn3` (muted teal).
- Charts read `--chart-1..6` (already re-pointed) — don't hard-code series colours.

---

## 2. Console component primitives (already available globally)

From `console-components.css`. Prefer these over bespoke markup.

| Class | Use for |
|-------|---------|
| `.aug-lbl` (+ `.aug-lbl-sig` / `-crit` / `-scan`) | Mono micro-labels; section headers; the console "voice" |
| `.aug-statusbar` + `.aug-st` (+ `.aug-st--right`, `.aug-pdot`/`--sig`/`--crit`) | Telemetry strip under the topbar |
| `.aug-reticle` (+ child `<span class="aug-reticle-x">`) | HUD corner ticks on ONE signature panel per screen |
| `.aug-conf` (with `<i>` segments, add `.on`) | Segmented confidence meter |
| `.aug-receipt` + `.aug-rc` (`.d` = status dot) | Provenance chips that justify a claim |
| `.aug-kv` (`.k` / `.v` / `.v.mono`) | Object-inspector key/value rows |
| `.aug-tl` + `.aug-ts` (`.done`/`.run`, `.nd`/`.k`/`.l`/`.m`) | Reasoning timeline |

They read existing tokens, so they flip with light/dark automatically and reuse the
existing `@keyframes aug-blink` in `globals.css`.

---

## 3. Task list — apply the system, in priority order

For each screen: open the component, replace hard-coded hex with tokens, apply the
colour rules, and adopt the relevant primitive. Keep all data/logic identical.
Commit per screen. Run the verification in §4 after each.

### P0 — App shell (highest visibility)
- [ ] `app/page.tsx` — **add the telemetry status strip** under the topbar using
      `.aug-statusbar` / `.aug-st`. Show: system status, connections + freshness,
      agents live (`.aug-pdot--sig`), budget, open signals (`.aug-pdot--crit`),
      active canvas (`.aug-st--right`), p95 latency. Wire to existing state where it
      exists (`getConnectionFreshness`, `getJobs`, `costSummary`); static placeholders
      are acceptable for fields without a source yet. Match the prototype's strip.
- [ ] `app/page.tsx` — sidebar nav active state uses the amber left-marker (already
      via `.aug-nav-item.active`); confirm it reads amber after the skin. Make the
      command bar visually central; add a `/` affordance hint.

### P1 — Intelligence Map (the signature screen)
- [ ] `components/IntelligenceWorkspace.tsx` — layer switcher as underline tabs;
      persistent scope line; `.aug-lbl` headers.
- [ ] `components/OntologyCanvas.tsx` — render the graph as a **schematic on a
      coordinate grid** (dotted/lined bg), nodes as mono-labelled chips, high-novelty
      nodes carry amber, selected node = amber fill. Add an **object inspector** panel
      on the right using `.aug-kv` rows (kind, rows, synonyms, relations, learned
      skills) + a novelty meter via `.aug-conf`. See prototype tab 02.
- [ ] `components/ERDiagram.tsx` — align table cards to graphite + hairline + mono
      column labels; FK lines neutral.

### P1 — Investigation polish (reference already started)
- [ ] `components/ChatMessage.tsx` — the inline trace + result figure: ensure the
      3-part read (finding → evidence → receipt) is visually clear; figures use the
      chart tokens; "Source data" link uses `.aug-lbl-scan` cyan.
- [ ] `components/InvestigationReport.tsx`, `ExplorationReport.tsx`, `ReportView.tsx`
      — section headers → `.aug-lbl`; phase markers neutral; keep verdict colours only
      where they carry meaning.
- [ ] `components/HypothesisCard.tsx` — confidence via `.aug-conf`; status neutral.

### P2 — Data screens (table-forward; inherit the skin well)
- [ ] `components/CatalogScreen.tsx` — left index + right detail; column table with
      type chips (`.aug-rc`) + distribution; `.aug-lbl` section heads.
- [ ] `components/QueryBuilder.tsx` — dimension/measure/filter chips; result chart uses
      chart tokens; grain-warning uses `--blue3` (signal) / `--red3` (critical).
- [ ] `components/SemanticLayerPanel.tsx`, `MetricsPanel.tsx` — underline tabs; metric
      approval lifecycle states as neutral + amber (approved) + red (rejected).

### P2 — Operations & the rest
- [ ] `components/ProcessHealthPanel.tsx` (Health) — **on-target recedes to ink-grey;
      off-target is the only amber/red and sorts to the top.** This rule is the whole
      design in one screen.
- [ ] `components/RecommendationInbox.tsx` (Inbox) — one triage list; type as `.aug-lbl`;
      one status mark per row; one primary verb per row.
- [ ] `components/MonitorsPanel.tsx`, `ActionHubPanel.tsx`, `SecurityAuditPanel.tsx`,
      `ActivityLog.tsx` — tables to graphite + mono figures; blocked/critical rows are
      the only red; verdict/severity as `.aug-lbl` + mark.
- [ ] `components/BriefingPanel.tsx` — headline-signal at full width (amber), supporting
      signals as a ruled index, coverage as neutral bars, held-back footnote.
- [ ] `components/PlaybookPanel.tsx`, `HistoryPanel.tsx` / `HistoryDetailPanel.tsx`,
      `CanvasBrowser.tsx` / `CanvasWorkspace.tsx`, settings
      (`OrgSettingsPanel.tsx` / `SystemPanel.tsx` / `ConfigurePanel.tsx`) — apply tokens
      + primitives; underline tabs; `.aug-kv` for key/value detail.

---

## 4. Verification (run after every screen)

```bash
cd web
npx tsc --noEmit            # MUST stay 0 errors
npm run dev                 # sweep the screen in BOTH themes
```

- Toggle dark ↔ light (the app's theme switch / `[data-theme]`) — nothing should look
  broken in either; amber darkens to `#B5781A` on the light "broadsheet" automatically.
- **Find anything that didn't re-skin** (hard-coded colour):
  ```bash
  grep -rnE "#[0-9a-fA-F]{3,6}|rgb\(" web/components/<File>.tsx
  ```
  Replace each literal with the nearest token from §1.
- Lint the file you changed: `npx eslint components/<File>.tsx` (note: TrustReceipt has
  one *pre-existing* `react-hooks/static-components` warning — not yours; leave it).

## 5. Accessibility & constraints
- **Do not** put amber on small body text on dark — keep body on `--t1`/`--t2`. Amber is
  for fills, markers, headings, key figures.
- Keep the focus ring (`--bfocus`, now amber) visible on all interactive elements.
- `prefers-reduced-motion` is already handled in `globals.css`; don't add motion that
  ignores it. Live markers must degrade to static.
- Never change API calls, data shapes, props, or component behaviour. Visual only.

## 6. Definition of done (per screen)
1. `tsc --noEmit` clean.
2. No raw hex / rgb() left in the file (charts use `--chart-*`).
3. Renders correctly in dark **and** light.
4. Obeys the §1 colour rules — one accent, red only for critical, the rest neutral.
5. Uses the §2 primitives where applicable instead of bespoke markup.
6. Visually consistent with `design-mockups/aughor-console-direction.html`.
