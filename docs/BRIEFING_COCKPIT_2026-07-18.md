# The Self-Explaining Briefing — Argument Graph + Co-authored Cockpit

**Design doc · 2026-07-18 · Status: Slice 0 + Slice 1 BUILT & live-verified on branch
`2026-07-18-briefing-cockpit` (not pushed); Slices 2–4 pending — see §10.**
Build is gated slice-by-slice in §10; nothing here ships until a v1 slice is picked.

All file:line references below were verified against the current tree on 2026-07-18. Where a
claim depends on machinery that does *not* exist yet, it is called out as a **GAP**.

---

## 0. TL;DR

Turn the Briefing from a linear report into a **co-authored cockpit**: the explorer's findings
stay, but the reader can (a) read the briefing as an interactive **argument graph** where the
verdict, its drivers, and their evidence are nodes joined by typed edges, and (b) pin their own
**cards** — a tracked topic, a KPI, or a chart — that live alongside the findings and refresh over
time.

Three observations make this cheap to *start*:

1. **The argument graph is already computed and then thrown away.** The explorer emits typed
   finding→finding edges (`share / tension / concentration / confound / chain`, plus `drill_of`)
   and never reads them back — they die in the state blob. Un-orphaning them is mostly wiring.
2. **A user "card" is the inverse of a finding** — a standing question the user declares and asks
   Aughor to keep answering. We already answer, ground, guard, chart, and monitor questions; the
   card points that machinery at a human-chosen question.
3. **The three "create a chart/KPI" features you asked for are one primitive with three doors** —
   from an insight, from Query Builder, and authored inline. Build the primitive once; the "mega"
   inline-authoring feature becomes the cheapest of the three because it ships last.

North star, and the line we must not cross: **the dashboard that explains itself.** Every number is
one click from the finding that explains its movement, grounded and trust-guarded. The moment a card
is a dumb tile with no link to *why*, we've built a worse Looker. That connection is the product.

---

## 1. Motivation & the pivot

Leadership wants two things a plain dashboard and a plain briefing each half-serve: **trends / grip
over time** (how is the business doing?) and **the narrative** (what changed this cycle and why?).
A BI dashboard gives dead numbers with no explanation; a narrative briefing gives explanation with
no standing scorecard. Aughor's differentiator — grounded, trust-guarded, *explained* numbers —
lets us do the thing neither category does: a scorecard where every tile is backed by evidence and
wired to the analysis that explains its delta.

**Two layers on one surface** (this resolves the identity tension — an argument is curated and
cycle-specific, a dashboard is stable and persistent):

- **Standing layer (cockpit):** user-authored KPI/chart cards that persist and refresh — the grip
  over time.
- **Narrative layer (argument):** the explorer's cycle findings + the argument graph — what changed
  and why, this cycle.
- **They are wired together:** a KPI card links to the findings explaining its move; a finding
  references the KPIs it moved. The user's **watch cards** are the bridge (a declared topic that is
  both standing *and* narrative).

**Non-goal:** rebuilding a BI tool. If we drift into "chart grid with no explanation," we've lost.

---

## 2. The three ideas, as one initiative

| Idea | One-line | Relationship |
|---|---|---|
| **A. Argument-graph lens** | Render the briefing as a node+edge argument map (React Flow) | The narrative layer, made structural |
| **B. Co-authored cards** | User-authored watch / KPI / chart / note cards that ground & refresh | The standing layer + the human half of the graph |
| **C. Three authoring doors** | Create a card from an insight, from Query Builder, or inline | How B gets populated |

The architectural claim that makes this tractable: **A and B share one data model** — a graph of
typed nodes and edges — and **B's three doors produce one Card object.** We are not building three
features; we are building one primitive (the Card), one edge model, and one render surface (the
graph/cockpit), with several entry points and reuse of machinery that already exists.

---

## 3. What already exists (verified reuse map)

This is the credibility section: the feasibility grades below rest on it. Paths verified 2026-07-18.

### 3.1 The big enablers

