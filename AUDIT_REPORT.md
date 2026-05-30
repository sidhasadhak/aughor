# Aughor Platform Audit — 2026-05-29

Comprehensive audit across 4 dimensions: prompt leakages, dead code, missing LLM harnesses, and frontend-backend gaps.

---

## P0 — Critical (LLM produces wrong answers)

### 1. Hardcoded terminal states leak filters into every query

**Files:** `aughor/ontology/builder.py:133-143`, `aughor/explorer/agent.py:51-65`

Two frozen keyword sets silently classify lifecycle states as "terminal" without per-schema override:

```python
# builder.py — generates active_filter automatically
_TERMINAL_KEYWORDS = {"cancel", "cancelled", "canceled", "deliver", "delivered",
    "complet", "completed", "clos", "closed", "fail", "failed", "reject",
    "rejected", "return", "returned", "archived", "archive", "resolved", "done", "void"}

# explorer/agent.py — used in lifecycle extraction
_TERMINAL = frozenset({"canceled", "cancelled", "returned", "closed", "archived",
    "failed", "rejected", "expired", "deleted", "churned", "lost", "void",
    "voided", "refunded", "bounced", "blocked", "completed", "done",
    "delivered", "shipped"})
```

**Impact:** "shipped" is NOT terminal in fulfillment contexts (shipped -> delivered). "completed" and "delivered" being terminal means queries about order flow silently exclude the majority of rows. Once `active_filter` is auto-generated, it's injected into ontology context and the LLM applies it to EVERY query on that entity — even when the user asks about ALL orders.

**Root cause:** Same family as the `CHAT_SQL_SYSTEM` filter leak we just fixed — the system makes filtering decisions FOR the user.

**Fix:** Make terminal classification data-driven, not keyword-driven. The ontology enricher LLM pass should classify states based on actual data context, not string matching. Add `terminal_states_override` field to ontology entity config so users can correct misclassifications.

---

### 2. ADA intake auto-applies status filters without user request

**File:** `aughor/agent/prompts_investigate.py:64-68`

```
7. TRANSACTION STATUS FILTER — Does the metric table have a status/state column?
   If yes, identify which values represent COMPLETED/VALID transactions
   (e.g. 'PAID', 'COMPLETED', 'SETTLED', 'DELIVERED', 'CLOSED')...
   - If a clear "completed" status exists, incorporate it into metric_sql as a CASE WHEN filter
```

**Impact:** User asks "what was total order value in February?" -> ADA auto-applies `status IN ('PAID','COMPLETED')` without being asked. This contradicts the CHAT_SQL_SYSTEM fix we just made. Two pipelines, inconsistent behavior.

**Fix:** Rewrite to: "List the status values present. Do NOT automatically filter — note which states represent terminal vs active phases so downstream queries CAN filter if the user requests it."

---

### 3. Chat pipeline is a "dumb pipe" — missing 40% of available intelligence

**File:** `aughor/api.py:348-420` (`_stream_chat`)

The chat endpoint injects: schema, KB patterns, SQL examples, conversation history, global rules. It does NOT inject:

| Available data | Injected? | Impact of gap |
|---|---|---|
| Ontology actions (ACTION:get_active_orders()) | NO | LLM regenerates SQL from scratch instead of using verified templates |
| Metric definitions (approved SUM formulas) | NO | LLM guesses metric logic instead of using approved business definitions |
| Exploration findings (null meanings, lifecycle maps, cross-table patterns) | NO | LLM blind to data quality issues discovered by explorer |
| Uploaded documents (PDFs, SOPs) | NO | Chat can't ground answers in business context docs |
| Causal graph (confirmed causal edges) | NO | LLM can't reference proven cause-effect relationships |
| Playbook (proven interventions) | NO | "How do we fix churn?" gets generic advice instead of data-backed playbook entries |

**Fix:** Before `CHAT_PROMPT.format()`, inject ontology actions, metrics catalog, and document search results. These are 3 separate additions, each ~10 lines of code.

---

### 4. Missing concept mappings — "sales", "quantity", "rate" misfire

**File:** `aughor/agent/prompts.py:68-75`

The concept mapping covers "revenue" and "retry rate" but misses:

