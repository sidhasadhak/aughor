# Aughor NL2SQL & Agentic Synthesis: Thrashing Baggage for 10x Leaner, Faster, Deterministic Investigations

> **Status:** Conceptual design document — not yet implemented  
> **Goal:** Reduce token burn, latency, and hallucination surface by replacing LLM-based SQL generation and narrative synthesis with ontology-driven, grammar-bound, deterministic pipelines. LLMs become ambiguity resolvers, not query writers.

---

## 1. The Current Landscape: What Aughor Does Today

### 1.1 The Graph (14+ LLM calls per investigation)

```
route_question ──► exploratory_scan ──► ada_intake ──► ada_baseline ──► ada_decompose ──► ada_dimensional ──► ada_behavioral ──► ada_synthesize
        │                                                                  │
        ├──► plan_queries ──► execute_planned_queries ──► score_evidence ──► replan ──► synthesize
        │                                                                  │
        └──► decompose_exploration ──► plan_and_execute_subq ──► reason_over_result ──► synthesize_exploration
```

Every shaded node is an LLM call. A typical investigate-mode question consumes **8–14 LLM calls**, each with a schema context of 1,000–4,000 tokens. On a local `qwen2.5-coder:32b`, this is 2–5 minutes. On API models, it is $0.50–$2.50 per question.

### 1.2 The NL → SQL Pipeline (Text-Dump Architecture)

```
User Question ──► [LLM: route_question] ──► [LLM: decompose / intake]
                                    │
                                    ▼
                          Schema Context (text blob)
                                    │
                                    ▼
                          [LLM: plan_queries / write SQL]
                                    │
                                    ▼
                          [sqlglot lint] ──► [execute]
                                    │
                                    ▼
                          [LLM: fix on error] ──► retry
```

The LLM receives the schema as a **raw text string** (TABLE: orders, column lines, join hints, profile annotations). It must:
1. Memorise table/column names from the blob
2. Infer join paths from fuzzy text
3. Write dialect-correct SQL from memory
4. Handle all business logic (status filters, date arithmetic, ratios) from the prompt

This is the classic **"NL → Raw SQL"** paradigm that every NL2SQL benchmark (Spider, BIRD, etc.) struggles with. It is inherently fragile because:
- Column names are hallucinated (~8% of queries in BIRD require correction)
- Join paths are guessed (~15% use wrong tables)
- Aggregations are semantically wrong (AVG of ratios vs ratio of SUMs)
- Dialect rules are ignored despite being in the prompt

### 1.3 The Synthesis Pipeline (Narrative Over-Generation)

After SQL runs, the LLM:
1. Re-reads all query results (raw rows as text)
2. Scores hypotheses (another LLM call)
3. Writes a narrative report (another LLM call)
4. Checks consistency (another LLM call)
5. Replans (another LLM call)

Most of this is **re-deriving what the SQL already proved**. The queries returned definitive numbers. The LLM is simply re-stating them in prose with a confidence score invented from thin air.

---

## 2. Deep Research: State of NL2SQL & Text-to-SQL (2023–2025)

### 2.1 The Benchmarks

| Benchmark | Focus | Key Finding |
|---|---|---|
| **Spider** | Single-turn, single-schema | Best models hit ~91% execution accuracy, but on **clean schemas** with human-written descriptions. Real-world schemas drop to 60–70%. |
| **BIRD** (2023) | Dirty schemas, large DBs, external knowledge | Top systems (DIN-SQL, MAC-SQL) hit ~65% execution accuracy. The gap is **schema understanding**, not SQL syntax. |
| **Spider 2.0** (2024) | Enterprise-scale schemas (100+ tables) | Accuracy drops to ~40%. Context window saturation is the primary blocker. |
| **KaggleDBQA** | Real analytics questions on messy data | Most NL2SQL systems fail on implicit aggregation ("trend" → time-series, "drop" → comparison). |

**The brutal truth:** LLM-based NL2SQL works well on toy schemas with 5 tables. It falls apart on real warehouses with 50+ tables, stale column names, implicit business logic, and fuzzy natural language.

### 2.2 The Architecture Families

#### Family A: Prompt Engineering (Aughor's current approach)
- **Method:** Schema-as-text + few-shot examples → LLM writes SQL
- **Representatives:** GPT-4 + CoT, DIN-SQL, Self-Debugging
- **Pros:** Flexible, no training data needed
- **Cons:** Unbounded token cost, hallucination, non-deterministic, slow
- **Determinism:** LOW — same question, different SQL on different runs

