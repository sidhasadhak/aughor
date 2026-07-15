# Databricks wire study #2 — canvas birth + two Deep-Research investigations → R11–R15

**Companion to** [`DATABRICKS_HAR_SQLX_AUTODOC_STUDY_2026-07-15.md`](DATABRICKS_HAR_SQLX_AUTODOC_STUDY_2026-07-15.md)
(which produced R1–R10). This study reads two more HAR captures taken on the **same airline dataset we
have** (`workspace.airlines.*`, 18 tables — apples-to-apples with our `tickets.csv` fixture), plus the two
rendered outputs:

| Capture | File | What it is |
|---|---|---|
| 3 · Canvas birth → investigation | `DB_Canvas_creation_investigation.xlsx` | table-picker → space create → **column-config + knowledge-mining + curated questions** → a Deep-Research run |
| 4 · "Where are we losing money?" | `DB_where_are_we_losing_money.xlsx` | a Deep-Research investigation (confirms capture-2's shape) |
| Output A | `Where You're Losing Money.pdf` | the losing-money report |
| Output B | `Interesting Outlier Entit.pdf` | the outlier-entities report (a **curated starter**, `source_id=research_agent_outliers`) |

Method: reconstruct the HAR JSON from column A (one line per row), summarize the request timeline + decode
the POST payloads. Everything below is quoted from the actual wire.

---

## 1 · The canvas-birth rite (Capture 3, t=1:56:02 → 1:56:43, ~40s)

Databricks turns "pick some tables" into a **documented, profiled, indexed, curated space** in one ~40s
orchestrated burst *before the first question*:

```
POST /ajax-api/2.0/data-rooms/            create the space
  {"display_name":"New Agent","warehouse_id":…,
   "table_identifiers":[18 × workspace.airlines.*],
   "run_as_type":"VIEWER","auto_generate_joins":false,"generate_space_name":true}
per-table, in parallel:
  POST /unity-catalog/authz-eval          RBAC gate (every table access authorized)
  GET  /unity-catalog/tables/{fqn}         full column metadata (types, comments, tags) — 25 KB/table
  GET  /unity-catalog/…/tags               governance tag assignments
  POST /graphql/TableMetadataPreviewPopularityData   ← POPULARITY (query-frequency = notability)
  POST /sql/statements  {"statement":"describe detail `workspace`.`airlines`.`flights`;"}  ← profiling probe
POST /data-rooms/{id}/column-configs       ← 17 KB, 13.8 s — the per-column semantic config (see §2)
POST /data-rooms/{id}/knowledge/start-mining  {"tables_names":[18 …]}  ← background KNOWLEDGE MINING job
GET  /data-rooms/{id}/value-index-…        the value index (built from is_indexing columns)
GET  /data-rooms/{id}/schema               15 KB assembled schema
GET  /data-rooms/{id}/curated-questions    auto-generated STARTER questions
GET  /data-rooms/{id}/instructions         → "{}"  (EMPTY — zero curated context, again)
```

**The single most important payload — `POST /column-configs` (17 KB, 13.8 s):**

```json
{"space_id":"…","column_configs":[
  {"table_path":"workspace.airlines.aircraft","column_name":"registration","is_sampling":true,"is_visible":true,"is_indexing":true},
  {"table_path":"workspace.airlines.aircraft","column_name":"delivery_year","is_sampling":true,"is_visible":true,"is_indexing":false},
  {"table_path":"workspace.airlines.flights","column_name":"flight_id","is_sampling":true,"is_visible":true,"is_indexing":false},
  {"table_path":"workspace.airlines.flights","column_name":"flight_number","is_sampling":true,"is_visible":true,"is_indexing":true},
  {"table_path":"workspace.airlines.flights","column_name":"origin","…":"…","is_indexing":true},
  {"table_path":"workspace.airlines.flights","column_name":"destination","…":"…","is_indexing":true},
  {"table_path":"workspace.airlines.flights","column_name":"route_id","is_indexing":false},
  {"table_path":"workspace.airlines.flights","column_name":"haul","is_indexing":true}, … ]}
```

Three per-column flags, **decided at build and persisted to the space**:
- **`is_indexing`** — build a value index over the column (for offline entity binding). Chosen `true` for
  entity dimensions (`registration`, `flight_number`, `origin`, `destination`, `haul`, `type_code`) and
  `false` for keys / dates (`flight_id`, `route_id`, `flight_date`, `delivery_year`). **This is *exactly*
  Aughor's R5 `_ENTITY_DIM_RE` value-sample gate** — Databricks reached the same selectivity rule.
- **`is_sampling`** — sample distinct values into the prompt context.
- **`is_visible`** — expose the column to the agent at all (i.e. **prune noise columns** = DB-info
  compression, the ReFoRCE lever, at the column grain).

The 13.8 s spend is the LLM deciding these per column across 18 tables. The result is a **persisted,
per-column semantic config** the whole downstream stack reads.

**Two more birth-time first-class jobs Aughor doesn't have as first-class:**
- `knowledge/start-mining` — a named background job that mines knowledge over the picked tables.
- `curated-questions` — auto-generated per-space starter questions (one had `source_id=research_agent_outliers`).

---

## 2 · The investigation shape (Captures 3 & 4) — confirms capture-2, adds the starter provenance

Both runs are byte-for-byte the shape the first study found — this is now triple-confirmed:

```
POST /conversations   {"title":"Where are we losing money?","model":"SMART_AI","conversation_type":"DEEP_RESEARCH"}
POST /messages        {"content":"…","message_input_source":{"category":"STARTER","source_id":"research_agent_outliers"},
                       "client_context":{"genie_app_context":{"force_deep_research_planning":true}}}
… pure polling of an APPEND-ONLY message JSON (resp grows 282 → 1053 → 2652 → 6213 B = the plan+waves state machine)
… STAGED PARALLEL WAVES of query-result/{uuidv7}, 4–8 concurrent per wave, polled ~1.2–2.5 s
… long synthesis → report
instructions → "{}"  (zero curated context — orchestration is the edge, again)
```

**New signal:** the outlier run carried `message_input_source:{category:STARTER, source_id:"research_agent_outliers"}`
— i.e. Databricks ships a **library of named "research-agent" starters** (an outlier-finder, presumably a
losing-money one, …) that are one-click Deep-Research playbooks, distinct from free-typed questions.

---

## 3 · The output quality bar (the two PDFs)

Both reports are decision-grade. The patterns worth *adopting* (beyond what our ADA already does):

- **Named, grounded entities with IDs.** `CU0036204` (2,423 tickets ≈ 6 flights/day), aircraft `HB-JBE`
  (98-min delay on flight `LX836`), baggage `BG00065297` (165.9 kg). Every claim points at a real row.
- **Numbered finding sections**, each = *claim → specific evidence → chart/table → "Potential causes"*
  (hypotheses, honestly hedged: "likely", "operationally impossible → data-quality"). Even names a
  data-quality cause for the 6-flights/day outlier.
- **Opportunity-cost / benchmark framing** (the losing-money report's strongest move): not just "long-haul
  load factor is 74.5%" but *"raising it to the short-haul benchmark of 77.2% fills 1,767 seats across 258
  flights → 2–3 M CHF."* The **gap-to-benchmark × volume = $ opportunity** is the decision.
- **Actionable, finding-tied recommendations** (route optimization, dynamic pricing, refund-policy review).

---

## 4 · Where Aughor stands (verified against current `main` + memory)

| Databricks capability | Aughor today | Gap |
|---|---|---|
| `column-configs` (is_visible/is_sampling/is_indexing, persisted, editable) | R5 decides value-index selectivity (`_ENTITY_DIM_RE`); R8 doc-tree captures column facts; nao editable-ontology overrides | **No unified, persisted, editable per-column {visible, sample, index} config.** No column *visibility pruning* at all. |
| `knowledge/start-mining` birth job | R1 re-arms exploration on upload; ontology builds at schema-load; R8 doc-tree | Pieces exist but are **scattered across triggers**, not one observable "understand this data" job |
| `curated-questions` + named starters | `/suggestions` (6), R8 3-analyst-questions, overview interesting-facts | **No named, reusable research-playbook library** (outlier-finder, losing-money) as one-click starters |
| `TableMetadataPreviewPopularityData` (popularity) | overview "learned notability"; `sql/query_log_miner.py`; `obs.task_table` | Popularity **not unified** as a signal feeding column-visibility / doc-tree ranking / overview priority |
| Staged parallel SQL waves | explore subgraph waves; **R9** unlocks them from `/ask` | ✅ matched (R9 in flight, PR #167) |
| Pure-polling transport | SSE / token streaming | ✅ we're strictly better — DON'T adopt polling |
| `run_as_type:VIEWER` + per-table authz | RBAC (`rbac/`) + connector RBAC (#120) | ✅ matched |
| Opportunity-cost / named-outlier output | ADA findings + charts + honesty guards; overview outlier lens | **No $-quantified benchmark lens; no named-entity outlier lens** in the deep path |

---

## 5 · Recommendations — R11–R15 (continue the R-program)

### R11 · Per-column semantic config: `{visible, sample, index}` — persisted + editable
The `column-configs` analog, and the highest-leverage structural learning here because it **unifies R5 + R8
+ nao + context-compression** into one artifact. A per-(table,column) config with three flags:
- `index` — build the R5 high-card value index over this column (deterministic default = R5's
  `_ENTITY_DIM_RE` gate, now *persisted and overridable* instead of recomputed each build);
- `sample` — include sampled distinct values in the agent's schema context;
- `visible` — expose the column to the agent at all → **prune keys/audit/technical/noise columns from the
  prompt** (DB-info compression at the column grain; the biggest untapped lever on wide schemas).

Deterministic defaults from the profiler's `semantic_type` + name heuristics (entity-dim → index+sample+visible;
PK/FK/date/`_id`/audit → visible-but-no-index; low-signal/high-null/free-text blobs → hidden). Override-wins
via the nao editable-ontology file tree (`ontology/filetree.py`). **Consumed by:** `tools/schema.py` render
(prune invisible), `sql/value_index.py` (index set), R8 `doctree.py` (mark per-column), the profiler
(sampling set). Seam: a new `ontology/column_config.py` beside `overrides.py`; flag `ontology.column_config`.
*Builds directly on [R5](spider2-b1…)/[R8].*

### R12 · Canvas birth as ONE observable "knowledge-mining" job
The `knowledge/start-mining` analog. Today Aughor's birth work (R1 explorer re-arm, ontology build, R8
doc-tree, R11 column-config, profiles) fires from *different* triggers. Unify them into one first-class,
progress-emitting **"understand this data" job** (kernel K1 job, `obs.task_table` spine) that runs at
connection/canvas creation and on R1's upload re-arm: profile → ontology → R8 doc-tree → R11 column-config →
R13 curated questions → knowledge mine, each a visible sub-step. Makes canvas birth a coherent, observable,
resumable rite instead of lazy side-effects. Seam: `agent/schema_annotators.py` + a new `birth` orchestrator;
reuses the R8 auto-build hook. *Extends R1/R2/R8.*

### R13 · Named research-starter playbook library (`curated-questions` + `research_agent_*`)
Ship a small library of **named, deterministic research playbooks** — `outlier_entities`,
`where_are_we_losing_money`, `data_quality_scan` — surfaced as one-click canvas starters, plus per-space
auto-curated questions generated from R8's 3-analyst-questions + the schema shape. Each playbook is a
deterministic template (question + suggested mode + purpose tag) that routes to **R9** (wide → explore) or the
deep path with an **R10** purpose tag. The `outlier_entities` playbook is a *deep-research* sibling of our
overview/interesting-facts mode. Seam: a `playbook/` registry (exists) + `overview/` + R9 routing; surface via
`/suggestions` + the empty-chat starter chips. *Extends R9/R10 + overview.*

### R14 · Popularity/usage as a unified notability signal
The `TableMetadataPreviewPopularityData` analog. Mine the query log / task history (`sql/query_log_miner.py`
+ `obs.task_table`) into a per-table and per-column **popularity score**, and feed it into: R11 `visible`
(popular columns stay visible, never-queried ones can hide), R8 doc-tree node ranking, overview seed priority
(generalize the existing "learned notability"), and R13 starter relevance. One signal, four consumers. Seam:
a `stats`/`obs` popularity aggregator read by the four sites. *Extends R10 + overview + R8.*

### R15 · Decision-grade output lenses (opportunity-cost + named-outlier)
Adopt the two output moves the Genie reports nail, both on existing ADA/overview machinery:
- **Opportunity-cost / benchmark lens** — for an underperforming segment, compare to its best peer/benchmark
  and quantify **gap × volume = $ opportunity** ("74.5% → 77.2% = 1,767 seats = 2–3 M CHF"). Deterministic;
  extends the existing ADA benchmark lens (`_run_reason_benchmark_lens`) to compute the $ headroom.
- **Named-outlier-entity lens** — an overview/explore lens that surfaces the *extreme entities by ID* (top
  customer, most-delayed aircraft, heaviest baggage) each with a mini-profile + a hedged "potential causes"
  hypothesis. This is the `research_agent_outliers` output shape; extends the overview outlier lens into named
  entities with drill provenance. *Extends ADA lenses + overview.*

---

## 6 · What NOT to adopt (reinforced)
- **Polling transport** — we stream (SSE/AG-UI); strictly better. Adopt only the persist-first, append-only
  *state-machine* semantics, not the 200 ms polling.
- **13.8 s silent column-config spend** — do the R11 decision deterministically first (the `semantic_type`
  gate already gets it right); reserve any LLM pass for enrichment, behind the R8 estimate-then-confirm gate.
- **`instructions` = "{}"** — Databricks curates nothing; the orchestration is the edge. Validates our
  lean-deterministic thesis. Our editable ontology/glossary is a *superset* — keep it optional, never required.

## 7 · Sequencing
R11 (per-column config — unlocks pruning + persists R5) → R12 (unify birth into one job — the home for R11/R13)
→ R14 (popularity signal — feeds R11 visibility) → R13 (starter playbooks — needs R9 merged) → R15 (output
lenses — independent, user-visible). R11 and R15 are the two highest-leverage; R11 is the structural keystone.
