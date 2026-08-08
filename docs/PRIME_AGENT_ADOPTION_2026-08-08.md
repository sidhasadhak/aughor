# Adopting Prime Agent's Learnings in Aughor — Implementation Plan (2026-08-08)

> **Superseded as the plan of record by `docs/UNIFIED_ADOPTION_PLAN_2026-08-08.md`**, which merges this document with the open-webui conversational design into one layered program. This file remains the detailed Prime-Agent-side reference; workstream IDs (A/B/C/D/E/F/G) are cross-referenced there.

**Sources.** (1) The deep study of [PrimeIntellect/prime-agent](https://github.com/PrimeIntellect-ai/prime-agent) (v0.7.1, ~170k lines read across 5 subsystem deep-dives; distilled in memory `prime-agent-study-2026-08-07.md`). (2) A code-verified gap analysis of aughor's knowledge-capture path (2026-08-08), which confirmed: **a user's chat correction like "use `v_fact_sales`, not `fact_sales`, for general sales calculations" is not captured anywhere today** — no chat-side capture, no structured vocabulary for table routing, and a table retriever that couldn't enforce the preference even if it were stored.

**Status.** Proposal, nothing implemented. Every "current state" claim below was verified against the code on 2026-08-08; anything unverified is marked **PRE-CHECK**.

---

## 0. Guiding constraints

These come from aughor's own hard-won lessons and shape every workstream:

- **C1 — Serverless-first.** No resident processes (Vercel). Durable state lives in Postgres / YAML artifact stores / job rows. Prime Agent's daemon/worker/kernel topology is architecturally out of scope; we adopt its *invariants*, not its processes.
- **C2 — Deterministic guards beat LLM machinery** (the NL2SQL conclusion, proven 4×). Enforcement is always deterministic code; LLMs are used only to *propose* and *review*, never to enforce.
- **C3 — Flag-gate, default-off, byte-identical when off** (repo convention). Every behavioral change here ships behind a flag with an explicit off-state test.
- **C4 — Human approval for durable writes.** Prime Agent auto-applies `/refine` with no review UI — we deliberately diverge. Run-local notes may auto-apply; anything durable (overrides, agent revisions) lands as a *proposal* requiring one click. (Precedent for the risk: the currency-VARCHAR incident, where a feature's own recommended action destroyed data.)
- **C5 — Measure the premise before building** (Wave H lesson). Workstreams flagged **PRE-CHECK** start with an instrumented measurement, not code.

What we explicitly do **not** adopt: the IPython kernel / fork-server / dill machinery (wrong runtime, C1 + C2), resident agent-to-agent messaging daemons, and auto-applied self-refinement (C4).

---

## Workstream A — The Continual Harness (centerpiece)

### A.0 The pattern, distilled

Prime Agent's harness has five properties worth copying wholesale:

1. **Immutable base by construction** — the base prompt is compiled code; the mutable layer is a separate store with *no code path* into the base.
2. **Bounded edit vocabulary** — few kinds, three verbs (create/update/delete), hard schema validation. An entry claiming a capability must carry a machine-checkable reference to it.
3. **Every edit ships its own undo** — full before/after snapshots; rollback is synthesized inverse edits, itself recorded.
4. **A cheap review gate before the expensive write** — a small "is this evidenced, or one-off noise?" pass with a cooldown, biased to say no.
5. **Injection as a bounded index, not a payload** — top-N one-liners in the prompt; full content fetched on demand.

Aughor already independently invented pieces of this: the ontology override store's EXPLAIN-bind gate ([aughor/ontology/overrides.py](../aughor/ontology/overrides.py) — SQL-bearing human edits must bind against the live DB before they earn `verified`) *is* property 2. The overrides being YAML-in-git *is* property 3 (git is the snapshot/rollback). What's missing is the loop: capture → vocabulary → enforcement.

### A.1 Table-routing guidance (the found gap) — **highest priority**

**Verified current state.**
- `aughor/ontology/overrides.py` — human overrides, `{conn}/{schema}`-keyed, rebuild-proof, `source: human`, per-kind `_EDITABLE` field whitelist. **No routing vocabulary** (entity fields: `description`, `display_name`, `domain`, `active_filter`, `default_filters`, `exclude_when`, `lifecycle_states`, `terminal_states`).
- `aughor/ontology/semantic_block.py:32` `render_semantic_layer` — injects only *verified segments + computed properties*. Entity descriptions never reach the prompt via this path.
- `aughor/semantic/glossary.py` + `aughor/routers/knowledge.py` — table descriptions/grain/join hints reach schema text via `apply_glossary`; **advisory prose only, manual UI entry only**.
- `aughor/semantic/retriever.py:119` `retrieve_relevant_schema` — pure embedding top-k; **no preference/deprecation signal**; the preferred view may not be retrieved at all.
- `aughor/routers/investigations.py` (~:769 request field, `_apply_clarify_choice` ~:3084) + `aughor/semantic/ambiguity_ledger.py` — the only chat-capture loop; captures **only answers to system-initiated clarify questions** (`source=user`, override-wins by source rank, read back into prompts).

**Design.** Three pieces, in build order:

**A1.1 — Vocabulary (the store).** Add `"use_instead"` to `_EDITABLE["entity"]` in `overrides.py`. Value shape:

```yaml
# data/ontology_overrides/{conn}/{schema}/entity/{fact_sales_id}.yaml
target_kind: entity
target_id: fact_sales
fields:
  use_instead:
    table: v_fact_sales
    scope: "general sales calculations"   # free text, matched leniently (A1.2c)
    reason: "view pre-joins the dimension tables; base fact double-counts on returns"
source: human
edited_by: "…"
note: "captured from chat 2026-08-08"
```

Heed the module's frozen-values warning: we add a *field* to an existing kind, not a new `TargetKind`, so no directory-layout migration. Validation on write: the preferred table must exist in the connection's schema (deterministic existence check — the analog of the EXPLAIN-bind gate; a typo'd view name is stored `bound=False` and never enforced).

**A1.2 — Enforcement (deterministic, three points, phased).**
- **(a) Retriever post-filter** (`retriever.py`, inside `retrieve_relevant_schema` after `_retrieve`): load routing overrides for the scope; if a deprecated table survived top-k, **add its preferred twin to the keep-set**. Do *not* silently drop the deprecated table (the scope match is fuzzy; the question may legitimately need the base table) — keep both, annotated. Pure set arithmetic, no LLM. Falls through untouched when no overrides exist.
- **(b) Schema-text annotation** (in the `apply_schema_enrichment` / `apply_glossary` pass in `aughor/tools/schema.py`): render on the deprecated table's line: `⚠ prefer v_fact_sales for general sales calculations (human, 2026-08-08)` and on the view: `✓ preferred for general sales calculations`. This is the prompt-visible half; (a) guarantees the model actually *sees* both tables.
- **(c) SQL guard — phase 2, observe-only first**: post-generation check — generated SQL references a deprecated table AND the question matches the scope (lenient token overlap, same style as the ambiguity ledger's matcher) → increment a counter + stamp the answer trace. Only after observing real hit rates do we consider blocking/rewriting. (C5: measure before enforcing.)

**A1.3 — Capture (chat → proposal → click → store).** Extend the clarify-crystallize pattern from *answers to our questions* to *volunteered corrections*:
- Detection: in the ask/investigate flow, a lightweight post-turn check (or an explicit agent tool) recognizes corrective routing guidance and emits a `proposed_guidance` event carrying the structured fields + evidence (the literal chat turn, the run id).
- Review: the web UI shows a confirmation chip with the before/after diff (the override YAML rendered). One click → `POST` to the existing ontology override endpoints (`aughor/routers/ontology.py` already fronts the store).
- **Never auto-apply** (C4). The proposal is free to be wrong; the store write is not.
- Provenance: `note` records the source chat turn; `edited_by` the user. Evidence-pointing-at-a-real-run is mandatory (the Wave L rule: a receipt must point at a run that EXISTS).

**Flag:** `harness.table_routing`, default off; off = byte-identical (no retriever change, no annotation, no capture events).

**Tests.** Store round-trip + existence-bind unit tests (`tests/unit/test_ontology_overrides.py` extends); retriever post-filter unit (deprecated in top-k ⇒ preferred injected; no override ⇒ byte-identical output); schema-annotation golden test; capture endpoint test; the standard `pytest -k "ratchet or boundary or swallow or private"` pass on the diff. Off-state: assert `retrieve_relevant_schema` output unchanged with the flag off *and* with the flag on but no overrides present.

**Effort:** ~2–3 days end-to-end behind the flag. A spawnable task chip already exists for this (`task_34d493b4`).

### A.2 Generalized guidance entries ("prompt notes" beyond routing)

Not every correction targets a table. "Fiscal year starts in February," "always report EUR for LuxExperience" — durable, connection-scoped facts with no ontology target. (Note: some cases are *already* expressible — e.g. "exclude test orgs" is `exclude_when` on an entity; check the existing vocabulary before adding here. C5.)

**Design (smallest useful version).** A `note` kind in the override store: `{title, content, scope_tags}` per `{conn}/{schema}`, same provenance model. Injected prime-agent-style as a **bounded index**: top-N (start N=6) one-liners, `- [title]: content (truncated 180 chars)`, appended to the explorer/answer prompt build; full text on demand only if we later add a lookup tool. No retrieval machinery — deliberate; if the index grows past ~20 entries per connection we revisit with embedding recall, not before.

This kind *does* require a new `TargetKind` — follow the frozen-values discipline in `overrides.py` (the kind string is both YAML field and directory name; choose it once, keep it forever).

**Flag:** `harness.guidance_notes`. **Effort:** ~1–2 days once A1 lands (shares the capture UI).

### A.3 The post-run refine gate (auto-refine analog)

Prime Agent runs a cheap "should we even refine?" review every 25 turns with a 20-minute cooldown, biased to reject noise — and only then the expensive planner. Aughor's analog is **post-run, not per-turn** (explorations are batch):

- After an exploration/investigation completes, a small-model call over the run trace asks one question: *"Did this run surface a durable, evidenced lesson (a routing preference, a term definition, a data caveat)? Reject one-off noise, unsupported hypotheses, and transient tool output."*
- Output: zero or more **proposals** into the same review inbox as A1.3, each with `evidence = run_id` + the specific trace excerpt. Never auto-applied.
- Cooldown per connection (start: 1 proposal pass per connection per day) and a hard cap on proposals per pass (start: 3). Failure stamps the cooldown (Prime Agent's trick: a broken gate degrades to silence, not a retry storm).
- **Cost note:** this is one extra small LLM call per exploration — against the 1,000 req/day OpenRouter budget, gate it to explorations that produced findings.

**Existing precedent to bring under this regime:** the explorer already *silently auto-writes* column caveats during exploration (`aughor/agent/explore.py:1426` → `update_column`). That write predates this design and violates C4-in-spirit (no review, no run-id evidence). Migration: keep it (it's proven), but stamp provenance (`source: explorer, run_id`) and surface writes in the learning receipt so they're visible. Do not regress it to a proposal — it's column-caveat-grade, low blast radius.

**Flag:** `harness.refine_gate`. **Effort:** ~2 days. **Depends on:** A1.3's inbox.

---

## Workstream B — Faux provider + mechanical no-key testing

**Why.** The "tests were spending the LLM budget" lesson (`_ENABLED` read at module import; a fake that *fell through to the real provider* — see the war story in `tests/conftest.py:130`). Prime Agent solves this structurally, not by discipline: a scripted provider that registers as a *real* provider, plus a test entrypoint that mechanically strips every credential.

**Verified current state.** The seam exists and is good: all completions funnel through `LLMProvider._complete_on` (`aughor/llm/provider.py`), backends are named strings with an `_active_backend()` / `_fallback_backends()` chain, and `aughor/llm/coordination.py` is explicitly "one seam, swappable backend."

**Design.**
- **B1 — a first-class `faux` backend** in the provider registry, selected via `AUGHOR_LLM_BACKEND=faux`. API mirrors Prime Agent's:
  - `set_responses([...])` — a queue of scripted completions **or factories** `(system, user, role, model, call_index) -> completion`. The factory form is the killer feature: a test receives the *exact prompt the code built* (e.g. asserting A1.2b's schema annotation actually reached the prompt) and controls the reply.
  - Exhausted queue → **loud error** (`FauxResponsesExhausted`), never fallthrough. This is the exact failure that bit the old fake.
  - Can script failure shapes the reliability layer classifies: truncation (`finish_reason="length"`), rate-limit, malformed JSON — making `aughor/llm/reliability.py`'s taxonomy testable without live calls.
- **B2 — mechanical key stripping**: a conftest fixture (or `test.sh`-style wrapper) that unsets every provider credential env var and pins `AUGHOR_FALLBACK_BACKENDS=""` — so the chain *cannot* reach a paid backend from a test (the `together`-had-a-key incident, made structurally impossible). Assert at session start that no provider key is visible.
- **B3 — cache-aware usage simulation (optional, later)**: Prime Agent's faux provider simulates prompt-cache hit rates via common-prefix length; adopt only if/when cache-hit-rate regressions matter (pairs with `aughor/llm/cache_probe.py`).

**Tests are the deliverable here** — B1/B2 exist to make other tests cheap. Effort: ~1–2 days. No flag needed (test-only surface).

---

## Workstream C — Scheduler & jobs: claim-before-deliver, coalescing, honest uncertainty

**Verified current state — better than expected.** `aughor/routers/cron.py` is already at-least-once with idempotent-per-family ticks and `window_s` lookback; `aughor/kernel/jobs.py` has a supervisor that fails stale orphans by heartbeat; `aughor/kernel/queue.py` dispatches with idempotency keys.

**The gaps vs Prime Agent's scheduler:**

1. **Side-effectful deliveries lack a per-item durable claim.** Prime Agent advances `nextRunAt` *in the same durable write* that records the dispatch claim — a crash between claim and delivery leaves an explicit dangling record, never an ambiguous "did it fire?". Aughor's family-level idempotence covers re-computation but **PRE-CHECK**: verify whether brief/monitor *deliveries* (emails, webhooks) have per-item dedup or could double-send on a tick that crashes mid-delivery. If they can: add a claim row (`delivery_claims: family, item_key, period, claimed_at, completed_at`) written before the send; a later tick finding a dangling claim marks it `uncertain` and does **not** re-send within the same period.
2. **"Uncertain" is not a first-class outcome.** `jobs.py` marks stale orphans as failed with `error="orphaned (stale heartbeat, no live task)"`. Adopt Prime Agent's three-state honesty: add a distinct terminal status `interrupted_uncertain` (vs `failed`) so the Fleet view and any retry logic can distinguish "it broke" from "we don't know how far it got — check side effects before redoing."
3. **Recovery markers in agent context.** When an exploration slice's lease is reclaimed stale, the *next* slice should see an explicit in-state marker: `previous slice was interrupted mid-work (uncertain); verify recorded findings/side effects before repeating them`. Prime Agent injects exactly this into the model's transcript after a worker crash — the agent is told its own history has a gap. Wire it into the slice-resume prompt build. Cheap, and it directly prevents duplicate findings after an interruption.

**Flags:** `jobs.uncertain_status`, `explore.interrupt_marker`. **Effort:** 2, 3 are ~half a day each; 1 depends on the pre-check.

---

## Workstream D — Output budgets: model-derived, task-shaped

**Verified current state.** `aughor/llm/provider.py:118` — `_MAX_OUTPUT_TOKENS = 4096`, one env-tunable constant sent on every call to every backend. `aughor/llm/reliability.py` already does the hard part right: `finish_reason` is the truncation authority, `TRUNCATED` is a distinct failure kind, and truncations are never blindly retried. The known casualty: a ~25-finding briefing dies outright at 4096 (memory: `briefing-synthesis-length-cap`).

**Design.**
- **D1 — per-call budgets**: replace the flat constant with `output_budget(role, model)` = `min(model_max_output(model), role_cap)`, floor 256. Role caps: synthesis/briefing 16k, judge/gate 1k, extraction 2k, default 4096 (unchanged — so the off-state is byte-identical for un-migrated roles). `model_max_output` comes from `aughor/llm/models.py`'s catalog; **when the catalog doesn't know the model, keep the current constant** (Prime Agent's rule: never regress to worse-than-current defaults when a source is missing).
- **D2 — reduce-and-recompose for briefings**: on `TRUNCATED` in the briefing-synthesis path specifically, split the findings set and synthesize in parts + a merge pass, instead of failing the briefing. This is the compaction-shaped answer to a truncation that retries cannot fix.
- **D3 — budget accounting hygiene** (from Prime Agent's autonomous mode): wherever aughor budgets tokens across a loop (`aughor/agent/evidence_budget.py` — **PRE-CHECK** its accounting), exclude cache-read tokens from the spend, or cached-prefix loops exhaust budgets before real work does.

**Flag:** `llm.dynamic_output_budget`. **Effort:** D1 ~1 day, D2 ~1–2 days.

---

## Workstream E — Result handles + inventory re-injection — **PRE-CHECK first**

Prime Agent's single cleverest context trick: large results live outside the context as named handles; after compaction, the system re-injects an *inventory of what still exists* so the model reuses instead of recomputing.

Aughor's substrate is already handle-shaped (the warehouse is the persistent namespace; the durable-slicing spike concluded "pass a REFERENCE, not 49KB"). What's unverified is **how much result text actually enters exploration prompts today** and how often later slices recompute earlier results.

**E0 — the measurement (do this, defer the rest):** extend `aughor/kernel/metering.py` (per-run accumulator, already flushed to job rows) with two counters: chars-of-tool-results-injected-per-prompt, and repeated-identical-query count per exploration. One flag-gated logging change, then read the data. If repeated-query rates or result-injection sizes are low, **stop here** — the workstream dissolves (Wave H precedent: six of six pre-checks moved their scope).

**E1 — only if warranted:** a per-exploration handle registry in exploration state (`{handle_id, sql_hash, table_ref/materialization, schema, row_count, preview}`); prompts carry handle + preview instead of full results; slice-start injects the live-handle inventory. Design details deferred until E0 says they're needed.

---

## Workstream F — Contract governance (mostly done; two small remainders)

**Verified current state — the big piece already exists**: CI has an "API client · codegen drift" job (`.github/workflows/ci.yml:141`) regenerating `web/lib/api.gen.ts` from `scripts/dump_openapi.py` and failing on drift. The #269 incident (dual-method `api_route` → colliding operationIds → *nondeterministic* typecheck/build failures) slipped past it because the failure was in generation, not drift.

**Remainders:**
- **F1 — deterministic operationId-uniqueness test** (unit, local, fast): dump the OpenAPI spec in-process, assert operationIds are unique and every route is single-method. Turns the #269 class from a nondeterministic CI mystery into a named local failure. ~1 hour.
- **F2 — conscious-change revision stamp (optional):** commit a short digest of the OpenAPI JSON alongside a `CONTRACT_REVISION` constant; the same unit test asserts they match, so any contract change requires touching the constant — Prime Agent's `DAEMON_SCHEMA_ID` idea at one-tenth scale. Adopt only if silent contract drift recurs; the drift gate may already be enough. (C5.)

---

## Workstream G — Small wins (each ≤ half a day)

- **G1** — `web/.npmrc`: `min-release-age=7` (dependency cooldown; supply-chain guard; requires npm ≥ 11.10 — verify CI's npm first, older npm silently ignores it).
- **G2** — Engineering-principles addition (doc/memory, no code): *"Reversing durable intent must clear the durable record — not the in-memory flag — and persist the reversal before acting on it."* Generalizes aughor's existing tombstone-is-the-authority lesson (blob deletes) with Prime Agent's revive-tombstoned-workers bug as the cautionary tale.
- **G3** — One architectural boundary test in the ratchet family: pick the seam that hurts most when crossed (candidate: `aughor/ontology/*` stores must not import `aughor/llm` — keeps the knowledge stores deterministic and hermetically testable). Prime Agent enforces its client/runtime split with exactly such a test.
- **G4** — "Uncertain" wording convention: wherever we report interrupted work (WS-C), use the same sentence everywhere ("its result is uncertain and was not replayed") — Prime Agent repeats one phrasing at three layers, and the consistency is itself the feature.

---

## Sequencing

| Wave | Items | Rationale | Rough effort |
|---|---|---|---|
| 1 | **B1+B2** (faux backend + key stripping), **F1** (operationId test), **G1–G4** | Test infrastructure first — every later wave's tests get cheaper; all zero-risk | ~3 days |
| 2 | **A1** (table-routing: store field → retriever post-filter → schema annotation → capture chip) | The user-visible gap; chip `task_34d493b4` exists; B1's factory-form makes its prompt tests trivial | ~2–3 days |
| 3 | **D1+D2** (budgets), **C2+C3** (uncertain status, interrupt markers) | Kills a known briefing failure mode; honesty in job states | ~3 days |
| 4 | **A2** (guidance notes), **A3** (post-run refine gate) | Generalizes the harness once A1's capture UI is proven | ~3–4 days |
| 5 | **E0** (measure), then **E1**/**C1**/**F2** only if their pre-checks say so | C5: premise first | ~1 day + conditional |

Every wave is independently shippable and independently reversible (flags). Nothing in this plan modifies existing behavior with flags off — the off-state tests are part of each wave's definition of done.

## Risks & open questions

1. **Scope matching for routing guidance (A1)** is the one genuinely fuzzy piece: "general sales calculations" must match questions leniently without hijacking legitimate base-table queries. Mitigation: enforcement (a)+(b) only *add* information (inject the view, annotate both tables) — they never remove the base table; the only blocking enforcement (c) starts observe-only.
2. **Proposal fatigue (A3):** a refine gate that proposes too much trains users to dismiss. The cooldown + per-pass cap + reject-bias are the guard; tune with the acceptance-rate metric the learning router already exposes (`/learning/summary` verdict economy).
3. **Override store growth:** Prime Agent's harness never prunes and it shows. The bounded-index injection (A2) caps prompt cost, but add a count to `/learning/summary` so growth is visible from day one.
4. **PRE-CHECKs that may dissolve work:** delivery dedup (C1), evidence-budget accounting (D3), result-injection volume (E0). Per the Wave H record, expect at least one of these to change its workstream's scope — that's the point of checking.