- **The argument graph is emitted then orphaned.** Synthesis operators
  `share/tension/concentration/confound/chain` are defined at `aughor/explorer/synthesis.py:31`
  (`OPERATORS`; eligibility `_eligible_operators:101`). A synthesized insight persists its edge:
  `composition_type` + `parents:[id,id]` at `aughor/explorer/agent.py:3878-3879`, and drill children
  carry `drill_of` at `agent.py:3548`. The state is `json.dumps`-ed opaquely at
  `aughor/explorer/store.py:50`. **Grep confirms zero read sites** for `composition_type`
  (as a stored key), `parents`, or `drill_of` — the edges exist in data and are never traversed,
  serialized, or rendered.
- **The prose→finding edge is already serialized:** the `citations` list in
  `aughor/knowledge/briefing.py` (built ~`:411-422`) maps each `[N]` prose marker to a finding id;
  the front end already parses and renders it (`BriefingPanel.tsx` `BriefProse`).
- **A ready-made card body exists:** `web/components/charts/ResultChartCard.tsx:123`
  (`{columns, rows, title, chartType, chartConfig, custom, heightScale, onSelect}`) with an internal
  chart/table/pivot toggle — no persistence prop today, but it is the natural "card" a pin produces.
- **The chart engine is one seam:** `web/components/Chart.tsx:98-431`. Its props
  (`columns, rows, chartType, chartConfig, custom, columnUnits, exhibit`) ARE the de-facto render
  spec a card carries. Export mirror in `aughor/export/charts.py` (kept in sync with `exhibit.ts`).
- **Drill / evidence wiring keys off `insight.id`:** `_build_origin_finding`
  (`aughor/routers/investigations.py:2252`, raw-seed fallback), `get_insight_receipt`
  (`aughor/routers/exploration.py:1089`), `ground_briefing_number` (`exploration.py:1117`),
  signed receipts (`aughor/trust/receipt.py`). A graph node's click-actions are these handlers.
- **The explorer-steering feedback loop is fully closed:** `record_drill`
  (`aughor/overview/drills.py:51`, captured at `routers/query.py:896`) →
  `load_priors` (`drills.py:72`) → `build_overview(priors=…)` (`aughor/overview/build.py:664`,
  read at `routers/investigations.py:3387-3400`). A declared watch is a strong prior for this loop.

### 3.2 Reuse map by subsystem

| Need | Reuse | Location | Notes |
|---|---|---|---|
| Persist a card's query | `SavedQuery` | `aughor/savedquery/models.py:14`, store `store.py` | **GAP:** persists `id, connection_id, name, sql, spec` only — **no refresh/schedule** |
| Governed metric / KPI | `MetricDefinition` | `aughor/semantic/metrics.py:39`; `build_metrics_block:464` | carries target/warning/critical thresholds + governance lifecycle |
| KPI strip (briefing) | `IndustryKpiStrip` | `web/components/brief/IndustryKpiStrip.tsx:295` | driven by **business-profile `north_star_metrics`** (`value_sql` + `chart_sql`) — a *different* store from `MetricDefinition` |
| Chart render | `Chart` / `EChart` / builders | `web/components/Chart.tsx`; `charts/echarts/` | ECharts only (Vega removed, dead refs) |
| Encoding overlay | `ExhibitSpec` | `web/components/charts/exhibit.ts:33` | **not** the render spec — just color/ref-lines/quadrant/order over a chart |
| Existing dashboard region | `BriefingDashboard` | `web/components/brief/BriefingDashboard.tsx:130` | 2-col grid of AI `FindingCard`s; **no user-card container yet** |
| Query Builder charting + save | `QueryBuilder` | `web/components/QueryBuilder.tsx:938` (chart), `:1441` `buildSpec()`, `:1668` Save | "Pin to dashboard" hooks beside Save |
| Per-finding action menu | `FindingActions` | `web/components/BriefingPanel.tsx:763-901` | Monitor/Promote/Share/Evidence/Dismiss; "Promote"=org intel, **not** dashboard |
| Metric authoring UI | `MetricsPanel` | `web/components/MetricsPanel.tsx` | full CRUD + governance (draft→approved→deprecated) |
| SQL trust guards | `execute_guarded` | `aughor/sql/executor.py:123` | battery: fan-out `grain_guard.py:75`, join `join_guard.py:329`, ratio `ratio_grain.py:74`, E1 `trust_checks.py:93` |
| Trust plane (blockable) | `verify(...)` | `aughor/trust/__init__.py:43` | `trust.verify_live`-gated verdict |
| Unit/100× guard | `verify_finding` | `aughor/explorer/grounding.py:164` | **answer path, not `sql/`** |
| Monitor (graduation) | `Monitor` + create | `aughor/monitors/models.py:14`; `routers/monitors.py:145` | resolves `metric_name` OR `custom_sql` + thresholds; `reanchor_window` was built for briefing-finding monitors |
| Grounding receipt | dossier | `aughor/explorer/dossier.py:93` (`build_dossier`; `update_dossier:70`) | **not** `knowledge/dossier.py` (does not exist) |
| Graph engine | — | **greenfield** | React 19.2.4 / Next 16.2.6 / ECharts ^6.1.0; **no react-flow/xyflow/tldraw present** |

