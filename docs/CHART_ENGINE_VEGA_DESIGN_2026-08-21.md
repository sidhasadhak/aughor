# The Fourth Chart Engine — ECharts → Vega-Lite design

**Status:** **structure agreed 2026-08-21** — curated / escape / raw, all Vega family · **Author:** design pass with Claude
**Decision owner:** @sidhasadhak

---

## 0. Verdict

Migrate — but as a **spec-first** migration, not a renderer swap, and to **Vega-Lite**, not
`vega/vega`.

1. **DECIDED.** A three-tier control ladder — **curated → escape → raw** — entirely within the
   Vega family. Vega-Lite is the authoring default; raw Vega is the per-chart escape. ECharts is
   retired completely; there is no second engine.
2. Keep the seam that already exists (`resolveOption.ts`) and change the *target language*,
   not the architecture.
3. Gate the whole programme on a 2–3 day **theme-parity spike**. If a re-themed ECharts
   looks as good as Vega-Lite, stop there and take the cheap win — that is a legitimate,
   successful outcome of this doc.
4. Do not port a chart type that the ledger has never seen.

---

## 1. Two facts that reframe the request

### 1.1 Aughor has already run Vega-Lite, and removed it

The engine history is **Observable Plot → Vega-Lite → ECharts**
(`docs/archive/FEATURES_full_2026-06-29.md:720`). The move off Vega-Lite happened on
**2026-06-20**:

| Commit | What it did |
|---|---|
| `b275e2d` | Added the ECharts engine — "the Vega-Lite replacement (Superset-aligned)"; token theme, pure builders, `/chart-lab` harness |
| `3175000` | Flipped `Chart.tsx` to ECharts — same public props, 9 consumers untouched |
| `aa69c8b` | Deleted `VegaChart.tsx`; dropped `vega`, `vega-lite`, `vega-embed` |

Two reasons are recorded, and only one of them was about Vega:

- **Superset alignment.** `docs/SUPERSET_INTEGRATION.md` frames ECharts as the
  Superset-aligned choice. This was a strategic bet, not a defect in Vega.
- **Theming was fragile.** `b275e2d` replaced "the fragile `remapLegacyColors` hex-walk".
  Colours were being retrofitted by walking a produced spec and substituting hex values.

That second reason is the one that matters, because **it was a self-inflicted implementation
choice, not a property of Vega-Lite.** Vega-Lite has a first-class `config` object for exactly
this. Any return that re-creates a hex-walk will fail the same way.

### 1.2 The current engine has a theming regression Vega would fix

From `web/components/charts/echarts/theme.ts:11`, in the codebase's own words: ECharts'
canvas renderer writes the font string into the 2D context, which **does not resolve
`var(--font-ui)`** — so a concrete font stack is baked in and must be kept in sync by hand.
The comment notes Vega could use the CSS variable directly because it renders SVG.

That is a real, documented regression the previous migration accepted.

---

## 2. Vega vs Vega-Lite

| | **Vega** (`vega/vega`) | **Vega-Lite** |
|---|---|---|
| Level | Low-level runtime + grammar | High-level grammar that **compiles to Vega** |
| You describe | data, transforms, scales, axes, marks, signals, event streams | data, `mark`, `encoding` (x / y / color / size) |
| A bar chart | ~50 lines of JSON | ~8 lines |
| Inference | none — you declare every scale, axis, legend | scales, axes, legends, types inferred |
| Interaction | signals + event streams (manual) | `params` / selections (declarative) |
| Exotic layouts | treemap, force, custom marks — yes | no; drop to Vega |
| Ships as | `vega` | `vega-lite` **+** `vega` |

**The link in the request points at the runtime.** Adopting `vega/vega` alone would be a
downgrade in authoring ergonomics versus ECharts' option objects — more verbosity for the
same picture. The layer worth having is Vega-Lite. Databricks-style chart specs are
Vega-Lite specs; the runtime underneath is an implementation detail.

**Decision: author Vega-Lite, and keep a documented escape to raw Vega per chart.**

### 2.1 How Databricks actually does it

