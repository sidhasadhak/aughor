# Part 2 — Scoping & Sequencing (2026-07-04)

The plan of record for executing Part 2 of the architecture review
([`PART-2-uiux-nomenclature-and-layering.md`](PART-2-uiux-nomenclature-and-layering.md)).
Part 1 + DATA-05/06 + full RBAC + DATA-06 depth + item 2b are all shipped; Part 2 is
the last untouched arc.

Part 2 is **not a redesign** — it is finishing **three consolidations the codebase
started and stopped mid-way**, plus one backend architecture axis:

- **Track A — one enforced design layer** (tokens → primitives → composites)
- **Track B — one shell + one render protocol** (`<Workspace>`, renderer registry)
- **Track C — one noun model** (kill the `ADA`/`Insight`/`Finding`/mode overloads)
- **Track D — the eight functional planes** (AL: `trust.verify` façade, `Capability`
  template, Semantic plane in the router) — backend, largely independent of A–C

## Grounded numbers (verified against HEAD 2026-07-04, not the review's older commit)

Every count below was re-grepped now. Where it differs from the review, **reality is
worse** — the debt grew, which strengthens the case for the lint gates first.

| Finding | Review | **Now** | Note |
|---|---|---|---|
| Radius violations (`rounded-lg/xl/2xl/3xl/full`) | 156 | **156** | exact |
| Arbitrary `text-[Npx]` | "arbitrary" | **543** | much larger than implied |
| Orphaned `ui/` primitives | 9 files, 0 imports | **9 files, 0 `ui/card` imports** | confirmed orphan |
| Raw `<button>` vs `<Button>` | 183 vs 5 | **204 vs 1** | `<Button>` is effectively dead |
| Formatting drift (`toLocaleString`/`Intl`) | "under-adopted" | **26 sites** outside `lib/format.ts` | confirmed |
| Palette triplication | 3 sources | **`palette.ts` has AUG_PALETTE + TABLE_PALETTES + H_PALETTES** | confirmed |
| `ReportView.tsx` div-soup | large | **769 lines / 31 KB** | confirmed |
| `ChatMessage.tsx` god-component | 1253 | **1253 lines** | exact |
| `ADA` jargon leak | 47 files | **49 files (27 py + 22 web)** | `ada_intake/report/synthesize/...` |
| Sibling panels / NavTabs | 20 panels | **23 `*Panel.tsx`, ~33 tab refs, 2 `*Workspace` exemplars** | confirmed |

---

## Waves (each wave ≈ one branch / PR; every REC = one reversible, mechanically-verified commit)

### Wave 1 — DO NOW · the enforced design layer (unblocks everything else)
*Every structural rec renders through the primitives, so freeze drift + fix the
primitive layer first. Highest leverage in Part 2 per the review's own verdict.*

| REC | What | Effort | Risk | Verify |
|---|---|---|---|---|
| **REC-U1** | ESLint/CI gate banning `rounded-{lg..full}` + raw `text-[Npx]` in `components/**`,`app/**`; codemod 156 radius + 543 px sites to tokens (`--r2/--r3`, `aug-text-*`); add an explicit `--r-pill` for intentional pills | S | Low–Med | grep for banned classes → 0; CI fails on reintroduction |
| **REC-U8** | Route `ReportView.KPIHighlight`/`ChatMessage.fmt`/`HistoryDetailPanel` through `lib/format.ts`; lint-ban `toLocaleString`/`Intl.NumberFormat` outside `lib/format.ts` (26 sites) | S | Low | no `toLocaleString` in `components/`; one value renders identically across surfaces |
| **REC-U4** | One palette source — generate `palette.ts` **and** the CSS `--chart-*` from one TS constant at build (no runtime `getComputedStyle` → SSR-safe); replace `TABLE/H_PALETTES` literal bundles with token ramps; fix stale "Vega-Lite"→"ECharts" label | S | Med (SSR) | six brand hexes in exactly one file; changing `--chart-1` moves series + chrome |
| **REC-U2** | Rebuild `ui/button/badge/card` from tokens (drop `rounded-xl`/`font-heading`); codemod 204 raw `<button>` → `<Button>` (preserve `type`/native attrs); then **delete the off-brand orphans** or fold into the token'd set | M | Med (form regressions) | raw `<button>` < ~20; `ui/card` imports > 15; form smoke test |