### 3.3 Gaps (net-new work, called out honestly)

1. **No refresh/schedule on `SavedQuery`** — the "living/trend" property needs a new field or store.
2. **No user-authored-card container** — `BriefingDashboard` renders AI findings only.
3. **Two metric stores** — profile `north_star_metrics` (KPI strip) vs governed `MetricDefinition`
   (MetricsPanel). A cockpit **bridges** them; it does not reuse one.
4. **User-card SQL is not auto-guarded** — monitor `custom_sql` only gets `_validate_custom_sql`
   (mutation/bind), lighter than `execute_guarded`. Cards must be routed through the guard battery
   explicitly.
5. **The argument-graph edges are orphaned** — they must be serialized through the domain-insights
   API into `BriefingData`, and densified for ordinary findings.
6. **The graph lib is greenfield** — React Flow (MIT) to be added.

---

## 4. Data model — the Card primitive + the Edge model

### 4.1 The Card

One object; watch / KPI / chart / note are configurations of it.

```
DashboardCard {
  id
  scope            # canvas | workspace | user   (governance + where it shows)
  source           # insight | query_builder | authored | watch
  title            # human label
  kind             # note | kpi | chart | watch
  query_ref        # FK → SavedQuery (the grounded SQL)   ── reuse savedquery/
  render {         # subset of Chart.tsx props (the render spec)
    chartType, chartConfig, custom, columnUnits,
    exhibit?       # optional ExhibitSpec encoding overlay
  }
  refresh {        # NEW — SavedQuery has none
    cadence        # brief_cycle | hourly | daily | manual
    last_run, last_value, prev_value   # for delta / trend
  }
  thresholds?      # optional → graduate to a Monitor
  provenance {     # receipt / lineage
    origin_finding_id?, receipt_ref
  }
  links[]          # finding ids this card explains / relates to  (edges)
  body?            # free text (for kind=note)
  author, created_at, updated_at
}
```

**Storage recommendation:** a **new `dashboard_cards` SQLite store** (mirroring `savedquery/` and
`monitors/`) that **references a `SavedQuery`** for the SQL rather than overloading `SavedQuery`.
Rationale: `SavedQuery` is connection-scoped with no refresh/render/scope/links, and is already used
by Query Builder for a different purpose; compose, don't overload. The card store adds refresh,
render, scope, links, and provenance.

**kind mapping:**

| kind | query | render | refresh | thresholds |
|---|---|---|---|---|
| note | — | text | — | — |
| kpi | scalar SQL | number (+delta/sparkline) | yes | optional |
| chart | grouped SQL | chart | yes | — |
| watch | resolved question | number/chart + "what's new" | yes | optional → monitor |

### 4.2 The Edge model

