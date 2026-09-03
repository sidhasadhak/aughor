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
| Governance | `govern/` — actions · caps · guardrails · lineage · outbound · disclosure · tags; `security/` — audit · authz · credentials · pii; graduated approval gate → `approval_required` (428) |
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
> **Still unbuilt here:** a UI (`+ Custom MCP` in the connectors catalog and
> the palette's per-server rail rows, §3.7 Phase 1's P2 note), OAuth-authenticated servers
> (the `auth_header` is a single opaque forwarded value, not an auth implementation), and
> non-text tool results — images and embedded resources are dropped rather than flattened,
> deliberately, because a partial answer that looks whole is worse than a missing one.

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

Untouched. User analytics over `session_events`, per-user and per-org quotas, an admin view of
every user's agents/runs/connections, RBAC on the agent plane, and audit of admin access to
user traces. **Risk is policy, not code:** an admin reading a user's prompts is a real question.
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
  ⏳ **Still owed — the authoring UI.** Nothing in the canvas SETS `$as` yet: it is reachable
  through the API and the DS-16 import funnel, not from the binding chip. Until that lands
  this is the arc's own recurring failure (a complete and inert plane), and it is named here
  rather than left to be discovered.
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

**Three of the four verdict doors pin; the fourth cannot, and saying so is the finding.**
`finding_verdicts` (by investigation_id), `chat.feedback` (its `turn_id` IS an
investigation id) and `trace.feedback` (by trace_id) all pin at verdict time.
**`staged_proposals` resolution does not**: that table's `run_id` is a fresh `uuid4()`
minted per tool call (`agent/action_tools.py`), not a `trace_id` or an `investigation_id`,
so it does not join to `session_events` at all — and pinning on the RESOLVER's ambient
trace would pin the wrong run (the human's request, not the agent's). This is the same
missing-reciprocal-key shape MI-1 just fixed for `automation_runs`, and it wants the same
fix — a real join key on the proposal — rather than a plausible-looking pin aimed at the
wrong rows. **Open, and small.**

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
        (spec-deltas in §3.7 Phase 1; DS-1's P1 port-filter + P2 rail remain open)

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
  🆕 §3.8 CANVAS PARITY (2026-09-03, from the user's Langflow comparison) — two halves:
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
                                   carries both. Still unbuilt: OAuth-authenticated servers,
                                   non-text tool results.
  ✅ S1 Qdrant embedded SHIPPED 2026-09-02  (third backend: in-process local mode at
                                   AUGHOR_QDRANT_PATH; one serialized client per path;
                                   three bespoke QdrantClient call sites joined the
                                   seam — §3.6)
  ✅ DS-1 leftovers SHIPPED 2026-09-02  (P1 edge-drop → pre-bound palette filter · P2
                                   Palette·Runs rail — §3.7 Phase 1 ledger; landed into
                                   DS-1R's canvas-first shape, same day)
  ✅ tool_grants column SHIPPED 2026-09-02  (migration 6 + store/create/patch + write-time
                                   roster validation + the editor's grants list; grants
                                   stay PROPOSE-only — §1 limit retired)

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
```

### Loose-end ledger (swept 2026-09-02, verified live — not a band, a debt list)

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
- **Notion + Confluence are built and unreachable** — and the two diagnoses this line carried
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
  ⏳ Two things survive it: **`AgentMap.tsx` has the same missing handler** and was left for a
  separate change, and the fix has **no empirical receipt** — the browser tool cannot drive
  ReactFlow pointer interactions, so a React Profiler trace during a real drag is still owed.
- ~~**The primitive gap**~~ — **CLOSED 2026-09-03** (`e3a56b5c`, #428). Data shaping shipped as
  `$as` on the binding; the conditional-router half was my own false claim and DS-6's `else_of`
  was always the branch (§3.8a). ⏳ Survives it: **nothing in the canvas SETS `$as`** — API and
  the DS-16 import funnel only, not the binding chip.
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
- **Runs rail lists every per-minute `not_fired` tick** — the fired run drowns in scheduler noise.
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

> **Status 2026-09-02: NONE open. All six are decided.** Kept as a register, not a queue —
> each entry records the reasoning so a settled question is not re-litigated, and so no band
> elsewhere in this document can go on reading as blocked once the call has been made. If you
> arrived here looking for what the user still owes, the answer is *nothing*; what remains is
> in the ledger's "keyed on the user" list, and those are credentials and one manual gesture,
> not decisions.

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
release artifacts, §3.9) · online/continual learning on live traffic.

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