**Guardrails:** never batch radius with color; preserve `type="submit"` in the button
codemod (add a form smoke test); U4 must generate at build, never read `getComputedStyle`
at SSR (charts render black otherwise).

### Wave 2 — DO NEXT · composites + structure + the gen-UI protocol
*Depends on brand-correct primitives (Wave 1). This is where the "answer is a document"
philosophy reaches every surface and the CopilotKit/AG-UI gap closes.*

| REC | What | Effort | Risk | Depends |
|---|---|---|---|---|
| **REC-U3** | Promote `components/brief/*` → `composites/`; export `<FindingCard>`/`<StatusChip>`/`<MetricGrid>`/`<Placeholder>`; fold 11 local `*_STYLE` maps into one `STATUS_SCHEMA`; rewrite `ReportView.tsx` (769→composites, delete `CollapsibleSection`/`KeyFindingCard`/`RecommendationCard`) | M | Med (structure-only!) | U2 |
| **REC-U6** | **Renderer registry** — `TURN_RENDERERS: {id, match(turn), render(turn,props)}[]` with the 5 existing bodies; reduce `ChatMessage.InvestigateBody` to `renderers.find(match)?.render(...)` | M | Med (match order) | U3 |
| **REC-U5** | Generalize `IntelligenceWorkspace` → `<Workspace layers scope onLayerChange>`; re-express Intelligence/Canvas/Operations as instances; fold ~23 panels → ~5 workspaces; keep `LEGACY_*_LAYER` deep-link maps | L | Med (deep-links) | U2 |
| **REC-U7** | `<FigureCaption>` source-footers on `BriefFigure` (sourceTables/rowCount/dateRange); render each recommendation with its `origin_finding` evidence chip (backend provenance already exists — Part 1 Finding Dossier) | M | Low | U3 |

**Guardrails:** REC-U3/U5 are **structure/containment only — do NOT restyle or merge
component internals in the same commit** (DOM-diff, not color-diff); encode renderer
priority by array order (dossier before direct) + a unit test.

### Wave 3 — DO LATER · the noun model (widest blast radius — do last)
*Wants the registry + composites stable first. Boundary-first, `@deprecated` aliases,
one mode per commit, screenshot each mode.*

