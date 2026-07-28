# Cognee Study — 2026-07-28

**Sources studied:** [topoteretes/cognee](https://github.com/topoteretes/cognee) (README,
API shape, deployment modes, Claude Code plugin design) · [cognee.ai](https://www.cognee.ai/)
(claims, pricing, concepts) · repo metadata. Research paper noted but not read:
[arXiv 2505.24478](https://arxiv.org/abs/2505.24478) — flagged as follow-up (§4 T3).

**Companion docs:** [`NEO4J_CONTEXT_GRAPH_STUDY_2026-07-28.md`](NEO4J_CONTEXT_GRAPH_STUDY_2026-07-28.md)
(same question, weaker subject — read its §2 for the Aughor-side inventory, not repeated
here) · plan of record [`PLATFORM_PROGRAM_2026-07-26.md`](PLATFORM_PROGRAM_2026-07-26.md).

---

## 0. Verdict up front

1. **This is the serious one.** Where Neo4j's `agent-memory` was a 384-star labs
   experiment, cognee is Apache-2.0, 29.5k stars, ~3 years old, 5M+ SDK runs/month, a
   research paper, and a full deployment story (pip → single Postgres → Docker → MCP →
   cloud). It deserved this study, and parts of it deserve theft.
2. **Do not adopt it as Aughor's memory engine.** Cognee's core move is extraction-first:
   an LLM reads arbitrary data and writes entities/relations into the graph. Our memory's
   entire warrant is that **no fact enters it that a model authored** (J4 — there is no
   `llm_inferred` provenance source). A €1.8M revenue answer cannot rest on a model's
   paraphrase of a document; ours rests on executed SQL and receipts. For warehouse
   analytics this is not dogma, it is the moat — and it is precisely what cognee cannot
   offer, because for *arbitrary unstructured input* extraction is the only possible move.
3. **Their flagship SQL use case is our shipped feature, with weaker warrants.** Their
   README's "Expert Knowledge Distillation (SQL Copilot)" — store expert SQL patterns,
   match schema, adapt the expert's logic, "update memory with new successful patterns" —
   is Aughor's trusted-query store + N1 answer-divergence pinning, which we shipped
   **this week** with stronger guarantees: exact verified SQL structure (not LLM-adapted
   reasoning), promotion only on all-runs consistency or an explicit human pin, warrant
   tiers stated in the prompt, and a measured cost of *not* settling (€1.84M spread on one
   question). "Successful" is doing a lot of unexamined work in their sentence — L5 caught
   exactly that laundering (consistency ≠ correctness) in our own prompt header. On our
   home turf, we are ahead.
4. **Nobody in this market publishes evidence that memory improves answers.** Cognee's
   site shows operational scale (runs/month, latency), not effect sizes — same as Neo4j.
   Our L2/L3 measured-and-refused results remain, oddly, ahead of the industry's public
   state of evidence. Their "feedback loops → recall weights updated" is exactly the
   plausible-but-unproven delta we refuse to ship unmeasured.
5. **Where they are genuinely ahead — and worth real enthusiasm:** production-grade
   **unstructured ingestion** (docs → ontology-constrained typed graph with citations,
   local-first so the NAMS privacy disqualifier does NOT apply), a **session-memory tier
   that consolidates into the permanent graph at session end**, **`forget` as a
   first-class API verb**, and top-of-market **DX** (4-verb API, one-Postgres deployment,
   MCP server, agent plugins with lifecycle hooks). Three thefts scoped in §3.

## 1. What cognee actually is

| Aspect | Grounded fact |
|---|---|
| License / scale | Apache-2.0 · 29.5k stars · created 2023-08 · 5M+ SDK runs/month claimed |
| Core API | `remember` / `recall` / `forget` / `improve` — plus session-scoped remember (fast cache, background sync to graph) and auto-routed search |
| Pipeline | ingest any format → LLM "cognify" into entities/relations (ontology-constrainable) → hybrid vector+graph retrieval with citations |
| Deployment | pip · **entire memory layer on one Postgres** (1.0) · Docker/compose profiles · MCP server · CLI + local UI |
| Cloud | $0 free tier / $2.50 per 1M tokens — data leaves the premises (disqualified for us, same as NAMS) |
| Agent integration | Claude Code plugin: lifecycle hooks (SessionStart/UserPromptSubmit/PostToolUse/Stop/PreCompact/SessionEnd) capture prompts, tool traces and answers into session memory, inject context per prompt, sync to graph at session end |
| Learning story | feedback stored → recall weights updated (no published effect sizes) |

## 2. Head-to-head where it matters

- **Provenance.** Theirs: LLM-authored triples with citations back to source documents.
  Ours: deterministic projection only — schema, measured join overlap, receipts, human
  pins; a model never writes a fact. Both attach provenance; only ours restricts *who may
  author*. For analytics answers this is the whole game.
- **The SQL-memory loop.** Theirs adapts expert reasoning via the model at recall time.
  Ours injects the exact verified SQL pattern and tells the model to reuse its structure —
  and the divergence detector measures, in the data's own euros, what unsettled answers
  cost. Ahead, with receipts.
- **Session capture.** Their plugin captures tool traces and answers per session and
  consolidates at session end. Our platform writes receipts per answer (stronger: the
  receipt is the answer's audit artifact), but our *consolidation* story (N3) is unbuilt —
  theirs is a working reference for its shape.
- **Forgetting.** They put `forget` in the four-verb core. We scoped N3 (dedup/supersede,
  source-freshness expiry, tombstones) and have not built it. Their API placement
  validates N3's priority; our design is stricter (tombstones over deletion, expiry tied
  to source-data movement rather than recency).
- **Unstructured data.** They are simply better: we have nothing for documents until G7's
  knowledge connectors, and our deterministic projection *cannot* ingest prose by
  construction. This is the one place their extraction-first design is the right design.

## 3. The thefts, scoped

**T1 — N3 design inputs (free, now).** Fold three cognee patterns into N3's spec:
consolidation happens at **session boundaries** (not continuously — cheap, natural
batching); `forget` is a **first-class operation** with the same API dignity as write and
read; recall weighting from feedback is admissible **only behind the eval plane** — a
weight change is a flag-shaped claim and gets measured like one (the L3 lesson, pre-paid).

**T2 — the document tier, when G7 lands (earmark, do not build now).** For Notion/
Confluence/PDF knowledge, extraction-first is the only possible design, and cognee is the
best open-source engine for it: Apache-2.0, runs entirely local (privacy disqualifier
void), ontology-constrained extraction, citations kept. The integration contract if we
take it: a **quarantined tier** with provenance `doc_extracted`, retrieved with the
weakest-warrant phrasing `build_trusted_block` already practices, never written into the
answer-grounding graph, and admitted to prompts only after our own eval plane measures it
helping on a doc-question corpus. Pilot: embed cognee locally, `remember` our own `docs/`
tree, compare recall against the existing lexical KB retriever on 20 questions.

**T3 — read their paper (free, one session).** "Optimizing the Interface Between
Knowledge Graphs and LLMs" is directly our open question from L2's refusal: *how a graph
slice should be serialized into a prompt* is a variable we never varied — we tested
read-back on/off, not read-back *formats*. If the paper has measured serialization
effects, it reshapes the N1-successor experiment for free.

## 4. What we are deliberately NOT taking

- **Cognee as the memory engine** — replaces a deterministic, committed, diff-readable
  artifact with LLM-extracted triples plus a service dependency and per-token extraction
  cost, and surrenders J4. No.
- **Cognee Cloud** — customer schema and findings on third-party infrastructure. No.
- **Feedback-weighted recall as shipped behaviour** — admissible only as a measured
  experiment (T1).
- **Their benchmark posture** — operational scale is not evidence of answer quality; we
  keep refusing our own unproven deltas, which is a feature.

## 5. One-line summary

Cognee is the most credible open-source answer to agent memory we have studied — genuinely
excellent at the problem we do not have (unstructured ingestion), openly unproven at the
problem we measured (does read-back help), and their flagship SQL use case is a weaker-
warranted version of what Aughor shipped this week. Steal the consolidation shape for N3,
earmark the engine for G7's document tier, read the paper.
