# Aughor — Roadmap and Plan of Record

**Product:** Aughor — Autonomous Intelligence Platform ("your warehouse, always thinking")
**Stack:** LangGraph · FastAPI (SSE) · Next.js (App Router) · DuckDB + PostgreSQL · SQLGlot ·
Qdrant · instructor over 5 LLM backends · uv

**Consolidated 2026-08-30.** This is the single roadmap. It replaces both the stale build-status
file that used to live here (last reconciled 2026-06-24, pointing at a plan two months old) and
the eleven per-arc roadmaps and adoption studies under `docs/`. §9 lists what was absorbed.
**Arc DS added 2026-08-31** (§3.7) — the visual-editor re-study's full plan, absorbed here per
the one-roadmap rule; it supersedes the session documents it came from.

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

## 1 · What is true today (measured 2026-08-30; amended 2026-08-31 after Arc DS Phase 1)

| Plane | State |
|---|---|
| Query workbench | SE-0…SE-5a complete |
| Conversational intelligence (Arc CI) | complete — `#335` roster, chat SDK data model, chat-first home |
| Answer path | one door (`/ask`), converse ON, grounded-answer guard, Trust Receipt |
| Agent plane (Arc VA) | VA-0…VA-9b, VA-4a…4e shipped; VA-9c **partial** — the propose-only action tool is live but no grant can be stored (limits below); the agent Map (DS-5); VA-11 vault+broker+catalog shipped and **consumed 2026-09-01** (DS-11's first half: an `integration_call` step spends a grant through govern.outbound); VA-9d, VA-10 open |
| Governance | `govern/` — actions · caps · guardrails · lineage · outbound · disclosure · tags; `security/` — audit · authz · credentials · pii; graduated approval gate → `approval_required` (428) |
| Reach (Arc RC) | Slack door live: @mention → answer, streamed, threaded, filed as a conversation |
| Automations | trigger → effects with `{"$from": …}` dataflow, `when` guards, `for_each` fan-out, branch+join (`else_of` / `$from_any`, DS-6), parallel steps (`scheduling`, DS-7), dry run + run-to-here, typed-port Design canvas with a truth-telling palette, live runs streaming onto nodes, undo/redo · copy/paste · minimap · layout sidecar; runs visible in Activity as traces |
| Observability | OTLP spans, waterfall + flow canvas, per-node usage, cost with explicit `unpriced` |
| Connections | 7 live; BigQuery/theLook mirrored daily 07:00 |

**Honest limits, same date:** a fan-out has no
list to read from any effect kind but the declared
action's open outcome (§3.2); **`UserAgent.tool_grants` is a phantom** — consumed by
`action_tools.py` and named in `GOVERNING_FIELDS`, but not a column, never loaded by
`_row_to_agent`, absent from `_PATCHABLE`/`UserAgentCreate`/`UserAgentPatch`, so no agent can
hold a grant and `propose_action` is unreachable everywhere (persisting it = a migration +
six files); no user-scoped credential store anywhere; warehouse connections have **no
owner**; no RBAC on `/agents/custom*`. (`telemetry.py`'s Langfuse backend, dead here on
2026-08-30, has since been repaired to ride the OTel exporter — OA·LF-1.)

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
automations-run-as-agents (VA-9b), the propose-only action tool (VA-9c — **partial**: the
law "a grant is permission to PROPOSE, never to EXECUTE" and the `propose_action` tool are
live, but `tool_grants` is a phantom field — §1 honest limits — so no agent can yet hold a
grant; the tool correctly serves nothing rather than a tool that always refuses).

**VA-12/13/14 (2026-08-30)** — canvas authoring (Add Trigger / Add Action), the
`investigate → slack_post` chain with wait-when-consumed, and the Slack app manifest generated
inside Create Agent.

**B2 · dry run (2026-08-30)** — "try it before you arm it", on the draft in the editor.
A preview returns an `AutomationRun` and the graph beside it, so the Execution canvas
renders it unchanged; steps read "would run", a guard reads "checked when it runs", and
the banner says "preview — nothing was sent" alongside whatever would gate it today.

**W1 · `when` on an effect (2026-08-30)** — a step runs ONLY IF its guard holds against what
earlier steps published. Structural clauses (`{"left": {"$from": "s1.answer"}, "op": "truthy"}`),
never an expression string, for this plane's three standing reasons: validated at save, not an
injection surface, and it draws. Authored as **"Only if"** on every surface — the trigger node
already owns the word "When". Two properties beyond the obvious: a step consumed only by a
downstream *guard* is still **awaited** (or `investigate` would hand it the job id it returns
when nobody waits — a non-empty string, so `is set` would hold every morning), and a run whose
every step was guarded off no longer fires the **fallback**, because "nothing was meant to run"
is not "everything failed".

**Arc DS Phase 1 (2026-08-31, #416–#418)** — the editor-grade pass: the component palette
that tells THIS deployment's truth (DS-1) · run-to-here (DS-2) · live runs streaming onto
the canvas (DS-3) · undo/redo, copy/paste, minimap, persisted layout, the last
`window.prompt` dead (DS-4) · the agent Map (DS-5). Spec-deltas and receipts in §3.7
Phase 1; also fixed there and worth naming: `PUT /automations/{id}` was erasing
`agent_id`/`last_run_at`/`last_status` on every save.

---

## 3 · ACTIVE — Arc VA remaining, Arc DS, plus substrate

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

Measured 2026-08-30: our engine ran a strictly sequential list. It could not branch between
effects, fan out over a list, or parallelise. The user named this gap directly; it was real —
and as of 2026-08-31 every clause of it is closed: guards (W1), fan-out (W2), branch+join
(DS-6) and parallel steps (DS-7, absorbing this section's W3).

- ~~**W1 · `when` on an effect**~~ — **SHIPPED 2026-08-30.** A guard over the accumulated
  `context`, evaluated BEFORE the dispatch so a held step costs nothing. Its references run
  through the one `effect_refs` that validation, the engine's await and both canvases already
  read, so a guard cannot become a fourth, invisible dataflow. Operators are FETCHED from
  `/automations/vocabulary`; the subject is a picker over what upstream steps publish, never
  free text (B1's law, one field over).
- ~~**W2 · `for_each` on an effect**~~ — **SHIPPED 2026-08-30.** One step, N dispatches,
  one `EffectOutcome` each. 🔑 **The pre-check moved the scope again: NOTHING in this
  plane publishes a list** — `investigate` publishes two strings, `slack_post` two
  strings, `notify`/`brief`/`monitor`/`agent_alert` nothing at all, and only the
  declared-action kind has an OPEN outcome shape. So a source is a **literal list** or a
  binding onto that open kind, and fanning over a closed-set producer is refused at SAVE
  rather than found at 09:00 as "cannot iterate a str". ⚠️ **Amended 2026-09-01 by
  DS-11:** the measurement was true when taken and is not any more — an
  `integration_call` step publishes `items`, a real list, in a CLOSED set. The rule is now
  "a source is a literal list, a binding onto an open kind, or a binding onto a key the
  producer DECLARES to be a list", which is strictly better: fanning over that step's
  `count` is still refused, where an open set would have let it through. The item is one
  more entry in the
  same accumulated context (`item.value` / `item.<field>`), so `resolve` needed no change
  and the canvas draws the source as an ordinary edge. The guard runs **per item** — a
  fan-out whose guard were checked once would be all-or-nothing, and "post the regions
  that moved" is a filter. ⚠️ It broke a load-bearing assumption: `build_graph` read
  `outcomes[i]` because the engine appended exactly one outcome per effect, so every node
  after a fan-out would have shown another step's status — a picture that is *wrong*, not
  missing. Grouped by `fan_count` instead.
- ~~**W3 · parallel-safe steps**~~ — absorbed into Arc DS as **DS-7** and **SHIPPED
  2026-08-31** (§3.7 Phase 2).

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
- ~~**B2 · Dry-run.**~~ — **SHIPPED 2026-08-30.** `run_automation(dry_run=True)` returns an
  ordinary `AutomationRun`, so the existing run canvas draws a preview with no second way
  of showing a chain. ⚠️ **The plan's premise was half true**: `evals/equivalence.py`'s inert
  dispatcher publishes NOTHING, so every step after the first read "upstream data
  unavailable" — a working chain reported as broken. Four more side effects had to be
  suppressed, each measured off the engine: the delivery CLAIM (would have silenced the
  real run), the source BASELINE (runs regardless of `persist` — a preview would consume
  the change), the SPAN (VA-4d made the run id the trace id), and the stored run. Gates and
  conditions are reported rather than enforced, because "disabled" and "not due" are the two
  states a design lives in before it goes live. Guards are reported, never decided.

### 3.4 · VA-11 — the credential becomes a governed object (1·2·4 SHIPPED `dadc6f63`; CONSUMED 2026-09-01 by DS-11)

> **State, measured 2026-08-30 (after `dadc6f63`).** Deliverables 1, 2 and 4 are BUILT:
> `aughor/integrations/models.py` (the `Connection` object, Fernet under `AUGHOR_SECRET_KEY`,
> masked reads), `broker.py` (begin/complete with `state`+PKCE, refresh-before-expiry, revoke,
> audit), `providers.py` (Google · Slack · Microsoft as pure data), six routes and the
> Integrations panel in `OperationsWorkspace`. **Deliverable 3 — a live end-to-end Google grant
> — is not done, and more importantly the plane is INERT: nothing outside
> `aughor/routers/integrations.py` imports the module, and `broker.fresh_access_token()` has
> zero callers.** No effect kind, tool or connector runs under a user's grant. §7's recurring
> failure, verbatim. The remaining work is a CONSUMER, not more vault.
>
> **Closed 2026-09-01 by DS-11's first half** (§3.7 Phase 3). The premise above was
> re-measured before building and was still exactly true. An `integration_call` step now
> spends a grant through `govern.outbound`; `fresh_access_token` has one production caller,
> `integrations/call.py`, and that is deliberately the only one. Deliverable 3 — a live
> end-to-end GOOGLE grant — is still not done and needs a Google account's consent, which
> no test can stand in for; the network path either side of it is proven (a real call to
> `gmail.googleapis.com`, refused by Google for the token it was given).

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
   `http://localhost:8000/oauth/callback` is accepted by Google and Microsoft — **and not by
   Slack**, whose docs require HTTPS and list `http://` among the rejected examples
   (measured 2026-08-30, after a user hit Slack's own error page: *"redirect_uri did not
   match any configured URIs"*). Carried as `Provider.https_only` and warned about in the
   Set-up form. Local hosting therefore needs nothing extra **for two of the three shipped
   providers**; Slack needs the API reachable over HTTPS (a tunnel suffices — `_callback_uri`
   already honours the forwarded proto and host).
3. **Google first, end to end** — consent → token → refresh → revoke, proven live before any
   second provider. Then **Slack and Microsoft as data, not code.**
4. **The catalog surface** — categorised, searchable, one `Connect` per provider, with
   `+ Custom MCP` as its last entry (where VA-9d surfaces to a user).
   🔑 **Decided 2026-08-30, from a live install failure: a card must offer the door THIS
   deployment can open.** Slack's OAuth needs an HTTPS callback; a laptop has none; so a
   freshly-cloned Aughor was being pointed at the one door it cannot open — to reach a
   token **nothing consumed yet** (`broker.fresh_access_token()` had zero callers then;
   DS-11 gave it one on 2026-09-01, which does not change this card's argument — the door
   a deployment cannot open is still the wrong door to offer). Meanwhile RC-5's Slack app path — manifest + three tokens + Socket
   Mode, an *outbound* socket, no callback, no tunnel — works on a laptop today and is
   what `slack_post` actually uses. The catalog now computes `oauth_ready` from the same
   callback `connect` would send, and routes to `Provider.alt_door` when it is false.
   The user's framing, which is the general rule: *"someone who just installed from
   GitHub would not know how to start a tunnel."* **A provider gains an `alt_door`
   whenever one exists that needs no public callback.**
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

### 3.6 · S1 — Qdrant installs WITH the app, not beside it (raised by the user, 2026-08-30)

**Measured, not recalled.** `uv sync` / `pip install '.[semantic]'` installs the *client only*
— `pyproject.toml` concedes it in its own comment: `qdrant-client` "already needs a Qdrant
server (`AUGHOR_QDRANT_URL`, default localhost:6333)". The server comes from a **separate**
`docker compose up` (`docker-compose.yml`, `qdrant/qdrant:latest`, volume `qdrant_data`), and
that is exactly how it runs on the author's machine today (container `hermes-qdrant-1`, up 7
days). README says the same out loud: "there is no container image (the only Docker asset
composes Qdrant)". Without a server the `semantic` extra degrades — reads return no hits,
writes no-op.

**Half of this is already solved; do not rebuild it.** `vector_store.backend()` routes a
Postgres deployment to **pgvector** — the index rides inside the platform's one managed
database, no second service — so the hosted/Vercel shape needs no Qdrant at all. The gap is
only the **local** shape: with no Postgres `AUGHOR_DB_URL` and no pinned URL, `_client()`
hardcodes `url=http://localhost:6333`, and on a fresh clone nothing is listening there.

**Direction — make the laptop backend embedded.** `qdrant-client` 1.18.0, already the pinned
dependency, supports in-process on-disk local mode (`QdrantClient(path=…)`; verified — both
`path` and `location` are on `__init__`). A third branch in `backend()`/`_client()` defaults to
`data/qdrant/`: same API, no port, no daemon, no second install step. Three backends behind the
one seam — **embedded local · Qdrant server (pinned URL) · pgvector (Postgres)** — which is the
same local-AND-scale test §3.4 applied to the vault.

**The constraint that decides the design:** local mode takes an exclusive lock on its path —
one process, ever. This repo has corrupted `data/system.db` four times on exactly that rule, so
the API must be the single writer, the new env name goes into `tests/conftest.py`'s allowlist in
the SAME commit, and CLI/backfill paths talk to the API rather than open the directory
themselves. (Compose-the-app-too is the alternative, but it helps only Docker users and leaves
`uv run` — the documented path — needing a second service.)

**Receipt:** fresh clone → `uv sync` → `uvicorn aughor.api:app` → semantic search returns hits
with no second process running and no environment variable set.

---

### 3.7 · Arc DS — the Design arc (adopted 2026-08-31; decision §6.4)

> **Origin.** The user's 2026-08-31 directive — *"any & every agent that we spawn should be
> created via langflow style visual editor… fork it, clone it or whatever… go all in… think
> years ahead"* — re-opened §4.2 from scratch. The four-pass re-study (their docs 1.5→1.12 ·
> their source at v1.12.0 `da3d5050` · security/ownership · our own seams) **confirmed the
> refusal of Langflow's codebase and produced this arc instead: the grammar, not the
> codebase** — a Langflow-class editor, then a better one, on our engine and governance
> plane. Evidence summary lives in §4.2's addendum; the falsifiers in this section's tail.
> Named DS because the surface is already called **Design** ("Canvas" belongs to Data
> Canvas — a collision already paid for once).
>
> **The grab split, decided with the user:** their node **anatomy and styles — YES**,
> rebuilt in our own tsx on `@xyflow/react` (already under four canvases here); their
> component **contract shape — YES** (declared typed inputs, outputs, dynamic field
> visibility, a tool-mode-like flag → DS-10's schema); their **430 component
> implementations — NO** (in-process `exec()` by design; mostly LLM/vector plumbing our
> funnel already is, or Composio wrappers whose functionality lives on Composio's servers;
> the useful ~10 % becomes DS-13's shortlist). MIT covers their code and patterns; their
> name, logos and provider icons do not transfer.

**Laws that bind every DS wave (standing, not per-phase):**

- An agent remains **one record** (§4.1). The canvas authors what has producer/consumer
  structure — the chain an agent operates. DS-5 draws an agent's *system*, never its record.
- **Every node is a reference** to a governed capability. No node is code; no second write
  path; adding a palette entry is a backend act, never a paste.
- **One engine.** A foreign runtime bypasses the woven plane (token caps in the LLM funnel,
  PII at `security_post`, approval/audit/identity in the one executor, spans in the engine
  loop) — the REST API is the only complete choke point, so everything drawn executes here.
- **The palette tells the truth of THIS deployment** — §3.4's alt-door rule generalized:
  every entry is served as `ready | needs_setup | unavailable` with a reason and a door.
- **`lfx` (MIT) is reference text, never a dependency** — study its layered scheduler,
  dynamically-computed runnable frontier, subgraph-per-item loops and checkpoints for
  DS-6/7/8; never execute its flows (a Langflow flow JSON is `exec()`d Python by design).
- Prove each wave live · names from GLOSSARY.md · hues are tokens, never hexes (CSS-var
  KIND gate) · vocabulary/ports/availability are **served, never mirrored** — the
  hand-copied contract that rots is a paid-for trap.

**Phase 0 — down already** (#412–#415, plus VA-4d/4e): typed ports from server vocabulary
with drag-to-bind and drag-time refusals mirroring `validate_chain` (B1) · `when` guards
(W1) · `for_each` with per-item guards and refuse-not-truncate caps (W2) · whole-chain dry
run rendered on the run canvas (B2) · on-canvas authoring (VA-12) · run canvas with typed
node faces and a timeline rail (VA-4e) · run-id-as-trace-id (VA-4d). The arc names and
finishes a direction already chosen.

#### Phase 1 · Editor-grade — ✅ SHIPPED 2026-08-31 (#417 DS-1 · #418 DS-2…DS-5)

> **Shipped as specced, with these measured deltas (the spec text below is kept as
> written; where they disagree, this ledger is the truth):**
> - **DS-1** — P0 + served availability shipped. **Open: the P1 port-compatibility filter
>   and the P2 rail.** The port-type→hue map is DEFERRED to DS-10 — no port-type
>   vocabulary exists yet and only six `--chart-N` tokens do (`lint:palette` CVD-validates
>   additions); colour stays direction+kind keyed. No structured `door` field is served —
>   the reason sentence names the door until DS-11 gives it destinations (don't serve a
>   field nothing reads). ⚠️ **Still true after DS-11's first half (2026-09-01):** it added
>   a destination (Integrations, named in the new row's sentence and in every dimmed
>   integration component's) and still did NOT serve a structured field, because nothing
>   navigates by one yet. The clause is now waiting on a READER, not on a destination. A **failed availability probe leaves a row READY** — only a
>   measured zero dims; a dimmed row that would have worked is a lie the reader can't check.
> - **DS-2** — `until_alias` truncates the effect list before the loop; an unknown alias
>   walks the whole chain; steps past the cut are drawn, undecorated.
> - **DS-3** — zero new routes: `POST /automations/{id}/run` gained an optional `run_id`,
>   step attrs joined `span_attrs` (the only channel that reaches `session_events`), feed
>   = `/activity?trace_id=`. Live state renders **`ran`** — a span's `ok:true` is not step
>   success (the verdict lands after the span closes); the stream is anticipation,
>   `build_graph` is truth.
> - **DS-4** — layout persisted in an `automation_layouts` **sidecar table, not a column
>   on the automation**: the update route rewrites whole rows, and exactly that bug was
>   live in this route (the `PUT` erase, fixed in #418). One pure undo stack covers
>   draft+positions (coalesce <600 ms; rehydrate resets); paste **drops** a ref whose
>   producer is absent rather than repointing it (`validate_chain` cannot catch a ref that
>   resolves to a *different* step — a well-formed wrong result).
> - **DS-5** — shipped as the **Map** tab ("Design" is the automation button AND its
>   canvas mode; "Canvas" is Data Canvas). Zero server cost: two undeclared wire fields
>   (`SlackBotSummary.agent_id`, `Automation.agent_id`) + three client filters bought
>   every relation. It deliberately draws **no grants spoke** — `tool_grants` is a
>   phantom (§1 honest limits).

**DS-1 · The component palette** — the discovery surface, and the part the user singled
out. Specced from a source-level dissection of theirs (sidebar component tree, hooks and
constants read at v1.12.0) before this was written.

- **The contract comes first.** Extend `/automations/vocabulary` (or a sibling
  `/design/palette`) to serve, per item: category · name · description · icon name · port
  signature (`PUBLISHED_KEYS` / `BINDABLE_FIELDS` already exist server-side) · badges
  (`beta`, `legacy`) · a `priority` int (curated pinning) · and **availability:
  `ready | needs_setup | unavailable` + reason sentence + door** — `slack_post` with no bot
  record renders dimmed with "needs a Slack app" linking the Reach step; `kinetic_action`
  lists per action actually declared on a connection; a fan-out notes it needs a
  list-publishing upstream. Their palette shows the same 430 rows to every install and
  lets the canvas discover what won't run; **ours refuses to lie at the palette.**
- **P0 interactions:** fuzzy search — tight threshold (theirs: Fuse at 0.2 over
  name/description/type/category), debounced, matched categories auto-expand, `/` focuses
  and opens (shortcut configurable later), Esc blurs · collapsible categories from the
  served contract · row = 18px icon + truncating name under tooltip + badges +
  hover-revealed `+` + drag grip · **two add paths, one gate**: drag-to-place and
  click/double-click/Enter-to-append (append lands at viewport centre computed from
  pan/zoom) share one add gate, so the affordance and the refusal can never disagree ·
  disabled-with-reason rows · Beta shown / Legacy hidden by default, both persisted ·
  loading skeletons matching row geometry · badge text folded into the accessible name
  (WCAG 2.5.3 label-in-name) and the panel `inert` while hidden.
- **P1 — the killer interaction, the port-compatibility filter:** drop an edge on empty
  canvas → the palette opens filtered to steps that can bind that type, a banner names the
  active filter (with ×-to-clear), and choosing an entry lands the node **pre-bound to the
  dragged edge**. Cheap here: B1's drag-time refusals already know every port's type.
  Also P1: singleton/constraint reasons (one trigger node; one fan-out per step) and the
  three-key sort (priority → search score → name).
- **P2:** a slim segmented rail once there is more than one section — **Palette · Runs ·
  Versions**, library-above / this-chain-below, active re-click collapses, feature
  re-click returns to Palette, every section switch clears search. When VA-9d lands, adopt
  their MCP pattern wholesale: **each allowlisted server materialized as its own palette
  row**, with Add server / Manage servers in the section footer. Per-row context menu
  (export a step as JSON) last.
- **Deliberately not copied:** no code editor behind any row (DS-13's declarative form is
  the custom path) · no Bundles section (breadth arrives as governed connections + MCP) ·
  no Store · no per-row delete of built-ins · no drag-ghost theatrics until fundamentals
  are receipted · no category graveyard — categories are few and real (≈ Triggers · Steps ·
  Guards & flow · Connections · Tools) and Legacy is a display state kept empty by intent.
  (Their own sidebar wears 13 Legacy chips per 20 rows with the toggle on, above a
  constant carrying 16 retired category names — the metabolism of components-as-code;
  references must not rot that way.)
- **Color law:** one served map, port-type → hue **token**, used identically by the
  palette row, the node's port dots and the edge — colour means the same thing in all
  three places. Extends B1's kind-hued tiles; our type vocabulary (text · id · list ·
  channel · tabular · open/unknown) fits in eight hues.
- **Fit:** the palette owns discovery + placement; the Design rail owns configuration; the
  canvas owns wiring. On-canvas Add Trigger / Add Action stay, as shortcuts that open the
  palette pre-filtered.
- **Receipt:** `/` → "slack" → drag the row in wired-ready, or click `+` and it lands at
  centre; a fresh install with no bot shows the row dimmed with its door; drag from a
  step's answer port into space and the palette shows only what can consume text.

**DS-2 · Per-node run and run-to-here.** Scoped dry run: execute the chain up to a selected
node against sample input, inert, results rendered on the traversed nodes, downstream
quiet. Same five suppressions B2 measured (no dispatch, no delivery claim, no baseline
commit, no span, no stored run), with a frontier cut; gates and conditions reported,
guards reported never decided. The affordance that makes iterating on step 4 not cost
steps 1–3. **Receipt:** "run to here" mid-chain shows would-run results above, quiet below.

**DS-3 · Live runs stream onto the canvas.** The Execution view subscribes to a run's
events as they happen instead of decorating a stored run afterwards. Substrate exists —
the run id IS the trace id (VA-4d) and every step/iteration emits into `session_events` —
so this is a feed (SSE, like the ask stream), not a new plane. **Receipt:** run-now; nodes
light, stream and settle in order with no refresh.

**DS-4 · Canvas ergonomics.** Undo/redo · copy/paste · minimap · persisted layout (a
DECISION, not a drift — today's positions are deliberately session-local; persisting means
a layout column on the automation, never localStorage) · and the death of the last
`window.prompt`: the open-outcome binding key (declared-action outcomes are an open set,
accepted unchecked by design) gets a typed picker with an "accepts any key" affordance —
closing B1's residual free-text seam. **Receipt:** arrange, reload, find it where you left
it; bind to a declared action's outcome without typing a key blind.

**DS-5 · The agent map.** Every agent gets a Design view of its operational world: the
agent at centre; its doors (chat, Slack bots, MCP); its automations; its tool grants and
connections — real producer/consumer relations drawn from data that all exists today.
This honours "every agent is visual" WITHOUT re-litigating §4.1: the record stays a form;
the agent's *system* is a graph. Read-first; every node clicks through to its surface.
**Receipt:** open any agent → Design; see every door and chain it operates.

#### Phase 2 · Past their ceiling (their documented, seven-release-old limit becomes our demo)

**DS-6 · Branch and join — ✅ SHIPPED 2026-08-31.** Route between steps on a guard's verdict AND merge the branches
back — **a join waits only on taken branches**, tractable because awaits already derive
from the one `effect_refs` that validation, the engine's await and both canvases read (a
route cannot become a fourth, invisible dataflow). Structural clauses only, W1's law:
validated at save, not an injection surface, and it draws. For contrast, their engine
implements the *anti*-pattern — persistent branch-exclusion that walks downstream and
stops everything the router didn't take, which is exactly why their branches cannot
rejoin. **Receipt:** revenue fell → #alerts, else #daily, and ONE summary step runs after
either.

> **Shipped as:** `Effect.else_of` (surface word **Otherwise**: the arm runs exactly when
> the named step's Only-if was evaluated and did NOT hold) + the `{"$from_any": [...]}`
> join binding (first alternative that resolves, in authored order — each validated,
> awaited and drawn like any reference). The laws that took deciding: **an undecided
> guard takes NEITHER arm** (unevaluable/missing-upstream is not falsehood — the guard
> went three-valued, `evaluate_guard_verdict`, to say so); **the route reads the
> verdict, never the arm's health** (a failed primary does not run the otherwise — a
> route is not a fallback); an untaken arm is `BRANCH_SKIP`, so it cannot fire the
> fallback; `else_of` must name an earlier, guarded, unfanned step (a per-item guard is
> N verdicts); elif chains fall out free (`else_of` onto an else-arm). Guards now
> evaluate BEFORE the params resolve — cheaper, and the decision belongs to the guard.
> Canvas: a third edge kind `route` (labelled "otherwise"), the arm's own strip + rail
> picker, join chips reading "alerts.ts or daily.ts", one drawn edge per candidate;
> dragging the *other arm* onto a bound field JOINS instead of replacing. Two defects
> found by driving: the list summary rendered a join as `[object Object]` (the B1 hole,
> one form over — both now route through `bindingRefs`), and a bound non-primary field
> (`thread_ts`) never mounted its port, so ReactFlow silently dropped the join's edges
> (`visibleFields`: a binding is wiring, and wiring must draw). Live-receipted on a
> scratch instance: both branch directions, preview walking both arms ("otherwise of
> alerts — decided when it runs"), and the execution canvas reading dispatch_error red /
> **not taken** amber / skipped dim.

**DS-7 · W3 — parallel steps — ✅ SHIPPED 2026-08-31** (absorbs §3.2's W3). Steps with no data dependency execute
concurrently via frontier scheduling — the lfx shape (topological layers, a dynamically
recomputed runnable frontier) adapted to our outcome model; DS-6's dependency analysis
does most of the homework. One outcome per dispatch; spans intact under the run trace.
**Receipt:** two independent investigations overlap in the span waterfall.

> **Shipped as:** `Automation.scheduling: "ordered" | "parallel"` — **per-automation and
> opt-in**, because the declared list is a documented contract ("Then, in order" on every
> surface) and two steps with no data edge can still be order-sensitive in the world (two
> posts into one channel arrive in list order); only the author knows. A step's
> dependency set = every reference in its params, guard and fan source, plus its
> `else_of` target — the one `effect_refs` again, so "may these overlap" and "is an edge
> drawn between them" cannot disagree, and forward-ref refusal makes the graph a DAG by
> construction. The engine's per-step body was EXTRACTED once (`_execute_step`) and
> driven by both the ordered walk (byte-for-byte, the whole pre-DS-7 suite is that
> assertion) and the frontier (`ContextThreadPoolExecutor`, the kernel's contextvar-
> copying pool, ≤ `MAX_PARALLEL_STEPS`=4; per-step retry budgets since parallel sleeps
> overlap; outcomes reassembled in DECLARED order because `group_outcomes` matches
> positions). A dry run always walks in order — parallelism over an inert dispatcher
> buys only nondeterministic sample ordering. The graph prunes the sequence spine to
> trigger→roots under parallel (a chain spine would lie) and serves `scheduling` so both
> canvases and the trigger card say "steps run in parallel — as the arrows allow".
> Store migration 3 (rehearsed at boot on a v2 scratch store); the authoring form gained
> the select AND the carry-forward fix — its payload was silently resetting
> `description`/`enabled`/`paused_until`/`expires_at`/`retry_backoff_seconds`/
> `fallback_effect` on every form edit (4th of the PUT-erase family; canary-proven fixed
> live). **Live receipts on a scratch instance:** the same two-notify automation ran
> 2.7s parallel (both steps opening the same millisecond) vs 5.1s ordered; worker-thread
> spans landed under the run's trace with the waterfall's own header reading "this run
> did work in parallel"; the DS-6 branch+join chain kept its laws under the frontier
> (the otherwise arm waited for the verdict). Left open, chip-filed: the VA-5 waterfall
> draws single `external_call` completion events forward from their timestamp, and both
> editors read-modify-write from a stale list snapshot.

**DS-8 · Durable pause — approvals mid-chain.** A run that reaches an approval-gated
action parks durably, surfaces in the A4/RC-3 proposal inbox (resolve-once, expiry
applying, fail-closed), and resumes from its checkpoint on accept — prior steps never
re-run (checkpoint = the persisted run + accumulated context). Their HITL is authored
per-flow; ours rides the governance plane that already exists (verdicts, audit, identity,
expiry). **Receipt:** a chain proposing a governed write pauses; accepting in the inbox
resumes it; the trace shows one run with a human in its middle.

> **Shipped 2026-09-01.** `AutomationRun` gained `paused` — its first NON-TERMINAL outcome —
> and a `checkpoint` (store migration 4, numbered off the live store's `user_version=3`)
> carrying exactly what dies with a tick: the accumulated context, the guard verdicts, the
> frontier's completed set, and per-step outcome counts so the flat `effects` list can be
> re-attributed to steps on the way back. Both drivers park (the frontier stops scheduling and
> lets what is in flight land); the resume seeds the SAME chain-walk body rather than adding a
> second walker. A resume is not gated and does not re-evaluate conditions — a human who
> approved a write is owed the rest of the chain, and a re-probe could answer differently and
> abandon it half-executed. Accept, reject and expiry all end the wait; a refusal makes its
> step `skipped`, and dependents skip through the unresolved-binding path that already existed.
> **The layering forced the shape:** `aughor/actions/*` may not import `aughor/automations/*`
> and `runners/*` may import neither, so the resume is called from the ROUTER (where the
> automation→proposal purge cascade already lives) and swept every heartbeat by
> `resume_parked_runs`, which makes resuming a property of the system rather than of whichever
> surface was pressed. **Live receipt on the fixture connection:** a two-step chain parked with
> `finished_at: None` and step 2 never dispatched; one row in NEEDS YOU carried Accept;
> accepting IN THE UI resumed the same run id to `fired` with both steps executed and step 2
> bound to step 1's approved output. **Two defects the live run found and the green suite had
> agreed with:** a dispatcher names `target` after what it dispatched — the ACTION ID for a
> governed write, not the step alias — so the resumed context was published where no binding
> could reach it (the fixture set `target=alias`, hiding it from both sides); and `needs-human`
> listed one approval twice, once as a pending proposal and once as a parked run, with Accept
> on only one of the two cards. **Left open, chip-filed:** `AUGHOR_ACTION_APPROVAL` is unset by
> default, so `guard()` returns immediately and the pause is unreachable on a default
> deployment — the whole graduated-approval plane is complete and inert until that flips.

**DS-9 · Subchains.** An automation invokes an automation as a step; cycles refused at
save; child outcomes fold into the parent trace. Composition keeps the palette small while
the library grows. **Receipt:** two chains share one "post with fallback" subchain.

> **Shipped 2026-09-01.** A `subchain` effect kind whose child runs as if someone pressed
> Run now — its own conditions are NOT re-asked (a shared chain triggered "every Monday"
> that answers "not due" to every caller on every other day is not shared), while its
> lifecycle gates still apply (`enabled=False` is a person saying this must not run, and
> being called is not an exemption). The child keeps its own run row — a shared chain's
> history is the one place every caller that used it is visible — but writes its steps under
> the PARENT's trace, so a nested chain reads as one waterfall. That inheritance rides a
> ContextVar rather than a parameter, because `Dispatch` is `(effect, automation)` and six
> dispatchers would otherwise grow three arguments five of them ignore; DS-7's
> `ContextThreadPoolExecutor` copies it into workers, so a subchain inside a parallel step
> inherits exactly what a sequential one does. Cycles are refused at SAVE, on the store (the
> one write path — the question needs the rest of the library, so it cannot live on the
> model), breadth-first with a `seen` set so a DIAMOND is not mistaken for a loop: two steps
> sharing one subchain is the entire point of the wave. The refusal reaches the author as a
> 422, not a 500. A depth cap guards the shape a cycle check cannot see — a legal tree built
> one honest edge at a time. **DS-8 met DS-9:** a child that parks on an approval parks its
> PARENT, whose checkpoint records the child run rather than a proposal; resuming the child
> wakes the parent, and the heartbeat's sweep now takes passes so a whole nested tower comes
> unstuck on the tick that unblocked its leaf. **The defect that interaction hid:** the
> parent's subchain step reports `approval_required`, so DS-8's staging fired for it too and
> put a phantom proposal — for a step with no action to approve — on the parent's run, which
> then blocked its own resume forever, because `resume_run` refuses to continue a run with a
> pending proposal. A relayed wait now stages nothing. **Live receipt:** two chains sharing
> one subchain, both fired, the shared chain's own history showing both callers.

#### Phase 3 · The component economy (its first two waves ARE §3.4's consumer and §3.1's VA-9d)

**DS-10 · One component registry.** Unify what already exists into a single typed roster
the palette reads: 7 effect kinds · 17 connector types · 18 MCP-served tools · 12 platform
tools · declared kinetic actions — each with ports, badges, priority and availability,
served like `/automations/vocabulary`. Schema borrows their contract shape (declared typed
inputs; outputs; dynamic field visibility; an "exposable as tool" flag that DS-14 reads)
with the law kept: **a component references a governed capability.** Beta/Legacy live as
registry metadata — display states, empty by intent. **Receipt:** the palette lists every
capability of this deployment, searchably, and nothing that isn't real.

> **Shipped 2026-09-01.** `aughor/components/` adapts five existing rosters at read time and
> copies none of them: a registry holding its own table of effect kinds would be a second
> place to add the seventh, and the seventh would reach exactly one of them. Served at
> `/components` (with `conn_id`, `family`, `q`) and — the part that makes it one roster
> rather than a sixth — `/automations/palette` is now served FROM it, losslessly, so "does
> this kind exist" and "does it work here" have one answer instead of two that happen to
> agree. **The law is checkable:** every row names in `governed_by` the MODULE that governs
> its use (the approval gate for a declared write, the one engine for an automation step,
> the connection registry for a connector), and a ratchet imports every distinct value — a
> taxonomy nobody can check is how a roster starts describing a system that no longer
> exists. Badges are the closed set `beta | legacy` with no members, which is what "empty by
> intent" has to mean to be worth anything: metadata every surface reads, not a word one
> renderer hard-codes later. **The premise was measured first, and the plan was wrong about
> it:** connectors 17 ✓, platform tools 12 ✓, MCP tools 18 ✓, but "7 effect kinds" is now 8
> (6 of them offerable — `monitor` and `agent_alert` are adopted, never authored), because
> DS-9 moved that number three hours before this wave read it. **And a real capability was
> missing from every surface:** the connector family is built from the full type set, not
> `REGISTRY.supported_types()`, because the two KNOWLEDGE connectors (Notion, Confluence)
> are configured, authenticated and synced by a live route while having no
> `open_connection()` — so the builder list omits them, and `/connectors/types`, which is
> built off that list, has never offered them. The registry reports all 17; closing the
> picker gap is filed separately, because what it changes is a creation FORM, not a roster.
> **Live receipt:** 59 components on the fixture connection across all six families —
> including its two authored declared actions — with four rows dimmed and each saying why;
> the same question on another connection answers 57 with none of those actions and a
> different dimmed set; `q=notion` finds the connector nothing else lists; an unknown family
> is a 422 naming the closed set; and the palette agrees with the registry field for field
> on both connections. **Left open, chip-filed:** the non-placeable families are served but
> not yet palette ROWS — that is DS-11's own sentence ("an allowlisted MCP server's tools
> land on the palette as governed nodes"), and drawing them as steps before they can be
> placed would teach a reader that a connector is a step. ⚠️ **Half-closed 2026-09-01:**
> DS-11's first half added a SEVENTH family, `integration`, whose rows are placeable —
> each is an operation an `integration_call` step runs — so the registry's first
> person-shaped family arrived already placeable rather than as a row a reader cannot use.
> `mcp_tool`, `connector` and `platform_tool` are still served and still not placeable,
> and the MCP half of DS-11 is what changes that for the first of them.

**DS-11 · The VA-11 consumer and VA-9d, surfaced as components.** A vault `Connection`
becomes a node ("as Google · sales@…") whose effects run under the user's grant through
`govern.outbound` (cap before the work, span, `EXTERNAL_CALL` event) — the wave that makes
§3.4's built-and-inert plane consumed. An allowlisted MCP server's tools land on the
palette as governed nodes (posture per §3.1: allowlist + outbound-off-by-default, agreed
with the user first). This is how the 400-component envy resolves: Composio/Arcade's
catalog — the same one Langflow outsources to — arrives as governed rows under OUR
approval gate and OUR vault. **Receipt:** a chain reads Gmail under the user's own grant
and posts to Slack, every hop attributed, capped and audited.

> **First half SHIPPED 2026-09-01 — the VA-11 consumer. The VA-9d half is NOT started**
> (§3.1 requires the allowlist and outbound-off-by-default posture be agreed with the user
> before a line of it exists; that conversation has not happened).
>
> **The premise, measured before building and exactly as §3.4 stated it:**
> `broker.fresh_access_token()` had **zero** callers outside its own tests, and nothing
> outside `routers/integrations.py` imported `aughor.integrations` at all. The vault
> minted, refreshed, revoked and audited tokens that no capability could spend. Two new
> modules end that: `integrations/operations.py` — what a grant may DO, as DATA in
> `providers.py`'s shape — and `integrations/call.py`, the ONE door, so refresh policy,
> the scope check, the approval gate, the outbound cap and the audit line cannot be
> remembered by one caller and forgotten by the next.
>
> **The closed URL set is what keeps "no node is code" true here.** DS-13 is the wave that
> lets a user declare an endpoint from a form; until then every URL this platform will
> call on someone's behalf is in the repository. A param can never move the host or the
> path — declared names land in the query or body, and the one path placeholder is
> percent-encoded with an EMPTY safe set, so a message id of `../../admin` addresses a
> message called that and reaches nothing else. An undeclared param is REFUSED, never
> dropped: a silently discarded `cc` is a message the author believes was copied to
> someone. Both refusals moved to SAVE (K1's rule) — `validate_chain` now refuses an
> unknown operation naming the closed set, and an input the operation does not declare.
>
> **A scope is checked against what was GRANTED, not what was asked for** — and silence is
> not a measured absence: a provider that returns no scope list at all leaves every row
> lit, which is the palette's own rule (only a measured zero dims) one plane over.
>
> **The first closed published set in this plane, and the first LIST.** Every effect kind
> before this published the same keys on every instance, so a table keyed by kind WAS the
> answer; an integration step's keys are its OPERATION's, known at save time. So
> `published_keys(effect)` became a function, and B1's unknown-key refusal finally reaches
> a remote call where the open-set kinds must accept anything. It also amends W2's
> premise, which was true when measured: *nothing in this plane published a list*, so its
> rule could be written as "open set ⇒ fannable". A remote read is the first honest list —
> `for_each` over `inbox.items` works and `for_each` over `inbox.count` is still refused
> at save, which an open set could not have told apart. What each item carries is DECLARED
> too: Graph's `/me/messages` returns whole messages, bodies included, and a run history
> is stored and read by people.
>
> **What is deliberately NOT here: a pause.** A write the gate refuses returns a terminal
> refusal, not the `approval_required` a step turns into a DS-8 proposal — because
> `inbox.accept_proposal` resolves a proposal by loading a DECLARED ACTION and running the
> one governed-write executor, so a proposal staged for an integration operation would be
> presented to a human, accepted, and then fail with "declared action no longer exists". A
> refusal a person can act on beats a proposal that cannot be honoured. **Filed for DS-11's
> completion:** teach the inbox a second proposal kind.
>
> **Live receipts, driven in the browser against a real API.** The chain was authored on
> the Design canvas (two SERVED pickers — grants from `/integrations/connections`,
> operations and their ports from `/integrations/operations?connection_id=`, because
> whether a grant carries an operation's scope is a fact about the PAIR), saved, and run:
> both hops `executed`, the read publishing its declared keys only, the write bound to
> `{"$from": "step1.count"}` and arriving as `3`. It also fired UNATTENDED on the
> scheduler heartbeat. `for_each` over `inbox.items` fanned one read into three per-item
> writes. With `AUGHOR_ACTION_APPROVAL=1` the read proceeded and the write stopped with
> the gate's own sentence; allowlisting `integration.slack.slack.chat.postMessage` for
> THAT grant let it through and left another grant refused. And the network path is real,
> not stubbed: a step pointed at the unmodified `gmail.messages.get` reached
> `gmail.googleapis.com` and came back with Google's own 401 verbatim in the run history.
> The audit ledger carries one row per call (`read_only` for a read, `high` for a write,
> scoped to the grant, naming its owner); `/activity` carries the `EXTERNAL_CALL` events
> that make them countable.
>
> **Two defects the browser found and the green suite had agreed with:** the canvas drew
> two integration steps — one reading Gmail, one posting to Slack — as two identical empty
> boxes, because `effect_detail`'s allowlist had no key for the kind AND the design node's
> three per-kind tables (`PRIMARY_FIELDS` / `KIND_ICON` / `KIND_HUE`) had no entry, so it
> also fell back to `subchain`'s hue. The operation is safe on a picture by CONSTRUCTION
> (a roster id, never authored text); the grant is not, and stays in the rail. And a
> module-level cache on the grants hook meant a page that had once seen no connected
> accounts kept saying so after one was connected in another tab.
>
> **Left open, chip-filed:** ownership of a grant is RECORDED on every audit line but not
> ENFORCED — an automation fires from cron with no identified user, so a rule demanding
> `conn.user_id == current_user_id()` would refuse every scheduled step on a multi-user
> install. Discovery is scoped instead (the registry and the routes offer only the
> caller's own grants). That is VA-10's to close. The chart series is six CVD-validated
> tokens behind `lint:palette`, so this kind SHARES `--chart-4` with the declared action
> rather than inventing a seventh: they are the two kinds the approval gate can stop.

**DS-12 · Ontology components — the moat.** Metrics, entities, cohorts and trusted queries
as first-class typed nodes: "Revenue (metric)" publishes a typed series; "Churned accounts
(cohort)" publishes a LIST a `for_each` fans over — closing §3.2's honest limit that
nothing in the plane publishes lists. The component class no canvas competitor can copy
without a semantic layer. **Receipt:** fan over a cohort and post one message per at-risk
account, the cohort's definition one click away.

**DS-13 · Declarative custom components.** Extension WITHOUT `exec()`: an HTTP-template
component (endpoint · schema-typed input/output · secrets from the vault · dispatched
through `govern.outbound`) plus pack-shipped component bundles via the skills/packs plane
(VA-1's draft→promote gate). The direct answer to Langflow's defining liability — their
"New Custom Component" opens a Python editor; ours opens this form. Also the home of the
useful sliver of their catalog: `http_request` · `url_fetch` · `web_search` (a real gap in
our tool roster today) · file parsing. **Receipt:** a user adds a PagerDuty component from
a form, never writes Python, and the approval gate still owns its writes.

**DS-14 · B3 — chains as MCP tools** (absorbs the old LATER item). An enabled automation
is exposable as a tool on our MCP server — external agents invoke it and inherit the whole
governed path, because the server already fronts the real API. A2A agent cards ride later
only if that protocol earns it. **Receipt:** Claude Desktop calls "daily-sales-report" and
the run appears in Activity like any other.

#### Phase 4 · The authoring inversion

**DS-15 · Conversation authors the canvas.** Describe the outcome in chat; the agent
proposes a chain — grounded in the ontology, the registry and THIS deployment's doors —
rendered on the Design canvas with a dry-run receipt attached; the human edits and arms
it. Creation by proposal, the same shape as every governed write here (a grant is
permission to PROPOSE). Even Langflow no longer assumes the canvas is the author (their
Assistant builds whole flows; coding agents author over MCP); ours is stronger because
proposal-first already exists. **Receipt:** "post a Monday pipeline summary to #revenue"
becomes a drawn, dry-run-proven chain awaiting one click.

**DS-16 · The migration funnel.** An importer for Langflow (and archived-Flowise) flow
JSON: model/prompt/agent/tool nodes map onto an agent record plus a chain; code-carrying
nodes are REFUSED with a sentence naming the no-code-injection law and the declarative
alternative. Their format is the category's lingua franca and their users' exit path.
Cheap after DS-10, pointless before; their flow format migrates in-engine upstream, so
DS-16 tracks it release-by-release. **Receipt:** drop a Langflow JSON; get a governed
chain plus an honest report of what was refused and why.

**DS-17 · Deploy is a menu of doors.** One Deploy control on the canvas enumerating what
THIS deployment can open — schedule · webhook trigger (new, small: the trigger kinds grow
by one) · Slack door (RC-5) · MCP tool (DS-14) — each an existing plane, each honouring
the alt-door rule. Deploying an agent has always meant binding doors; say it on the
surface where the behaviour lives. **Receipt:** a finished chain goes live on a schedule
and as an MCP tool from one menu, no other screen involved.

**Revisit triggers — §4.2's verdict is falsifiable.** Any of these is "new facts" and the
question reopens without ceremony: upstream ships default-on sandboxed execution AND a
genuinely embeddable editor package with a host-auth bridge (both, not either) ·
branch-merge semantics land in their engine · IBM moves Langflow to neutral governance
(foundation, enforced OSS RBAC, published trademark policy) · **or Phase 1 stalls for two
quarters** — then the lfx-in-jailed-workers posture gets a real trial, not a paragraph.

**Standing upkeep (an hour a quarter, not a project):** track their releases — the
flow-JSON format (DS-16), the component anatomy (palette parity), and their CVE feed,
which doubles as a checklist of mistakes for §3.4 to avoid (their seeded-PRNG Fernet key
derivation is the class example; ours was audited clean 2026-08-31 — no derivation step
exists to get wrong).

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

**Addendum — re-examined 2026-08-31 at the user's direction (*"be absolutely open… fork it…
go all in"*): refusal CONFIRMED on stronger evidence; the vision adopted as Arc DS (§3.7).**
The four-pass re-study (docs 1.5→1.12 · source v1.12.0 `da3d5050` · security/ownership · our
seams) added, beyond the 2026-08-30 findings:

- **`lfx` is real** — since 1.11 their engine ships standalone (MIT, pluggable services;
  parallel frontier scheduling, per-item subgraph loops, checkpoint/pause worth studying for
  DS-6/7/8) — but it executes Python embedded in the flow JSON in-process, unsandboxed;
  sandboxing upstream is still an open proposal. A flow accepted from a user is code accepted
  from a user.
- **The editor is not extractable.** Their official embedded mode is chrome-hiding over an
  iframe (their docs: it controls UI visibility only, not API exposure); the canvas is welded
  to 21 stores and a hand-written client imported by 382 files; upstream moves at ~300
  commits/month (45 releases in 12 months); no successful commercial fork or white-label
  exists, and white-label requests upstream were closed not-planned.
- **The security record is a pattern, not an incident**: ~a dozen critical/high advisories
  2024–26, twice CISA-KEV, three in-the-wild campaigns (botnet, cryptominer + credential
  harvest, cross-tenant flow-key exfiltration), one "fixed" release later shown still
  exploitable — and a vault key derived from a seeded PRNG (CVSS 9.1). Our own Fernet paths
  were audited clean the same day: no derivation step exists to get wrong.
- **Ownership and category**: IBM closed the DataStax acquisition; hosted Langflow was shut
  down 2026-04; OSS RBAC is a pass-through (enforcement is the commercial plugin seam);
  watsonx is the funnel. Flowise reached EOL 2026-08-31; OpenAI's Agent Builder sunsets
  2026-11. The standalone canvas is the most disposable layer of the agent stack.
- **The ceiling stands**: If-Else×Loop incompatibility and no-branch-merge are still in the
  1.11 docs verbatim, seven releases after we first cited them.
- **The structural law, re-derived from our own seam map**: the REST API is Aughor's only
  complete governance choke point — token caps live in the LLM funnel, PII at
  `security_post`, approval/audit/identity in the one executor, spans in the engine loop.
  A foreign engine bypasses all of it, or is routed through the API and reduced to a picture
  of our engine. Their node is CODE; ours is a REFERENCE.

Revisit triggers that would legitimately reopen this are carried at the end of §3.7.

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
  ✅ B2  SHIPPED 2026-08-30 — "Dry run" on the design rail: the chain walked with sample
        values, nothing dispatched, claimed, committed, spanned or stored
  ✅ W1  SHIPPED 2026-08-30 — "Only if" on a step: guard clauses over the chain context,
        evaluated before the dispatch, drawn on both canvases, refused at save like any
        other reference; a guarded-off run no longer pages on-call
  ✅ B1  SHIPPED `16019b5a` — typed ports (server vocabulary, fetched), drag-to-bind,
        unknown KEYS refused at save; Runs layer retired into Activity → Phases

  ✅ W2  SHIPPED 2026-08-30 — "For each" on a step: one step, N dispatches, the guard
        evaluated per item, an empty list a skip that does not page on-call, and a cap
        that REFUSES rather than sending a truncated part of a list

  ✅ DS-1…DS-5  SHIPPED 2026-08-31 (#417, #418) — the palette that tells this deployment's
        truth · run-to-here · live runs streaming onto nodes · undo/redo, copy/paste,
        minimap, layout sidecar, the last window.prompt dead · the agent Map
        (spec-deltas in §3.7 Phase 1; DS-1's P1 port-filter + P2 rail remain open)

  ✅ DS-6  SHIPPED 2026-08-31 — branch ("Otherwise": else_of, routed on the guard's
        VERDICT, undecided takes neither arm) + join ($from_any: first alternative that
        resolved; a join waits only on taken branches). Their seven-release-old ceiling,
        crossed — receipts in §3.7 Phase 2

  ✅ DS-7  SHIPPED 2026-08-31 — parallel steps: scheduling="parallel" (opt-in, per
        automation), frontier over the same effect_refs the awaits and canvases read;
        one step body driven by both orders; 2.7s parallel vs 5.1s ordered on the same
        chain, spans overlapping under one trace — receipts in §3.7 Phase 2

  ✅ VA-11 consumer / DS-11 first half  SHIPPED 2026-09-01 — the vault is consumed: an
        `integration_call` step spends a user's grant through govern.outbound (cap, span,
        EXTERNAL_CALL, audit), reads and writes are declared as DATA against a closed URL
        set, a write passes the approval gate, and the palette/registry tell the truth
        about which grant can run which operation — receipts in §3.7 Phase 3

NEXT (order within a band is the user's knob)
  VA-9d  MCP consumer             (posture first — allowlist + outbound off by default;
                                   NOT started: §3.1 requires that posture be agreed with
                                   the user first. DS-11's second half)
  S1  Qdrant embedded by default  (installs WITH the app, not beside it — §3.6)
  DS-1 leftovers                  (P1 port-compatibility filter · P2 rail — §3.7 Phase 1 ledger)
  tool_grants column              (turn VA-9c's phantom into a stored grant — §1 honest limits;
                                   migration + store/create/patch surfaces; grants stay
                                   PROPOSE-only)

THEN    (§3.7 Phase 2 COMPLETE — DS-8 durable pause and DS-9 subchains SHIPPED)

LATER   DS-11 completion (the inbox's second proposal kind, so an integration write can
        PARK on a human rather than refuse) · DS-12 ontology components · DS-13 declarative
        customs · DS-14 chains-as-MCP-tools   (§3.7 Phase 3)
        DS-15 conversation-authors-canvas · DS-16 migration funnel · DS-17 deploy-as-doors
        (§3.7 Phase 4)
        VA-10 multi-user + admin  (hardening pass over everything above)
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
2. ✅ **DECIDED 2026-08-30 — the primitives come first.** W1 and W2 both shipped; next is the
   VA-11 CONSUMER (§3.4). Reasoning kept: they are independent — W1/W2 make what exists
   properly expressive, VA-11 makes it reach further — and W2 needs nothing from outside
   this repo, while VA-11's live receipt waits on a Google OAuth client only the user can
   create.
3. **VA-10's privacy default** — may an admin read a user's prompts, or only their metadata?
4. ✅ **DECIDED 2026-08-31 — the visual-editor question: the grammar, not the codebase.**
   The user re-opened §4.2 with a mandate for total openness ("fork it… go all in… think
   years ahead"); the four-pass re-study confirmed the refusal (§4.2 addendum) and the
   vision landed as **Arc DS (§3.7)** — Langflow-class editing on our engine, then past
   their documented ceiling, then the governed component economy, then authoring by
   proposal. Phase-1 default order DS-1 → DS-4 → DS-3 → DS-2 → DS-5, reorderable; the
   VA-11 consumer stays first among equals in §5 (repairing the built-and-inert vault is
   §7's own law).

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

A second application · a TS runtime · an n8n dependency · a low-code flow engine (adopting a
foreign one, that is — Arc DS's visual authoring over our own engine is §3.7, not this) · a
canvas for anything without a producer/consumer relation (an agent record still gets a form;
its *system* gets DS-5's map) · model ids hardcoded anywhere in `aughor/`.

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
