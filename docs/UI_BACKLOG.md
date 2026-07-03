# Aughor — UI Backlog (surfacing shipped-but-invisible features)

> **Why this exists.** A platform-heavy two days shipped a cluster of capabilities
> that are wired and tested on the backend but have **no UI surface** — a user can't
> reach them in the app. This file is the dedicated backlog to close that gap, with
> *placement* decisions, not just a list. Audit sources: the last-two-days work, the
> full `ROADMAP.md`, and `FEATURES.md`, each cross-referenced against `web/`.

## Reference model — Databricks Catalog Explorer

Most of these gaps are **metastore-shaped**, so we model the information architecture
on **Databricks' Catalog Explorer**: a left **Catalog** tree (catalog → schema →
table / volume), and a main panel of **tabs per object** — *Columns / Sample*,
**Permissions** (= our grants), **Details**, and inline **Comments** (= our glossary).
This single screen is the natural home for four of the gaps at once.

```
Catalog Explorer (evolve the existing Catalog screen)
└── Catalog (= a connection within an org)
    ├── Schemas ─ Tables ─ Columns | Sample | Comments(glossary)
    ├── Volumes ─ Objects (browse / upload / download)        ← Volumes UI
    ├── Permissions  (workspace grants: grant / revoke)        ← Grants UI
    └── Details
```

## Priority 1 — 🔴 real gaps (capability with zero UI)

| # | Feature | Backend | Placement | Notes |
|---|---|---|---|---|
| U1 | **Volumes** (unstructured tier) | `/metastore/catalogs/{id}/volumes`, `/metastore/volumes/{id}/objects` | Catalog Explorer → a **Volumes** node under a catalog; object list + an **upload** widget + download/delete | the "SQL over any object" tier; users currently cannot create a volume or upload a file |
| U2 | **Grants / access control** | `/metastore/workspaces/{id}/grants` (GET/POST/DELETE) | Catalog Explorer → a **Permissions** tab on a catalog (grant/revoke a workspace) | gate is `membership ∪ explicit grants`; no way to manage the explicit layer |
| U3 | **Business Glossary** (view/edit) | `/glossary`, `/glossary/{table}[/{column}]` (`routers/knowledge.py`) | Catalog Explorer → inline **Comments** on a table/column (Databricks-style); the auto-seed feeds the agent, users can't view/edit | only `api.gen.ts` types exist; no component calls it |

## Priority 2 — 🟡 backend ahead of UI (small, in their existing screens)

| # | Feature | Backend | Placement |
|---|---|---|---|
| U4 | **Catalog Explorer shell** | metastore (`list_catalogs`, `list_schemas`, UC read API) | the container for U1–U3 — surface catalogs/schemas as first-class instead of the flat connection tree |
| U5 | **Per-agent LLM model picker** | `PATCH /agents/{id}` accepts `model` | Fleet → **Agents** tab: add a model dropdown next to enable/pause |
| U6 | **Governed Dives / playbook version history** | playbook `version` + `/playbook/{id}/versions` | Playbook panel → a version timeline / "pinned receipt" badge per entry |
| U7 | **Monitor anti-flap knob** | `grace_period_hours` in `run_monitor` | Monitor create/edit form → a "grace period" field |
| U8 | **Post-processing operators** | `tools/postproc.py` (PoP/Pareto/rolling/cumulative) | answer card / Query Builder result → optional "add PoP / rolling avg" transforms (today only auto-injected to the LLM) |

## Priority 3 — 🟢 invisible by design (optional Settings toggles)

These are deliberate cost/ops trade-offs (off by default). Optionally expose a toggle
in **Settings → Models / System** so an operator can flip them without env vars:
- **R8 in-SQL `prompt()`/`embedding()`** — `AUGHOR_AI_SQL`
- **Snapshot-pinned receipts** — `AUGHOR_SNAPSHOT_RECEIPTS`
- **dbt manifest** — env/file (`HERMES_DBT_MANIFEST`); a manifest-upload UI is optional