#### Family B: Fine-Tuned Models
- **Method:** Train a model (CodeLLaMA, CodeT5+) on schema+question→SQL pairs
- **Representatives:** Picard, SLSQL, RESDSQL
- **Pros:** Faster inference than prompting, better column grounding
- **Cons:** Requires expensive training data, doesn't generalise to new schemas
- **Determinism:** MEDIUM — model is fixed, but sampling temperature introduces variance

#### Family C: Grammar-Constrained Decoding
- **Method:** Constrain the LLM's output to valid SQL using a grammar (EBNF) at decode time
- **Representatives:** Picard, SQL-PaLM, Grammar-Aligned Decoding (GAD)
- **Pros:** Zero invalid SQL syntax, fewer runtime errors
- **Cons:** Still hallucinates columns/tables, doesn't solve semantic correctness
- **Determinism:** MEDIUM-HIGH — syntax is guaranteed, semantics are not

#### Family D: Semantic Parsing (Intermediate Representation)
- **Method:** NL → structured intermediate representation (IR) → SQL
- **Representatives:** RAT-SQL, IRNet, ValueNet
- **Pros:** Separates "what to ask" from "how to query"; the IR is verifiable
- **Cons:** IR design is hard; domain-specific; needs training data
- **Determinism:** HIGH — IR is structured, SQL generation from IR is deterministic

#### Family E: Retrieval-Augmented Generation (RAG-SQL)
- **Method:** Retrieve similar past queries / query fragments → inject into prompt
- **Representatives:** Aughor's KB retriever, SQL-PaLM with exemplar retrieval
- **Pros:** Reuses proven patterns; reduces hallucination on common queries
- **Cons:** Cold-start problem; retrieval quality determines everything
- **Determinism:** LOW-MEDIUM — depends on vector similarity scores

#### Family F: Program Synthesis / Symbolic Methods
- **Method:** Build a symbolic representation of the schema (graph) and use search or deterministic algorithms to find query plans
- **Representatives:** Schema2QA (graph-based), CEGIS-style synthesis
- **Pros:** Fully deterministic, verifiable, no LLM needed for SQL generation
- **Cons:** Complex to build; brittle on ambiguous language
- **Determinism:** HIGH — pure algorithmic

### 2.3 The Gap Analysis

| What we need | Family A (Current) | Family D (IR) | Family F (Symbolic) |
|---|---|---|---|
| Deterministic SQL | ❌ | ✅ | ✅ |
| Handles 50+ tables | ❌ | ⚠️ | ✅ |
| No training data required | ✅ | ❌ | ✅ |
| Explains *why* (causal) | ⚠️ | ❌ | ❌ |
| Adapts to new schemas | ✅ | ❌ | ✅ |
| Fast (<1s for simple queries) | ❌ | ✅ | ✅ |
| Complex multi-hop joins | ⚠️ | ⚠️ | ✅ |
| Business logic (status filters, etc.) | ❌ | ❌ | ✅ (if encoded) |

**The insight:** No single family solves everything. But Aughor already has something unique: a **living ontology** (entities, relationships, metrics, actions) that is essentially a **symbolic schema graph** (Family F). We are not using it for SQL generation. We should.

---

## 3. The Baggage Inventory: What to Thrash

### 3.1 Baggage Item: Schema-as-Text Prompting

**Current:** Every LLM call receives the full schema as a text blob. For a 50-table warehouse, this is 3,000–6,000 tokens. With 14 LLM calls, that's **42,000–84,000 tokens of schema repetition per investigation**.

**Why it's baggage:** The LLM doesn't need to "read" the schema every time. The schema is a structured graph. We have it in `OntologyGraph`. Passing it as text forces the LLM to do graph traversal in its head — a task it is terrible at.

**Trash it:** Replace schema-as-text with **schema-as-graph** — a symbolic representation the system queries, not the LLM reads.

### 3.2 Baggage Item: LLM-as-SQL-Writer

**Current:** The LLM writes raw SQL strings. Every query plan, every sub-question, every direct query — all go through an LLM.

**Why it's baggage:** SQL is a programming language. LLMs are mediocre programmers, especially with dialect quirks (DuckDB `datediff` vs Postgres `AGE` vs MySQL `TIMESTAMPDIFF`). The `lint.py` module exists precisely because the LLM can't be trusted to write correct SQL. The `inspect.py` module exists because we need a *second* LLM to check the first LLM's work.

