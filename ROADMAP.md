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
| Agent plane (Arc VA) | VA-0…VA-9b, VA-4a…4e shipped; VA-9c **partial** — the propose-only action tool is live but no grant can be stored (limits below); the agent Map (DS-5); VA-11 vault+broker+catalog shipped and **consumed 2026-09-01** (DS-11's first half: an `integration_call` step spends a grant through govern.outbound); **VA-9d first slice shipped 2026-09-02** — an allowlisted MCP server's read-only tools, discovered, classified and callable as an `mcp_call` step (§3.1); its write slice and UI, and VA-10, remain open |
| Governance | `govern/` — actions · caps · guardrails · lineage · outbound · tags; `security/` — audit · authz · credentials · pii; graduated approval gate → `approval_required` (428). (`disclosure` DELETED 2026-09-06 — see the ledger.) |
| Reach (Arc RC) | Slack door live: @mention → answer, streamed, threaded, filed as a conversation |
| Automations | trigger → effects with `{"$from": …}` dataflow, `when` guards, `for_each` fan-out, branch+join (`else_of` / `$from_any`, DS-6), parallel steps (`scheduling`, DS-7), dry run + run-to-here, typed-port Design canvas with a truth-telling palette, live runs streaming onto nodes, undo/redo · copy/paste · minimap · layout sidecar; runs visible in Activity as traces |
| Observability | OTLP spans, waterfall + flow canvas, per-node usage, cost with explicit `unpriced` |
| Connections | 7 live; BigQuery/theLook mirrored daily 07:00 |

**Honest limits, same date:** a fan-out has no
list to read from any effect kind but the declared
action's open outcome (§3.2); ~~`UserAgent.tool_grants` is a phantom~~ — **RETIRED
2026-09-02**: migration 6 stored the column, `_row_to_agent`/`_PATCHABLE`/create/patch all
carry it, grants validate at write against the connection's declared roster (a `*` is
refused by name — "a grant names an action, never a roster"), and `propose_action` is
reachable end to end while staying PROPOSE-only; no user-scoped credential store anywhere;
warehouse connections have **no
owner**; no RBAC on `/agents/custom*`. (`telemetry.py`'s Langfuse backend, dead here on
2026-08-30, has since been repaired to ride the OTel exporter — OA·LF-1.)
**The ontology, measured 2026-09-10 (§3.15):** table = entity by construction; no
instance layer; its semantic fields reach the UI and not the prompt; the only ablation
of injected context (R4, 2026-06-21) was a regression; the kinetic plane holds one
declared action. The layer §0 calls the moat is, today, a description the agent reads
rather than a mechanism it runs on — Arc ON is the re-think, §6 item 14 the decision.
**Decided 2026-09-10 (all four clauses YES); ON-0 started:** 59 of 142 ontology fields can
change any prompt block, 83 cannot (`ontology.prompt_reach`, ratcheted); the R4 harness had
been un-runnable since June and is rebuilt with an ontology arm; the LLM arms ran the same
evening on the one set that still exists (`samples/ecommerce`: 12/12 on every arm — a ceiling,
not a lift; `workspace/missimi`, the discriminating set, is GONE from this instance; the hard
set re-authored on LuxExperience ran the same night — raw 13/14 = ontology 13/14, guards 100%
safe, NO LIFT; the falsifier fires as written, but the block carried four wrong N:N labels —
the user decides, §3.15). **ON-0a built 2026-09-11 (three commits):** cardinality and lifecycle
terminal states measured at build time, the map as claims — `packs/core-ecommerce` and
`packs/fashion-ecommerce` — evaluated by tier; its re-run on the measured block ran
2026-09-11 and lifted nothing (raw 14/14, ontology 13/14) — the falsifier fires on a block that says
true things. **ON-1's first slice and ON-2's first slice built 2026-09-11:** objects have stable api
names and a measured backing; the object-set algebra compiles over measured links with the join law
by construction — 22 of 26 hard reference questions compile and all 22 answers are right when a
person writes the object query, `POST /objects/query` answered "revenue per segment last quarter"
live equal to the reference with no model call, and `run_sql`'s fan-out detector turned out never to
have run on the conversation's door (found, flagged). A MODEL filling the same queries regressed
(1/14 and 3/12 against raw 14/14 and 12/12), so the conversation's door is PARKED behind its flag
and ON-6 is RETIRED (§6 item 15, decided 2026-09-11); ON-3, the object pages, started.

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
automations-run-as-agents (VA-9b), the propose-only action tool (VA-9c — **completed
2026-09-02**: the law "a grant is permission to PROPOSE, never to EXECUTE" and the
`propose_action` tool were live from the start; `tool_grants` is now a stored column, so an
agent can hold a grant across restarts and the tool serves its roster).

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

### 3.1 · VA-9d — the MCP consumer (FIRST SLICE SHIPPED 2026-09-02)

~~`aughor/mcp/` today is a **server** exposing Aughor's tools, plus an HTTP client to Aughor's own
API. A generic consumer — stdio + SSE, registry, discovery, health — does not exist.~~

