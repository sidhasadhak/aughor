# Aughor — Feature Reference

**Product:** Aughor — an autonomous, grounded data-warehouse intelligence platform.
**This document:** a tight, current map of what Aughor does, organized by capability area. The full
chronological build log (171 numbered features, sprint by sprint) is preserved verbatim in
[`docs/archive/FEATURES_full_2026-06-29.md`](docs/archive/FEATURES_full_2026-06-29.md) — consult it for
per-feature detail, history, and the technology behind each increment.

> **One-line thesis:** not a SQL copilot — an always-thinking analyst that builds a business ontology,
> explores continuously, and is engineered so *the numbers are trustworthy, not just plausible*.
> Values, in priority order: **trustworthiness > autonomy > discipline (test ratchets) > local/privacy > breadth**.

---

## 1. One conversational agent — depth chosen for you (`POST /ask`)

A single conversational entry decides **how deep to go** instead of making the user pick a mode up
front (BIRD-INTERACT-driven, arXiv 2510.05318). A **deterministic-first router** (`aughor/agent/ask_router.py`)
picks the depth — clear lookup → quick, causal/complex → deep, with no model call on the obvious cases;
the user sees a `route` receipt explaining *why* and can re-run at another depth (**auto + transparency**).
The underlying depths:

- **Quick (Insight)** — fast NL→SQL→answer with auto-charting and a plain-English headline.
- **Deep / ADA** — an autonomous investigative loop: decompose a question into hypotheses, run
  evidence-gathering SQL, synthesize, and report with a confidence verdict; resumable and crash-recoverable.
- **Explorer** — background autonomous learning: continuously probes connected warehouses to build and
  refresh the ontology, surface findings, and seed suggestions.

On top of the depths, the conversational agent (the unified-answer-path arc, PR #89):

- **Ask-vs-guess clarification** — when a question is materially ambiguous it asks **one** targeted
  question instead of guessing: deterministic under-spec + value-term detection (`aughor/agent/clarify.py`)
  **plus SOMA candidate-disagreement** (`aughor/agent/soma.py`) — generate N candidate readings, execute
  them, and ask **only when their results diverge**, with each reading surfaced as a grounded option chip
  **carrying its result preview** (`= 68` vs `= 1131`), so the divergence is visible before you choose.
- **The Ambiguity Ledger — resolution that COMPOUNDS** (`aughor/semantic/ambiguity_ledger.py`) — when an
  ambiguity is settled (by an execution probe, by the user's clarify choice, or by a reviewer verdict) the
  resolution **crystallizes as a first-class, per-connection record** and is read back as an authoritative
  plan-time prior (`verify/priors.py`, the leading block on the live answer paths). Idempotent burn-down
  (one row per dimension), **override-wins** authority (verdict > user > probe — machinery never clobbers a
  human decision). So the same question class never re-ambiguates: ambiguity **burns down per connection**
  instead of re-paying a probe pipeline every question. Flag-gated (`closed_loop`); `ledger_stats` reports
  the burn-down (served-from-ledger vs freshly asked).
- **Interactive metric clarify — pause, ask, remember** (`ada.clarify_gate`) — when a metric's GOVERNED reading and
  the LLM's parsed reading both run over the metric table but give **materially different numbers** (the count-vs-value
  split — e.g. a value-weighted 27.8% vs a count-based 26.2% return rate), a deep run **pauses before the scan** and
  asks which reading you meant, showing **each reading's probed value**. It is a real interrupt/resume gate — a faithful
  sibling of the editable plan gate — so the run genuinely halts and continues on your answer (not an ignorable banner).
  Your choice binds the metric for the run and crystallizes to the Ambiguity Ledger (source=user, override-wins), so a
  subsequent run **hard-binds it and never re-asks** (precedence: resolution > clarify > canonical pin). Off by default;
  fires only on a genuine divergence, at most once per run.
- **Conversational follow-ups** — "now break that down by region / just for the ultra tier" composes on the
  prior query (`aughor/agent/followup.py` + a result digest carried across turns), on **every** path: the
  quick Insight path, AND the deep/Direct-lookup path (a follow-up in a canvas anchors on the previous turn's
  query via an origin-finding seed — kept its metric/filters/grain, extended by the new dimension).
- **Progressive escalation (ITS)** — a quick answer that's inconclusive (errored, empty on an analytical
  question, or a "why" answered by a single figure) **offers** a deeper investigation rather than leaving
  a thin answer (`aughor/agent/escalate.py`).
- **Measured discipline** — every interaction feature is gated by the interactive eval harness
  (`evals/interactive.py`, `evals/ambiguity_eval.py`, `evals/its_structural.py`): built and measured
  before it ships (the SOMA build was justified by a measured 0/6 detection gap + a 0/3→3/3 asking gain).

All depths share **one SQL-safety pipeline** (`aughor/sql/safety.py` `preflight_repair`) and **one
data-understanding context**, so quick and deep stay at parity (mode cross-pollination). `/chat` and
`/investigate` remain as back-compat shims.

## 2. Grounded NL2SQL & trust guards (the core differentiator)

Deterministic, execution-grounded guards over LLM-generated SQL — each ships with a test that proves it fires.

- **Unit-conversion guard** — a planner-invented "stored in cents" ÷100 on a money column is detected at
  intake **and at every phase's fresh SQL**; one data probe (a multiplicative sibling relation like
  `totalPrice = unitPrice × quantity`) proves the true unit — proven wrong → stripped with a structured
  note, unproven → kept but explicitly caveated. Paired with a **money-coherence retry** (a money question
  with a COUNT-only metric is re-parsed once).