Nodes: `finding` (AI), `card` (human), `verdict` (the headline).

| Edge | Meaning | Source today |
|---|---|---|
| `chain` | causal ("drives") | `synthesis.py` operator (orphaned) |
| `tension` | trade-off | `synthesis.py` operator (orphaned) |
| `confound` | "headline is misleading" | `synthesis.py` operator (orphaned) |
| `concentration` | roll-up | `synthesis.py` operator (orphaned) |
| `share` | shared entity/join key | `synthesis.py` operator (orphaned) |
| `explains_why` | drill parent→child | `drill_of` (orphaned) |
| `cites` | prose claim → finding | `citations` (already serialized) |
| `relates_to` | **card ↔ finding** | **NEW** — entity/metric/table overlap |
| `supports` | driver → verdict | **NEW** — from impact ranking / narrator refs |

**Deterministic-first:** the operators and `drill_of` are computed from real join keys / composition,
not an LLM drawing arrows — that is what makes the graph *trustworthy*, not decorative. `relates_to`
and `supports` should likewise start deterministic (entity/metric/table overlap, impact ranking);
use an LLM only to densify where structure is genuinely latent in prose.

---

## 5. Feature A — the argument-graph lens

**Engine: React Flow (`@xyflow/react`, MIT).** It is purpose-built for node+edge graphs, MIT
(no tldraw watermark / per-deployment license / telemetry that would break Aughor's Apache-2.0,
fully-local, self-hostable posture), and lets a node hold arbitrary React (a chart/table inside a
node). Greenfield — no graph lib present today.

**Two-part work:**

1. **Un-orphan (small).** Serialize the existing `parents` / `composition_type` / `drill_of` +
   `citations` through the domain-insights API into `BriefingData`, then render. The edges already
   exist; they die at the API boundary (`explorer/store.py` → routers → client).
2. **Densify (medium).** The typed edges cover only synthesized findings + drills — a sparse subset.
   The everyday relationships (headline→driver, loss-lens leakage↔utilization, "caveats") are latent
   in impact-ranking and prose. Emit edges for ordinary findings by extending the deterministic
   `patterns.py` / `synthesis.py` operators over the briefing top-N, or by typing the narrator's
   cross-references at synthesis time. Deterministic-first; LLM only where unavoidable.

**Node design:** finding node = title + a KPI/chart inside (reuse `ResultChartCard` body); verdict
node = the headline; card node = human-authored, visually distinct. **Layout:** hierarchical
(dagre or elkjs), verdict on top, evidence below. **Progressive disclosure:** start collapsed to
verdict + top ~3 drivers; expand on demand — a graph is only more consumable than prose if it is not
a hairball.

**Adaptive & non-destructive:** render the graph when structure warrants (cross-domain synthesis),
fall back to linear otherwise. It is a **lens**, not a replacement — the linear brief stays the
default fast-read and the export/print/a11y path (React Flow → PNG/SVG for exports). Node clicks
reuse the existing drill/evidence/monitor handlers (`FindingActions` via the `renderActions` prop).

---

## 6. Feature B — co-authored cards (watch / KPI / chart / note)

**Lifecycle:** create → ground → fill/refresh → place → graduate → own.

**The refresh ladder (how a card stays informed) — three existing engines, a maturity progression:**

1. **Re-answer each cycle.** The card holds a grounded query; each brief cycle re-runs it and shows
   current value + delta + a one-line read, carrying the same receipt a finding does. Reuses the
   `ask`/resolve grounding + saved-query rerun. **Needs the new `refresh` field** (§3.3 gap 1).
2. **Steer the explorer.** A declared topic becomes a prior that biases what Aughor explores —
   exactly the closed loop at `overview/drills.py` + `build_overview(priors=)`; a watch is a louder
   signal than a click. Now the card also catches things the user did not ask for precisely.
3. **Graduate to a monitor.** With a metric + threshold, POST the card's `custom_sql` + thresholds
   to `/monitors` (`routers/monitors.py:145`); `reanchor_window` (built for briefing-finding
   monitors) slides the frozen date window. Now it is proactive push, not a refreshed slot.

