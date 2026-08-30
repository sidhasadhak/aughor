# Aughor — Roadmap and Plan of Record

**Product:** Aughor — Autonomous Intelligence Platform ("your warehouse, always thinking")
**Stack:** LangGraph · FastAPI (SSE) · Next.js (App Router) · DuckDB + PostgreSQL · SQLGlot ·
Qdrant · instructor over 5 LLM backends · uv

**Consolidated 2026-08-30.** This is the single roadmap. It replaces both the stale build-status
file that used to live here (last reconciled 2026-06-24, pointing at a plan two months old) and
the eleven per-arc roadmaps and adoption studies under `docs/`. §9 lists what was absorbed.

The per-feature record stays in [`FEATURES.md`](FEATURES.md); this file stays at the
at-a-glance altitude.

**How to read this.** §1–2 are state — measured, not recalled. §3 is the only *active* arc.
§4 is what has been decided AGAINST, with the evidence, because re-litigating those has cost
this project more than building. §6 is the short list of things only the user can decide.

> **63 documents under `docs/` were deliberately KEPT.** They are cited from module docstrings,
> tests, `FEATURES.md` or `AGENTS.md` as design rationale — `docs/GLOSSARY.md` is enforced by
> `tests/unit/test_vocabulary_ratchet.py` and named in its failure message; `docs/PITFALLS.md`
> has its own contract test; `docs/MCP_SERVER.md` is operator documentation for a shipped
> surface. Those are **reference material, not plans**, and folding them in here would break 63
> citations across the codebase. Only plans, roadmaps, adoption studies, wave arcs and
> superseded handoffs were absorbed.

---

## 0 · Thesis — one platform, three planes

Aughor's shape is validated externally: Databricks is assembling the same stack (Unity Catalog
+ Ontos business semantics + Lakebase Postgres + Electric sync + a first-class SQL editor).
Aughor has all five in miniature — **plus the piece they lack: an agent that answers with the
semantics, not just governs them.** The moat is the ontology→agent loop.

1. **The human plane** — a pro surface where a person does data work directly. Human SQL and
   agent SQL are peers in one provenance system: same `/query/run`, same guards, same receipts,
   same audit.
2. **The agent plane** — a conversation that feels like a frontier model, because it is one:
   general, multi-turn, platform-wide, with the guard battery *underneath* it rather than in
   front of it.
3. **The substrate** — serverless-correct, honest-signalled, measured-not-inferred.

**The rule that generalises across all three:** a capability is not shipped when it is tested,
it is shipped when something *consumes* it. Repeatedly, the gap has been a complete and inert
plane — see §7.

---

## 1 · What is true today (measured 2026-08-30)

| Plane | State |
|---|---|
| Query workbench | SE-0…SE-5a complete |
| Conversational intelligence (Arc CI) | complete — `#335` roster, chat SDK data model, chat-first home |
| Answer path | one door (`/ask`), converse ON, grounded-answer guard, Trust Receipt |
| Agent plane (Arc VA) | VA-0…VA-9c, VA-4a…4e shipped; VA-9d, VA-10, VA-11 open |
| Governance | `govern/` — actions · caps · guardrails · lineage · outbound · disclosure · tags; `security/` — audit · authz · credentials · pii; graduated approval gate → `approval_required` (428) |
| Reach (Arc RC) | Slack door live: @mention → answer, streamed, threaded, filed as a conversation |
| Automations | trigger → ordered effects, `{"$from": …}` dataflow, runs visible in Activity as traces |
| Observability | OTLP spans, waterfall + flow canvas, per-node usage, cost with explicit `unpriced` |
| Connections | 7 live; BigQuery/theLook mirrored daily 07:00 |

**Honest limits, same date:** automations cannot branch, fan out, or parallelise (§3.2); no
user-scoped credential store anywhere; warehouse connections have **no owner**; `telemetry.py`'s
Langfuse backend is silently dead (v2 path, 4.x runtime); no RBAC on `/agents/custom*`.