**Trash it:** Replace LLM SQL generation with **ontology-driven synthesis** — deterministic SQL generation from structured query intents using the ontology graph.

### 3.3 Baggage Item: Hypothesis Scoring by LLM

**Current:** After SQL runs, the LLM reads the results and assigns a confidence score (0.0–1.0) to each hypothesis.

**Why it's baggage:** The confidence score is **ungrounded**. The LLM has no access to ground truth. It invents confidence based on prose patterns in the result set. A query returning "N/A" gets 0.3; a query returning "42" gets 0.8 — but both could be measuring the wrong thing.

**Trash it:** Replace with **evidence scoring functions** — deterministic statistical measures (z-score, p-value, effect size, sample size) computed by code, not guessed by an LLM.

### 3.4 Baggage Item: Narrative Synthesis by LLM

**Current:** The final report is written entirely by an LLM reading all query results as text and composing prose.

**Why it's baggage:** It is expensive (another 2,000–4,000 tokens), slow, and non-deterministic. The same investigation run twice produces different wording, different emphasis, and sometimes different conclusions.

**Trash it:** Replace with **template-based synthesis** — the system assembles the report from pre-defined templates filled with computed evidence slots. LLM is used only for stylistic smoothing (optional, post-hoc).

### 3.5 Baggage Item: The ADA 8-Phase Funnel

**Current:** investigate mode runs: intake → baseline → decomposition → dimensional → behavioural → synthesis. Each phase is an LLM call that writes 2–3 SQL queries.

**Why it's baggage:** This is a **waterfall process** encoded in a graph. It assumes every investigation follows the same analytical pattern. Real questions don't:
- "What is MRR this month?" needs intake + baseline — skip decomposition entirely
- "Why did APAC revenue drop?" might need decomposition but not behavioural
- "Top 10 customers" needs none of the above — it's a direct query

The phases also duplicate work: baseline computes period-over-period changes, then decomposition recomputes them by segment, then dimensional drills further. Many queries are re-executions with different GROUP BYs.

**Trash it:** Replace with a **lazy, demand-driven investigation planner** — only run phases whose output is actually needed by the final answer. Pre-compute and cache metric baselines at connection time, not investigation time.

### 3.6 Baggage Item: LangGraph Checkpoint Overhead

**Current:** Every node in the graph is checkpointed to SQLite via `SqliteSaver`. For 14 nodes, that's 14 SQLite writes per investigation.

**Why it's baggage:** Checkpointing is necessary for resumability (human-in-the-loop), but most questions complete in under 2 minutes. The SQLite overhead is pure latency for the 95% case.

**Trash it:** Make checkpointing **opt-in** per mode. Direct queries: no checkpointing. Quick investigations: in-memory checkpointing. Deep investigations: persistent checkpointing.

### 3.7 Baggage Item: Vector Search for Schema Retrieval

**Current:** For large schemas (>12 tables), Aughor embeds table/column descriptions into Qdrant and retrieves the top-k most relevant tables per hypothesis.

**Why it's baggage:** This is a **heuristic approximation** of what the ontology graph already knows. The ontology explicitly maps entities to tables, relationships to join paths, and metrics to formulas. Vector search is a fuzzy workaround for not using the ontology.

**Trash it:** Use the ontology graph directly. Given a question, traverse the graph to find relevant entities, then expand to related entities via relationship edges. This is deterministic, exact, and requires zero embedding cost.

---

## 4. The New Architecture: Ontology-Driven Deterministic Synthesis