| REC | What | Effort | Risk | Depends |
|---|---|---|---|---|
| **REC-U9** | Concept renames at the **serialization boundary** — `ada_report`→`report`+`mode:"investigate"`, strip `ADA`/`hypothesis_id` from web-bound payloads (49 files); regen `api.gen.ts`; `types.ts` → `AnswerReport`/`Fact`/`AnalyticalNarrative`; keep old names as `@deprecated` one release | L | **High** | U6 |
| **REC-U10** | `semantic/contracts.py:SemanticContract`; make `MetricDefinition` + `ontology.OntologyMetric` serialize to it; point planning/enforcement/display at one type (ties to Part 1's #1 20-year ontology bet) | L | High | U9 |
| **NOM-07/11** | Shared `Safeguard` base for Monitor/Brief/Playbook; one `ExecutionScope` for `canvas_id`/`connection_id`/`scope_schema`/`table_filter` precedence | L | Med | U10 |
| **LAYER-04** | Settle the `OntologyCanvas`(1280)/`OntologyPanel`(1262)/`OntologyOrgCanvas` orphan — grep mount sites, delete or fold | S | Low | — |

**Guardrails:** never rename backend internals + the wire in one commit; wire-rename
first behind aliases, internal renames later; screenshot every answer mode after each.

### Wave 4 — the eight planes (AL) · backend, parallelizable with A–C
*Three reversible moves, each flag-gated with a plane-conformance test — not a rewrite.*

- **AL-01** — hoist the ~9 validation modules behind one `trust.verify(sql|code|metadata, scope) → Verdict` façade; every capability calls it (also closes Part 1 SEC-02 in one place).
- **AL-02** — collapse the 3 pipelines into one `Capability{generate,validate,execute,interpret}` template with a `domain` param.
- **AL-05** — insert the Semantic plane into the router so every route carries `SemanticContext`.
- **Verify:** a new capability (e.g. "forecast") = register one `Capability` impl + reuse Trust/Semantic/Memory planes, with zero edits to Orchestration or the stores.

*Effort: L, and it overlaps the ontology bet — best taken when that bet is picked up, or
slotted between UI waves since it touches different files.*

---

## Recommended sequence & first slice

1. **Wave 1** in order **REC-U1 → REC-U8 → REC-U4 → REC-U2** (U1/U8 have no deps and are
   pure wins; U4 before U2 so primitives consume the single palette).
2. **Wave 2** (U3 → U6/U7 → U5).
3. **Wave 3** (U9 → U10 → NOM-07/11), with **LAYER-04** droppable in anytime.
4. **Wave 4 (AL)** slotted in parallel or when the ontology bet is taken up.

**First slice → REC-U1 (radius/type lint gate + codemod).** S effort, no dependencies,
High leverage, and it's the "make drift cheap-to-prevent" move the 20-year view calls the
thing that "ages worst" if skipped. Concrete steps:
1. Add a flat-config ESLint rule (or a CI `grep` gate) failing on `rounded-(lg|xl|2xl|3xl|full)`
   and raw `text-\[\d+px\]` under `components/**`,`app/**`.
2. Introduce a `--r-pill` token; allowlist it for the handful of intentional pills.
3. Codemod 156 radius + 543 px sites to the nearest token (mechanical, screenshot-diff a
   few high-traffic surfaces after).
4. Wire the gate into `.github/workflows/ci.yml` (frontend job) — blocking, baseline zero,
   the same discipline as the ruff gate.

**Verification bar (all waves):** `tsc --noEmit` + `next build` clean, the new lint gate
green, and a screenshot-diff of `direct` vs `investigate` answers (the review's one
unverified visual claim — worth capturing early to prove the "two visual languages" thesis
before/after).

**Cross-cutting rules (from the review's failure-mode pass):** design layer before
consolidation; never restyle while migrating structure; never rename concepts + move files
in one commit; boundary-first renames with `@deprecated` aliases; flag-gate U9/U10; one
reversible commit per REC with a mechanical verify.

---

## Progress log

### ◑ Wave 4 in progress — the eight functional planes (AL)

**◑ AL live-path migrations — all three planes now run ON a live answer path, flag-gated (2026-07-04).**
With all three planes built + conformance-tested, wired each onto a live answer path,
**default-off → byte-identical** until enabled:
- **AL-01 live** (`trust.verify_live` / `AUGHOR_TRUST_VERIFY_LIVE`): `agent/investigate.py:_execute_safe`
  routes every generated SQL through `trust.verify` (conn-less Scope → only the pure readonly + E1
  checks, no double-work with the preflight/join/grain guards already inline) right before
  `conn.execute`; a readonly BLOCK **returns a blocked `QueryResult`** (handled downstream like any
  failed query, never raises) — the mutation gate the generation path never ran.
- **AL-05 live** (`semantic.resolve_live` / `AUGHOR_SEMANTIC_RESOLVE_LIVE`): a deep investigation
  resolves the Semantic plane once at seed (`routers/investigations.py` `initial_state`) via
  `semantic.context.resolve_if_enabled` (flag-gated + fail-open) and carries it on a new
  `AgentState.semantic_context` field, so every node reads one consistent context — the "every route
  carries SemanticContext" goal, additively (the ad-hoc consultations still work; they migrate onto
  the state incrementally).

**AL-02 live** (`capability.pipeline_live` / `AUGHOR_CAPABILITY_PIPELINE_LIVE`): `SqlCapability` is now
a **complete** capability — `generate` translates a question to SQL via a new standalone
`capability/sql_generate.py` (reusing the answer path's `WRITE_SQL_PROMPT` + `coder` provider — a
shared prompt, not a fork), so the Data domain runs **end-to-end through the one template**
(generate → validate=`trust.verify` → execute → interpret). Wired at a new `POST
/query/capability-answer` (non-streaming, template-driven counterpart to `/ask`). **✅ The deep ADA
path now shares the one generator too:** `generate_sql` was extended to expose the full
`WRITE_SQL_PROMPT` context (intent / pitfall / examples / ontology sections + injectable provider),
and `nodes._gen_sql._write` was converged onto it (same prompt, same `coder` provider — byte-identical
LLM call; its old silent `except: return None` now routes through `tolerate`, so `WRITE_SQL_PROMPT` /
`SQLOutput` are dropped from `nodes.py` and the swallow-count drops). **One WRITE_SQL_PROMPT call site
now** — the capability's `generate` and the ADA path both invoke it. *(enforce_gate / the metric-drift
B-7 gate stays in the node as the post-generation wrapper; that's orthogonal.)*

**Verified (pytest): 12 AL-live tests** — AL-01 blocks a `DELETE` before execute (flag on) / executes
unchanged (flag off) / passes clean SELECTs; AL-05 dormant-by-default / resolves-when-on / state
carries it; **AL-02 generate-from-question, full generate→validate→execute→interpret end-to-end on a
spy conn, and the `/query/capability-answer` endpoint (200 with the answer when on, 404 when off) —
all with a stubbed provider (no live LLM)**. Full-suite collect 2406 clean; 45 plane/regression tests
+ all ratchets green; ruff clean.

**◑ AL-05 — the Semantic plane, resolved once (2026-07-04).** The review's "single biggest
architectural gap": the crown-jewel semantic material (governed metrics, ontology, business profile,
KB) is consulted **ad-hoc** — ~9 inline calls scattered across `agent/nodes.py` +
`routers/investigations.py` — not a plane in the request path. Built `aughor/semantic/context.py`:
a `SemanticContext` dataclass + `resolve(question, connection_id, scope_schema) -> SemanticContext`
that **composes the existing consultations** (delegation, not rewrite) — `metrics.list_metrics`
(+ optional schema filter), `ontology.store.load_latest_ontology`, `profile.store.load_raw` (cached,
no LLM inference), `kb_retriever.has_strong_kb_match` — each **fail-open** (a missing ontology / empty
catalogue / unreachable KB leaves its field default; `resolve` never raises). Tied to AL-02:
`CapabilityRequest` gained a `semantic` field (the review's "Capability takes Question × Scope ×
SemanticContext"), typed loosely so the planes stay independent. **First consumer wired**:
`/query/semantic-context` (read-only, reads caches only — no DB connect) returns `SemanticContext.summary()`
("what the platform knows about this question"). **Verified (pytest): 7 tests** — composition (all four
sources bundled), fail-open (an erroring source degrades to default, others still resolve), `summary()`
shape, the `CapabilityRequest` tie, and the endpoint (200 + stable shape; 400 on missing conn); ruff
clean; 21 AL-01/AL-02 tests still green. *Deferred (the invasive half): threading the resolved context
through the live `_stream_ask` → every node (so every route carries it) behind a flag, and feeding it
into `SqlCapability.generate` (metric-aware SQL) — the "not a big bang" migration.*

**◑ AL-02 — the Capability plane template + one real instance (2026-07-04).** The three answer
pipelines are the *same shape* built three times (Data: SQL-gen → validate → execute → interpret;
Code: same but unimplemented; Metadata: handler → interpret). Modeled that shape once in a new
`aughor/capability` plane: a `CapabilityPipeline` Protocol (`generate/validate/execute/interpret`
+ `domain`/`kind`), a `run()` template that sequences the four phases — **`validate` routes through
the Trust plane** (`trust.verify`, so AL-02 consumes AL-01) and a BLOCK **short-circuits before
execute** (a mutating statement never reaches the DB) while a repair from `validate` is adopted as
the executed artifact — and a dict registry (`register_capability`/`get_capability`/`run_capability`,
matching the `kernel/registries` idiom). Named `CapabilityPipeline`, not `Capability`, to avoid the
`licensing.capabilities.Capability` (permission enum) clash. **One real instance**: `SqlCapability`
(domain `"data"`) whose phases *delegate* to existing code — `trust.verify` (validate),
`conn.execute` (execute), `format_result_for_llm` (interpret) — runnable end-to-end with no LLM.
**Purely additive** (only new files; zero edits to existing code → no regression surface).
**Verified (pytest): 8 conformance tests** — the review's acceptance bar (*register a toy
`forecast` capability from outside → it runs through the template unchanged*), block short-circuit
(a `DELETE` never reaches a spy connection), repair adoption, and `SqlCapability` end-to-end on both
a spy connection and the **real DuckDB fixture**; ruff clean. *Deferred (documented): the LLM
question→SQL `generate` (`nodes._gen_sql`) + full narrative synthesis; the Code/Metadata instances;
and migrating the live investigate/explore orchestration onto the template behind a flag — the
"not a big bang" step.*