- **Join-coverage guard** — the deflation counterpart to the fan-out battery: an INNER JOIN that drops
  base rows (a dimension map covering half the fact table) is probed (joined SUM vs base SUM) and the
  finding caveated + confidence-capped instead of shipping an understated total at High confidence.
- **Explicit depth binds** — `/investigate` stamps the user's Deep Analysis choice into the run; the LLM
  route classifier can never silently downgrade it to a direct lookup.
- **SQL self-correction** — `SqlWriter` centralizes generation + deterministic bind-error repair (no-LLM
  candidate substitution first, typed LLM repair as fallback, every candidate dry-run-validated).
- **Error classification & SQL hardening** — classify a failure by root cause, inject the right fix hint.
- **Connector-capability contract** (`capability.contract`) — a machine-checkable per-dialect descriptor
  (`db/capabilities.py`) of constructs that error on each native warehouse (QUALIFY/ILIKE/SAFE_DIVIDE/DATE_TRUNC/…).
  It seeds an "avoid these" line into the SQL-writer prompt (pre-empting the footgun) and, when a native-dialect
  query still fails, names the exact unsupported construct in the repair prompt (fewer dry-run round trips).
  Deterministic; permissive for transpile-from-DuckDB dialects (Hasura-NDC-inspired, DataAgentBench).
- **Fan-out / grain guards** — deterministic de-fan (parent + chasm), AVG-over-chasm linter, and a
  uniqueness-probe grain guard (`COUNT(*)` vs `COUNT(DISTINCT key)`) that flags over-counting on real data.
- **Value-domain join guard** — refuse/repair joins whose key domains don't actually overlap ("fool-proof joins");
  when a mismatch fires, **ill-formatted-key reconciliation** (`join.key_reconciliation`) tries deterministic
  normalizations (digits-only, strip-prefix, trim/case) and surfaces the exact normalized join when the keys are
  the same entity in a different format (`bid_123` ↔ `bref_123`) — in-source and across sources (DataAgentBench GAP-3).
- **Filter-literal binding** — a guessed enum/literal that matches no row is bound to its confirmed stored
  value (`'cancelled' → 'canceled'`), including a CHESS-style trigram value index for high-cardinality columns.
- **Measure-additivity layer** — per-unit vs per-line grain, ratio-of-sums (never AVG of per-row ratios).
- **Semantic compiler** — typed intent IR → deterministic SQL for the well-specified core.
- **Result-trust checks (CIDR-E1)** — flag function-semantics footguns (timestamp vs date-literal boundary,
  lexicographic order of numeric text, text↔numeric comparison) as labelled caveats, never overwriting the query.
- **Finding-trust ladder** — guards → quarantine → dismiss-with-reason; pre-emission insight verification;
  numeral grounding; ratio-aware cross-sectional scans; angle-feasibility + repair intent-preservation gates.
- **Numeric grounding, reconciled** — a claimed figure is credited when it appears in the result cells **or is
  derived from them** (a % change / share / delta), so the grounding advisory stops crying wolf on valid
  arithmetic; a fired trust caveat then **caps report confidence** (HIGH→MEDIUM, so "high confidence" can't sit
  beside "claim not grounded"); and each narrator finding **binds to the query whose cells actually contain its
  numbers**, so a z-score card can't inherit a period-over-period finding's figures just because both are "by tier".