AI/BI dashboards ship a **curated set of built-in visualization types**. Beyond that set, a
**Vega-Lite specification editor** accepts a hand-written Vega-Lite JSON spec — that is how a
gauge, radar, bullet, sunburst or radial chart gets made. Not low-level Vega. Vega-Lite.

Nor is that a coincidence: **Kanit Wongsuphasawat, a co-creator of Vega-Lite, works on
visualization at Databricks** and authored their 2021 post "Building the Next Generation of
Visualization Tools at Databricks". (That post sets out a vision and does not itself name a
library — the Vega-Lite fact comes from the AI/BI custom-visualization docs.)

So the architecture behind the look you admire is **constraint at the default layer plus one
true escape hatch** — not maximum control everywhere. Vega-Lite's own pitch, quoted in that
post, is that it takes "a dozen lines of code instead of hundreds in D3.js". Its value
proposition is *less* control, converted into leverage and consistency.

### 2.2 The control ladder

Maximum control applied to *every* chart is how chart systems get worse. Twenty-three builders
drift apart, each one locally reasonable, and the set stops looking like one product.
**Uniformity is what reads as professional.** Singularity is what you want in one or two places,
deliberately.

So put control on a ladder, chosen per chart:

| Tier | For | You write | Control |
|---|---|---|---|
| 1 · Curated | the six types that are 99% of traffic | `resolveSpec()` emits the encoding | Defaults enforced, consistency guaranteed |
| 2 · Escape | the exceptional chart | a hand-authored Vega-Lite spec, stored on the artifact | The full Vega-Lite surface |
| 3 · Raw | a chart that must be singular | a Vega spec or a custom mark | Unlimited |

**The ladder only runs downward.** Vega-Lite compiles to Vega, so `vl.compile(spec)` hands you
the Vega spec for tier 3 whenever a chart earns it — per chart, without changing engines.
Choosing `vega/vega` globally throws that property away: there is no path back up, and every
ordinary bar chart pays tier-3 verbosity forever.

### 2.3 Where "perfect" is actually gated today

The renderer's expressive ceiling is not the binding constraint. **99% of what Aughor draws is
bars and lines**, and ECharts, Vega-Lite and D3 all draw those perfectly. What limits how well a
chart *delivers its message* sits one layer up — and all three are findings from §4:

1. The chart type is inferred client-side at render time and never recorded.
2. The exhibit semantics — severity, sign, reference lines, subject emphasis — are computed,
   sent, and dropped before they are stored.
3. The resolved chart is unserializable, so no chart can be reviewed, diffed or corrected.

A chart is meaningful because the right thing was encoded, not because the renderer could draw
anything. **Spend the control there first** — it is the same standard, aimed at the layer that
is actually failing it.

---

## 3. What actually produces the "Databricks look"

Separate two things that get conflated, because they have wildly different prices:

| | **Look** | **Grammar** |
|---|---|---|
| What it is | type scale, muted palette, hairline axes, no gradients, direct labels, generous plot padding | declarative encodings, transforms, selections, a serializable spec |
| Where it lives | a theme object | the chart engine + the layer above it |
| Cost | days | weeks |
| Engine-dependent? | **No** — ECharts can be themed to match | Yes |

Vega-Lite's defaults are closer to that restrained look out of the box, which is why the
association is real. But it is an association, not a causal link. PR #367 ("Match Databricks")
already moved the token layer in this direction.

**This is why §6 Phase 1 exists.** Build the same six charts both ways, side by side, and
look at them. If the difference is theme, buy the theme.

---

## 4. Evidence from the live ledger

Measured read-only against `data/system.db` on 2026-08-21. **32,721 artifacts** total.

### 4.1 What Aughor actually charts

703 artifacts carry a `chart_type`. Every one is a `chat_answer`.

| chart_type | count | share |
|---|---:|---:|
| `bar_horizontal` | 372 | 52.9% |
| `auto` (deferred to client inference) | 195 | 27.7% |
| `line` | 55 | 7.8% |
| `multi_line` | 27 | 3.8% |
| `counter` | 22 | 3.1% |
| `bar` | 18 | 2.6% |
| `combo` | 5 | 0.7% |
| `pie` | 4 | 0.6% |
| `stacked_bar` | 2 | 0.3% |
| `scatter` | 1 | 0.1% |
| `table` / `{}` | 2 | 0.3% |