> **The premise was re-measured before building, and for once it held exactly.** The
> `mcp_tool` component family looked like the place it would be wrong — but
> `_mcp_tool_components()` reads `aughor.mcp.server`'s OWN tool manager, so it re-reports
> what we serve, never a foreign roster. A repo-wide sweep for `stdio_client`, `sse_client`,
> `streamablehttp_client` and `ClientSession` found **zero** first-party hits, and
> `client.py`'s `_stream_sse` is Aughor's own SSE framing, not the protocol's. Two things
> were better prepared than the paragraph admitted: the SDK client is already a dependency
> (`mcp>=1.28.0`, its `stdio`/`sse`/`streamable_http` transports installed and unused), and
> `govern/outbound.py`'s docstring already names the counterparty — *"later an MCP server
> id"* — and says outright that VA-9a *"comes before that one"*. The seam was built for
> this slice.
>
> **Shipped: `aughor/mcpservers/`** — `models` (the record + `classify`) · `store` (the
> allowlist and the rosters discovered against it) · `session` (stdio + streamable HTTP,
> transport only) · `discover` (tools/list, classification, health) · `call` (THE door).
> Plus `GET/POST/PUT/DELETE /mcp-servers`, discover and health routes, a `remote_tool`
> component family, and the `mcp_call` effect kind so a chain can name one.
>
> **The posture's own sentence had a hole, and the protocol filled it.** "A tool the server
> declares as mutating is listed and refused" does not say what to do with a tool that
> declares NOTHING — which is what most real MCP tools do, so reading it as "refuse the
> flagged ones, allow the rest" would have allowed almost everything. The specification
> settles it rather than leaving it to taste: `readOnlyHint` is documented *"Default:
> false"* and `destructiveHint` *"Default: true"*, so **silence is not an absent answer, it
> IS the answer "may modify, possibly destructively"**. An unannotated tool is listed and
> refused exactly like a declared-mutating one. `classify()` is the single place that
> decides, and a contradiction (`readOnly` AND `destructive`) takes the restrictive reading.
>
> **The allowlist is the off state — no flag.** `FLAG_DEFAULT` has been empty since the
> flag endgame, and a switch somebody must remember to leave closed is the control this repo
> already replaced once. A fresh clone reaches nothing because there is nowhere to go, and
> the only way to add a destination is a human writing one down. That also settles the
> trust question the SDK raises (*"clients should never make tool use decisions based on
> ToolAnnotations received from untrusted servers"*): what makes a server trusted here is
> that a person put it in the table — so the allowlist does real work rather than decorating.
>
> **🔴 The defect that only driving it could find.** Discovery was capped and spanned and
> recorded **nothing**. `session_log.emit` drops any event with no ambient trace — correctly,
> and by its own docstring — and a chain step inherits the run's trace (VA-4d made the run id
> the trace id) while a discovery pressed from a ROUTE has none. So the step path audited
> perfectly and the route path was silent, which is the wrong way round: discovery is the
> most audit-worthy act on this surface, being the one that first opens a connection — or
> spawns a process — against a newly written-down destination. Fixed by binding a trace in
> `discover()` and `call()` rather than at the route, because the route is not the only
> caller. **The test that should have caught it was the same shape as the bug**: it spied on
> `external_call` and proved the wrapper was entered, which was never the claim. Rewritten to
> assert the ambient trace at emission, and verified to FAIL with the fix reverted.
>
> **Receipt, live 2026-09-02** (a real MCP server over a real stdio subprocess, deleted
> after): empty allowlist → `/mcp-servers` returns `[]` and the palette dims `mcp_call` with
> the door named → register (nothing contacted; a stdio row with no `command` is a 400 in the
> model's own words) → Discover → **3 tools, 1 callable here** → saving a chain step naming
> `delete_everything` is **refused at SAVE** with the roster's own sentence → the read-only
> one saves, runs, and publishes `{"text": "It is bright and 21C in Lisbon.", "truncated":
> false}` → and both calls land in the live ledger as `EXTERNAL_CALL` beside Slack's:
> `mcp:<id>.tools/list` and `mcp:<id>.tools/call:read_the_weather`.
>
> ✅ **SHIPPED 2026-09-02 — the write slice, built to the decision below.** `McpToolGrant`
> + `grant_verdict()` (models) · a `mcp_tool_grants.json` store beside the roster, so no new
> env var and no migration · the door's fifth gate · `GET/PUT/DELETE /mcp-servers/{id}/
> grants[/{tool}]` · grant controls on the catalog roster · the save-time check and the
> palette both taught the same thing. 35 tests, the two load-bearing ones verified to FAIL
> with the fix reverted.
>
> 🔴 **The premise in the decision's own wording was wrong, and measuring it first is what
> caught it.** "Reusing `tool_grants`" is not possible: that column's subject is an AGENT,
> its object is an ontology action id validated against a connection's declared actions, and its verb is
> PROPOSE. This grant's subject is the deployment, its object is a `(server, tool)` pair on
> somebody else's machine, and its verb is CALL — and it must carry a PINNED DECLARATION,
> which that column has nowhere to put. The principle survived the premise intact; only the
> storage moved. `McpToolGrant`'s docstring carries the distinction so the noun stops
> inviting the confusion.
>
> 🔴 **A second gap the build found: `writes` reached the SPAN and not the LEDGER.**
> `external_call` sends `attributes` to mlflow and emits `payload={"operation", **extra}` —
> two destinations — and the operation string is `tools/call:<name>` for reads and writes
> alike. So the audit trail this slice is accountable to could not tell a granted mutation
> from a read. Same class as the read-only slice's missing trace: capped, spanned, and
> unrecorded. Fixed on the `extra`, and the test asserts the ledger rather than the wrapper.
>
> ✅ **DECIDED 2026-09-02 (the user's call, §6.6) — the write slice's two questions.**
> *Whose declaration of "read-only" is believed:* **nobody's but ours.** A server's
> annotation is DISPLAYED and ADVISORY; what authorizes a mutating call is an explicit
> **per-tool grant a human wrote down**, reusing `tool_grants` rather than standing up a
> second grant plane beside it. This is the reading the SDK's own warning asks for —
> *"clients should never make tool use decisions based on ToolAnnotations received from
> untrusted servers"* — and note what it does to `classify()`: the restrictive defaults it
> already applies (silence = "may modify, possibly destructively") now decide what **needs a
> grant**, never what **may run**. The allowlist says where we may reach; the grant says what
> we may do there. Two questions, two answers, neither borrowed from the counterparty.
>
> *What a server that CHANGES a declaration after registration may do:* discovery **pins a
> snapshot**, and when a granted tool's annotations change that tool's grant is **REVOKED** —
> the next call is refused until a human re-ratifies. Scoped to the tool that actually moved:
> a server is not quarantined for re-versioning one label, because a control that fires on
> every legitimate change is one people learn to click through. Fail-closed, because a
> silently relabelled tool is precisely the attack the advisory reading exists to blunt.
>
> **Still unbuilt here** — ~~a UI~~, OAuth-authenticated servers, non-text tool results.
> **RE-MEASURED 2026-09-04, and two of the three were wrong:**
>
> - ~~**a UI**~~ — **BUILT.** `McpServersSection.tsx:298` renders `+ Custom MCP`, with tests
>   covering it, against full CRUD + `/discover` + per-tool grant routes. It shipped with
>   #426 and this line was never updated.
> - **OAuth-authenticated servers** — still true as written (the `auth_header` is one opaque
>   forwarded value), **but it is NOT what unlocks Arcade/Composio, and the sentence below
>   that says it is was wrong.** This repo's own Langflow study records Composio as *keyed by
>   `COMPOSIO_API_KEY`*, with *"service provider authentication managed through the Composio
>   platform"* — the platform absorbs the per-service OAuth, and what it wants from us is an
>   API key in a header. `session.py:74` already sends exactly that. **So the most-wanted
>   feature is reachable TODAY** via a Custom MCP server with an API-key auth header; it wants
>   an end-to-end receipt against a real key, not an OAuth implementation. OAuth remains a
>   real capability for servers that demand a flow of their own — a narrower, separate case.
> - **non-text tool results** — ✅ **the DECLARATION half shipped 2026-09-04.** Images and
>   embedded resources are still not carried (a base64 image in a chain context is a
>   megabyte no downstream step can read), but the omission is no longer silent — which it
>   was, in flat contradiction of the very sentence this line used to justify it. A tool
>   returning a chart plus one line of prose handed back the prose alone, and every reader
>   downstream, the model included, saw a complete-looking answer. `_text_of` now counts the
>   dropped blocks by kind onto `McpCallResult.omitted` AND states them in the text, because
>   the text is what a step actually reads and a flag nobody consults would leave the model
>   exactly where the objection says it must not be. The notice is appended AFTER the cap so
>   a long result cannot truncate away the sentence saying something is missing.
>   ⏳ Still owed: CARRYING them, typed, when a consumer exists.

VA-9's own risk note calls this *"the largest new attack surface in the arc"*. ~~Agree the
allowlist and the outbound-off-by-default posture with the user before starting.~~

> ✅ **POSTURE DECIDED 2026-09-01 (the user's call, asked before a line was written):
> READ-ONLY TOOLS FIRST.** Ship discovery and read-only tool calls against an allowlisted
> server; a tool the server declares as mutating is **listed and refused with a sentence**
> until a later slice — listed, because a roster that hides what a server offers is the
> catalogue-that-lies failure DS-10 exists to end, and refused, because the hardest
> question in this wave is whether we trust a third party's own risk labelling, and
> deferring it is cheaper than getting it wrong. Everything the DS-11 vault half
> established still binds: every call rides `govern.outbound` (capped, spanned,
> `EXTERNAL_CALL`), and OUR approval gate stays the policy authority when the write slice
> lands. **What this decision does NOT settle** and the write slice must: whose declaration
> of "read-only" is believed, and what a server that changes a tool's declaration after
> registration is allowed to do.

**Promoted in importance 2026-08-30:** the Langflow study (§4.2) found that the connector
platforms which solve the OAuth problem — Arcade, Composio — expose their tools **over MCP**.
VA-9d is therefore no longer an abstract capability; it is the delivery mechanism for the
most-wanted feature on this list.

> ✅ **And that delivery mechanism is BUILT (re-measured 2026-09-04).** The chain — custom
> server UI → registration → `/discover` → per-tool grants → `mcp_call` step — is complete,
> and these platforms authenticate with an API key the existing `auth_header` already
> forwards. What is owed is a **receipt**, not a feature: register one against a real key and
> drive a tool end to end. That needs a credential, so it is the user's to run, not mine.

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
  plane publishes a list** — `investigate` publishes two strings (three since
  2026-09-02: `summary` carries the report's executive summary, because the nightly
  briefing was measured posting a 71-character *title* while the trust warning and the
  numbers sat in a 20KB report Slack never saw — still no list), `slack_post` two
  strings, `notify`/`brief`/`monitor`/`agent_alert` nothing at all, and only the
  declared-action kind has an OPEN outcome shape. So a source is a **literal list** or a
  binding onto that open kind, and fanning over a closed-set producer is refused at SAVE
  rather than found at 09:00 as "cannot iterate a str". ⚠️ **Amended 2026-09-01 by
  DS-11:** the measurement was true when taken and is not any more — an
  `integration_call` step publishes `items`, a real list, in a CLOSED set. The rule is now
  "a source is a literal list, a binding onto an open kind, or a binding onto a key the
  producer DECLARES to be a list", which is strictly better: fanning over that step's
  `count` is still refused, where an open set would have let it through.
  **DS-12 closed the same limit from the other side**, for a key whose list-ness is a
  property of the KIND rather than of an operation: a `trusted_query` publishes `rows`.
  Its table is read BY `list_published_keys()` rather than sitting beside it, because two
  places that both say which keys are lists is two places that will disagree. The item is
  one more entry in the
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

- ~~**B1 · Typed bindings.**~~ — **SHIPPED `16019b5a`**: typed ports over a server-fetched
  vocabulary, drag-to-bind, and unknown KEYS refused at save (`PUBLISHED_KEYS` /
  `published_keys()` in `automations/dataflow.py`, covered by three test files). The Runs
  layer retired into Activity → Phases.
  ⚠️ **This entry read "the weakest seam in VA-12/13" for days after it shipped** — §5's band
  had it right the whole time. Third instance this week of a resolved item reading as open
  (VA-9d's posture, the report-quality count, this). Verified in code 2026-09-03 before the
  strikethrough, not taken from the band.
  *Kept because it was the design brief and the ports still answer to it:* render bindings as
  visible inward/outward ports — coloured dots, output right, input left — nodes draggable,
  fields editable on the node.
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

### 3.4 · VA-11 — the credential becomes a governed object (1·2·4 SHIPPED `dadc6f63`; CONSUMED by DS-11)

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

> **The consumer shipped 2026-09-01.** The premise was re-measured first and still held to the
> line: `fresh_access_token()` had exactly zero production callers, and `routers/integrations.py`
> was still the only importer of the package. It now has one caller, deliberately one —
> `integrations/call.py`, where refresh, the scope check, the cap, the span and the audit line
> all live, so a second consumer inherits every one of them by construction instead of by
> remembering. The step is the effect kind **`connection_call`**, and the roster it spends a
> grant on is `integrations/operations.py`: four declared reads (Gmail list · Gmail message ·
> Calendar events · Graph mail) with typed params, a required scope and a response mapper each.
>
> **Three laws it is built on, each refusing something a plausible version would have allowed.**
> *A closed roster, not a URL field* — an effect taking an arbitrary URL is a request-forgery
> surface wearing a credential, and a `{"$from": …}` binding could reach it; the host and path
> are constants of the module and authored config chooses only the ROW. (The general HTTP
> template is DS-13's, behind its own form.) *Reads only* — a write under a user's grant belongs
> behind the approval gate, and §3.4's own line settles it: two gates that can disagree is
> strictly worse than one. *The credential selector may not be bound* — `BINDABLE_FIELDS`
> DECLARES the input ports but `resolve()` walks the whole config, so every other kind in the
> plane will happily substitute a binding into a field its tuple omits; harmless on an
> org-scoped `bot_id`, not harmless on a credential, so this kind refuses it on the model where
> a save actually fails.
>
> **Measured, not assumed.** A closed published set is refused as a `for_each` source (correctly
> — every closed one in this plane is strings), so the kind publishes an OPEN set: one kind
> carries many operation shapes, and that is exactly what makes *list the messages → for each →
> read it → post* expressible. DS-10's registry picked the seventh effect kind up with **no
> registry edit at all**, which is the property that wave claimed and this is the first
> independent exercise of it. The palette dims the row on a deployment with no grant and names
> the door that fixes it, and a REVOKED grant does not light it — counting rows would have.
>
> **Left open, and honestly.** Deliverable 3's live receipt still waits on a Google OAuth client
> only the user can create — every path here is proven against a faux provider at the one
> seam (`call._get`), which is where the broker's own suite draws the same line. Any automation
> author may name any grant id today; grant ids are unguessable and neither the palette nor
> `/integrations/operations` exposes another user's, but ENFORCING that is VA-10's hardening
> pass, not this wave's. And `connection_call` is the seventh effect kind while the design
> system caps its series at six ("never a seventh hue"), so it takes the documented fallback
> rather than an invented token — extending the ramp is the user's call.

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

~~Untouched.~~ **RE-MEASURED 2026-09-04: "Untouched" was wrong, and so was "risk is policy,
not code" — it is the exact inverse.** Three of the five pieces are already built:

| Piece | This line said | Measured 2026-09-04 |
|---|---|---|
| RBAC on the agent plane | untouched | **built** — `aughor/rbac/` store, `/rbac/roles` routes, `effective_capabilities`/`resolve_roles`, and **80 routes enforcing a capability gate** |
| Per-user / per-org quotas | untouched | **built** — `govern/usage_caps.py`: `UsageCap`, `evaluate`, `check`, `observed_usage` |
| Audit of admin trace access | untouched | **built** — VA-5's `trace.payload_access`, categorized into the governance feed |
| Admin view across users | untouched | **genuinely missing** — no admin routes exist |
| Per-user analytics | untouched | **impossible today** — `COUNT(DISTINCT user_id)` = **0** over 6,618 rows |

~~**The blocker is code, and it is authentication.**~~ **CLOSED 2026-09-06 (decision §6
item 11 — OIDC, the user's call).** `security/oidc.py` verifies a JWT-shaped bearer at
the `resolve_principal` seam: issuer + audience from config, keys via the issuer's own
discovery document — **no IdP hardcoded** (the model-id law applied to identity), so
Google Workspace / Azure AD / Okta / Keycloak are the same deployment with different env
values. Fail-closed throughout: half-configuration (issuer without audience) refuses;
an invalid token resolves to NOTHING rather than downgrading to the header seam; and
while an issuer is configured under `AUGHOR_REQUIRE_IDENTITY`, the `X-Aughor-*` headers
are **DEAD** — the mallory demonstration below is now a 401, pinned by a test that was
verified to FAIL with the wiring reverted. The header seam survives only for identity-off
localhost and for OIDC-less deployments, exactly as before, byte-identically. The admin
view shipped with it: `GET /admin/users` (metadata only per §6.4 — usage ∪ role
assignments, coverage stated so an unattributed ledger never reads as one busy blank
user) + the Users·measured section on the access panel. ⏳ Owed and user-keyed: the live
receipt against a real IdP tenant (issuer + client id only they can create) — same class
as VA-11's Google receipt.

The paragraph this replaces, kept for the record: `resolve_principal` read
`X-Aughor-Org`/`X-Aughor-User` as unverified headers, marked *"SEAM: swap this for
authenticated-token extraction in production"* — and there was no JWT, no OIDC, no
session anywhere in the tree.

**Demonstrated on the live instance 2026-09-04**, not argued from a code comment: with
`AUGHOR_REQUIRE_IDENTITY=1`, a request with no headers is **401**; `X-Aughor-User: mallory`
is **200** with no credential; and the §6.4 break-glass audit then recorded
**`read_by: mallory`** — a string typed into a curl. One thing came out BETTER than
expected: a caller naming a different org got **403**, so tenant isolation (DATA-06) is real
enforcement, not theatre. The gap is specifically the USER half, inside an org.

That matters because every remaining piece keys on it: per-user analytics groups by it,
per-user quotas meter by it, and §6.4 requires a payload read be *"visible to the user whose
data it is"*. Built on a self-asserted header, that surface would be trivially
misattributable — worse than absent, because people would trust it.

⏳ **VA-10 is therefore not one band.** It is (a) an auth model — service tokens? OIDC
against which IdP? — which is the user's decision, and (b) an admin view, which is small once
(a) exists. **Risk is policy, not code** was written when the policy was undecided; §6.4
decided it 2026-09-02, and what remains is the code this line assumed was already there.
✅ **DECIDED 2026-09-02 (§6.4): visible metadata, GATED payloads.** Counts, timings, costs,
tool names, error rates and run outcomes are admin-visible without ceremony — that is the
whole analytics case, and it needs no prompt text. Reading a prompt or a response body is a
**break-glass**: an explicit act, with a reason recorded, written to the audit log, and
**visible to the user whose data it is**. The asymmetry is the point — metadata answers
"is this deployment healthy", payloads answer "what did this person ask", and only the
second needs a name attached to it.

---

### 3.6 · ~~S1 — Qdrant installs WITH the app, not beside it~~ — **SHIPPED 2026-09-02**

> **Built as directed below: the third branch.** `_client()` opens qdrant-client's
> in-process local mode at `AUGHOR_QDRANT_PATH` (default `<state_dir()>/qdrant`, so the
> suite's temp `AUGHOR_STATE_DIR` and any data/ move carry it) whenever no URL is pinned
> and no Postgres is configured; `backend()` still answers `qdrant` for both shapes
> because every operation is identical — only the client differs. The exclusive-lock
> constraint became the design: ONE serialized client per path for the life of the
> process (request threads and kernel job threads share this seam), a lock-contention
> error that names the one-writer rule, and the env name in `tests/conftest.py` the same
> commit. **Receipt:** the embedded suite runs a real upsert→ranked-search→filter→
> scroll→delete roundtrip on a temp path — no server, no port, no env var.
> **Found while joining:** THREE call sites built their own `QdrantClient` from
> `AUGHOR_QDRANT_URL` (org-intelligence list + delete, doc-chunk delete), so on any
> deployment whose index wasn't at localhost:6333 they read/deleted against a server
> holding nothing. All three now ride the seam; `scroll_points`/`delete_ids` were added
> to it (with pgvector twins) because a listed row must be addressable.
> An operator with an existing server (this repo's author included) pins
> `AUGHOR_QDRANT_URL` — the embedded default would otherwise hide those vectors.

### The original S1 case (raised by the user, 2026-08-30)

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

### 3.7 · Arc DS — the Design arc (adopted 2026-08-31; decision §6.5)

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
> - **DS-1** — P0 + served availability shipped. **P1 (the port-compatibility filter)
>   SHIPPED 2026-09-02**, verified in code 2026-09-07 (`onConnectEnd` →
>   `landPrebound` → the palette's `bindFilter`); this line claimed it open for five days
>   after the receipt was written 70 lines below.
>   **P2 (the Palette · Runs · Versions rail) IS NOT BUILT** — §5 claims it shipped the same
>   day and no rail exists; what ships is a category filter (`only=`), which is a different
>   control. Its PREMISE has also lapsed: the rail was specced "once there is more than one
>   section", and the Runs layer was retired into Activity → Phases, so there is no second
>   section to switch to. Re-spec or drop it; do not build it as written. The port-type→hue map is DEFERRED to DS-10 — no port-type
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
>   every relation. It deliberately drew **no grants spoke** while `tool_grants` was a
>   phantom; the column landed 2026-09-02, so the spoke is now buildable (unbuilt).

> **DS-1R · Canvas-first, decided by the user 2026-09-02 and SHIPPED same day** — *"the
> actual workflow should be the primary driver.. Design may read from the actual
> workflow.. while creating the automation itself, the workflow screen should be the
> starting point.. a blank canvas with only the trigger node placed by default."* Measured
> against the code, the complaint was exact: the VA-12 rail and the canvas were two
> synchronized FULL editors of one draft, and the rail (340px, permanent) predated the
> node faces growing real editors. What shipped: the rail and the create/edit form are
> RETIRED · the canvas is full-bleed under ONE header strip (identity · mode · dirty ·
> Discard · Dry run · Save · Run now) · the rail's richer widgets survive as a
> **StepInspector** — a lens that opens on the SELECTED node only (trigger ⇒ the WHEN
> editor, step ⇒ that step's widgets) · **+ New automation lands on a blank canvas with
> the trigger node pre-placed**, name edited in the header, Save = create (`POST
> /automations/dry-run` already took unsaved chains, so Dry run works before the record
> exists) · a DS-15 proposal now seeds the CANVAS, not a form — closing that wave's
> "left open". Token-ratchet baseline 1180→1176 (the dead form paid it).

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
- ~~**P1 — the killer interaction, the port-compatibility filter**~~ — **SHIPPED
  2026-09-02**, straight into DS-1R's canvas-first shape. `onConnectEnd` (a gives port
  released over nothing) opens the palette filtered to consumers, a banner names the
  offered value with ×-to-clear, and the chosen entry lands at the RELEASE POINT wired
  through `landPrebound` — which runs `applyConnect`, never beside it, so the pre-bind
  obeys exactly the hand-drag refusals. An `out:*` drop appends unbound and parks the
  connection for DS-4's key picker. Triggers are out by construction (the "one trigger
  node" constraint surfaced as the filter); the three-key sort landed as priority →
  match-place (label-prefix < label < description) → name. The law is pure and
  jsdom-tested because the gesture is not drivable there (nor by the browser tool —
  4× measured); the drag itself is the one manual receipt.
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

> **First half SHIPPED 2026-09-01 — the VA-11 consumer. The VA-9d half's FIRST SLICE
> shipped 2026-09-02** (the posture conversation happened on 2026-09-01, §6.3): an
> allowlisted server's read-only tools are discovered, classified, served as `remote_tool`
> components and callable as an `mcp_call` step through `govern.outbound`. What is still
> open is the WRITE slice and the UI — receipts and left-opens in §3.1.
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
> **A write the gate stops is a QUESTION, not a fact** — the one verdict in the call seam
> a person can answer — so it comes back as its own `needs_approval` rather than as one of
> the refusals beside it, and the automation plane parks the run on a human. **Shipped in
> the same session as DS-11's completion** (below); the first half had left it as a
> terminal refusal because the inbox knew one proposal kind.
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

> **✅ DS-11 COMPLETE 2026-09-01 — the inbox learned a second proposal kind, so an
> integration write PARKS on a human instead of refusing.** The gap the first half named
> and left open, closed in the same session.
>
> **One inbox, one branch.** `staged_proposals` gained `kind` and `grant_id` (migration 3,
> numbered off the LIVE store's `user_version=2` — the repo's own rule, and the one no
> hermetic test can catch). Both columns default to what every existing row already means,
> so there is no backfill and none is needed. `connection_id` keeps meaning the WAREHOUSE
> connection in both kinds, deliberately: it is what the queue filters, groups and purges
> by, and overloading it to carry a grant would have hidden every integration proposal from
> the queue that exists to show them. The branch in `accept_proposal` sits AFTER the
> resolve-once UPDATE, because expiry, the acceptance window, first-responder-wins and the
> audit trail are properties of the QUEUE; only what the accept executes differs, which is
> the smallest seam the two kinds can meet at. A second inbox was the alternative, and this
> repo has found the same bug in that shape three times.
>
> **`approved=True` bypasses the GATE and nothing else.** The grant's verdicts, the scope
> check and the params are all re-asked on accept — the same split the governed-write
> executor makes, for its reason: a proposal can sit for days, and an approval is
> permission, never a promise that the world stood still. A revoked account is not spent
> because a human said yes.
>
> **No standing grant is minted, and the silence is SAID.** A standing grant is
> target-bound to a declared action's coerced params; the standing permission for an
> integration write is an allowlist entry on `(operation, account)`, with a door of its
> own. The inbox card drops the checkbox for this kind and names that door instead —
> offering a control that does nothing is worse than not offering one.
>
> **The defect the live run found, and the green suite had agreed with.** `accept_proposal`
> resolves the row to `accepted`, THEN performs the write, THEN records its outcome — three
> statements with a network call in the middle. The router's own resume runs after all
> three; the HEARTBEAT's sweep visits every parked run once a minute and does not. Landing
> inside that window it saw `accepted`, mapped it to `executed` (which it is) and rewrote
> the step with an EMPTY outcome — a governed write that happened, reported as one that
> produced nothing, with every later binding onto it resolving to nothing. **This is a
> DS-8-era race, not a DS-11 one**; it took a live run with a heartbeat actually ticking to
> surface, because every test resolved and resumed in one thread with nothing in between.
> `resume_run` now holds while an accepted proposal has nothing recorded yet — BOUNDED at
> 120s, because the same shape is what a process that died mid-write leaves behind and
> holding forever would strand a run in `paused`, the one state DS-8 must never produce.
>
> **Live receipt:** with the gate armed, the chain parked with `finished_at: None` and step
> 2 never dispatched; ONE row in NEEDS YOU (not the double-listing DS-8 had to fix), and
> one card in the Inbox reading "slack.chat.postMessage · as slack · Aughor HQ" over the
> RESOLVED params (`text: 3`, step 1's count — RC-3 freezes values, never references).
> Accepting IN THE UI resumed the SAME run id to `fired` with both steps executed and the
> resumed step publishing the write's real `{ts, channel}`. The audit ledger carries the
> three rows the story needs: `blocked` by the automation, `approved` by the operator,
> `executed` by the operator.

**DS-12 · Ontology components — the moat.** Metrics, entities, cohorts and trusted queries
as first-class typed nodes: "Revenue (metric)" publishes a typed series; "Churned accounts
(cohort)" publishes a LIST a `for_each` fans over — closing §3.2's honest limit that
nothing in the plane publishes lists. The component class no canvas competitor can copy
without a semantic layer. **Receipt:** fan over a cohort and post one message per at-risk
account, the cohort's definition one click away.

> **Shipped 2026-09-01 — and the plan was wrong about its headline.** The premise was
> measured before a line was written, the way DS-10's was. Metrics are real
> (`semantic.MetricDefinition`, governed draft→approved, owner and thresholds); entities
> are real (`OntologyEntity`, grain-verified tables); trusted queries are real
> (`semantic.TrustedQuery`, stored and vetted). **Cohorts do not exist.** Every `cohort`
> in the tree is a regex in a classifier, a word in a prompt, a demo string or a
> SQL-alias blocklist entry — no model, no store, no id. So the wave shipped on what is
> real, and the LIST that closes §3.2 comes from the trusted query, whose rows are
> already a governed, reviewed row-set. A first-class Cohort object remains available as
> its own wave if one is ever wanted; "churned accounts" is expressible today as a
> trusted query, and inventing a second object to say the same thing would be the second
> roster DS-10 exists to refuse.
>
> **Two kinds, and neither carries SQL.** `metric_value` names a metric; `trusted_query`
> names a query id. That is the moat in one sentence: the number a chain acts on is the
> one the registry DEFINES — filters, caveats and all — rather than one an author typed
> or a model re-derived, and gaining row-lists cost the plane no expression surface at
> all. The metric read is SCOPED to the automation's connection, because a
> connection-scoped definition SHADOWS the global one of the same name; an unscoped read
> computes the wrong "revenue" on a connection that deliberately redefined it, which the
> suite now pins (600 vs 650 on the same fixture).
>
> **The substrate had to be repaired first, and it was broken in public.** Both
> metric-evaluation paths in `routers/metrics.py` called `db.execute(query)` against a
> signature that has always been `execute(hypothesis_id, sql)`. Each swallowed the
> TypeError into a field that reads as a data problem — `value: null` with a note on the
> value route, `status: "unknown"` on the health scorecard — so **the governed metric
> value had never once been computed**, including through the MCP tool whose docstring
> promises "the exact governed number, not an LLM re-derivation". Measured live before
> the fix, and live after. The two copies also disagreed about WHAT to compute: one
> applied the metric's declared filters, the other ran the bare aggregate. There is now
> one builder and one runner, in `semantic/metrics.py` beside the definition they read.
>
> **Also repaired in passing:** `semantic/trusted_queries.py` was the last authored store
> here with a hardcoded path, so a test that saved one wrote to the live
> `data/trusted_queries.json`. `AUGHOR_TRUSTED_QUERIES_PATH` and its conftest redirect
> landed in the SAME commit the automations plane started reading it — the rule this repo
> bought with a suite run that destroyed real content.
>
> **Live receipt:** a real chain on `workspace` ran both steps — `trusted_query` executed
> and published `{"rows": [{"total_orders": "112439"}], "columns": [...], "count": 1}`;
> `metric_value` FAILED with "Revenue could not be computed: Binder Error", because the
> two seeded metrics name a schema no connection on this install has. That second half is
> the honest one: a governed number that cannot be computed here now says so with the
> engine's own words instead of reporting null. The registry serves `metric` (2) and
> `trusted_query` (11) as new deployment-shaped families, and the palette lights or dims
> each row per connection.
>
> **Left open:** a metric publishes a SCALAR — the by-dimension series DS-12 imagined
> needs a group-by the governed query builder does not have, and is deliberately a later
> wave. Entities are served by neither kind: an entity node with no evaluation is a
> label, and building a row query from `identity_key` + `active_filter` would be a new
> SQL surface next door to the vetted one this wave just made available.

**DS-13 · Declarative custom components.** Extension WITHOUT `exec()`: an HTTP-template
component (endpoint · schema-typed input/output · secrets from the vault · dispatched
through `govern.outbound`) plus pack-shipped component bundles via the skills/packs plane
(VA-1's draft→promote gate). The direct answer to Langflow's defining liability — their
"New Custom Component" opens a Python editor; ours opens this form. Also the home of the
useful sliver of their catalog: `http_request` · `url_fetch` · `web_search` (a real gap in
our tool roster today) · file parsing. **Receipt:** a user adds a PagerDuty component from
a form, never writes Python, and the approval gate still owns its writes.

> **Shipped 2026-09-01, and mostly by NOT building it.** The premise was measured first
> and the substrate was already here: a declared action carries typed params, submission
> criteria, a risk tier and the graduated approval gate; `PUT /ontology/kinetic-actions/{id}`
> is already the form's write path behind `ONTOLOGY_EDIT`; `is_safe_webhook_url` already
> guards SSRF; and `exec`/`eval` appear NOWHERE in `aughor/`, so the no-code-injection law
> was already true rather than newly promised. Building a separate "custom component"
> object with its own store and its own gate would have been the second policy authority
> §3.4 refuses in one line.
>
> **So DS-13 is a fourth side-effect kind, `http`** — method, url, headers, an encrypted
> auth header and a body TEMPLATE, filled and never evaluated. The existing `webhook` kind
> posts AUGHOR's envelope (`{action, kind, params, config}`) to a URL, which is right for a
> receiver written for us and useless for one that was not: PagerDuty wants PagerDuty's
> body. A custom component's writes are governed the day it is authored, because it
> inherits the plane it was added to.
>
> **Three guards, each for a failure a plausible version ships.** The SSRF check runs on
> the FILLED url — guarding the template would approve `https://api.vendor.com/{path}` and
> then send the request wherever `path` said, which is a guard-shaped comment. URL params
> are percent-encoded, so a value carrying `/` cannot reshape the path it lands in.
> Substitution is TOTAL: only declared params may appear, and an unknown placeholder is an
> authoring error rather than a brace shipped to a vendor.
>
> **The credential is Fernet at rest and masked on the way out.** It matters more here than
> anywhere else this platform holds a secret, because an ontology override is a FILE and
> files here are tracked — ciphertext under `AUGHOR_SECRET_KEY` is what makes a declared
> PagerDuty component safe to commit beside the entity it belongs to. Masked rather than
> dropped, unlike a `Connection`'s tokens: this feeds an EDIT form, and a dropped field
> makes "no key" and "a key you may not see" look identical. An unchanged (masked) value
> carries the stored credential forward — the edit-form trap that otherwise replaces a key
> with bullets the next time someone fixes a typo in the description.
>
> **Fixed in passing — the fourth sender that never joined VA-9a's seam.** That wave's own
> note named `slackbots/post.py`, `slackbots/verify.py` and `notifications/executor.py` as
> emitting no span and consulting no cap, and fixed them. `actions/executor.py`'s webhook
> was missed: measured 2026-09-01, every other outbound sender in the tree imported
> `external_call` and this one did not, so a declared action's webhook fired unbudgeted,
> absent from the waterfall, and invisible to `observed_usage` — which reads session
> events, not spans. Both it and the new `http` kind go through the seam now.
>
> **Left open, deliberately.** Pack-shipped component BUNDLES are a distribution channel,
> not a component model: the packs plane already has the draft→promote gate they would
> ride, so they are a clean wave of their own rather than a second half of this one. And
> `web_search` is not a component — it is a vendor choice plus a key, which is a product
> decision; `http_request`/`url_fetch` are simply *subsumed*, because "fetch a URL" is now
> something a person declares from a form rather than something we ship code for.

**DS-14 · B3 — chains as MCP tools** (absorbs the old LATER item). An enabled automation
is exposable as a tool on our MCP server — external agents invoke it and inherit the whole
governed path, because the server already fronts the real API. A2A agent cards ride later
only if that protocol earns it. **Receipt:** Claude Desktop calls "daily-sales-report" and
the run appears in Activity like any other.

> **Shipped 2026-09-01.** An automation carries `exposed_as_tool` — OPT-IN, default off,
> and `enabled` must hold too: a chain someone deliberately switched off staying callable
> from outside would make the off switch a lie for exactly the caller nobody is watching.
> `GET /automations/tools` is what the MCP server reads at start; the eighteen static
> tools are what this VERSION can do, and these are what THIS deployment's people built,
> so they are registered dynamically rather than by a decorator that cannot know their
> names. The tool wraps `POST /automations/{id}/run` — the same route the web app's "Run
> now" presses — which is the whole claim: **the caller changes, the governance does
> not.** The chain lands in the one engine, writes the run row Activity reads, and a
> governed write inside it still parks for the approval gate rather than firing because
> the request arrived over MCP.
>
> **Three failures pinned, each of which looks correct until a tool is called.** Late
> binding — a closure built inline in the loop captures the loop variable, so every
> registered tool fires whichever automation was last (mutation-checked: `['a3','a3']`
> instead of `['a1','a3']`). Shadowing — an automation named "Ask" must not replace the
> governed `ask` path, so a colliding name is skipped, and two automations that would
> answer to one name are refused at the ROUTE with a sentence naming the fix, because two
> tools a client cannot tell apart is worse than one missing tool. And a dead API leaves
> the static tools standing: those are the ones you would use to find out why it is down.
>
> **Two defects found by driving it, neither of which a unit test could have seen.**
> `GET /automations/tools` was declared after `GET /automations/{automation_id}`, and
> FastAPI matches in declaration order — so "tools" was read as an id and the route
> answered "Automation not found". And `exposed_as_tool` was missing from
> `CreateAutomationRequest`, so the PUT accepted it, echoed it back as true, and dropped
> it on the way to the store: 200, and the flag never persisted. That is the HTTP spelling
> of the half-added-column trap the store warns about one layer down.
>
> **The field landed everywhere at once** — model, DDL, migration 5, both halves of the
> upsert, the row reader, the param builder and the request model, SEVEN places — because
> this store has twice shipped a field with a model attribute and no column, and SQLite's
> named binding ignores a key it has no column for. Migration 5 was numbered off
> `PRAGMA user_version` on the deployed database, which read 4.
>
> **Live receipt:** an MCP client sees 19 tools — the eighteen static ones plus
> `ds_6_receipt_revenue_routing`, described with its steps and the sentence that a governed
> write in it stops for a human. Reverted after; nothing on this install is exposed.
>
> **Left open:** the tool list is read once at server start, so a chain exposed afterwards
> needs a reconnect. MCP has a `tools/list_changed` notification for exactly this, and
> wiring it needs a live client to prove against — its own small wave rather than an
> untested paragraph here.

#### Phase 4 · The authoring inversion

**DS-15 · Conversation authors the canvas.** Describe the outcome in chat; the agent
proposes a chain — grounded in the ontology, the registry and THIS deployment's doors —
rendered on the Design canvas with a dry-run receipt attached; the human edits and arms
it. Creation by proposal, the same shape as every governed write here (a grant is
permission to PROPOSE). Even Langflow no longer assumes the canvas is the author (their
Assistant builds whole flows; coding agents author over MCP); ours is stronger because
proposal-first already exists. **Receipt:** "post a Monday pipeline summary to #revenue"
becomes a drawn, dry-run-proven chain awaiting one click.

> **Shipped 2026-09-01.** `POST /automations/propose` takes a sentence and a connection and
> returns a DRAFT — the same authoring payload the create form already renders — with a
> dry-run receipt attached. Nothing is saved. The draft seeds the form through its own
> prop rather than through `initial`, because `initial` means "editing a stored record"
> and the save branch keys on it: seeding through it would have made the form PUT to an id
> the draft does not have.
>
> **Three things make the draft honest rather than plausible.** It is offered only what
> THIS deployment has — the prompt is built from the same palette the canvas reads, so a
> kind the palette dims is named as unavailable WITH the reason, and the real ids (the
> Slack bots that exist, the metrics that are defined, the vetted queries that are stored)
> are listed with "never invent an id". A prompt assembled from a hand-written kind list
> would drift from the one the save enforces, and the drift shows up as a proposal that
> validates in the prompt and is refused by the code. It is refused by the SAME code a
> save is refused by — the draft is constructed as an `Automation`, so every model
> validator and `validate_chain` runs, and a chain the Save button would reject is never
> drawn: that looks like work which is nearly done. And it fails CLOSED —
> `actions/propose.py` fails open to `[]` because proposing an action garnishes an answer
> somebody already asked for, whereas here the proposal IS the request, so a silent empty
> would answer "nothing" to "build me a chain".
>
> **The draft carries no armed state.** No `enabled`, no `exposed_as_tool`, no id. A
> proposal that arrived already armed — or already exposed as an MCP tool (DS-14, three
> hours earlier) — would have made the decision the human is being asked to make.
>
> **Every test injects its provider.** This repo has already paid once for a suite that
> reached a live model, so the rule is structural: `propose_chain` takes the provider as an
> argument and resolves the default only when nobody passed one. An empty outcome is
> refused before the model is reached at all, which is also the one live check that costs
> nothing.
>
> **The one live call earned its cost.** Asked for "every Monday morning, check how revenue
> is doing and post a short summary to Slack", the model drafted a correct chain — a Monday
> cron, the governed `revenue` metric through DS-12's `metric_value`, an investigate, and a
> `slack_post` naming a REAL bot id rather than an invented one — and got the BINDINGS
> wrong in a way nothing could refuse: it wrote `"{\"$from\": \"step.key\"}"`, a STRING
> holding the JSON of a binding. A string is a legal literal, so `validate_chain` passed
> it, the dry run was clean, and the chain would have posted those characters to Slack. A
> well-formed wrong answer, which §7 already ranks below an exception. Two fixes: the
> prompt now shows the correct and incorrect shapes side by side, and a repair pass
> un-stringifies an EXACT single-key `$from` object. A binding embedded in a SENTENCE is
> deliberately left alone — the engine cannot interpolate one, so guessing at the author's
> meaning would swap a visible mistake for an invisible one.
>
> **Left open:** the proposal seeds the FORM, not the Design canvas — the canvas renders a
> stored automation, and giving it an unsaved one is its own change. The receipt's "drawn"
> half is therefore the form plus the dry-run summary rather than nodes on a canvas.

~~**DS-16 · The migration funnel.**~~ — **SHIPPED 2026-09-02.** `import_flow.py` +
`POST /automations/import` + an Import flow… door beside Propose. The structural fact the
wave turns on: **every Langflow node carries its component's source in a `code` template
field** (their engine exec()s it) — so the importer reads DECLARATIONS only, from an
explicit allowlist table (their format migrates upstream; a table is what the quarterly
release-tracking pass diffs). Model/agent nodes → `investigate` on the governed answer
path (a pinned model id is DROPPED by name — model routing is the deployment's, never a
flow file's); an Agent's system prompt arrives as a SUGGESTED agent record, never
created; Prompt text folds into the downstream question; LLM→Slack edges become
`{"$from": "<step>.summary"}` — the briefing's own binding; ChatInput/Output drop as
conversation plumbing; code and open-HTTP nodes are REFUSED naming the law and the
DS-13 declarative alternative. Validation constructs the real Automation with one honest
carve-out: pydantic SKIPS the chain validator when a field fails, so deployment-specific
holes (bot_id) are placeholder-filled for a second structural pass and returned as
`to_fill` — the create form's incomplete gate collects them; structural failures still
fail CLOSED. The REPORT renders BEFORE the canvas (the refusals are half the receipt).
**Receipt, live 2026-09-02:** a six-node starter flow → report (dropped/folded/mapped/
refused, each with its sentence) → seeded canvas: Trigger → Investigate → Post to Slack
with the summary edge drawn, Create gated on "Action 2 needs bot_id", nothing saved.
Archived-Flowise exports read through the same table.

~~**DS-17 · Deploy is a menu of doors.**~~ — **SHIPPED 2026-09-02.** One Deploy control on
the canvas enumerating what THIS deployment can open — schedule · webhook (new) · Slack
(RC-5) · MCP tool (DS-14). `automations/doors.py` + `GET /automations/{id}/doors`, with the
verbs on routes beside it: `/enabled`, a new `/exposed` sibling, and the webhook token's
issue/revoke. Reading the menu opens nothing.

> **The contract is the palette's plus one axis, and that axis is the product.** The palette
> answers *can this be placed here* (`ready | needs_setup | unavailable`); a door also has a
> POSITION, so `ready` splits into **`open`** (traffic comes through now) and **`closed`**
> (everything is in place, one gesture away). A reader looking at a finished chain wants to
> know which of those two they are looking at, and three states cannot say. `closed` is
> deliberately not an error hue either — nothing is wrong with a door nobody has opened.
>
> **The alt-door rule turned out to live in the WORDS, not the shape.** Both places it bites
> were bought by earlier waves. The **clock** is not always a thread: on serverless the
> in-process heartbeat is off by design and an external cron drives `/cron/tick`, so a door
> that looked for the thread would tell a Vercel deployment its schedules are dead while they
> fire every minute — hence `scheduler.clock()`, which also reports the state nothing else in
> the product reports (no clock running at all, because `start()` swallows its own failure as
> non-fatal). And **Slack is not OAuth here**: Slack rejects `http://localhost` callbacks, so
> the sentence names the manifest path — Socket Mode, an outbound socket, no tunnel. The test
> for that asserts the sentence contains "socket mode" and *not* "oauth", because a door
> reading "connect via OAuth" is correctly SHAPED and points a self-hosted install at a door
> that will not open for it.
>
> **The webhook trigger is the fifth kind, and its config is empty on purpose.** Every other
> trigger is configured by NAMING something (a cron, a monitor, a table); a webhook is
> configured by ISSUING A URL — a deployment act, behind the door. So the step is complete the
> moment it is placed, and a chain that has one but no URL is a chain whose door is shut. Its
> probe reads the RUN rather than the world, because the engine cannot look at the warehouse
> and learn that someone called a URL: it is `manual`, exactly as `schedule` is, which is why
> Run now fires a webhook chain and a heartbeat tick does not.
>
> **Three refusals the security shape rests on.** The token is refused for a chain with no
> webhook trigger — `manual` bypasses the cron by design, so a token on a schedule-only chain
> would be an unauthenticated "run this scheduled job now" button, and the trigger on the
> canvas IS the author's consent to being called (checked at issue AND at call, because a
> route is the boundary and a trigger can be removed afterwards). The **body is ignored** —
> a payload from the public internet must not reach a step's config, which is the
> request-forgery shape §3.4 already refuses for `connection_call`. And every credential
> failure returns ONE sentence, or the route is an oracle for which automation ids exist.
>
> **Its own prefix, `/hooks/{id}`, because `_AUTH_EXEMPT` matches by `startswith`.** Hanging
> the public door under `/automations/` would have exempted every read, write and delete on
> that surface along with it. It is the only exempt entry that DOES something rather than
> reporting something, and it carries a strictly narrower grant than the shared key it is
> exempt from: one chain, through the same lifecycle gates as Run now.
>
> **Receipt, live 2026-09-02** (a real chain on theLook, deleted after): created not-live →
> `Not live`, four doors each with its sentence → `/enabled` + `/exposed` → **`Live on 2
> doors`**, and `GET /automations/tools` really offered `ds_17_receipt_deploy_as_doors` → URL
> issued → `Live on 3 doors`, with the token absent from the doors response → an
> unauthenticated `POST /hooks/{id}` **fired the chain** (`webhook: called`), while no token,
> a wrong token and an unknown id all returned the same 401 sentence → rotate invalidated the
> old token → revoke returned the door to `closed`. The best line came from the heartbeat a
> minute later: `not_fired — webhook: waiting to be called`, which is the probe's whole design
> stated by the system rather than by a test.
>
> **Two defects found by driving it, neither visible to a unit test.** A webhook call on a
> chain that also had a cron logged `schedule(0 9 * * *): called` — nobody called the
> schedule; what happened to it is that it was not consulted, so the `via` map split in two.
> And deleting a chain left its token row behind, so the DELETE cascade that already purges
> grants and proposals now purges the credential too.
>
> **Swept in passing:** `scripts/dump_openapi.py` isolated only `AUGHOR_*_DB` names, so a
> store keyed on a DIRECTORY had no pin at all during `npm run gen:api`. Measured before
> claiming it: no directory store writes during a spec dump today (reproduced with the old
> shape — the stray `data/qdrant/` of 2026-09-02 was NOT this script), so it closes a latent
> hole rather than a bleeding one. `tests/conftest.py` and this list are siblings now.
>
> **Left open:** the MCP tool list is read once at MCP server start, so a chain exposed from
> this menu needs a client reconnect — the door says so in its own sentence rather than
> leaving an operator to debug a client behaving exactly as designed. `tools/list_changed` is
> the fix and still wants a live client to prove against (DS-14's own left-open, unchanged).

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

### 3.8 · Canvas parity — the primitive gap, and why our nodes drag badly

Both halves of this band came out of one comparison against Langflow on 2026-09-03, prompted
by the user. §4.2's refusal is untouched: this is **palette parity and canvas feel**, the
"standing upkeep" §4.2 already asks for, not a re-proposal of their codebase.

#### 3.8a · The primitive gap — MEASURED, not estimated

Counted from **their repo** (`docs/docs/Components/*.mdx`), because docs.langflow.org renders
client-side and returns an empty body to a fetch — a page that looks present and answers
nothing is the measurement trap this document keeps paying for.

| | Langflow | Aughor |
|---|---|---|
| Core component pages | **43** (34 real + 9 index pages) | — |
| Vendor **bundles** | **76** | — |
| Droppable palette entries | ~34 | **15** (5 triggers + 10 actions) |

**The raw gap is the wrong number and must not be quoted on its own.** 76 of their ~110 pages
are vendor bundles — OpenAI, Anthropic, Chroma, Composio, Docling. That is the job our
`connector` + `integration` families already do, and ours are **deployment-shaped**: membership
is what this install has connected, not what the version ships. Counting those as missing
components counts our architecture as a deficit.

**The real gap is general dataflow primitives**, and it is worth having a position on each
rather than a backlog. ⚠️ **One line of this list was already wrong within hours of being
written** — see the struck control-flow entry. Re-measure before building from it, including
when the author was me:

- ~~**Control flow** — `If-Else`, `Smart Router`.~~ **THIS CLAIM WAS FALSE, and it was written
  in this very section hours earlier. Re-measured 2026-09-03: we already have it.** DS-6's
  `else_of` IS the branch — a step declares itself the *Otherwise* arm of a sibling's guard,
  the target is validated at save (must exist, run earlier, carry a guard), it draws as one
  labelled edge, and the two arms are **complementary by construction** because one guard is
  read from both sides. An unevaluable guard takes NEITHER arm rather than guessing. Chaining
  `else_of` gives the else-if ladder a Smart Router is. What we express as *guard + Otherwise*
  Langflow expresses as a *router node*; that is a rendering difference, not a missing
  primitive.
  🔑 **Fourth instance this week of a resolved item reading as open — and the first one I
  authored myself, the same day.** Writing a gap analysis is not exempt from "measure the
  premise": I read the palette, saw no `if_else` row, and wrote the conclusion without
  checking whether the capability lived on the step instead of in the roster.
- ✅ **Data shaping — SHIPPED 2026-09-03 as `$as` on the binding**, the user's call between a
  transform STEP and a formatter on the wire. `{"$from": "rows.count", "$as": "text"}`.
  Verified absent first (`dataflow.resolve` returned `produced[key]` and nothing else), so
  this is the one half of §3.8a that survived re-measurement.
  **A closed set, not an expression**: `text · json · number · integer · boolean · count ·
  first · last`. DS-16 refuses code nodes by law and the same reasoning applies one plane
  down — an expression language here would be a second place values are computed, outside
  every guard that governs the first. An unknown name is refused at SAVE with the whole set
  in the sentence.
  🔑 **Every conversion that cannot be made honestly RAISES rather than producing a plausible
  value** — `resolve`'s own law ("a default would let a step run with a silently wrong value,
  and these steps send messages and write to systems") applied to the conversion instead of
  the lookup. `integer` refuses `2.9` rather than truncating; `boolean` refuses `maybe` rather
  than using truthiness (`""` and `"false"` are both falsey and only one means false);
  `first` refuses an empty list rather than yielding None. `UncastableBinding` SUBCLASSES
  `UnresolvedBinding`, so every caller that already skips a step skips this one unchanged.
  🔴 **The client mirrored the same rule in the same commit.** `automationFlow.ts` read
  bindings with `keys.length === 1`, so without it a cast-carrying binding would not have
  been wiring at all — edge gone from the canvas, field rendered as a raw object, for a chain
  the server considers valid. A rule mirrored on one side only is a rule that disagrees with
  itself.
  ✅ **DISCOVERABLE 2026-09-04.** `$as` shipped supported on both sides and **named on
  neither surface** — the server honoured it, the client parsed it, and nothing told anyone
  it existed or which words it takes. A capability reachable only by reading the source is
  one nobody reaches. The cast vocabulary is now exported from `lib/automationFlow` and
  stated on the bindable inputs, with a **cross-language test that reads BOTH the TS list
  and `dataflow.py` and asserts they match** — the drift that file's own comment warns about
  ("a rule mirrored on one side only is a rule that disagrees with itself") now fails a test
  instead of surfacing as a cast the server refuses.
  ✅ **PICKER SHIPPED 2026-09-04.** `BindingCast` renders a cast selector beside a bindable
  field — and **nothing at all** when the field holds a plain value, which is what lets it
  sit next to a free-text input without cluttering the majority of fields that will never
  carry a binding. Wired to `slack_post`'s message and channel and to every param an
  operation DECLARES bindable (offering a conversion on a param that cannot hold a binding
  would advertise wiring the server refuses). Clearing it **deletes** `$as` rather than
  setting `""`: `CASTS` has no empty member and `wearsMarker` accepts `$from` plus at most
  `$as`, so an empty string would be a third state — read as wiring by the client and
  refused as a conversion by the server. That property has its own test, verified to fail
  against the naive implementation.
  The cast is therefore reachable from the binding chip itself, not only through the API and
  the DS-16 import funnel — which is what closes this item. The arc's recurring failure it
  was named against (a complete and inert plane) does not apply once the control is where
  the value is edited.
- **File I/O** — `Read File`, `Write File`, `File System`.
- **LLM as a component** — `Language Model`, `Embedding Model`, `Prompt Template`,
  `LLM Selector`. We have the whole plane; it is not droppable, it lives inside
  `investigate`/`brief`. Exposing it is a posture question, not a build: a droppable raw LLM
  step is an ungoverned generation path, which is the §4.2 structural objection in miniature.
- **Misc** — `Calculator`, `Current Date`, `Notify/Listen`.

**Already ours under other names** (do not build twice): `Run Flow`=`subchain` ·
`Batch Run`=W2 for-each · `MCP Tools`=`mcp_call` · `Human Input`≈DS-8 durable pause ·
`Guardrails`/`Policies`≈the govern plane · `Knowledge Base`/`Message History`≈semantic + KB.

**REFUSED outright:** `Python Interpreter`. DS-16 already refuses code nodes by law, and a
palette entry that executes arbitrary Python is the write-path-outside-`govern/` objection
§4.2 closes on.

#### 3.8b · Why our nodes drag badly — ROOT-CAUSED 2026-09-03

**`AutomationGraph.tsx` passes `nodes={design.nodes}` to ReactFlow with no `onNodesChange`.**
That breaks the controlled-mode contract: position changes never flow back to our array, and
are committed only at `onNodeDragStop`. Any parent re-render mid-drag regenerates the node
array from the *stale* `positions` state.

🔑 **The tell was already in our own code, read as a library quirk.** The DS-4 comment at
`AutomationGraph.tsx:1161` says the library *"reports its measurements only through
`onNodesChange`, which this canvas never receives (probed: it does not fire here at all)"*. It
does not fire **because it was never passed**. A missing prop was diagnosed as a library
limitation and worked around by measuring the DOM per render — and that workaround is itself a
jank source: a dependency-less `useEffect` reading `offsetWidth`/`offsetHeight` for every
`.react-flow__node` on every render plus a rAF, which forces synchronous layout.

Three supporting measurements:
- **`GraphCanvas.tsx` wires `onNodesChange` (3 hits). `AutomationGraph.tsx` — the authoring
  canvas people actually drag on — has zero.** `AgentMap.tsx` has `nodesDraggable` and no
  handler: the same defect, second site.
- **Zero `memo(` across all five of our canvas files.** Langflow memoises six sub-components
  inside `GenericNode` alone (`RenderInputParameters`, `NodeIcon`, `NodeName`,
  `CustomNodeStatus`, `NodeDescription`, `NodeOutputs`).
- Langflow's `flowStore.ts:422` is the textbook pattern:
  `onNodesChange: (changes) => ({ nodes: applyNodeChanges(changes, get().nodes) })`.

Even adding `React.memo` first would not help: each node's `data` is rebuilt with fresh
closures (`onPatch`, `onClear`, `onDuplicate`) every time the `design` memo re-runs, so props
always differ. **Order matters — wire the change channel, stabilise `data`, then memoise.**

**The fix pays twice:** once `onNodesChange` is live, measurements arrive through the channel
the DS-4 comment wished for, and that DOM-measuring workaround can likely be deleted outright.

⚠️ **Not yet reproduced empirically.** The browser tool cannot drive ReactFlow pointer
interactions (measured 4×), so this is a code-level diagnosis. A React Profiler trace during a
drag would show the re-render storm directly, and is the receipt to get before claiming the fix
worked.

### 3.9 · Arc MI — the Machine-Intelligence arc (adopted 2026-09-03; decisions §6.7 · §6.8)

> **Origin.** The user's 2026-09-02 directive: *"a never-ending learning process through
> which models can be made smarter as more and more users start using the platform…
> smaller LLMs will themselves act like specific engines for specific agents… micro LLMs
> will be the new agents… start recording the learnings from each and every activity that
> goes on in the platform and turn it into Machine intelligence."* The same-day audit
> (both TangleML repos read end-to-end, nothing executed; every recording surface in
> `aughor/` inventoried with file:line receipts; the retention, prompt-window and
> trace-input claims re-verified by hand) reframed the ask: **capture is already rich;
> grading, keeping and exporting are the gaps.** The case, the scenario storyboards and
> the NVIDIA-RL read live in the session memo (artifacts `35b2c8fa` / `b387d309`, memory
> `arc-mi-flywheel-and-tangleml-verdict`); everything load-bearing is restated here so
> this section stands alone.
>
> **The thesis, corrected where measurement disagrees.** Frontier per-token prices have
> historically fallen — but the constraints *measured here* are request RATE (the real
> ceiling — see Transport), hourly `:free` provider-health flips the failover chain
> silently absorbs, latency on high-volume narrow calls, and payload custody (a local
> model is the only inference that never leaves the box). Micro models relieve all four.
> The economics that makes "micro-LLMs as the agents" real is **one small base, N LoRA
> adapters** — an agent's specialization is megabytes, hot-swapped over a shared 1–8B
> base. And the moat compounds: §0's ontology→agent loop gains a second loop around it,
> **experience→model** — a student trained on OUR schemas, OUR ontology definitions and
> OUR corrections beats any generic corpus at being this platform. §7's law generalizes:
> a capability ships when something consumes it; **data ships when something GRADES it.**
> Ungraded logs are exhaust. Graded logs are training sets. The models are how the
> ledger's capital gets spent; models depreciate, the graded ledger compounds.

**Laws that bind every MI wave (standing, not per-slice):**

- **The lawful lane first.** Nothing trains on payloads outside §6.7's TRAINING ANNEX
  (✅ decided 2026-09-03): an org-level opt-in carrying a retention class, a purpose
  tag, and PII scrub at export. §6.4's reading half (2026-09-02) governs an admin's
  eyes; the annex governs machine consumption — two different acts, each with its own
  law. The NL2SQL loop needs neither: question, SQL, outcome and human verdicts are
  already durable work artifacts — which is why it goes first.
- **A verdict pins its evidence.** Graded runs become permanent; ungraded exhaust keeps
  expiring on the 14-day sweep. Retention follows grading, not the other way round.
- **Reward integrity precedes optimization.** Before any training consumes a signal,
  hand-audit the verifier against 50–100 real outputs. A guard hole is a policy exploit
  waiting to be learned (`E1-quoted-identifier`, found 2026-09-02, is the live class:
  "Guards clean" over an always-false predicate). Good rewards measure the real task,
  are hard to game, and fail visibly when wrong.
- **The ratchet gates every promotion.** A model/adapter version ships only when it meets
  baseline on the held-out golden set with no regression on safety, latency or cost —
  the eval plane's graduation law extended to weights. Every escalation the cascade
  takes is automatically next version's most valuable training row.
- **No model id in `aughor/`** (standing law, unchanged). Serving rides the provider
  chain as config; local inference rides library runtimes (Ollama / llama.cpp / vLLM),
  never a hand-rolled one. The cascade is the failover seam pointed at economics.
- **Store hygiene, paid for repeatedly:** a new store's env name lands in
  `tests/conftest.py` AND `scripts/dump_openapi.py` in the same commit (a dir-keyed
  store needs the directory family too — paid again 2026-09-02) · one writer per
  `data/` · migrations numbered off the LIVE `PRAGMA user_version`, per-statement
  execute, portable SQL only.
- **The ledger is in the box; weights never are.** Every deployment shape keeps full
  function: laptop installs may open a local-model door; serverless points the same
  binding at a remote endpoint; the repo and installer carry zero weights.
- **Catalogue-timestamp discipline.** The measured facts below are dated 2026-09-02.
  Re-measure before building on them — this ledger has been stale the same evening it
  was written before.

**What is true today (measured 2026-09-02, file:line receipts in the audit):**

- **Guard verdicts are computed and never persisted** — `sql/trust_checks.py` returns
  `E1-*` issues; `emit_guard_receipt` fans out to SSE + a ContextVar only. The best
  free supervision signal on the platform is discarded at birth. (`eval_run_results.fired`
  proves the column shape is already understood — it exists only on the eval path.)
- **`session_events` expires in 14 days** (`AUGHOR_SESSION_LOG_KEEP_DAYS=14`,
  `obs/session_log.py:698`) while `finding_verdicts`, `staged_proposals` and
  `evidence_claims` are unbounded — a late verdict's join target is already deleted.
- ~~**Attribution is dead on arrival**~~ — **RE-MEASURED 2026-09-03, and it was wrong in
  both halves.** `agent_id` is at **639 of 10,782** rows across seven kinds, flowing since
  2026-08-30: VA-9b's plumbing works and the earlier count was taken before it landed.
  `user_id` is genuinely 0 of 10,782 — but not for want of wiring. `session_log.emit`
  already reads all three ids ambiently from contextvars (`telemetry.py:388`), so there is
  nothing to thread; `user_id` is empty because `AUGHOR_REQUIRE_IDENTITY` is **off by
  default** (localhost mode) and the identity middleware no-ops. Making it non-empty is
  multi-user work — **§3.5 VA-10's band, not MI-1's**. `investigations.py:5528` had already
  written the diagnosis down: *the machinery was reading a value nobody set.*
- **`automation_runs` cannot reach the LLM calls it caused** — no `trace_id`; and its
  INSERT drops the model's existing `agent_id` (the half-added-field class, again).
- **Feedback is split and invisible:** `chat.feedback` keys on turn_id, `trace.feedback`
  on trace_id; neither is in `KIND_CATEGORY`, so neither reaches the governance feed.
- **The strong verdict surfaces already exist** — *as SCHEMA; re-measured 2026-09-03 and
  the contents are the story.* `finding_verdicts` (accept · correct · reject, with a
  `corrected_sql` column) held **5 rows on the live deployment: 2 accept, 1 correct, 2
  reject — and ZERO carrying `sql_source` or `corrected_sql`.** "Ready-made preference
  pairs" described a column, not its contents; the true count of usable DPO pairs was
  **0**. A catalogue is a proxy for the thing (×7). The funnel, not the schema, is the
  constraint: the fix-it chain is wired end to end from chat (`ChatMessage.tsx:1208` passes
  both fields) but **`ExplorationReport.tsx:196` and `TraceExplorerPanel.tsx:192` call
  `recordVerdict` without them**, so verdicts from the exploration report — plausibly the
  highest-volume surface — can never become training pairs however diligently anyone
  grades. **Two call sites, and worth more per line than the exporters.**
  ✅ **FIXED 2026-09-04.** Both surfaces now send the structural payload, and the trace
  explorer gained the corrected-SQL field it needed to produce a preference pair at all
  (without it, that surface could only ever yield accepts). The selection rule lives in
  `web/lib/verdictSql.ts` because it must be IDENTICAL wherever a verdict is recorded, and
  it is deliberately conservative: **attribute only when exactly one statement could be
  meant.** A chain whose headline synthesises several queries has no single statement its
  finding rests on, and naming the last would be a fabricated attribution — a wrong
  training pair teaches a falsehood with full confidence, which is worse than a missing
  one. §3.9's reward-integrity law is about the corpus, not only the grader. Distinct
  statements are counted rather than events, so a retried identical query stays
  attributable. 8 unit tests on the rule itself. · `staged_proposals`
  (accepted · rejected · executed · failed, resolver named) · `evidence_claims`
  (validated · disputed, downstream fate) · `guardrail` events (allow AND block) ·
  `automation_runs` (fired · not_fired · gated · error · paused, no-ops included) ·
  the eval plane + git-sha'd ratchet baselines · `audit_log` (every executed SQL:
  full text, row_count, duration, error, trace_id).
- **Reasoning traces already exist ungraded:** `episodes_*.jsonl` (think → SQL →
  observation) — the closest thing to training data the runtime writes today.
- **Payload custody is deliberate and uniform** — prompts/completions reach no durable
  sink and no export unless an operator opens the self-expiring capture window
  (default 20 calls / 15 min, caps 200 / 120, 2,000-char cap, reads audited via
  `trace.payload_access`). **One exception, found by reading:** `new_trace()` puts the
  user's *question* on the OTLP wire (`langfuse.trace.input`) regardless of the window.

#### MI-0 · The custody law: the training annex — ✅ DECIDED 2026-09-03 (§6.7); ✅ GATE SHIPPED 2026-09-03

The decision half landed with §6.7: **payloads are trainable only under an org-level
opt-in carrying a retention class, a purpose tag, and PII scrub at export; work
artifacts (questions, SQL, result summaries, verdicts) are lawful training inputs,
org-scoped by default.** (§6.4's 2026-09-02 reading half governs an admin's eyes; this
annex governs machine consumption — deliberately separate acts.) What remains of MI-0
is its one piece of code: `langfuse.trace.input`'s question attribute — an *export*,
not a read, so no break-glass ever fires on it today — must obey the same custody
classes, with a test.
**Receipt:** §6.7's dated stamp (✅ landed); the trace-input gate ✅ shipped with MI-1's
wave — `telemetry._trace_input` keeps `connection_id` unconditionally (§6.4 makes metadata
free) and attaches the question only inside an open capture window, failing safe to "no
capture" when the window cannot be read. It deliberately does NOT `consume()` that budget:
the budget is denominated in captured MODEL CALLS, and spending it per trace would make an
operator's "20 calls" mean something different depending on how many runs happened to
start.

#### MI-1 · Grade what already runs (substrate-sized) — ✅ SHIPPED 2026-09-03

> **Three of this band's four bullets survived their own pre-check; the fourth did not.**
> The guard sink, the run attribution and the feedback categorization were all real and are
> built. "Wire attribution" was struck — see the bullet below. The pre-check also turned up
> a defect the band had predicted in the abstract and got exactly right in the concrete:
> the `uncategorized_kinds` ratchet was blind *by construction*, not by omission.

> **Corrected the same day, by driving it instead of testing it.** The first cut gated the
> write on an ambient trace, reasoning by analogy with the session log's drop-trace-less-
> events law. Wrong analogy: that law is about session EVENTS, meaningless outside the run
> they describe, whereas a guard verdict is a standalone labeled example — exactly what
> MI-3 consumes. Running the live `/query/validate` proved it: the guard fired
> (`E1-quoted-identifier` on `row_id`) and persisted **nothing**. Measured on the live
> deployment: **189 audit rows that day, 28 with a trace — `bind_trace` is bound only at
> the ask door**, so the workbench and the validate endpoint carry none. The gate would
> have discarded ~85% of the signal in the slice whose whole purpose is to stop discarding
> it. Every fire is now kept, `trace_id` empty when absent, and `phase` (`execute` ·
> `validate` · `deep` · `trust_scope` · `eval`) carries the weight of separating production
> supervision from the eval plane's own cases — a dataset built from an unlabelled
> population would train on its own benchmark.

- ✅ **Persist guard verdicts at the execution chokepoint** — the one seam every connector
  and both the quick and deep paths already pass (the capability-misses-a-connector
  lesson, ×3, decides the placement). Rows `(ts, trace_id, sql_digest, pattern,
  subject, phase, org_id)` beside `audit_log` in `AUGHOR_AUDIT_DB` (an existing store:
  migration rules above apply).
- ✅ **`automation_runs` gains `trace_id`**, and the INSERT carries the `agent_id` the
  model already declares — a chain run can finally reach the `llm_call` rows it caused
  (`session_events` got `job_id`/`charter_id` in m10 precisely for this join; this is
  the reciprocal key).
- ✅ **Both feedback kinds enter `KIND_CATEGORY`** under a new `human_verdict` category —
  none of the existing four fits a thumbs, and a mapping alone renders nothing because
  `feed()` walks `_SINKS`, so both halves landed together.
  **Why the ratchet was silent, which was the more expensive half:** it hand-listed the
  emitted kinds as a literal and asserted them against the hand-maintained `KIND_CATEGORY`.
  Both sides were the same edit, so a kind nobody remembered was absent from *both* and the
  assertion passed. It failed OPEN. It now DISCOVERS its population by parsing `aughor/`
  (resolving module-level constants too — the guardrail sink emits `EVENT_KIND`, not a
  literal), and every discovered kind must be categorized or explicitly declared
  non-governance. It caught `budget.exceeded` on its first run.
  **Found by the fix, and needing a product decision:** `govern.cap`, `guardrail`,
  `metric.enforcement` and `budget.exceeded` are all governance-shaped and invisible to the
  governance feed. They are held in `GOVERNANCE_SHAPED_UNCATEGORIZED` rather than buried in
  the exclusion set, because writing "not governance" about them would record a judgment
  known to be false. Admitting them changes what a user-facing surface returns, and
  `guardrail` alone is 1,074 of the local ledger's rows — every one a PII *allow* — against
  a 500-per-sink read. Whether a high-volume allow trail belongs in a reader-facing feed is
  the user's call, not the builder's.
- ~~**Wire attribution**~~ — **struck at the pre-check (2026-09-03).** The bullet named a
  mechanism that does not exist: nothing is threaded through the emitters, because they
  read identity ambiently. Half of it already works and the other half is VA-10's (see the
  re-measured bullet above). Kept as a lesson rather than deleted: this line was written
  the day before it was struck, from a count taken the day before that.