| Business term | Expected behavior | Current behavior |
|---|---|---|
| "sales", "sales numbers", "sales value" | SUM(price) | COUNT(*) — JUST FIXED |
| "units sold", "quantity", "items sold" | COUNT(order_items) or SUM(quantity) | May SUM(price) or COUNT(orders) |
| "volume" | Ambiguous — could mean units OR count | Undefined |
| "conversion rate", "churn rate", "return rate" | COUNT(condition) / COUNT(all) with NULLIF | May return raw COUNT without denominator |
| "refund rate" | SUM(refunded) / SUM(total) | May return COUNT of refunds |
| "AOV", "average order value" | SUM(price) / COUNT(DISTINCT order_id) | May AVG(price) per item instead of per order |

**Fix:** Expand the CONCEPT MAPPING block with explicit rules for quantity, rates, and averages.

---

## P1 — High (Features exist but intelligence is crippled)

### 5. Decompose node blind to exploration findings

**File:** `aughor/agent/nodes.py:260-295` (decompose_question)

The hypothesis decomposer receives prior analyses and KB patterns, but NOT:
- Null meanings from Phase 3 (why columns are NULL — pending vs missing)
- Join verification from Phase 4 (orphan rows, cardinality surprises)
- Lifecycle maps from Phase 5 (entity state machines)
- Distribution profiles from Phase 6 (log-normal, bimodal, outlier counts)
- Cross-table insights from Phase 7

**Impact:** Hypotheses are generated without awareness of data quality issues the explorer already discovered. The explorer runs for hours building deep schema understanding, then the investigator ignores all of it.

**Fix:** Load exploration state and build a summary section for DECOMPOSE_PROMPT.

---

### 6. Plan queries missing causal graph context

**File:** `aughor/agent/nodes.py:300-343` (plan_queries)

When planning SQL queries for a hypothesis, the LLM never sees confirmed causal edges from prior investigations. It may re-investigate already-disproven causal paths or miss known upstream drivers.

**Fix:** Inject causal graph edges relevant to the metric being investigated.

---

### 7. Suggestions endpoint uses only raw schema

**File:** `aughor/api.py:2349-2411` (GET /suggestions)

