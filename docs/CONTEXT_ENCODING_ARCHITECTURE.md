# Encoding Business Context for Any Connection — Architecture & Reasoning

*Design note, 2026-06. Distilled from the Spider 2.0 benchmarking effort and the
beautycommerce product A/B. Companion to `docs/competitive/genloop-deep-study.md`.*

---

## 0. Why this document exists

Across two independent evaluations — the Spider 2.0 benchmark **and** Aughor's own
beautycommerce database — the dominant cause of wrong answers was **not** SQL syntax,
fan-out, or grain. It was **concept-mapping / business-semantics**: the agent not knowing
*which column is "the customer", which event is "a purchase", what "abandoned" or "repeat
rate" actually means in this schema*.

Two data points frame the whole problem:

- **Zero-shot agentic systems** (ours, and the academic SOTA *ReFoRCE*) plateau around
  **~27–31% execution accuracy** on Spider 2.0. They must *infer* business semantics from
  the schema on every question, with no memory.
- **Domain-specialised systems** (e.g. Genloop's Sentinel Agent, ~96% on Spider 2.0-Snow)
  reach the high 80s–90s by **encoding** that semantics once — a persistent "business
  memory" (join paths, metric definitions, value semantics) plus domain fine-tuning.

The 3× gap *is* the value of encoded context. The conclusion is blunt:

> **Stop trying to out-reason the missing context. Encode it.**

This document specifies how to encode that context for **any** connection / schema /
dataset, generically — what can be derived automatically, what needs a human or usage
signal, and how it must be *enforced* (not merely injected) at query time.

---

## 1. The mental model: three tiers of context

Context divides cleanly by **what each layer can know without human help**:

| Tier | What it captures | Source | Human needed? | Aughor home |
|------|------------------|--------|---------------|-------------|
| **1. Structural** | encodings, composite keys, grain, joins, value formats | the data itself (profile + probe) | **No** — fully automatic | `build_intelligence`, `compute_join_map`, data catalog, composite-key guard |
| **2. Semantic** | concept→column dictionary, metric definitions | LLM proposes from schema+profiles; human/usage confirms | **Once** (cheap review) | `ontology`, metrics catalog, connection-KB |
| **3. Learned** | verified query templates, corrections | accumulates from usage | No (passive) | `trusted_queries`, connection-KB write-back |

Tiers 1 and 3 are largely **mechanical**. Tier 2 is **the wall** — and the one that
decides whether a connection performs at 27% or 90%.

---

## 2. Tier 1 — Structural context (fully automatic)

### What
Everything derivable by profiling and probing the live database, with zero human input:

- **Value profiles & encodings** — distinct values, enums, null rates, and crucially the
  *format* of a column: is it a comma-separated list of ids? a `YYYY-MM-DD` string? a code?
- **Composite & true join keys** — discovered by uniqueness probes, not guessed from names.
- **Grain & cardinality** — rows per entity; what one row *means*.
- **Relationship/FK inference** — which columns join which tables.

### Why it must be automatic
These are facts of the data. A human shouldn't hand-annotate them, and an LLM shouldn't
*guess* them — both are error-prone. They're cheap to *measure*.

### How (the probe pattern)
Run small diagnostic queries and read the results, e.g.:

```sql
-- Is (match_id, over_id, ball_id) a unique key, or does it fan out?
SELECT COUNT(*), COUNT(DISTINCT match_id || '-' || over_id || '-' || ball_id)
FROM batsman_scored;
-- 131259 vs 71298  → NOT unique → the real key also needs innings_no
```

```sql
-- What does the `toppings` column actually contain?
SELECT toppings FROM pizza_recipes LIMIT 5;
-- '1, 2, 3, 4'  → a comma-separated list of ingredient ids, not a single value
```

### Worked example — the `innings_no` fan-out (Spider local022)
Every model (including a strong reasoning model) joined `ball_by_ball ⋈ batsman_scored`
on 3 of the 4 key columns, omitting `innings_no`. The join silently fanned out and run
totals doubled → 93 "centuries" instead of 7. **One probe** (the `COUNT(DISTINCT subset)`
above) reveals the fan-out deterministically; a guard then adds the missing key. No
reasoning required — *measurement*.

### Status in Aughor
**Solved / available.** `connection.build_intelligence()` produces value profiles +
ontology; `compute_join_map` infers joins; `build_data_catalog` supplies sample rows; and
the composite-key guard + probe-and-ground loop (`aughor/sql/composite_key.py`,
`aughor/agent/sql_explore.py`) handle structural correction.

---

## 3. Tier 2 — Semantic context (the wall)

### What
The business meaning that the data **cannot** unambiguously reveal on its own:

1. **Concept dictionary** — natural-language business terms → schema columns/tables:
   - "customer" → `anon_id`? `customer_id`? `email`?
   - "channel" → `orders.traffic_source` or `campaigns.channel`?
   - "purchase" → which `event_type` / which page?
2. **Metric definitions** — the exact formula for each business metric:
   - `AOV = SUM(revenue) / COUNT(DISTINCT order_id)`
   - `repeat_purchase_rate = customers_with_2+_orders / all_customers`
   - `abandoned = added_to_cart AND NOT purchased`
   - `delivered_ingredients = base_recipe + per-order extras − per-order exclusions`

### Why it is *not* automatable from data alone
This is the honest limit. Two different columns can both plausibly be "the customer."
"Revenue" might or might not include tax, freight, or cancelled orders. The data is
**genuinely ambiguous**; resolving it requires a business signal — a human, a doc, or
accumulated usage. **No amount of profiling or reasoning closes this gap by itself.**

### Worked examples — where the agent fell off the wall

- **beautycommerce "top 10 customers"** — no customer table exists. One run invented
  `traffic_source AS customer_id` (garbage); another used `order_id` (top *orders*, not
  customers). The real entity was `anon_id`. **Concept-mapping failure.**
- **beautycommerce "AOV by channel"** — one run joined
  `attribution.touchpoint_type = campaigns.campaign_id` (a type-vs-id mismatch) → 0 rows.
  The right "channel" was simply `orders.traffic_source`. **Concept-mapping failure.**
- **Spider local075 "product funnel"** — assumed `purchase = event_type 3`; that filter
  matched nothing, so purchases came out as 0 and "abandoned" collapsed to `adds − 0`.
  "Purchase" was a different page/event. **Metric-definition failure.**
- **Spider local066 "delivered pizza ingredients"** — counted only base-recipe toppings;
  the correct figure adds per-order **extras** and subtracts **exclusions**.
  **Metric-definition failure.**

In every case the *structure* was fine and the SQL ran. The answer was wrong because the
**meaning** was wrong.

### How to populate it generically (propose → confirm → store)

1. **Auto-propose at onboarding.** An LLM reads the schema + Tier-1 profiles and drafts a
   candidate concept dictionary and metric catalog. It can guess well from signal:
   high-cardinality id columns that appear across fact tables are likely entity keys;
   a column named `traffic_source` with values like `organic/email/ad_click` is likely
   "channel"; a monetary column summed per `order_id` is likely "revenue".
2. **Confirm once (cheap human review).** Surface the draft for a 5-minute
   accept/correct pass — *per connection, not per query*. "customer = anon_id ✓",
   "revenue excludes tax ✓", "purchase = checkout-page event ✗ → it's `event_type 4`".
3. **Store** in the ontology + metrics catalog, keyed by connection.

> The cost is one short review per connection. The payoff is every future query inheriting
> the correct mapping — exactly the leverage that separates 27% from 90%.

### Status in Aughor
**Stores exist, the population flow does not.** `ontology`, `build_metrics_block`, and
connection-KB can hold all of this. What's missing is the **onboarding auto-proposal +
one-click confirmation** that fills them for a new connection. *This is the highest-value
thing to build.*

---

## 4. Tier 3 — Learned context (compounds from usage)

### What
Memory that accumulates as the connection is used:

- Every **confirmed-correct answer → a trusted query template** (a verified
  question→SQL pair the agent can reuse/adapt).
- Every **user correction → a concept/metric update** ("no, revenue excludes returns").

### Why
This is the "self-learning" that vendors market. It needs no upfront work — it captures
the long tail of semantics that onboarding missed, and turns each interaction into durable
context. Accuracy climbs with use.

### Example
A user asks "repeat-purchase rate by channel", the agent gets it wrong, the user corrects
the definition once. That correction (a) updates the metric catalog and (b) is stored as a
trusted template. The next person who asks anything involving repeat-rate or channel
inherits both. The connection has *learned*.

### Status in Aughor
`trusted_queries` and connection-KB exist; the **write-back loop on
confirmation/correction** is the gap.

---

## 5. The critical enforcement insight: supply, don't suggest

A lesson learned the hard way (twice this effort): **injecting context into the prompt is
necessary but not sufficient — the model frequently ignores it.**

- A verified metric formula was *proven* injected into the prompt, yet the generated SQL
  was byte-identical with and without it. The model didn't act on the note.
- Probe results showing a fan-out were placed in the prompt; the model still wrote the
  partial-key join.

Therefore Tier-2 context must be **enforced deterministically wherever possible**, not left
as a hint the model may or may not honour:

- **Resolve concepts before generation.** Substitute "customer" → `anon_id` in the plan
  *mechanically*, rather than hoping the model reads a glossary line.
- **Apply known metrics via templates / a semantic compiler.** For recognised metric
  shapes, emit deterministic SQL from the catalog; reserve free LLM generation for the
  genuinely novel parts.
- **Guard structurally.** Composite-key completeness, fan-out, and value-domain checks
  *rewrite* the query rather than asking the model to reconsider.

General principle, mirroring the structural lesson:

> **Deterministic *supply* of context beats hoping the model *uses* injected context.**
> The reliability ranking is: enforced substitution > template/compiler > injected hint.

(Caveat from observation: models reliably obey hard constraints like status filters, but
unreliably apply injected free-text formulas. Treat injected definitions as a fallback,
not the mechanism.)

---

## 6. End-to-end pipeline for a new connection

```
┌─ ON CONNECT (automatic, minutes) ───────────────────────────────────────────┐
│ Tier 1: build_intelligence + profiling + composite-key/value probes          │
│   → structural memory: encodings, composite keys, grain, joins               │
│   (re-run on schema change)                                                   │
└──────────────────────────────────────────────────────────────────────────────┘
            │
┌─ ONBOARDING (one cheap human pass) ─────────────────────────────────────────┐  ← the missing build
│ Tier 2: LLM drafts concept dictionary + metric catalog from schema+profiles  │
│   → user confirms/corrects once → stored in ontology + metrics catalog       │
└──────────────────────────────────────────────────────────────────────────────┘
            │
┌─ AT QUERY TIME ─────────────────────────────────────────────────────────────┐
│ 1. Deterministically RESOLVE concepts/metrics from the store (substitute,    │
│    don't just inject).                                                        │
│ 2. Generate SQL for the novel remainder.                                     │
│ 3. Structural guards rewrite (fan-out, composite key, value domain).         │
│ 4. Execute; verify result plausibility (non-empty, sane cardinality).        │
└──────────────────────────────────────────────────────────────────────────────┘
            │
┌─ WRITE-BACK (passive, compounding) ─────────────────────────────────────────┐
│ Tier 3: confirmed answer → trusted template; correction → ontology update.   │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 7. Honest limits

- **Tier 2 cannot be fully automated.** You cannot know "customer = anon_id" or "revenue
  excludes tax" from raw data with zero human or usage signal — the data is ambiguous by
  construction. Auto-proposal + a cheap confirmation gets you most of the way; pretending
  it's 100% automatic is how you ship confidently-wrong answers.
- **Encoded context is per-connection and must stay fresh.** Schema drift, new columns, and
  changed business rules require re-profiling (Tier 1) and occasional re-confirmation
  (Tier 2). Treat the memory as living, not one-shot.
- **This is the unglamorous lever.** It is not a cleverer prompt or a bigger model. It is
  curation + enforcement. That is precisely why it works where reasoning alone does not.

---

## 8. The smallest high-value first build

**Connection-onboarding "concept + metric dictionary" auto-proposal with one-click confirm**,
plus **deterministic resolve-before-generate** at query time.

That single addition is what turns Aughor from *"infers context per query (~27% regime)"*
toward *"knows the warehouse (Genloop regime)"* — on any connection, schema, or dataset.