**Receipt:** ONE live SQL query walks run → executed SQL → guard fire. Before this slice
that query could not be written; it is now
`tests/unit/test_mi1_graded_ledger.py::test_one_query_walks_run_to_executed_sql_to_guard_fire`,
and both tables share `AUGHOR_AUDIT_DB` so it is a single-store join. The human-verdict hop
is reachable but not yet joined in one statement — `finding_verdicts` lives in its own
store, which is MI-3's dataset plane, not this slice's.

#### MI-2 · A verdict pins its evidence (substrate-sized) — ✅ SHIPPED 2026-09-03

> **The pre-check found that the sweep this band protects against was not running at all.**
> `_session_events_maybe_prune` fired on an in-process counter (`_session_event_writes`,
> initialised to 0 in `Ledger.__init__`, prune every 500). The counter resets on every
> boot, so an install that restarts before accumulating 500 session-event writes in one
> process lifetime **never pruned**. Measured live: **4,186 of 10,788 rows past a 14-day
> retention — 39% of the table — the oldest 19 days**, with `session_events_prune` itself
> working perfectly and called by nothing but an eval receipt and a test — the "tested, not
> leveraged" shape, a fourth time.
>
> ⚠️ **That figure is a correction, and the first one was mine.** The probe originally said
> 1,766 because it compared `at` against `datetime('now','-14 days')`, which renders a
> SPACE separator (`2026-08-20 21:13:50`) while the stored values use `T`
> (`2026-08-20T21:13:50+00:00`). These are string comparisons: `'T'` (0x54) sorts above
> `' '` (0x20), so every row on the boundary day silently fell out of the count. The prune
> builds its cutoff with `.isoformat()` and was comparing correctly all along — the code
> was right and the measurement was wrong, which is the standing lesson, and it is the same
> family as `E1-quoted-identifier`: a string comparison wearing the costume of a temporal
> one. The live sweep deleted exactly 4,186 rows, which is what settled it.
> Retention is a **stated privacy property** that §6.4's and §6.7's custody decisions lean
> on, and it was not true. It also made this band's own receipt unprovable: "a graded run
> survives the sweep, its ungraded neighbour does not" says nothing when neither is swept.
>
> Fixed WITHOUT a new loop (§VA-6's law: periodic work joins the one that exists). The
> defect was never the missing loop — it was **volatile state driving a durable decision**.
> The amortised counter stays on the write path unchanged; the restart case is insured
> **at OPEN**, where `Ledger.__init__` consults a last-pruned stamp kept in `kv` and sweeps
> if it is stale. One read per process, not per write, and an unreadable clock fails
> *toward* pruning.
>
> **At open rather than on the first write, and the difference is not cosmetic.** The first
> draft hung the check on the first write and two existing suites caught it within the
> hour: `session_event_insert` prunes AFTER inserting, so a first write that is itself
> backdated — a back-fill, an import, a test fixture — was deleted by the very sweep its
> own arrival triggered. Opening is also simply the honest place for it: the thing being
> insured against is a process starting, not a row arriving. Best-effort and last in
> `__init__`, because a prune that raises must never be why the app cannot boot —
> Migration 10's back-fill did exactly that on Postgres.

`session_events.pinned_at` — **Migration 11**, numbered off the LIVE store's
`PRAGMA user_version` of 10 and **rehearsed on a `.backup` first** (10 → 11, column
present, 10,785 rows intact) before anything touched the real file. Portable SQL only:
this store also runs on Postgres, where Migration 10's `json_extract` back-fill once
raised inside `Ledger.__init__`. The column is projected in `_SESSION_EVENT_COLS`, not
merely stored — a reader that cannot see a pin cannot tell a kept run from one the sweep
has not reached yet.

Pinned rows are skipped by the age sweep **and do not count toward the row cap**: a graded
run is evidence, not budget, and letting pins consume the newest-N window would mean
grading enough runs quietly starved the log of everything else.

**All four verdict doors pin — the fourth caught up 2026-09-04.**
`finding_verdicts` (by investigation_id), `chat.feedback` (its `turn_id` IS an
investigation id) and `trace.feedback` (by trace_id) all pin at verdict time.
✅ **`staged_proposals` now has the join key it was missing (Migration 4, numbered off the
live store's `user_version` of 3 and rehearsed on a `.backup` first).** Its `run_id` is a
fresh `uuid4()` minted per tool call for idempotency and joins to `session_events` not at
all, so the proposal now carries `trace_id`, defaulted from the ambient run exactly as
`automation_runs` does — a pattern since **measured in production: 2,142 of 2,142 automation
runs written after MI-1 shipped carry a trace.** Resolution pins that trace, after the
commit and outside the lock, because the decision is the durable thing and pinning is
bookkeeping that must never cost someone their verdict.

🔑 **It pins the PROPOSAL's trace, never the resolver's** — the agent that proposed and the
human who answered are different runs, and pinning the latter would confidently preserve the
wrong rows while the evidence it was meant to keep expired on schedule. That property has
its own test.

**Receipt:** `tests/unit/test_mi2_retention_and_pinning.py` — a 15-day-old graded run
survives the sweep and its ungraded neighbour does not, in ONE test, because survival
proves nothing if nothing is being swept. Plus the restart case the counter could never
cover, both directions of the durable clock, and the row-cap exemption.

#### MI-3 · The dataset plane (Tangle's schema, our law — §4.5) — ✅ SHIPPED 2026-09-03

> **Built, and honest about what it currently exports: ~0 examples.** The plane is the
> accrual substrate (MI-5: MI-1…3 are default-ON for every install, and a fresh install
> starts accruing from its first query), so it is worth having before there is volume — but
> the exporters run over 5 verdicts today, none carrying SQL. That is the arc's own
> prediction (*capture is rich; grading is the gap*), and `gate_status()` publishes the
> measured distance to MI-4's entry gates precisely so the falsifier stays checkable.
>
> **Store:** `AUGHOR_LEARNING_DB` + `AUGHOR_DATASETS_DIR`, both registered in all THREE
> places in the same commit (code · `tests/conftest.py` · `scripts/dump_openapi.py`),
> directory family included. Three tables as ported: content-addressed `dataset_data`
> (bytes dedup by hash; `deleted_at` lets a purge remove payload while the node and its
> lineage stand), `dataset_node` (per-org versioning, `parent_id` clone lineage; identical
> content re-registers as the SAME version rather than minting one), `dataset_lineage`.
>
> **Exporters:** SFT from accepted findings, DPO from `correct` verdicts that carry an
> actual correction (a `correct` with no `corrected_sql` is a judgement without a lesson —
> including it would fabricate a preference nobody expressed), golden as a stable 1-in-10
> hold-out. The split is a content hash, NOT a shuffle: a random split would move examples
> between corpora on every export and break both determinism and the never-trained-on
> promise. PII scrub rides the existing `security/pii` seam and **fails closed**.
>
> **Consumption, not just capability:** the endpoints landed in the EXISTING
> `routers/learning.py` — the Wave 1 surface built to make the closed loop's accumulation
> visible, which is one step short of this. Scheduling is deliberately absent: periodic
> work joins the one loop that exists, and a nightly export over a two-example corpus is
> motion without progress. `gate_status()` is what says when that changes.

New store `AUGHOR_LEARNING_DB` + `AUGHOR_DATASETS_DIR` for snapshot files — the
THREE-registration law applies, same commit. The ported ideas (§4.5): content-addressed
**`dataset_data`** (hash, size, uri, created_at, deleted_at — bytes dedup by reference;
provenance survives purging the bytes) · **`dataset_node`** (name, version, task,
kind ∈ {sft, dpo, golden}, data_id, parent_id — slots and clone-lineage) ·
**`dataset_lineage`** (dataset → the runs, verdicts and guard rows that fed it).
Exporters run as kernel jobs (budget-metered, one writer, idempotent):

- **SFT pairs** from accepted findings — question + ontology/briefing context → SQL.
- **DPO pairs** from `correct` verdicts — `sql_source` rejected vs `corrected_sql`
  chosen. The platform has been collecting preference data without calling it that.
- **Golden sets** — held-out accepts across difficulty bands, registered in the evals
  plane, never trained on. `scripts/quality_sweep.py` graduates from a laptop script
  into an exporter.

PII scrub at export via the existing `security/pii` seam; aggressive dedupe; a small
human-audited seed set kept apart from everything generated. **Synthetic bootstrap is
allowed only through the same graders** — generated question/SQL pairs scored by the
real guard battery and real execution before entry; synthetic is fuel, never ground
truth (volume is currently the scarce input; this is the honest accelerator).
**Receipt:** the same dataset exported twice yields the same content hash; a provenance
query walks dataset → runs → verdicts; a golden set shows up in the evals plane.

#### MI-4 · First distillation: NL2SQL, rented

**Entry gates (measured, not vibes):** ≥1,000 SFT pairs · ≥150 DPO pairs · a golden set
≥150 spanning difficulty bands · guard-verdict rows flowing ≥30 days. Until the gates
pass, this slice does not start — the ledger keeps accruing either way.

- **Train:** LoRA SFT, then DPO on the correction pairs. Rented first — a managed
  fine-tune API or a single rented GPU with the standard open stack; owning hardware is
  explicitly out of scope. Adapters land in the **artifacts ledger** as versioned
  `model_adapter` records (the VA-7 pattern: append-only, supersession, restore writes
  forward) — provenance from adapter → dataset hash → source runs is two joins.
- **Evaluate:** the existing evals plane + ratchet. Promotion law above. No new harness
  — the removed-harness lesson stands.
- **Serve:** one more OpenAI-compatible binding in the LLM config — localhost (Ollama)
  or a rented endpoint, same seam, id from config, hardcoded nowhere.
- **Route:** the cascade — micro first on eligible task tags, escalation on guard fire /
  low confidence / execution error / timeout. The guards that grade the flywheel also
  catch its student; every escalation is labeled into MI-3.

**Receipt:** a ratchet A/B where the adapter meets baseline on the golden set at
measured cost and latency (the memo's illustrative numbers replaced by real ones), and
a live Trust Receipt naming the cascade hop it rode.

#### MI-5 · The deployment posture: ledger in the box, model as a door, adapters as releases

- **MI-1…3 are default-ON for every install.** Day-one learning IS the ledger — pure
  SQLite, zero compute, every deployment shape. A fresh install starts accruing graded
  pairs from its first query, before any model exists to spend them.
- **Local inference is a door, never a bundle** (DS-17 grammar: `open | needs_setup |
  unavailable` + the alt-door sentence): "enable local model — pulls ~X GB via Ollama,
  needs Y RAM," default off, size disclosed, one click. Serverless deployments show the
  same door pointing at a remote binding. Weights never enter the repo or installer —
  even a 0.6–1B base is 0.5–1.5 GB quantized, and an untuned base meets users at its
  worst; first impressions are a one-shot resource.
- **Shared adapters ship as versioned release artifacts** (`aughor-sql-v1`, `-v2`, …)
  trained on our own pilot data — and on opted-in, scrubbed contributions under §6.7's
  annex (**§6.8: decided YES 2026-09-03**; contribution stays strictly per-deployment
  opt-in — nothing leaves a deployment that didn't say so). An install pulls them the
  way it pulls packs; org-private adapters layer on top. This is the origin directive
  made mechanical: *"models made smarter as more and more users start using the
  platform"* — a fresh install starts with the distilled experience of every deployment
  before it, and its own ledger immediately feeds the next version.

**Receipt:** a fresh laptop install reaches a working micro door in one click with size
disclosed; a serverless deploy reaches the same behavior via remote binding; a release
carries an adapter an install can pull, and the local ratchet re-verifies it there.

#### MI-6 · RLVR, only after the plateau (gated, optional)

**Trigger:** the MI-4 ratchet flat across two consecutive dataset versions — SFT+DPO
has stopped paying before any RL machinery is considered (the lightest-fix ladder:
prompt/tool → SFT → DPO → RLVR). **Recipe when triggered:** GRPO on an adapter over the
same 1–8B base — a single rented GPU suffices for the rehearsal (NVIDIA's 2026-07
guide, verified against the full text). Reward starts **binary and deterministic**:
executed cleanly + guards clean + golden-answer match where one exists — never a naive
`rows > 0` (zero rows is sometimes the right answer; the always-false-predicate class
proves it). Hand-audit the reward on 50–100 real outputs first (law above); inspect
for reward hacking at every checkpoint. The environment is the platform's own loop —
the evals plane grows into the gym; evals and environments are two sides of one system.
Harness (TRL GRPO / veRL / NeMo Gym) chosen then by health, not now by brand.
**Receipt:** a rehearsal report — the reward audit sheet, before/after golden delta,
and the hack-inspection notes — before any promoted weight.

**Traps this arc must not re-pay** (the short list; each is a standing memory):

- Tests that spend the LLM budget (`_ENABLED` read at import) — exporters and trainers
  get the same import-time discipline.
- Two caps for one population — exporter jobs are metered under the SAME budget the
  kernel jobs plane already enforces, not a parallel one.
- An editable install poisons worktree probes — training/export scripts pin
  `PYTHONPATH="$PWD"` like every other bare script.
- A proxy is not the measure — "cost saved" comes from provider invoices and measured
  latency, not token arithmetic.
- Non-hermetic `data/` is real data loss (×2) — the learning store follows the same
  isolation laws as every store before it.
- The catalogue rots — every "true today" bullet above carries its date; re-measure at
  each slice's pre-check (every DS wave moved its own scope at the pre-check).

**Sequencing and dependencies.** Drafting met the collision this document warns about,
at pre-flight: VA-9d's write slice (#427) and §3.8 canvas parity (#428) landed on main
while this section was being written, and §6.4 got its stamp the same evening — caught
by re-checking `origin/main` before committing, which is the standing lesson doing its
job (this section was renumbered from 3.8 to 3.9 in the reconciliation). As reconciled:
MI-0 is decision-sized on its own (§6.7's annex). MI-1 and MI-2 are substrate-sized —
three migrations and a categorization — and may ride alongside any band. MI-3 follows
both. MI-4 starts only at its measured gates. MI-5's door ships with MI-4's first
serving; adapters-as-releases is cleared by §6.8 (YES, 2026-09-03). MI-6 waits on a
measured plateau.
**Non-goals for the whole arc:** a GPU fleet · weights in the repo/installer ·
online/continual learning on live traffic · a second eval harness · a foreign pipeline
runtime (§4.5) · any training on payloads outside §6.7's annex.

**Falsifiers — this arc is droppable by measurement.** If after ~90 days of MI-1…3 on
real usage the graded-pair rate cannot plausibly reach MI-4's gates, the distillation
premise is unproven HERE — stop at the ledger (independently worth having: it is the
audit surface §6.4's break-glass requires and the report-quality measurement substrate)
and re-measure the premise before spending a training dollar. If frontier price/rate
movements make the cascade's savings < 2× at MI-4's pre-check, MI-4 re-scopes to a
latency/custody play or parks. If a foreign runtime ships releases + auth AND we by
then own training volume, §4.5's factory question reopens.

### 3.10 · Arc KI — the Knowledge-Intake arc (adopted 2026-09-05; decision §6 item 9)

> **Origin.** The user's 2026-09-05 directive, raised while walking the production story:
> *"how we enable organisations to bring their own metric definitions. It can be in a
> Google sheet, confluence page, md format, yaml, notion or ready sqls… do we have an
> inlet for all such (and many more) formats?"* The same-day sweep (every ingestion
> surface in `aughor/` and `web/` inventoried with file:line receipts) answered: **prose
> has inlets; structure mostly does not — and the structured stores are exactly the ones
> that carry metric definitions.** Everything load-bearing is restated below so this
> section stands alone.
>
> **The thesis.** §0's ontology is *derived* knowledge (explored from the schema); Arc
> MI's ledger is *earned* knowledge (graded from usage). This arc is the third inlet:
> **declared** knowledge — the metric dictionary the org already owns before it installs
> anything. The wrong build is N format parsers each targeting one of the eight
> definition stores that exist; the right build is ONE funnel: **any source → typed
> candidate objects → a staged review lane → human accept / edit / dismiss → the
> existing stores.** A new format is a new fetcher, never a new pipeline. And the review
> lane is deliberately the SAME surface Arc MI grades through, because an accepted
> import IS a graded artifact: an org's existing dictionary is the fastest lawful volume
> toward MI-4's gates — hundreds of pre-vetted definitions on day one, versus months of
> organic grading.

**Laws that bind every KI wave (standing, not per-slice):**

- **Nothing auto-applies.** Every imported definition passes human accept/edit/dismiss
  before any store the prompt reads is touched. Snowflake's own docs list "patching a
  weak model with verified queries" as an anti-pattern and warn that bad VQs actively
  hurt; §3.9's reward-integrity law extends to imported corpora unchanged. An import is
  a PROPOSAL, in exactly the sense the action plane already means the word.
- **Import into the stores that exist.** Eight definition stores already reach the
  prompt (metrics · glossary · connection KB · trusted queries · vocabulary · packs ·
  instructions · playbook). This arc adds DOORS and a lane, never a ninth store of
  record (the lane's own staging table is bookkeeping, not a destination).
- **Every door is HTTP.** The four structured doors that exist today all require
  filesystem or env access to the host — dead on a serverless deployment. A KI door
  must work on every deployment shape: §3.9's ledger-in-the-box discipline, applied to
  intake.
- **Provenance on every accepted object:** source (file hash / page URL / connector id),
  `imported_at`, `accepted_by` — and on trusted SQL, `verified_at`/`verified_by`, the
  timestamp the Snowflake study flagged our VQ store as missing. A catalogue is a
  measurement with a timestamp; so is a verified query.
- **Imported SQL is fuel, never ground truth.** It becomes prompt-authoritative only
  after real execution plus the real guard battery, and it enters MI-3's dataset plane
  only through the same graders as everything else — §3.9's synthetic-bootstrap law,
  verbatim.
- **Custody is already decided.** Questions, SQL, definitions and verdicts are work
  artifacts — lawful, org-scoped inputs under §6.7; intake changes nothing outbound
  (§6.8's strictly-opt-in posture untouched). No new custody ground is opened.
- **Extraction rides the provider chain** — model ids from config, metered under the
  existing kernel-jobs budget (two caps for one population is a paid trap), no
  import-time `_ENABLED` reads.
- **Store hygiene as ever:** a new table's env name lands in `tests/conftest.py` AND
  `scripts/dump_openapi.py` in the same commit, directory family included; one writer
  per `data/`; migrations numbered off the LIVE `PRAGMA user_version`.

**What is true today (measured 2026-09-05; file:line receipts in the session sweep):**

- **Prose has inlets.** `POST /documents/upload` accepts `.pdf .docx .md .markdown .txt`
  (hard allowlist, `aughor/routers/knowledge.py:20`) into the Qdrant KB → the EXTERNAL
  CONTEXT block on every ask. Confluence and Notion knowledge-sync connectors exist and
  land in the same KB (`aughor/connectors/knowledge/confluence.py:52`, `notion.py:64`;
  trigger `aughor/routers/actions.py:203`).
- **Structure mostly does not.** `POST /metrics` takes one JSON metric per call — no
  bulk, no file. Glossary PUTs are per-entity. The four doors that DO take structured
  files — `data/glossary.yaml`, `/ontology/import`'s export tree, pack folders, the dbt
  manifest (`AUGHOR_DBT_MANIFEST`, env-only) — all assume host filesystem access.
- **The most prompt-authoritative store has NO write door.** Trusted queries are
  injected at the top of the prompt (`aughor/routers/investigations.py:2027`), and the
  only writers are internal (`aughor/evals/promote_trusted.py:112`,
  `aughor/semantic/answer_divergence.py:386`). An org seeds golden SQL by editing
  `data/trusted_queries.json` on disk, or not at all. The model has no
  `verified_at`/`verified_by`, and stores physical SQL that schema drift silently rots.
- **A complete bundle format exists, exposed nowhere.** `aughor/ontology/interchange.py`
  carries a versioned bundle (synonyms · formats · value_dictionaries · exclusions),
  `plan_import`, `apply_import`, `bundle_from_yaml` — and its only caller is
  `aughor/demo/pack.py`. Likewise the vocabulary store's writers (`add_synonym`,
  `set_format`, `set_value_dictionary`, `aughor/ontology/vocabulary.py:155,243,272`)
  have zero HTTP/CLI callers. Built-and-inert — §7's recurring shape, twice over.
- **Google Sheets exists as DATA only** (public gviz CSV → DuckDB tables,
  `aughor/connectors/api/gsheets.py:78`); a Sheet-shaped metric dictionary can become a
  table and nothing else. CSV/XLSX likewise (`local_upload.py:81`) — there is no "this
  file IS a glossary" path anywhere on the platform.
- **MCP cannot supply content** — the consumer implements `tools/list` + `tools/call`
  only (`aughor/mcpservers/session.py:122,136`); `resources/*` is unimplemented, and
  nothing routes an MCP result into any knowledge store.
- **The review plumbing already exists in spirit:** `staged_proposals` (accept/reject,
  resolver named, trace-pinned since MI-2), the packs propose-bindings pattern, DS-15's
  propose→validate→seed grammar, and the eval-promotion path that already turns green
  cases into trusted queries.

#### KI-0 · The trusted-SQL door (substrate-sized) — ✅ BUILT 2026-09-05 (at the user's direction, ahead of item 9's stamp)

CRUD API over the existing store, capability-gated (`SEMANTIC_EDIT`), the model gaining
`status · version · source · proposed_by/at · verified_by · verified_at ·
last_executed_at · verification`. A seeded query is EXECUTED (bounded, mutations
AST-blocked before any engine sees them) against its connection and walked through the
SAME guard battery `/query/validate` runs — extracted into `aughor/sql/validation.py`
precisely so there is one battery, not a drifting copy. A failing seed lands as a
draft with the report attached, never in the prompt. Acceptance is a metrics-style
transition on the shared governance machine — propose (re-verifies) → approve — so
uploading and trusting are two recorded acts; every step journals
`trusted_query.governance` (categorized AND sunk in the governance feed — a mapping
alone renders nothing). `list_trusted` now fails CLOSED: only `approved` reaches
`retrieve_trusted`, the MCP listing and the automations component; a pre-KI-0 record
with no status is grandfathered approved (it was being injected before statuses
existed). The two internal writers stamp their provenance (`eval_promotion`,
`divergence_review`), so `source` is no longer inferable-only.
**Receipt:** `tests/unit/test_ki0_trusted_door.py` — a seed reaches the trusted block
only AFTER the approve act; a mutating seed is blocked before execution and its
propose returns 409; an edit resets approval; identical re-seed of an approved row is
a no-op (the door is safe to point a sync at); the delete is audited (the metrics
catalog already paid for an unaudited one).

#### KI-1 · The canonical bundle and the review lane (the spine) — ✅ BUILT 2026-09-05

The candidate object model landed as `metric · synonym · glossary · rule · join ·
trusted_query` (`aughor/intake/engine.py SECTIONS`; join and rule are connection-KB
entries, glossary carries table+column semantics). `ontology/interchange.py` is
CONSUMED, not rebuilt: its `bundle_from_yaml` parses the wire format, its
forward-version refusal law is shared, and `_plan_synonyms` delegates to its
`plan_import` — the planner that had zero callers has its consumer. Endpoints
(`/intake/*`, SEMANTIC_EDIT-gated): upload → PLAN (per-object verdict against the
LIVE stores: new / changed / identical / conflict, where conflict means an APPROVED
object differs — overwriting a human's approved curation is a human's decision) →
accept/edit/dismiss → accepted objects fan out through each store's own governance:
a metric lands PROPOSED in the metrics workflow, a trusted query goes through KI-0's
`seed_trusted` (extracted so the HTTP door and the lane are ONE flow), a synonym
lands via the vocabulary writer that finally has a caller — **and, since the
2026-09-05 follow-up, a prompt that finally renders it**: human-tier synonyms now
emit a BUSINESS SYNONYMS grounding block (the Snowflake study's last un-landed PORT
lever; mined and model-proposed tiers keep widening schema-linker retrieval and stay
out of the prompt until a person promotes them — their own caveat, kept). Before
that, the lane accepted synonyms into a prompt-invisible store, which is the
built-and-inert shape by construction. Malformed rows are
REFUSED at the door, never staged; identical objects stage as `noop` (nothing to
decide); a failed apply keeps the candidate PENDING with the error attached, so an
edit can fix what a dismissal would lose. Staging store `AUGHOR_INTAKE_DB` — all
three registrations same commit, path resolved PER CALL (the DS-12 lesson; the
module-level resolution failed its own isolation test within the hour).
`intake.governance` categorized AND sunk. `/intake/export/{conn}` emits the extended
bundle (approved trusted queries only — an export states what this deployment
TRUSTS).
**Receipt:** `tests/unit/test_ki1_intake_lane.py` — export → re-import plans ALL
IDENTICAL and zero pending; a byte-identical re-upload dedupes to the SAME bundle by
content hash; provenance walks accepted object → bundle hash → source → uploader;
the accepted metric is `proposed` (never approved by an import) and the accepted
trusted query is NOT in the prompt until KI-0's own approve.

#### KI-2 · File mappers — ✅ COMPLETE 2026-09-05 (deterministic half + LLM prose mapper)

`POST /intake/files` (multipart, SEMANTIC_EDIT-gated) maps a file into a bundle and
feeds the SAME lane (`aughor/intake/mappers.py`; the router's `_stage` is shared, so a
mapped file is just a bundle). Built: the column-mapped **CSV/TSV/XLSX dictionary**
(header vocabulary: Metric/Definition/Formula/Unit/Owner/Aliases/Notes and their
spellings; XLSX via DuckDB's `excel` extension, the same reader the data-upload path
uses) and the **dbt `manifest.json` upload** — mapped through
`semantic/dbt.glossary_from_manifest`, a seam extracted from the env-configured layer
so there is ONE reading of dbt's shape (the env door stays for CI). A row with a
formula becomes a governed-metric candidate; a row with only prose keeps its meaning
as a `definitions` candidate (a new lane kind, landing as the connection-KB `metric`
entry that already exists for exactly that); an Aliases cell fans into synonym
candidates; a nameless row is refused with its row number. The mapper judges
nothing — every object still waits in the lane.
✅ **The LLM prose mapper landed 2026-09-05, falsifier first** (`POST /intake/prose`,
`aughor/intake/prose.py`): pasted text or a markdown page → ONE structured model call
on the provider chain (`get_provider("coder")`, role from config, no model id, metered
like every call) → deterministic validation stands between the model and the lane
(nameless drops; a formula-less metric DEMOTES to a definition, the CSV mapper's own
rule; synonyms are FORCED to `llm_candidate`, so the synonyms prompt block ignores
them until a human promotes; everything tagged `mined:llm`). **The edit-rate
falsifier is instrumented, not aspirational:** the lane's own resolutions are the
measurement (accept-with-edit vs accept-clean vs dismissed), published per import in
the door's response and in aggregate at `GET /intake/mapper-stats` with the ~50%
threshold beside it — above it after prompt iteration, the mapper parks and the
deterministic doors remain. Receipt: `tests/unit/test_ki2_prose_mapper.py` — no test
spends a token; the cross-slice law is pinned (an accepted LLM synonym widens
retrieval and stays OUT of the prompt until promoted to human).
✅ **The SKILL.md lane landed 2026-09-05 — the arc's last deferral, and the pack
candidate kind earned its place:** a `skills` section on the bundle door (and `.md`
with frontmatter on the file door; markdown WITHOUT frontmatter is pointed at
`/intake/prose` rather than guessed at) stages `pack` candidates through the
skills-ingest engine that already owned the format — `plan_pack`'s lint-first plan
was the lane's grammar all along. A BLOCKED skill (model ids, credential shapes,
injection, exfiltration) is REFUSED at the door with the rules named; lint warnings
ride the candidate (the lane IS the review screen the ingest module asked for); an
ACTIVE pack conflicts rather than being overwritten. An accept writes the DRAFT,
PARTIAL pack into the imported root — inert until the pack plane's own promotion,
the two-act law unchanged. Receipt: `tests/unit/test_ki_skill_lane.py`.
**Receipt:** `tests/unit/test_ki2_file_mappers.py` — the same CSV maps to the same
candidate set twice; the mapped file lands: metric `proposed`, definitions in the KB,
synonyms in the vocabulary; the same file re-uploaded dedupes to the same bundle; a
non-manifest JSON and a nameless CSV are refused with reasons.

#### KI-3 · Source fetchers — ✅ COMPLETE 2026-09-05 (Sheets mode + Confluence/Notion mining)

✅ **Sheets definitions mode** (`POST /intake/sheets`): a link-shared Google Sheet
holding a metric dictionary is fetched through the SAME public gviz export the Sheets
DATA connector reads (id extraction made a public seam, `extract_spreadsheet_id` —
the private-import ratchet refused the `_underscore` import, correctly), mapped by
KI-2's deterministic dictionary mapper, staged in the SAME lane. A private sheet is
reported plainly ("Google answered with a login page — share as
Anyone-with-the-link") rather than as a parse error.
✅ **Confluence/Notion mining** (`POST /intake/mine`, `aughor/intake/mining.py`):
walks a knowledge connection's pages through the connectors' OWN iterators and mines
TABLES — the deterministic first cut, exactly as scoped. One pipeline; only the
extraction is per-format, because the wire formats genuinely differ: Confluence
storage-XHTML `<table>` markup (read from the RAW body — the sync's text-stripper
flattens tables to word soup), Notion `table` blocks whose rows are CHILD blocks the
text path never fetches (tables are entirely invisible to the document KB today),
and a Notion DATABASE as one table — its page properties ARE the columns, the most
dictionary-shaped thing in the product. One bundle per page, the page URL as source;
the target DATA connection is named explicitly in the request — mined definitions
attached to the wiki connection itself would be invisible to every prompt, the
built-and-inert trap by construction. A header-less grid is skipped at extraction; a
header-ed table with no metric-name column is "not a dictionary" — checked
explicitly, not caught (the silent-swallow ratchet refused the `except: continue`
version, correctly). Prose mining still waits on the LLM mapper (KI-2's deferred
half). Private-OAuth Sheets/Drive stays parked until a real deployment asks.
**Receipt:** `tests/unit/test_ki3_knowledge_mining.py` — a Confluence metric page
becomes staged candidates whose bundle source IS the page URL; a re-mine of an
unchanged page stages nothing (content-hash dedupe); mined candidates land through
the same lane (metric arrives `proposed`); Notion table-blocks and databases both
mine; a lunch-spots page stages nothing.

#### KI-4 · The suggestions loop — ✅ BUILT 2026-09-05

The Snowflake study's biggest PORT item, landed where it belongs. `POST
/intake/suggest` (`aughor/intake/suggestions.py`) mines what the platform already
witnessed on a connection into the SAME lane: validated `sql_examples` runs →
trusted-query proposals (one per question, ONLY when its history holds exactly one
distinct SQL — two variants is divergence, and proposing either would fabricate an
attribution; divergent questions are counted and named for the consistency surface
instead) · recurring guard fires → factual rule proposals (subject required,
threshold applied, eval-phase fires excluded — a corpus must not mine its own
benchmark) · questions the platform could not answer → a REPORT, not candidates
(an unanswered question has no SQL to stage; writing it is the human act KI-0's
door exists to receive). Deterministic, no model call; the bundle carries no
timestamp so an unchanged corpus re-mines to the same hash and proposes nothing.
**The pre-check measured first (2026-09-05, live):** guard_verdicts held 26 non-eval
rows and the only cluster ≥3 was 24 SUBJECT-LESS `preflight_repair` fires — the
subject requirement and threshold exist because of that measurement; 31 unresolved
investigations; the Qdrant example population is exclusively locked by the live API,
so the endpoint publishes its own populations with every run — the measurement is
part of the product, not a document.
**The MI tie is now mechanical:** `export_sft`/`export_golden` include APPROVED
trusted queries whose approval was a human act (`verified_by` set; eval-promoted
excluded — consistency is not a human warrant; legacy no-verifier rows excluded),
under `trusted_query` lineage, same stable-hash golden split. Every approval through
the two-act door — seeded, imported, or mined — now moves `gate_status()`.
**Receipt:** `tests/unit/test_ki4_suggestions.py` — a mined proposal names its runs
in note, payload and, after approval, dataset lineage; the approved query lands in
exactly one of SFT/golden; a re-mine of the unchanged corpus stages nothing; an
empty deployment gets its populations and stages nothing.

**Traps this arc must not re-pay:** the built-and-inert plane (interchange and
vocabulary are ALREADY that — this arc's first job is consuming them, §7's law) · a
capability added to one store misses the seven others (the lane fans out through ONE
dispatcher, not eight hand-copies) · a guard population hand-listed beside its
expectation (the plan's new/changed/identical/conflict verdicts get tests whose
fixtures the planner discovers) · two caps for one population (mapper LLM calls ride
the kernel-jobs budget) · non-hermetic `data/` (the staging table is a new env name —
all three registrations, same commit).

**Sequencing.** KI-0 is substrate-sized and independent — it may ride alongside any
band and pays for itself the day one pilot org has golden SQL to seed. KI-1 precedes
KI-2/3/4: nothing-auto-applies requires somewhere to review. KI-2's deterministic
mappers precede its LLM mapper. KI-4 shares Arc MI's funnel and should land while
MI-4's gates are still filling — that is the point of it.

**Falsifiers — this arc is droppable by measurement.** If after ~90 days no pilot org
brings a dictionary through the doors, stop at KI-0/KI-1 (independently worth having:
they are also the export/migration surface between deployments) and re-measure demand
before building a single mapper. If the LLM mapper's human edit-rate stays above ~50%
after prompt iteration, park it and keep the deterministic paths — a lane full of junk
candidates teaches reviewers to rubber-stamp, and that poisons the SAME verdict stream
Arc MI trains on. The coupling cuts both ways, and it is the strongest reason this arc
must not ship half-attended.

**Non-goals for the whole arc:** a ninth definition store · auto-apply in any form ·
LookML / Cube / MetricFlow / catalog-tool (DataHub · Atlan · Collibra) importers
without a measured customer pull · OAuth Drive/SharePoint/OneDrive before a deployment
asks · MCP `resources/*` as a content channel (revisit only with a concrete server in
hand) · any change to §6.8's outbound posture.

### 3.11 · Arc SP — Spotlight, the platform operator (adopted 2026-09-05; decision §6 item 10, both clauses YES)

> **Origin.** The user's 2026-09-05 framing, verbatim in the parts that bind: *"an agent
> that understands knows and can modify each and every part of the whole platform (without
> impacting the core functions of course) — the one who can switch between Dark Mode and
> light mode, who can create an agent via Text input from the user, who can schedule
> automations, who can deliver meta data about the activities that were recorded on the
> platform, the one who can query the logs, the one who can count the number of
> connections the tables the schemas… It should be able to guide the user… I think it can
> be a game changer."* The user named it **Spotlight**. Lineage: the 2026-09-01
> meta-agent vision (drafted as an Arc EX section, never inserted, recovered 2026-09-05 —
> the recovery is itself a §7 lesson: a proposal living only in a transcript is invisible
> to every later session) is the **Shape** limb of this arc, one of four.
>
> **The thesis.** This platform's most-repeated failure shape, in its own §7 words, is
> *features stall at TESTED, not LEVERAGED* — the action plane, the vault, interchange,
> the instruction endpoints each shipped complete and sat unreachable. Spotlight ends the
> class structurally: it is the **universal surface**. A governed door, on the day it
> merges, becomes operable ("do it"), introspectable ("what's its state"), and explainable
> ("how does it work") by sentence — before any bespoke UI exists. It is also the stated
> product principle ("chat must feel like a frontier-LLM conversation", user ×3) promoted
> from the data plane to the platform plane. Four limbs: **Know** (counts, activity,
> audit, logs, config) · **Act** (create/schedule/pause/grant — by proposal) · **Guide**
> (teach the product from inside it, ending in an offered act) · **Shape** (the EX
> experience plane, absorbed).

**Laws that bind every SP wave (standing, not per-wave):**

- **One brain, many summons.** Palette, chat rail, Slack (RC-5), and the MCP server are
  transports over ONE declared roster with one custody. No transport sees a wider roster
  than another.
- **The roster is declared, never discovered.** Typed, capability-gated, risk-tiered
  declarations organized into topics — never scraped from OpenAPI at runtime, never
  live-discovered from outside. The house verdict stands: the description IS the routing
  policy, so nothing untrusted may author it.
- **Reads are free within scope; claims are bound to tool results.** Org-scoped, RBAC ∩
  tier via `effective_capabilities` (shipped), §6.4's line intact: metadata freely,
  payloads only through the audited break-glass. Spotlight never answers a state
  question from priors — CI-3's latitude law, unchanged.
- **Cosmetic applies; structural proposes.** Self-scoped preference edits land
  instantly; anything that changes what runs, what others see, or what exists is a
  drafted diff into the EXISTING inbox. The model drafts, the human certifies; a grant
  is permission to PROPOSE.
- **One inbox, one loop, one chat stack.** No second approval plane; periodic work joins
  by adoption, never its own timer; Spotlight extends `converse`, it does not fork it.
- **The invariant plane, non-overridable at every scope.** Spotlight cannot widen its
  own roster, mint capabilities or grants, alter auth/audit configuration, or restyle
  away approvals · failures · provenance · reset. Invariants are always evaluated; only
  an operator decision widens anything.
- **Everything it reads is data, never instructions.** Log lines, activity strings,
  agent names, document text are attacker-influenceable; every tool result is fenced; no
  URL in retrieved content is fetched; no retrieved text can trigger an act (the
  EchoLeak class — CVE-2025-32711 — is the industry's paid receipt). The red-team corpus
  becomes a permanent test file.

**What is true today (measured 2026-09-05; file:line receipts in the session census):**

- **The summon exists.** `web/components/CommandPalette.tsx` (⌘K, Fuse index, 16 nav
  targets, live data) + `web/lib/commandRegistry.ts` (views contribute scoped commands
  while mounted). Gap: `Command.run` is sync-void — free text that matches no command
  dead-ends; no async/streamed shape.
- **The outside door exists.** `aughor/mcp/server.py`: 18 governed tools (incl.
  `list_connections`, runs, jobs, briefing — deliberately no raw query) plus every
  exposed automation as a dynamic tool, stdio/HTTP :8765. The irony that sells the arc:
  an external MCP client can ask this platform how many connections it has; the
  product's own chat cannot.
- **The brain is data-facing.** The conversational roster is 18 tools
  (`converse_tools.py:378–475`) with the platform-wide identity — including
  `platform_help` (8 curated topics; a proto-Guide) and `propose_action`
  (grants-gated, inbox-staged; the Act custody already live in conversation). It is
  connection-bound: no platform-ops tools.
- **Know's substrate is complete and scattered.** ~528 routes; `GET /activity` (+SSE,
  filters, kinds histogram) over `session_events` — whose rows carry
  `prompt/completion/total_tokens`; `GET /usage` rolls cost by six axes with
  `cost_is_complete` honesty; six audit readers across six routers; traces with
  per-trace logs; `GET /capabilities` resolves tier ∩ role. Table/column popularity is
  ALREADY MINED (`aughor/sql/popularity.py`, R14) but consumption sits behind
  `obs.popularity`, default-off — the built-and-inert shape, in miniature, waiting.
- **The user's acceptance suite is green on substrate (2026-09-05, four questions —
  a fifth, nav-tab telemetry, was struck by the user same day):** agent runs 7d + token
  spend ✅ (usage rollup; one `since/until` seam on `usage_report`) · investigation
  accuracy ✅ with the honesty clause (`/learning/summary` verdict acceptance over N
  graded; MI-4's coverage is the limiter) · most-queried table ✅ (popularity store;
  must answer "not mined yet", never a confident 0) · investigations/month ✅
  (`started_at NOT NULL`).
- **The real gaps are three seams and one store:** no per-user settings store anywhere
  (theme = one browser's localStorage) · docs corpus not served (though KI-2's SKILL.md
  lane, landed 2026-09-05, is now the Guide corpus's intake) · `POST /agents/custom`
  goes instantly live, no draft state — so text-to-agent MUST stage, never post · the
  async palette seam above.

**The ten conversations (the market case), graded for buildability.** NL2SQL chat is
table stakes (Genie, Cortex Analyst, Sage, Power BI Copilot). None of them hold this
platform's substrate — receipts, verdict economics, guard batteries, definitional audit,
one inbox, per-sentence cost — so each use case below is a conversation a competitor
cannot have without first building the governance plane. Grades: **near** = wiring over
merged substrate; **medium** = one new seam or falsifier-gated quality; none require new
ML or a new plane.

1. *The disagreement autopsy* ("why do these two numbers differ?") — **medium**: the
   deterministic diff (definition version · snapshot age · warrant tier · guard fires)
   covers most real cases; free-form divergence narration rides the deep path.
2. *Blast radius before any change* — **medium**: needs a `consumers()` reverse index
   per store over edges that exist (ontology · trusted · monitors · briefs · automations).
3. *Deployment by interview* (empty org → staged KI bundle) — **medium**: prompting over
   the SHIPPED plan→accept/edit/dismiss lane; quality falsifier-gated exactly like
   KI-2's mapper (edit-rate at `/intake/mapper-stats` is the precedent).
4. *"Someone already answered this"* — **near**: investigations + SQL-examples vector
   store + `finding_dedup` + freshness; falsifier = dedupe precision.
5. *The pre-mortem sweep* (silent-failure audit: zero-doc agents · failing automations ·
   unpriced models · guards gone quiet · default-off flags) — **near**: every check is a
   deterministic read; this is §7's lesson catalog productized.
6. *Spend attributed to the sentence* — **near**: the G3 rollup + the windowing seam.
7. *The ambiguity broker* (unanswered questions → staged fixes) — **near**:
   `/intake/suggest` already mines exactly this exhaust.
8. *Approvals that learn* (repetition → offered target-bound standing grant) — **near**:
   counting over the inbox + grant machinery that exists.
9. *Cross-tool missions under one custody* — **medium**: automations already call
   granted MCP tools (`automations/engine.py:980`); composition = `draft_automation`
   over granted effects, staged.
10. *Replay any answer as a lesson* — **medium**: narration over traces/spans/logs that
    exist; the stepping UX comes later.

The "time machine" ("what did we believe on Aug 15") stays OUTSIDE the ten: append-only
stores make it reconstructable for governed objects, but it graduates to a wave only if
versioned reads become a platform discipline — wild, kept honest.

#### SP-0 · The census — ✅ substantially done 2026-09-05

This section's "what is true today" table IS the census, taken with file:line receipts.
At build time each wave re-verifies its own rows (the catalogue-timestamp law) — three
inline claims here will rot before any code does.

#### SP-1 · The Know roster (first shippable slice; read-only) — ✅ FIRST CUT BUILT 2026-09-05 (same evening as the stamp)

Platform-ops read tools join conversation: connections/catalog counts, activity
queries, run histories, trace lookups, a unified audit read, popularity ("not mined
yet" honest), capability introspection. Bodies shared with the MCP server — the
`knowledge_tools.py` pattern already proven. Injection fencing on every result.

**Built (first cut, acceptance-suite-shaped):** `aughor/agent/spotlight_tools.py` —
six org-level reads in the converse roster (`list_platform_connections` ·
`platform_usage` · `platform_runs` · `investigation_cadence` · `answer_accuracy` ·
`table_popularity`), same read-only contract as `platform_tools`, stated in the same
absolute terms. The usage tool windows at the LEDGER (`session_events(since=…)` — the
"one seam" turned out to already exist) and totals through the pure `rollup`, so it
cannot disagree with `/usage`; every honesty field travels (`cost_is_complete`,
`calls_without_usage`, unpriced counts). Two new public reads in `db/history.py`
(`investigation_counts_since`, `investigations_by_month`) compare on DAY/MONTH
substrings — the ISO-`T`-vs-space lexical-compare trap, refused by construction.
`answer_accuracy` quotes the rate WITH `graded_total` and grows a caveat under 30
gradings; `table_popularity` reports an empty store as `mined=false` ("not mined
yet"), never as an unqueried warehouse — the confident-0/unmeasured-0 law, per tool.
**Receipt:** `tests/unit/test_spotlight_tools.py` (windowing hits the ledger not
client-side; unpriced ⇒ `cost_is_complete=false`; unknown axis refused before any
read; zero-months listed not omitted; thin-sample caveats; not-mined honesty; the
roster reaches `converse_tools`).

**✅ LIVE RECEIPT 2026-09-06 — and the live drive earned its keep by finding two real
defects, fixed the same day.** The user asked the acceptance questions through the
product's own chat. What held: tokens (1.53M / 565 calls — the org-scoped subset of
1,156 platform-wide, BY DESIGN) with the unpriced-cost honesty clause spoken in the
model's own words; deep-run counts (34, org-scoped of 37). What broke, verified
read-only against the live stores:
- 🔴 **The automation count was a ~16× undercount** — "500 ticks, 5 fired" against a
  windowed truth of 10,646 ticks / 83 fired. Cause: the tool scanned the newest 500
  rows then filtered by date; a soft caveat under a 16× wrong number is not honesty.
  **Fixed:** `automations/store.count_runs_since(day_floor)` counts BY OUTCOME at the
  store; the tool no longer sees rows at all.
- 🔴 **The tables answer reported 0 over correct data** — `table_popularity` returned
  the real top-5 with real counts (4,210 mined; the model even listed the right
  names), but "in the last 7 days" pushed the model to ALSO write warehouse SQL
  (`Count(Distinct Table Name)` → 0, the warehouse has no query log) and let 0
  override the tool. **Fixed** at the description (the description IS the routing
  policy): the tool now declares itself THE source for that question, forbids the
  warehouse-SQL route, discloses that counts are all-time and not windowable (a
  quotable `scope` field), and returns a direct distinct-table count.
- ⚠️ **"34 finished and 5 failed" read as disjoint** — `finished` includes failures.
  **Fixed:** an explicit `succeeded` field; the narrator never infers it again.
**Hardening 2026-09-06 (after a second live drive on a different chat model):** the
model got both QUALITATIVE fixes right (refused the window, quoted the scope, subset
phrasing) but garbled a deterministic count (32/27/5 narrated where the tool said
22/18/4) and turned USD into €. Every tool now returns a pre-composed `summary`
sentence — numbers, units and honesty clauses already worded, built from the SAME
locals as the fields so the two cannot disagree — and every description instructs:
quote it verbatim, never re-derive. Also closed in passing: `cost_is_complete` now
requires zero unpriced AND zero usage-less calls (it keyed on unpriced alone).
**✅ WAVE CLOSED 2026-09-06 — the trace/audit leftovers built.** Two more reads:
`platform_traces` (recent runs from the session ledger via `recent_sessions`, or one
run's anatomy via `recover_session` + the trace summary — step counts, timing,
models, slowest steps, error classes) and `platform_audit` (the unified feed —
`govern.audit_categories.feed` IS the aggregator the census asked for, already
merging every sink with tenant scoping inside; the tool adds only the
conversation-shaped cap and the honesty line that it is a recency feed, never a
total). Custody line drawn where §6.4 draws it: the trace tool is METADATA ONLY —
span inputs/outputs are the audited read on the Traces page, and the tool cannot
express the request (the binding law applied to depth; it also keeps the
conversational read from silently skipping the `trace.payload_access` audit the
route performs). An absent trace is reported as "does not exist or belongs to
another org — the two look identical from this side." Receipt drive on throwaway
stores, real writers only (`session_log.emit` under `bind_trace`): listing counted
2 runs / 1 not ok, the anatomy quoted the guard-refusal error class, the ghost
lookup refused honestly, the audit feed carried the seeded model call.

#### SP-2 · The summon — ✅ FIRST CUT BUILT 2026-09-06

Free text falls through to Spotlight inside the ⌘K overlay; the current surface
travels as context; commands stay first — deterministic and instant; the model is the
fallthrough, never the fast path.

**Built (first cut):** the palette grows a second mode, not a second stack — the
Spotlight row is appended AFTER Fuse's results (never through the index: zero
keystroke cost, always last), and selecting it flips the overlay into an answer pane
driving `useAughorChat` → the same `/api/chat` transport → the same `/ask` door as
every chat surface, `depth:"quick"` pinned, rendered through `projectTurn` →
`PartsMessage` (receipts and all, no bespoke renderer). Follow-ups compose in one
overlay session; ESC backs out one level (spotlight → search → closed); the topbar
search bar — already mouse-clickable on every screen — now reads "Search — or ask
Spotlight anything…", which is the visible affordance. `surface` rides
`ChatRequest`/`AskRequest` end to end (route → both quick bodies → one prompt line),
whitespace-collapsed and capped at 48 chars because it is client-supplied text —
structurally unable to smuggle a paragraph.
**Receipts:** `tests/unit/test_sp2_surface_context.py` (6) — both request models
accept the field; BOTH quick bodies render the line (the guard found the fork
function and counted both threads — the two-site instructions defect, refused);
the sanitizer collapses and caps. Seven web gates + `gen:api` + 670 web tests
green; the raw-font-size ratchet came out one UNDER baseline and was lowered.
**✅ In-browser receipt 2026-09-06:** the user drove ⌘K live — free text produced
the Spotlight row and grounded answers in the overlay (the same session that found
SP-1's two live defects; the summon did its job by carrying real questions).
**✅ WAVE CLOSED 2026-09-06 — the three leftovers built.** The registry's command
shape is async (`run: () => void | Promise<void>` + `keepOpen`; the overlay keeps
the row visibly running until the promise settles and surfaces a rejection as an
error line, never a vanished overlay — one `activate` body serves keyboard and
click, the two-site class refused). The in-context handles exist through one tiny
seam (`commandRegistry.askSpotlight` parks the question, one event opens the
overlay, the palette consumes it straight into the answer pane): the empty Agents
screen offers "Ask Spotlight to draft one" and a failed run row offers "ask why" —
the question is met where it arises, exactly the discovery map's sentence. And the
latency is MEASURED over the real pipeline: the Fuse configuration moved to
`lib/paletteSearch.ts` so the receipt benchmarks the module the overlay runs —
**1.99 ms per keystroke over 800 items** (tripwire bound at 50 ms), with the
structural pin that the Spotlight fallthrough row is appended after the search,
never indexed, so its existence costs zero per keystroke.
**Open in the wave:** nothing.

**Where a person finds it (the discovery map, ranked by how people actually discover):**
⌘K for hands already on keyboards · a **visible Spotlight affordance in the top chrome
of every screen** — the same overlay, for everyone who will never learn a shortcut ·
**the chat surface itself** — the same brain, so a platform question mid-data-
conversation just works, no mode switch, the router routes · **in-context handles where
questions actually arise** — an empty Agents screen offers "ask Spotlight to draft
one", a failed run row offers "ask why" (the commandRegistry's scoped contribution,
aimed; DS-17's doors law: offer only what THIS deployment can open) · and on an EMPTY
deployment, the first thing a brand-new user meets IS Spotlight offering the interview
(use case 3) — onboarding is the summon. Outside the product, SP-5's doors: Slack and
MCP. **The anti-pattern, named: Spotlight is NOT a navigation tab.** An operator is
ambient — summonable everywhere, resident nowhere; a fifteenth tab would demote it to
a destination you remember to visit, which is the built-and-inert shape with a door.

**Receipt:** ⌘K → a question no command matches → a grounded answer with an offered
action, without leaving the overlay; the same overlay opens from the chrome affordance
with a mouse alone; palette latency for plain commands unchanged, measured.

#### SP-3 · The Act limb, and the arc's one new store — ✅ FIRST CUT BUILT 2026-09-06

`draft_agent` — the "describe it" NL bootstrap the 2026-08-18 research already
recommended: an accept/reject DIFF over the five governing fields, the empty-`doc_ids`
trap disclosed in the draft itself; `draft_automation` — trigger + effects + attached
dry-run, joining the ONE loop by adoption; grant/pause/resume proposals. All staged
through the existing inbox; nothing posts live. Plus the per-user settings store
(theme · density · defaults) — hermetic from day one: env name in `tests/conftest.py`
AND `scripts/dump_openapi.py` the same commit, one writer per `data/`.

**Built (first cut):** `aughor/agent/spotlight_act.py` — the Act roster the Know
module promised by name, wired into converse beside `action_tools`. The custody line
is mechanical: `set_preference` (cosmetic, self-scoped) applies INSTANTLY against the
arc's one new store (`db/user_prefs.py`, closed key registry — theme · density ·
default connection — per-call env resolution, all three hermeticity registrations in
this commit, plus `GET/PUT /me/preferences`); `draft_agent` and `draft_automation`
(structural) can only STAGE — two new kinds on the ONE inbox (`agent_draft`,
`automation_draft`), exactly the seam the inbox's own docstring names ("what differs
is only what the accept executes"). Accept is the arming: it RE-validates (documents
can vanish between the two acts — a moved-data draft fails with the problem sentence,
never creates) and then runs the same one-door writes the create routes use — `create_agent`
directly, and the automation save through a REGISTERED door
(`runners/automation_save.py`: the store hangs its save there at import), because
three layering guards hold in both directions: K may not import A, and the runner
package may not import its own callers either. Cycle refusals land verbatim. Reject
leaves the platform byte-identical. `draft_automation` owns none of the drafting —
DS-15's `propose_chain` validates and attaches the dry-run; a refusal is relayed as
the considered answer it is. Validation itself became ONE body:
`custom_agents/store.validate_agent_draft`, with the create route now delegating —
the two-site drift class, closed at birth. The swallow ratchet shaped the prefs
reader (unreadable rows route through `tolerate`, never a bare skip); the vocabulary
ratchet forced the retired term out of the new code AND retired three stale-path
prose uses in the inbox while it was at it; the layering guards redesigned the
automation save into the door registry above — three ratchets, three better shapes.
**Receipts:** `tests/unit/test_spotlight_act.py` (12 — instant-apply + persistence +
per-call env resolution; unknown key refused naming the registry; the empty-docs
disclosure reaches the APPROVER's reasoning; accept creates / reject byte-identical /
second accept `already_resolved`; accept re-validates moved data; a stale automation
draft refused with its reason; roster wiring). Neighbor guards green (kinetic,
grants, agents, hermeticity, prose/binding/flag ratchets). `gen:api` regenerated.
**✅ LIVE RECEIPT 2026-09-06 (post-merge #453, API restarted):** the prefs door live
(`PUT /me/preferences/theme` → dark); the arc's ORIGIN SENTENCE driven through the
product's own chat — and the model MEASURED THE PREMISE FIRST: three Know reads found
the target connection's orders are US-only (no DE rows exist) and it DECLINED to
draft a false-premise agent, offering grounded alternatives; on confirmation
`draft_agent` staged live (pending in the real inbox, empty-docs disclosure spoken —
the approval left to the human, which is the design), and `draft_automation` relayed
DS-15's considered refusal verbatim (no brief-delivery effect on this deployment —
the doors law working). One wobble for the record: the draft's name/instructions
echoed the earlier per-country frame after the user had agreed to overall scope —
recommend reject and restage when a draft's params outlive the frame they were
negotiated under. ⚠️ `GET /kinetic-actions/inbox` defaults to the BUILTIN
connection — pass `?connection_id=…` when checking for staged rows.
**✅ Web reads the settings store (2026-09-06, with SP-4):** the shell consults
`GET /me/preferences` on load (localStorage paints first, the store wins and re-caches)
and the Settings toggle writes through `PUT /me/preferences/theme` — a theme set from
chat, another browser, or Spotlight follows the user here on next load. Theme is no
longer client-local.
**✅ WAVE CLOSED 2026-09-06 — grant/pause/resume + the live flip built.** Two Act
tools: `pause_or_resume_automation` (a pause always carries its end — an endless
mute is disabling, a different act; resume clears it) and `propose_agent_grant`
(ONE declared action onto an agent's grant list — a grant is permission to
PROPOSE, never to execute, and the reasoning the approver reads says so). Both
stage as two more kinds on the ONE inbox (`automation_state`, `agent_grant`);
accepts apply through the second registered runners door
(`runners/automation_state.py` — the layering guards' shape, reused) and the ONE
grant-validation body (`custom_agents/store.validate_agent_grants`, extracted from
the agents routes so stage, accept and the 422 path speak identical sentences —
the two-site drift class, closed the way SP-3 closed it for drafts). The write's
TARGET is bound too: an automation on another connection is refused with its home
named. The vocabulary ratchet came out one UNDER baseline (347): the inbox's four
accept bodies now share one lazy import of the executor's result type, so two new
kinds arrived while the count fell. And the live flip: `useAughorChat` announces a
finished turn (one hook, every chat surface — panel, /chat, the ⌘K overlay), the
shell re-reads stored preferences and applies a changed theme without a reload;
proven in-browser against the live store read-only (DOM drifted, event fired,
stored value won and re-cached). Receipt drive on throwaway stores: pause staged →
byte-identical until accept → applied with its end; resume cleared it; the grant
appended exactly at accept; a deleted automation refused at accept with its
sentence. **Open in the wave:** nothing.

#### SP-4 · The Guide limb — ✅ FIRST CUT BUILT 2026-09-06

The curated corpus becomes real and served: KI's SKILL.md lane feeds it; answers ground
in the registry (what THIS deployment offers — a door the deployment cannot open is
never offered, DS-17's law) and in live state (what YOU have built, what failed
lately); every guidance answer ends in an offered, staged act. **Receipt:** "how should
I create an agent?" yields the real four steps, cites the asker's own agents and their
eval results, and offers the draft.

**Built (first cut):** `aughor/agent/spotlight_guide.py` — one tool on the converse
roster (`platform_guide`), four walkthroughs: creating an agent, creating an
automation, connecting data, appearance. The split with the concept tool is stated on
both descriptions (concepts stay with `platform_help`; how-do-I comes here), so the
router routes by the same claims from either side. Three laws hold per topic: the
steps are the PRODUCT's — the agent walkthrough quotes the create flow's own stepper
(Start · Scope · Define · Prove · Reach), the empty-docs trap taught in the Define
step in the flow's own words; the grounding is live and honest about failure — the
asker's agents each carry their evaluation state in the eval-basis vocabulary (a
stale pass chip is named as measured on a configuration that no longer runs, never
presented as current), the automation topic reads the REAL clock (a stopped clock is
disclosed before a schedule is implied — DS-17's alt-door honesty) and the trailing
error count, and a failed store read reports itself unavailable rather than posing as
an empty deployment; and every walkthrough ends in an offered act from the Act
roster — `draft_agent`, `draft_automation`, `set_preference` — except connect_data,
which offers a page and says why (credentials are a person's to type, never a model's
to relay; no chat door exists, deliberately). An unknown topic answers with the topic
list, never a guessed walkthrough. Every result carries the pre-composed `summary`
built from the same locals as its fields (SP-1's hardening, inherited at birth).
**Receipts:** `tests/unit/test_spotlight_guide.py` (11 — alias resolution; unknown
topic lists, never guesses; every offered tool exists on the live converse roster;
the asker's agents cited with pass counts, never-evaluated and stale states worded
distinctly; a failed grounding read is "could not be read", not "0 agents"; the
stopped clock disclosed; stored preferences quoted; the stepper stations present;
staging taught before scheduling; roster wiring). Prose/vocabulary ratchets green.
**✅ LIVE RECEIPT 2026-09-06 — the wave's sentence, verbatim.** "How should I
create an agent?" through the product's own chat: two steps, exactly ONE tool
fired (`platform_guide` — routing healthy at ~36 tools), and the answer walked
the real five stations, taught the empty-documents trap in the flow's own words,
cited the asker's own agent WITH its eval result ("The Look Analyst — 5/5 golden
questions passing, measured on the configuration running now"), and ended by
offering the staged draft. The same grounded body also served through the MCP
door the same day (SP-5's receipt) — one declaration, two transports, one answer.
**Open in the wave:** deeper corpus service (searching SKILL.md-fed pack prose
from inside the guide, beyond naming the door).

#### SP-5 · One roster, every door — ✅ FIRST CUT BUILT 2026-09-06

The converse and MCP rosters unify into one declared registry with two transports;
Slack summon rides RC-5. **Receipt:** the same staged-proposal flow driven from Slack
and from an external MCP client; a diff of the two rosters returns empty and is
ratcheted so it stays empty.

**Built (first cut):** the census settled half the wave before any code — **Slack
already summons the one brain** (the bot service drives the same `POST /ask` every
chat surface drives, so the whole Spotlight roster, staged proposals included, is
reachable from Slack by construction), and MCP's `ask` tool likewise. What was
genuinely missing was DIRECT tool parity, and one-writer-per-`data/` is what shaped
it: the MCP server is a separate process, so its Spotlight tools must not open the
stores. The declaration is now ONE function (`agent/spotlight_roster.py` — Know 9 ·
Act 5 · Guide 1), and every consumer derives from it: converse concatenates it (as
before, connection bound by closure); two new routes serve it as the out-of-process
transport seam (`GET /spotlight/tools` lists the declaration — names, descriptions,
parameter schemas; `POST /spotlight/tools/{tool}` dispatches one call into the same
bodies conversation runs, auth'd by the API's normal front door, deliberately NOT an
exempt prefix); and the MCP server registers one tool per declared entry at startup
(`register_spotlight_tools`, mirroring the automations pattern — never fatal,
collision-skipped, `--no-spotlight` to opt out), each call riding the route back
into the one process that owns the stores. Custody rides the roster, not the
transport: an MCP client's Act call can only stage into the same inbox.
**Receipts:** `tests/unit/test_spotlight_roster_parity.py` (7) — the parity ratchet
the wave named: conversation carries exactly the declaration (names AND
descriptions — the routing policy); the HTTP listing diffs empty against it; the
real registration function driven over the real listing payload registers exactly
it (declared descriptions led with verbatim; a name collision skipped, never
shadowed); the dispatch door runs the same bodies, refuses an unknown tool naming
the roster, and relays a raising tool as a refusal.
**✅ LIVE DRIVES DONE 2026-09-06 — the staged-proposal flow proven on ALL THREE
transports.** MCP: a real external client (stdio, its own process, no stores)
listed 33 tools with 15/15 Spotlight present, read the same grounded guide body,
and STAGED an agent draft into the real inbox — rejected, agents byte-identical.
Slack: the user sent one message to the running bot (Socket Mode, supervisor up
since Aug 29) → the same `agent_draft` kind staged pending → rejected,
byte-identical. The Slack drive also handed the custody line a live win: the
bot's turn ran on a different connection than the user meant, the model drafted
against the wrong tables — and the questionable draft SAT WAITING for a human
instead of going live. The model drafts; the human certifies; the mistake died
in review.
**Open in the wave:** native per-parameter schemas on the MCP side (arguments
travel as one `args` object today, schema rendered into the description).

#### SP-6 · Red team, then proact — ✅ FIRST CUT BUILT 2026-09-06 (red team held first, in-branch)

An adversarial pass seeds hostile content into logs, agent names, document text —
every hole becomes a refusal test in the permanent corpus (EX-9's pattern, arc-wide).
Only after it holds: evidence-backed proposals ("this automation failed four Mondays
running — fix its schedule?") that cite their evidence rows and never auto-apply.
**Receipt:** the attack corpus IS the test file; one proactive proposal accepted by a
real user with its evidence chain in the record.

**Built (first cut, red team first as the wave orders):**
`tests/unit/test_spotlight_redteam.py` is the PERMANENT corpus — instruction
overrides, fake system/tool framing, exfiltration nudges, SQL-shaped names, and
10 KB bulk, seeded through the REAL writers (ledger emits under a bound trace, real
automation and agent records) and driven through the roster. What it pins is what a
unit test can enforce: hostile content comes back as DATA, clipped
(`agent/spotlight_text.py` — every name Spotlight interpolates and every free-text
field it relays now rides one clip; the corpus forced that helper into existence
across the Know, Act and Guide modules); no attack string changes custody (hostile
automation references are clean clipped refusals, hostile preference keys/values
die at the closed registry, hostile reasoning is truncated before an approver reads
it); every result is size-bounded; and the whole Know roster leaves the inbox
untouched over hostile data — a read that staged would be the EchoLeak shape. What
a unit test cannot enforce — whether a model OBEYS relayed text — stays on the
transport's structure (tool results ride the provider's tool-role channel) and the
live drives this corpus seeds. THEN the proact half, held to its law:
`platform_premortem`, a Know read whose findings are deterministic and
evidence-backed — automations erroring N runs in a row (evidence: the run rows,
with reasons), agents with zero documents (the sees-less trap), unpriced spend
(the cost-floor clause) — each finding carrying the roster offer that addresses it
(`pause_or_resume_automation` for a streak; an honest page pointer where no chat
door exists), and the tool NEVER applies anything: the receipt pins that a sweep
stages zero proposals, and an unreadable store reports itself, never a clean bill.
**Receipts:** the corpus file (9) + two premortem receipts in
`test_spotlight_tools.py` (streak flagged with run-row evidence and the pause
offer; zero-doc agent flagged with the honest no-tool offer; a broken store is
"not a clean bill of health", never silence).
**Hardened 2026-09-06:** the evidence chain is now STRUCTURAL, not narrated — a
premortem streak finding's offer carries its own arguments (`automation`,
`action`, and the pre-worded `evidence` chain of run ids), and
`pause_or_resume_automation` records a passed evidence string verbatim (clipped)
onto the staged reasoning, so the approver always sees the rows whether or not
the narrator re-types them faithfully. And the permanent corpus followed the
arc's newest seam, as the wave orders: hostile arguments through the
`/spotlight/tools` HTTP door come back as bounded refusals (a guessed
walkthrough never appears, a 10 KB agent name dies at the cap, nothing is
created, nothing staged by reads), an unknown tool is a bounded 404, and a
non-object `args` is a validation refusal, never a dispatch.
**Open in the wave:** the LIVE half of the receipt — one proactive proposal
accepted by a real user with its evidence chain in the record (no honest
candidate existed on the live deployment when checked: the only finding's offer
is deliberately a page, not a staged act — the receipt waits for a natural
occasion) — and periodic live red-team drives feeding new corpus entries.

**Traps this arc must not re-pay:** the built-and-inert plane (the popularity flag is
sitting in it right now) · the god-roster (500 tools, no topics — routing collapses and
the blast radius is maximal) · approval fatigue (bulk-approve turns the inbox into a
rubber stamp; diffs, batching, and standing grants are the counter-design) · a confident
0 where an unmeasured 0 belongs (the observability docstring's own law) · unfenced
content blending (EchoLeak) · a new store without its three registrations.

**Sequencing.** SP-1 is independent, read-only, and first — it pays for itself the day
it answers the acceptance suite. SP-2 can ride in parallel (it is mostly `web/`). SP-3
follows SP-1 (the Act tools want the Know tools' grounding). SP-4 any time after KI's
lane (already landed). SP-5 after SP-1+SP-3 stabilize the roster. SP-6's red-team half
gates the proactive half, not the other way around. **Cross-user Know answers ("who did
what") wait on VA-10's auth-model decision, full stop** — resolve_principal trusts
unverified headers today, and an operator agent must not stand on that.

**Falsifiers — this arc re-scopes by measurement.** Tool-routing accuracy degrading
past ~25 tools ⇒ topics become load-time-scoped before the roster widens further ·
drafted agents mostly edited-to-death before approval ⇒ SP-3 re-scopes to "open the
real form, pre-filled" · palette fallthrough latency people abandon ⇒ the summon stays
navigational and Spotlight lives in the chat rail · if 30 days after SP-1 nobody asks
Spotlight platform questions, stop and re-measure demand before building a single Act
tool — a universal surface nobody summons is the built-and-inert shape wearing a cape.

**Non-goals for the whole arc:** an OpenAPI-scraped roster · auto-execution of anything
structural · a second inbox, loop, or chat stack · raw SQL over system stores · live MCP
tool discovery into the brain · client-side navigation telemetry (proposed as an
acceptance question, struck by the user 2026-09-05 — do not re-propose without new
facts) · a browser-local theme hack in place of the settings store · any capability
widening by Spotlight itself, ever.

**Relationship to the other arcs.** Arc EX folds in as the Shape wave-family (item 10
recommends this rather than a sibling arc; the EX draft and its two session artifacts —
the founding note and the interactive console demo — are the wave-family's design
record). Arc KI feeds Guide's corpus and the interview use case; every graded Spotlight
exchange feeds Arc MI's funnel; VA-10 gates cross-user Know. CI-2/CI-3 (the platform
identity and first roster) are, in hindsight, SP's Phase 0 — this arc aims what they
began.

### 3.12 · Arc MT — self-serve multi-tenancy (drafted 2026-09-07; decision §6 item 12)

> **Origin.** The user's 2026-09-07 directive, given while wiring Google sign-in:
> *"any user who goes to vercel deployment should be asked to login using Gmail.. and
> once logged in the user can create a number of workspaces.. naturally linked to the
> users Google login."* That is a product shape, not a feature: the hosted deployment
> stops being a single shared instance behind a login and becomes a self-serve
> platform where a stranger's first Google sign-in creates a private world.
>
> **The thesis: aim the tenancy machinery that already exists; build almost none.**
> VA-10 (#459/#461) made identity verifiable end to end — OIDC at `resolve_principal`,
> the sign-in flow in the topbar, the spoofable header seam dead under a configured
> issuer. The org is already the tenant boundary and already ENFORCED: connections
> carry `org_id`, every store filters by it, and cross-org access was demonstrated
> live as a hard 403 (2026-09-04, DATA-06). Workspaces are already org-scoped, and
> RBAC already crowns the first identified user of an org its owner
> (`maybe_bootstrap_owner`). What is missing is exactly one mapping and one door:
> **one user = one org** (derived at token verification), and a **login wall** in
> front of the app. "Create an account" needs no flow at all — the first verified
> sign-in IS account creation, which is the cheapest onboarding a product can have.

**Laws that bind every MT wave (standing, not per-slice):**

- **The org id derives from Google's `sub`, never from the email.** `sub` is Google's
  stable subject identifier; an email can be changed and would silently orphan a
  user's entire world. The email is display material (§ VA-10's own rule: the client
  decodes claims for display; the server decides identity).
- **A fresh org is born CAPPED.** A stranger with a Gmail address must never mean
  uncapped LLM spend: provisioning writes default usage caps through the G4 store
  (the `/governance/caps` door shipped 2026-09-06 — this is one call, not a build).
  Operators raise caps deliberately; nothing raises them by signing up.
- **Fail-closed inherits from VA-10 unchanged.** An invalid token is nothing; the
  header seam stays dead under a configured issuer; localhost with identity off stays
  byte-identical — a laptop install never sees any of this arc.
- **Provisioning is idempotent and first-touch.** The same token arriving twice
  provisions once; a returning user's org is looked up, never re-created. No
  provisioning happens for an unverified caller, ever.
- **Shared builtins stay shared by design** (the Workspace samples, aughor_ops) —
  they are demo substrate, not tenant data, and every org sees them. Everything a
  user CREATES lands in their own org.
- **One roadmap, one tenancy mechanism.** No per-user ownership columns beside the
  org boundary — two isolation mechanisms that can disagree is how leaks happen.

**What is true today (measured 2026-09-06/07, receipts in this file and the session):**

- Identity: OIDC verification live (#459), sign-in flow + `/auth/config` + fetch
  wrapper live (#461, receipted `{oidc_configured:false}` on the local instance —
  inert until env). `AUGHOR_REQUIRE_IDENTITY=1` would today let the app SHELL render
  and fail every call with 401s — enforcement without a front door.
- Tenancy: all verified users land in ONE org (`AUGHOR_OIDC_DEFAULT_ORG`, default
  "default"); two strangers would be individually identified and jointly staring at
  the same workspaces. Org isolation itself is enforced and live-proven (403).
- Cost safety: the caps store has a write door but NO defaults — a fresh org is
  uncapped until an operator says otherwise. Inverted by this arc's second law.
- Google side: an External consent screen in "Testing" mode shows an unverified-app
  warning and limits sign-ins to allow-listed test users; full verification is a
  later, user-keyed process with Google.

**Waves, in build order:**

- **MT-0 · The login wall.** When `/auth/config` says `identity_required` and no
  token is held, the app renders a full-screen sign-in page instead of the shell —
  the Google button front and center, nothing else reachable. Small by design: the
  config plumbing (#461) anticipated exactly this reader.
  **Receipt:** an incognito visit to the armed deployment shows only the sign-in
  page; after sign-in, the app; after sign-out, the wall again.
- **MT-1 · One user = one org.** A per-user tenancy mode at the verification seam:
  with the mode on and no org claim configured, `principal_of` derives the org from
  `sub` (a stable prefix-hashed id, never the raw email). First touch provisions:
  the org row, a starter workspace, the owner role (the existing bootstrap does
  this per-org already — verify, don't rebuild), and DEFAULT USAGE CAPS. Idempotent;
  covered by isolation tests that prove two verified users cannot see each other's
  workspaces, connections, or history.
  **Receipt:** two different Gmail identities sign in; each sees a private starter
  workspace; each creates workspaces the other cannot list; cross-org reads 403.
- **MT-2 · Arm the hosted deployment.** External consent screen (user's console),
  client id pasted, three env vars on Vercel (`AUGHOR_OIDC_ISSUER`,
  `AUGHOR_OIDC_AUDIENCE`, `AUGHOR_REQUIRE_IDENTITY=1`) plus the per-user mode.
  **Receipt:** the MT-1 two-account receipt taken on the LIVE Vercel deployment.

**Deliberately out of scope (not refused — later):** billing and paid tiers · team
orgs (a second user JOINING an existing org — invites, membership, role grants;
the substrate supports it, the join mechanism is a later wave) · Google app
verification (user-keyed paperwork) · org deletion/export lifecycle · rate-limiting
beyond the usage-cap defaults.

**Risks, carried in rather than discovered:** (a) serverless provisioning must be
race-safe — two concurrent first requests from one new user must not double-provision
(idempotency by derived org id, not by "did I just create this"); (b) the Vercel data
plane is Postgres — provisioning writes must ride the same store seams as everything
else, no direct DDL; (c) a capped org's refusal must SAY it is a cap, not fail
mysteriously — the caps plane's `action` vocabulary already distinguishes alert from
block.

### 3.13 · Arc DX — the documents plane (built 2026-09-07)

> **Origin.** The user's 2026-09-07 directive: *"I want people to upload any document
> and convert it to any format ... and when they upload, they should have a preview,
> those should be usable as context in canvases, for agents, practically anywhere in
> the platform."*
>
> **What measurement found before any code was written.** The plane read five file
> types and its reading was worse than its chunk counts suggested. On a Word file
> holding a four-row revenue table, `extract_text` returned 117 characters and every
> number was gone — `python-docx`'s `.paragraphs` does not walk tables, so the table
> was dropped in silence. The same table in a PDF came back as orphaned cells with no
> grid. And a `.pptx` reaching the `read_text(errors="replace")` fallback produced
> **26,928 characters of decoded ZIP container**, chunked and embedded as if it were
> prose — a failure that looked exactly like success, guarded only by a hand-written
> extension list that `index_text`'s connector callers never pass through.
>
> **The shape: Markdown is the PIVOT.** anydoc (Firecrawl's Rust converter; MIT,
> prebuilt abi3 wheels, no ML model, no network) brings fourteen formats IN as
> Markdown; the `ExportDoc` renderers already in `aughor/export/` — which had exactly
> one producer, an investigation's `report_json` — take it back OUT as PDF, Word,
> PowerPoint, HTML or text. Fourteen readers plus six writers is twenty seams; the
> format-pair matrix would have been eighty-four.

**Laws this arc establishes:**

- **Fail closed on input you cannot place.** Dispatch on what the bytes ARE
  (`format_from_bytes`), never on what they are called. A mislabelled binary raises a
  typed error; nothing returns a best-effort string, because "we could not read this"
  must never reach the index disguised as content.
- **Retention is the keystone.** Upload used to `unlink` the file in a `finally:`.
  Preview had nothing to show but chunk text, conversion had nothing to convert, and
  a re-index could only re-embed the old parse. Originals are kept org-pathed, with
  the Markdown cached beside them as a DISPOSABLE artefact — deleting the `.md` is
  always safe because the original can be re-read.
- **An allowlist is asked, never restated.** The router's accepted set and the drop
  zone's `accept` both come from the converter's declared formats. The old
  hand-written five stayed five while the parser grew to twenty: a capability that
  existed and was unreachable.
- **Pinning is not fencing.** An AGENT's `doc_ids` RESTRICT (fail-closed — its context
  is what its creator gave it). A CANVAS's `doc_ids` PIN — they add to what is in
  reach without removing the corpus, because a canvas is a place, not a fence. Pinned
  documents are searched against the question so a 200-chunk report cannot flood the
  prompt, and an agent still fences a canvas: widening would turn a restriction into
  a suggestion.
- **Hosted OCR is a network call.** anydoc can delegate scanned PDFs to Firecrawl.
  Off unless `AUGHOR_DOC_OCR=hosted`; consent for sending a document off the box is
  external, like every other outbound seam.

**Shipped:** the converter seam (`knowledge/convert.py`), byte retention
(`knowledge/blobs.py`), the outbound renderer (`knowledge/render.py`), preview and
convert routes, canvas document binding wired at all three retrieval sites, and the
UI for both.

**Defect fixed on the way through, worth remembering:** routing upload through
`index_text` turned a loud 422 into a silent **201** — `index_text` returns early
WITHOUT registering when chunking yields nothing, so any document shorter than
`min_chars` came back "Created" with a doc_id that appeared in no listing and 404'd on
fetch and delete. The same early return still applies to the Confluence/Notion
connectors, where a short page vanishes the same way and nothing reports it.

**Measured on a live 40-page investor deck (2026-09-08), which found three defects
and one limit that cannot be coded away:**

- 🔴 **A row wider than its header had its extra cells TRUNCATED**, and converters do
  not escape pipes inside a cell — so a slide labelled `Luxury | Mytheresa` emitted
  three cells under a two-cell header and the parser kept `Luxury`, dropped
  `Mytheresa`, and threw away the whole bullet list of results beside it. The deck's
  headline table came out as `[['Luxury'], ['Luxury'], ['Off-price']]` and the
  rendered PDF looked perfectly well-formed with every GMV, Net Sales and NPS figure
  gone. A table is now as wide as its WIDEST row; widening can leave an empty column,
  truncating loses content, and only one of those is visible to the reader.
- 🔴 `str.strip("|")` is GREEDY — `||Highlights|` lost both leading pipes and parsed
  one cell narrower than its own body rows, which is what fed the truncation above.
  Strip exactly one pipe per side.
- 🔴 **A per-page marker asserted a cause it did not know.** Every page failure was
  reported as "an image with no text layer", including ones that failed for other
  reasons. Only `NeedsOcrError` / `UnsupportedError` license that claim; anything else
  says only that the page could not be read, and `pages_failed` is reported apart from
  `pages_needing_ocr` because OCR fixes one and nothing fixes the other.
- ⚠️ **CHART DATA LOSES ITS LABELS, and no converter can fix it.** A bar chart's
  numbers are positioned graphics, not structure, so they extract as an unattributed
  run: `Value (GMV)245.9 268.9 279.6 224.5 290.7 243.4 118.6 125.3 130.7` with
  `Q1 Q2 Q3 Q1 Q2 Q3 Q1 Q2 Q3` on a separate line. Real tables are unaffected — the
  same deck yielded 158 well-formed table rows against one chart slide — but those
  orphan numbers ARE chunked and embedded, so an agent asked for one segment's GMV can
  retrieve the run and answer confidently from the wrong position — the
  well-formed-wrong-answer trap on the intake side.
  **Answered 2026-09-08 (the user's call): those runs are held OUT OF THE INDEX**
  (`ChunkSettings.suppress_numeric_runs`, the one default here chosen rather than
  inherited). It is a different KIND of setting from `strip_urls_emails` beside it:
  that deletes from the DOCUMENT, this only from the index — every figure stays in the
  stored Markdown, the preview and every conversion, and turning it off and
  re-indexing puts it back. A line qualifies only when four or more numeric tokens
  OUTNUMBER the words among the non-numeric ones (a unit welded to its value belongs
  to the number: counting the "bps" in "+140bps" as a word let nine bare deltas score
  themselves a sentence), and table rows and fenced code are never runs because their
  header or fence IS the attribution. Measured on the live deck: **5 lines of 522,
  0.78% of characters**, and every figure that matters survived because it also
  appears in a real table. Both doors report the count; the UI says what was held back
  and offers the switch. What remains open is the harder half — a chart's meaning is
  recoverable only by reading the page as an image.

**Open:** a re-index that genuinely RE-READS retained originals (today it re-embeds
the stored chunks — the material is now on disk, the code is not written); documents
as canvas nodes on the ReactFlow surface rather than only as a canvas-level binding;
`.potx`/`.pages`/`.html` are not anydoc formats and are refused.

### 3.14 · Arc PX — the product-experience arc: doors, language, composition (drafted 2026-09-09; decision §6 item 13) — ✅ **ALL SEVEN WAVES SHIPPED 2026-09-09**

> **Completion note, same day.** Drafted, adopted, and built in one session, waves
> ordered by the user's knob (most ambitious first: PX-3 → PX-0 → PX-1 → PX-2 →
> PX-4 → PX-5 → PX-6), every wave live-driven with its receipt taken. Two premise
> corrections earned along the way and recorded on their waves: PX-5's provenance
> substrate already existed (the gap really was composition), and PX-6's "seven
> activity surfaces" measured as views over FOUR data planes — one cross-link, not
> a merge. Open leftovers, each recorded on its wave: the in-chat cap-refusal
> door-link (PX-2), eval-suite name curation and a static title lint (PX-1), and
> the consistency-plane UI (out of scope until its flag graduates).

> **Origin.** The user's 2026-09-09 hypothesis, given after the USP discussion: *"there
> are a lot of features that aughor has but are not surfaced or exposed as much as they
> should be. Along with that, our UI is also like an AI slop … it lacks the UI judgement
> of an experienced UI/UX researcher."* Audited the same day — two exhaustive code
> audits (every backend path vs. every frontend caller; every surface vs. how a person
> reaches it) plus sixteen screens of the live app — and **both halves confirmed**, with
> a correction: the slop is not the visual layer (the token system and its seven
> ratcheted gates are fine); it is content design, information architecture, and doors.
>
> **The thesis.** §0's rule — a capability ships when something consumes it — has a
> second clause this audit forces: **a capability is not consumed until a person can
> find it, and it is not trusted until it speaks the person's language.** The inert mass
> has migrated one level up: the planes got built (the agent planes all have doors —
> the old suspicion is measured FALSE), and now the DOORS are the inert layer —
> ~89 live browser-relevant endpoints with no UI, 30 fully-written client wrappers no
> component calls, 3 finished components never imported. The Genie study's verdict
> ("~90% of the parts — the gap is composition") is this arc, itemized. And it
> composes with Arc MT: **MT is the lock on the front door; PX is the room a stranger
> walks into.** Arming self-serve before fixing the first five minutes ships the void
> to strangers.

**Laws that bind every PX wave (standing, not per-slice):**

- **No machine text reaches an eye.** Anything rendered as a title, label or suggestion
  must be authored for a person. Prompt preambles, snake_case rule keys, eval wave
  names, raw connection-id prefixes and unformatted decimals are exhaust. The fix is
  always display-side — **what the model receives never changes to make a screen
  prettier** (the `observation_note` preamble stays byte-identical; the run gains a
  display title).
- **An empty state is a door, not an apology.** Every empty surface names the action
  that fills it and offers the button — the standing card law ("a card must offer the
  door THIS deployment can open") extended to blank screens. One shared `EmptyState`
  primitive; the four independent local ones retire into it.
- **A door ships with its deep link.** Any surface a wave adds or touches writes its
  `?tab=`/`?layer=` state and restores from it. Unbookmarkable is unshipped.
- **Wire it or delete it, in the same wave.** A dead `lib/api.ts` wrapper or
  never-imported component in a wave's path either gains its consumer or is removed.
  No third state — half-built doors are how this audit's 30-wrapper pile grew.
- **The differentiator gets the design budget.** Verification, custody and provenance
  are the pitch; today they are the *least* designed pixels (declared-action authoring
  is raw JSON textareas; execution-verified metrics are a chip reading "approved v1").
  Inverting that is the arc's point, not its polish.
- **Doc drift is fixed by the wave that touches its subject** — `FEATURES.md:392`'s
  nonexistent `AgentsAdminPanel.tsx`, `docs/UI_BACKLOG.md`'s wrong "overrides covered"
  claim, federation presented as shipped while its only door is a printed curl string.
- **The audit is a catalogue with a timestamp (2026-09-09).** Re-measure a row before
  building on it; the full inventory lives in the session's two agent reports and the
  memory file `ui-exposure-and-slop-audit-2026-09-09`.

**What is true today (measured 2026-09-09; receipts in the audit):**

- **461 backend path templates; 324 (70%) UI-reachable.** After discounting machine
  doors (UC REST, webhooks, cron, MCP seams) and deprecated aliases: ~89 live
  endpoints doorless. Fully inert planes: `/intake` (11 endpoints, zero consumers
  anywhere — Arc KI shipped its API without a door, re-paying the inert-library trap
  one level up), `/governance/caps`×3 + `/usage`×2 + `/audit/feed` (an operator cannot
  see spend or set a cap), briefing subscriptions (all five typed wrappers exist,
  zero callers), the `/learning` write half, 22 of 40 ontology paths (including the
  routing-proposal review queue and export/import), `/obs` cost-routing
  (route-mix · model-usage · prompt-weight · prompt-capture), eval graduations
  (`SystemPanel` shows the queue from a *different store* than the evidence endpoint).
- **The first five minutes are the worst five.** Default landing tab is
  `intelligence`, not `home` (`web/app/page.tsx:1387`); on the default connection
  that renders a *blank black pane* — no empty state, no skeleton (verified live:
  the DOM holds the shell and nothing else). The 3-step first-run funnel exists — on
  the Home tab a new user is never shown. Two palette destinations ("Connections",
  "Add a data source") navigate to a tab with no render branch → blank screen.
  `?layer=` is written only for Intelligence, so every other workspace's sub-layer is
  lost on reload. ⌘K search on "guardrail" finds nothing but "Ask Spotlight".
- **The slop, classed:** (1) machine exhaust as user text — run cards titled with the
  scheduler's prompt preamble (`aughor/automations/temporal.py:81`), 392 Playbook
  rules titled by snake_case keys, eval suites named "…(Wave H)", a Briefing tile
  pairing a concentration sentence with the number "2014", raw `0.315801`,
  "1 entities"; (2) lying states — Catalog says "Add a connection to get started"
  beside 7 live connections, the Documents banner alarms while narrating agreement
  (`DocumentUploader.tsx:435` narrates one metric, triggers on another), the empty
  Inbox congratulates work never done; (3) inverted investment — Actions authoring is
  JSON textareas, Health is a nav slot holding one sentence, document upload leads
  with chunk-delimiter parameters.
- **What is NOT broken:** the token/design system (Arc DS; ratcheted), Agent Ops
  (honest footnotes, real control-room judgment), the SQL workbench, the
  Integrations copy. The judgment exists in the codebase; it is unevenly applied.

**Waves, in build order (each small; every wave touches `page.tsx`, so they land one
at a time under the one-branch law):**

- ✅ **PX-0 · The first five minutes — SHIPPED 2026-09-09 (`2c560b55`).** Every receipt
  taken live: cold `/` lands on Home; `?tab=evals&layer=experiments` and
  `?tab=agentic-ops&layer=attention` open their layers and survive reload; both
  palette entries land somewhere real ("Add a data source" opens the form over the
  Catalog); the former landing void reads "Reading this connection's schemas…"; one
  shared `EmptyState` (four locals retired, two emoji became icons, the font ratchet
  came DOWN 1174 → 1166); eight missing palette destinations added under the
  sidebar's own words. Original spec: land on `home`; the landing void gets an empty
  state that offers the door; shared `EmptyState` primitive (four locals retire); fix
  the two broken palette targets; write `?layer=` for every workspace;
  palette↔sidebar naming parity ("Agent runs" vs "Agent history").
  **Receipt:** an incognito visit lands on Home with the funnel; every sidebar
  destination survives reload; both palette entries land somewhere real.
- ✅ **PX-1 · The language pass — SHIPPED 2026-09-09 (`5883b00b`).** `runTitle.ts`
  derives run titles display-side (fixtures are the cross-language tripwire on
  temporal.py's constants); keyFigure refuses bare years ("2014" was a live tile);
  tile prose rides the precision policy; Catalog/Documents/Inbox stop lying;
  Playbook leads with the sentence; `countNoun()` ends "1 entities". Deferred from
  this wave, honestly: eval-suite names are STORED DATA (renaming is curation, not
  rendering) and a static title-shape lint gate (the deriver's tests carry the
  contract instead). Original spec: display titles for scheduled runs (preamble stays
  model-only); Playbook rules titled for people (key demoted to metadata); eval
  suites named by purpose; number formatting (percentages, pluralization, the
  stat-tile extraction mismatch); the three lying states corrected to tell this
  deployment's truth. Where cheap, a title-shape ratchet in the claim-language
  linter's spirit: no bracketed preamble, no snake_case-only string renders as a
  title. **Receipt:** the audit's screenshot walk re-taken clean.
- ✅ **PX-2 · The governed-spend cockpit — SHIPPED 2026-09-09 (`180c0592`).**
  Operations ▸ Spend (sidebar + palette + `?tab=spend` deep link): the caps form
  vocabulary-driven from its endpoint with observed-value meters and a real delete;
  usage by provider/model with the floor-not-a-total honesty; per-model health;
  route mix; the governance feed with its category vocabulary. Live receipt: the
  cap loop end to end (declare $100/24h alert → observed meter → remove, net zero),
  and the cockpit's first real screen showed 2,369 unpriced calls and the `:free`
  models failing at 89–100% — visible for the first time. Action authoring lost its
  last two JSON textareas (typed rows are lossless). Deferred honestly: the in-chat
  door-link on a cap refusal — the refusal sentence already names the number;
  the link waits for the error class to reach one identifiable transcript surface.
  Original spec: doors for caps (`GET/PUT /governance/caps` —
  the endpoint already serves the form's vocabulary), usage + cost
  (`/usage`, `/usage/cost-sql`, `/obs/route-mix`, `/obs/model-usage`), and the
  cross-cutting `/audit/feed`. MT runs THROUGH this wave: MT-1 births orgs capped,
  and a capped org's operator must SEE the cap and raise it in-product. Same wave:
  declared-action authoring becomes a form (typed fields; JSON behind "advanced").
  **Receipt:** set a cap in the UI, hit it, and the refusal names the cap and links
  the door that raises it.
- ✅ **PX-3 · The intake door — SHIPPED FIRST 2026-09-09 (`0cd5b40c`, §6 item 13's
  knob-turn).** Semantic Layer ▸ Import; all 12 endpoints consumed; driven live end
  to end (plan → accept through governance → provenance trail → dedupe → export
  round-trip). The drive found and fixed the paste-door listing gap (a bundle
  without its own `connection_id` was invisible to the per-connection listing).
  Original spec: the KI lane's UI: upload → per-object PLAN
  (new/changed/identical/conflict) → accept/edit/dismiss → apply receipt + re-export.
  **Receipt:** the KI golden bundle driven end-to-end through the browser.
- ✅ **PX-4 · Grading made possible — SHIPPED 2026-09-09 (`a547cec9`).** Memory
  governs the full trusted-query lifecycle (seed-verifies-now, edit-resets-approval,
  propose/approve/reject/deprecate, audited remove) plus a corpus inspector with
  lineage; graduation evidence renders under each queued flag in the System panel.
  Live receipt taken exactly as this wave's line demanded: seeded through the UI,
  verification executed against DuckDB, approved (count 11 → 12, on the ledger),
  removed (audited, back to 11) — the golden count moved through the UI, not curl.
  The live graduation queue is empty because every recorded decision belongs to a
  flag that already graduated — the system working, not a gap.
  Original spec: the `/learning` write half (author, edit,
  transition, retire a trusted query; dataset detail), and eval-graduation evidence
  joined to the flag panel it currently cannot reach. This is MI-4's own bottleneck:
  the flywheel moves by grading, and grading has no door.
  **Receipt:** the golden count moves through the UI, not curl.
- ✅ **PX-5 · Verification made visible — SHIPPED 2026-09-09 (`0e23d4c2`).** The
  premise measured BETTER than drafted: the provenance substrate (source_asset,
  author, verification-outranks-authority, MetricProvenancePanel) already existed —
  the wave was pure composition. An ontology metric's verified state is the loudest
  fact on its card ("✓ executed against your database" / "unverified — demoted");
  the provenance panel reaches the ANSWER (each governed metric on a Trust Receipt
  opens "Whose definition?", live-resolved outside the signed body like the trace);
  grounding is NAMED in the agent header in the reader's words; and the agent
  surface completes Chat | Monitor | Benchmark — a Chat door that opens the
  conversation with that persona preselected. Original spec: the Genie study's
  PORT list is this wave:
  a provenance panel on an answer ("this used <author>'s definition from <asset> —
  executed against your database"); verified/demoted state loud on metrics —
  `OntologyMetric.verified` is the one thing we hold that Databricks does not claim,
  rendered today as a chip; grounding named in an agent's description; the
  `Chat | Monitor | Benchmark` agent surface (pure composition — every endpoint
  exists). **Receipt:** a screenshot of an answer that shows *why* it is trusted.
- ✅ **PX-6 · Consolidation and the sweep — SHIPPED 2026-09-09 (`256f56f4`).**
  The sweep: 22 dead wrappers deleted (re-verified at zero callers; two had gained
  callers and stay), SearchOverlay + three unimported components + SchemaCards
  gone, both ratchets DOWN (fonts 1164 → 1120, buttons 69 → 64). Wired instead of
  deleted: scheduled briefing delivery (the Briefing's Schedule card) and orphan-
  chunk purge (beside the sentence that used to apologize for it). The ontology's
  human-edit ledger shipped (overrides list/revert · routing-proposal inbox ·
  export/import — 61 files exported live with the receipt on screen). **Premise
  correction, recorded rather than built through:** the seven activity surfaces
  measured as views over FOUR data planes (/investigations · session_events · the
  SQL audit log · eval runs) — a merge would have fused planes, so the shared pair
  got one cross-link ("Machine view: traces & spans →" from Agent runs into Agent
  Ops ▸ Activity) and the rest keep their jobs. Doc drift fixed (FEATURES.md
  filename, UI_BACKLOG overrides row, the federation curl-string replaced by an
  honest sentence naming its experiment flag).
  Original spec: seven run/activity surfaces become one
  Activity with lenses (each retired surface's distinct capability named and kept —
  the DS-1 P2 lesson: a premise can lapse mid-build); the ontology depth doors worth
  having (routing-proposal inbox, overrides list/revert, export/import); the
  wire-or-delete sweep over the 30 dead wrappers, 3 unimported components and the
  never-rendered `SearchOverlay`; the doc-drift fixes.
  **Receipt:** the reachability audit's orphan and dead-code tables re-run empty.

**Deliberately out of scope (not refused — just not this arc):** a visual redesign or
rebrand (the token layer is not the problem); rewriting `page.tsx` into App Router
routes (the NavTab contract works — fix the contract, not the architecture); UI for
machine doors (UC REST, webhooks, `/cron/tick`, the MCP seams — consumed elsewhere by
design); the `/consistency` plane's UI while its flag is default-off (it graduates
first, per the eval plane's own law); federation UI while `federation.planner` is an
experiment (but the curl-string in Add Data goes, per the language law).

**Risks, carried in rather than discovered:** (a) display-title derivation drifting
into changing stored fields — the first law forbids it, tests pin emission; (b) IA
consolidation is where regressions hide — PX-6 is LAST for a reason and each retired
surface needs its capability inventory first; (c) an arc about "polish" invites scope
creep — every wave has a receipt that is a *behavior*, not an adjective, and a wave
with no receipt left to take is done.

### 3.15 · Arc ON — the ontology the agent runs ON (drafted AND adopted 2026-09-10 — §6 item 14, all four clauses YES; **ON-0 STARTED** the same day)

> **Origin.** The user's 2026-09-10 challenge, verbatim: *"I feel the ontology that we have
> is just a Fancy representation of the ERD of the schema. I don't know how our ontology
> structure makes sense in an agentic data intelligence platform, do we use it to improve
> the context of the agents that explore the Data and synthesise it? Is our ontology as a
> module actionable or interpretable for the Agents in their runtime? I strongly feel we
> need to rethink what we have built, why we have built it and are we even integrating it
> the way it's meant to be integrated."* With five references: Foundry's ontology
> core-concepts, applications, models and why-ontology pages, and MotherDuck's
> context-layer-vs-semantic-layer-vs-ontology essay.
>
> **How this was measured.** Code first, prose second (§7). Every claim below carries a
> `file:line` re-read on 2026-09-10 against `main` at `1f71f47`. The two external hosts
> were unreachable from the drafting environment (egress-blocked); Foundry's vocabulary
> is taken from this repo's own full study (`docs/PALANTIR_FOUNDRY_STUDY_2026-07-22.md`
> §1.3, §2) and from memory of the same pages, and MotherDuck's from
> `docs/MOTHERDUCK_LEARNINGS.md` + memory. **ON-0 re-verifies both against the live pages
> before ON-1 starts** — a wave must not be built on a recollection.
>
> **The verdict, in one line.** The critique is right about the NOUN layer, right about
> RUNTIME REACH, and wrong about the VERB layer — and the one measurement that exists
> says the prompt-injection strategy the ontology currently rides was a regression.

**What is true today (measured 2026-09-10):**

| The claim | Measured | Where |
|---|---|---|
| "It is the ERD, dressed up" | **True, by construction.** The builder's own comment: *"table = entity: every profiled table becomes an entity"*; `source_tables=[table]`; `table_to_entity` is 1:1; `entity_to_tables` is always a singleton. A business object cannot be born spanning two tables — only a gated, manual `entities/merge` can fuse two after the fact. Properties are copied `ColumnProfile`s (*"Sourced from ColumnProfile at build time"*). Relationships are the join map with a verb. Interfaces are name-pattern detection. | `aughor/ontology/builder.py:849-914` · `aughor/ontology/models.py:60-67` · `aughor/ontology/dedup.py:66-106` |
| "Is it interpretable by the agent at runtime?" | **As TEXT, partially.** What reaches a prompt: the ENTITY MODEL block (name · table · grain · event-time · type · lifecycle · active filter · ≤2 default filters · ≤2 exclusions · `ACTION:` template names); ENTITY RELATIONSHIPS (verified/exact joins with cardinality); the VERIFIED SEMANTIC LAYER (segments + computed properties, verified-gated, question-scoped); the metrics catalog; synonyms; routing rules; `ACTION:` expansion in the planner. **What never reaches a prompt on the answer path:** the entity `description` — the one sentence that says what the business object IS, LLM-enriched, human-editable, rendered in the UI, grep-zero in every renderer; `domain`; `implements`; `exploration_insights` (deliberately, after R4); the `EntityProperty` semantics (`null_meaning`, `value_interpretation`, `measure_grain` reach prompts from the PROFILER directly — the ontology's copy is UI-only); `DefinitionSource` provenance. And the block rides the **heavy** phase, so a fresh connection answers with none of it until `build_intelligence()` has run. | `aughor/ontology/builder.py:1052-1121` · `aughor/agent/schema_annotators.py:262,472` · `aughor/ontology/semantic_block.py` · `aughor/routers/investigations.py:1838-1868,2063` · `aughor/agent/nodes.py:658-784` |
| "Does it improve the agents' context?" | **Unmeasured since 2026-06-21, and the last measurement was NEGATIVE.** R4 (n=12, one warehouse, one model): raw 92% · guarded 92% safe · **injected 58% with 5 silent-wrong**. The doc's own conclusion: *"governed ≠ 'inject more LLM context'; governed = deterministic guards + registered metrics."* That eval predates verified-gating (M24c) and the relationship block, and measured the whole injection stack rather than the ontology alone — so today's effect is UNKNOWN, not merely small. No ontology-only arm has ever been run. | `docs/R4_ABLATION_EVAL_2026-06-21.md:40-60` · `evals/ablation_missimi_results.json` |
| "Is it actionable?" | **The verb layer is real and Foundry-shaped — and nearly empty.** `KineticAction`: typed params, submission criteria with authored messages shown verbatim to human AND model, side effects (notify · webhook · trigger_investigation · declarative `http`), risk tiers with fail-safe HIGH, graduated approval, K4b proposals attached to every deep-analysis report, the VA-9c `propose_action` tool bounded by grants, one inbox. This IS an Action Type in miniature. Population: **one** tracked declaration (`refund_orders`, description empty) + one untracked receipt on theLook. §7's complete-and-inert shape, on the arc's best idea. | `aughor/ontology/models.py` (`KineticAction`) · `aughor/actions/propose.py` · `aughor/agent/action_tools.py` · `data/ontology_overrides/workspace/default/action/refund_orders.yaml` |
| "Do agents navigate it?" | **No — humans and the UI do.** The graph's own helpers (`entity_for_table`, `relationship_index`, `actions_for_entity`) have ZERO callers under `agent/`; outside `ontology/` they are used by the router, the explorer's Phase-8 hypothesis prose, and `semantic/compiler.py`. The agent's runtime graph tools (`search_graph`, `describe_entity`) read the **context graph** (Wave C) — node kinds `table · metric · glossary_term · domain · finding · brief` — whose tracked instances are 255/262 glossary terms and 100 findings per connection with 5–15 `joins_on` edges. That is a provenance graph of findings and definitions (the citation substrate, valuable) — not a graph of business objects. | `aughor/mcp/knowledge_tools.py:87-130` · `aughor/ontology/context_graph.py:41-42` · `data/context_graph/**/*.json` |
| "Does it have instances?" | **No.** Type-level only. There is no object, no link between two objects, no "Customer 42 and her orders" anywhere in `aughor/ontology/`. Segments are WHERE fragments, not collections. Foundry's loop runs on instances; ours runs on a description of types followed by LLM-written SQL. | `grep -rn "instance\|object_id" aughor/ontology/` → 0 semantic hits |

**What is NOT an ERD, and must survive the re-think untouched** (the four things the
critique undercounts — each is something Foundry does not have, per the study's §2):

1. **Verification as a TIER, not a tiebreak.** `verified` on segments, computed
   properties and metrics is *execution against the live database*; `DefinitionSource`
   ranks an executed formula above a popular or certified one no matter who wrote it
   (`aughor/ontology/authority.py`). Genie ranks meaning; we check the arithmetic.
2. **The deterministic guard battery and the operations vocabulary.** Fan-out, additivity,
   value-domain, id-arithmetic, and `operations.yaml` — *what a concept admits and what
   it must never be used for* ("SUM of a latitude is not a quantity"). This is the "logic
   as a foundation" the user is asking for, already here — but applied AFTER generation,
   as a check, not DURING, as a constraint.
3. **The kinetic plane** (above) — built on the right law: a grant is permission to
   PROPOSE, never to EXECUTE; nothing mutates source data.
4. **The semantic compiler** — the one place the ontology is *executed* rather than
   *described*: a typed intent IR (`scalar · timeseries · breakdown · ranking`) assembled
   deterministically from verified entities, coverage-gated, single-table, falling back
   to LLM SQL when it cannot vouch. *"The LLM augments a declarative layer rather than
   regenerating SQL."* This is the seed of the whole arc. (`aughor/semantic/compiler.py`)

**The thesis.** Foundry's sentence, from our own study: *the ontology is simultaneously
the context store, the guardrail, and the write API for AI — agents get three tools:
query objects, execute actions, call functions.* Ours today: the context store is a
text block (partial, heavy-phase, unmeasured); the guardrail is post-hoc; the write API
is one YAML file with an empty description. **The arc turns the ontology from a thing
the agent reads ABOUT into a thing the agent runs ON.** Three moves, each a wave:
the noun decouples from the table (ON-1); the agent's primary door becomes a compiled
object query in which the guards hold *by construction* (ON-2); the verb layer acts on
objects and its edits are visible to the next answer (ON-3/ON-4). MotherDuck's frame is NESTING, not competition — each layer contains the one before (re-verified 2026-09-10 against the published summary; the page itself stays egress-blocked here): the **semantic layer** (metrics, dimensions — we have it) ⊂ the **ontology** (objects, links, operations — ON-1…ON-5) ⊂ the **context layer** (definitions, quirks, caveats, owners, freshness, what an agent may surface — we store most of it and render almost none; ON-6). Their sentence for agents: *a semantic layer grounds queries in correct data; an ontology grounds reasoning in correct relationships; the context layer serves agents executing multi-step workflows.*

**Laws that bind every ON wave (standing, not per-slice):**

- **Measure before, ratchet after.** ON-0's harness runs before any wave and after every
  wave; a wave whose arm regresses the ratchet does not ship, whatever its receipt. The
  R4 lesson is the arc's founding lesson: more context is not more correctness.
- **Live resolution, never a copy of the warehouse.** An object is a backing query
  resolved at read time; no object store, no sync, no Phonograph. DuckDB + pushdown is
  the bet (§4, §8). Reopen only on a measured latency that a cache cannot cover.
- **By construction beats by guard — and the guard stays for the escape hatch.** A link
  traversal in the compiled path pre-aggregates the N side because the *link* carries
  measured cardinality; a semiadditive measure cannot be summed across periods because
  the *declaration* forbids it. `run_sql` remains (this is not Foundry — the human plane
  is SQL, §0) and the battery guards it exactly as today.
- **The read-only law is untouched.** An action edits an OVERLAY keyed to an object;
  source data is never written (`security/safety.py`, `sql/readonly.py` stay
  fail-closed). Foundry materialises edits back into datasets; we deliberately do not.
- **Nothing the model says becomes a fact.** J4 holds: an object type, link, property
  binding or derived value exists only with provenance — schema, probe, human, function,
  or `model:<id>@<version>`. There is still no `llm_inferred` provenance.
- **API names are stable; display names are free.** A rename never breaks a consumer
  (Foundry's one rule worth copying verbatim). Today's entity ids ARE table names — ON-1
  gives every type an `api_name` and keeps the id as its default.
- **Supersede, do not delete.** The one-table entity becomes the default backing of its
  type; every cached graph, override file and `GET /ontology/*` payload deserialises
  unchanged. The ERD is a VIEW of the ontology, never its definition again.
- **The catalogue rots** — every "true today" cell above carries its date; each wave's
  pre-check re-measures its own row.

**Waves, in build order** (ON-0 is not optional; the order after it is the user's knob):

- ✅ **ON-0 · Measure what the ontology is worth — STARTED 2026-09-10** (the user's
  *"start ON-0 now"*; the deterministic half landed the same day, the LLM half ran the
  same evening on `samples/ecommerce` (a ceiling) and on the re-authored LuxExperience hard
  set (no lift); the falsifier's honest reading is in that receipt — the user decides).
  **Receipts, 2026-09-10:**
  - **Prompt reach, measured** (`aughor/ontology/prompt_reach.py` — a field reaches a
    block iff changing it changes the block's text; one fixture graph with every
    renderer gate open; the seven pure renderers on the answer path). **59 of 142
    fields reach at least one prompt block; 83 reach none.** By model: OntologyGraph
    0/11 · OntologyEntity 13/19 · Segment 3/8 · **EntityProperty 0/19** · ComputedProperty
    4/6 · OntologyRelationship 11/13 · OntologyMetric 15/16 · **DefinitionSource 0/9** ·
    QueryTemplate 5/11 · ActionParameter 4/12 · KineticAction 3/9 · SubmissionCriterion
    1/2 · SideEffect 0/2 · **OntologyInterface 0/5**. Named unreached: `entity.description`,
    `domain`, `use_instead`, `implements`, `exploration_insights`; every `EntityProperty`
    field (`null_meaning`, `measure_grain`, `value_interpretation`, the percentiles…);
    every `DefinitionSource` field (the provenance the metric card shows and no model
    sees); `Segment.description`; `QueryTemplate.sql_template` and its parameters (by
    design — the planner sees the NAME and the runtime expands it); `SubmissionCriterion
    .message` (by design — the authored sentence reaches the model only after a failed
    proposal); `KineticAction.risk`, `entity`, `side_effects`. Two corrections to this
    section's own prose, earned by measuring: (1) `entity.description` IS rendered on
    one path — the explorer's Phase-8 hypothesis prose (`explorer/agent.py:2605`), an
    exploration prompt, not an answer prompt; (2) `lifecycle_column` reaches exactly one
    block, the deep-analysis baseline plan. **Ratcheted:**
    `tests/unit/test_ontology_prompt_reach.py` pins the 59 (reach may grow — that is
    ON-6's job — never silently shrink) and refuses a collapsed walk. To make it
    measurable, the deep-analysis intake block was extracted from `agent/investigate.py`
    into `ontology.semantic_block.render_entity_context`, byte-identically (tested); the
    planner's APPROVED METRIC FORMULAS and the explorer's Phase-8 prose remain inline
    and are named as such in the audit's output.
  - **Kinetic census:** `python -m aughor.ontology.prompt_reach --census` → **1**
    declared action in the tracked tree (`workspace/default/refund_orders`, description
    empty). The live per-connection number is the user's instance's to take.
  - **The harness, rebuilt** (`evals/ablation_eval.py`): five arms — `raw` · `guarded` ·
    **`ontology`** (raw schema + ONLY the verified ontology blocks, rendered by the same
    three functions the product uses) · **`ontology_guarded`** (do the blocks make the
    guards fire LESS — by-construction beating by-guard, counted) · `injected`;
    `--arms` to spend fewer tokens, `--dataset` repeatable for ≥2 connections, and every
    reference SQL (and `accept_sql`) is EXECUTED before any model call — a failed
    reference is skipped and named, never scored, never spent on. 🔴 **Found by running
    it: the R4 harness had not been runnable since June** — its `_parse_schema_tables`
    import died in a rename nobody re-ran the eval to notice. Fixed; a harness nobody
    re-runs is the ledger's lesson, in code.
  - **Two harder sets.** `evals/ablation_missimi_hard.jsonl` — 11 questions: cross-grain
    joins, ratios, ratio-of-sums, lifecycle, a named segment, a nullable-FK anti-join,
    and a CORRECT N:1 join the model must not refuse (references execute only on the
    user's warehouse; h08 and h11 state the assumption each carries).
    `evals/ablation_samples_ecommerce.jsonl` — 12 questions on the deterministic bundled
    sample warehouse every install has; **all 12 references executed here**; its
    value-domain trap is the mirror image of missimi's (`cancelled`, two Ls) and its
    lifecycle has THREE terminal states.
  - **Re-verification of the references** (pages egress-blocked; published summaries via
    search): Foundry — object type · property · link type · action type; *semantic* =
    object + link types, *kinetic* = action types + functions; a function is typed logic
    (TypeScript/Python) for validation rules, derived values and action side effects;
    live model inference rides a function-wrapped model deployment. MotherDuck — the
    three layers are NESTED (semantic ⊂ ontology ⊂ context), which corrected the
    thesis paragraph above. Nothing in either summary contradicts the waves as drafted;
    the full pages still deserve one read by someone with access before ON-1.
  - **The LLM half — RUN 2026-09-10 on `samples/ecommerce`** (12 questions · arms `raw`,
    `guarded`, `ontology`, `ontology_guarded` · `gemini` / `gemini-3.1-flash-lite` ·
    fallback chain pinned to none · every store redirected to a scratch dir · the arm fed
    the graph `GET /ontology` serves). Receipt: `evals/ablation_on0_ecommerce_results.json`;
    the served graph is committed beside its dataset as
    `evals/ablation_samples_ecommerce_ontology.json` (built 2026-07-02, enrichment v5) so
    the arm reproduces without an instance:
    `AUGHOR_SYSTEM_DB=/tmp/scratch/system.db AUGHOR_FALLBACK_BACKENDS=none uv run python
    evals/ablation_eval.py --dataset evals/ablation_samples_ecommerce.jsonl --arms
    raw,guarded,ontology,ontology_guarded --graph-json
    samples/ecommerce=evals/ablation_samples_ecommerce_ontology.json` (redirect EVERY
    `AUGHOR_*_DB` beside a serving API — the list is `tests/conftest.py`'s).

    | arm | correct | silent-wrong | error | guards fired |
    |---|---|---|---|---|
    | raw | 12/12 | 0 | 0 | — |
    | guarded | 12/12 | 0 | 0 | 0 |
    | ontology | 12/12 | 0 | 0 | — |
    | ontology_guarded | 12/12 | 0 | 0 | 0 |

    **A ceiling, not a lift — the falsifier is NOT decided by this run.** The block
    (3,756 chars beside a 3,831-char schema: 5 verified N:1 joins, 3 segments, 6 computed
    properties, 14 ACTION templates; grain unverified on all 5 entities) changed the SQL
    text on 5 of 12 questions and the answer on none; no guard fired on either side
    because nothing in this set made this model fan out. "No lift" at 100% raw says
    nothing about the ontology and everything about the set. 🔴 **The set that could
    discriminate is gone: `workspace/missimi` no longer exists on this instance** — the
    live workspace lists 11 schemas and no `missimi`, there is no upload directory for
    it, no ontology was ever built for it (built: amazon, default, scm); only June
    backups of its exploration prose survive. `ablation_missimi.jsonl` and
    `ablation_missimi_hard.jsonl` — 23 of the 35 questions, every cross-grain,
    ratio-of-sums and anti-join trap — skip at the reference check. **Decided the same
    night (the user: "re-author the hard set against amazon") — and the offer of `amazon`
    or `scm` was wrong, measured before a line was written:** `workspace/amazon` is ONE
    table (1,465 product-review rows; `discounted_price` and `actual_price` imported as
    INTEGER and ALL NULL — the ₹-prefixed strings never survived the cast; `product_id`
    is the ontology's "verified" grain and repeats on 114 rows) and `workspace/scm` is ONE
    table (100 rows, grain "Product type"). Neither has a join, a lifecycle or a nullable
    key, so neither can host a cross-grain trap; both were offered on the strength of
    having an ontology, not a shape. The host that can: **LuxExperience
    (`914df862/luxexperience`, the demo pack — `docs/DEMO_PACK_DESIGN.md`)** — 14 tables,
    706,894 rows, an ontology built 2026-09-05 with 11 verified joins, two lifecycles and
    named segments; the API holds the file read-only, so a second read-only open beside it
    is safe. ON-1/ON-2 proceed regardless, as the falsifier already says.
  - **The hard set, re-authored on LuxExperience — `evals/ablation_luxexperience_hard.jsonl`,
    14 questions, references verified, RUN the same night (twice; the receipt follows).** Every trap was measured to bite
    before it was written — the reference and the plausible-wrong answer differ on the
    data: `grain` womenswear 84,024 lines vs 63,831 orders · `value_domain` 'cancelled'
    4.03% vs 'canceled' 0 · `fanout` returned-GMV share 39.98% vs 46.47% joined, GMV of
    orders with a return 18.17M vs 21.36M joined · `ratio_of_sums` shipping cost 7.76% of
    GMV vs 15.75% as an average of row ratios · `lifecycle` 3,069 'reject' vs 0 'rejected'
    · `nullable_fk` 4,536 never shipped vs 0 through an inner join · `ratio` ticket
    coverage 0.10 vs 1.0 over joined rows · `cardinality` captured payments by method
    inflated ~50% through order_items. Two candidates were DROPPED for not biting: "which
    category appears in the most orders" (the same winner by lines and by orders) and a
    refund-to-price ratio (every refund is full). Every `accept_sql` was executed and
    compared with its reference; the two that differ by design (GMV by channel; the
    percentage form of a fraction) are alternative correct answers, not tolerances — the
    scorer rounds to four places and matches sets exactly. 🔴 **What the block will teach
    there, rendered by the product's own functions (5,901 chars beside a 13,925-char
    schema): four joins labelled N:N that the data shows are N:1 or 1:1** —
    `order_items → orders`, `order_items → payments`, `order_items → shipments`,
    `return_logistics → returns` (first counted as five: `customer_service → orders` joins
    on customer_id and is genuinely N:N — corrected by ON-0a's measurement) — under a CARDINALITY
    sentence that tells the model an N-side join multiplies rows. The validator verified
    that the KEYS overlap (100%); the cardinality was never measured against the row
    counts. `l14_captured_by_method` is written to that claim, and the run will say
    whether a wrong verified claim hurts — the falsifier's own question, sharpened.
    Harness door, ratcheted: a record may carry `duckdb_path`, so the set opens its file
    read-only instead of the registry — a served store a hermetic run redirects, where a
    REGISTERED id resolves to nothing (found by running it: `KeyError: '914df862'`; the
    builtins never hit this). The served graph is committed beside the set as
    `evals/ablation_luxexperience_ontology.json`. The command: `AUGHOR_FALLBACK_BACKENDS=none`
    + every `AUGHOR_*_DB` redirected + `uv run python evals/ablation_eval.py --dataset
    evals/ablation_luxexperience_hard.jsonl --arms raw,guarded,ontology,ontology_guarded
    --graph-json 914df862/luxexperience=evals/ablation_luxexperience_ontology.json --output
    evals/ablation_on0_luxexperience_results.json`.
  - **The run — 2026-09-10 22:57, `gemini` / `gemini-3.1-flash-lite`, fallback none, every
    store redirected, `--graph-json` + `duckdb_path`, 28 calls, 113 s of model time.** Run 1
    (22:53) is kept as `evals/ablation_on0_luxexperience_results_run1.json`; run 2 is the
    receipt, `evals/ablation_on0_luxexperience_results.json`.

    | arm | correct | caught | silent-wrong | guards fired |
    |---|---|---|---|---|
    | raw | 13/14 | — | 1 | — |
    | guarded | 13/14 | 1 | 0 | 2 |
    | ontology | 13/14 | — | 1 | — |
    | ontology_guarded | 13/14 | 1 | 0 | 2 |

    **Ontology vs raw: gains [], losses [] — NO LIFT, on the set built to show one.** The
    block changed the SQL text on 9 of 14 questions and the class on none. The one miss is
    the same on both arms: `l13` (AOV and items per order by platform) — both joined
    order_items and summed `gmv_eur` once per LINE (MR PORTER's AOV comes out at
    803.41 EUR against 468.56); the fan-out guard caught it on both sides and its rewrite
    did not bind, so the product would have shown a flagged answer, never a silent one.
    That is the join the block labels `order_items → orders [N:N]` — so its own CARDINALITY
    sentence ("pulling the N side into a query grained on the 1 side multiplies rows —
    pre-aggregate") said nothing on the exact question where it could have. `l14`, written
    to the wrong N:N claim on payments, was answered from `payments` alone by both arms:
    the model did not follow the block into a fan-out either. Run 1 (raw 12/14, ontology
    12/14) differed by one question, `l05`, which failed on an ambiguity in the question as
    I wrote it (carrier cost vs customer fee; `status = 'shipped'` vs has-a-shipment) —
    every legitimate reading was executed and added to `accept_sql` before run 2, the
    question's fault, not the model's, and its pitfall says so (`l13` likewise now accepts
    a 2-place rounding of items per order; its AOV is wrong regardless). The fan-out guard
    also flagged two 1:1 joins whose answers were RIGHT (`shipments → orders` on `l05` raw
    and `l09` ontology) — a false positive it cannot see through without measured
    cardinality, the block's defect seen from the other side.
    **The falsifier, read honestly.** As written it FIRES — "no lift or a regression ⇒
    prompt injection retired for the ontology, ON-6 cancelled". Two things weigh against
    acting on it tonight. (1) The block under test carried four wrong verified labels, and
    the one question the ontology could have won is the one those labels blanked: this
    measured a corrupted block, not the verified layer the arc proposes. (2) n = 14 on one
    model with raw already at 13/14: the set discriminates the GUARDS (one save, zero
    regressions, in both runs) far better than it discriminates prose. What it does
    establish: on this model, verified blocks that are RIGHT (the seven joins the data confirms, two
    lifecycles, the segments) changed no answer on 13 questions the raw arm already had.
    **The decision is the user's (§6):** retire ON-6 on the falsifier as written, or
    measure relationship cardinality first (chip filed — the validator verifies key
    OVERLAP, never cardinality against row counts), rebuild the LuxExperience ontology,
    re-run, and decide on a block that says true things. ON-1/ON-2 proceed either way.
    ✅ **Measured 2026-09-11 (ON-0a's re-run):** on the block that says true things the ontology
    arm again gains nothing — 13/14 against raw 14/14, the one loss caught by a guard — so the
    falsifier fires on both blocks; the recommendation is to retire ON-6 as written (see ON-0a).
    **The premise was wrong, too:** the run never waited on a key. The instance was keyed
    all along (Gemini, via `data/llm_config.json`, which outranks the `.env` OpenRouter
    lines — those are dead letters). What actually blocked it: the ontology store IS
    `system.db`, so a bare run beside the serving API either opens the served store (the
    corruption precondition) or, redirected, finds no ontology and silently runs raw twice.
    **One thing the run did measure:** the served ecommerce ontology says Order has TWO
    terminal states (`delivered`, `cancelled`) and its "Active Orders" segment encodes
    that; the data has THREE (`refunded`, 500 rows — 1,400 open orders by the data, 1,900
    by the ontology). The model answered s05 correctly on BOTH arms: it read the status
    values off the schema and did not trust the block. A verified block that is wrong and
    ignored is the worst case — it is on the prompt (`terminal_states` reaches ENTITY
    MODEL, per the reach audit) and it is not load-bearing. The validator proves a segment
    EXECUTES, not that it is TRUE; ON-1's measured cardinality needs a sibling for lifecycle.
    **Harness, three fixes found by preparing the run** (ratcheted in
    `tests/unit/test_ablation_guards.py`): (1) the results never recorded which model
    answered — `summary.llm` now carries backend, model and the fallback chain, and the
    header prints them; (2) an `ontology` arm with an empty block was still spent on — the
    ontology arms are now DROPPED, not run, and the summary says so; (3) `--graph-json
    conn/schema=file` feeds the arm the graph the API serves, the door a redirected store
    needs. Run log: one transient Gemini retry (s09), 94.5s of model time across 24 calls.
  Original spec: Re-run the
  R4 harness on TODAY's stack with the ontology as its own arm — `raw` · `+guards` ·
  `+verified ontology blocks` · `+full injection` — on a harder set (forced cross-grain
  joins, ratio metrics, lifecycle questions, "active" semantics) across ≥2 connections;
  add a per-field **prompt-reach audit** (which `OntologyEntity`/`EntityProperty` fields
  reach any prompt on the answer path, counted, not recalled) and a **kinetic census**
  (declared actions per live connection). Re-verify the Foundry and MotherDuck pages
  against the drafting recollection above and correct this section in place.
  **Receipt:** a dated table in this section; the harness wired as the arc's ratchet.
  **Falsifier:** if the verified-ontology arm shows no lift or a regression, the
  prompt-injection strategy is retired for the ontology (blocks stay only where a
  guard cites them) and ON-6 is cancelled; ON-1/ON-2 proceed regardless, because the
  compiled path does not depend on the model reading prose.
- **ON-0a · The core the business extends — DRAFTED 2026-09-10, first commit BUILT the same
  night** (the user: *"standardize
  the semantic core; allow businesses to extend it"*; sits between ON-0 and ON-1 in build
  order, and gives ON-0's open decision its build shape). A pack gains an approximate map
  of its industry, and the builder treats every entry in it as a **claim to measure,
  never a fact to render**. Four parts, all approximate by design and none of them prose:
  (1) **expected object types** with the roles they play — `Order`, `OrderItem`,
  `Payment`, `Shipment`, `Return` … — matched to this schema's tables by the builder
  (the alignment is proposed by the model, shown, and overridable like every other
  override; `Pack.entities` / `RoleSpec` is the seed of this and already exists);
  (2) **expected links** with an expected cardinality and nullability — `OrderItem →
  Order` N:1 · `Order → Shipment` 0..1 · `Order → Payment` 0..1 before capture — each
  one an obligation to count `COUNT(*)` against `COUNT(DISTINCT key)` on both sides and
  to count the orphans: the measurement the validator never made, which is how five N:1
  joins reached the prompt labelled N:N (the ON-0 receipt above); (3) **expected
  lifecycles** with terminal states and ordering rules — `Order.status` has terminal
  states, a refund or return state is expected, `shipped_at` precedes `delivered_at` —
  each an obligation to read the column's observed domain, flag unclassified values, and
  test "no later transition" where a `<state>_at` column exists: the measurement that
  would have caught `refunded` (500 rows) missing from the samples ontology; (4)
  **value-domain aliases**, marked business-specific and EMPTY in the core — the core
  declares that `country` has aliases, never what they are (`DACH` is not Germany).
  **Layering** rides the pack `extends` chain that already exists: `core-ecommerce` ←
  `fashion` (season, collection, size, brand tier) ← the company. LuxExperience is the
  fashion case sitting on this instance; the samples warehouse is the core case.
  **Laws.** Every entry is `expected` until measured and carries its provenance (core ·
  pack · measured · human); a measured fact beats a core claim and a human override
  beats both (§6: verification trumps authority); an entry that measures FALSE is
  rendered nowhere and shown in the panel as a contradiction, never silently dropped;
  the reach ratchet is the gate — nothing from the map reaches a prompt block except
  through the same verified tier the semantic layer uses today; the core stays small
  (ten to twenty object types per industry) and versioned, because pack playbooks bind
  to its names. Standardize the grammar and the obligations; the business supplies the
  facts.
  **Build.** The pack model gains `PackOntology` (object types · links · lifecycles ·
  aliases) beside `metrics` and `playbooks`; the builder consumes it as a prior — match,
  then measure; the validator gains the two measurements the open chips name
  (relationship cardinality against row counts · terminal states against observed
  transitions) — those chips ARE this wave's first two commits and stand on their own
  without a pack; one bundled `core-ecommerce` pack and one `fashion` extension; the
  ablation harness gains a builder arm (`--builder with-core|without-core`).
  **Receipt:** the LuxExperience ontology rebuilt with the core — the four N:N labels
  become N:1 / 1:1 by measurement (✅ done, first commit below), or the wave has failed at
  its first step; the samples
  ontology's terminal states gain `refunded`; a dated count of claims by tier (expected
  · measured-true · measured-false · human) per connection; and ON-0's hard set re-run on
  the block the core-built ontology produces — that re-run IS the user's open decision
  on ON-6, made on a block that says true things.
  **Falsifier:** if a core-built ontology carries no more measured-true claims and no
  fewer wrong labels than a bare build on the same schema, the map is documentation and
  the wave stops at the validator measurements (which stand on their own); if the re-run
  still shows no lift or a regression on the ontology arm, ON-6 is retired on that
  evidence and the map's value is confined to ON-2's compiled path — where a measured
  cardinality is a compile-time law, not a sentence.
  **Not this:** a prose block per industry; a reference model (FIBO, FHIR and the TM
  Forum SID are quarries, not adoptions); an alias table shipped in the core; a runtime
  (RDF/OWL, property graph — three studies, one verdict: port the levers, refuse the
  runtime).
  ✅ **First commit, 2026-09-10 — relationship cardinality is measured at build time.**
  `aughor/ontology/cardinality.py`: a side is "1" iff its key is unique over its non-null
  rows (`COUNT(*)`, `COUNT(col)`, `COUNT(DISTINCT col)` — exact, one scan per side); the
  label reads from:to like the prompt's own sentence; a contradicted label is REPLACED and
  the authored one survives in `cardinality_note`; an unmeasurable edge (empty or missing
  table) keeps its label and says why. Hooked into the build right after the join-value
  pass, in the same connection, so every rebuild measures; `python -m
  aughor.ontology.cardinality --graph-json … --duckdb … --out …` measures a served graph
  offline. Ratcheted in `tests/unit/test_relationship_cardinality.py`: the committed
  LuxExperience fixture must still carry the four wrong labels; a hermetic warehouse with
  the demo file's key uniqueness must flip exactly those four and leave the three genuine
  N:N edges alone; the rendered block must then say `[N:1, verified` where it said N:N.
  **Measured on the real files:** LuxExperience 11 relationships → 7 confirmed, 4
  relabelled (`order_items → orders/payments/shipments` N:N→N:1, `return_logistics →
  returns` N:N→1:1), 0 unmeasurable. **The samples "control" was not a control:** 5
  relationships → 3 relabelled. `customers → orders` and `customers → reviews` were stored
  PK-side-first, so their N:1 read left→right as "many customers per order"; the data says
  1:N. `order_items → reviews` is N:N (an order can carry several reviews), not N:1. The
  builder's `_infer_cardinality` assumes the from side holds the FK and orients the label
  on that assumption; the measurement is orientation-aware by construction. Both measured
  graphs are committed beside their served ones (`evals/ablation_*_ontology_measured.json`).
  Prompt-reach walk 142 → 144; the two new fields reach no block by design — the renderer
  reads the corrected `cardinality`. **A no-model door for graphs already built:**
  `POST /ontology/measure?connection_id=…&schema_name=…` (gated like every ontology edit)
  measures the cached graph against the live connection — both measurements below — saves
  it under the graph's own key, invalidates the enriched-schema cache that embeds the
  blocks, and journals `ontology.measure`; an instance sees true labels without spending a
  rebuild. Applied on this instance 2026-09-11 to LuxExperience, samples, and the DWH
  connection's `ecommerce` graph (6 joins → 3 relabelled: `customer → orders` N:1→1:1,
  Olist's one-customer_id-per-order; `order_items → order_payments` and `→ order_reviews`
  N:1→N:N).
  ✅ **Second commit, 2026-09-11 — lifecycle terminal states are measured at build time.**
  `aughor/ontology/lifecycle.py`. What a snapshot can prove: an observed state the lists
  never named, and a claimed terminal state whose `<state>_at`-style timestamp is set on
  rows now in another state (they left it) — either sets `lifecycle_verified=False`, and
  the segment derived from the terminal set (the active filter) is downgraded, so the
  VERIFIED SEMANTIC LAYER stops offering a filter the data refutes. What it cannot prove:
  that a state is final — so an observed state whose NAME is an end state in the core map
  (`refunded`, `returned`, `rejected` …) and is missing from `terminal_states` is reported
  as UNCONFIRMED, rendered beside the claim in ENTITY MODEL as `lifecycle check: …`, never
  as a verdict; the pack will own that list (part 3 of this wave). Hooked beside the
  cardinality pass; the same CLI shape. Ratcheted in
  `tests/unit/test_lifecycle_measurement.py` (the verdicts, the downgrade, the rendered
  check, the samples fixture's omitted `refunded`, the Lux lifecycles). **Measured on the
  real files:** samples `Order` — six observed states all listed, nothing refutable,
  `refunded` (500 rows) unconfirmed; LuxExperience `Payment` — `refunded` (42,941 rows)
  unconfirmed against a terminal set of `failed` alone; `ReturnLogistic` clean.
  Prompt-reach walk 144 → 146; `lifecycle_note` and `lifecycle_verified` now reach ENTITY
  MODEL (recorded). 🔑 The samples case this wave was drafted on is NOT a contradiction the
  data can prove — no order ever leaves `refunded`, but no column says so either. The
  honest verdict is "unconfirmed, 500 rows", and that is what the block now says.
  ✅ **Third commit, 2026-09-11 — the pack section: the map as claims, measured.**
  `PackOntology` (`ontology.yaml`: objects with roles and aliases · links with the
  cardinality the data must confirm and the key they are expected on · lifecycles with
  terminal states and the END-STATE NAMES · aliases the core declares and leaves EMPTY)
  loads beside metrics and playbooks; `packs/core-ecommerce` (11 objects, 10 links, 4
  lifecycles, 3 empty alias fields) and `packs/fashion-ecommerce` (`extends:
  [core-ecommerce]`; adds Brand, Season, Collection, Variant, 4 links, 2 alias fields)
  ship as authored packs. `aughor/packs/ontology_map.py` resolves the `extends` chain
  (parents first, a child replaces by name), matches objects to entities deterministically
  (ids, display names, table stems, aliases — never a model call, never double-booked),
  and evaluates every entry into a `CoreClaim` on the graph with a tier — `expected` ·
  `measured-true` · `measured-false` · `human` — and its provenance (`pack:<id>`); a link
  is compared on the expected KEY (a built join on another key is a different link) and
  oriented before it is compared. The end-state names moved out of code:
  `lifecycle.default_end_state_names()` reads the core pack; the in-code set is the seed
  of last resort. Packs DEPLOYED on a connection apply at build time; the door takes
  `pack=<id>` to evaluate one explicitly. Nothing from a claim reaches a prompt — the walk
  grew 146 → 147 and `core_claims` reaches no block, by design. Ratcheted in
  `tests/unit/test_pack_ontology_claims.py`. **Measured on the real files — the dated
  count of claims by tier this wave asked for:** LuxExperience × fashion-ecommerce: 12
  measured-true · 27 expected · 0 measured-false, 9 objects matched. samples ×
  core-ecommerce: 10 measured-true · 21 expected · 0 measured-false, 5 matched. The DWH
  connection's Olist-shaped `ecommerce` × core-ecommerce (live, through the door): 11
  measured-true · 19 expected · **1 measured-false** — `Order → Customer` expected N:1,
  measured 1:1 (Olist mints a `customer_id` per order; the person is `customer_unique_id`).
  The core's expectation is wrong for that warehouse and the data wins, recorded as such —
  the first claim the tier system was built for. What the
  expected tier says, honestly: on LuxExperience the builder never found `orders →
  customers`, `payments → orders`, `shipments → orders` or `returns → orders` — it linked
  everything through order_items — and never marked `orders.status` as a lifecycle though
  the column is there (shipped / returned / cancelled); Product → Brand is a string, not
  a key. The map's value on this instance is exactly that list: the joins and lifecycles a
  rebuild should look for. The claims are recorded on both measured fixtures. Trimmed from
  the draft: the harness `--builder` flag (two `--graph-json` inputs already are the two
  arms) and the `human` tier, declared but not yet written (the overrides tree does not
  say which claims it settled). **The re-run — DONE 2026-09-11** (the user:
  *"run both measurements"*): ON-0's hard set on the block the measured graph renders
  (`--graph-json 914df862/luxexperience=evals/ablation_luxexperience_ontology_measured.json`),
  `gemini` / `gemini-3.1-flash-lite`, fallback none, every store redirected, in one run beside
  ON-2's objects arm so both read the same raw baseline. Receipt
  `evals/ablation_on0a_luxexperience_measured_results.json`:

  | arm | correct | caught | silent-wrong | guards fired |
  |---|---|---|---|---|
  | raw | 14/14 | — | 0 | — |
  | guarded | 14/14 | 0 | 0 | 0 |
  | ontology | 13/14 | — | 1 | — |
  | ontology_guarded | 13/14 | 1 | 0 | 2 |

  **Ontology vs raw: gains [], losses [l13] — the block that says true things lifts nothing
  either.** The one loss is the question the measured labels were meant to win: `l13` (order value
  and items per order by platform). Raw answered it this run (it missed it in run 2 — at n = 14 one
  question flips between runs); the ontology arm summed order GMV across order lines, and the
  fan-out guard caught it. Across both blocks — four wrong N:N labels, then every label measured —
  the ontology arm has gained nothing in 28 question-runs and lost one, while the guards kept every
  arm safe. **The falsifier, read on a block that says true things: it fires.** ON-0's sentence and
  this wave's say the same thing — prompt injection is retired for the ontology (blocks stay only
  where a guard cites them) and ON-6 is cancelled; the map's value is the measured claims, the
  compiled path's laws and what a person reads in the panel. The caveat, carried: one model, raw at
  ceiling, so the set measures "does the block hurt" better than "can it help". **The call is the
  user's; the recommendation is to retire ON-6 as written.**
- ✅ **ON-1 · The noun decouples from the table — FIRST SLICE BUILT 2026-09-11.** What
  shipped: every entity carries a stable `api_name` (`OrderItem` → `order_item`, never
  the table's spelling; a set name is never overwritten) and a `backing` — its table by
  default, filled from `source_tables[0]` + `identity_key` so every graph built before
  today loads with every pre-existing field byte-identical and the ERD underneath
  untouched — or a keyed SELECT a human sets through the overrides tree (`PUT
  /ontology/entities/{id}` with `backing: {kind: query, sql, primary_key}`). Every link
  has a name on each side (`order_item_to_order` / `order_to_order_item`). **The backing's
  key is measured**, the way every claim is since ON-0a: `COUNT(DISTINCT key)` over the
  backing's rows at build time and through the measure door (`backings` in its report);
  a table backing that fails the check corrects the entity's `grain_verified` — the
  builder's flag was a profile inference, and on `workspace/amazon` it read "verified"
  over a `product_id` that repeats on 114 rows. A human backing binds by dry-running its
  SELECT and earns `verified` only when a measure pass proves the key unique; the verdict
  rides the override's binding, so the overlay carries it at read time without a database
  in hand. The validator probes every computed property, metric and segment through the
  backing (`_entity_table` → the SELECT as a subquery for a query-backed object; the table,
  byte-identically, otherwise), which is what makes the receipt hold: a `Customer` backed
  by `customers ⋈ customer_profiles` with `lifetime_value` verified against the join, the
  ERD unchanged, `GET /ontology/entities` unchanged for every single-table type. Ratcheted
  in `tests/unit/test_object_backing.py`; `aughor/ontology/backing.py` holds the
  measurement and `entity_from_clause`, the seam ON-2's compiler reads. Prompt-reach walk
  147 → 156; none of the nine new fields reach a block — the prompt still names tables,
  which is ON-6's question, not this wave's. **Measured live through the door, 2026-09-11,
  four connections:** LuxExperience 14 backings unique, 13 grains CONFIRMED (the flag said
  unverified; the key is unique); samples 5 unique, 5 confirmed; `workspace/amazon` —
  `product_id` 1,351 distinct over 1,465 rows, grain REFUTED (the flag said verified); the
  DWH connection's Olist-shaped `ecommerce` — 5 confirmed and FOUR keys that are not keys:
  `OrderItem.order_item_id` is a per-order sequence, 21 distinct over 112,650 rows (the true
  grain is `order_id + order_item_id`), `OrderPayment.order_id` 99,440 over 103,886 (several
  payments per order), `OrderReview.review_id` 98,410 over 99,224 (Olist's duplicated review
  ids), `Geolocation.geolocation_zip_code_prefix` 19,015 over 1,000,163. Every one of those
  four was rendered "grain: ✓" or offered as an identity to the model before today; every one
  now reads `backing.verified = False` with the counts in its note. **Deferred from the
  draft, honestly:**
  `dedup.merge_entities` is not yet rewritten as "two tables, one backing" (it still
  concatenates `source_tables`); a query backing has no UI and no diff view; properties
  are still copied ColumnProfiles, not typed properties mapped to expressions.
  **The draft:** An `ObjectType` with a stable
  `api_name`, a **backing** (one table today; a SELECT with a declared primary key
  tomorrow — `users ⋈ customer_profiles`), typed properties mapped to columns or
  expressions, and `LinkType` as a first-class record with an API name on EACH side and
  a cardinality that is *measured* (`value_overlap` already exists — promote it).
  Interfaces stay. The builder proposes types from tables exactly as today; a human
  edits the backing through the overrides tree; `dedup.merge_entities` becomes a
  special case of "two tables, one backing". Every existing consumer reads the default
  backing byte-identically.
  **Receipt:** a `Customer` type backed by two tables with `lifetime_value` as a derived
  property, the ERD unchanged underneath, `GET /ontology/entities` unchanged for every
  single-table type.
- ✅ **ON-2 · Objects at runtime — the compiled door — FIRST SLICE BUILT 2026-09-11** (the
  user: *"Lets proceed with the roadmap!"*; branch `claude/on-2-object-query`; the conversation's
  door PARKED 2026-09-11 on a measured regression, §6 item 15(c)).
  **What shipped.** `aughor/semantic/object_query.py`: the algebra below as a typed IR
  (`ObjectQuery`: object type · segment · filters · measures with `where` and `divide_by` ·
  `by` · `time`/`grain`/window · order/limit), compiled over the backings with no model call;
  v1's `compiler.py` stays byte-identical beside it. The laws hold by construction: a link is
  traversed only when ON-0a MEASURED its cardinality — an inferred label is refused and the
  refusal names the measure door (risk (a) below, closed); a to-one link is a LEFT JOIN that
  carries dimensions, filters and the aggregates repetition cannot change (COUNT DISTINCT, MIN,
  MAX), and a SUM/AVG/COUNT across an N:1 hop is REFUSED as the fan-out it is (a 1:1 hop is
  allowed — nothing can repeat); a to-many link is pre-aggregated per key before the join, an
  average across it rolls up as a ratio of sums, a COUNT DISTINCT across it is refused; a
  condition through a to-many link is an EXISTS; N:N is refused both ways; a ratio is a ratio of
  aggregates; segment and metric fragments are re-anchored on the object's alias (sqlglot) so a
  join cannot rebind a bare column; literals are typed by the column they meet and never
  spliced; a DATE time column renders `DATE_TRUNC` for BigQuery. Every unresolved name is a
  refusal that carries the names which exist. Doors: `GET /objects/catalog` (exactly the names
  the compiler accepts — usable links, and why the others are not) and `POST /objects/query`
  (`path: compiled` with the SQL, one plan line per decision, the links relied on and the rows —
  or `path: refused` with why), both over the graph `GET /ontology` serves and through
  `execute_guarded`. The conversation's `query_objects` tool — the model fills the IR, never SQL;
  given only an object type it returns that type's catalog entry; a streamed answer emits the
  `compiled` frame and leads its Trust Receipt with `validated_by guard:object_compiler` — is
  described FIRST in the roster, behind **`ask.query_objects`** (EXPERIMENT, default off, its
  exit this wave's falsifier) and only where an ontology is built.
  **Live receipt, 2026-09-11 — the API restarted on the branch, no model call:** "revenue per
  customer segment last quarter" on LuxExperience (orders span 2020-07-01 → 2025-06-29, so the
  data's last full quarter is Q2 2025) through `POST /objects/query` —
  `objects(order).by(segment).window[2025-04-01, 2025-07-01).measure(sum gmv_eur · count ·
  count order_to_order_item)`, the item link pre-aggregated per order_id: luxury 1,247,920.00 EUR
  over 1,989 orders and 3,460 items, off_price 470,855.00 over 1,943 and 3,332 — **equal to the
  unjoined reference row for row**; the join a model writes returns 2,207,654 and 798,274 (1.77×
  and 1.70×). That join, forced through the conversation's `run_sql` body on the same file
  (all quarters; stores redirected): luxury 52,210,160 against a true 30,698,533 — flagged, a
  `fanout_detected` receipt plus a caveat. The fan-out-shaped object query
  (`objects(order_item).measure(sum order.gmv_eur)`) is refused over HTTP with the l13 reason.
  🔴 **Found building that receipt — its `run_sql` half did not hold before this wave.** The
  battery's fan-out detector lives in `preflight_harden`, which runs only for callers that pass
  a rendered schema, and the converse `run_sql` tool (the analyst loop's too) never did; and
  `preflight_harden` executed a detected fan-out it could not rewrite with no receipt at all.
  Measured on the samples warehouse: a SUM of `orders.total_amount` across `order_items` came
  back 2.4× through `execute_guarded`, silently, with and without a schema — while both detectors
  fire when called directly. Fixed: `flag_fanout()` flags without rewriting on the door that runs
  the caller's exact SQL, and the unrewritable branch leaves a receipt ("Join over-count flagged").
  **The falsifier, measured two ways.** (1) *As written, on the ledger:* `session_events` holds 59
  user requests since it began recording (2026-08-29), 35 distinct: 7 platform questions (runs,
  tokens, models, tables queried), 5 about an uploaded document, 4 guide turns, 3 actions (stage
  an agent), 3 follow-ups that ask no new query, 1 test string, 10 multi-step warehouse turns
  (the daily change report — 7 scheduled runs and 1 asked by hand — a "why", an "interesting
  facts"), and **2** single-query warehouse questions. The compilable share of real questions is
  therefore at most 2/35 = 6% and the falsifier fires as written — on a population that is
  two-thirds questions no SQL answers, 13 days of an instance exercising its own platform. Of the
  two: theLook's "total sales yesterday against the prior 7-day average" compiles (single table;
  compiled for BigQuery, not executed — the scan bills), and the served read returns no ontology
  for workspace/default, where "last 6 months sales" was asked. (2) *On the sets built to be
  hard* (`evals/object_query_coverage.py`: a person writes the object query, the compiler and the
  ablation scorer do the rest, every store redirected): **22/26 compile (85%), 22/22 equal their
  references**; 4 refusals, all graph — LuxExperience has no orders↔shipments link (l05, l09: the
  edge ON-0a's pack lists as expected and unbuilt), samples has no orders↔reviews link (s12), and
  review↔order_item is N:N (s10). Zero refusals the algebra caused. Two answers took a path the
  reference did not and still agree (l06 reads the lines' returned flag, the reference the
  returns table; l10 reaches tickets through the order's lines). Receipt
  `evals/object_query_coverage_results.json`, ratcheted in `tests/unit/test_object_query_coverage.py`.
  **Reading it honestly:** the IR is not too narrow for warehouse questions — the refusals point at
  the ontology, not the algebra — but this is an UPPER bound: a person filled the IR. The share a
  MODEL reaches, and whether the tool in the roster lifts or regresses the ON-0 hard set, is a
  model run: `ask.query_objects`'s exit, and the user's call (§6 item 15).
  **Also measured:** theLook's served graph has five links and all are unmeasured (the ON-0a door
  never ran there — on BigQuery its COUNT DISTINCT scans bill), so every linked object query on it
  is refused today; and its `revenue` metric, marked verified, is `SUM(num_of_item)` — an item
  count. The compiler inherits what "verified" means (the formula EXECUTES), so a metric that runs
  and is not true compiles as faithfully as one that is: ON-0a's lesson a third time, now for
  metric formulas.
  **The model-filled measurement — RUN 2026-09-11** (§6 item 15(a); the user: *"run both
  measurements"*). A harness arm (`evals/ablation_eval.py --arms …,objects`, commit `f2a2ad25`): the
  model sees the schema the raw arm sees plus the object catalog and returns a typed object query —
  never SQL; the compiler writes the SQL or refuses; `objects_fallback` scores the product posture
  (the tool first, model-written SQL when it does not answer). `gemini-3.1-flash-lite`, fallback
  none, stores redirected. Receipts `evals/ablation_on0a_luxexperience_measured_results.json` (Lux,
  the same run as ON-0a's re-run) and `evals/ablation_on2_objects_samples_results.json` (samples):

  | set | raw | objects | compiled | objects + run_sql fallback |
  |---|---|---|---|---|
  | LuxExperience hard (14) | 14/14 | 1/14 | 6/14 | 9/14 |
  | samples (12) | 12/12 | 3/12 | 5/12 | 10/12 |

  **A regression — `ask.query_objects` stays off.** What the 26 fills did: 4 correct; 5 refused as
  malformed (`form`: the model filled a named `metric` AND a `path`); 2 declined (the model left
  `object_type` empty); 2 infrastructure errors (an empty structured output; a Gemini 429 quota
  refusal); 6 honest graph or law refusals (N:N or missing links, a distinct count across a to-many
  link — the fallback answered all six correctly); and 7 compiled answers the scorer marks wrong:
  2 with the right numbers in the wrong shape (an extra group column; unrounded averages), 1 with
  the right number from a different query that coincides on this data (`status = 'cancelled'` for
  "never shipped" — 4,536 both), and **4 genuinely wrong** — a share's condition put in `by` instead
  of the measure's `where` (100% per group), the order's shipping FEE for the shipment's shipping
  COST (the right link is missing, so the model substituted), a ratio's condition on the denominator
  (833% for 12%), and a denormalized `item_count` that disagrees with the lines (3.0 for 2.4). Zero
  `ir` refusals: the algebra was never the limit, the filler was, and nothing compiled a fan-out.
  🔑 **What this measures:** construction guarantees JOIN safety, not SEMANTIC correctness —
  choosing the measure, the filter and the ratio's sides stays the model's job, and on sets where raw
  is at ceiling a small model writing SQL it knows beats the same model filling an IR it has never
  seen. Fixable without new theory, none of it built: `object_type` required and `op` an enum in the
  fill schema, `metric` exclusive of `path`, a rounding convention, worked examples in the prompt, a
  stronger model — then re-measure. Found by the same run: the first refusal classifier had no
  `form` kind and filed a malformed fill as `ir`, which reads as "the algebra is too narrow";
  relabelled in the stored results, where the relabelling is recorded.
  **Not built, honestly:** the semiadditive law has nothing to bind to — O5's
  `window_measures.from_declaration` has zero callers and no store holds a declaration, so "a
  semiadditive measure refuses a period SUM at compile time" waits on a declaration surface;
  computed properties are not measures yet; a link touching a query-backed type is refused until
  its cardinality is measured over the backing; the `compiled` frame has no renderer in `web/`
  (the receipt carries the path, the chat shows no badge); ON-1's deferred items stand.
  **The draft:** Widen `semantic/compiler.py`'s
  intent IR from single-table to an **object-set algebra**:
  `objects(T).filter(segment | predicate).link(L).measure(metric | agg(property))
  .by(dimension).over(grain)` — compiled deterministically to SQL over the backings,
  with the join guard's law applied *by construction* (an N-side link is pre-aggregated
  before the join; a semiadditive measure refuses a period SUM at compile time), dialect
  via sqlglot, coverage-gated exactly as v1 ("it never guesses"). The agent gets
  `query_objects` as a tool, described in its roster ABOVE `run_sql`; `run_sql` stays as
  the escape hatch under the battery. The Trust Receipt names the path taken.
  **Receipt:** "revenue per customer segment last quarter" answered through
  `query_objects` with no model-written SQL, the receipt naming the compiled path; the
  same question forced through `run_sql` hitting the fan-out guard. **Falsifier:**
  compilable share of the last 30 days of real questions (`session_events`) below 30%
  ⇒ the IR is too narrow; widen before exposing the tool.
- **ON-3 · Instances — the object page and the object link.** `GET /objects/{type}/{pk}`
  resolved live through the backing; links resolved on demand; the zero-config
  **Standard Object View** the 07-22 study's Wave S named and nobody built — properties,
  links, the findings that cite this object (the context graph's `grounded_in`, finally
  pointed at an instance), the metrics touching its type, and the declared actions that
  take it as a parameter, pre-filled. `describe_entity` gains a sibling `get_object` on
  the agent roster and the MCP roster (SP-5's parity ratchet holds the diff empty).
  **Receipt:** a customer id in an answer is a link → its object page → "Orders" →
  `flag_order_for_review` offered with the id filled.
- **ON-4 · The kinetic plane closes the loop on objects.** `KineticAction` gains an
  `object_type` and an `object` parameter kind typed to ON-1's types; submission
  criteria may reference object properties (`object.status != 'refunded'`), evaluated
  deterministically as today; the `annotate` kind writes the K3 overlay keyed
  `(object_type, pk, property)` — Foundry's edits-as-overlay, on instances — and ON-2's
  compiler **merges the overlay at read time**, so an accepted annotation is visible to
  the very next answer with provenance. Source data is never written.
  **Receipt:** the agent proposes `flag_order_for_review(order=Order:123)` from a
  finding; a human accepts; `query_objects` over Orders now shows `review_flag=true` for
  123 with "annotated by <user>, <date>"; the receipt says so.
- **ON-5 · Functions and models on objects (the "intelligence mapping").** A
  **function** is a declared, deterministic computation over an object set — derived
  properties across ≤N link hops, and O5's window/semiadditive measures move here as
  the first citizens. A **model binding** attaches a callable to an object type — a
  scoring model, a prompt template, or an MI-4 adapter — with outputs landing as overlay
  properties carrying `model:<id>@<version>` provenance, refreshed on the object's
  freshness clock (Wave V vocabulary). The MI arc's adapters become ontology-bound
  instead of route-bound.
  **Receipt:** a churn-risk binding on `Customer`, its score on the object page and
  queryable through `query_objects`, the model version on the receipt.
- ❌ **ON-6 · The context layer reaches the model — RETIRED 2026-09-11** (the user: *"retire
  ON-6"*; §6 item 15(d)). ON-0's falsifier fired on both blocks — four wrong labels, then every
  label measured (ON-0a's re-run: raw 14/14, ontology 13/14) — so prompt injection is retired for
  the ontology and the wave is cancelled as drafted. **The draft, kept for the record** (it rode
  after ON-0, gated by it): Entity `description`, `domain`, exclusions, `null_meaning`, `measure_grain`,
  definition provenance and owners rendered question-scoped and verified-gated like the
  semantic layer today, each field's inclusion decided by ON-0's harness, not by
  taste. The fast phase gains a cheap, cached ENTITY MODEL so a fresh connection is not
  ontology-blind until a heavy build. **Receipt:** the ratchet up, per field, dated.

**Deliberately not ported (re-read §4.2's law: the grammar, never the codebase):** an
object store or sync layer · materialising edits back into source datasets · Spark-scale
indexing · CBAC · a "no raw SQL tool" posture (the human plane is SQL; §0) · a new agent
runtime (the roster gains two tools) · any second ontology store (ON-1 EXTENDS
`OntologyGraph`; the context graph stays the citation substrate and gains instance
targets in ON-3).

**Risks, carried in rather than discovered:** (a) ON-2's algebra is where a wrong
cardinality would corrupt a number silently — the compiler must REFUSE an unmeasured
link (`join_confidence` inferred) rather than traverse it, and O6's declaration probes
re-validate measured ones; (b) ON-1's multi-table backing is a view the warehouse never
declared — every backing EXPLAIN-binds before it is offered (the overrides' own gate)
and grain is re-verified (`COUNT(*) == COUNT(DISTINCT pk)`) on the backing, not the
table; (c) the kinetic census is ~1 today, so ON-4's receipt needs declared actions to
exist — PX-3's intake door and KI's suggestions loop are where declarations arrive,
and ON-4's pre-check counts them first; (d) "ontology" invites the very slop PX just
fixed — every wave's receipt is a behaviour a person can drive, and the ERD keeps its
job as a view.

**Sequencing note.** ON-0 is a measurement and may start now, beside MT-0/MT-1 (small,
unblocking strangers). ON-1 → ON-2 is the arc's substance and is where the roadmap's
thesis (§0: *"the moat is the ontology→agent loop"*) either becomes mechanically true
or is measured false. ON-4 wants ON-2's merge point; ON-3 is composition over ON-1/ON-2;
ON-5 wants MI-3's ledger for provenance and nothing from MI-4's gates; ON-6 rides ON-0's
ratchet and can interleave anywhere after it.


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

### 4.5 · TangleML as a runtime — REFUSED; its schema PORTED (2026-09-02)

Studied at the user's prompt (both repos read end-to-end, nothing executed). What it is:
the continuation of Cloud Pipelines by KFP v1's co-author, matured in Shopify's Search &
Discovery team, Apache-2.0, genuinely active (~6 contributors) — a visual-first pipeline
platform over containerized CLI components with content-based cross-run caching.
**Refused as anything that runs here:** pre-release (zero backend releases; the README's
`stable` branch nine months behind master; backend effectively single-maintainer), the
OSS build ships **no authentication** (every request is hard-coded "admin"),
**plaintext secrets** in its DB, arbitrary-container execution with read-write host
mounts as the product — and a foreign flow engine is §8 by name. It also contains none
of what Arc MI needs: no dataset versioning, no eval tracking, no LLM machinery.

**Ported instead — five schema ideas into MI-3 (§3.9)** (all from
`cloud_pipelines_backend/backend_types_sql.py`, 8 tables, ~546 lines): the
artifact-slot / content-hashed-bytes split (dedup by reference; provenance survives
purging via `had_data_in_past` + `deleted_at`) · cache_key = hash(step spec + input
content hashes) with attach-to-RUNNING dedup of concurrent identical jobs · the
execution-ancestor closure table (O(1) run-scoped lineage, no recursive CTEs) ·
three-table producer/input/output lineage · clone-lineage + indexed annotation k/v
with a typed filter language (the minimum viable experiment tracker).

**Falsifier:** ships real releases + auth, AND we own enough training volume that a
containerized offline *factory* (beside the product, never in it) beats rented
fine-tuning — then the factory question reopens, against Flyte/Metaflow as controls.

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
        (spec-deltas in §3.7 Phase 1; DS-1's P1 port-filter SHIPPED 2026-09-02; the P2 rail
        is NOT built and its premise has lapsed — see §3.7's DS-1 ledger)

  ✅ DS-6  SHIPPED 2026-08-31 — branch ("Otherwise": else_of, routed on the guard's
        VERDICT, undecided takes neither arm) + join ($from_any: first alternative that
        resolved; a join waits only on taken branches). Their seven-release-old ceiling,
        crossed — receipts in §3.7 Phase 2

  ✅ DS-7  SHIPPED 2026-08-31 — parallel steps: scheduling="parallel" (opt-in, per
        automation), frontier over the same effect_refs the awaits and canvases read;
        one step body driven by both orders; 2.7s parallel vs 5.1s ordered on the same
        chain, spans overlapping under one trace — receipts in §3.7 Phase 2

  ✅ DS-11 COMPLETE 2026-09-01 (both halves of its VA-11 side) — the vault is consumed: an
        `integration_call` step spends a user's grant through govern.outbound (cap, span,
        EXTERNAL_CALL, audit), reads and writes are declared as DATA against a closed URL
        set, a write passes the approval gate, and the palette/registry tell the truth
        about which grant can run which operation. A gated write PARKS on a human through
        the proposal inbox's second kind, and accepting it resumes the same run —
        receipts in §3.7 Phase 3

NEXT (order within a band is the user's knob)
  ✅ VA-9d FIRST SLICE SHIPPED 2026-09-02 — the allowlist IS the off state (no flag; an
                                   empty registry reaches nothing). Discovery + health + the
                                   read-only gate + `mcp_call` as a chain step, every hop
                                   through govern.outbound. The protocol's own defaults
                                   settled the case the posture sentence left open: a tool
                                   that declares NOTHING is refused, because `readOnlyHint`
                                   is documented "Default: false". 🔴 Found by driving it:
                                   discovery was capped and spanned and recorded NOTHING —
                                   no ambient trace, and `emit` drops those. DS-11's second
                                   half; §3.1 carries the receipt.
                                   ⚠️ The posture was DECIDED 2026-09-01 (§3.1, §6.3) — this
                                   band said "agree it with the user first" for a further
                                   day, which is a resolved item reading as a blocked one.
  ✅ §3.8 CANVAS PARITY SHIPPED 2026-09-03 (`e3a56b5c`, #428) — BOTH halves. The drag defect
                                   fixed (`onNodesChange` wired, handlers out of `data`, memo
                                   last — that order is load-bearing) and data shaping shipped
                                   as `$as` on the binding. 🔴 The conditional-router half of
                                   the gap was my own FALSE claim: DS-6's `else_of` already was
                                   the branch. ✅ 2026-09-04: the "same missing
                                   handler" claim was WRONG — `agentops/AgentMap.tsx` already
                                   sets `nodesDraggable={false}`, so it never wanted drag.
                                   `agentops/TraceFlow.tsx` was the real one and is FIXED.
                                   ⏳ Still owed: the Profiler receipt. `$as` is now NAMED at the point of authoring (2026-09-04). Original note:
                                   the PRIMITIVE gap (measured: their 34 core components vs our
                                   15 palette entries; their other 76 pages are vendor bundles,
                                   which is our connector/integration family and NOT a deficit)
                                   and the DRAG defect (`AutomationGraph` passes `nodes` with no
                                   `onNodesChange`; zero `memo(` on any canvas). The drag is the
                                   smaller fix and the bigger felt difference — take it first.
  ✅ VA-9d WRITE SLICE SHIPPED 2026-09-02 — the grant plane. Our per-tool ratification
                                   authorizes a mutating call, their `readOnlyHint` is
                                   advisory, and a changed declaration revokes the grant
                                   (pinned at discovery, scoped to the tool that moved,
                                   fail-closed). `uncertain` arrived with it, as the
                                   read-only slice promised it would. 🔴 Two premises broke
                                   under measurement: `tool_grants` was the wrong column,
                                   and `writes` reached the span but not the ledger — §3.1
                                   carries both. Still unbuilt (2026-09-04: the UI half of
                                   this line was WRONG — `+ Custom MCP` ships): non-text tool
                                   results, and OAuth-authenticated servers,
                                   non-text tool results.
  ✅ S1 Qdrant embedded SHIPPED 2026-09-02  (third backend: in-process local mode at
                                   AUGHOR_QDRANT_PATH; one serialized client per path;
                                   three bespoke QdrantClient call sites joined the
                                   seam — §3.6)
  ⚠️ DS-1 leftovers — HALF SHIPPED 2026-09-02. **P1** edge-drop → pre-bound palette filter
                                   is real (verified in code 2026-09-07). **P2's
                                   Palette·Runs rail was claimed here and never existed** —
                                   grep finds no rail; the shipped control is a category
                                   filter. Corrected 2026-09-07 by measuring instead of
                                   reading. Its premise lapsed too: Runs retired into
                                   Activity → Phases, so the rail has no second section.
  ✅ tool_grants column SHIPPED 2026-09-02  (migration 6 + store/create/patch + write-time
                                   roster validation + the editor's grants list; grants
                                   stay PROPOSE-only — §1 limit retired)

  🆕 Arc PX (§3.14, drafted 2026-09-09) — doors · language · composition: the
                                   exposure/slop audit's arc. The user turned this
                                   band's knob the same day ("most ambitious or
                                   complex item first") ⇒ PX-3 the intake door
                                   begins ahead of PX-0/PX-1; §6 item 13.

THEN    (§3.7 Phase 2 COMPLETE — DS-8 durable pause and DS-9 subchains SHIPPED)

LATER   ✅ DS-12 ontology components SHIPPED 2026-09-01
        (metric_value + trusted_query; §3.2's list limit closed from the kind side; the
        governed metric value repaired — it had never computed) · ✅ DS-13 declarative
        customs SHIPPED 2026-09-01 (the `http` side effect: a described call, filled and
        never evaluated, credential encrypted at rest; the declared webhook joined
        govern.outbound) · ✅ DS-14 chains-as-MCP-tools SHIPPED 2026-09-01
        (opt-in `exposed_as_tool` + migration 5; the 18 static tools are the version's,
        the automations are the deployment's)   (§3.7 Phase 3 COMPLETE)
        ✅ DS-15 conversation-authors-canvas SHIPPED 2026-09-01 (propose → validate →
        dry-run → a seeded form; nothing saved, nothing armed) · ✅ DS-16 migration
        funnel SHIPPED 2026-09-02 (allowlist translation, code nodes refused by law,
        report-before-canvas, to_fill holes for the form) · ✅ DS-17 deploy-as-doors
        SHIPPED 2026-09-02 (one Deploy menu: schedule · webhook (the fifth trigger kind,
        with the repo's one publicly-reachable route) · Slack · MCP tool, each `open |
        closed | needs_setup | unavailable` with the alt-door sentence — §3.7 Phase 4;
        **§3.7 is now COMPLETE**)
        VA-10 multi-user + admin  (hardening pass over everything above) — ✅ UNBLOCKED
                                   2026-09-02: §6.4 decided (visible metadata, gated payloads,
                                   break-glass audited and visible to the user). §3.5 carries it.

ARC MI  ✅ ADOPTED 2026-09-03 (§6.7 both clauses YES · §6.8 YES) — first target NL2SQL,
        training rented, not owned
        MI-0 annex ✅ DECIDED (§6.7b); remaining code: the langfuse.trace.input gate
        MI-1 grade what already runs · MI-2 verdict pins evidence — substrate-sized,
             may ride alongside any band above
        MI-3 dataset plane (learning store; Tangle's schema per §4.5)
        MI-4 NL2SQL adapter — starts ONLY at measured gates (≥1,000 SFT · ≥150 DPO ·
             golden ≥150 · verdicts flowing ≥30 days); rented training; ratchet-gated
        MI-5 ledger-in-the-box · model-as-a-door · adapters-as-releases (§6.8 ✅)
        MI-6 RLVR rehearsal — only after a measured SFT+DPO plateau (×2 versions)

ARC KI  ✅ ADOPTED 2026-09-05 (§6 item 9, both clauses YES) — org-owned definitions in
        through ONE funnel: any source → typed candidates → accept/edit/dismiss →
        the stores that exist. Nothing auto-applies.
        KI-0 ✅ trusted-SQL door BUILT 2026-09-05 — seed → verify (real execution +
             the shared battery) → propose → approve; only approved reaches a prompt
        KI-1 ✅ canonical bundle + review lane BUILT 2026-09-05 — upload → plan →
             accept/edit/dismiss → fan-out through each store's own governance;
             interchange.py consumed (plan_import has its first caller)
        KI-2 ✅ COMPLETE 2026-09-05 — CSV/TSV/XLSX dictionary + dbt manifest upload
             + LLM prose mapper (edit-rate falsifier at /intake/mapper-stats)
             + SKILL.md lane (pack candidates, draft-until-promoted). ARC COMPLETE
        KI-3 ✅ COMPLETE 2026-09-05 — Sheets definitions mode + Confluence/Notion
             table mining (one bundle per page, page URL as provenance; re-mine
             of an unchanged page proposes nothing)
        KI-4 ✅ BUILT 2026-09-05 — /intake/suggest mines validated runs + guard
             clusters into the lane; human-approved trusted queries now export
             to SFT/golden, so every approval moves gate_status()

ARC SP  ✅ ADOPTED 2026-09-05 (§6 item 10, both clauses YES) — Spotlight, the
        platform operator: one declared roster behind palette/chat/Slack/MCP;
        know · act · guide · shape; EX folded in as the Shape wave-family.
        Census done in-draft; the user's 4-question acceptance suite is green
        on substrate. SP-1 taken first at the user's direction.
        SP-0 ✅ census (in §3.11 itself; re-verify per wave)
        SP-1 ✅ COMPLETE 2026-09-06 — six org-level reads BUILT 09-05, LIVE 09-06
             (live drive found 2 real defects — automation count ~16× under via
             row-scan cap; tables misroute to warehouse SQL — both fixed same
             day); trace/audit leftovers closed 09-06: platform_traces (runs +
             one run's anatomy, metadata only — span payloads stay behind the
             audited read) and platform_audit (the unified recency feed over
             every governance sink). Nine reads with SP-6's premortem.
        SP-2 ✅ FIRST CUT BUILT 2026-09-06 — ⌘K free text → Spotlight answer pane
             in the overlay (same /ask door, quick-pinned); surface context
             threaded end-to-end, sanitized. In-browser receipt done (the user
             drove ⌘K live). CLOSED 2026-09-06: async command shape +
             keepOpen; askSpotlight in-context handles (empty Agents screen,
             failed-run rows); latency measured 1.99 ms/keystroke over 800
             items on the real pipeline. Nothing open.
        SP-3 ✅ COMPLETE 2026-09-06 · LIVE RECEIPT DONE (the origin sentence
             driven; the model measured the premise and declined a
             false-premise draft; agent draft staged pending in the real inbox)
             — set_preference applies instantly (user_prefs store, closed
             registry); draft_agent/draft_automation/pause-resume/agent-grant
             stage as four kinds on the ONE inbox; accept re-validates then
             applies through registered doors, reject byte-identical; the web
             shell reads the settings store AND re-reads it when a chat turn
             ends, so a theme switched in conversation is visible without a
             reload. Nothing open in the wave.
        SP-4 ✅ BUILT + LIVE RECEIPT 2026-09-06 — platform_guide: four grounded
             walkthroughs, steps quoted from the product's own flows, honest
             failure grounding, every answer ending in an offered staged act;
             the live ask hit the wave's receipt sentence verbatim (five
             stations, the asker's 5/5 agent cited, draft offered). Open:
             corpus search over pack prose
        SP-5 ✅ BUILT + ALL THREE TRANSPORTS DRIVEN 2026-09-06 — the roster
             declared ONCE; MCP registers the declaration at startup through
             the /spotlight routes; parity ratchet holds the diff empty. Live:
             an external MCP client and a real Slack message each STAGED the
             same agent-draft kind into the one inbox (both rejected,
             byte-identical) — and Slack's wrong-connection draft died in
             review, the custody line working unprompted. Open: native MCP
             parameter schemas
        SP-6 ✅ BUILT + HARDENED 2026-09-06 — permanent red-team corpus (now
             covering the /spotlight HTTP door), clips at every interpolation
             site, reads stage nothing; platform_premortem's offers carry
             their own arguments WITH the evidence chain, and the pause tool
             records evidence verbatim for the approver. Open: the live
             accepted-proposal receipt (waits for a natural evidence-backed
             occasion), periodic live red-team drives
        ⚠ cross-user Know waits on VA-10's auth decision
ARC ON  ✅ ADOPTED 2026-09-10 (§3.15; §6 item 14, all four clauses YES) — ON-0 STARTED. The user's challenge
        ("a fancy ERD… is it actionable or interpretable for the agents at runtime?")
        measured and largely confirmed: table = entity by construction; no instance
        layer; the semantic fields reach the UI, not the prompt; the only ablation
        (R4, 2026-06-21) was a regression for injected context; the kinetic plane is
        Foundry-shaped and holds ONE declared action. Waves: ON-0 measure — ✅ STARTED 2026-09-10
        (prompt reach measured: 59/142 fields reach a prompt · census: 1 declared
        action · harness rebuilt with an ontology arm and found un-runnable since
        June · two harder sets · the ratchet test · LLM arms run on samples/ecommerce:
        12/12 on every arm, a ceiling; missimi is GONE — the hard set re-authored on
        LuxExperience and RUN: raw 13/14 = ontology 13/14, NO LIFT; the falsifier fires
        as written, contested by four wrong N:N labels — the user decides) →
        ON-0a the core the business extends (built 2026-09-11: cardinality and terminal
        states measured at build time; the map as claims by tier — core-ecommerce ←
        fashion-ecommerce ← the company; the hard-set re-run on the measured block ran
        2026-09-11: no lift, the falsifier fires again) →
        ON-1 object types decoupled from tables (first slice built 2026-09-11) →
        ON-2 the compiled object-query door (FIRST SLICE BUILT 2026-09-11: the algebra
        compiles over measured links — 22/26 hard questions, every answer right when a person
        fills the query; POST /objects/query driven live; run_sql's silent fan-out found and
        flagged; a MODEL filling it regressed, 1/14 and 3/12 against raw at ceiling, so
        query_objects PARKED behind its flag — §6 item 15)
        → ON-3 instances + the standard object view (STARTED 2026-09-11) → ON-4 actions on
        objects with the overlay merged into the next answer → ON-5 functions and model
        bindings. ON-6 (the context layer reaches the model) RETIRED 2026-09-11 — ON-0's
        falsifier fired on both blocks (§6 item 15).
```

### Loose-end ledger (re-swept 2026-09-04 — not a band, a debt list)

> ⚠️⚠️ **The 2026-09-04 sweep, and where the rot actually is.** The five OPEN bullets below
> were all re-measured and all hold — three of them (`VA-11`'s Google client, the Slack
> reinstall, the manual drag) are **keyed on the user and no sweep can move them**, and the
> other two (Notion/Confluence, `svg_to_png`) were re-verified by driving the endpoint and
> importing the module. **This list was not the problem.**
>
> The stale claims were **inline in §3**, where nobody re-reads them: §3.5 said VA-10 was
> "Untouched" when three of its five pieces ship; §3.1 said the MCP UI was unbuilt when
> `+ Custom MCP` ships and said OAuth was the Arcade/Composio unlock when this repo's own
> study records an API key; §3.8's leftover named a file (`AgentMap.tsx`) that already opted
> out of the behaviour, while the file that actually had the defect went unnamed. **Three of
> five items offered as "next" on 2026-09-04 were misdescribed.**
>
> 🔑 **The lesson, third instance in a week:** a struck-through debt list stays honest because
> striking it is a deliberate act. A prose claim inside a section rots silently, because
> nothing forces anyone to look at it again. **Measure the inline claims, not just the
> ledger** — and prefer a dated table to a sentence, because a table with a date on it
> invites re-measurement and a sentence does not.

> ⚠️ **Re-swept 2026-09-02 (later the same day), and the sweep itself was the finding.** Of the
> items re-measured, **two were FALSE** (`notification_channel`, wired a fortnight earlier by
> #349) **or wrong by six** (report-quality: 1 live, not 7), **one was stale** (DS-6/DS-7
> receipts, cleaned that morning), **one was true for the wrong reason** (`svg_to_png` — an
> uninstalled extra, not a missing backend), and **one was true and root-caused to a single
> line** (the Notion/Confluence picker). Three of the week's failures were the same failure:
> **a resolved item that keeps reading as open costs whatever work it deters.** Re-measure
> before scheduling from this list; every line below carries the date it was last checked.

**Keyed on the user** (a decision or credential only they hold):
- ~~**VA-9d posture**~~ — **NOT a debt: decided 2026-09-01** (§3.1, §6.3), and the first
  slice shipped 2026-09-02. This line and §5's band both still read "needs sign-off" a
  day after the call was made — the ledger's own worst failure mode, because a resolved
  item that keeps reading as blocked stops work that could have started.
- ~~**VA-10's privacy default**~~ — **DECIDED 2026-09-02** (§6.4, §3.5): visible metadata,
  gated payloads. **§6 now has NO open decisions**, and VA-10 no longer stalls. The MCP write
  slice's two questions were decided the same day (§6.6, §3.1) — so is Arc VA's other blocker.
- **VA-11's live Google receipt** — needs an OAuth client only the user can create.
- **Slack reinstall** with `assistant:write` + `files:write` — three Slack surfaces dark until then.
- **One manual drag** — P1's edge-drop gesture: no tooling here can drive a ReactFlow drag
  (4× measured); the law is pure-tested, the gesture wants one human receipt.
- Working-tree odds: modified `customers.yaml` · untracked `data/ontology_overrides/fixture/` ·
  stale tags (`pre-rebase-va11`, `pre/post-rebase-backup`) · ~40 squash-merged local branches.

**Buildable** (flagged, unscheduled — pull forward at will):
- ✅ **`govern/disclosure.py` DELETED 2026-09-06 (the user's call, asked first).** Fully built
  and tested since Wave G6, zero production callers ever — §7's complete-and-inert shape held
  for months. The deciding argument was not the inertness but VA-10: its run-as identity half
  would today surface the unverified `X-Aughor-User` header on answers — misattributable
  identity people would trust, §3.5's own warning. Recoverable via git; rebuild ON REAL
  IDENTITY when VA-10's auth model lands, with the receipt/answer as its consumer from day one.
- ~~**Report-quality deep dive, 7 of 8 defects still live**~~ — **RE-MEASURED 2026-09-02: the
  true count was ONE, and it is now closed.** This line advertised seven live defects for two
  weeks, and it is the ledger's own worst failure mode a second time (see VA-9d's posture): a
  resolved item that keeps reading as open costs whatever work it deters. **CA-0 (#359) merged
  at 23:55 on 2026-08-19 — the same evening the catalogue was written — and closed most of it**,
  each fix naming the specimen it came from, so the catalogue was stale within hours of being
  filed and nobody re-read it against the code.

  Verified one by one, against the code AND the live corpus
  (985 reports, 229 deep runs): ① the tautology's measure regex —
  closed by CA-2, which added `abs_change`/`delta`/`pct_change`/`contribution` by name ·
  ② `_orchestration_plan` — closed, and PROVEN on live data: today's run journals
  `planned: [baseline, decomposition, dimensional, intake, synthesis]` · ③ the confidence floor —
  closed, `_finding_has_rows` keys on `row_count` and excludes the synthetic intake-spec finding,
  the exact two things named, with its own test file · ④ derivation credit in `check_grounding` —
  closed, docstring names both halves as CA-0 fixes · ⑤ the `increase` verb regex — closed by
  CA-0's transitive/intransitive split, whose comment cites the Direkteingabe #15 hits ·
  ⑦ session_id — closed for every CHAT path (10/10 shaped runs in the last 7 days carry one; the
  session-less remainder are AUTOMATION runs, which correctly have no session), and the
  zero-row conjunction trap is handled in `analyst.py` naming the same specimen ·
  ⑧ observation_label and the contradiction detector — closed; the detector reads `is_significant`
  flags, not prose word-lists.

  ⑥ **was** live and is now fixed (2026-09-02): `drifted_registered_metric` concatenated
  *"Recompute with the governed formula or relabel to what the SQL computes."* — plus the raw
  governed SQL — into a finding's `trust_caveat`, which `_evidence_confidence_ceiling` copies
  verbatim into `confidence_justification`, which renders in the customer PDF while the web view
  hides it. Measured on the live corpus: three stored reports carried it, the most recent from
  2026-09-01. Split by AUDIENCE at the source — the reader gets the diagnosis ("this number is
  not Revenue as your organisation defines it"), the log gets the remedy and the formula. The
  phrase "metric formula drift" is kept because `_COMPUTATION_ERROR_CAVEAT_RE` matches on it to
  reframe the headline, and a reword would have un-wired that silently.

  **The standing lesson, not the defect:** a catalogue is a measurement with a timestamp, and
  this one was re-read as a to-do list for two weeks. Re-measure before scheduling from one.

  ⚠️ **Conflict resolved 2026-09-03 when this branch merged main.** Both sides had rewritten
  this same line: main's (from #427) was a summary that ended by pointing at
  `claude/report-quality-audience-split` as *"pushed, NOT merged"*, and this branch IS that
  fix. The pointer was dropped rather than carried, because a ledger line naming a branch
  that has landed is the exact failure this entry is about.
- ~~**Explorer partial-day sibling**~~ — **FIXED 2026-09-03.** The baseline TREND axis
  (`explorer/manifest_query.cell_to_sql`) had **no upper bound on its time axis at all**:
  `WHERE ts IS NOT NULL GROUP BY 1 ORDER BY 1`, so the final point of every canvas trend was
  today-so-far. It now drops the unfinished bucket, carrying the investigate guard's two
  conditions rather than re-deriving them: **only when the data reaches today** (a closed
  dataset's last bucket is final — trimming it would erase real data on every render, which is
  what keeps every demo and fixture set whole) and **only when a complete bucket would remain**
  (an empty chart reads as a fact about the business rather than about the calendar).
  🔑 The cutoff is `date_trunc(<grain>, CURRENT_DATE)` **in SQL, not a Python literal** — the
  warehouse's idea of now, in its own timezone. A literal would be this process's idea of
  today, and the two disagree for several hours a day. Grain-aware, so a monthly trend drops
  the whole current month rather than one day of it. `seasonality`, `yoy`, `headline` and
  `dimension` are untouched and tested to stay so. Eleven tests, three conditions each
  mutation-verified.
  ✅ **And the ORIGINAL guard's live receipt, which was owed since 2026-09-02**: today's 09:00
  briefing fired and reported *"1,769 orders on September 2nd, a 58.8% increase over the
  previous day"* — a complete day against the preceding complete day. The defect it replaced
  led with "orders fell 97.5%" from nine hours of today (43) against all of yesterday (1,733).
  The window guard holds live.
- ~~**Notion + Confluence are built and unreachable**~~ — **DECIDED AND CLOSED 2026-09-06
  (the user's call: the DOCUMENTS surface, not "Add data").** They feed the doc KB, not
  tables — the registry's own comment was the argument. Shipped: `GET/POST
  /knowledge/sources` (form fields SERVED from the connector registry; credentials tested
  live before the record exists, Fernet-encrypted at rest) + a Connected-sources section
  on the Documents tab riding the existing per-connection sync routes. The data catalog's
  category ratchet (`test_connector_categories`) is untouched — deliberately. Also fixed
  while joining: both connectors' sync state was a CWD-relative `Path("data")`, so any
  process not started at the repo root re-synced from scratch; now `state_dir()`,
  resolved per call. The history below is kept because its lesson (a static lookup table
  read as the route's output, twice) outlives the item:
  before were both WRONG. 🔴 **Re-measured 2026-09-03 by driving the live API**, which is what
  finally settled it: `GET /connectors/types` emits **no `knowledge` category at all**.
  - The 2026-09-02 entry blamed the frontend's `CATEGORY_ORDER` and called it "one line". That
    was read off the static `CATEGORIES` map. The route builds its list from
    `["duckdb", "postgres"] + REGISTRY.supported_types()`, and **`_register_defaults` never
    registers notion or confluence** — its own comment says why: *"not DB connectors —
    `open_connection()` is not called on them"*. They feed the documents pipeline.
  - So adding the `knowledge` row draws an **empty heading**, which reads as "we support this
    and you have none". It was added, driven, and reverted the same hour.
  🔑 **Twice now, a static lookup table was read as though it were the route's output.** The
  live call took one command and overturned both answers. *A proxy is not the measure* — and a
  registry map is a proxy for a registry.
  **What it actually needs is a DECISION, not a line**: does a Notion source belong in "Add
  data" (where a person expects tables) or on the documents surface? The connectors import
  cleanly and have no route, no registration and no UI — the complete-and-inert shape §7 names.
  ✅ A guard now exists either way: `tests/unit/test_connector_categories.py` fails if the
  server emits a category nothing draws, AND if the panel draws one the server never emits.
- ~~**Monitors' `notification_channel` unwired**~~ — **THIS LINE WAS FALSE. Re-measured
  2026-09-02:** the field was wired by **#349 (`f4c25426`, OA·N8-0)**, which is where
  `aughor/monitors/notify.py` came from. `dispatch_alert(alert)` is called on the alert-commit
  path (`monitors/store.py:332`), the channel holds an **Action Hub trigger id** (a configured
  destination, not a channel *kind*), delivery is `fire_action`, and a unit test covers it.
  Monitors CAN route. Third instance of the week's lesson — this one deterred work that had
  already shipped a fortnight earlier.
- ~~**The propose plane has an empty roster on this deployment**~~ — **the claim was false as
  written, and the receipt is now taken. Measured live 2026-09-03, per connection:**
  `workspace` **1** · `fixture` **2** (a DS-8 receipt from 2026-09-01) · theLook **0**. So the
  plane already had something to bite on two connections; what was true is narrower — *theLook*
  declared none. Fifth line this week whose wording outlived its measurement.
  ✅ **Receipt taken on theLook**: one `annotate` action (`flag_order_for_review`) declared
  through `PUT /ontology/kinetic-actions`. It reaches every consumer — the roster returns it,
  and `GET /components?conn_id=8233e4fd` now carries `declared_action: 1`, `availability=ready`,
  its `order_id` param drawn as a port, `exposable_as_tool=true`, `governed_by=
  aughor.govern.actions`, and `risk=high` by the model's fail-safe default (an unclassified
  declared action stops for a human rather than auto-firing).
  🔴 **The chain was NOT driven to a staged proposal, deliberately.** `POST
  /kinetic-actions/propose` runs a proposer **LLM call** on the `fast` binding, and spending the
  user's tokens is not something a receipt gets to do unasked. What is proven is that a
  declaration reaches the palette, the ports and the tool-exposure flag; what is unproven here
  is the LLM proposal step, which has its own unit coverage (`test_kinetic_propose.py`).
  ⚠️ The declaration is a reversible override file
  (`data/ontology_overrides/8233e4fd/thelook/action/flag_order_for_review.yaml`), untracked like
  its `fixture` sibling. Delete it to restore the previous state.
- ~~**DS-6/DS-7 receipt automations pollute Attention daily**~~ — **CLOSED 2026-09-02.** The
  10 offending fixtures were deleted; `automation_runs` 26,298 → **3,010** and the heartbeat
  write rate ~11/min → **1.0/min**. Deletion cascades runs, probe_state and layouts; real
  automations untouched (`The Look - Daily Briefing` still live on 2 doors).
  ⚠️ Two DISABLED fixtures remain by choice — `W1 guard check`, `W2 fan-out check` — same class,
  zero cost because disabled. Ask before deleting. ⚠️ No `VACUUM` yet (needs an exclusive lock,
  the API was running): the file is still 12.1 MB.
- **`svg_to_png` dead** → PPTX chart export degrades (Chat SDK study). Re-measured twice, and
  **the second correction is the one that mattered — my first was also incomplete.**
  ✅ The install half stands (2026-09-02): `reportlab` and `svglib` live only in the `[export]`
  extra (`pyproject.toml:85-90`) and do not import here; the documented setup is
  `uv sync --all-extras`, and **CI installs them, which is why CI never saw what follows.**
  🔴 **"Degrades by design" was WRONG (2026-09-03) — it was masking a defect that ships to
  customers.** `document._chart_or_table` blanks the TABLE's caption whenever a chart block
  exists, because the chart is meant to carry the title — and in the PDF it does, from the SVG,
  needing no raster. `slides.py` renders a chart slide only `if b.png`. So on any install
  without the backend the PPTX dropped the chart **and** the table arrived with an empty
  caption: **an untitled table in a customer's deck.** Not a degraded picture — a missing
  title, silently, on the format that goes out to people. **FIXED**: the renderer that drops
  the chart hands the caption to the table that follows, spends it once, and never displaces a
  table's own title.
  🔑 **The repair belongs in the RENDERER, not in `document.py`** — the block layer is
  format-agnostic and was right to blank the caption, because the PDF really does draw it.
  Only the renderer knows it dropped the picture. Deliberately NOT a "chart unavailable"
  slide: the numbers arrive on the next slide, so a line about our own plumbing tells a
  customer nothing they cannot see. Six tests, two mutation-verified.
  🔑 **The lesson: I read the FUNCTION and called it benign; the defect was in the PATH.**
  `svg_to_png` really does degrade cleanly — and two layers up, something else had already
  given away the title on the strength of a chart that would not arrive.
  ⏳ Installing the `[export]` extra here would restore the PICTURES too; that is the user's
  environment to change, and the deck is honest without it.
- ~~**Canvas drag is not fluid**~~ — **FIXED and MERGED 2026-09-03** (`e3a56b5c`, #428; §3.8b).
  ✅ **The follow-up is done, and it was not what this line said (2026-09-04).**
  `AgentMap.tsx` does not have the same missing handler — it is `agentops/AgentMap.tsx` (the
  bare path here is why it read as absent) and it already sets `nodesDraggable={false}`, so
  it never offered a drag. Grepping every ReactFlow canvas for the actual defect shape found
  the real one: **`agentops/TraceFlow.tsx`** passed controlled `nodes` with no
  `onNodesChange` and no `nodesDraggable={false}`, and ReactFlow defaults dragging ON.
  **Fixed by REMOVING the affordance, not wiring the channel** — #428 wired it because that
  canvas has an authored layout and a sidecar to persist it; a trace's positions are computed
  by `layoutForest`/`layoutGrid`, there is no trace-layout store, and a moved card would be
  lost on the next re-select. Wiring drag would promise a persistence that does not exist,
  and the tree layout is a READING of the run that arbitrary positions destroy.
  ⏳ Still owed: the **empirical receipt** — the browser tool cannot drive ReactFlow pointer
  interactions, so a React Profiler trace during a real drag remains outstanding. The new
  tests assert the render HANDOFF (the flags the canvas is given), which is the honest limit
  of what jsdom can prove; they were verified to FAIL without the fix.
- ~~**The primitive gap**~~ — **CLOSED 2026-09-03** (`e3a56b5c`, #428). Data shaping shipped as
  `$as` on the binding; the conditional-router half was my own false claim and DS-6's `else_of`
  was always the branch (§3.8a). ✅ 2026-09-04: `$as` is now TAUGHT where bindings are typed, and the dedicated
  PICKER (`BindingCast`) ships with it — the cast is a control beside the field, not only an
  API/DS-16 path.
- ~~**DS-5 Map grants spoke**~~ — **DRAWN 2026-09-03**, closing the last undrawn spoke of the
  DS-5 spec ("its doors; its automations; its tool grants and connections"). One node per
  granted action on the reach side, edged from the agent, pointing at **Attention** — the
  file's own law is that only destinations which exist are offered, and a proposal lands in
  the inbox, so that is the honest one rather than a link to the semantic layer.
  🔑 **Every card says "may PROPOSE · a human accepts before anything runs", and that sentence
  is the reason the spoke is safe to draw at all.** A card titled with an action id, sitting on
  the outward side of an agent, is read as *"this agent does that"* unless it says otherwise —
  and the whole design of this plane is that it does not. A test fails if the wording goes.
  It could not have been drawn earlier: before the `tool_grants` column landed (2026-09-02)
  every agent answered `[]`, so the spoke would have rendered an empty truth. Six tests, two
  mutation-verified. `MAP_META` is a `Record<MapKind, …>`, so adding the kind made the
  renderer's half a compile error rather than a silent omission — the type system catching the
  partial add that this arc keeps paying for.
- ~~**Runs rail lists every per-minute `not_fired` tick**~~ — **FIXED 2026-09-03** (`4f30bf58`,
  #432). Measured first: **99 of the last 100 runs were `not_fired`**. Adjacent quiet ticks now
  stack with a ×N badge — the stacking rule this project applies on every canvas, brought to a
  list. It collapses and does not hide: only a tick that did nothing at all collapses, adjacency
  is kept rather than globally filtered, and a group claims a shared reason only when every tick
  in it gives the same one.
- ~~**Stray `data/qdrant/` appeared 2026-09-02** despite the server pin~~ — **CAUSE FOUND
  2026-09-03: `aughor/cli.py` never read `.env`.**
  The chain, proven statically: `.env` was read by `api.py` and `semantic/kb_retriever.py`
  and **nothing on the general import path**, so a process starting at the CLI — the
  installed console script — saw no `AUGHOR_QDRANT_URL`. Without that pin
  `vector_store._client()` takes the embedded branch at `_embedded_path()` →
  `state_dir()/qdrant` → **`data/qdrant`**. And `aughor investigate` reaches the store
  through `agent.bootstrap` (`delete_by_filter` / `match_filter`) — real operations, and
  these stores write when USED, which is exactly why the DS-17 suspect could be real and
  still not reproduce it: a spec dump only imports.
  🔑 **Fixed at the ENTRYPOINT, not in the library modules.** `kb_retriever` had already
  patched itself the same way — and patching one call site is precisely why the gap
  survived, because the next path in did not go through it.
  🔑 **And the repo already had an opinion about WHERE**: `test_env_isolation` refuses a
  module-level load outside its allowlist, so the load sits in the `click.group()` callback
  every command passes through and no test that merely imports the module runs. The
  existing ratchet caught the first attempt and was right.
  ✅ `tests/unit/test_entrypoints_load_dotenv.py` guards the CLASS — every process
  entrypoint reads `.env`, honours `AUGHOR_SKIP_DOTENV`, and the console-script target
  stays covered — plus a canary on the premise (the set of `.env` readers) so the next
  reader re-derives the reasoning instead of trusting it.

**House rules that bind every PR:** one PR at a time, squash, never push without authorisation ·
ratchet battery on your own diff in a clean worktree · seven frontend gates + `gen:api` on route
changes · `PYTHONPATH="$PWD"` in worktrees · one writer per `data/` · **prove each wave live in
the browser** · **measure the premise before building.**

---

## 6 · Open decisions — the user's, not the builder's

> **Status 2026-09-07: NONE open. All TWELVE are decided** (items 9 and 10
> each stamped YES, both clauses, the same day they were drafted — the KI build ran
> ahead of its stamp at the user's direction, and SP-1 began the moment item 10 landed).
> Kept as a register, not a queue — each entry records the reasoning so a settled
> question is not re-litigated, and so no band elsewhere in this document can go on
> reading as blocked once the call has been made. If you arrived here looking for what
> the user still owes, the answer is *nothing*; what remains is in the ledger's "keyed
> on the user" list — credentials and one manual gesture, not decisions.
> **Amended 2026-09-09:** item 13 (Arc PX) arrived and was decided in the same
> session by the user's own directive — the register stays at zero open.
> **Amended 2026-09-10:** item 14 (Arc ON) arrived, was open for one turn, and was
> DECIDED the same day — all four clauses YES, every recommendation adopted as written;
> the register is back at zero open and ON-0 started within the hour.
> **Amended 2026-09-11:** item 15 (ON-2's exposure) arrived with ON-2's first slice and was
> MEASURED and DECIDED the same day — the door parked behind its flag, ON-6 retired, ON-3
> started. The register is back at zero open.

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
3. ✅ **DECIDED 2026-09-01 — the MCP consumer's posture: read-only tools first.**
   Allowlisted servers, discovery and read-only calls; a tool the server declares as
   mutating is listed and refused with a sentence rather than hidden or trusted. The
   question it defers on purpose — whose declaration of "read-only" is believed — is the
   write slice's to answer, and is the reason this cut is the narrow one. Full note: §3.1.

4. ✅ **DECIDED 2026-09-02 — visible metadata, gated payloads.** An admin reads a user's
   metadata freely and their prompts only through an audited break-glass: a recorded reason,
   an audit-log entry, and the access visible to the user it concerns. Metadata carries the
   analytics case on its own; payload access is the exception that must justify itself.
   Specced as §3.5 — VA-10 no longer stalls.
5. ✅ **DECIDED 2026-08-31 — the visual-editor question: the grammar, not the codebase.**
   The user re-opened §4.2 with a mandate for total openness ("fork it… go all in… think
   years ahead"); the four-pass re-study confirmed the refusal (§4.2 addendum) and the
   vision landed as **Arc DS (§3.7)** — Langflow-class editing on our engine, then past
   their documented ceiling, then the governed component economy, then authoring by
   proposal. Phase-1 default order DS-1 → DS-4 → DS-3 → DS-2 → DS-5, reorderable; the
   VA-11 consumer stays first among equals in §5 (repairing the built-and-inert vault is
   §7's own law).
6. ✅ **DECIDED 2026-09-02 — the MCP write slice: our grant, not their label.** A server's
   `readOnlyHint` is advisory and displayed; an explicit per-tool grant (reusing
   `tool_grants`) is what authorizes a mutating call, which is what the SDK's own
   untrusted-annotation warning asks for. A declaration that changes after registration
   revokes that tool's grant and refuses the next call until a human re-ratifies — pinned at
   discovery, scoped to the tool that moved, fail-closed. Full note: §3.1.
7. ✅ **DECIDED 2026-09-03 — Arc MI enters the queue, and the training annex is law.**
   Both clauses stamped YES by the user. **(a) Adoption:** §3.9 is active; first
   distillation target NL2SQL (ground truth is free: execution outcomes + guard fires +
   human corrections with `corrected_sql`); training rented, not owned; MI-1/MI-2 are
   substrate-sized and may ride the next wave. **(b) The training annex to §6.4:** the
   2026-09-02 decision governs an admin's *reading*; this clause governs *machine
   consumption* — payloads are trainable only under an org-level opt-in carrying a
   retention class, a purpose tag, and PII scrub at export; work artifacts (questions,
   SQL, result summaries, verdicts) are lawful training inputs, org-scoped. The NL2SQL
   loop needs nothing from this clause.
8. ✅ **DECIDED 2026-09-03 — the community flywheel: YES to both halves.** (a) Releases
   may ship shared task adapters (`aughor-sql-vN`) trained on our own pilot data.
   (b) A deployment may OPT IN to contribute scrubbed graded pairs under 7(b)'s annex.
   The yes does not change the default posture: contribution is strictly opt-in —
   nothing leaves a deployment that didn't say so. This is the mechanical form of the
   origin directive ("smarter as more users use the platform"), now deliberate.
9. ✅ **DECIDED 2026-09-05 — Arc KI is adopted, and the two-act authority model is
   law.** Both clauses stamped YES by the user, the same day the section was drafted
   (the build ran ahead at their direction: KI-0…KI-3 landed before the stamp).
   **(a) Adoption:** §3.10 is active; order within §5 stays the user's knob.
   **(b) The authority model for prompt-authoritative imports:** trusted-SQL
   acceptance is a metrics-style transition (propose → approve, capability-gated) —
   uploading and trusting are two recorded acts. On a single-analyst deployment the
   same person performs both, but the ledger records them separately; the shipped
   KI-0/KI-1 code implements exactly this. Neither clause opened custody ground:
   §6.7 already covers imported work artifacts as org-scoped inputs, and §6.8's
   outbound posture is untouched.
10. ✅ **DECIDED 2026-09-05 — Arc SP is adopted, and EX folds in as its Shape limb.**
    Both clauses stamped YES by the user, the same day the section was drafted ("Lets
    add to the roadmap… and then quickly take the first one in line"). The user's
    Spotlight vision as §3.11: one platform operator (know · act · guide · shape)
    behind one declared roster, every write a staged proposal into the existing inbox.
    The census in the section shows the substrate largely merged; the user's own four
    acceptance questions are green on it, and the ten market use cases grade
    near/medium with none requiring new ML. **(a) Adoption:** §3.11 is active; order
    within §5 stays the user's knob — SP-1 (read-only Know roster) is first, at the
    user's direction. **(b) The EX fold:** the 2026-09-01 meta-agent/experience
    vision is the Shape wave-family INSIDE this arc, not a sibling arc — one custody
    story, one roster, one decision. Neither clause opened custody ground: §6.4
    governs what Spotlight may read, §6.7/§6.8 are untouched, and cross-user Know
    waits on VA-10 regardless.
11. ✅ **DECIDED 2026-09-06 — VA-10's auth model: OIDC.** The user's call, made when the
    gap-map round asked it directly (platform-minted tokens were the recommended
    alternative; OIDC won). Built generic the same day: no IdP is hardcoded — issuer +
    audience are configuration, provider specifics come from the issuer's discovery
    document, and the org claim is opt-in (`AUGHOR_OIDC_ORG_CLAIM`, strict when set)
    with a single-org default. The spoofable header seam dies whenever an issuer is
    configured under required identity. What only the user can supply: a real tenant's
    issuer/client id for the live receipt. Full note: §3.5.
12. ✅ **DECIDED 2026-09-07 — Arc MT is adopted: the hosted deployment becomes
    self-serve.** The user's directive, verbatim: *"any user who goes to vercel
    deployment should be asked to login using Gmail.. and once logged in the user can
    create a number of workspaces.. naturally linked to the users Google login."*
    Three clauses fall out of it and are recorded together: **(a)** the consent screen
    is **External** — any Google account, not a Workspace org; Internal was the
    employees-only reading and is not this product. **(b)** the tenancy mapping is
    **one user = one org**, derived from Google's stable `sub` — chosen over per-user
    ownership columns because the org boundary is the isolation mechanism that already
    exists, is already enforced, and was already proven live (403); two mechanisms
    that can disagree is how leaks happen. **(c)** a fresh self-serve org is **born
    capped** — signup must never mean uncapped LLM spend; defaults ride the G4 caps
    store and only an operator raises them. Not decided here because it isn't ripe:
    billing, team orgs (joining, not owning), and Google's app-verification paperwork.
    Full note: §3.12.
13. ✅ **DECIDED 2026-09-09 — Arc PX is adopted, and the band's knob is turned: most
    ambitious first.** The user's hypothesis, verbatim: *"there are a lot of features
    that aughor has but are not surfaced or exposed as much as they should be. Along
    with that, our UI is also like an AI slop … it lacks the UI judgement of an
    experienced UI/UX researcher"* — confirmed by the same-day audit and specced as
    §3.14. The build directive followed mid-session: *"take the most ambitious or
    complex item first with precision"*, which inverts the arc's default
    PX-0-first order. Chosen under that directive: **PX-3, the intake door** — the
    single largest fully-inert plane (11 endpoints, zero consumers anywhere), a
    complete propose→review→accept governance flow, and buildable to a hard live
    receipt now because its backend is finished and tested. PX-5 is grander but
    waits on provenance fields the ontology does not yet store; PX-2 is broad
    rather than deep. PX-0/PX-1 follow.
14. ✅ **DECIDED 2026-09-10 — Arc ON is adopted: the ontology becomes the thing the agent
    runs on.** The user's words, verbatim: *"Yes to all four, start ON-0 now."* Every
    recommendation below was adopted as written; ON-0's receipts are in §3.15.
    Drafted as §3.15 from the user's own challenge, measured the same day (the
    noun layer is the schema by construction; no instances; semantic fields reach the
    UI and not the prompt; the last ablation of injected context was a regression;
    the kinetic plane is Foundry-shaped and holds one declared action). Four clauses,
    each with the builder's recommendation marked — the call was the user's, and was YES on all four:
    **(a) Adoption.** Is §3.15 active, with ON-0 (the measurement) starting now?
    *Recommended: yes — ON-0 is a week and decides the rest by number.*
    **(b) The agent's primary door.** Does `query_objects` (ON-2) become the tool
    described FIRST in the roster with `run_sql` as the escape hatch, or a peer?
    Foundry gives agents no raw SQL at all; this platform's human plane is SQL (§0).
    *Recommended: primary-with-fallback, and ON-0's ratchet may overturn it.*
    **(c) Resolution posture.** Objects resolved LIVE through backing queries (no
    object store, no copy of the warehouse) versus a materialised object layer.
    *Recommended: live — §4/§8's lean-compute law; reopen only on measured latency.*
    **(d) The band's knob.** ON-0 beside MT-0/MT-1 now, ON-1/ON-2 after — or ON ahead
    of MT outright. *Recommended: ON-0 ∥ MT-0/MT-1; ON-1 → ON-2 next, because §0's
    thesis ("the moat is the ontology→agent loop") is today a sentence, not a
    mechanism, and this is the arc that makes it one or measures it false.*
    Not decided here because it isn't ripe: whether `run_sql` is ever demoted below a
    guard-cited allowlist (needs ON-2's coverage number); whether edits are ever
    materialised back to source (the read-only law stands until someone asks with
    a case).
15. ✅ **DECIDED 2026-09-11 — ON-2's `query_objects` does not reach the conversation: the door
    is PARKED, ON-6 is RETIRED, and ON-3 starts.** The user, verbatim: *"Park the door, retire
    ON-6, start ON-3."* The falsifier was measured two ways (§3.15 ON-2): as written, on the
    ledger, it fires (at most 2 of 35 real questions compile — but two-thirds of those turns ask
    nothing SQL answers); on the hard reference sets the algebra compiles 22 of 26 with every
    answer right and no refusal the algebra caused.
    ✅ **(a) Measured** (the user: *"run both measurements"*): a model filling the IR —
    `gemini-3.1-flash-lite`, given the schema and the object catalog, the compiler and scorer
    doing the rest — scored **1/14 and 3/12 against raw 14/14 and 12/12** (9/14 and 10/12 with the
    run_sql fallback). Four answers were genuinely wrong, seven fills malformed or empty, six
    honest refusals the fallback answered, zero refusals from the algebra.
    ✅ **(b) Not met — `ask.query_objects` stays off**, as recommended for a regression.
    ✅ **(c) PARKED** (recommended, adopted): the compiler and the `/objects` doors stay — they
    are deterministic, measured right when a person fills the query, and ON-3 reads through
    them — and the conversation's tool stays behind its flag. *Reopen only with a set where raw
    FAILS and a fill that fixes the malformed shapes (`object_type` required, `op` an enum,
    `metric` exclusive of `path`); a re-measure where raw is at ceiling can at best tie.*
    ✅ **(d) RETIRED** (recommended, adopted): ON-6 is cancelled on ON-0's falsifier, fired on
    both blocks. No new ontology prose is built toward the prompt. The blocks that already reach
    it are untouched by this decision — removing them (keeping only those a guard cites) is its
    own measured change, not a side effect of cancelling a wave.

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
its *system* gets DS-5's map) · model ids hardcoded anywhere in `aughor/` · a GPU fleet ·
model weights in the repo or installer (Arc MI ships the ledger in the box and adapters as
release artifacts, §3.9) · online/continual learning on live traffic · a ninth definition
store or auto-applied imports (Arc KI reviews everything into the eight stores that exist,
§3.10).

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