## Not gaps (verified — do not build)
- **Ontology overrides** — the *API* overrides already have inline edit UI (`lib/api.ts:942,955` → OntologyPanel); only the *YAML-file* override (#138) is file-only **by design**.
- **R8 semantic operators** (`runSemanticOp`) — already wired in the Query Builder (`QueryBuilder.tsx:827`).
- Briefing / Verdict hero, Fleet, Agents enable/pause, Learned-skills drawer, Save-as-skill, Trust Receipt, Validate/feedback row, QB decompile, KPI scorecard, Org/Workspace settings, Pivot — all confirmed present.

## Build order
1. ✅ **U4 + U1 + U2** — Catalog Explorer with **Volumes** + **Permissions** tabs (`7caaa6e`, browser-verified).
2. ✅ **U3** — **Glossary** as a Comments tab in the table detail (`63efe35`, browser-verified).
3. ✅ **U5 / U7 / U6** — per-agent model picker · monitor grace-period · playbook version history (`56f2c95`, browser-verified).
4. ✅ **U8** — post-proc transforms: a `POST /query/postproc` endpoint + a "Transform" control on the answer card (`8c5a88e`).
5. ✅ **P3** — runtime feature-flag store (`aughor/kernel/flags.py`, override > env) + Settings → System toggles (`494b43e`).

> **Status: COMPLETE.** All 🔴 real gaps (Volumes · Grants · Glossary) and all 🟡/P3 items
> (U5–U8, P3) are shipped on branch `2026-06-22-org-tenant-spine` (PR #78), each browser-verified.
> Every shipped-but-invisible feature from the audit now has a UI surface.

---

## Deep Analysis report — formatting fixes + layout redesign (2026-07-02)

Four points raised against the live "Why are womenswear returns so high?" report.

**Shipped (branch `2026-07-02-ada-temporal-intake-grain`):**
- **#1 — percentage consistency.** A ratio metric aliased `metric_total` was stored as a fraction
  (0.4096) and rendered three ways: chart "0.4", section key-number "0.41%", prose "40.96%". Root:
  the frontend detected percentages by column *name* only (three copies of the same regex), which
  `metric_total` never matches. Fix (approach a): the backend tags a per-column unit on the finding
  (`InvestigationFinding.column_units = {"metric_total":"percent"}`) whenever the metric is a
  percentage (`_metric_is_percent`), rebuilds percent key-numbers scale-aware (`_fmt_pct`,
  `_normalize_pct_key_numbers`, scale-aware `_fix_xsec_extreme_key_numbers`), and the frontend chart
  honours the explicit unit (`builders.isShareField`/`valueFormatter`, `Chart.columnUnits`) so axis +
  labels + key numbers all read "41.0%". Composition (`pct_of_total`) + temporal (`metric_value`)
  lenses tagged too. Live-verified via `/chart-lab`.
- **#2 — bar sizing.** Horizontal-bar height was `max(350, nCats*28+60)` → a fixed 350px floor that
  stretched 2 bars into slabs. Now `max(110, nCats*46+44)` (adapts down; the 350px viewport still
  scrolls tall charts) + `barMaxWidth: 34` (fixed thickness). Live: 5 bars → 274px, 2 bars → 136px.
- **#3 — data labels.** Off by default; now on for report finding charts, routed through the #1
  formatter, with series `labelLayout: { hideOverlap: true }` so crowded labels drop instead of
  overprinting.

**Proposed, NOT built — #4 report layout ("more content, less noise").** Lead with the verdict + the
2–3 numbers that matter; each phase = one-line takeaway + one figure with visible labels; demote prose
to muted secondary; merge significance + trust + grain into one compact chip row; keep a SINGLE details
drawer (no per-finding SQL repeated inline); gate sparklines to temporal findings. Mockup delivered in
session. Current structure map: `InvestigationReport.tsx` (`EvidenceBlock` / `PhaseSection` /
`InvestigationDetails`) + `Brief.tsx`.