**◑ AL-01 — the Trust plane, built + conformance-tested + first consumer wired (2026-07-04).**
The ~9 validation modules were diffused across the three answer paths, each grown a *different
subset* (grep-confirmed: `check_join_value_domains` in 6 paths, `run_trust_checks` in only the
query router, `readonly.is_mutating` in *none* of the generation paths — only the execution
gate). Hoisted them behind one `aughor/trust` plane: `verify(artifact, scope) -> Verdict`
(`trust/verdict.py` = `Scope`/`Check`/`Verdict`; `trust/__init__.py` = the façade). It
**delegates** (composition, not rewrite) — for `kind="sql"`: `readonly` → **BLOCK** (mutation /
destruction / disallowed-function; the decisive gate, never swallowed — this is the guard the
generation paths were missing, so it closes Part 1 **SEC-02** at the plane), `trust_checks` →
**WARN** (E1 footguns, pure), and conn-gated `preflight_repair` (repair, folds its receipt +
returns repaired SQL as `Verdict.artifact`) / `join_guard` / `grain_guard` → repair/WARN. `ok`
is derived: false iff a BLOCK check failed; WARNs are advisory and never flip it. Flag-gated
(`trust.verify_facade` / `AUGHOR_TRUST_FACADE`, default off). **First consumer wired**:
`/query/validate` gains a flag-gated `mutation_blockers` field (additive — existing keys
untouched), closing the SEC-02 read-only gap on that surface. **Verified (pytest — the whole
reason Wave 4 was sequenced before the remaining UI slices): 13 plane-conformance tests** (BLOCK
decisiveness, WARN-never-flips-ok, delegation parity `verify(sql).ok == not is_mutating(sql)`,
non-sql-kind passthrough) **+ 2 integration tests on the real `/query/validate` path** (flag on →
a `DELETE` is blocked; flag off → field empty); ruff clean; 21 existing query/safety/packs tests
green. *Deferred to later AL-01 slices (documented, not dropped): the `code`/`metadata` kinds;
the `semantic_validator`/`sql_consistency`/`verify`/`soma`/`sql_consensus` guards; and migrating
the answer paths (investigate/explore/nodes) off their inline guard calls onto the façade. AL-02
(one `Capability{generate,validate,execute,interpret}` template) and AL-05 (Semantic plane in the
router) are the next Wave 4 moves.*