**Six types are ~99% of everything the product has ever charted.**

Never persisted, not once: `sankey`, `treemap`, `funnel`, `gantt`, `choropleth`, `point_map`,
`waterfall`, `pareto`, `boxplot`, `histogram`, `heatmap`, `delta_bar`, `small_multiples`,
`line_forecast`.

The frontend carries **23 builders across 1,403 lines** to serve that distribution.

### 4.2 Two structural findings

**Findings persist no chart hint at all.** Across the last 2,000 `finding` artifacts, zero
contain `chart_type`, `chart_config`, `exhibit`, or `viz`. A finding stores `sql`, `measures`,
`dimensions`, `confidence`. The chart type is inferred **client-side at render time** by
`chartTypeInference.ts` (402 lines). Whatever engine renders it, that inference is the real
chart-selection system — and it is invisible to the ledger.

**`chart_config` is computed and then thrown away.** `investigations.py:2625` calls
`quick_exhibit(...)` and merges the result into `answer.chart_config["exhibit"]`. It reaches
the browser. It is then **persisted 0 times out of 700** `chat_answer` artifacts — the
artifact keeps `chart_type` and drops `chart_config` entirely.

Consequences:

- The `exhibit` grammar (`web/components/charts/exhibit.ts`, `aughor/agent/exhibit.py`,
  `tests/unit/test_chart_exhibit.py`) — severity ramps, sign colouring, reference lines,
  subject emphasis — **has never been recoverable from a stored answer.**
- **You cannot re-render a past answer's chart as it was shown.** For a product whose thesis
  is evidence and provenance, that is the most consequential finding in this document.
- It is also **engine-independent**: it is worth fixing whether or not Vega-Lite ever lands.
  Vega-Lite simply makes the fix natural, because a Vega-Lite spec *is* JSON, while a
  resolved ECharts option is not — **43 function-valued fields** (`formatter: (v) => …`,
  `renderItem`) across `builders.ts` and `resolveOption.ts` make today's resolved chart
  unserializable by construction.

### 4.3 Limits of this measurement

It counts charts **persisted**, not charts **viewed**. Dashboards (`_body`) and findings
render types this count cannot see, and `auto` hides its resolved type. A second pass over
`session_events` would measure what was actually looked at. Row counts are unavailable —
persisted charts do not carry their data, so the p95-rows question that governs renderer
performance is **still open**.

---

## 5. Target architecture

```
backend intent                    one pure resolver              three consumers
─────────────                     ─────────────────              ───────────────
chart_type                                                  ┌──▶ browser: vega-embed (canvas)
chart_config  ──────────────▶  resolveSpec(intent)  ────────┼──▶ print:   vega → SVG (node)
exhibit                        → VegaLiteSpec (pure JSON)   └──▶ ledger:  the spec, persisted
VizConfig (user overrides)
```

The seam already exists and is already correct. `resolveOption.ts` is one pure function —
no React, no DOM — shared by the browser and the headless PDF renderer, so "the PDF draws
exactly the chart the user was just looking at". **Keep that. Change only what it emits.**

### 5.1 Contracts that must survive unchanged

| Contract | Where | Why it constrains the design |
|---|---|---|
| `VizConfig` (18 optional fields) | `charts/vizConfig.ts` | Crosses the wire, persisted in `DashboardCard.render` and `viz_configs`. Absent-means-default; an untouched chart must still persist nothing. |
| `ChartType` vocabulary | `aughor/agent/chart_vocab.py` | Backend and frontend agree on names; `tests/unit/test_chart_vocab_parity.py` enforces it. |
| `exhibit` semantics | `charts/exhibit.ts`, `agent/exhibit.py` | `color.mode` (neutral/categorical/severity/sign/continuous), `ref_lines`, `quadrant`, `emphasis`, `order`. |
| Palette gate | `web/scripts/check-chart-palette.mjs` | Parses `echarts/palette.ts` and CVD-validates. **Rewriting this is in scope, not optional.** |
| Print path | `web/scripts/chart-ssr-entry.ts` → `aughor/export/chart_ssr.bundle.mjs` (825 KB) | Node subprocess, stdin JSON → stdout SVG. |

