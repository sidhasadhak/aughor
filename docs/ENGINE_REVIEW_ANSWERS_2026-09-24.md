# Three questions from an ML engineer's review, answered from the code

*Measured 2026-09-24 against `main` at `ef02a91` (#546). Four read-only surveys of the code, and every claim this
document's conclusions rest on re-checked by hand; nothing here was run against a warehouse or a model (this
session had no model key). Each gap names the PENDING.md item that closes it.*

The reviewer's points, in their words:

1. *SQL is the agentic language to query and respond. SQL is generated for the user's text query and returned as
   text. Think of this as an encoder-decoder for text to text — how do we do this?*
2. *Actions are logged and you want to use these as training data to build a self-improving agent. From successful
   interactions meaningful labelled data can be extracted — how do we do this?*
5. *The learning has one weak point: the latent representation of the warehouse data is not part of the attention
   mechanism. This is the blocker — how do we do this?*

---

## 1 · Text to SQL to text: how it works today

**It is not an encoder-decoder, and nothing is trained.** It is retrieval-augmented generation: a general
decoder-only LLM (whichever the operator configures — no model id ships) fills a typed JSON schema, and
deterministic code does everything on both sides of that call. The "encoder" is non-parametric — code that
decides what the model reads.

The quick answer, stage by stage (`_answer_core`, `aughor/routers/investigations.py:1496`):

| # | Stage | By | What happens |
|---|---|---|---|
| 1 | Route | code (one small model call only on a borderline question) | overview, clarify gate, quick or deep (`aughor/agent/ask_router.py`) |
| 2 | Link | code | a keyword schema linker picks tables and columns within a budget by model tier (`aughor/tools/schema_linker.py`) |
| 3 | Assemble | code + embeddings | the Data Catalog (columns, five rows, value-verified joins), relationship cardinalities, governed metrics, the ontology's declared business terms, the values a question names resolved to real column values, trusted query templates, past corrections, few-shot SQL from earlier runs |
| 4 | Generate | **model** | one call returns `{sql, headline, chart_type, intent, …}` (`_ChatAnswer`) |
| 5 | Check and repair | code first, model last | sqlglot parse, fan-out rewrite, lint, identifier repair, literal binding, dry run; deterministic fixes before at most two model repairs (`aughor/sql/writer.py`) |
| 6 | Execute | code | read-only enforced by parsing, safety checks, row security, a row cap (`aughor/db/connection.py`) |
| 7 | Ground | code | the headline checked against the rows; caveats for known SQL traps |
| 8 | Narrate | **model** | prose from at most 20 result rows |
| 9 | Envelope | code | one structured answer every destination reads (CP-4) |

Two model calls on every answer (three when an ontology exists, plus repairs only after code fails), against
roughly twenty-five stages that never touch a model. The default `/ask` now runs a tool-using conversation agent
on top that calls this pipeline as one of its tools (two to eight more model calls a turn).

**What would make it a trained text-to-SQL model:** MI-4 (ROADMAP §3.9) — fine-tune an open model on
*(context, question) → SQL*. That only teaches the mapping if each training row carries the context the model
saw; today none does (§2).

**Found while measuring this — defects on the path as it stands:**

- After the Data Catalog replaces the schema text (`investigations.py:1862`), the parser the SQL checks share
  reads it as no tables at all (`parse_schema_tables` of the catalog → `{}`, reproduced), so identifier-case
  repair never runs on the default path and the SQL fixer loses its column lists. → **item 18**
- The conversation agent needs tool calls, and the `anthropic` backend raises before any fallback
  (`aughor/llm/provider.py:2040`, uncaught at `aughor/agent/tool_loop.py:178`): every quick `/ask` turn — the
  Slack bot's, and since 2026-09-24 the web's two main buttons — errors on that backend. → **item 17**
- The headline the model writes *before* its query runs streams to the screen as it is typed, numbers included
  (`headline_delta`, `investigations.py:2321`), and is replaced afterwards only on a flat contradiction.
  → **item 22**

---

## 2 · Logged actions as training data: how to do it

**The pipeline exists and yields about nothing.** MI-3 built exporters, a dataset store and a report against
MI-4's entry gates (≥1,000 SFT pairs, ≥150 preference pairs, ≥150 gold, 30 days of guard data). The dated count
is 5 human verdicts, none carrying SQL (2026-09-19). Why:

- **Nobody can say "yes" from the chat.** The chat's feedback form writes only `correct` or `reject`
  (`web/components/ChatMessage.tsx`); the surface where most answers are given cannot produce an accepted example.
- **The exported prompt is the answer's headline, not the question** (`aughor/learning/exporters.py:124`, `:151`).
- **No row carries the context the model saw** — connection, dialect, the schema slice, the resolved values. A
  model trained on these rows would learn question → SQL without ever seeing the data (§3).
- **The gate report double-counts:** it sums `row_count` over every version of a dataset
  (`aughor/learning/store.py:274`), so a corpus exported at 100 and again at 110 reads as 210.