### ◑ Wave 2 in progress — composites + structure + gen-UI

**✅ REC-U5 — first panel-fold: the Operations workspace (2026-07-05).** With the `<Workspace>`
shell in place, folded the three Operations rail tabs (Monitors / Action Hub / Security & Audit)
into one `OperationsWorkspace` — an *instance* of `<Workspace>` (3 layers), mirroring
IntelligenceWorkspace. `page.tsx` drops the three separate `tab === …` render blocks (and the three
now-dead panel imports) for one `tab === "operations"`; a `LEGACY_OPS_LAYER` deep-link map routes the
kept rail items → the workspace layer (and the legacy `activity` deep-link → Security layer on the
Activity lens); the Sidebar gets a computed `activeNav = tab === "operations" ? opsLayer : tab` so the
right rail item highlights. Security & Audit's own `security ↔ activity` lens is threaded through
(`secLens`) so it's preserved inside the layer. **Live-verified on the running app** (own dev server,
after killing the peer's): each rail item deep-links to its layer, the segmented switcher swaps layers
+ syncs the sidebar highlight, the nested lens toggles, exactly one rail item is `.active`, zero
console errors; tsc + all three web gates green.

**✅ REC-U5 — second panel-fold: the Data workspace (2026-07-05).** Same pattern for the Data rail
(Catalog / Query Builder / Semantic Layer). These three panels are tightly coupled to `page.tsx`
state (Catalog alone takes 6 callbacks), so rather than a prop-bag component this fold renders
`<Workspace>` **inline** in `page.tsx` — `renderLayer` closes over the existing state/handlers, reusing
the existing dynamic panel imports + the `NavIcon` set — so it net-*shrinks* `page.tsx` (three
`tab === …` blocks → one `tab === "data"`). `LEGACY_DATA_LAYER` deep-links + the same computed
`activeNav`; the insight→builder handoff (`handleOpenInBuilder`) now routes to `data`/`builder`.
(The `Workspace` primitive is imported `as WorkspaceShell` — `page.tsx` already has a `Workspace`
domain *type*.) **Live-verified**: each rail item deep-links to its layer, the switcher swaps
Catalog/Builder/Semantic + syncs the sidebar, cold deep-links land right, exactly one rail item
`.active`, zero console errors; tsc + gates green. *Two of the three sidebar sections (Operations,
Data) are now folded; the Intelligence section's Briefing is already IntelligenceWorkspace. Remaining
U5: re-express CanvasWorkspace (richer header + eager-mount need care).*

