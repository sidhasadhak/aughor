# Aughor Platform Program v2 — the wave roadmap after the Databricks studies (2026-07-26)

**Supersedes the *forward* sections (§2–§4) of
[`PLATFORM_PROGRAM_2026-07-24.md`](PLATFORM_PROGRAM_2026-07-24.md).** That document remains
the authority on the completed waves (K, A, R, E, C, V), the joints J1–J8, and the rules of
engagement (§6, inherited verbatim here). `ROADMAP.md` §0 stays the session status page.

**Scope authority for this plan:**
[`DATABRICKS_STUDY_2026-07-26.md`](DATABRICKS_STUDY_2026-07-26.md) (ecosystem study: dqx ·
ontobricks · impulse · Genie One/Ontology/Agents · Federation · Lakeflow · landscape) and
[`GENIE_DOCS_TEARDOWN_2026-07-26.md`](GENIE_DOCS_TEARDOWN_2026-07-26.md) (the ~50-page Genie
docs teardown + imbibe map). One sentence of context: **Genie One validated Aughor's
architecture at DAIS scale; the competitive gap is default state, not design** — so this
program starts by turning on what is built, then hardens governance, then takes the
ontology fight to parity-plus, then ships the differentiator nobody has (quality caveats
in answers), then composes it all into the surface.

---

## 0. Where the build is (2026-07-26)

| Wave | State |
|---|---|
| K · A · R · E · C1–C6 · V1–V6 | ✅ all merged (#201, #204–#215, #217, **#219** — C6 + V landed together in one PR; V3b and V6b remain deliberately deferred) |
| **L · G · O · Q · S** | ⭕ this document |

`main` = `9584931`. Nothing is in flight; Wave L starts on a clean base.

---

## 1. The program — one sequence

```
  ┌─────────────────────┐
  │ L — Leverage        │  turn the built loops ON, through E6 receipts; closes the
  │     (activation)    │  ROADMAP §0 caveat; near-zero new machinery
  └──────────┬──────────┘
  ┌──────────▼──────────┐
  │ G — Governance      │  as planned + study enrichments; builds the clearance/tag/
  │                     │  usage substrate O·Q·S retrieval and surfaces sit on
  └──────────┬──────────┘
  ┌──────────▼──────────┐
  │ O — Ontology        │  parity with the settled checklist + the edge: synonyms,
  │     parity + edge   │  per-connection re-key, ranking, the generalization loop,
  │                     │  window measures, drift checks, connection-as-code
  └──────────┬──────────┘
  ┌──────────▼──────────┐
  │ Q — Quality plane   │  table-health rules → persisted results → CAVEATS RIDE THE
  │                     │  ANSWER (first-mover; nobody ships this)
  └──────────┬──────────┘
  ┌──────────▼──────────┐
  │ S — Surface &       │  Genie One as the blueprint: consumer surface, answer
  │     composition     │  anatomy, the loop UX, digests, distribution (MCP/OpenAI
  └─────────────────────┘  façade/llms.txt), entity pages = C rendered (J6)
```

**Mainline: L → G → O → Q → S.**

Why this order (and the named alternates):

1. **L first** because it is the cheapest wave with the largest product delta: five waves
   of built machinery become the running loop Genie is marketing. O's and Q's review
   queues only matter if the loops run. Alternate: none — nothing sane displaces L.
2. **G before O** for the same joint-shaped reason the old program put G before S:
   O3/O4 build retrieval surfaces that G5 permission-trims — building them on the
   clearance substrate avoids touching every retrieval site twice, and S's Domains are
   G2's tags rendered. *Alternate:* if competitive urgency wins, run **O before G** and
   accept retrofitting G5 across O's retrieval paths; the dependency is real but not
   architectural.
3. **O before Q** because O4's review-queue UX (the two Genie modals) is shared by Q2,
   and O2's re-keyed stores make Q's per-connection rule catalog cleaner. *Alternate:*
   **Q before O** if go-to-market wants the differentiator (Q4 caveats-in-answers)
   before parity — Q's hard dependencies are only on landed work (V3 publish, monitors,
   profiler, A4 inbox).
4. **S last** because it composes everything: G's tags (Domains), O's format spec
   (answer rendering, #189), Q's health results (answer caveats), C's graph (entity
   pages, J6). Same argument as the old program, now with more to compose.

---

