# Five-Repo Comparative Study — openworker · aisuite · atomic-agent · Understand-Anything · turboquant_plus (2026-07-23)

**Method.** Five parallel deep-read passes, one per repo, each over a full local clone (not READMEs —
actual source, tests, and docs), each briefed on Aughor's current surface (guard battery, free-tier
LLM layer, ontology/glossary plane, kinetic plane, wave roadmap) so findings came back pre-mapped.
Substance was verified, not assumed: test suites were run where feasible (turboquant: 977 passing),
upstream claims were checked online (turboquant's vLLM merge is real: vllm-project/vllm #38479),
and star counts were treated as a claim to audit, not evidence. Builds on the Foundry study
(`docs/PALANTIR_FOUNDRY_STUDY_2026-07-22.md`) and the flag-drift / provider-chain / request-budget
arcs (#197–#202).

**Thesis in one line.** All five repos — written by different teams for different domains —
independently converged on Aughor's founding bet, *LLM as unreliable emitter, deterministic layer as
authority*; the study's value is that each has production-hardened one plane where Aughor is
currently weakest: weak-model reliability (atomic-agent), governed actions + human-in-the-loop
durability (openworker), context read-back (Understand-Anything), binding-fidelity evals
(turboquant), and provider-quirk encodings (aisuite's inner layer).

**Honesty ledger up front.** None of the five is a hollow-star repo. But: three of the five ship as
single-squashed-commit mirrors of private repos (atomic-agent, openworker, Understand-Anything), so
development discipline is taken partly on faith; turboquant's headline performance numbers live in
the author's unverifiable C++ forks and its "papers" are self-published with heavy self-citation
(trust the direction, not the decimals); and aisuite's 15k stars considerably overstate the depth of
its core library — its own authors bypass it in production. Verdicts below reflect this.

---

## 1. Repo dossiers

### 1.1 `AtomicBot-ai/atomic-agent` — weak-model reliability engineering (~883★, TypeScript)

**Identity & verdict.** A local-first desktop operator agent (browse/shell/files/git/Telegram/MCP)
explicitly engineered so 4B–35B quantized local models survive long multi-step tool work.
**Substantially real, not vibes**: ~153k lines TS, 322 test files (~3,000 cases), a reproducible
GAIA L1 eval harness with a deterministic scorer (no LLM judge) and published NDJSON traces, a
memory-eval campaign with paired ON/OFF runs, and prompt-drift replay tooling. Code comments read
like post-mortems of real traces. Caveats: single-commit public mirror, self-labeled developer
preview, throughput claims depend on an external llama.cpp fork.

**Architecture (one paragraph).** One macro-turn = N steps; each step builds a prompt from a
byte-stable prefix (KV-cache reuse) + variable tail, runs ONE completion under a GBNF grammar that
constrains output to a JSON array of tool calls with the tool-name set enumerated *in the grammar*,
validates the batch (terminal verbs last, approval-gated tools solo, fail-closed on unknown resource
class), executes calls grouped by declared resource class (pure reads parallel, writes serialized),
compresses results, loops. Memory lives outside the prompt in SQLite+FTS5; the prompt sees pointers
(memory-index, top-K recalled notes, distilled lessons); writes happen via background
grammar-constrained reflection. No planner — a purely reactive loop, and the docs admit it.

**Load-bearing ideas (with source evidence):**
- **Grammar-enumerated tool calls** (`grammars/tool-call.gbnf`, `src/llm/grammar/build-grammar.ts`):
  format failure is *structurally impossible* locally — the sampler cannot emit an unknown tool or
  invalid JSON. Two hard-won details in comments: array-only root (small models have a first-token
  bias toward `{` and would never batch) and bounded trailing whitespace `{0,8}` (unbounded `ws`
  lets small models degenerate into newline loops until max_tokens).
- **Classify-before-retry** (`src/llm/reliability/detect-model-failure.ts`): truncated / empty /
  no-stop completions are detected and *never* retried verbatim — a retry cannot fix a truncation.
  All failures land in a canonical taxonomy (transport / grammar / model / tool / cancelled).
- **One bounded repair round-trip** (`step-executor.ts:468-591,1213`): at most one repair call, it
  carries the *specific* rejection reason per call index, it re-opens the model's reasoning block
  correctly, and it is hard-capped at 1024 tokens because reasoning models otherwise burn 8k
  self-deliberating.
- **Mechanical fixes before LLM fixes** (`trimBatchToFirstApprovalGated`): when the fix is
  deterministic (drop the offending element, trim the batch), it's done in code with a notice
  injected into the next prompt — zero extra requests.
- **Fresh-full / stale-stub rendering** (`src/session/conversation-turn.ts:106-198`): a tool result
  is rendered full-size only on the inference that consumes it; 400-char stub forever after; dropped
  turns become a deterministic one-line count summary, never an LLM paraphrase. Context cost of a
  result is paid once.
- **Two-tier tool catalog** (`src/prompt/stable-prefix.ts`): frequent tools get full schemas +
  few-shot in the prefix; rare tools get a one-line manifest and a `tool.view` load-on-demand — and
  a *failed* rare call auto-loads its schema for the next step.
- **Graduated loop governor with veto authority** (`src/agent/loop-detector.ts`): args-repeat →
  notice; args+result-hash no-progress streak → the call is vetoed *pre-dispatch* with a synthetic
  explanatory result; consecutive vetoes → forced graceful reply. Plus a **wandering detector** for
  many-distinct-queries-no-convergence churn, which repeat counters cannot see.
- **Deterministic gates in front of optional LLM calls** (`src/memory/retrieve/referential-detector.ts`,
  `embedding-gate.ts`): the query rewriter fires only when a pure function or embedding-cosine gate
  proves the message is a follow-up. Spend a request only when a deterministic check proves need.
- **Dual-enforced structured contracts**: every auxiliary call ships a GBNF grammar *and* an OpenAI
  `response_format: json_schema` equivalent — one contract, enforced by whichever mechanism the
  provider supports. For the tightest contracts they use *line-oriented micro-grammars*
  (`SET k=v` lines, not nested JSON): weak models fail line formats far less, and a line parser
  salvages partial output where one bad brace loses everything.

**Weaknesses.** The killer trick (GBNF) does not transfer to hosted APIs — the reliability story is
a local-inference story; the transferable parts are the repair/validation/gating layers. Benchmarks
are narrow (one competitor, one hardware config). Marketing gloss on an external fork. Bespoke
non-chat-template prompt monolith needing per-model-family profiles. Aspirational docs (59–238KB
design fabrics, some explicitly unimplemented) mixed with shipped reality. No planning layer.

### 1.2 `andrewyng/openworker` — governed actions and human-in-the-loop durability (~741★, Python+TS)

**Identity & verdict.** A local-first Tauri desktop "AI coworker": approval-gated agent loop over
files/shell, ~25 SaaS connectors, MCP, scheduled automations, Slack/Telegram surfaces, BYO model
key. **A real product in open beta**: signed/notarized DMG with auto-update, OAuth broker with PKCE,
812 backend tests across 79 files, a `FakeSlack` double driving the *real* slack-bolt handler,
hermetic Playwright e2e. The engine core (`coworker/engine.py`, 1,033 lines) is unusually
disciplined; the rim is monolithic. Same product family as aisuite (see §1.3) — this is the app the
aisuite repo's `platform/` directory hosts.

**Architecture (one paragraph).** `TurnEngine` owns the loop and emits a typed event stream
(TOOL_PROPOSED, PERMISSION_REQUIRED, PLAN_PROPOSED, INTERRUPTED, …) as the sole contract with every
surface. Approvals are out-of-band: the engine awaits an injected async approver. A provider router
dispatches by `provider:` prefix over a canonical OpenAI-shaped history, so mid-session model switch
is a field write. A permission plane classifies every call into READ / WRITE_LOCAL / EXEC / EXTERNAL
with path-scoped writes and per-task standing rules. A cross-session Inbox queues approvals and
questions and mirrors them to Slack/Telegram as button messages. An autonomy plane gives scheduled
tasks and self-wake (`sleep_until`, `wake_on_event`). FastAPI control plane; sessions persisted as
JSONL + SQLite index.

**Load-bearing ideas:**
- **Target-bound standing grants** (`tool_defs.py:target_arg_for`, `automation/models.py:27-58`,
  `permissions.py:149-166`, `engine.py:541-548`): an auto-allow grant is never "allow
  `send_message`" but "allow `send_message` → `slack:C0123:1700….000100`" — exact string equality on
  a *declared* target argument; eligible only for EXTERNAL-risk tools, never exec; stored on the
  owning automation so revocation is per-owner and deletion takes grants along; re-read on every
  check; and **every auto-allowed call cites its exact rule in the audit log and tool card**. The
  exact-target binding is what makes auto-allow safe — a deterministic guard.
- **Resolve-once Inbox + durable resume** (`inbox.py:295-332`, `engine.resume`,
  `tests/test_durable_resume.py`): each item resolves exactly once (first-responder-wins;
  `resolve()` returns False on the second attempt), awaitable across surfaces; a restart replays
  trailing unanswered tool_calls, and the re-raised prompts find the already-resolved Inbox item —
  idempotent by `(session_id, tool_call_id)` — and continue without re-prompting. *Unattended* mode
  changes where the human is reached, not the autonomy ceiling.
- **Sidecar discipline with one choke point** (`engine.py:878-982`): persisted messages carry
  display-only keys (`source`, `_display`, `reasoning`, whole `notice` roles) stripped in exactly
  one function that produces the provider feed. Best instance: Gmail privacy filters return a
  fabricated 404 *indistinguishable from a real miss* ("a tombstone invites probing") while the
  hidden-count rides `_display` to the user's card and audit only.
- **No-orphan interrupt/retry** (`engine.py:120-148,217-248,504-515`): stop works from any state;
  every pending tool_call still gets a tool-error result (hosted chat templates reject orphans, and
  durable resume would re-prompt them); partial streamed text is persisted as what-the-user-watched;
  `retry()` is gated on tail-is-error and looks *through* model-switch notices so "switch model,
  then retry" is a supported recovery path.
- **Declarative parallelism + permission-plane-enforced read-only subagents**
  (`engine._parallel_safe`, `tools/subagent.py`): only metadata-declared low-risk calls run
  concurrently, writes stay ordered; the explorer subagent is read-only because the child's
  PermissionEngine hard-blocks writes regardless of what the child model emits — not because the
  prompt asks nicely.
- **A vouched model matrix** (`coworker/providers/matrix.py`): deliberately small, keyed by full
  routed id, per-model capability flags (tools/vision/pdf/parallel/streaming) + verified-on date;
  the single source for graceful degradation and the picker; unknown ids fall back to conservative
  heuristics "at your own risk."
- **Hermetic test substrate at product scale**: FakeSlack, ScriptedProvider, mocked-WS e2e; the code
  reads as a decision log (comments cite decision-doc sections, dates, owner calls).

**Weaknesses.** God objects at the rim (`SessionManager` 3.5k lines; `integration_tools.py` **4.9k
lines of hand-written closures and copy-pasted JSON schemas** — the cautionary tale for any
connector/action surface). The command allowlist is prefix-string matching
(`permissions.py:205-209`) — `git status ; rm -rf ~` sails through; for a product whose central
promise is approval-gating, this is the weakest link. Risk classification falls back to
read-by-default, so one missing annotation silently makes a write auto-run. The decision log the
code cites is not in the repo. JSON-file whole-rewrite stores with no cross-store transactionality.
Zero behavior evals (mechanics exhaustively tested; agent output quality unmeasured).

### 1.3 `andrewyng/aisuite` — a thin famous core wrapped around a good inner layer (~15k★, Python)

**Identity & verdict.** Three layers in one repo: (1) the famous chat-completions unification — ~28
provider adapters behind an OpenAI-shaped API; (2) a newer Agents API (callable tools, MCP, tool
policies, tracing); (3) `platform/` — the OpenWorker desktop app, containing **its own separate,
better-engineered provider stack** (`platform/coworker/providers/`), which is the most
Aughor-relevant code in the repo. Actively maintained (HEAD 3 days old at study time; 507 test
functions) but pre-1.0, and adapter depth is concentrated in exactly 3 providers
(OpenAI/Anthropic/Gemini); the rest are lowest-common-denominator shells (29-line LMStudio adapter).
**The single most telling fact: the repo's own authors did not trust the core library for their
production app** — OpenWorker reimplements the provider layer from scratch with capabilities,
verification, curated ids, and error classification. That independently confirms Aughor's choice to
hand-roll.

**Core-layer reality check (why not to adopt):**
- **Error handling is actively destructive**: the universal pattern is
  `except Exception as e: raise LLMError(f"An error occurred: {e}")` — status code, `retry-after`,
  quota metadata (Google's `quotaId`!), request id, all flattened to a string. No taxonomy
  (no AuthError/RateLimitError/QuotaError). Any consumer wanting failover must string-parse.
- **Zero resilience**: across the whole core, resilience is one HuggingFace 503 retry and one
  Cerebras re-wrap. No backoff, cooldowns, failover, budgets, token caps (except a silent
  `max_tokens=4096` injected for Anthropic), no rate-limit awareness.
- **Correctness gaps in the famous paths**: the Anthropic non-streaming path takes `next(...)` —
  the *first* `tool_use` block only, silently dropping parallel tool calls
  (`anthropic_provider.py:317`); the Vertex adapter says "Assuming single function call for now."
  Streaming is implemented for 5 of 28 providers; the OpenRouter adapter holds an `openai.OpenAI`
  client that streams natively and simply never wired it.
- **No model-id validation, no catalogue, no capability metadata** in the library — all of that
  exists only in OpenWorker's inner layer, unexported.

**The inner layer worth stealing (`platform/coworker/providers/`):**
- **Error classification by error-body markers, not HTTP status** (`errors.py`): marker tuples taken
  verbatim from vendor bodies (`insufficient_quota`, `credit balance is too low`,
  `model_not_found`, `permission_error`) with the explicit rationale that a 404 also means "wrong
  base_url" and a 429 also means "slow down." Ambiguous shapes require compound evidence
  (Anthropic's 404 needs both `not_found_error` *and* the model id before classification).
  Unrecognized → raw error surfaces unchanged; friendly messages always keep the raw text attached.
- **Fix-exactly-what-the-server-named one-shot retry** (`openai_provider.py:57-72`):
  `max_tokens` → `max_completion_tokens` swap happens *on rejection only, never preemptively* —
  because behind one OpenAI-compatible endpoint sit servers with contradictory parameter dialects.
  One retry, one named fix, else re-raise.
- **Curated, date-stamped model matrix** (`matrix.py`): keyed by FULL routed ids including reseller
  "ugly names"; header: "Ids verified against vendor/reseller catalogs on 2026-07-04; refresh the
  reseller rows when catalogs rotate." Custom ids fall back to conservative heuristics.
- **Per-provider credential verification** (`registry.py:verify_provider_key`): one cheap read-only
  `GET /models` per provider, never raises, distinguishes bad-key (401/403) from wrong-endpoint
  (Ollama's 404) from unreachable. Plus provider detection from key shape (`sk-ant-`/`AIza`).
- **No cross-vendor key leakage** (`registry.py:_openai_compat`): OpenAI-compatible vendors resolve
  keys from their OWN profile only — a configured OpenAI key is never silently sent to a different
  vendor's endpoint.
- **Anthropic streamed-usage accounting done right** (`anthropic_provider.py:convert_stream_event`):
  block-index→tool-index remapping; prompt tokens captured at `message_start`, output tokens at
  `message_delta`, usage (incl. cache-read tokens) on the final chunk — the correct way to meter
  streamed spend.
- **Gemini quirks as an allowlist** (`gemini_provider.py` `SCHEMA_KEYS`): only keys Gemini's OpenAPI
  subset accepts survive recursive sanitization; parameter-less functions omit `parameters` entirely
  ("Gemini rejects empty objects"). Sibling: `utils/tools.py:_normalize_json_schema` inlines
  `$defs/$ref` and flattens `anyOf:[X, null]` — exactly the Pydantic shapes that 400 on
  Gemini/Anthropic.
- **Fail-eager misuse checks** (`client.py:_prepare_stream_kwargs`): stream+max_turns and
  stream+MCP rejected at the call site, before the generator is handed back; the base class's
  default for unimplemented streaming is an explicit raise, not a fake stream or a hang.

### 1.4 `Egonex-AI/Understand-Anything` — the context read-back machine (~75k★, TypeScript)

**Identity & verdict.** A coding-agent plugin (Claude Code native; 17 other platforms via
symlinked markdown skills) that runs a multi-agent pipeline over a codebase, emits one versioned
JSON knowledge graph (`.ua/knowledge-graph.json`), and serves an interactive React dashboard.
Real and polished (~600 merged PRs referenced, 8 README languages, versioned deterministic
benchmark harness, three levels of tests). **The 75k stars are explained by a genuine mechanic, not
hype**: the graph is *just a committed JSON file* — teammates run `npx …viewer.tgz` and get the full
dashboard with **no LLM, no API key, no infrastructure**. Generation cost is paid once per team;
consumption is free. Second hook: one `install.sh` symlinks the same skills into every agent
platform — it rode the coding-agent wave without betting on a platform. Third: a stated ideology —
"graphs that teach > graphs that impress" — that visibly shows in the product.

**Architecture (one paragraph).** Orchestration is an 858-line SKILL.md runbook the *host LLM
executes* (no orchestrator program): scan → deterministic semantic batching → up to 5 concurrent
file-analyzer subagents → assembly → layers → tour → validation → save. Extraction is a strict
deterministic/LLM split: tree-sitter WASM extracts functions/classes/imports/call-graph for 10+
languages plus 12 non-code parsers (SQL, Terraform, Dockerfile…); imports are pre-resolved once into
an `importMap` and the analyzer prompt *forbids* re-deriving them, mandating 1:1 emission with a
self-check sum. Deterministic recovery nets (`merge-batch-graphs.py`) normalize IDs, dedupe, drop
dangling edges, re-emit dropped import edges, and flip LLM-inverted `tested_by` directions — **the
LLM is treated as an unreliable emitter with a deterministic post-processor as authority.** Data
model: 27 node types / 38 edge types; mandatory non-empty plain-English summaries; one JSON file per
project, committed to git; no database anywhere.

**Load-bearing ideas:**
- **The hairball is structurally impossible, not stylistically discouraged**: at every zoom level
  the renderable edge set is aggregated. Level 1: layers as cluster cards, all cross-layer edges
  collapsed to one aggregated edge per pair with a count label (`utils/edgeAggregation.ts`).
  Level 2: nodes grouped into containers by folder longest-common-prefix, falling back to Louvain
  community detection when folder grouping degenerates (`utils/containers.ts`), with **two-stage
  lazy ELK layout** — containers laid out as opaque atoms first, children laid out only when a
  container is expanded, positions cached. Cross-layer references render as **portal nodes**
  (click → navigate) rather than edges to invisible nodes. Level 3: detail toggles, 1-hop focus
  mode, token-gated code viewer.
- **"Teach" is operationalized as a computed curriculum** (`agents/tour-builder.md`): a
  deterministic topology script first (fan-in ranking = importance; scored entry-point detection;
  BFS from the entry point = natural reading order; coupled-cluster detection), then the LLM
  narrates 5–15 ordered steps mapped from BFS depth, each required to connect to previous steps.
  Pedagogy grounded in graph topology, not prose vibes.
- **Grounded Q&A without RAG infrastructure** (`skills/understand-chat/SKILL.md`): freshness-check
  the graph against git → grep node names/summaries/tags for the question → grep edges for matched
  IDs (1-hop subgraph) → **answer only from that subgraph, citing files**, warning when the graph
  lags the code. A grounding protocol, not a service.
- **The closed loop**: hooks detect commits → structural fingerprints
  (`core/src/fingerprint.ts`) classify the change (`change-classifier.ts`: SKIP /
  PARTIAL_UPDATE / ARCHITECTURE_UPDATE / FULL_UPDATE with explicit thresholds) →
  token-proportional refresh (cosmetic commits cost zero) → typed staleness states
  (fresh/dirty/stale/unknown) surfaced in a UI banner. Context is captured *and read back* every
  session.
- **Teach-quality metadata enforced deterministically**: the inline validator requires non-empty
  summary/tags on every node, no dangling edges, every file in exactly one layer; the summary
  prompt ships anti-patterns ("Bad: 'The utils file contains utility functions'").

**Weaknesses.** The pipeline is a prompt, and the docs are littered with scars of the host model not
obeying it ("batch-fused-8-13.json silently dropped, losing every node with no error"); a thin real
orchestrator would delete half the defensive text. **Semantic search is BUILT but not WIRED**: the
cosine-similarity engine exists, the UI has a fuzzy/semantic toggle, and `store.ts:540` admits both
modes run the same fuzzy engine — nothing ever generates embeddings; the README oversells it.
LLM-inferred edges have no provenance (hardcoded per-type weights cosplay as confidence). Semantic
staleness of unchanged-neighbor summaries is unsolved. One monolithic JSON in browser memory;
10MB+ needs git-lfs. 27 node types where a plugin mechanism belonged. The auto-update hook injects
"You MUST … do not ask the user" into sessions — effective, but self-authorized prompt injection.

### 1.5 `TheTom/turboquant_plus` — eval methodology disguised as a quantization repo (~7k★, Python)

**Identity & verdict.** Not quant finance: a reference implementation of Google's TurboQuant
KV-cache quantization paper (Walsh-Hadamard rotation + PolarQuant + optional QJL residual), plus 16
self-published validation papers, plus — the actual shipped product — **`refract-llm`, a 4-axis
KV-cache fidelity evaluation framework** (the `turboquant` package itself is excluded from the
wheel). Substance verified: 977 tests pass in a fresh venv; the claimed vLLM upstream merge is real
(`--kv-cache-dtype turboquant_k8v4`); 342 commits, 923 forks. Honest caveats: performance claims
live in the author's C++ forks; single author ("Independent Researcher"); papers are self-published
markdown with n=1 community confirmations; README drift (lists modules that don't exist, wrong test
counts). **Trust the direction, not the decimals.** The quantization math is near-zero direct value
to Aughor; the transferable asset is REFRACT's evaluation methodology.

**REFRACT's methodology (the part that matters):**
- **Reference-anchored scoring**: nothing is scored absolutely; every axis measures *distance from
  the same model's fp16 self* on the same inputs. Motivation is documented and rigorous
  (`docs/papers/attn-rotation-and-ppl-artifact.md`): on gemma-4 instruct models, quantized KV
  scores 7–42% *better* corpus perplexity than fp16 while KL divergence says it drifted most —
  PPL reads miscalibration as improvement. Absolute proxy metrics can invert.
- **Floor verification** (`refract/score.py` MIN_FLOOR): the harness scores reference-vs-reference
  first; if the reference doesn't agree with itself ≥ 99.5, all deltas are refused as
  untrustworthy. This caught a real broken eval: a "secret password" needle triggered refusal
  training so even fp16 scored 0 — the floor exposed the broken prompt, which was replaced with a
  neutral needle (`refract/axes/rniah.py:68-76`).
- **Excess-drift-over-control** (`refract/axes/plad.py`): brittleness = candidate drift under
  typo/case/punct/synonym perturbation *minus* the reference's own drift under identical
  perturbation and seed — the model's inherent instability is subtracted out.
- **Measure in the units the system consumes** (`refract/axes/trajectory.py` docstring): the
  original axis compared retokenized decoded *text* and suffered up to 2.87× token inflation; fixed
  by capturing token IDs at decode time. A textbook unit-mismatch bug, kept and documented.
- **Harmonic-mean composite + plain-English diagnosis**: one broken axis tanks the composite by
  design; `interpret_pattern()` turns the band pattern into 1–3 diagnosis sentences.
- **Dataset-identity guard**: KLD refuses to score against a reference built from a different
  corpus; corpus path/size/SHA recorded in every report.
- **Operational hygiene worth copying**: `selftest` (30s preflight of binaries/flags/model),
  `repeatability` (run N times, per-axis stdev), regression tests named after the bugs they pin
  (`refract/tests/test_bugs.py`), a pre-push quality gate checking both quality and speed ratios.
- **Proxy-metric inversion, measured** (`docs/papers/why-mse-fails-for-kv-quantization.md`): a
  centroid change improving K-cache MSE 1–13% across five model families causes 70–90% KL
  regressions, because softmax is non-linear and sparsity-concentrating. "An MSE-improving change
  is not a safe optimization. It is an uncontrolled intervention." The canonical citation for
  Aughor's exact-match-on-grounded-numbers stance.

---

## 2. The meta-patterns (what the five repos agree on)

1. **Determinism-as-authority is now the winning pattern, everywhere.** UA's deterministic
   post-processor repairs everything the LLM emits; atomic-agent's grammars make invalid output
   unsamplable and its normalizers fix the rest in code; openworker's permission plane enforces
   read-only subagents structurally; REFRACT refuses to trust any delta a deterministic floor check
   can't certify. Aughor's guard battery is not a contrarian bet anymore — it is the consensus of
   everyone who shipped. The competitive question has moved from "guards or not" to *which planes
   have guards*.
2. **The request is the unit of cost discipline.** Atomic-agent gates every optional LLM call
   behind a pure function, caps every repair, and batches background writes on a cadence; UA's
   change classifier makes cosmetic commits cost zero tokens; REFRACT batches all ref-side calls
   before cand-side to avoid reload thrash. Aughor's own finding (#200/#202: the constraint is
   request RATE) is the same law observed independently three times.
3. **Intent records beat process state.** Openworker's Inbox items and standing grants survive
   restarts and are the authority the process re-derives itself from; UA's committed graph +
   fingerprint baseline is the authority the hooks re-derive staleness from. Aughor already banked
   this lesson once (the upload tombstone); these repos show it generalizes to approvals,
   automations, and context artifacts.
4. **The artifact is the distribution strategy.** UA's committed JSON + zero-infra viewer is why it
   has 75k stars and Aughor doesn't. A generated artifact that colleagues can consume with no
   server, no key, and no login converts one user into a team.
5. **BUILT-but-not-WIRED is a failure mode that hits good teams.** UA ships a semantic-search UI
   toggle where both modes secretly run the same fuzzy engine; openworker's code cites decision
   docs that aren't in the repo; aisuite's OpenRouter adapter holds a streaming-capable client and
   never wired streaming. Aughor's leverage gate (BUILT→WIRED→TESTED→LEVERAGED) is the right
   ratchet — these are three independent confirmations of why it exists.
6. **Single-commit mirrors are the new normal for launched OSS** (3 of 5 repos). Judge the code,
   not the history — but also: Aughor's public, honest history is itself a differentiator worth
   keeping.

---

## 3. Adoption plan — ranked

### Tier 1 — cheap, deterministic, directly attacks the free-tier request budget

**T1.1 — Shared reliability layer for structured LLM calls** *(from atomic-agent →
`aughor/llm/provider.py` + call sites)*. There are ~80 `provider.complete` call sites (ROADMAP §0.5
already flags that per-agent pins drive most volume). Build one shared path with four stages:
1. *Deterministic normalizer first*: fence-stripping, trailing-comma repair, enum nearest-match,
   schema-driven extra-key dropping — before any repair call is considered. Emit a counter for
   "repair calls saved."
2. *Classify before retry* (`detect-model-failure` port): truncated/empty/no-stop → do NOT re-send
   the same prompt; record in a canonical failure taxonomy per call.
3. *One bounded repair*: at most one repair request, carrying the specific validation error per
   element, `max_tokens`-capped.
4. *Line-oriented micro-formats for the tightest contracts*: `SET k=v` lines instead of nested JSON
   where feasible — weak models fail line formats less, and a line parser salvages partial output.
Also: attach an explicit deterministic gate to every *optional* LLM call on the /ask and ADA paths
(follow-up detectors, digest triggers) with a "skipped by gate" metric — the request-count
application of the leverage gate.

**T1.2 — Provider-plane hardening** *(from aisuite inner layer + openworker →
`aughor/llm/provider.py`, `kernel/agents.py` bindings)*.
- *Error-body-marker classification* in the failover chain: `insufficient_quota` / "credit balance
  too low" → skip provider for the day (cooldown can't fix it); `model_not_found` / "does not
  exist or you do not have access" → **config error — fail the binding loudly, never fail over**
  (silent failover masks guessed model ids, our exact historical bug); plain 429 → existing
  cooldown. Compound evidence for ambiguous shapes; raw error always attached. Extends the "Google
  quotaId is the authority" lesson chain-wide.
- *Vouched model matrix* (~150 deterministic lines): full routed id → capabilities + verified-on
  date + tier eligibility (`fast` eligible: yes/no). **Per-agent bindings must resolve through
  it**, structurally killing both "guessed model ids" and "pin clobbered the fast tier." The live
  OpenRouter catalogue diffs against it at startup → drift *warning*, same shape as the flag-drift
  audit.
- *Per-provider cheapest-call health check* that classifies failure (bad key ≠ wrong endpoint ≠
  unreachable) — fixes "health check covered only the coder model."
- *Fix-what-the-server-named one-shot param retry* for the OpenRouter surface
  (`max_tokens`↔`max_completion_tokens`, reasoning-effort pins) — on rejection only, never
  preemptively; fits the one-retry budget.
- *Two quirk encodings to diff against our Gemini/streaming paths*: Gemini tool/response-schema
  allowlist sanitization (unsanitized Pydantic output = silent 400), and Anthropic streamed-usage
  accounting (input at `message_start`, output at `message_delta`, usage on final chunk) if the
  chain ever streams from Anthropic.

**T1.3 — Context-budget discipline for ADA** *(from atomic-agent → `aughor/agent/`,
`aughor/llm/context_budget.py`)*.
- *Fresh-full / stale-stub evidence rendering*: each evidence blob rendered full only for the
  immediately-following synthesis step; thereafter a deterministic stub (`finding-id + metric names
  + row/col counts`); grounded numbers re-fetched by id from the finding store, never re-generated.
  Sibling of #202's deterministic condensation; pays each blob's context cost once.
- *Two-tier schema catalog*: one-line manifests of all tables/glossary terms in the prompt; full
  DDL/glossary bodies only for plan-touched entities; **auto-inject the full schema of any table a
  SQL error names** (error-path autoload).
- *Wandering detector for exploration waves*: args-hash repeat → notice; args+result-hash
  no-progress streak → deterministic veto with an explanatory synthetic result; consecutive vetoes →
  graceful wave termination; plus a distinct-args-spread counter for the
  many-distinct-queries-no-convergence churn that repeat counters can't see. Free-tier models need
  this most.

### Tier 2 — kinetic-plane and answer-path hardening (openworker as reference implementation)

**T2.1 — Target-bound standing grants** *(→ `govern/actions.py`, `ontology/actions.py`, trust
receipt)*. A standing-grant record `(action_id, exact_target, owner_id)` owned by the automation or
briefing that minted it; consulted by the K-plane gate via exact string equality; mintable only from
an approval card, and only when the action declares a single target argument; never for exec-class;
listed and revocable inside the trust receipt; every auto-allowed invocation cites its grant in the
audit log.

**T2.2 — Resolve-once inbox + durable resume** *(→ new pending-interaction store; ADA/briefing
runners)*. Items resolve exactly once (first-responder-wins; second resolution no-op), keyed
idempotently by `(run_id, call_id)`; agents await the store; a restart rebuilds suspensions from the
persisted transcript and finds already-resolved items without re-prompting. Unattended runs route
prompts to the inbox instead of dying with the process.

**T2.3 — No-orphan interrupt/retry on streamed /ask** *(→ /ask streaming path; composes with the
#197 chain)*. A mid-stream 429/failure leaves exactly: persisted partial (what the user watched) +
typed error-notice tail; `retry()` gated on tail-is-error and looking through model-switch notices
("switch model, then retry" is the blessed recovery). Never a dropped or duplicated turn.

**T2.4 — `_display` sidecar + single outbound choke point** *(→ /ask transcript layer)*.
Model-facing content and user-facing metadata (guard-trip counts, receipt internals, provenance,
cost telemetry) on the same persisted record; ONE tested function produces the provider feed and
strips every sidecar. Adopt the anti-probing rule verbatim: guard-suppressed data must be
indistinguishable from absence in the model's view; the suppression count surfaces to the user
out-of-band.

**T2.5 — Declared parallel-safety on every tool/action**. "Parallel-safe" as a metadata property
(read probes: yes; K-plane actions: no) checked in one place; ADA sub-explorations' read-only-ness
enforced in the SQL/action gate, not instructions. (Aughor mostly has this via the SQL gate; the
gap is making it a uniform declared property as the action surface grows.)

### Tier 3 — the two bigger bets

**T3.1 — The connection knowledge graph** *(from Understand-Anything; deserves its own scoping doc,
Foundry-study style)*. The recipe transfers from codebases to databases nearly 1:1, and Aughor is
better positioned than UA on the two things UA fakes or stubs:
- *One typed, committed graph artifact per connection.* Nodes: `table`, `metric`, `glossary-term`,
  `domain`, `finding`, `brief`. Edges: `joins_on` (annotated with the join guard's observed
  value-domain overlap % — **real, auditable edge confidence** where UA hardcodes weights),
  `defines` (glossary→metric), `derived_from` (metric→columns), `grounded_in` (finding→tables/SQL),
  `resolves` (ambiguity-ledger entry→term). Deterministic layer = schema + dbt + profiler + guard
  evidence; LLM adds only summaries/tags/domain grouping. Stored beside the glossary:
  version-controlled, human-editable, override-wins.
- *Three-level anti-hairball rendering, copied verbatim*: domain cluster cards with aggregated
  join-edge counts → drill-in with containers (schemas, Louvain fallback over the join graph;
  FK graphs degenerate exactly like flat folder trees) with two-stage lazy layout → table detail
  (columns, profile stats, glossary links, *past findings touching it* — the dossier system makes
  that $0). Portals for cross-schema references. Persona filter: hide column/SQL-level nodes for an
  exec persona (one filter line).
- *A connection tour*: deterministic topology (fact tables = fan-in entry points; BFS = dimension
  reading order; coupled clusters = star schemas; metrics layer = capstone) narrated by the LLM.
  The 7-lens "interesting facts" TOUR (#154/#157) already generates the content — this turns a
  listicle into a curriculum.
- *Grep-the-graph-first answer protocol* — **the concrete fix for the open context-graph feedback
  loop**: before planning any /ask or investigation, match graph nodes for the question, pull the
  1-hop subgraph (which now includes past findings and ledger resolutions on those tables), inject
  as plan-time prior, and let the trust receipt cite which nodes grounded the plan. Context finally
  read back.
- *Freshness + token-proportional refresh*: schema fingerprint (tables/columns/types hash — the
  autoseed fingerprint work from #198 is adjacent) + UA's change-classifier decision matrix
  (cosmetic DDL → SKIP; column adds → PARTIAL re-profile; new schema → re-cluster domains); typed
  fresh/dirty/stale/unknown states surfaced in the UI and gating briefings.
- *Distribution*: the committed-artifact trick + an "Aughor skills pack" (markdown skills +
  `install.sh` symlinks, no MCP server) so an agent in a dbt repo can answer "what does
  `net_revenue` mean here and which tables feed it" from an exported context-pack JSON with Aughor
  not even running. Include the freshness-gate preamble in every skill — a trust receipt in prose.
- *Avoid their two big misses*: build the graph pipeline as a real program (LLM called for narrow
  emissions only), and wire graph search to Qdrant on day one — the "which tables handle churn?"
  query UA only promises should be the first thing Aughor's graph actually delivers.

**T3.2 — Reference-anchored binding-fidelity harness** *(from REFRACT; = Wave E4's methodology
customer → `aughor/evals/`, Wave-E library)*.
- `aughor evals fidelity --candidate <binding>`: run a fixed prompt set drawn from real
  investigation traces under the pinned reference binding and the candidate; score *agreement*
  with deterministic comparators Aughor already owns — normalized SQL equivalence via
  dry-run/EXPLAIN binding, grounded-number exact match, abstention agreement.
- *Floor verification as a gate, not a habit*: ref-vs-ref first; if the same binding disagrees with
  itself beyond threshold, the suite refuses to attribute deltas. Mechanizes "replicate before
  trusting deltas at small n." Add `repeatability` (run N, per-axis stdev).
- *Composite = harmonic mean* (one broken axis fails loudly) + a plain-English
  `interpret_pattern()` diagnosis + bands.
- *Perturbation-brittleness axis* (PLAD port for NL2SQL): typo/case/punct/conservative-synonym
  perturbations of the NL question; correct behavior is invariance and our comparator is
  deterministic (same result set / same bound SQL ⇒ zero drift) — cleaner than REFRACT's own
  token-edit distance. Score candidate excess drift over the reference's drift, subtracting
  inherent brittleness. Directly measures the "worked on the canned demo, broke when a real user
  typed" failure mode the guards exist to prevent.
- *Fixture-fingerprint guard*: stamp the fixture-DB fingerprint (#198's autoseed fingerprints)
  into every eval report; comparison tooling refuses to diff mismatched fingerprints.
- *Reference-floor sanity on prompts*: any axis where the *reference* scores below floor flags a
  broken test, not a broken candidate (their refusal-contaminated needle incident; our eval
  prompts touching security/PII phrasing are exposed to the same failure).
- *One-time proxy-inversion audit*: for each existing eval metric (token overlap, judge scores…),
  check historically whether improving it ever worsened end-task exact-match on grounded numbers;
  demote any axis that inverts. Cite the MSE-vs-KL case study in the evals docs.
- Budget note: the harness costs requests; run it as a scheduled batch inside the free 1,000
  req/day capacity (or on the graduated OpenRouter threshold), never inline.

---

## 4. Anti-patterns — what NOT to adopt, with reasons

| Anti-pattern | Source | Why not |
|---|---|---|
| Adopting aisuite as a dependency | aisuite core | Zero resilience; `LLMError` string-flattening would sit between our failover chain and the quota metadata (`quotaId`, `insufficient_quota`) the chain must read; silently drops parallel tool calls on the Anthropic blocking path; its own authors bypassed it in production. Our layer is ahead on every axis we care about. |
| Pipeline-as-prompt orchestration | Understand-Anything | 858-line SKILL.md the host model must obey; docs full of silent-data-loss scars. Aughor's graph builder must be a real program calling the LLM for narrow emissions. |
| Hand-written connector monolith | openworker `integration_tools.py` (4.9k lines) | Copy-pasted closures + schemas resist contribution and audit. The K-plane declaration registry is already the stronger shape — keep it that way as connectors grow. |
| Prefix-match command allowlists | openworker `permissions.py:205` | `git status ; rm -rf ~` passes an allowlisted `git status`. Parse, don't prefix; dry-run/EXPLAIN binding is our stronger equivalent. If the kinetic plane ever grows shell-adjacent actions: full parse. |
| Read-by-default risk fallback | openworker `risk.py` | One missing annotation silently makes a write auto-run. Aughor's rule must be fail-closed: undeclared action ⇒ blocked, not read-classed. |
| Naming-convention provider discovery | aisuite `ProviderFactory` | Makes "registered-but-not-wired" *easier*, not harder. Our explicit registry + bindings is stronger. |
| Convention-free LLM edge inference | Understand-Anything | Edges emitted "when confident" with fixed weights cosplaying as confidence and no line evidence. Aughor edges must carry provenance (guard evidence, dbt refs, profiler stats) or not exist. |
| KV-quantization math, hw-replay module, GBNF grammars | turboquant, atomic-agent | No local-inference hot path in Aughor; GBNF requires llama.cpp. The transferable parts are the methodology (REFRACT) and the repair/gating layers (atomic-agent), not the kernels/grammars. |
| Hook-injected "You MUST, don't ask" auto-updates | Understand-Anything | Self-authorized prompt injection into user sessions. Aughor surfaces staleness and lets the user act (typed staleness states + banner: yes; coercive injection: no). |

---

## 5. Sequencing against the wave roadmap

- **Tier 1 (T1.1–T1.3)** is a natural next arc in its own right: small, deterministic,
  test-friendly, zero product risk, and it de-risks *every* future model-heavy wave by making
  free-tier calls cheaper and more reliable. T1.2's matrix + health checks also close three
  already-paid-for bug classes structurally.
- **Tier 2 (T2.1–T2.5)** is Wave-K hardening — Wave K shipped the declared-actions skeleton
  (#201); openworker is a working reference for the grant, inbox, and interrupt planes that make
  governed actions safe *unattended*. Fits whenever K-plane follow-ons are picked up; T2.3
  (no-orphan streamed /ask) is independently valuable and could ride with Tier 1.
- **T3.2 (fidelity harness)** belongs inside **Wave E4** — E4 finally has both a concrete customer
  (the 5 unproven flag deltas from the graduation audit) and now a proven methodology (floor check,
  repeatability, harmonic composite, perturbation axis).
- **T3.1 (connection knowledge graph)** is the one genuine product bet and the largest surface. It
  plausibly *is* a wave: it unifies the glossary, ledger, dossiers, TOUR, and Qdrant index behind
  one read-back artifact, closes the context-graph loop, and carries the distribution mechanic
  (committed artifact + skills pack) that UA proved converts single users into teams. Recommended:
  a scoping doc first, Foundry-study style, before any code.

**Where this leaves the strategy.** The Foundry study concluded Aughor's edge is the trust plane
and the path is the kinetic half. This study adds two refinements: (1) the trust plane should
extend *into the LLM transport itself* — request-level reliability, provider-plane guards, and
binding-fidelity evals are guard-battery work, same philosophy, new plane; (2) the context plane
needs its read-back artifact — the difference between Aughor's captured-but-unread context and UA's
75k-star loop is not intelligence, it's one committed, versioned, deterministically-refreshed
artifact that every question passes through first.