**◑ REC-U5 — the one Workspace shell, extracted (2026-07-04).** Pulled the generic
`<Workspace layers layer onLayerChange ariaLabel renderIcon headerControls renderLayer>`
shell out of `IntelligenceWorkspace` into `components/Workspace.tsx`: it owns the header
chrome (active title + optional controls slot + the segmented perspective switcher) and the
keep-alive layered body (visited-Set mount-once, `display`-toggled, now keyed by layer id).
`IntelligenceWorkspace` is re-expressed as a thin *instance* — it keeps only its own scope
(connection + schema pickers as `headerControls`, the five panels via `renderLayer`, the
inline icon set via `renderIcon`) and shrank 144→62 lines of body. **Behaviour-preserving
by construction** (DOM-diff, not color-diff — every inline style/class/aria preserved
byte-for-byte; the only change is the body's sibling order now follows the switcher order
instead of the old hand-written order, which is immaterial under `position:absolute;inset:0`
and now keyed for stable identity). Verified: `tsc --noEmit` clean, all three design gates
green (the switcher's one `<button>` moved file-to-file → the raw-element ratchet holds at
204), dev server compiling without errors. *Deferred (the risky half REC-U5 also names):
the panel-folding (~23 panels → ~5 workspaces) and re-expressing the Canvas/Operations
workspaces as instances — those touch deep-links (`LEGACY_INTEL_LAYER` in `page.tsx`) and
CanvasWorkspace's different tab chrome, so they're a separate ratchet-down, same discipline
as U2. The seam is now in place for them. Live click-through of the five layers was blocked
this session by the shared-dir Next dev lock (a peer session holds `:3000`; no second
`next dev` in one dir) + no Chrome MCP — the change is structure-only and fully type-covered.*

**◑ REC-U7 part 2 (rec→origin_finding chips) — stays deferred, confirmed why (2026-07-04).**
Re-mapped the flow to check the earlier deferral. Confirmed `ADARecommendation` still carries
no finding anchor (`action`/`expected_impact`/`owner`/`timeline` only), and the frontend chip
is trivial — but the *value* depends on knowing which finding motivates each recommendation,
which the `ada_synthesize` LLM does not reason about today (it gets the evidence as one prose
block and emits unanchored action text). Every linking strategy (ask-the-LLM-to-cite /
post-hoc semantic match / bracketed-id extraction) has a hallucination-or-ambiguity caveat
needing a quick synthesis experiment. Shipping a provenance chip over an unreliable anchor
would be a hollow feature — deferral is correct; do it as a scoped backend experiment, not a
UI-first change.