- **A typed correction becomes the "chosen" SQL without being run**, and conflicting verdicts on one answer are
  not reconciled.
- **Rows cannot be joined:** history has no trace id, and the bridge that has one expires after 14 days, so a
  guard firing cannot be tied back to its question.

**What is plentiful** is graded only by execution: every statement (`audit_log`, full SQL, rows, error), every
guard that fired, every answer envelope, every re-check. That is executability, not correctness.

**How to turn it into labelled data** — by tier, never mixed silently:

| Tier | Source | Label |
|---|---|---|
| Gold | trusted queries a person approved after execution; per-agent goldens; the 139 hand-written benchmark pairs | reference SQL |
| Silver | a person's accept or typed correction on an answer — needs the chat accept, and a correction verified by running it | preference pair |
| Bronze | ran, returned rows, guards clean, never rejected, stable when re-checked | weak positive; hand-audited on 50–100 rows before any training use (ROADMAP §3.9) |
| Free pairs | every rewrite guard (fan-out de-fan, preflight repair) produces *wrong SQL → fixed SQL*, verified by execution — today kept as a 120-character prefix | preference pair |

Evaluation is execution match on a held-out gold set (the comparator exists: `evals/sql_accuracy.py`). Then MI-4
(SFT and DPO on an open model); reinforcement learning (MI-6) only with an execution-based reward, and only after
fine-tuning plateaus. Before any export leaves the box: org scoping, a scrubber that keeps SQL intact, and erasure.
→ **item 23**

**The half that works without training — and is broken in the same way.** Past SQL is reused at answer time as
few-shot examples (`aughor/tools/prior_analyses.py`), but only deep runs feed it — never a quick answer or a chat
turn (`skip_index` for direct mode) — a rejected query is never evicted, nothing checks guards before indexing,
and a dead vector store silently returns nothing. This is the self-improving loop that exists today.
→ **item 24**

---

## 3 · The warehouse's data in the model's attention: how to do it

**The diagnosis is right, and the gap is closer to hand than a model change.** With a hosted general LLM,
attention covers exactly the tokens in its context window; the warehouse's data can only enter attention as text
there, until we train our own model.

What reaches the SQL writer today: column names and types, the **first five rows** of at most 10 (24 on a
large-context model) linked tables, relationship cardinalities, and the values a question names once resolved.

What does not:

- **The profiler's statistics.** Distinct counts, null rates, ranges, quartiles, top values and the full value
  sets of name-like columns are computed and cached (`aughor/tools/profiler.py`), then dropped: the Data Catalog
  replaces the schema string they would ride (`investigations.py:1862`) and carries none of them
  (`aughor/tools/data_catalog.py:101`).
- **Values, when choosing tables.** The linker ranks tables by their *names*; a question naming a value
  ("Ferrari") does not raise the table that holds it.
- **Values on most warehouses.** Value resolution probes only columns whose name matches a keyword list (`name`,
  `brand`, `category`…) and does nothing on BigQuery or Snowflake schema text.
- **Any vector of the data.** Every embedding in the product encodes text *about* the warehouse — descriptions,
  documents, findings. Value matching is character trigrams.

**Three levels, in the order to build them:**

1. **In-context representation (now, no training).** Profile lines for the linked tables inside the catalog,
   under a budget; the rows the question's values select, instead of the first five; tables linked by the values
   a question names; value resolution on every warehouse. Measurable without a model: the linker's recall of the
   tables a gold query reads, on the eval sets, before and after; and a prompt-reach test that pins what the
   writer sees. → **item 19**
2. **Learned retrieval representation (next).** Embed each connection's value sets and column profiles in the
   vector store that already exists, so a question finds `make` by meaning when it says "Ferrari" — still text
   into attention, chosen by learned similarity.
3. **Learned model representation (MI-4 onward).** Fine-tune an open model on rows that carry profiles and
   resolved values, so the weights learn how this warehouse's data maps to SQL. Beyond that, a table encoder
   whose embeddings enter the model as soft tokens (TaBERT / TAPAS-style) needs open weights and our own training
   — research, not on the plan, and not worth starting before levels 1 and 2 are measured.

---

## Where each answer lands

| Point | PENDING.md item |
|---|---|
| 1 — the path's own defects | 17 (every backend) · 18 (the checks see the tables) · 22 (no number before it is measured) |
| 2 — labelled data | 23 (training data that means something) — built 2026-09-24 (ROADMAP §3.42): the chat's accept, question prompts with their context, verified corrections, the four tiers kept apart, a split that cannot leak · 24 (the few-shot memory) |
| 5 — the data in attention | 19 (the SQL writer sees the data) — level 1 built 2026-09-24 (ROADMAP §3.38): the inline-form fixes on by default, the DATA PROFILE block behind `grounding.data_profiles` until measured; levels 2–3 follow its measurement |
| Found on the way | 16 (documents stay inside their connection and organisation) |