### 5.2 What changes

- `resolveSpec(intent) → VegaLiteSpec` replaces `resolveChartOption(...) → EChartsOption`.
- Theme becomes a Vega-Lite **`config`** object built from the same CSS tokens — injected
  once at compile, never hex-walked into a produced spec. SVG output resolves `var(--font-ui)`
  natively, closing the baked-font-stack regression.
- The resolved spec is **persisted onto the artifact**, closing the provenance hole.
- Hand-rolled maths (histogram bucketing, Pareto cumulative %, boxplot quartiles, forecast
  bands) becomes declarative `transform` — `bin`, `aggregate`, `window`, `regression`, `loess`.

### 5.3 What must NOT change

Vega-Lite makes dual-axis charts easy via `resolve.scale.independent`. Aughor's own exhibit
grammar already retired combo charts ("one measure per exhibit" —
`aughor/agent/prompts.py:245`). **Do not let the new grammar's convenience reopen a decision
the product already made correctly.**

---

### 5.4 The ladder in the architecture

One family, three tiers, one runtime. ECharts is retired completely — the exotic types move to
tier 3 or are deleted (Phase 5).

| | **Tier 1 · Curated** | **Tier 2 · Escape** | **Tier 3 · Raw** |
|---|---|---|---|
| Produced by | `resolveSpec(intent)` | a hand-authored Vega-Lite spec | a Vega spec or custom mark |
| Stored as | intent **+** resolved spec as a receipt | the spec, verbatim | the spec, verbatim |
| Re-resolvable? | Yes — improves when the resolver improves | No — frozen at authoring | No |
| Editor | the full `VizConfig` field editor | the spec editor | the spec editor |
| Validated by | the resolver's own types | the Vega-Lite JSON schema | the Vega JSON schema |

**Three rules make the ladder work:**

1. **The theme is never baked into a stored spec.** It is injected as `config` at render time, so
   a tier-3 spec authored in March still follows today's tokens and still flips dark/light. A spec
   carrying its own hex values is the June failure wearing a new hat (§1.1).
2. **Ejecting is explicit and one-way.** `vl.compile(spec)` produces the tier-3 starting point
   from a tier-1 or tier-2 spec. There is no automatic path back up — returning discards the hand
   edits, and the UI must say so before it happens.
3. **A chart records its own tier.** `chart_spec: { tier, spec, source: "resolved" | "authored" }`.
   Tier 1 is re-resolved from intent at render; tiers 2 and 3 render verbatim. Without the marker,
   a resolver improvement would silently overwrite someone's hand-authored chart.

Tier 2 is also the natural target for a **model-authored** chart: Vega-Lite has a JSON schema, so
a proposed spec can be **validated before it renders** — a guard the current option-object path
cannot have at all.

## 6. Phasing

Every phase ends with the old path **deleted** or a **dated decision to keep it**. No phase
begins before the previous one's gate is met.

### Phase 0 — Measure · DONE
This document. Result: six types are 99% of traffic; the four "Vega-Lite can't do that"
types have zero usage; `chart_config` is never persisted.

### Phase 1 — Theme-parity spike · 2–3 days · **GATE**
Render the six real types both ways, side by side, in `/chart-lab`, both themes, with a
token-built Vega-Lite `config`.
**Gate:** Vega-Lite is visibly better, or indistinguishable.
**Kill:** if a re-themed ECharts matches it, stop the programme and ship the theme. Cheap win.

### Phase 2 — Renderer behind a flag · 1–2 weeks
`resolveSpec()` for `bar`, `bar_horizontal`, `line`, `multi_line`, `counter`, `pie`, plus the
`auto` inference path. `AUGHOR_CHART_ENGINE=vega|echarts` selects the engine; both render
from the same intent.
**Harness:** replay all 703 persisted charts through both engines and diff screenshots.
**Gate:** no visual regression on the replay set; p95 render time within 20% of ECharts.

### Phase 3 — Persist the spec · 3–5 days
Stop dropping `chart_config`. Write the resolved Vega-Lite spec onto the artifact.
**Gate:** a chat answer from 2026-07 re-renders byte-identically to what was stored.
*(Worth doing even if Phase 1 kills the migration — see §4.2.)*