**note vs watch vs kpi/chart:** a **note** is free text (inert, human opinion — trivial, an
annotation node; style it distinctly so nobody mistakes a hunch for a measurement). A **watch** is a
tracked metric with delta/alerting. A **kpi/chart** is a pinned metric render. All are one Card.

**Trend depth:** reuse `GroundedNumber` / `Sparkline` / `seriesTrend` and the `IndustryKpiStrip`
pattern (`value_sql` for the scalar, `chart_sql` for the series). "Grip over time" wants the
sparkline; it is cheap when the card's query carries a time dimension.

---

## 7. Feature C — the three authoring doors

| Door | How | Reuse | Grade |
|---|---|---|---|
| **1. From an insight** | Extend `FindingActions` with "Pin to dashboard" → clone the finding's grounded SQL + render into a Card | `origin_finding`/`dossier`, `Chart` props, `ResultChartCard`, `FindingActions` | **Easy — do first** |
| **2. From Query Builder** | "Pin to dashboard" beside Save (`QueryBuilder.tsx:1668`) → persist query + chosen render as a Card | `buildSpec()`, `createSavedQuery`, `InvestigationChart` (already renders) | **Easy / medium** |
| **3. Inline on the briefing** ("mega") | Metric/dimension picker → live `Chart` preview → save as Card | `MetricsPanel` + semantic metrics + `north_star`, `Chart` preview | **Medium — ships last, cheapest by then** |

Door 1 is zero-ambiguity (the SQL comes from the finding). Door 3's feared complexity is real but
bounded: it is assembling existing parts (metric picker + chart preview + the Card store), and by the
time it is built the primitive, persistence, refresh, and guarding already exist from Doors 1–2.

---

## 8. Trust, grounding & governance

- **Guard user SQL — a requirement, and a selling point.** Today card/monitor SQL is *not* run
  through the full battery (only `_validate_custom_sql`). Route every Card's SQL through
  `execute_guarded` (`sql/executor.py:123`) and/or the Trust plane `verify` (`trust/__init__.py:43`),
  plus the unit/100× check on the answer path (`explorer/grounding.py:164`). Result: the only
  cockpit that refuses to show a fabricated or mis-grained KPI. A user pinning a bad join gets the
  same guard treatment as an AI answer.
- **Grounding/receipt.** Every measured Card carries a signed receipt (`trust/receipt.py`) resolved
  through the origin-finding / `get_insight_receipt` path. Notes are opinion — style them so.
- **Refresh cost / staleness.** No schedule field exists; the Card store adds a per-card cadence.
  Use the prewarm/cache machinery; display honest staleness ("as of last cycle").
- **Scope / RBAC.** canvas vs workspace vs user; RBAC gates who pins to a shared/leadership
  dashboard.

---

## 9. Risks & non-goals

1. **Don't rebuild BI.** North star = explains-itself; every card links to its "why."
2. **Graph hairball.** Adaptive lens + progressive disclosure + keep linear as default.
3. **User-authored wrong numbers.** Guards are mandatory, not optional.
4. **Two metric stores.** Bridge `north_star_metrics` and `MetricDefinition`; do not fork a third.
5. **Scope creep.** This is one initiative but many slices — ship the gated order, not the vision.

---

## 10. Gated build order (leverage-gate: build → wire → test → verify on the real path)

Each slice is independently shippable, flag-gated, and verified on a real briefing before the next.

- **✅ Slice 0 — the spine. DONE** (`975e50f` · `0b91d60` · `f627344` · `b4db3a1`). New
  `dashboard_cards` store + CRUD `/cards` + **Door 1** (`POST /cards/pin-insight`) + `/run`
  (guard-on-read) + the "Pin" action in `FindingActions` + the `PinnedCards` region.
  *Verified live:* pinned real findings on the luxexperience briefing; a finding whose SQL errored
  (`SUM` over a VARCHAR) was **refused with a 422** — the guard guarantee, on write.