- **Grain-aware cross-section** — an **event-only** dimension (return reason/condition) is read as a
  **composition** (share of the event), never a tautological "rate by it" (which is always 100%);
  a **saturated** result (every group pinned at 0/100%) triggers a single grain-corrected reattempt; and
  discriminating **population attributes** the plan missed (a joinable table's price band / season) are
  surfaced deterministically, gated by a uniqueness probe so the added join can't fan out.
- **One canonical grain + temporal feasibility** — every lens of a "why is X high" investigation computes
  the metric at the **same unit of observation** (the metric table's grain, via a denominator-pinning plan
  directive), so the WHERE/WHY/WHEN cards can't contradict each other (per-order 40% vs per-line-item 76%);
  and the event-rate-aware **temporal-axis recovery** runs at **intake**, so a metric on a dateless child
  table still trends on the join-reachable purchase date instead of being declared non-temporal.
- **Period-comparison integrity guards** — a period-over-period comparison is trustworthy only when the two
  windows are like-for-like, so three deterministic guards run at **intake**: a **duration-mismatch** guard (a
  prior window far shorter than the observation — the ~18× "56-months-vs-3-months" artifact), a **density**
  guard (a window whose calendar span is fine but is sparsely populated — an internal gap/ramp), and a
  **trailing-partial** guard (an incomplete final period that reads as a false drop). When one fires it is
  **enforced**, not merely advised: the absolute-change waterfall is neutralised and the summary reframed to
  average per-period run-rate, so the report can't headline a duration artifact the narrator was told to avoid.
- **Global-ratio plausibility guard** — for a cross-table rate (`SUM(event)/SUM(population)`), a per-segment
  scan that inner-joins the denominator *through* the numerator's event table silently counts only the
  population that already had the event — inflating every segment (a refund rate of ~73% when the truth is
  ~10%) with no row fan-out to trip the other guards. The metric's **true global level is recomputed
  independently** (each aggregate over its own full table), and when every scanned segment sits ≥2.5× above it —
  the systematic-inflation signature of a conditioned denominator — the corrupted numbers are **suppressed** and
  the caveat **states the true global**, so a broken ratio can't be headlined as a business finding.
- **Sustained level-shift detection** — a "why did X change?" investigation no longer relies on single-point
  anomaly detection alone (which is blind to a gradual multi-period shift where no single point is an outlier —
  a real −6.4% year-over-year decline dismissed as "within normal variance" because the mean gap was divided by
  a single-period σ, wrong by √n). A **Welch two-sample test** on the series' earlier-vs-later halves
  (SE = √(s₁²/n₁+s₂²/n₂)) runs alongside, and a material, statistically-real shift **proceeds to dimensional
  decomposition** instead of a Tier-0 "it's just noise" abstention that lists the dimensions it never queried.
- **Structural trust caveat** — a computation-error trust check (conditioned denominator, fan-out, formula
  drift) now **leads the executive summary with an honest reframe and floors confidence to LOW** *when a flagged
  finding's numbers are actually headlined* (its figures appear in the conclusion, checked by numeric grounding);
  a peripheral flagged finding whose numbers don't reach the conclusion is surfaced in the data-gaps instead of
  nuking a grounded answer — rather than only capping HIGH→MEDIUM while the flagged figures ride into the headline.
- **Render-boundary number hygiene** — a report never ships a raw 17-significant-digit float in prose: any
  over-long decimal run in a headline/summary/narrative is deterministically rounded to display precision (the
  "0.20829576194770064" miss), on both the investigate and explore paths.
- **Fraction↔percent prose consistency** — when the metric is a percentage, a value written BOTH ways in the same
  prose ("0.208" next to "20.8%") is normalized to the percent form. Self-grounded: a fraction is rewritten only
  when its ×100 value is literally present as an explicit percent in the same text, so an unrelated sub-1 number —
  a correlation `0.82`, a p-value `0.05`, a `$0.50` price, a `0.36 pp` spread — is never rescaled.
- **Inspectable exploration traces** — a "what's driving X?" exploration forwards **every** sub-question's SQL,
  rows, and result (not just the final one), emits a **per-step progress event** as each sub-question completes
  (no multi-minute silent gap on the parallel-wave path), and — because each step now carries its own result —
  **charts every step** through the existing per-result renderer.
- **Live per-dimension scan progress** (`ada.progress_events`) — a Deep-Analysis cross-section / decompose scan
  streams a progress event as **each dimension query completes** ("scanning brand · 3/6…"), so a multi-minute
  phase reports what it's doing DURING execution instead of a silent spinner between phase-complete events. It is
  a genuine mid-node → SSE channel: a best-effort in-process sink bound inside the scan's execution context and
  carried through its worker threads into the response stream (no extra model cost). Off by default = byte-identical stream.
- **Data-coverage transparency** — intake runs one deterministic `MIN/MAX(date)` probe and the report states the
  **real coverage window** it analyzed (populated even for a cross-sectional scan, which used to blank it), and a
  sample-inferred observation window that falls outside the real data span is replaced with the probed one.
- **Metric-definition receipt** — every report states **how the metric was computed** in plain language (formula,
  and for a ratio whether it's a value-weighted `SUM/SUM` or a count-based rate — the two can differ and the
  reading was chosen automatically), so a silently-picked definition is visible and challengeable, not buried.
- **Canonical-metric pinning at intake** (`ada.pin_canonical_metric`) — when a deep investigation parses a metric
  the connection already GOVERNS (curated catalog · connection north-star · verified ontology), the intake's
  formula is **pinned to the governed one** so the cross-section scan decomposes on a stable, canonical definition
  instead of a run-varying LLM guess (the count-vs-value "refund rate" that left the breakdown un-decomposable →
  "cause remains unidentified"). Fail-open: it only replaces the LLM formula when a governed metric matches the
  label on its distinctive tokens, its SQL is a bare substitutable aggregate, AND a dry-run confirms it runs over
  the metric table. Deterministic; the resolution also **crystallizes to the Ambiguity Ledger** (source=probe) so
  it compounds per connection to every path.
- **Verdict↔recommendation coherence** — the cross-phase contradiction detector now also checks the **headline
  against the recommendations**: a verdict that rejects the premise ("X is not the problem") or reports no
  material issue while still shipping actionable recommendations is flagged, instead of reading as "no contradiction".
- **Tiered adversarial verification** (opt-in, `ada.adversarial_verify`) — a ReFoRCE-style skeptic pass that fires
  **only** on a decision-changing verdict (a premise rejection or an abstention) to try to refute it before
  shipping; a surviving refutation records the objection and caps confidence **HIGH→MEDIUM**. Off by default (one
  extra LLM call on those runs); the deterministic default path is unchanged. A cheaper **materiality-gated tier**
  (`ada.adversarial_high_stakes`) spends the skeptic call **only on a HIGH-confidence** decision-changing verdict —
  the costly-if-wrong minority, and the only case where the cap can bite (confidence-triggered activation).

## 3. Evidence, trust receipts & statistical rigor

- **Statistical Evidence Engine** — significance, effect size, and direction behind every claim.
- **Evidence Ledger / Trust Receipt** — per-answer lineage: executed SQLs, input tables, which guards fired,
  earned confidence (`kernel/ledger.py`, `_write_answer_receipt`) — **and any resolved ambiguity the answer
  applied** ("followed a previously-resolved reading, settled by a probe / the user / a reviewer"), so the
  compounding machinery is inspectable, not hidden (`web/components/TrustReceipt.tsx`).
- **Finding Dossier** — drill-down is a *read* of captured derivation, not a second (re-)analysis.
- **Outcome tracking & feedback loop** — close the loop on whether findings were acted on.

## 4. Business intelligence layer (ontology · metrics · glossary)

- **Business ontology** — auto-built object sets + computed properties + causal graph; refreshed by the
  domain-intelligence loop; **per-schema isolated**; org-level ontology board.
- **Human-editable, version-controlled overrides** — YAML ontology with override-wins; a Phase-8 gate
  binds every per-domain block against the live schema (dry-run/EXPLAIN as the universal binder).
- **Metrics catalog** — governed metric definitions, targets & health scorecard, one unified resolver
  (`UNIFY`) shared by chat and Deep Analysis, with cross-connection leak prevention.
- **One metric contract** — a governed metric (curated catalog · connection north-star · ontology-derived)
  resolves to a single `SemanticContract` type the whole platform points at: one precedence rank (catalog >
  north-star > verified-ontology > unverified), one render-authority signal, one dedup. Planning renders from
  it and `/query/semantic-context` surfaces it, flag-gated (`semantic.contract_live`) and byte-identical off —
  the "20-year ontology bet" type unification (REC-U10).
- **Business glossary** — manual + dbt-manifest + LLM auto-seed (override precedence), injected into context.
- **Industry-aware intelligence** — `BusinessProfile` + per-industry metric knowledge base.

## 5. Data understanding & schema intelligence

- **Profiling** — per-column stats (distinct/null/range/top-k/semantic-type), cached by schema fingerprint.
- **Join inference & fingerprinting**, **FK-neighbour expansion**, value-verified join edges + "DO NOT JOIN" hints.
- **Schema linking & compression** — trim wide schemas to the relevant tables; collapse sharded/dated table families.
- **Query-log mining** — learn real join paths, value domains, and business formulas from past queries.
- **Vector search over schema** + semantic suggestions cache (Qdrant); ER diagram; rich schema-card UI; data catalog.

## 6. Connections & data ingestion

- **Multi-database connectors** — DuckDB, Postgres, Snowflake, BigQuery, SQLite (first-class), and more;
  Fernet-encrypted DSNs, exclusive-checkout pool, health checks.
- **Add data** — new connectors, **bulk-CSV import** (with catalog-delete intelligence cascade), workspace
  file uploads (size-capped), **document ingestion** as a context layer.
- **Integrations** — dbt (manifest-driven glossary/metrics), Superset (ECharts engine + per-dialect rules).

## 7. Briefings & proactive monitors

- **Proactive monitors** + **scheduled brief delivery** on the kernel event spine (anti-flap).
- **Briefing live dashboard**, **CEO-grade triage** (impact-ranked lead, trust gate, currency),
  **interactive briefings** (interrogate the brief in place), conclusion-first design.
- **Briefing trust** — gated on governed metrics with live re-validation; multi-tier dedup; metric-explainer charts.

## 8. Query Builder

A first-class, schema-qualified query surface: bounded preview, saved queries, first-class time range &
grain (with grain-misuse warnings on metric chips), HAVING + distinct-value picker + CSV export, a real
SQL editor (highlight + format), a chart-type gallery + customize panel, pivot mode, and "open in Query
Builder" from Insights/Deep. Schema-qualified correctness; user-typed SQL is **gated** (no safety bypass).

## 9. Charts & the answer surface

- **Identifiers are never measures** — one camelCase-aware `isIdLike()` shared by the column classifier,
  chart inference, LLM chart-config validation, captions, and the PDF export renderer, so `franchiseID`
  can't be plotted (or captioned) as a quantity on any surface; export grouped bars also drop >25×
  scale-gap series and prefer name columns over ids on the category axis.
- **Genie-grade report presentation** — a collapsible thinking trace with nested, named query steps;
  clean-output policy (no internal phase headers — method lives in a Details disclosure); per-finding
  numbered **Sources** (claim → numbered query → SQL); criterion-complete extreme-tie enumeration;
  adaptive temporal grain (a 17-day window charts daily, never one monthly point); humanized scan labels
  ("revenue", never "metric_total"); full-panel-width answers; one currency per metric card.
- **Auto-charting** on one **Apache ECharts** engine (chat + report + explorer + query builder share it),
  with **intent-driven chart selection** — the chart follows the finding's *narrative*, not a data-shape
  guess: composition → **donut** (parts-of-a-whole) / ranked bar, trend → **line**, ranking → **sorted
  horizontal bar**, relationship → scatter; plus **100%-stacked** (composition-over-time) and
  **small-multiples** (many-group trends). One shared column-role classifier (`columnRoles.ts`) feeds both
  inference and rendering. Fixed bar thickness + count-adaptive height, on-by-default data labels with
  overlap-drop, nice-axis/headroom + apply-able customize knobs, sub-day grain axis handling. See
  `docs/CHART_SELECTION_GUIDE.md`.
- **Consistent numbers everywhere** — a backend per-column **unit hint** (`column_units`) drives one
  scale-aware formatter so a rate reads **"41.0%"** on the chart axis, the data labels, AND the key numbers
  (never "0.4" / "0.41%" / "40.96%" for the same value); a temporal peak/trough is recomputed from the full
  series so it matches the chart.
- **Source-data panel** — a **"Source data"** trigger on every finding chart (report + quick answer) opens
  a right-side drawer: the result table + the **SQL at 50%** + an **"Explore with Query Builder"** hand-off.
- **Chart source-footers** — a provenance line under every exhibit ("Source: order_items · 12,345 rows ·
  Jan–Dec 2024"), derived from the query result (input tables, row count, date range) — a chart is only as
  trustworthy as its source, made inspectable at a glance.
- **The Brief** — the answer surface with agent-reasoning quality + data-shape intelligence. **One enforced
  3-tier design layer** (tokens → primitives → composites) behind it — a `StatusChip` vocabulary, a size-only
  type scale, and a **turn renderer registry** (`registerTurnRenderer`) so a domain pack can contribute a
  custom answer surface without a frontend release (the AI-native "the agent composes its own UI" seam).
- **KPI highlight / ThoughtSpot-style scorecard**, smart report formatting + collapsible sections,
  thinking trace, **PDF / PowerPoint export**.

## 10. Semantic operators over SQL

LLM-grounded operators that compose with SQL: **filter · extract · top_k · aggregate**, hierarchical
tree-reduce synthesis, embedding-based entity dedup, a Query Builder "semantic step", and an AI-SQL operator.

- **Guarded extraction** (`semops.guarded_extract`) — the extract operator infers a type (year/date/email/
  number) from each field and re-extracts the off-type values with targeted feedback (a bounded gleaning loop),
  surfacing and keeping residuals rather than dropping them. Turns text extraction from regex-fragile into a
  self-correcting, type-checked step (DocETL gleaning; the DataAgentBench axis where frontier models score 0%).
- **Champion cost/quality cascade** (`semops.champion_validate`) — the filter operator runs on the cheap tier,
  re-judges an evenly-spread sample on the strong "champion" model, and escalates the whole batch only when they
  disagree beyond a bar — a label-free quality estimator in the Palimpzest/LOTUS lineage.

## 11. RAG & knowledge

- **Prior-investigations RAG** — reuse past analyses for similar questions.
- **SQL Knowledge Base** + pattern enrichment; **structured playbook** retrieval for metric/phase planning.

## 12. Platform & infrastructure

- **User-defined agents** (`agents.user_defined`) — reusable domain personas ("Gems on governed data"):
  an agent binds standing INSTRUCTIONS + a set of uploaded DOCUMENTS + a CONNECTION
  (`aughor/user_agents/`, store `data/agents.db`, CRUD `/agents/custom`). Answering via
  `/ask` + `agent_id`: the instructions lead the prompt (rules_block-style), document retrieval is
  restricted to the agent's bound documents (fail-closed — an agent with none sees none), the
  connection binding wins (a conflicting explicit connection is a 409, never a silent override), and
  the stream opens with an `agent` receipt event. Unlike a Gem/custom-GPT, the persona inherits the
  whole trust substrate — guards, receipts, RBAC — untouched. **Builder UI included**: the
  Intelligence-rail **Agents** panel (roster + create/edit with connection select + document
  multi-attach + enable toggle, `web/components/AgentsAdminPanel.tsx`), an agent picker on the ask
  composer, and an "Answering as …" `AgentBadge` receipt per turn. **Deep path included**: the
  persona persists in the run's checkpointed state (`AgentState.agent_id`) so a plan/clarify-gate
  resume re-activates it (fail-open), the brief leads the ADA synthesis prompt, and deep document
  retrieval is agent-scoped through the same seam as the quick path. **Schema + pack bindings
  included**: `schema_scope` pins the agent to one schema (conflicting explicit schema → 409) and
  `pack_ids` restricts specialist-pack selection to the agent's packs — a preference, never a
  deploy-gate bypass (the pinned-binding requirement applies unchanged). **Measured agents
  included**: each agent carries its own GOLDEN QUESTIONS (question + read-only reference SQL);
  `POST /agents/custom/{id}/evaluate` generates SQL as the agent, executes both, compares result
  sets deterministically (no LLM judges), and stamps the "n/m passing" chip — quality is measured,
  not vibes, which no Gem/custom-GPT builder offers. Slices 1–5 of the agentic-platform arc
  (`docs/DATABRICKS_OSS_AND_AGENTIC_PLATFORM_STUDY_2026-07-11.md` Part B).
  Off by default (routes 404, answer path byte-identical, picker hidden).
- **MLflow investigation tracing** (`obs.mlflow`) — every investigation exported to a self-hosted MLflow
  server as one inspectable trace tree: LangChain/OpenAI autolog creates the trace root per graph run (LLM
  calls with token counts), the existing `node_span` seam nests each graph node under it, and every guarded
  SQL execution (`sql/executor.py`) appears as a `TOOL` span carrying the SQL — searchable by
  `tags.investigation_id`. Third backend of the one telemetry seam (`aughor/telemetry.py`, beside
  Langfuse/OTel): lazy lock-serialized init, transient server failures retry on a 60s cooldown (never a
  process-lifetime disable), HTTP timeout/retries bounded so a dead server can't stall the answer path,
  and flipping the flag OFF **unpatches autolog** (no silent trace export after opting out). Client is
  `mlflow-skinny` (`uv sync --extra observability` — the full server distribution would downgrade
  pandas/cryptography); server via `docker compose --profile obs up -d mlflow` (localhost:5001).
  Engineer-facing observability only — answers, receipts, ledgers unchanged. Off by default = byte-identical.
  Phase 1 of the MLflow arc in `docs/DATABRICKS_OSS_AND_AGENTIC_PLATFORM_STUDY_2026-07-11.md`.
- **Functional-plane consolidation** (Part 2 of the 2026-07-03 review, flag-gated) — the diffused agent
  runtime is being re-drawn as clean horizontal planes, each with a typed contract + a conformance test:
  a **Trust plane** (`aughor/trust:verify(sql|code|metadata, scope) → Verdict`) hoisting the ~9 scattered
  validation guards behind one façade (the read-only/mutation gate now runs on the generation path too);
  a **Capability plane** (`aughor/capability`) — one `Generate→Validate→Execute→Interpret` template
  parameterized by domain (`data` SQL + `metadata` schema-Q&A), whose `validate` *is* the Trust plane;
  and a **Semantic plane** (`aughor/semantic/context.py:resolve → SemanticContext`) that resolves
  metrics/ontology/profile/KB **once** per run instead of ad-hoc, read back by the planner. Live-verified
  end-to-end (`POST /query/capability-answer`). Each plane is a swap-point; a new capability = register one impl.
- **One noun model at the boundaries** (Part 2 Wave 3) — **`ExecutionScope`** (`aughor/canvas/scope.py`):
  the canvas/connection/schema/table-filter precedence resolved once (was hand-rolled at 4 router call
  sites; fixes a salvage/resume sibling-schema leak). **`SemanticContract`** (`aughor/semantic/contracts.py`):
  the one governed-metric type both the curated catalog and the ontology serialize to, unified via
  `SemanticContext.contracts()` (catalog wins on collision). **`answer_report`** — the deep-report SSE
  event/field renamed from the internal `ada_report` codename across every consumer (web + MCP), old name
  kept as a `@deprecated` wire alias one release; the web report type is now `AnswerReport`.
- **Cross-source federation** (`federation.planner`) — answer a question that spans two-or-more databases
  end-to-end, deterministic-first. A no-LLM **connection selector** (`aughor/agent/connection_selector.py`,
  lexical schema-relevance + greedy set-cover) picks the sources the question touches; a one-call LLM
  **federated planner** (`aughor/agent/federated_planner.py`) decomposes it into a grounded sub-query per
  source + the join keys (it also picks the driver and chains 3+ sources), validated deterministically; the
  **batched-foreach engine** (`aughor/connectors/remote_join.py`, `federation.remote_join`) joins them
  **N+1-free** (one keyed batch per source, Hasura's NDC pattern in SQL), with **self-healing ill-formatted
  keys**, cross-type numeric matching, and cap-lifted fetches (`execute_bounded`). Exposed as
  `POST /query/cross-source-join` · `/query/federated-answer` · `/query/auto-federated-answer`, and folded into
  the conversational `/ask` path (a plain chat question auto-federates when it spans sources). Complements the
  `FederatedConnection` DuckDB-ATTACH path; all flag-gated, default-off byte-identical (DataAgentBench GAP-1).
- **Job Kernel / event spine** — state machine + heartbeats + boot recovery + idempotency + scope
  cancellation; investigations, monitors & briefs run as first-class kernel jobs with crash-recovery (boot salvage).
- **Real-time SSE streaming**, **resumable investigations**, **human-in-the-loop interrupt**.
- **Two-model architecture** (coder + reasoner) with **runtime provider switching** and **provider
  resilience** (per-endpoint concurrency cap + retry/backoff/deadline); per-phase rate limiting;
  plan-then-SQL separation; non-blocking FastAPI event loop; bounded job concurrency.
- **Parallel investigation** — independent explore sub-questions run concurrently in dependency-respecting
  waves (flag `explore.parallel_subq`); the decompose planner is steered toward a **wide, shallow dependency
  DAG** (independent cuts of one landscape depend only on the landscape, not each other) with a deterministic
  `depends_on` normalizer + a logged wave-schedule — moving the realized plan from a serial chain (max wave
  width ~1) to a landscape → wide-wave → tail shape (~3.7), which is what lets the executor actually save
  wall-clock (measured: the executor alone on old chains ~1.12×; with the wider plan ~1.50×, growing with
  per-question independence and LLM latency). A cross-sectional Deep-Analysis runs independent lenses
  concurrently — **segment/where ∥ mechanism/why ∥ temporal/when** — for a deeper multi-angle answer at flat
  latency (flag `ada.parallel_lenses`). The WHEN lens deterministically resolves a population/order date
  (DB-probed, event-date-excluded) so a rate can be trended over time, flags a materially anomalous period, and
  forward-chains a period-scoped drill; that same axis recovery now runs at **intake**, so even the default
  single-scan path is temporal-aware (a "what drove the change" question with a join-reachable date no longer
  misroutes to cross-sectional). All rate-bearing lenses share **one canonical grain** (the metric table's unit)
  so a report can't show 40% (per order) and 76% (per line-item) for one rate. Both fan-outs run over `ContextThreadPoolExecutor` (so the metering
  accumulator + P6 budget propagate), with budget-abort, failure isolation, serial fallback and deterministic
  merge; in-phase dimension queries already run in parallel. See `docs/PARALLEL_MULTIAGENT_GROUNDWORK.md`.
- **Org / workspace tenancy** — `org_id` on every store, and (flag-gated on `AUGHOR_REQUIRE_IDENTITY`, default
  off) **enforced on the read path**: a request-identity + object-level-authz seam (`security/authz.py` — a
  `Principal`, owner-checks on by-id routes), org-scoped `list_connections` / investigation history, a pure-ASGI
  `_OrgContextMiddleware` that binds `current_org_id()` to the request, and kernel jobs that re-bind their own
  org at execution (survives restart/boot-recovery). The same `resource → connection → org` enforcement now
  covers the **monitor / alert / brief-subscription / canvas / saved-query** surfaces too — router-level
  owner-guards (403 cross-org), `org_visible_conn_ids()` list-filtering so another org's rows never surface,
  connection owner-checks on the create/digest paths, and org-binding of the **monitor + brief background
  schedulers** (a background tick stamps the connection's tenant, not `'default'`); the agent's monitor/brief
  stores stay behind a `kernel/registries/resource_org.py` resolver registry so the platform never imports them.
  **licensing tiers** (Free/Pro/Enterprise, 402 → upsell),
  **governed-intelligence MCP server**, time-to-first-insight instrumentation.
- **Role-based access control (RBAC)** — a second authorization axis orthogonal to licensing (`aughor/rbac/`,
  flag-gated on `AUGHOR_REQUIRE_IDENTITY` **and** the `RBAC_SSO` capability → localhost/non-RBAC tiers
  unchanged). A built-in role ladder **viewer ⊂ analyst ⊂ owner** over a small permission taxonomy, an
  org-scoped assignment store, and a **first-user-is-owner** bootstrap so enabling identity never locks out
  admin. Enforcement is centralized in one auditable **declarative policy table** (`rbac/policy.py`,
  `(method, route-template) → permission`) consulted by a global dependency — a viewer reads anything but
  mutates nothing anywhere, owner-only verbs (roles/settings/grants/billing) stay owner-gated — so the whole
  surface's authz lives in one place rather than 150+ scattered decorators. Roles also impose a
  **capability ceiling** (`tier_caps ∩ role_ceiling`), surfaced through `GET /capabilities` so the UI reflects
  role, not just plan. Managed from a **Settings → Access** roster (assign/revoke; `GET /rbac/me` gates the
  admin surface). Tier still gates 402; role gates 403.
- **RBAC row-level policy** (`rbac.row_policy`) — per-role, per-table row filters compiled INTO the executed
  SQL. A declarative `{role: {table: predicate}}` registry (`rbac/row_policy.py`, `{org_id}`/`{user_id}`
  placeholders, quote-escaped) is AST-rewritten (`sql/rls.py`) so each policied base table becomes an
  alias-preserving filtered subquery — `FROM orders o` → `FROM (SELECT * FROM orders WHERE org_id = '…') o` —
  and a role physically cannot read rows outside its filter, regardless of query shape. Triple-gated (identity
  **and** `RBAC_SSO` **and** the flag), scoped to identified requests, enforced at **every connector's**
  execution gate (DuckDB/Postgres/warehouse/file/API), and **fail-closed** — an un-appliable policy (e.g. a
  CTE shadowing a policied table) blocks the query rather than running it unfiltered (Hasura-permissions-inspired).
- **Security perimeter** — a **fail-closed** SQL safety gate (an errored gate BLOCKS, never allows),
  Postgres opened session-read-only, an **SSRF allowlist** on outbound webhook URLs (create + send-time),
  **prompt-injection fencing** of untrusted DB content fed to the LLM, a global exception handler (no stack
  leaks), gated inference-config, and `Idempotency-Key` on create endpoints.
- **Versioned schema migrations** — a forward-only, additive `run_migrations` framework keyed on
  `PRAGMA user_version` (`db/migrations.py`); every migrating store + the kernel ledger run through it, and every
  SQLite store is tuned (WAL + `busy_timeout`) and test-isolated.

## 13. Quality bar & engineering discipline

- **Eval suite** (`evals/`) — the 53-pair golden NL→SQL set with an execution-scored runner
  (`run_golden.py`: hermetic reference-replay / raw / full-pipeline modes), a delta-measurement
  **ratchet** (`ratchet.py`: accuracy + tokens vs a pinned baseline), and the interaction-arc evals
  (`ambiguity_eval.py` · `its_structural.py` · `ablation_eval.py`), with a **reliability-banding
  protocol** so sub-2-pt effects aren't mistaken for temp-0 noise. *(The one-off Spider 2.0 harness
  from the June benchmark arc was deliberately removed with the arc's conclusion — see
  `docs/SPIDER2_PROGRESS_AND_CHALLENGES_2026-06-28.md` §14; a fresh campaign harness is scoped in
  `docs/10X_AND_SPIDER2_PROGRAM_2026-07-06.md` WS5.)*
- **End-to-end answer-quality gate** (`tests/integration/test_ada_ground_truth.py`) — the deep-analysis guards are
  unit-tested, but *answer quality* on the audit archetypes was not gated. A hermetic harness (temp DuckDB with
  **closed-form ground truth**, no live LLM) now asserts the deterministic gains directly: the global-ratio guard
  recomputes the true global (and stays silent on a plausible spread), a sustained decline is Welch-significant and
  decomposes to the named driver, a genuinely flat series abstains, and the canonical pin binds a runnable formula /
  fails closed on a missing column — so a future change can't silently regress the answer while the unit tests stay green.
- **Fail-graceful-by-contract** — never a 500 / hang / silent-wrong-success.
- **No silent failures** — the only legal way to swallow an exception is `tolerate()` (logged + counted +
  journaled), enforced by a test ratchet that can only go down.
- **CI gate** (`.github/workflows/ci.yml`) — pytest (`not e2e/eval`) + frontend `tsc --noEmit` on every PR,
  plus **ruff at zero and blocking** (pinned; a sane ruleset that surfaced + fixed several real latent
  `NameError`s), plus a **codegen-drift gate** (the typed TS client `web/lib/api.gen.ts` is regenerated
  from the route surface via a hermetic offline OpenAPI dump — `scripts/dump_openapi.py` — and CI fails
  if it's stale). ~2,900 tests; the suite is **fully store-isolated so it can never mutate live data** — every SQLite
  store honours an `AUGHOR_*_DB` override, and the glossary + metrics-catalog **file** stores (`AUGHOR_GLOSSARY_PATH` /
  `AUGHOR_METRICS_PATH`) point at a throwaway temp copy in tests, so the autoseed / knowledge-sync write path can never
  touch `data/`.
- **Enforced frontend design layer** (Part 2 of the 2026-07-03 review) — three baseline-zero, *blocking*
  web gates, the ruff discipline applied to the UI: a **design-token gate** (`lint:tokens` — no raw radius or
  `text-[Npx]`; the scale is the source of truth), a **formatting gate** (`lint:format` — all number/date
  rendering routes through `lib/format.ts`, so the same value can't read "45.3K" in one surface and "45,300"
  in another), and a **raw-`<button>` ratchet** (`lint:elements` — the primitive layer's adoption can only
  grow). Drift is frozen by construction, not by review vigilance.
- **Verification substrate (Bet 0)** + **Specialist Agents** (Domain Expertise Packs) + ongoing audit hardening.

---

## 14. Human-command surface (AI-FDE-derived, flag-gated)

Studied Palantir Foundry's AI FDE and adopted its *human-in-command* posture as a 7-phase program
(all flag-gated + additive — default behaviour unchanged; see `docs/`). The close-the-loop and
premise-validation env vars below are registered in the runtime flag system (`kernel/flags.py`:
`closed_loop`, `ada.premise_check`) so they're also toggleable at runtime from Settings → System,
like `ask.clarify` (the ask-vs-guess gate, the one default-ON flag) and `ada.causal_drill`:

- **Close the loop** (`AUGHOR_CLOSED_LOOP`) — captured human corrections/verdicts + trusted queries are
  read back into the planner as priors, so a corrected mistake isn't repeated (+0.70 accuracy on a repeat set).
- **Agent Context surface** (`AUGHOR_CONTEXT_SURFACE`) — the working context is an inspectable, editable
  object (typed table set + live token budget + rescope endpoint); the ContextRibbon in the answer surface.
- **Editable plan gate** (`AUGHOR_PLAN_GATE`) — deep/explore runs pause after decomposition so the user can
  review/trim the sub-question plan before the expensive fan-out (reuses the LangGraph HITL interrupt/resume).
- **Graduated approval + audit** (`AUGHOR_ACTION_APPROVAL`) — risk-graded per-action gate under the user's
  identity: high-risk mutations require approval, every action is audited to the ledger; per-scope allowlist +
  the "Action approvals" audit view in Security & Audit.
- **Declarative modes** (`AUGHOR_DECLARATIVE_MODES`) — a mode's routing/context-scope is editable YAML with a
  hardcoded fallback (`aughor/agent/modes/`).
- **Deployment budget ceiling** (`AUGHOR_MAX_TOKEN_BUDGET`) — one hard cap floors every agent's token budget.
- **Premise validation** (`AUGHOR_PREMISE_CHECK`) — a "why is X so high" investigation validates the premise
  (subject vs overall/peers) *before* explaining it, instead of assuming it — questioning the question itself.

A delta-measurement ratchet (`evals/ratchet.py`) records accuracy + tokens/run to gate each change.

---

## Frontend

Next.js / React / Tailwind (v4). Streaming investigation UI, Databricks-brand + Genie-style chat, home page,
catalog tab (3-panel + sample data), navigation redesign + command palette + ask-hero, design system v2,
activity log (with fix-and-save / fix-all), and the Data Canvas (scoped editing, list ranking, recents, rename).
An **enforced 3-tier design layer** (Part 2 of the 2026-07-03 review): design tokens (radius/type/palette,
theme-aware light/dark) → the `ui/*` primitives → the `Brief*` composite family, kept honest by three
baseline-zero blocking CI gates (tokens · formatting · raw-element ratchet) so drift can't re-accumulate.
One **`<Workspace>` shell** (header + perspective switcher + keep-alive body) that the sidebar sections are
folded onto — Intelligence, **Operations** (Monitors / Action Hub / Security & Audit), and **Data**
(Catalog / Query Builder / Semantic Layer) each render as one perspective-switched surface instead of a row
of separate full-screen tabs (deep-links preserved). A **turn renderer registry** (`TURN_RENDERERS` +
`registerTurnRenderer`) lets a pack contribute an answer surface without editing the chat god-component.

## How it fits together

A question enters one of the three modes → schema intelligence + ontology + metrics ground the context →
the LLM proposes SQL → the deterministic guard battery validates/repairs it → execution → the answer is
rendered with a chart and a trust receipt. The Explorer runs this loop continuously in the background to
keep the ontology and suggestions fresh.

## Pointers

- Full per-feature history: [`docs/archive/FEATURES_full_2026-06-29.md`](docs/archive/FEATURES_full_2026-06-29.md)
- Architecture: `docs/PLATFORM_ARCHITECTURE.md` · Roadmap: `ROADMAP.md`
- Latest repository audit: `AUDIT_2026-06-27.md`