Generates 6 starter questions from raw `db.get_schema()` only. Does NOT use:
- Ontology entities/relationships (domain structure)
- Exploration insights (actual interesting patterns found)
- Playbook (proven investigation angles)
- Prior investigation topics (what's already been explored)

**Impact:** Suggestions are generic ("Show top customers by revenue") instead of targeted ("Why did SP state's freight costs spike 40% while delivery rates held steady?" — an actual explorer finding).

**Fix:** Inject ontology + exploration context into the suggestion generation prompt.

---

### 8. FIX_SQL missing ontology actions and metric definitions

**File:** `aughor/agent/prompts.py:236-273` (FIX_SQL_PROMPT)

When self-correcting a broken query, the LLM sees the error + schema + KB patterns. It does NOT see ontology actions or metric definitions. So if it's trying to compute revenue and gets the formula wrong, it has no reference to the approved formula.

**Fix:** Inject ontology actions section and metrics catalog into FIX_SQL_PROMPT.

---

### 9. Explorer Phase 8 doesn't use Phases 3-7 findings

**File:** `aughor/explorer/agent.py:701-900` (_phase8_domain_intelligence)

Phase 8's LLM prompt receives entity context and relationships, but NOT the findings from phases 3-7 (null meanings, join verifications, lifecycle maps, distributions, cross-table insights). The "curiosity loop" is generating questions without knowing what the structural phases already discovered.

**Fix:** Build a prior-phases summary and inject into the Phase 8 prompt.

---

## P2 — Medium (Features partially wired, missing pieces)

### 10. Causal graph visualization never calls backend

**File:** `web/components/OntologyCanvas.tsx`

Component imports `getCausalGraph` but never calls it. The backend endpoint `GET /connections/{conn_id}/causal-graph` works. Causal edges (confirmed from prior investigations) are supposed to overlay as dashed orange arrows on the ontology graph — but the call is missing.

**Severity:** Feature built on both ends, just not connected.

---

### 11. Canvas-scoped endpoints not implemented

**File:** `aughor/api.py`

Sprint 22 roadmap specifies these endpoints, but they don't exist:
- `GET /canvases/{id}/history` — canvas-scoped investigation history
- `GET /canvases/{id}/suggestions` — canvas-scoped starter questions
- `GET /canvases/{id}/recents` — canvas-scoped recent queries

The Canvas browser and creator exist, but without scoped data, selecting a canvas doesn't meaningfully filter anything.

---

### 12. ProcessMapper hidden from navigation

**File:** `web/components/ProcessMapper.tsx` (fully implemented), `web/app/page.tsx` (not in nav)

ProcessMapper renders lifecycle swimlane diagrams with health-colored nodes. Fully built. But it's only accessible indirectly through ProcessHealthPanel — there's no direct nav entry.

---

### 13. Scatter chart type not handled

**File:** `web/components/ChatMessage.tsx`

Backend can emit `chart_type: "scatter"` but InlineChart has no scatter handler. Falls through to null — chart disappears silently.

---

### 14. 3 SSE events emitted but never consumed

**File:** `aughor/api.py` -> `web/lib/useChat.ts`

| SSE event | Emitted | Handled | Gap |
|---|---|---|---|
| `queries_executed` | api.py:713 | NO | Users can't see real-time query progress |
| `score` | api.py:724 | NO | Evidence scoring hidden |
| `subq_answer` | api.py:804 | NO | Sub-question answers in explore mode lost |

---

### 15. Hardcoded significance thresholds

**File:** `aughor/agent/prompts_investigate.py:144`

```
is_significant: true if |z| > 2.0 OR absolute change > 10% of prior period value
```

2.0 sigma and 10% are hardcoded. Retail cares about 5% swings; finance cares about 0.1%. No way to configure per-connection or per-metric.

---

### 16. Frontend shows raw column names

**Files:** `web/components/CatalogScreen.tsx:408`, `web/components/SchemaCards.tsx`

Catalog displays `customer_unique_id` instead of enriched "Customer [Stable identifier for repeat purchase tracking]". The glossary descriptions exist in the backend but aren't passed to these components.

---

## P3 — Low (Cleanup / polish)

### 17. Stale import: QueryPlan in nodes.py:30 (replaced by QueryPlanV2)
### 18. Unused file: aughor/agent/prompts_ontology.py (never imported)
### 19. Olist-specific examples in generic prompts (prompts_investigate.py:168-174: "Revenue = Orders x AOV")
### 20. Chat-mode skips hypothesis/evidence/causal reasoning rules (rules.py: only sections 0,7,8 injected)
### 21. "auto" chart_type undefined — frontend interprets it differently than backend intends
### 22. chart_type field is unvalidated string, not enum — any LLM hallucination passes through

---

## Priority Matrix

| Priority | Count | Theme |
|---|---|---|
| **P0 — Wrong answers** | 4 | Leaked filters, dumb chat pipe, missing concept maps |
| **P1 — Crippled intelligence** | 5 | Explorer findings unused, causal graph ignored, suggestions generic |
| **P2 — Partially wired** | 7 | Canvas gaps, hidden features, unhandled events |
| **P3 — Cleanup** | 6 | Dead code, Olist examples, missing validation |

### Recommended Sprint Order

**Sprint A (immediate — prompt fixes, no architecture):**
- Fix #1: Make terminal state classification data-driven
- Fix #2: Remove auto-filter from ADA intake
- Fix #4: Expand concept mappings (quantity, rates, AOV)
- Fix #19: Remove Olist-specific examples from generic prompts

**Sprint B (high-impact wiring — connect existing data to prompts):**
- Fix #3: Inject ontology + metrics + docs into chat pipeline
- Fix #5: Inject exploration findings into decompose
- Fix #6: Inject causal graph into plan_queries
- Fix #7: Enrich suggestions with ontology + exploration
- Fix #8: Add ontology actions to FIX_SQL

**Sprint C (complete partially-shipped features):**
- Fix #10: Call getCausalGraph in OntologyCanvas
- Fix #11: Implement canvas-scoped endpoints
- Fix #12: Add ProcessMapper to navigation
- Fix #13: Add scatter chart handler
- Fix #14: Handle missing SSE events

**Sprint D (polish):**
- Fix #9: Feed phases 3-7 into phase 8
- Fix #15: Configurable significance thresholds
- Fix #16: Glossary-enriched column display
- Remaining P3 items