### 4.1 Core Principle: The Ontology is the Query Compiler

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           NEW ARCHITECTURE                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  User Question                                                              │
│       │                                                                     │
│       ▼                                                                     │
│  ┌─────────────┐    Deterministic    ┌──────────────────┐                  │
│  │  INTENT     │ ──► grammar-based ──►│  QUERY INTENT    │                  │
│  │  PARSER     │    parser (no LLM)   │  (Structured IR) │                  │
│  └─────────────┘                      └──────────────────┘                  │
│       │                                                                     │
│       ▼                                                                     │
│  ┌─────────────────────────────────────────────────────┐                   │
│  │         ONTOLOGY GRAPH (Compiled, Cached)           │                   │
│  │  ┌─────────┐  ┌──────────┐  ┌─────────┐  ┌────────┐ │                   │
│  │  │Entities │──│Relations │──│ Metrics │──│Actions │ │                   │
│  │  │(tables)  │  │(joins)   │  │(formulas)│  │(SQL   │ │                   │
│  │  └─────────┘  └──────────┘  └─────────┘  │templates)│ │                   │
│  │                                          └────────┘ │                   │
│  └─────────────────────────────────────────────────────┘                   │
│       │                                                                     │
│       ▼                                                                     │
│  ┌─────────────┐    Deterministic    ┌──────────────────┐                  │
│  │   QUERY     │ ──► graph-based ──► │  EXECUTABLE SQL   │                  │
│  │  SYNTHESIZER│    code generation  │  (Dialect-specific)│                 │
│  └─────────────┘                      └──────────────────┘                  │
│       │                                                                     │
│       ▼                                                                     │
│  ┌─────────────┐    Deterministic    ┌──────────────────┐                  │
│  │  EVIDENCE   │ ──► code-based ────►│  ANALYSIS REPORT  │                  │
│  │  AGGREGATOR │    stat functions   │  (Structured slots)│                  │
│  └─────────────┘                      └──────────────────┘                  │
│       │                                                                     │
│       ▼                                                                     │
│  ┌─────────────┐    Optional         ┌──────────────────┐                  │
│  │  NARRATIVE  │ ──► LLM only for ──►│  FINAL REPORT     │                  │
│  │  SMOOTHER   │    prose polish     │  (Human-readable) │                  │
│  └─────────────┘                      └──────────────────┘                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**The LLM is only used in two places:**
1. **Intent Parser** — NL → structured Query Intent (only when the deterministic parser fails or the question is ambiguous)
2. **Narrative Smoother** — optional prose polish on the final report (can be disabled for fully deterministic output)

Everything else is code.

### 4.2 Component 1: The Intent Parser (NL → Query Intent IR)

**What it is:** A deterministic parser that recognises ~40 common analytical intent patterns and produces a structured intermediate representation.

**Why no LLM for this:** 80% of business questions fall into a small set of patterns. These patterns can be recognised with regex + lightweight NLP (spaCy/dependency parsing) faster and more reliably than an LLM.

**The Query Intent IR:**

```json
{
  "intent_type": "metric_over_time",
  "entity": "Order",
  "metric": "revenue",
  "time_grain": "month",
  "filters": [
    {"dimension": "region", "operator": "eq", "value": "APAC"}
  ],
  "comparison": {"type": "prior_period", "offset": "1 month"},
  "ordering": {"by": "date", "direction": "desc"},
  "limit": 12
}
```

**Intent types:**

| Intent Type | Example Question | Deterministic? |
|---|---|---|
| `scalar_lookup` | "What is MRR this month?" | ✅ Yes |
| `metric_over_time` | "Revenue by month" | ✅ Yes |
| `ranking` | "Top 10 customers by revenue" | ✅ Yes |
| `breakdown` | "Revenue by region and channel" | ✅ Yes |
| `comparison` | "Compare Q1 vs Q2" | ✅ Yes |
| `trend` | "Is revenue trending up?" | ✅ Yes (code: STL) |
| `anomaly` | "Did anything unusual happen?" | ✅ Yes (code: z-score) |
| `correlation` | "How does discount affect profit?" | ✅ Yes |
| `causal_why` | "Why did revenue drop?" | ⚠️ Partial — decomposition needs LLM |
| `explore_relationship` | "What drives churn?" | ❌ No — requires LLM |

**The hybrid approach:**
- **Fast path:** Intent Parser handles the ✅ cases directly. No LLM. Sub-100ms parse time.
- **Fallback path:** For ❌ and ⚠️ cases, call the LLM to produce a Query Intent (structured Pydantic output, not raw SQL). The LLM never writes SQL — only structured intent.

**Token savings:** A Query Intent is ~200 tokens. A raw SQL query with schema context is ~2,000–4,000 tokens. **10x token reduction** for the fast path.

### 4.3 Component 2: Ontology-Driven SQL Synthesis (Query Intent → SQL)

**How it works:**

Given a Query Intent, the synthesizer traverses the `OntologyGraph`:

```python
def synthesize_sql(intent: QueryIntent, ontology: OntologyGraph, dialect: str) -> str:
    # 1. Resolve entity → tables
    entity = ontology.entities[intent.entity]
    primary_table = entity.source_tables[0]
    
    # 2. Resolve metric → formula
    metric = ontology.metrics[intent.metric]
    select_expr = metric.formula_sql  # e.g. "SUM(final_price_usd)"
    
    # 3. Resolve dimensions → columns
    group_cols = []
    for dim in intent.dimensions:
        prop = entity.properties[dim]
        group_cols.append(f"{primary_table}.{prop.name}")
    
    # 4. Resolve time filter → date column
    date_prop = next(p for p in entity.properties if p.semantic_type == "timestamp")
    date_col = f"{primary_table}.{date_prop.name}"
    
    # 5. Resolve filters → WHERE clauses
    where_clauses = []
    for f in intent.filters:
        prop = entity.properties[f.dimension]
        where_clauses.append(render_filter(prop, f.operator, f.value))
    
    # 6. Resolve comparison → JOIN to prior period (if needed)
    joins = []
    if intent.comparison:
        joins = build_comparison_join(intent.comparison, entity, ontology)
    
    # 7. Assemble query using dialect-specific template
    return dialect_assembler.assemble(
        select=[select_expr] + group_cols,
        from_table=primary_table,
        joins=joins,
        where=where_clauses,
        group_by=group_cols,
        order_by=intent.ordering,
        limit=intent.limit,
    )
```

**Why this is deterministic:**
- Every step is a graph lookup or a template fill. No LLM.
- The ontology is verified at build time (grain checks, join confidence).
- Dialect quirks are handled by the `dialect_assembler`, not by hoping the LLM remembers DuckDB rules.
- If a required entity/metric/dimension is missing from the ontology, the synthesizer **fails fast** with a clear error — it does not hallucinate a table name.

**What about joins?** The ontology's `OntologyRelationship` objects already encode join SQL (`orders.customer_id = customers.customer_id`). The synthesizer follows relationship edges to reach related entities. This is deterministic graph traversal, not fuzzy column-name matching.

**What about complex multi-hop joins?** The synthesizer uses a shortest-path algorithm over the relationship graph. Given `Order → Customer → Segment`, a query for "revenue by segment" follows two relationship edges deterministically.

### 4.4 Component 3: The Pre-Compiled Metric Cache

**Current:** Every investigation recomputes baselines (trailing 13 periods, z-scores, PoP changes) from scratch.

**New:** Maintain a **Materialised Metric Cache** — a set of pre-computed tables refreshed nightly (or on-demand):

```sql
-- kpi_daily (already exists in Aughor!)
-- Extend to:
-- kpi_weekly, kpi_monthly, kpi_quarterly
-- Each has: metric_id, period_start, period_end, value, prior_period_value, yoy_value, z_score
```

**Investigation speedup:** A "Why did revenue drop?" question no longer needs to run 3 baseline queries. It reads `kpi_monthly` where `metric_id = 'revenue'` and gets the z-score instantly. **From 3 LLM calls + 3 SQL executions → 1 table lookup.**

**Determinism bonus:** The z-score is computed by `scipy.stats`, not by an LLM guessing significance.

### 4.5 Component 4: Evidence Aggregation (No LLM Synthesis)

**Current:** The LLM reads all query results and writes a narrative report.

**New:** The Evidence Aggregator assembles the report from structured slots:

```python
class EvidenceAggregator:
    def assemble(self, findings: list[InvestigationFinding]) -> AnalysisReport:
        # 1. Rank findings by statistical significance (code, not LLM)
        ranked = sorted(findings, key=lambda f: abs(f.z_score or 0), reverse=True)
        
        # 2. Build headline from top finding
        top = ranked[0]
        headline = f"{top.metric_label} {top.direction} by {top.magnitude} — primarily driven by {top.dimension}={top.dimension_value}"
        
        # 3. Build waterfall from ranked dimensional contributions
        waterfall = self.build_waterfall(ranked)
        
        # 4. Build recommendations from controllable findings
        recommendations = [f.recommendation for f in ranked if f.is_controllable]
        
        # 5. Fill template
        return AnalysisReport(
            headline=headline,
            verdict=self.template_verdict(top, ranked[1:3]),
            key_findings=[self.slot_finding(f) for f in ranked[:5]],
            what_is_not_the_cause=self.excluded_findings(ranked),
            risks=[r for r in recommendations if r.urgency == "high"],
            recommended_actions=recommendations,
        )
```

**The template system:**

```python
VERDICT_TEMPLATES = {
    "drop_significant_single_driver": (
        "{metric} dropped by {magnitude} in {period}. "
        "The primary driver is {driver}, which accounted for {contribution} of the decline. "
        "This is a {significance}-sigma event ({confidence} confidence)."
    ),
    "drop_no_significant_driver": (
        "{metric} dropped by {magnitude} in {period}, but no single dimension "
        "explains more than {threshold} of the decline. The drop appears broad-based."
    ),
    ...
}
```