## 2. Wave L — Leverage (the activation arc)

**Thesis:** a fresh clone must behave like the platform the docs describe. 87 flags /
17 ON is the finding; E4 (grids) + E6 (promotion receipts) exist precisely to fix it
honestly. **L is measurement plus wiring, almost no new machinery.**

| # | What | The load-bearing detail |
|---|---|---|
| **L1** | **Background graph build + live-path writers.** Build the context graph as a side effect of explore/investigate (closes the ROADMAP §0 caveat: today only the C4 surface routes build it). When an investigation lands a finding or a brief publishes, write the `finding`/`brief` node and `grounded_in`/`derived_from` edges *at that moment*. | The two committed graphs have **zero** finding/brief nodes — the read-back protocol's reason to exist is unexercised. Writers exist; they are not called on the live path. |
| **L2** | **Graduate `graph.readback`** via an E4 grid (readback on/off) through the E6 gate. | Measure: % answers citing graph nodes, pass-rate delta vs noise floor (J3 — floor before delta), request cost per answer. |
| **L3** | **Graduate `closed_loop`** (verdicts → corrections → priors) the same way. | The loop is complete end-to-end and ships disabled. |
| **L4** | **Graduate `automations.source_probes` + `automations.engine`.** | A5's equivalence receipts (same alert severity/message/debounce) already exist; cite them. |
| **L5** | **Seed real curation + prove distribution.** Flagship demo connection gets ~20 glossary terms, 3–5 trusted queries, 2–3 overrides; export the C6 pack from it; the pack becomes fixture + demo + docs. | Zero-adoption mechanisms rot; one override file exists in the tree today. |
| **L6** | **Close the E4 measurement debt:** A/B `ada.evidence_stubs` (rows-vs-tokens with answer-quality measured) — the sixth customer the flag-graduation audit named. | Runs as scheduled batches inside the free 1,000 req/day (J3 rule). |
| **L7** *(opt)* | **V3b wiring** — canvas/dashboard/eval-case artifacts onto the V lifecycle (the deliberate deferral, now that V is landed). | Ride-along if V merges cleanly; otherwise slips to S without harm. |

**Pre-registered gates:** (a) fresh clone + demo connection + one `/investigate` ⇒ graph
exists with ≥1 finding node and its `grounded_in` edge, no manual build step; (b) every
flag flip in L cites an E6 `GraduationDecision` receipt with measured before/after — a
flip without a receipt is the bug; (c) suite time does not regress past the 3-minute
hermetic baseline. **Effort:** 4–6 PRs, request budget mostly in L2/L3/L6 grids.

---

## 3. Wave G — Governance (as planned, enriched by the studies)

Everything the 2026-07-24 program scoped for G, plus the teardown's governance findings.