### Phase 4 — Earn the grammar · 1–2 weeks
Move the hand-rolled transforms into the spec. Add selections **only if** cross-filtering is
on the roadmap — it is the one capability that is genuinely grammar-only.

### Phase 5 — Retire ECharts · ~1 week
One family, one runtime. Whichever of `sankey`, `treemap`, `funnel` and `gantt` survive a usage
decision get **tier-3 Vega specs**; the rest are deleted. `chart_ssr.bundle.mjs` is rebuilt on
`vega` → SVG, replacing the 825 KB ECharts bundle.
**Gate:** `echarts` and `zrender` are gone from `web/package.json`, and `/chart-lab` renders every
surviving type at its declared tier.

---

## 7. Risk register

| Risk | Evidence it is real | Mitigation | Kill criterion |
|---|---|---|---|
| The look does not actually improve | The "Databricks look" is largely theme (§3) | Phase 1 spike before any spend | Phase 1 gate |
| Performance at high row counts | Vega's dataflow + SVG is slower than ECharts canvas; **p95 rows is unmeasured** (§4.3) | Canvas renderer; measure from `session_events` first | p95 render > 1.2× ECharts |
| Two engines forever | `@observablehq/plot` is still a declared dependency with **zero importers**, ~3 months after Plot stopped being the engine | **Single-family mandate (decided 2026-08-21):** tier 3 replaces the ECharts fallback. Every phase deletes or dates its predecessor | `echarts` still in `package.json` after Phase 5 |
| Palette gate rewrite | `check-chart-palette.mjs` parses `echarts/palette.ts` by name | Rewrite as part of Phase 2, not after | Gate disabled at any point |
| Peer-dependency conflict | ECharts was installed with `--legacy-peer-deps` due to a pre-existing antd/react-19 conflict (`b275e2d`) | Check the React wrapper before Phase 2 | — |
| Repeating the 2026-06 failure | A hex-walk over a produced spec (§1.1) | Theme via `config` only; ban post-hoc colour substitution in review | Any hex-walk in the diff |

---

## 8. Decisions

1. ~~Vega-Lite as the authoring language~~ **DECIDED 2026-08-21** — three-tier ladder,
   Vega-Lite default, raw Vega as the per-chart escape.
2. ~~Keep ECharts for the exotic four?~~ **DECIDED 2026-08-21** — no. One family. Survivors get
   tier-3 Vega specs; the rest are deleted. *Still open:* which of the four survive.
3. **Is cross-filtering on the roadmap?** It is the strongest grammar-only argument. If no,
   Phase 4 shrinks to the transforms.
4. **Persisting specs**: a new field on the existing artifact, or a `chart_spec` artifact kind?
5. **Cheap path first?** Re-theme ECharts, look at it, and re-decide — Phase 1 answers this
   either way, but the order matters if the goal is purely visual.

---

## Appendix — files in scope

| File | Lines | Fate |
|---|---:|---|
| `web/components/charts/echarts/builders.ts` | 1,403 | Replaced by spec builders; ~6 types first |
| `web/components/charts/resolveOption.ts` | 392 | Retargeted — the seam survives |
| `web/components/charts/chartTypeInference.ts` | 402 | Unchanged; engine-independent |
| `web/components/charts/VizEditorPanel.tsx` | 397 | Rebound to spec fields |
| `web/components/charts/exhibit.ts` | 175 | Unchanged; semantics preserved |
| `web/components/charts/echarts/theme.ts` | 175 | Replaced by a Vega-Lite `config` |
| `web/components/charts/columnRoles.ts` | 161 | Unchanged |
| `web/components/charts/echarts/EChart.tsx` | 156 | Replaced by a Vega wrapper |
| `web/scripts/chart-ssr-entry.ts` | 114 | Retargeted to `vega` → SVG |
| `web/scripts/check-chart-palette.mjs` | — | Rewritten for the new palette source |
| `aughor/export/echarts.py` | 95 | Renamed / retargeted |
| `aughor/export/chart_ssr.bundle.mjs` | 825 KB | Rebuilt, expected smaller |