**◑ REC-U3a — one StatusChip vocabulary (2026-07-04).** Folded ReportView's three
copy-pasted chip style maps (VERDICT_STYLE / STAT_STYLE / STATUS_STYLE) into one shared
`components/brief/StatusChip.tsx` — a hue × strength scale + `<StatusChip>` + `chipTone()`.
ReportView keeps only thin semantic maps (status → hue + label); classes live once. The
review's "0 local `*_STYLE` maps" for this surface. **Zero-visual-change by construction**
(each hue×strength preserves the exact original class strings — verified byte-identical;
build + compiled-CSS confirm). *U3b — the structural migration (container → Brief,
CollapsibleSection → BriefDetails, KeyFindingCard → a Brief FindingCard) — is a real
LAYOUT change to a LEGACY renderer (ReportView; direct reports skip history indexing, so
there's no live legacy report to screenshot-diff) with badge/colored-title subtleties.
Deferred rather than shipped unverified — low value (legacy view) + unverifiable now.*

**✅ REC-U7 — chart source-footers (2026-07-04).** `BriefFigure` takes an optional
`source: FigureSource` → renders `<FigureCaption>` ("Source: order_items · N rows · date
range"); `lib/figureSource.ts:deriveFigureSource` derives it from the result (tables via a
FROM/JOIN scan, row count, first date column's min–max reusing format.ts granularity).
Wired into ChatMessage's ResultFigure. **Live-verified on luxexperience**: "total GMV by
brand tier" → bar chart with "Source: luxexperience.order_items · 3 rows". *The
recommendation-grounding half (link each rec to its origin_finding) is a separate backend
change — recs carry no finding anchor today — deferred.*

**✅ Follow-up composition on the deep/direct path (2026-07-04, `feat(agent)`).** Not a
numbered REC but the same "answer surface" arc: the quick /chat (Insight) path composed
follow-ups; the DEEP path (which owns the DIRECT lookup branch) didn't. Threaded `history`
through /investigate + /ask→deep, built a `_followup_origin` from the prior turn (anchors
ADA's origin_finding + the direct branch's prior_analyses), and stopped route_question
wiping the seed. **Live-verified on luxexperience**: "break that down by platform, just for
ultra" kept the GMV metric + returns filter, added platform, filtered ultra. +7 tests.

**✅ REC-U6 — turn renderer registry (2026-07-04).** ChatMessage's `InvestigateBody`
if-chain (dossier→ada→explore→direct) → a `TURN_RENDERERS` registry (first-match-wins by
array order = the old priority) + `registerTurnRenderer()` so a pack can contribute an
answer surface without editing ChatMessage — the LAYER-05 gen-UI seam. Behaviour-preserving
by construction (no JS test runner in web/; verified tsc + next build). *Follow-up: move the
render bodies out of ChatMessage to actually shrink the 1.25k-line file.*

**✅ LAYER-04 — RESOLVED, not an orphan (2026-07-04).** The review flagged it *unconfirmed*.
Confirmed the live chain: `page.tsx → IntelligenceWorkspace → OntologyPanel` renders BOTH
`<OntologyCanvas>` (OntologyPanel:1203) and `<OntologyOrgCanvas>` (:1154); `OntologyCanvas`
also exports `EntityCluster`/`measureCluster` used by `OntologyOrgCanvas`. All three are
live — no deletion/fold. Documentation-only outcome.

**Remaining Wave 2:** REC-U3 (promote Brief* + rewrite the 771-line ReportView div-soup +
fold its 3 style maps into one STATUS_SCHEMA). NOTE from the U7 work: ReportView is a
**legacy** renderer — only HistoryDetailPanel uses it; the live canvas direct-answer already
renders via the Brief* family (ChatMessage). So U3's value is narrowing the history-detail
surface onto Brief*; it's a large rewrite needing new FindingCard/StatusChip/MetricGrid
composites + a legacy report in history to screenshot-diff. REC-U5 (generalize `<Workspace>`,
fold ~23 panels — L).

### ✅ Wave 1 COMPLETE — the enforced design layer (2026-07-04): U1 · U8 · U4 · U2

### ✅ REC-U2 — primitive-layer ratchet (2026-07-04)
Shipped. The review's "off-brand orphaned ui/" premise was overtaken — the `ui/*`
primitives are modern shadcn v4 wired to the theme tokens, and REC-U1 already replaced
their `rounded-xl`. Removed the last off-brand bit (`font-heading`, an undefined no-op
class in `ui/card`). The real gap — 204 raw `<button>`s predating the primitive layer —
is handled by a **one-way ratchet** (`scripts/check-raw-elements.mjs`, `npm run
lint:elements`, blocking CI, baseline 204) rather than a risky blind codemod (which would
add the default `bg-primary` variant and break custom styling — the review's own failure
mode). Raw-`<button>` count may only shrink; convert to `<Button>` opportunistically and
lower the baseline. Full retro-adoption is incremental ratchet-down work.

### ✅ REC-U4 — one palette source (2026-07-04)
Shipped. The chart palette was already single-sourced from `--chart-*` (the ECharts
theme reads them live); the hard-coded `AUG_PALETTE` hex ramp was **dead code** (unused
since the Vega→ECharts migration) — deleted. `TABLE_PALETTES`/`H_PALETTES` (previously
unrelated Tailwind colours) now **derive from the six `--chart-*` tokens** via
`color-mix()` at the old `/NN` alphas, delivered as inline-style objects (SchemaCards /
ReportView apply via `style`), so card chrome and chart series share one ramp and flip
together in dark/light — the REC-U4 verify. Removed the redundant `--chart-1..6` from the
shadowed legacy `styles/tokens.css` (now defined once, in the active v2 theme — advances
discovery #1). Verified: tsc + build, both gates green, browser eval confirms the
`color-mix(var(--chart-N) …)` derivations resolve to the exact brand rgba.

### ✅ REC-U8 — formatting adoption gate (2026-07-04)
Shipped. `web/scripts/check-formatting.mjs` (blocking CI gate, `npm run lint:format`,
baseline zero) bans `toLocaleString` / `Intl.*Format` in `components/`,`app/`. Migrated
**22 sites across 20 files**: the two local reimplementations (`ChatMessage.fmt` —
lowercase-k drift — and `PivotTable.fmt`) now delegate to `compactNumber`/
`formatPercent`/`formatMetricValue`; 14 counts → `formatCount` (pins en-US); 6 timestamps
+ HistoryDetailPanel's hand-built date → a new `formatTimestamp(x, "full"|"short")` in
`format.ts`. Count/timestamp migrations are behaviour-preserving by construction. Verified:
both gates green, tsc + next build, isolated server mounts with no runtime errors. The gate
caught 2 offenders (`PivotTable`'s arg'd `toLocaleString`) a plain grep missed — the value
of an executable gate over a one-time sweep.

### ✅ REC-U1 — design-token lint gate + codemod (2026-07-04)
Shipped. `web/scripts/check-design-tokens.mjs` (blocking CI gate, `npm run lint:tokens`,
baseline zero) + a codemod of **711 sites across 41 files**: 161 raw radius →
`rounded-[var(--r3)]` / `rounded-[var(--r-pill)]`, 546 raw `text-[Npx]` → `aug-fs-*`.
New tokens: `--r-pill` (tokens.css + tokens-v2.css) and a **size-only** `aug-fs-*` family
in `type.css`. Verified: gate green + fails-on-reintroduction, `tsc` + `next build` clean,
compiled-CSS inspection (correct `font-size` / `border-radius:var(...)`, zero invalid
rules), and browser screenshots of two views (Briefing empty-state + Query Builder).

**Two discoveries that reshape later waves — read before U2/U3/U4:**

1. **The app runs a *v2* theme, not `styles/tokens.css`.** `app/globals.css` imports
   `aughor-v2/theme/tokens-v2.css` *after* the legacy `styles/tokens.css`, and v2
   **redefines the same token names with different values** (e.g. `--r3` is 6px in the
   legacy file but **10px** in v2 — v2 wins). So there are **two live token systems**,
   the legacy one shadowed. This IS the "color-model triplication / parallel-system"
   smell (UX-04, exec summary) made concrete. **REC-U4 (one palette source) and REC-U2
   (rebuild primitives) must target `aughor-v2/theme/` as canonical and retire/reconcile
   the legacy `styles/tokens.css`** — not the other way round. (`aug-fs-*` was added to
   `type.css`, which v2 does *not* shadow, so type is unaffected.)

2. **The `[--var]` bracket convention is silently broken under Tailwind v4** — a systemic
   latent bug. `text-[--t1]` compiles to `color:--t1` (a bare custom-property name, which
   is invalid CSS and dropped by the browser); it only *looks* fine because text colour
   **inherits** from a root `color:var(--t1)`. Non-inheriting properties (border-radius,
   backgrounds where the parent differs) are genuinely not applying. The correct v4 form
   is `[var(--x)]` (explicit) or `(--x)` (v4 shorthand). REC-U1's radius codemod uses
   `[var(--r3)]`; the **hundreds of pre-existing `text-[--t*]` / `bg-[--*]` sites are a
   separate, high-value cleanup** (candidate for its own gate: ban bare `-[--…]`, require
   `-[var(--…)]`). Note Tailwind v4 also scans comment/hint text for class candidates —
   keep token examples in the `[var(--…)]` form in comments too.