---

## 2 · Shipped

**Arc CI · conversational intelligence** — platform tool roster (#335), AI SDK UIMessage/parts
in `web/`, chat-first home, tiered write-scope (personal artifacts direct, org-shared semantic
state proposal-only).

**SQL editor (SE-0…SE-5a)** — the human plane, peer to the agent's.

**Program AT · answer truthfulness** — guards key on claims and verdicts, never on vocabulary.

**Arc CA · conversational analyst** — CA-1.

**Track FL · flow** (#403–#409) — plan bar, in-flight findings prose, provider-hop narration,
landscape report. *FL-3 measured and closed: `web/` has no markdown renderer — chat prose is a
regex split, so backend markdown is inert. FL-4 parked: 0/21 turn gaps under 10s.*

**Track RC · reach** (#410) — the Slack bot factory: bot records with vaulted credentials,
manifest render, N-socket supervisor, `Effect(slack_post)`, identity attribution
(`provider:external_id` + `identity_links`), proposal-inbox expiry, charts as Vega SSR PNGs,
GFM/CSV tables, deep links.

**Arc VA · the agent platform** — skills plane (VA-1), delegation (VA-2), OTLP (VA-3),
automations dataflow + run canvas (VA-4a…4e), trace excellence (VA-5), agent alerting (VA-6),
instruction/prompt management (VA-7), guardrail plane (VA-8), outbound seam (VA-9a),
automations-run-as-agents (VA-9b), per-agent tool grants (VA-9c).

**VA-12/13/14 (2026-08-30)** — canvas authoring (Add Trigger / Add Action), the
`investigate → slack_post` chain with wait-when-consumed, and the Slack app manifest generated
inside Create Agent.

**W1 · `when` on an effect (2026-08-30)** — a step runs ONLY IF its guard holds against what
earlier steps published. Structural clauses (`{"left": {"$from": "s1.answer"}, "op": "truthy"}`),
never an expression string, for this plane's three standing reasons: validated at save, not an
injection surface, and it draws. Authored as **"Only if"** on every surface — the trigger node
already owns the word "When". Two properties beyond the obvious: a step consumed only by a
downstream *guard* is still **awaited** (or `investigate` would hand it the job id it returns
when nobody waits — a non-empty string, so `is set` would hold every morning), and a run whose
every step was guarded off no longer fires the **fallback**, because "nothing was meant to run"
is not "everything failed".

---

## 3 · ACTIVE — Arc VA, remaining

### 3.1 · VA-9d — the MCP consumer

`aughor/mcp/` today is a **server** exposing Aughor's tools, plus an HTTP client to Aughor's own
API. A generic consumer — stdio + SSE, registry, discovery, health — does not exist.

VA-9's own risk note calls this *"the largest new attack surface in the arc"*. **Agree the
allowlist and the outbound-off-by-default posture with the user before starting.**

**Promoted in importance 2026-08-30:** the Langflow study (§4.2) found that the connector
platforms which solve the OAuth problem — Arcade, Composio — expose their tools **over MCP**.
VA-9d is therefore no longer an abstract capability; it is the delivery mechanism for the
most-wanted feature on this list.

### 3.2 · W1/W2 — the two workflow primitives

Measured: our engine runs a strictly sequential list. It cannot branch between effects, fan out
over a list, or parallelise. The user named this gap directly; it is real.

- ~~**W1 · `when` on an effect**~~ — **SHIPPED 2026-08-30.** A guard over the accumulated
  `context`, evaluated BEFORE the dispatch so a held step costs nothing. Its references run
  through the one `effect_refs` that validation, the engine's await and both canvases already
  read, so a guard cannot become a fourth, invisible dataflow. Operators are FETCHED from
  `/automations/vocabulary`; the subject is a picker over what upstream steps publish, never
  free text (B1's law, one field over).
- **W2 · `for_each` on an effect** — bind a step to an upstream list and run it per item,
  appending one `EffectOutcome` each. `resolve()` already walks lists.
- **W3 · parallel-safe steps** — lowest priority; nothing measured is latency-bound.

Neither needs a new canvas: VA-12's authoring rail edits whatever the model can express.

### 3.3 · B1/B2 — borrowed from Langflow

- **B1 · Typed bindings.** `validate_chain` catches an unknown *step* at save but **not an
  unknown key** — that surfaces at 09:00 as a skipped step. VA-13 shipped the binding as free
  text. A picker over "what each upstream step publishes" closes it. **Weakest seam in VA-12/13.**
  *Design direction (user, 2026-08-30, from the Langflow canvas):* render bindings as **visible
  inward/outward ports** on the nodes — coloured dots, output right, input left — with nodes
  free to drag and fields editable on the node. That look is `@xyflow/react` (the library the
  four existing canvases already use) with styled handles instead of our `opacity: 0` ones and
  `nodesDraggable` on: design investment, not new technology. B1's picker and the visible port
  are the same feature — the port IS the typed binding, drawn. Reference for the
  redesign (user-supplied): https://docs.langflow.org/concepts-components — their component
  anatomy (header/inputs/outputs, port types, tool-mode toggle) is the vocabulary to beat.
- **B2 · Dry-run.** We can inspect a run afterwards but cannot *try* a design before arming it.
  `evals/equivalence.py` already runs automations `persist=False` with an inert dispatch.

### 3.4 · VA-11 — the credential becomes a governed object (SPECCED 2026-08-30)

**Decision behind it (§6.1, user-approved 2026-08-30): Aughor owns the vault.** The Databricks
precedent settled it — a Unity Catalog connection is a *securable object* ("Databricks stores
the credentials and handles OAuth flows and token refresh, so the agent never sees them"), and
our thesis is UC in miniature. Every vendor fails the local-AND-scale test: Nango self-hosted
needs ~9 CPU / ~19GB across 8 services, Arcade needs Kubernetes, Composio's vault is
cloud-only — while this platform must run on a laptop (`uvicorn` + DuckDB) and on
Vercel/Supabase with **identical code**.

**The scope correction that makes this a wave, not a quarter:** the "~40 adapters" are mostly
DATA — authorize URL, token URL, scopes, refresh quirks. Ship **three providers** (Google,
Slack, Microsoft) and the ask is covered; forty is a catalogue, not a milestone.

**Deliverables, in build order:**

1. **`Connection` — the governed object.** User-scoped, provider-typed, granted scopes,
   expiry, and a `revoke()` that reaches the provider. Generalised from the pattern
   `slackbots/models.py` already proves in production: `SECRET_FIELDS`, Fernet under
   `AUGHOR_SECRET_KEY`, `encrypt_secrets`/`decrypt_secrets`, masked on every read
   (`credentials.py`: a credential "is an access token that reading grants" — masked for every
   reader, not gated by role). It is what `govern.audit` attributes against.
   **Warehouse connections adopt it** — they have no owner at all today, the oldest open item
   in this arc.
2. **The broker — a module, not a service.** Authorize redirect, callback (`state` + PKCE),
   token exchange, refresh-before-expiry, revoke; plus the error paths that matter (consent
   denied, scope downgraded by the provider, refresh token revoked upstream).
   `http://localhost:8000/oauth/callback` is a redirect URI every major provider accepts, so
   local hosting needs nothing extra.
3. **Google first, end to end** — consent → token → refresh → revoke, proven live before any
   second provider. Then **Slack and Microsoft as data, not code.**
4. **The catalog surface** — categorised, searchable, one `Connect` per provider, with
   `+ Custom MCP` as its last entry (where VA-9d surfaces to a user).
5. **LATER, not now — `CredentialBackend` seam.** A large deployment that genuinely needs 900
   providers points the same `Connection` at a self-hosted vendor broker (Nango under
   `NANGO_ENCRYPTION_KEY`) and the governance plane never notices — what moves is the vault,
   never the record. Deliberately unbuilt until a second implementation is actually wired:
   seams built before their second implementation are usually wrong. (If that day comes,
   Nango's Elastic Licence is a question for a lawyer first.)

**The authorization rule, decided once:** our graduated approval gate is the POLICY authority;
any vendor's per-action authz is transport. Two gates that can disagree is strictly worse than
one.

**Receipt:** a user clicks Connect on Google, consents in Google's own dialog, and a governed
action runs under **their** grant — token never rendered, scopes shown back, and Revoke removes
access at the provider, not merely from our table.

**Risks, carried in rather than discovered:** (a) a new token store is a new hermeticity
boundary — its env name goes into `tests/conftest.py`'s allowlist **in the same commit** (this
repo has been bitten by exactly that); (b) `state` + PKCE must be right, not approximately
right; (c) Vercel preview deployments have per-commit URLs and OAuth providers pin redirect
URIs — the callback must live on the stable production origin, verified before build.

### 3.5 · VA-10 — multi-user & admin

Untouched. User analytics over `session_events`, per-user and per-org quotas, an admin view of
every user's agents/runs/connections, RBAC on the agent plane, and audit of admin access to
user traces. **Risk is policy, not code:** an admin reading a user's prompts is a real question.
Default to visible-metadata, gated-payloads.

---

## 4 · Decided AGAINST — do not re-propose without new facts

### 4.1 · A canvas for AGENT creation — REFUSED (2026-08-18)

An Aughor agent is **one record** — a scope and a stance — with no producer/consumer relation
between its parts, so there is no second node for an edge to terminate on. Evidence: OpenAI's
Agent Builder canvas shut down; **Flowise sunset** citing *"rigid workflow low code quickly hits
the limit"*; Sierra and Decagon explicitly rejected flowcharts; Copilot Studio keeps a **form**
for the agent and reserves its canvas for conversation flow. Licence was never the issue
(`@xyflow/react` is MIT and drives four canvases here).

**What changed, and what did not:** automations *do* have a producer/consumer relation now
(VA-4a's bindings), which is exactly why VA-4b/4c/12 built that canvas. The refusal was never
about canvases in general — it was about drawing edges a record does not have.

### 4.2 · Langflow — REFUSED as a framework (2026-08-30)

Studied on the user's question. Full study: git history, `LANGFLOW_STUDY_2026-08-30.md`.

- **Its OAuth story is Composio.** Langflow's own Google OAuth component was **deprecated in
  1.4.0**; docs route to the Composio bundle keyed by `COMPOSIO_API_KEY`, with *"service provider
  authentication managed through the Composio platform"*. "Adopt Langflow for Gmail/Slack" means
  "sign up for Composio" — a buy decision about a connector runtime, independent of canvases.
- **Its workflow ceiling is documented by its own vendor.** If-Else and Loop exist and are
  *"not compatible"* with each other, and branches cannot be merged — *"any merging component
  will wait for branches that has been stopped by the conditional router"*. That is the Flowise
  ceiling in §4.1, restated.
- **Its governance posture is the opposite of ours.** Its docs: *"These settings do not provide
  full user isolation"*; default CORS *"can be a security risk in production"*; tracing
  *"process-wide, not per user"*; no audit logging or approval gate documented.
- **Structural:** every Langflow component is an executable node. Our `Effect` **references
  something that already exists** — *"no fourth action concept and, critically, no second write
  path."* Importing their model puts a write path outside `govern/`.

**Borrowed instead:** B1, B2 (§3.3). **Bought instead:** the connector runtime (§3.4).

### 4.3 · Arc OA — Langfuse + n8n — RETIRED (2026-08-29)

Dropped at the user's direction: *"we are not going that way again."* The n8n rule stands:
arm's-length only, users run their own. **Keep known:** `telemetry.py`'s Langfuse backend is
silently dead — retiring the program did not repair it, so treat any Langfuse surface as
non-functional rather than as telemetry someone is reading.

### 4.4 · A TypeScript agent runtime — REFUSED

VoltAgent's runtime is TS. Aughor's is Python and holds the ontology, the guards and the
governance plane. Adopting the runtime would mean two answer paths. What was imported from that
study is the *feature inventory*, not the stack — Arc VA is the result.

---

## 5 · Sequencing

```
NOW
  B2  dry-run an automation       (small — reuses evals' inert dispatch)
  ✅ W1  SHIPPED 2026-08-30 — "Only if" on a step: guard clauses over the chain context,
        evaluated before the dispatch, drawn on both canvases, refused at save like any
        other reference; a guarded-off run no longer pages on-call
  ✅ B1  SHIPPED `16019b5a` — typed ports (server vocabulary, fetched), drag-to-bind,
        unknown KEYS refused at save; Runs layer retired into Activity → Phases

NEXT — §6.1 decided 2026-08-30: Aughor owns the vault
  VA-11  Connection object + broker + Google, then Slack/Microsoft as data (§3.4)
  VA-9d  MCP consumer             (independent again — the vault no longer routes through it;
                                   still where third-party tools get consumed, posture first)

THEN
  W2  `for_each`                  (fan-out; wanted by "post per region")
  VA-10  multi-user + admin       (hardening pass over everything above)

LATER   W3 parallel steps · B3 flow-as-MCP-tool
```

**House rules that bind every PR:** one PR at a time, squash, never push without authorisation ·
ratchet battery on your own diff in a clean worktree · seven frontend gates + `gen:api` on route
changes · `PYTHONPATH="$PWD"` in worktrees · one writer per `data/` · **prove each wave live in
the browser** · **measure the premise before building.**

---

## 6 · Open decisions — the user's, not the builder's

1. ✅ **DECIDED 2026-08-30 — no third-party custodian: Aughor owns the vault.**
   The question dissolved once the bundle was split: vendors sell (a) the OAuth dance +
   provider registry and (b) the vault, and only (a) is worth having from outside. Databricks
   refused to outsource (b) and made the credential a securable catalog object; every vendor
   fails the local-AND-scale test this platform lives by. Specced as §3.4. A vendor broker may
   later sit *behind* a `CredentialBackend` seam for very large deployments — opt-in, the
   record stays ours, and the Elastic Licence gets legal review first.
2. **Do the workflow primitives (W1/W2) come before VA-11?** They are independent: W1/W2 make
   what exists properly expressive; VA-11 makes it reach further.
3. **VA-10's privacy default** — may an admin read a user's prompts, or only their metadata?

---

## 7 · Standing lessons (earned, expensive, repeatedly re-learned)

- **Measure the premise before building.** Every wave in this arc moved its own scope at the
  pre-check. "Authoring is missing" (VA-12) and "we need a workflow builder" (§4.2) were both
  false as stated.
- **Check whether an existing view's SUBSTRATE is simply unfed before building a new view.**
  VA-4d bought the entire Runs surface with ~40 lines.
- **Features stall at TESTED, not at LEVERAGED.** A complete and inert plane is the recurring
  failure — the governed-action plane shipped complete and unreachable.
- **A guard goes blind when its matching key stops matching**, and blind reads as green.
- **The measurement lies more often than the code.** Screenshot before believing a probe.
- **A capability added to one connector class misses the others** (×3).
- **Prove it live.** Most defects in this project were found by driving the product, not by tests.

---

## 8 · Not in scope

A second application · a TS runtime · an n8n dependency · a low-code flow engine · a canvas for
anything without a producer/consumer relation · model ids hardcoded anywhere in `aughor/`.

---

## 9 · What this document absorbed

**48 files, consolidated 2026-08-30 and removed from `docs/`.** Every one is recoverable:
`git log --diff-filter=D --name-only -- docs/` finds the deleting commit, and
`git show <commit>^:docs/<file>` prints it back.

**Roadmaps and plans of record**
`AGENT_OPS_CONTROL_ROOM_2026-08-17` · `CHAT_FLOW_ROADMAP_2026-08-28` · `HOSTED_DEMO_SCOPE` · `INSTALL_ACCURACY_PLAN_2026-08-18` · `KNOWLEDGE_BASE_WAVE_2026-08-24` · `PLATFORM_ROADMAP_2026-08-12` · `PRIME_AGENT_ADOPTION_2026-08-08` · `REBUILD_ANOMALIES_AND_IMPROVEMENT_PLAN` · `ROADMAP_ARC_VA_2026-08-22` · `ROADMAP_CONVERSATIONAL_ANALYST_2026-08-19` · `ROADMAP_SLACK_BOT_FACTORY_2026-08-29` · `RUNTIME_API_BASE_SCOPE` · `SQL_EDITOR_DATABRICKS_PARITY_2026-08-12` · `SQL_EDITOR_IMPLEMENTATION_ROADMAP_2026-08-12` · `SQL_EDITOR_PARADIGM_PLAN_2026-08-12` · `UI_ELEVATION_2026-07-14` · `VOCABULARY_UNIFICATION_2026-08-01` · `WAVE5_CLOSURE_PLAN_2026-08-09` · `WAVE5_EXTRACTION_MAP_2026-08-09`

**Adoption studies — verdicts now live in §4**
`COGNEE_STUDY_2026-07-28` · `CONVERSATIONAL_AGENT_STUDY_2026-08-08` · `DATABRICKS_HAR_SQLX_AUTODOC_STUDY_2026-07-15` · `FIVE_REPO_STUDY_2026-07-23` · `LANGFLOW_STUDY_2026-08-30` · `MASTRA_STUDY_2026-07-29` · `SPICEAI_STUDY_AND_ADOPTION_PLAN_2026-07-11` · `VOLTAGENT_ADOPTION_STUDY_2026-08-22`

**Completed wave arcs**
`WAVE_CR_CONTROL_ROOM` · `WAVE_C_CONTEXT_GRAPH_ARC` · `WAVE_H_HIRED_AGENTS` · `WAVE_L_ACTIVATION_ARC` · `WAVE_O_ONTOLOGY_ARC` · `WAVE_S_SURFACE_ARC`

**Superseded handoffs, probes and one-off analyses**
`BRIEFING_DESIGN_HANDOFF` · `CONTEXT_ENCODING_ARCHITECTURE` · `EXPLORER_GROUNDED_GENERATION` · `EXPLORER_SYNTHESIS_AND_FRONTIER` · `FLAG_QUEUE_HANDOFF_2026-08-01` · `FLAG_VERDICT_SHEET_2026-08-01` · `INTERACTIVE_DATA_AGENT_VISION_2030` · `OVERVIEW_INTERESTING_FACTS_2026-07-14` · `PIPELINE_QUALITY_ASSESSMENT` · `REPORT_QUALITY_DEEP_DIVE_2026-08-19` · `SESSION_HANDOFF_2026-07-06` · `SESSION_HANDOFF_2026-08-11` · `SESSION_HANDOFF_2026-08-12` · `SPIDER2_PHASE0_FAIL_ANALYSIS_2026-07-06` · `SPIDER2_REATTEMPT_2026-06-28`

**Deliberately KEPT (63)** — cited from module docstrings, tests, `FEATURES.md` or `AGENTS.md`,
and therefore reference material rather than plans: `docs/GLOSSARY.md`, `docs/PITFALLS.md`,
`docs/PLATFORM_ARCHITECTURE.md`, `docs/KERNEL_ARCHITECTURE.md`, `docs/AGENTIC_ARCHITECTURE.md`,
`docs/UNIFIED_ANSWER_PATH.md`, `docs/MCP_SERVER.md`, `docs/DOMAIN_EXPERTISE_PACKS*.md`,
`docs/PALANTIR_FOUNDRY_STUDY_2026-07-22.md` and 54 others.