| # | What | Source |
|---|---|---|
| **G1** | `govern.guard` into the **9 unenforced `_RISK` actions**; undeclared ⇒ blocked (the anti-pattern table's read-by-default rule). | K follow-on (unchanged) |
| **G2** | **Tag plane + clearances before roles.** Tags as governed key-values on connections/tables/artifacts; clearances gate retrieval and action, roles come later. | Program v1 + UC tags |
| **G3** | **Audit categories with the LLM call as a first-class event** + **usage attribution**: J8's `llm.*` counters rolled up per org/user/feature into a usage page, with documented copy-paste cost SQL against our own session log. | Program v1 + teardown §3.7 (metered-SKU honesty) |
| **G4** | **Org usage caps with honest budget algebra**: shared + per-user thresholds, alert-vs-block actions, most-permissive-within / most-restrictive-across, enforcement never claws back in-flight work, and a typed `budget_exceeded` error in the R4 tail. | Teardown §3.7 (Genie budgets) |
| **G5** | **Permission-trimmed context retrieval**: graph read-back, trusted-query retrieval, glossary and synonym resolution all respect G2 clearances. The R4 rule holds: a clearance block *says so* out-of-band — never an empty answer (Genie's empty-response is the pinned anti-pattern). | Study D-6 + R4 ratchet |
| **G6** | **Grant surface + run-as honesty**: J2 standing grants listed/revocable in the trust receipt; connection run-as surfaced on every answer; **sealed trusted programs** (executed, never displayed — clearance-gated formulas). | Program v1 + teardown (opaque SQL functions, split-credential lesson) |
| **G7** | **Lineage-aware cascade invalidation** on V5's enforced purge cascade (not a hand-maintained list) + per-user-credential audit of the knowledge connectors (Notion/Confluence follow the per-user-OAuth rule). | Program v1 (J5/V5) + teardown |

**Gates:** ratchet test proves all 9 `_RISK` actions refuse without a grant; a
clearance-lacking user's answer never contains trimmed rows *and* names the block
out-of-band; usage page totals reconcile with `GET /dev/stats` counters; every
auto-allowed run cites its grant in receipt + audit row. **Effort:** 5–7 PRs.
Deterministic to build (zero model quota).

---

## 4. Wave O — Ontology parity + edge (the competitive-response wave)

**Scoping doc first** (`WAVE_O_ONTOLOGY_ARC.md`), Foundry-style — O touches five stores
(ontology, overrides, glossary, metrics, ambiguity ledger) and must be mapped before
code, exactly like C and V were. The settled checklist (entities/relationships, metrics,
synonyms, verified queries, instructions) is table stakes; O's edge items are what Genie
cannot do (git-native governance, measured semantics, honest binding).

| # | What | The load-bearing detail |
|---|---|---|
| **O1** | **The vocabulary plane**: first-class per-connection **synonyms** (subject_kind + subject_id + synonym + source rank human>mined>llm_candidate); **entity-matching value dictionaries** (profiler-fed low-cardinality value lists, RLS-respecting — generated under a service context, never a user's; Genie's own leakage carve-out); **display_name + typed format spec** per metric/property (currency/percent/decimals/compact — the declared fix for standing item #189). | The one hard checklist gap. YAML, git, override-wins — same discipline as `data/ontology_overrides/`. |
| **O2** | **Re-key glossary + metrics per-connection.** Global entries become `connection=*` defaults; scoped entries shadow (override-wins). | The acknowledged debt (`context_graph.py:99`); the #198 shape: "a store keyed without the dimension distinguishing its owners." |
| **O3** | **Retrieval ranking from usage** — order candidates by ledger `record_hit`, drill records, trusted-query usage, V-freshness, source rank. **Never edge evidence** (J4 stands; ontorank's idea at the only honest layer). | One human YAML override still beats any popularity score — the governance story Genie lacks. |
| **O4** | **The generalization loop** (Snowflake's capture→verify→generalize→suggest with Aughor's binding rigor): mine accepted verdicts, trusted queries, and — at connection onboarding — the source's saved/dbt/query-log SQL, into **typed candidates** (join / measure / filter / synonym / object-set). Candidates land in the **A4 resolve-once inbox**; the two Genie modals (teardown §4.1–4.2) are the UI spec; **every candidate EXPLAIN-binds before it is offered** — unbound SQL is never even shown. | The compounding-accuracy flywheel. Nothing auto-applies (E6's philosophy, Genie's "telemetry, never training" — parity made policy). |
| **O5** | **Window/semiadditive measure vocabulary** on `OntologyMetric`: `order` / `range` (current·cumulative·trailing·leading·all) / `semiadditive: first\|last` / `offset` for period-over-period. "YoY growth," "trailing 7d," "balance at month end" become *declared* measures the planner instantiates — not per-query LLM SQL. | Teardown B-8; the UC metric-view frame algebra is the reference spec. Guards already catch violations; this moves correctness from post-hoc to by-construction. |
| **O6** | **Declared exclusions + coverage rollup** (unmapped ≠ out-of-scope, per-connection green/orange/red) and **semantics drift checks**: scheduled cheap probes re-validate declared cardinality/grain/active_filter; a violated declaration flips the edge `dirty` (V vocabulary) and surfaces as a caveat. | Ontobricks' two best ideas. Genie *documents* that a wrong cardinality promise silently corrupts; Aughor **checks the promise** — the marketing line. |
| **O7** | **Interchange + connection-as-code**: OSI v1.0 YAML import/export; C6 becomes a **round-trip** — export/import the full curation bundle (ontology + overrides + synonyms + trusted queries + glossary + graph) through the *same YAML stores*, no new bundle format. | Databricks is absent from OSI — "we speak the open standard" is a positioning line. Their `serialized_space` is the JSON-blob version; git-native YAML beats it. |

**Gates:** two connections with a same-named metric resolve differently and both
correctly (O2 isolation test); synonym resolution measurably changes linker candidates on
the eval suite with no pass-rate regression beyond floor (O1×E4); a candidate that fails
EXPLAIN-bind is refused with the reason, tested (O4); "YoY revenue" eval cases pass with
the window measure declared and *fail honestly* without it (O5); an OSI file from
Snowflake's examples imports to a usable ontology (O7). **Effort:** scoping doc + 7–9
PRs; O4/O5 grids spend requests — scheduled batches, free tier.

---

## 5. Wave Q — the Quality plane (table health → answer caveats)

**Scoping doc first** (`WAVE_Q_QUALITY_ARC.md`) — Q's one structural rule is set before
code: **no second quality store** (J12). Monitors, checks, and profiler findings write
one results store or Q recreates the five-eval-surfaces mistake Wave E existed to fix.

| # | What | The load-bearing detail |
|---|---|---|
| **Q1** | **Rule catalog**: declarative checks (name, criticality `warn\|error`, function + args, filter, for_each_column) per connection as YAML; **SHA-256 fingerprints per rule and ruleset, metadata excluded from the hash** (annotation edits ≠ new versions — DQX's exact trick). ~12 BI-trust checks compiled to source-dialect SQL via the existing sqlglot path: not_null, unique/grain, FK integrity, in_list, range, freshness-vs-SLA, row-count drift, accepted-values drift. | Criticality is data, not code: the same check warns or blocks per rule. |
| **Q2** | **Profile → candidates → review**: profiler thresholds (null_ratio, distinct ratio, min/max) emit deterministic candidates into the **same A4 queue** as O4, same modal UX. LLM proposals allowed as *additional* candidates, syntax-validated, never auto-applied. | DQX's generation discipline, Aughor's queue. |
| **Q3** | **Persisted results, one store**: per-table pass/fail counts + run_id + ruleset fingerprint; monitors' outputs (threshold/anomaly/drift/freshness) unify into it; graph table-nodes gain health provenance; results are V-freshness citizens (fresh/dirty/stale applies to health verdicts too). | The run_id spine: artifact ↔ metrics ↔ ruleset version. |
| **Q4** | **Caveats ride the answer** (the first-mover feature): tables in the executed SQL join against latest health results at answer time; failures within severity/age thresholds render inline with provenance — *"`orders` failed freshness 2 days ago (expected daily; last row 2026-07-23)."* `warn` annotates; `error` can gate V3 publish. | Nobody ships this; Aughor's `trust_caveat` threading is ~2 PRs of glue away once Q1–Q3 exist. |

**Gates:** editing a rule's note does not change its fingerprint (test); an answer over a
failing-freshness table renders the caveat with rule name + run id; a `error`-criticality
failure blocks publish with the reason and an override path; ratchet test proves monitors
and checks share one results store. **Effort:** scoping doc + 4–5 PRs. Deterministic.

---

## 6. Wave S — Surface & composition (Genie One is the blueprint)

Everything S inherits: entity pages = C's graph rendered (J6, unchanged), next-action
verbs, typed module interfaces, packs-as-products — plus the teardown's surface map.
`web/` today is a single-page shell; S is where that changes.

| # | What | Composes |
|---|---|---|
| **S1** | **The consumer surface**: routing (curated-first), listing pages with Certified/Favorite filters, **For you** (recently opened / favorites / trending from drill records), **Domains = G2's tags rendered** (J13), **entity pages = graph nodes rendered** (J6). | C, G2 |
| **S2** | **Answer anatomy**: receipt rendered as expandable analysis; **verified badge** when a trusted query served the answer; **freshness-rung label** (live/cached/mirror/upload/frozen + as-of) on every answer; per-column formats from O1's spec — **#189 closes here** (declared in O, rendered in S). | R4, V, O1, Q4 |
| **S3** | **The loop UX**: Fix-it flow (typed what-was-wrong → `record_verdict` → priors); add-as-instruction / add-as-benchmark kebab on any answer; ground-truth update + per-case overrule on the E5 surface; **accuracy as a per-connection product number** with trend; auto-suggested benchmark cases from session-log gaps. | E5/E6, O4, L3 |
| **S4** | **Digests**: weekly workspace brief on Aughor's own exhaust (volume, abstentions, feedback trend, top suggested curation actions from the O4/Q2 queues) — briefs dogfooded. | A5, G3 |
| **S5** | **Task + document surfaces**: scheduled-task threads for briefs/automations (@mention-able, delivery receipts); document canvas with click-through citations; opt-in **cited memory** = ambiguity-ledger choices surfaced as "remembered, cited, revocable." **V6b** (lifecycle React panel) and K5's "annotate this cell" land here. | A, V6b, ledger |
| **S6** | **Distribution**: MCP server extension (`describe_entity`, `search_graph`, `get_table_health`, `list_trusted_queries`); `llms.txt` + `AGENTS.md`; **OpenAI Responses-compatible façade** over ask/investigate (typed R4 errors slot into its taxonomy); the docs-presentation playbook (limits tables, symptom→fix troubleshooting, verbatim prompts, per-page last-updated, annotated screenshots). | F-1/2/3, teardown §5 |

**Gates:** entity page renders from the committed graph with no extra source queries; the
accuracy number and its history render per connection; an end-to-end Fix-it: thumbs-down
→ typed correction → next answer on the same question cites the correction; an unmodified
OpenAI SDK client completes an ask round-trip against the façade. **Effort:** 6–8 PRs;
the largest frontend wave — pair with a design pass.

---

## 7. New joints (J9–J15, continuing J1–J8)

- **J9 — L graduates only through receipts.** Activation is measurement, not
  flag-flipping: every default flipped in L cites an E6 `GraduationDecision`. A flip
  without a receipt reverts on review.
- **J10 — One review queue.** O4, Q2, and S3's suggestions all land in the A4
  resolve-once inbox. A second queue store is the bug (the five-surfaces lesson).
- **J11 — #189 has one fix, split across two waves.** The format *spec* is O1
  (declared in the ontology); the *rendering* is S2. No chart-level formatting
  hacks in between.
- **J12 — Q writes one store.** Monitors, checks, and profiler findings share results;
  health verdicts speak V's freshness vocabulary (a stale health verdict is itself
  `stale`, not silently authoritative).
- **J13 — Domains are tags rendered.** S1's discovery pages read G2's tag plane; no
  separate domain store.
- **J14 — Measured-over-declared stays the law.** O6 *validates* what Genie merely
  declares; O3's ranking orders retrieval and never creates or weights edges (J4
  unchanged). Popularity is not evidence.
- **J15 — Connection-as-code round-trips the real stores.** O7's bundle is the same
  YAML files (overrides, synonyms, checks, glossary) exported and re-imported — a
  view over the stores, never a parallel format.

## 8. Standing items — dispositions in this program

| Item | Home |
|---|---|
| ROADMAP §0 caveat (no background graph build) | **L1** |
| `ada.evidence_stubs` A/B debt (Wave R) | **L6** |
| V3b (canvas/dashboard/eval-case wiring) | **L7** (opt) or S5 |
| V6b (lifecycle React panel) · K5 "annotate cell" | **S5** |
| 9 unenforced `_RISK` actions | **G1** (unchanged) |
| Sub-1 shares render `0.275985` not `27.6%` (#189) | **O1 (spec) + S2 (render)** — J11 |
| `trigger_investigation` seam (task chip `task_401e3882`) | ✅ **Shipped as H5** — `aughor/runners/investigation.py`; both executors call the neutral runner, as planned here |
| Ontology-overrides root env override (chip `task_275035a4`) | Ride **O2** (same hermeticity class) |
| K2b — `query`-kind dispatch through the read-only executor | Ride **G1** |
| Stale rejects in `exploration_workspace.json` | Standalone chore, any live-server session |
| P7 frontier tier | Stays decided; re-opens only inside E4 grids (L2/L3/O4 batches) |

## 9. Rules of engagement

§6 of [`PLATFORM_PROGRAM_2026-07-24.md`](PLATFORM_PROGRAM_2026-07-24.md) applies verbatim:
default-off flags byte-identical when off (L is the *sanctioned* flipping mechanism —
through receipts); pre-registered gates; live-path proof before "done"; snapshot `data/`
before full-suite runs; push once per branch, one push/PR/merge per authorization, CI
advisory; strictly `:free` bindings with model-heavy gates budgeted; the anti-patterns
table binding — **plus the three added by these studies:** no popularity-as-evidence
(J14), no second store for queues (J10) or quality results (J12), and no silent-empty on
policy blocks (R4's rule, now a product principle: *a block says so*).