- **✅ Slice 1 — grip over time. DONE** (`743e63e`). Trend sparklines (intra-metric via
  `seriesTrend`/`Sparkline` for time-shaped findings; a bounded cross-cycle value history for
  scalars) + a per-card **Refresh** button. *Verified live:* a "GMV by month" card renders a
  60-month sparkline reading `565,875  −3.9% MoM`.
- **Slice 2 — Door 2.** Query Builder "Pin to dashboard." *Proves:* the second door on the same Card.
- **Slice 3 — argument-graph lens.** Un-orphan the edges + render the map as a React Flow lens
  (linear stays default). *Proves:* the narrative-as-graph, reusing drill wiring.
- **Slice 4 — Door 3 + connective tissue.** Inline authoring + `relates_to` edges (card↔finding) +
  watch/alert graduation. *Proves:* the full co-authored cockpit.

**Build notes (2026-07-18):** (a) tabular findings render "N rows" — a *trend* card needs a
scalar or a time series; rendering tabular cards as charts/tables (reuse `ResultChartCard`) is a
follow-up. (b) A **pre-existing** dev-only React warning ("useEffect changed size") fires from an
*unchanged* briefing child component (not introduced by the cockpit work — `git diff main` on
BriefingPanel added only `handlePin`'s dep array; bounded StrictMode-amplified load burst, not an
infinite loop) — worth a separate fix. (c) Demo cards live on the luxexperience briefing in
`data/dashboard_cards.db` (gitignored runtime); removable via each card's Remove.

---

## 11. Open decisions (need a call before spec'ing Slice 0)

1. **Card scope v1 default** — canvas (this brief's cockpit), workspace (shared leadership
   dashboard), or user (my cards follow me)? Storage/RBAC follow from this.
2. **Trend depth v1** — number + delta, or number + sparkline-over-time from the start?
   (Recommend sparkline; it is what "grip over time" wants and is cheap with a time dim.)
3. **Refresh mechanism** — new `dashboard_cards` store (recommended) vs extend `SavedQuery` vs
   delegate to Monitors.
4. **Where authoring lives first** — the linear briefing dashboard region (recommended; ships before
   the graph) or the argument-graph lens.
5. **Naming** — "cockpit", "watch", "pin to dashboard" are placeholders.

---

## 12. Appendix — verified reference map

Backend: `savedquery/models.py:14` · `semantic/metrics.py:39,464` · `sql/executor.py:123` ·
`sql/grain_guard.py:75` · `sql/join_guard.py:278,329` · `sql/ratio_grain.py:74,141` ·
`sql/trust_checks.py:93` · `trust/__init__.py:43` · `trust/receipt.py` · `monitors/models.py:14` ·
`routers/monitors.py:145,149` · `overview/drills.py:51,72` · `overview/build.py:664` ·
`explorer/synthesis.py:31,101` · `explorer/agent.py:3548,3878-3879` · `explorer/store.py:50` ·
`explorer/dossier.py:70,93` · `explorer/grounding.py:164` · `routers/investigations.py:2252,3387` ·
`routers/exploration.py:1089,1117` · `knowledge/briefing.py` (citations).

Frontend: `Chart.tsx:98` · `charts/echarts/` (`EChart.tsx`, `builders.ts`, `index.ts:90`) ·
`charts/exhibit.ts:33` · `charts/ResultChartCard.tsx:123` · `brief/BriefingDashboard.tsx:130` ·
`brief/IndustryKpiStrip.tsx:295` · `brief/GroundedNumber`, `brief/Sparkline` ·
`BriefingPanel.tsx:763-901,2103-2120` · `QueryBuilder.tsx:938,1441,1668` · `MetricsPanel.tsx` ·
`SemanticLayerPanel.tsx`. Export mirror: `aughor/export/charts.py`.

Stack: React 19.2.4 · Next 16.2.6 · ECharts ^6.1.0 · **no** react-flow/xyflow/tldraw (graph lens
greenfield).