**When is the LLM used?** Only if the user asks for a "smooth narrative" — an optional post-processing step that fills template slots into flowing prose. The default is structured output (headline, bullets, waterfall) which is what most decision-makers actually want.

### 4.6 Component 5: The Fast Path (Direct Queries → 0 LLM Calls)

For the 60% of questions that are direct lookups, aggregations, or breakdowns:

```
User Question ──► Intent Parser (deterministic, <50ms)
                    │
                    ▼
            Query Intent IR
                    │
                    ▼
            SQL Synthesizer (graph traversal, <10ms)
                    │
                    ▼
            Execute SQL
                    │
                    ▼
            Format Results (code templates)
                    │
                    ▼
            Return Answer
```

**Total time:** <200ms for a cached schema, <1s for cold schema.
**LLM calls:** 0.
**Token burn:** 0.
**Determinism:** 100% — same question always produces same SQL.

---

## 5. Implementation Roadmap

### Phase 1: Intent Parser (Sprint X)
- Build deterministic parser with 10 core intent types
- Integrate into `route_question` — fast path bypasses LLM routing
- Target: 60% of questions handled without LLM

### Phase 2: SQL Synthesis Engine (Sprint X+1)
- Build `QuerySynthesizer` that reads `OntologyGraph` and produces SQL
- Support scalar, time-series, breakdown, ranking intents
- Integrate with existing `dialect` abstraction (DuckDB, Postgres, etc.)
- Target: 0 LLM calls for direct queries

### Phase 3: Materialised Metric Cache (Sprint X+2)
- Auto-generate `kpi_*` rollups from `OntologyMetric` definitions
- Run as background job (reuse existing explorer scheduler)
- Target: Baseline queries become table lookups

### Phase 4: Evidence Aggregator (Sprint X+3)
- Build template-based report assembly
- Port ADA phases to use Evidence Aggregator instead of LLM synthesis
- Target: Narrative reports without LLM for 80% of findings

### Phase 5: Full Graph Migration (Sprint X+4)
- Deprecate `plan_queries` LLM node for direct/explore modes
- Retain LLM only for: (a) ambiguous intent parsing, (b) causal why-questions, (c) optional prose polish
- Target: 10x token reduction, 5x latency reduction

---

## 6. Expected Impact

| Metric | Current | Target | Method |
|---|---|---|---|
| **Tokens per direct query** | 2,000–6,000 | 0–200 | Intent Parser + Synthesis |
| **Tokens per investigation** | 30,000–80,000 | 3,000–8,000 | IR-based + pre-computed baselines |
| **Direct query latency** | 5–15s (LLM) | <1s (code) | Deterministic pipeline |
| **Investigation latency** | 2–5 min | 20–60s | Fewer LLM calls + cached metrics |
| **SQL correctness (direct)** | ~85% | ~99% | Ontology-driven synthesis |
| **Determinism (same question)** | ~70% identical | ~99% identical | No sampling in core path |
| **Hallucination rate** | ~5–10% | ~0.1% | Structured IR + graph traversal |
| **Cost per investigation (API)** | $0.50–$2.50 | $0.05–$0.25 | 10x token reduction |

---

## 7. Risk Analysis & Mitigations

| Risk | Mitigation |
|---|---|
| Intent Parser can't handle novel question types | Fallback to LLM intent parsing; telemetry tracks coverage gaps |
| Ontology is incomplete (missing relationships) | LLM-assisted ontology enrichment already exists (M12b); synthesis fails fast with clear error |
| Complex nested subqueries not representable in IR | IR is extensible; uncommon patterns fall back to LLM synthesis |
| Users want "creative" analysis not in templates | Optional full-LLM mode remains; default is deterministic |
| Dialect edge cases in assembler | Assembler is code — testable, unlike LLM prompts; add dialect test suite |

---

## 8. The Deeper Philosophy

**The current architecture treats the LLM as a junior data analyst.** It gives the LLM the schema, asks it to think, plan, write SQL, fix errors, score evidence, and write reports. This is the most expensive and least reliable way to use an LLM.

**The new architecture treats the LLM as a linguist.** Its only job is to bridge the gap between ambiguous natural language and structured intent. Everything after intent parsing is a deterministic computation over a verified knowledge graph.

This is the same shift that made compilers successful: we don't ask a human to write machine code from a vague description. We parse, type-check, optimise, and emit. The LLM is the frontend parser. The ontology is the backend.

> *"The LLM should guess what you mean. The system should guarantee what it does."*

---

*End of conceptual document.*
